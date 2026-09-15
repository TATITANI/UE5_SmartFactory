"""표준 라이브러리만 사용하는 결정적 컨베이어 및 로봇 공정 제어기입니다.

FactoryController(load_config(path))를 생성하고 매 단계 update(dt_seconds)를 호출합니다.
snapshot()은 원본과 분리된 JSON 호환 사전을 반환합니다.
좌표는 미터 단위이며 Z축이 위쪽입니다. 제품 위치는 박스 중심이고 robot_target은
그리퍼 목표입니다. 파지 목표는 제품 중심에서 grasp_offset만큼 위에 있습니다.
도구를 아래로 향하게 하는 자세와 관절 제어는 장면 어댑터가 담당합니다.
설정의 벨트 및 적재함 좌표는 표면 위치입니다.

목표 자세는 이상적인 명령값이며 충돌 또는 파지 피드백이 아닙니다.
Isaac 어댑터가 목표에 IK를 적용합니다. 코어에는 통신이나 ROS 의존성이 없습니다.
4셀 실행에서는 각 셀 좌표를 로컬 좌표로 사용하고 USD 루트에 배치 변환을 적용합니다.
전송 위치는 로컬 좌표를 유지하고 cell_origin_m으로 홀의 배치를 구분합니다.

running 모드에서만 시간이 진행합니다. 일시정지는 자세를 유지하고 비상정지는
초기화까지 잠깁니다. 다음 제품의 적재함이 가득 차면 복귀를 마친 뒤 bin_full로
정지하며 활성 제품은 없습니다. 재개 명령으로 잠금을 해제할 수 없습니다.
reset()은 공정을 비우고 정지하며 reset(start=True)는 운전을 시작합니다.
생성자는 자동으로 운전을 시작합니다."""

from __future__ import annotations

from copy import deepcopy
import json
import math
from pathlib import Path
from typing import Any

PHASES = (
    "conveying",
    "approaching",
    "picking",
    "lifting",
    "transferring",
    "placing",
    "releasing",
    "retracting",
)

DEFAULT_CONFIG: dict[str, Any] = {
    "conveyor": {
        "start": [-1.45, 0.0, 0.72],
        "pickup": [0.25, 0.0, 0.72],
        "speed": 0.35,
    },
    "robot": {
        "base": [0.25, 0.68, 0.72],
        "home": [0.25, 0.33, 1.25],
        "grasp_offset": 0.075,
        "clearance": 0.26,
    },
    "product": {"size": [0.08, 0.08, 0.08], "colors": ["red", "blue"]},
    "bins": {"red": [0.90, 0.40, 0.72], "blue": [0.90, 1.00, 0.72]},
    "placement": {"columns": 3, "rows": 3, "max_layers": 2, "spacing": 0.11},
    "timing": {
        "approaching": 0.8,
        "picking": 0.6,
        "lifting": 0.6,
        "transferring": 1.2,
        "placing": 0.7,
        "releasing": 0.3,
        "retracting": 1.0,
    },
}


def _merge(base: dict[str, Any], overrides: dict[str, Any], prefix: str = "") -> None:
    for key, value in overrides.items():
        name = f"{prefix}{key}"
        if key not in base:
            raise ValueError(f"Unknown configuration key: {name}")
        if isinstance(base[key], dict):
            if not isinstance(value, dict):
                raise ValueError(f"{name} must be an object")
            _merge(base[key], value, name + ".")
        else:
            base[key] = deepcopy(value)


def _number(value: Any, name: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    if not math.isfinite(value) or (positive and value <= 0):
        raise ValueError(f"{name} must be {'positive and ' if positive else ''}finite")
    return float(value)


def _validated_config(overrides: dict[str, Any] | None) -> dict[str, Any]:
    config = deepcopy(DEFAULT_CONFIG)
    if overrides is not None:
        if not isinstance(overrides, dict):
            raise ValueError("Factory configuration must be an object")
        _merge(config, overrides)
    vectors = [
        (config["conveyor"], "start"),
        (config["conveyor"], "pickup"),
        (config["robot"], "base"),
        (config["robot"], "home"),
        (config["product"], "size"),
        *[(config["bins"], color) for color in config["bins"]],
    ]
    for owner, key in vectors:
        value = owner[key]
        if not isinstance(value, (list, tuple)) or len(value) != 3:
            raise ValueError(f"{key} must contain exactly three coordinates")
        owner[key] = [_number(v, key, positive=key == "size") for v in value]
    for owner, key in [
        (config["conveyor"], "speed"),
        (config["robot"], "grasp_offset"),
        (config["robot"], "clearance"),
        (config["placement"], "spacing"),
        *[(config["timing"], phase) for phase in PHASES[1:]],
    ]:
        owner[key] = _number(owner[key], key, positive=True)
    for key in ("columns", "rows", "max_layers"):
        value = config["placement"][key]
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f"placement.{key} must be a positive integer")
    colors = config["product"]["colors"]
    if (
        not isinstance(colors, list)
        or not colors
        or any(not isinstance(color, str) or color not in config["bins"] for color in colors)
    ):
        raise ValueError("product.colors must be a non-empty list of configured bin colors")
    if math.dist(config["conveyor"]["start"], config["conveyor"]["pickup"]) == 0:
        raise ValueError("The conveyor start and pickup must be different")
    if config["placement"]["spacing"] < max(config["product"]["size"][:2]):
        raise ValueError("placement.spacing must be at least the product footprint")
    return config


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    """JSON 설정을 읽고 검증합니다. 경로가 없으면 기본값을 반환합니다."""
    if path is None:
        return _validated_config(None)
    with Path(path).open(encoding="utf-8") as stream:
        return _validated_config(json.load(stream))


def _lerp(start: list[float], end: list[float], fraction: float) -> list[float]:
    return [a + (b - a) * fraction for a, b in zip(start, end)]


class FactoryController:
    """한 번에 제품 하나를 처리하며 지정한 시간에 따라 색상별 적재함을 선택합니다."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = _validated_config(config)
        self.reset(start=True)

    def reset(self, *, start: bool = False) -> None:
        """제품과 카운터 및 정지 잠금을 초기화합니다. 명시적으로 요청하지 않으면 정지합니다."""
        self.mode = "running" if start else "paused"
        self.simulation_time = 0.0
        self._next_id = 1
        self._robot_position = list(self.config["robot"]["home"])
        self._gripper_closed = False
        self._placed: list[dict[str, Any]] = []
        self._active: dict[str, Any] | None = None
        self._counters = {
            "spawned": 0,
            "picked": 0,
            "placed": 0,
            "completed_cycles": 0,
            "by_color": {color: 0 for color in self.config["bins"]},
        }
        self._spawn()

    def pause(self) -> bool:
        """공정을 정지합니다. 비상정지 또는 적재함 잠금이 있으면 False를 반환합니다."""
        if self.mode in ("emergency_stopped", "bin_full"):
            return False
        self.mode = "paused"
        return True

    def resume(self) -> bool:
        """일시정지를 재개합니다. 비상정지와 적재함 잠금은 초기화가 필요합니다."""
        if self.mode in ("emergency_stopped", "bin_full"):
            return False
        self.mode = "running"
        return True

    def emergency_stop(self) -> None:
        """현재 제품과 파지 및 자세를 유지하면서 비상정지를 잠급니다."""
        self.mode = "emergency_stopped"

    def set_conveyor_speed(self, value: float) -> bool:
        """제품 위치와 운전 모드를 유지하면서 m/s 단위 속도를 설정합니다.

        이송 소요 시간이 달라져도 기존 이동 비율을 보존합니다.
        초기화 시 설정 사전을 유지하므로 속도도 유지됩니다."""
        speed = _number(value, "conveyor speed", positive=True)
        if not 0.05 <= speed <= 1.0:
            raise ValueError("Conveyor speed must be in [0.05, 1.0] m/s.")
        if self.state == "conveying":
            progress = self._phase_elapsed / self._phase_duration
            belt = self.config["conveyor"]
            self._phase_duration = math.dist(belt["start"], belt["pickup"]) / speed
            self._phase_elapsed = progress * self._phase_duration
        self.config["conveyor"]["speed"] = speed
        return True

    @property
    def cycle_duration(self) -> float:
        """제품 한 개의 전체 공정에 필요한 명목 시간(초)입니다."""
        belt = self.config["conveyor"]
        return math.dist(belt["start"], belt["pickup"]) / belt["speed"] + sum(
            self.config["timing"].values()
        )

    @property
    def bin_capacity(self) -> int:
        """색상별 적재함에 담을 수 있는 최대 제품 수입니다."""
        placement = self.config["placement"]
        return placement["columns"] * placement["rows"] * placement["max_layers"]

    @property
    def cycle_capacity(self) -> int:
        """초기화 후 다음 적재함이 가득 차기 전 완료할 수 있는 공정 수입니다.

        기본 빨강/파랑 교대 순서는 총 36개를 처리합니다. 사용자 색상 순서에서는
        한 적재함이 먼저 찰 수 있으므로 단순 용량 합계가 아닌 빈도와 순서를 계산합니다."""
        colors = self.config["product"]["colors"]
        first_overflow = []
        for color in set(colors):
            positions = [index for index, value in enumerate(colors) if value == color]
            repeats, remainder = divmod(self.bin_capacity, len(positions))
            first_overflow.append(repeats * len(colors) + positions[remainder])
        return min(first_overflow)

    def _surface_to_center(self, point: list[float]) -> list[float]:
        return [point[0], point[1], point[2] + self.config["product"]["size"][2] / 2]

    def _spawn(self) -> None:
        colors = self.config["product"]["colors"]
        color = colors[(self._next_id - 1) % len(colors)]
        if self._counters["by_color"][color] >= self.bin_capacity:
            # 초기화 직후 또는 복귀 완료 후에만 호출됩니다.
            # 완료 단계와 홈 자세를 유지하고 적재할 수 없는 제품은 생성하지 않습니다.
            # 남은 시간도 컨베이어 이동에 사용하지 않습니다.
            self._active = None
            self.mode = "bin_full"
            return
        self._active = {
            "id": self._next_id,
            "color": color,
            "position": self._surface_to_center(self.config["conveyor"]["start"]),
            "attached": False,
        }
        self._next_id += 1
        self._counters["spawned"] += 1
        placement = self.config["placement"]
        index = self._counters["by_color"][color]
        layer, slot = divmod(index, placement["columns"] * placement["rows"])
        row, column = divmod(slot, placement["columns"])
        target = self._surface_to_center(self.config["bins"][color])
        target[0] += (column - (placement["columns"] - 1) / 2) * placement["spacing"]
        target[1] += (row - (placement["rows"] - 1) / 2) * placement["spacing"]
        target[2] += layer * self.config["product"]["size"][2]
        self._placement_center = target
        self._enter_phase("conveying")

    def _enter_phase(self, phase: str) -> None:
        self.state = phase
        self._phase_elapsed = 0.0
        self._robot_start = list(self._robot_position)
        self._robot_end = list(self._robot_position)
        belt = self.config["conveyor"]
        robot = self.config["robot"]
        pickup = self._surface_to_center(belt["pickup"])
        grasp = [pickup[0], pickup[1], pickup[2] + robot["grasp_offset"]]
        place = list(self._placement_center)
        place[2] += robot["grasp_offset"]
        clearance_z = max(grasp[2], place[2]) + robot["clearance"]
        if phase == "conveying":
            self._phase_duration = math.dist(belt["start"], belt["pickup"]) / belt["speed"]
        else:
            self._phase_duration = self.config["timing"][phase]
        if phase in ("approaching", "lifting"):
            self._robot_end = [grasp[0], grasp[1], clearance_z]
        elif phase == "picking":
            self._robot_end = grasp
        elif phase == "transferring":
            self._robot_end = [place[0], place[1], clearance_z]
        elif phase in ("placing", "releasing"):
            self._robot_end = place
        elif phase == "retracting":
            # 적재함을 벗어나도록 수직 상승한 후 홈 위치로 복귀합니다.
            self._retract_via = [place[0], place[1], max(clearance_z, robot["home"][2])]
            self._robot_end = list(robot["home"])

    def _advance_poses(self) -> None:
        progress = min(1.0, self._phase_elapsed / self._phase_duration)
        if self.state == "conveying":
            assert self._active is not None
            belt = self.config["conveyor"]
            self._active["position"] = _lerp(
                self._surface_to_center(belt["start"]),
                self._surface_to_center(belt["pickup"]),
                progress,
            )
        elif self.state == "retracting":
            if progress <= 0.4:
                amount = progress / 0.4
                self._robot_position = _lerp(
                    self._robot_start, self._retract_via, amount * amount * (3 - 2 * amount)
                )
            else:
                amount = (progress - 0.4) / 0.6
                self._robot_position = _lerp(
                    self._retract_via, self._robot_end, amount * amount * (3 - 2 * amount)
                )
        else:
            smooth = progress * progress * (3 - 2 * progress)
            self._robot_position = _lerp(self._robot_start, self._robot_end, smooth)
        if self._active and self._active["attached"]:
            self._active["position"] = list(self._robot_position)
            self._active["position"][2] -= self.config["robot"]["grasp_offset"]

    def _finish_phase(self) -> None:
        if self.state == "picking":
            assert self._active is not None
            self._active["attached"] = True
            self._gripper_closed = True
            self._counters["picked"] += 1
        elif self.state == "placing":
            assert self._active is not None
            self._active["attached"] = False
            self._active["position"] = list(self._placement_center)
            self._gripper_closed = False
            self._placed.append(deepcopy(self._active))
            self._counters["placed"] += 1
            self._counters["by_color"][self._active["color"]] += 1
        elif self.state == "releasing":
            self._active = None
        elif self.state == "retracting":
            self._counters["completed_cycles"] += 1
            self._spawn()
            return
        self._enter_phase(PHASES[PHASES.index(self.state) + 1])

    def update(self, dt: float) -> dict[str, Any]:
        """0 이상의 시간만큼 진행하고 상태를 반환합니다.

        큰 시간 간격도 단계 경계의 이벤트를 빠짐없이 처리합니다.
        같은 시간을 나눠 갱신해도 부동소수점 오차 범위에서 같은 상태와 자세를 얻습니다.
        정지 중에도 잘못된 dt를 거절하며 실제 시계 시간에는 의존하지 않습니다."""
        remaining = _number(dt, "dt")
        if remaining < 0:
            raise ValueError("dt must be nonnegative")
        if self.mode != "running" or remaining == 0:
            return self.snapshot()
        while remaining > 0 and self.mode == "running":
            available = self._phase_duration - self._phase_elapsed
            step = min(remaining, available)
            self._phase_elapsed += step
            self.simulation_time += step
            remaining = max(0.0, remaining - step)
            # 소수 시간 간격의 반올림 오차로 단계 경계 직전에 멈추지 않도록 허용 오차를 둡니다.
            # 이 오차는 화면의 움직임에 영향을 주지 않을 만큼 작습니다.
            finished = self._phase_duration - self._phase_elapsed <= 1e-12
            if finished:
                self._phase_elapsed = self._phase_duration
            self._advance_poses()
            if finished:
                self._finish_phase()
        return self.snapshot()

    def snapshot(self) -> dict[str, Any]:
        """원본과 분리된 JSON 호환 상태 및 자세 스냅샷을 반환합니다."""
        belt_running = self.mode == "running" and self.state == "conveying"
        pickup = self._surface_to_center(self.config["conveyor"]["pickup"])
        sensor = bool(self._active and math.dist(self._active["position"], pickup) < 0.025)
        return {
            "simulation_time": self.simulation_time,
            "mode": self.mode,
            "state": self.state,
            "phase_progress": self._phase_elapsed / self._phase_duration,
            "conveyor_running": belt_running,
            "conveyor_speed": self.config["conveyor"]["speed"] if belt_running else 0.0,
            "conveyor_speed_setpoint": self.config["conveyor"]["speed"],
            "pickup_sensor": sensor,
            "active_product": deepcopy(self._active),
            "robot_target": {
                "position": list(self._robot_position),
                "gripper_closed": self._gripper_closed,
            },
            "placed_products": deepcopy(self._placed),
            "counters": deepcopy(self._counters),
        }
