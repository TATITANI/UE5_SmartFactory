"""Unreal 디지털 트윈을 위한 루프백 전용 논블로킹 TCP JSONL 통신입니다.

공정 상태 변경은 시뮬레이션 메인 스레드에서만 수행합니다.
제어기 갱신 전에 pump를 호출하고 장면 갱신 후 완성된 상태를 publish합니다.
ROS, Isaac, Unreal 및 외부 라이브러리에 의존하지 않습니다."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import json
import socket
import time
from typing import Any
import uuid

PROTOCOL = 1
MAX_FRAME_BYTES = 64 * 1024  # 마지막 줄바꿈을 포함한 최대 메시지 크기입니다.
MAX_CLIENTS = 4
MAX_COMMANDS_PER_TICK = 16
MAX_PENDING_ACKS = 64
MAX_COMMAND_IDS = 4096
SNAPSHOT_INTERVAL = 1.0 / 20.0
COMMANDS = frozenset(("resume", "pause", "emergency_stop", "reset", "set_conveyor_speed"))


@dataclass
class _Peer:
    socket: socket.socket
    received: bytearray = field(default_factory=bytearray)
    outgoing: deque = field(default_factory=deque)
    sending: bytes = b""
    offset: int = 0
    sending_kind: str = ""


class UnrealBridge:
    """시뮬레이션 스레드를 막지 않고 로컬 클라이언트 최대 네 개에 응답합니다.

    완료한 명령 ID는 재접속 후에도 세션 동안 유지합니다. 4096개를 사용하면
    재시작 전까지 신규 명령은 거절하지만 기존 응답은 다시 반환할 수 있습니다.
    느린 클라이언트에는 미전송 상태 한 개와 응답 최대 64개를 유지합니다.
    부분 전송 중인 프레임을 끝낸 후 다음 프레임을 보냅니다."""

    def __init__(self, port: int = 9847):
        if isinstance(port, bool) or not isinstance(port, int) or not 0 <= port <= 65535:
            raise ValueError("Bridge port must be an integer in [0, 65535].")
        self.host = "127.0.0.1"
        self.session_id = str(uuid.uuid4())
        self.sequence = 0
        self._next_snapshot = 0.0
        self._closed = False
        self._peers: list[_Peer] = []
        self._acks: dict[str, dict[str, Any]] = {}
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            # Windows에서 중복 리스너를 허용하는 SO_REUSEADDR는 사용하지 않습니다.
            # 다른 시뮬레이터가 포트를 점유하면 바인딩에 실패해야 합니다.
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            self.listener.bind((self.host, port))
            self.listener.listen(MAX_CLIENTS)
            self.listener.setblocking(False)
            self.port = self.listener.getsockname()[1]
        except Exception:
            self.listener.close()
            raise
        print(
            f"UNREAL_BRIDGE_LISTENING {self.host}:{self.port} protocol={PROTOCOL} "
            f"session_id={self.session_id}",
            flush=True,
        )

    @property
    def client_count(self) -> int:
        return len(self._peers)

    def _drop(self, peer: _Peer, reason: str) -> None:
        peer.socket.close()
        if peer in self._peers:
            self._peers.remove(peer)
        print(f"UNREAL_BRIDGE_DISCONNECTED reason={reason}", flush=True)

    def _accept(self) -> None:
        for _ in range(MAX_CLIENTS):
            try:
                connection, address = self.listener.accept()
            except BlockingIOError:
                break
            if address[0] != self.host or len(self._peers) >= MAX_CLIENTS:
                connection.close()
                continue
            connection.setblocking(False)
            connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self._peers.append(_Peer(connection))
            # 재접속 클라이언트에는 다음 전송에서 최신 상태를 제공합니다.
            self._next_snapshot = 0.0
            print(f"UNREAL_BRIDGE_CONNECTED clients={len(self._peers)}", flush=True)

    @staticmethod
    def _encode(message: dict[str, Any]) -> bytes:
        frame = (
            json.dumps(message, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n"
        ).encode("utf-8")
        if len(frame) > MAX_FRAME_BYTES:
            raise ValueError("Bridge frame exceeds 64 KiB.")
        return frame

    def _queue(self, peer: _Peer, kind: str, frame: bytes) -> bool:
        if kind == "snapshot":
            peer.outgoing = deque((k, v) for k, v in peer.outgoing if k != "snapshot")
        elif sum(k == "ack" for k, _ in peer.outgoing) >= MAX_PENDING_ACKS:
            self._drop(peer, "ack_backpressure")
            return False
        peer.outgoing.append((kind, frame))
        return True

    def _flush(self, peer: _Peer) -> None:
        # 클라이언트가 계속 읽더라도 한 번의 전송 작업량을 제한합니다.
        allowance = MAX_FRAME_BYTES * 2
        while allowance > 0:
            if not peer.sending:
                if not peer.outgoing:
                    return
                peer.sending_kind, peer.sending = peer.outgoing.popleft()
                peer.offset = 0
            try:
                count = peer.socket.send(peer.sending[peer.offset : peer.offset + allowance])
            except BlockingIOError:
                return
            except OSError:
                self._drop(peer, "send_failed")
                return
            if count == 0:
                self._drop(peer, "send_closed")
                return
            allowance -= count
            peer.offset += count
            if peer.offset == len(peer.sending):
                peer.sending = b""
                peer.offset = 0

    def _command(self, message: Any, controller: Any) -> dict[str, Any]:
        valid_object = isinstance(message, dict)
        command_id = message.get("id") if valid_object else None
        command = message.get("command") if valid_object else None
        valid_id = isinstance(command_id, str) and 0 < len(command_id) <= 128
        valid_command = isinstance(command, str) and len(command) <= 64
        ack = {
            "type": "ack",
            "protocol": PROTOCOL,
            "id": command_id if valid_id else "",
            "command": command if valid_command else "",
            "accepted": False,
            "mode": controller.mode,
            "reason": "invalid_command",
        }
        if not valid_object or not valid_id or not valid_command:
            return ack
        if (
            message.get("type") != "command"
            or type(message.get("protocol")) is not int
            or message["protocol"] != PROTOCOL
        ):
            ack["reason"] = "unsupported_envelope"
            return ack
        # 같은 ID는 요청 내용과 관계없이 최초 처리 결과를 반환합니다.
        # 재접속 후 초기화 또는 운전 명령이 중복 실행되는 것을 방지합니다.
        if command_id in self._acks:
            return self._acks[command_id]
        if len(self._acks) >= MAX_COMMAND_IDS:
            ack["reason"] = "command_id_capacity_restart_required"
            return ack
        if command not in COMMANDS:
            ack["reason"] = "unknown_command"
        else:
            try:
                result = (
                    controller.set_conveyor_speed(message.get("value"))
                    if command == "set_conveyor_speed"
                    else getattr(controller, command)()
                )
            except (ValueError, TypeError):
                ack["reason"] = "invalid_speed_range_0.05_to_1.0"
            else:
                ack["accepted"] = result is not False
                ack["reason"] = "applied" if ack["accepted"] else "reset_required"
            ack["mode"] = controller.mode
            print(
                f"UNREAL_BRIDGE_COMMAND id={json.dumps(command_id)} command={command} "
                f"accepted={ack['accepted']} mode={controller.mode}",
                flush=True,
            )
        self._acks[command_id] = ack
        return ack

    def pump(self, controller: Any) -> None:
        """접속과 명령을 수신하고 호출 스레드에서 실행한 뒤 응답을 전송합니다."""
        if self._closed:
            return
        self._accept()
        # 각 클라이언트의 처리량을 제한하여 과도한 상태 요청 때문에
        # 다른 클라이언트의 비상정지 명령이 지연되지 않게 합니다.
        quota = max(1, MAX_COMMANDS_PER_TICK // max(1, len(self._peers)))
        for peer in list(self._peers):
            try:
                # 완성된 메시지가 대기 중이어도 수신 버퍼 크기를 제한합니다.
                if len(peer.received) < MAX_FRAME_BYTES:
                    incoming = peer.socket.recv(MAX_FRAME_BYTES)
                    if not incoming:
                        self._drop(peer, "client_closed")
                        continue
                    peer.received.extend(incoming)
            except BlockingIOError:
                pass
            except OSError:
                self._drop(peer, "receive_failed")
                continue
            for _ in range(quota):
                end = peer.received.find(b"\n")
                if end < 0:
                    if len(peer.received) >= MAX_FRAME_BYTES:
                        self._drop(peer, "frame_too_large")
                    break
                if end + 1 > MAX_FRAME_BYTES:
                    self._drop(peer, "frame_too_large")
                    break
                line = bytes(peer.received[:end])
                del peer.received[: end + 1]
                try:
                    message = json.loads(
                        line.decode("utf-8"),
                        parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
                    )
                except (ValueError, UnicodeError, RecursionError):
                    ack = {
                        "type": "ack",
                        "protocol": PROTOCOL,
                        "id": "",
                        "command": "",
                        "accepted": False,
                        "mode": controller.mode,
                        "reason": "invalid_json",
                    }
                else:
                    ack = self._command(message, controller)
                if not self._queue(peer, "ack", self._encode(ack)):
                    break
            if peer in self._peers:
                self._flush(peer)

    def publish(
        self, controller: Any, snapshot: dict[str, Any] | None = None, *, now: float | None = None
    ) -> bool:
        """단조 증가 시계를 기준으로 초당 최대 20개 상태를 전송합니다.

        robot_joint_state를 포함하려면 장면 계산을 마친 스냅샷을 전달합니다.
        밀린 상태는 쌓지 않고 최신 상태로 교체합니다."""
        if self._closed:
            return False
        stamp = time.monotonic() if now is None else now
        if stamp < self._next_snapshot:
            return False
        self._next_snapshot = stamp + SNAPSHOT_INTERVAL
        self.sequence += 1
        if not self._peers:
            return False
        frame = self._encode(
            {
                "type": "snapshot",
                "protocol": PROTOCOL,
                "session_id": self.session_id,
                "sequence": self.sequence,
                "config": controller.config,
                "snapshot": controller.snapshot() if snapshot is None else snapshot,
            }
        )
        for peer in list(self._peers):
            self._queue(peer, "snapshot", frame)
            self._flush(peer)
        return True

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for peer in list(self._peers):
            self._drop(peer, "server_shutdown")
        self.listener.close()
        print("UNREAL_BRIDGE_CLOSED", flush=True)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
