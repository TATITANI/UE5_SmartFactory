"""Isaac Sim과 Unreal 없이 실제 루프백 통신을 검사합니다."""

from __future__ import annotations

import json
from pathlib import Path
import socket
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from factory_core import FactoryController
from unreal_bridge import MAX_COMMANDS_PER_TICK, MAX_FRAME_BYTES, UnrealBridge


class SlowSender:
    """TCP가 일부 데이터만 수락하고 송신 대기 상태가 되는 경우를 재현합니다."""

    def __init__(self, sock):
        self.sock = sock
        self.blocked = False
        self.limit = True

    def send(self, data):
        if self.blocked:
            raise BlockingIOError()
        if self.limit:
            self.blocked = True
            return self.sock.send(data[:7])
        return self.sock.send(data)

    def recv(self, count):
        return self.sock.recv(count)

    def close(self):
        self.sock.close()


class UnrealBridgeTests(unittest.TestCase):
    def setUp(self):
        self.controller = FactoryController()
        self.bridge = UnrealBridge(port=0)
        self.clients = []
        self.buffers = {}
        self.client = self.connect()

    def tearDown(self):
        for client in self.clients:
            client.close()
        self.bridge.close()

    def connect(self):
        client = socket.create_connection((self.bridge.host, self.bridge.port), timeout=1)
        client.setblocking(False)
        self.clients.append(client)
        self.buffers[client] = bytearray()
        self.bridge.pump(self.controller)
        return client

    @staticmethod
    def frame(command, command_id="test-1", **extra):
        return (
            json.dumps(
                {"type": "command", "protocol": 1, "id": command_id, "command": command, **extra}
            )
            + "\n"
        ).encode()

    def receive(self, count=1, client=None):
        client = client or self.client
        deadline = time.monotonic() + 1
        messages = []
        pending = self.buffers[client]
        while time.monotonic() < deadline and len(messages) < count:
            self.bridge.pump(self.controller)
            try:
                data = client.recv(MAX_FRAME_BYTES * 2)
                if not data:
                    break
                pending.extend(data)
            except BlockingIOError:
                pass
            while b"\n" in pending and len(messages) < count:
                end = pending.index(b"\n")
                messages.append(json.loads(pending[:end]))
                del pending[: end + 1]
            if len(messages) < count:
                time.sleep(0.001)
        self.assertEqual(len(messages), count, messages)
        return messages

    def command(self, command, command_id="test-1"):
        self.client.sendall(self.frame(command, command_id))
        return self.receive()[0]

    def test_roundtrip_snapshot_config_and_scene_joints(self):
        self.controller.update(0.5)
        snapshot = self.controller.snapshot()
        snapshot["robot_joint_state"] = {"names": ["base_yaw"], "positions": [0.25]}
        self.assertTrue(self.bridge.publish(self.controller, snapshot, now=1.0))
        message = self.receive()[0]
        self.assertEqual(message["type"], "snapshot")
        self.assertEqual(message["protocol"], 1)
        self.assertEqual(message["session_id"], self.bridge.session_id)
        self.assertEqual(message["sequence"], 1)
        self.assertEqual(message["config"], self.controller.config)
        self.assertEqual(message["snapshot"], snapshot)

    def test_snapshot_rate_uses_wall_time_and_continues_paused(self):
        self.controller.pause()
        self.assertTrue(self.bridge.publish(self.controller, now=10.0))
        first = self.receive()[0]
        self.assertFalse(self.bridge.publish(self.controller, now=10.049))
        self.assertTrue(self.bridge.publish(self.controller, now=10.051))
        second = self.receive()[0]
        self.assertEqual(second["snapshot"], first["snapshot"])
        self.assertGreater(second["sequence"], first["sequence"])

    def test_split_and_coalesced_commands(self):
        frame = self.frame("pause", "one")
        self.client.sendall(frame[:12])
        self.bridge.pump(self.controller)
        self.assertEqual(self.controller.mode, "running")
        self.client.sendall(frame[12:] + self.frame("resume", "two"))
        first, second = self.receive(2)
        self.assertEqual((first["mode"], second["mode"]), ("paused", "running"))
        self.assertTrue(first["accepted"] and second["accepted"])

    def test_emergency_stop_latches_and_reset_stays_frozen(self):
        self.controller.update(1.0)
        ack = self.command("emergency_stop", "stop")
        frozen = self.controller.snapshot()
        self.assertEqual(ack["mode"], "emergency_stopped")
        self.controller.update(100)
        self.assertEqual(self.controller.snapshot(), frozen)
        self.assertFalse(self.command("resume", "start-blocked")["accepted"])
        self.assertEqual(self.command("reset", "reset")["mode"], "paused")
        cleared = self.controller.snapshot()
        self.controller.update(10)
        self.assertEqual(self.controller.snapshot(), cleared)
        self.assertEqual(cleared["simulation_time"], 0)
        self.assertTrue(self.command("resume", "start")["accepted"])
        self.controller.update(0.1)
        self.assertGreater(self.controller.simulation_time, 0)

    def test_duplicate_id_replays_ack_without_reapplying_reset(self):
        first = self.command("reset", "same-id")
        self.controller.resume()
        self.controller.update(2.0)
        second = self.command("reset", "same-id")
        self.assertEqual(first, second)
        self.assertEqual(self.controller.simulation_time, 2.0)
        self.assertEqual(self.controller.mode, "running")

    def test_reconnect_retains_command_id_history_and_current_state(self):
        first = self.command("pause", "persistent-id")
        session = self.bridge.session_id
        self.client.close()
        self.bridge.pump(self.controller)
        self.client = self.connect()
        self.controller.resume()
        self.assertEqual(self.command("pause", "persistent-id"), first)
        self.assertEqual(self.controller.mode, "running")
        self.bridge.publish(self.controller)
        self.assertEqual(self.receive()[0]["session_id"], session)

    def test_invalid_input_cannot_invoke_controller_methods(self):
        invalid = [
            b"not json\n",
            b"\xff\n",
            b"[]\n",
            b'{"x":NaN}\n',
            self.frame("update", "method"),
            self.frame("__class__", "magic"),
            self.frame("pause", "bad-version", protocol=2),
            self.frame("pause", "bool-version", protocol=True),
            self.frame("pause", ""),
            self.frame("pause", "x" * 129),
        ]
        self.client.sendall(b"".join(invalid))
        messages = self.receive(len(invalid))
        self.assertTrue(all(message["accepted"] is False for message in messages))
        self.assertEqual(self.controller.mode, "running")
        self.assertTrue(self.command("pause", "valid")["accepted"])

    def test_oversize_frame_drops_peer_and_allows_reconnect(self):
        # 페이로드가 MAX_FRAME_BYTES이면 마지막 줄바꿈을 넣을 공간이 없습니다.
        self.client.setblocking(True)
        self.client.sendall(b"x" * MAX_FRAME_BYTES)
        self.client.setblocking(False)
        deadline = time.monotonic() + 1
        while self.bridge.client_count and time.monotonic() < deadline:
            self.bridge.pump(self.controller)
            time.sleep(0.001)
        self.assertEqual(self.bridge.client_count, 0)
        self.client = self.connect()
        self.assertTrue(self.command("pause")["accepted"])

    def test_command_work_per_tick_is_bounded(self):
        count = MAX_COMMANDS_PER_TICK + 5
        self.client.sendall(b"".join(self.frame("pause", str(index)) for index in range(count)))
        self.bridge.pump(self.controller)
        self.assertLessEqual(len(self.bridge._acks), MAX_COMMANDS_PER_TICK)
        messages = self.receive(count)
        self.assertEqual(
            [message["id"] for message in messages], [str(index) for index in range(count)]
        )

    def test_slow_client_coalesces_snapshots_and_preserves_ack_framing(self):
        peer = self.bridge._peers[0]
        sender = SlowSender(peer.socket)
        peer.socket = sender
        self.bridge.publish(self.controller, now=1)
        self.client.sendall(self.frame("pause", "during-partial-frame"))
        self.bridge.pump(self.controller)
        for index in range(2, 20):
            self.bridge.publish(self.controller, now=index)
        self.assertLessEqual(len(peer.outgoing), 2)
        sender.limit, sender.blocked = False, False
        messages = self.receive(3)
        self.assertEqual([message["type"] for message in messages], ["snapshot", "ack", "snapshot"])
        self.assertTrue(messages[1]["accepted"])
        self.assertEqual(messages[2]["sequence"], 19)

    def test_bin_full_remains_remotely_resettable(self):
        self.controller.update(self.controller.cycle_duration * self.controller.cycle_capacity + 1)
        self.assertEqual(self.controller.mode, "bin_full")
        self.assertFalse(self.command("resume", "full")["accepted"])
        self.assertEqual(self.command("reset", "clear")["mode"], "paused")
        self.assertTrue(self.command("resume", "run")["accepted"])

    def test_server_is_loopback_only_and_close_is_idempotent(self):
        self.assertEqual(self.bridge.listener.getsockname()[0], "127.0.0.1")
        self.bridge.close()
        self.bridge.close()
        self.bridge.pump(self.controller)
        self.assertFalse(self.bridge.publish(self.controller))

    def test_id_capacity_never_evicts_completed_commands(self):
        import unreal_bridge
        from unittest.mock import patch

        with patch.object(unreal_bridge, "MAX_COMMAND_IDS", 1):
            first = self.command("pause", "retained")
            rejected = self.command("reset", "over-limit")
            self.assertFalse(rejected["accepted"])
            self.assertEqual(rejected["reason"], "command_id_capacity_restart_required")
            self.controller.resume()
            self.assertEqual(self.command("pause", "retained"), first)
            self.assertEqual(self.controller.mode, "running")


if __name__ == "__main__":
    unittest.main()
