"""하나의 Isaac Sim에서 ROS 없이 독립 작업 셀 네 개를 실행합니다.

루프백 포트마다 프로토콜 1과 셀 로컬 미터 좌표를 사용합니다.
USD 루트와 Unreal 액터의 변환으로 홀 안에 셀을 배치합니다."""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import time

from factory_core import FactoryController, load_config
from unreal_bridge import UnrealBridge

ROOT = Path(__file__).resolve().parent
INITIAL_SPEEDS = (0.25, 0.35, 0.45, 0.30)
CELL_ORIGINS = ((-8.0, 4.5, 0.0), (0.0, 4.5, 0.0), (8.0, 4.5, 0.0), (0.0, -4.5, 0.0))


class MultiFactory:
    """메인 스레드에서 제어기와 통신을 관리하며 소켓 테스트에서도 사용합니다."""

    def __init__(self, config=None, *, base_port=9847):
        self.controllers = [FactoryController(deepcopy(config)) for _ in INITIAL_SPEEDS]
        for controller, speed in zip(self.controllers, INITIAL_SPEEDS):
            controller.set_conveyor_speed(speed)
        self.scenes = [None] * len(self.controllers)
        self.bridges = []
        try:
            for index in range(len(self.controllers)):
                self.bridges.append(UnrealBridge(base_port + index if base_port else 0))
        except Exception:
            self.close()
            raise

    def snapshot(self, index):
        snapshot = self.controllers[index].snapshot()
        snapshot["cell_id"] = f"Cell{index + 1:02d}"
        snapshot["cell_origin_m"] = list(CELL_ORIGINS[index])
        scene = self.scenes[index]
        if scene is not None:
            snapshot["robot_joint_state"] = deepcopy(scene.joint_state)
        return snapshot

    def step(self, dt):
        snapshots = []
        for index, (controller, bridge, scene) in enumerate(
            zip(self.controllers, self.bridges, self.scenes)
        ):
            bridge.pump(controller)
            controller.update(dt)
            if scene is not None:
                scene.update(controller.snapshot())
            snapshot = self.snapshot(index)
            bridge.publish(controller, snapshot)
            snapshots.append(snapshot)
        return snapshots

    def close(self):
        for bridge in self.bridges:
            bridge.close()


def arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "config" / "factory.json")
    parser.add_argument("--output", type=Path, default=ROOT / "outputs" / "unreal-multi")
    parser.add_argument("--base-port", type=int, default=9847)
    parser.add_argument("--headless", action="store_true")
    parser.add_argument(
        "--serve",
        action="store_true",
        help="Keep all cells available at bin-full; explicit --steps still stops.",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Controller and socket validation without Isaac Sim."
    )
    parser.add_argument(
        "--steps", type=int, default=0, help="Bounded update count; 0 keeps running."
    )
    parser.add_argument("--fast", action="store_true", help="Disable wall-clock pacing.")
    parser.add_argument(
        "--export",
        action="store_true",
        help="Save all four Isaac USD cells at startup and shutdown.",
    )
    parser.add_argument(
        "--stop-file",
        type=Path,
        help="Gracefully save and exit when this absolute file path exists; the marker is preserved.",
    )
    parser.add_argument("--dt", type=float, default=1.0 / 60.0)
    args = parser.parse_args()
    if not 1 <= args.base_port <= 65532 or args.steps < 0 or not 0 < args.dt <= 0.1:
        parser.error("base-port must be 1..65532, steps nonnegative, and dt in (0, 0.1].")
    if args.stop_file is not None and not args.stop_file.is_absolute():
        parser.error("stop-file must be an absolute file path.")
    return args


def run(args):
    from run_factory import Recorder

    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    config = load_config(args.config)
    app = None
    stage = None
    factory = None
    recorders = []
    disabled_ros = []
    started = time.perf_counter()
    steps = 0
    success = False
    stop_reason = None
    report_path = args.output / "report.json"
    usd_path = args.output / "factory_hall.usda"

    def report(final=False):
        value = {
            "success": success if final else None,
            "running": not final,
            "isaac_sim": None if args.dry_run else "4.5.0",
            "ros2_enabled": False,
            "model": "Four independent kinematic process cells with ideal product attachment",
            "cell_count": 4,
            "steps": steps,
            "wall_seconds": round(time.perf_counter() - started, 3),
            "disabled_ros_extensions": disabled_ros,
            "stop_reason": stop_reason,
            "stop_file": str(args.stop_file) if args.stop_file else None,
            "usd_scene": str(usd_path) if stage is not None and args.export else None,
            "cells": [],
        }
        if factory:
            for index, bridge in enumerate(factory.bridges):
                value["cells"].append(
                    {
                        "cell_id": f"Cell{index + 1:02d}",
                        "endpoint": f"127.0.0.1:{bridge.port}",
                        "session_id": bridge.session_id,
                        "sequence": bridge.sequence,
                        "origin_m": list(CELL_ORIGINS[index]),
                        "snapshot": factory.snapshot(index),
                    }
                )
        temporary = report_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(value, indent=2), encoding="utf-8")
        temporary.replace(report_path)
        return value

    try:
        if not args.dry_run:
            os.environ["OMNI_KIT_ACCEPT_EULA"] = "YES"
            os.environ["OMNI_KIT_DISABLE_TELEMETRY"] = "1"
            from isaacsim import SimulationApp

            renderless = args.headless and args.serve
            app = SimulationApp(
                {
                    "headless": args.headless,
                    "width": 320 if renderless else 1280,
                    "height": 200 if renderless else 800,
                    "create_new_stage": not renderless,
                    "window_width": 1600,
                    "window_height": 900,
                    "renderer": "RaytracedLighting",
                    "anti_aliasing": 2,
                    "samples_per_pixel_per_frame": 1,
                    "multi_gpu": False,
                    "sync_loads": True,
                    "extra_args": [
                        "--/isaac/startup/ros_bridge_extension=",
                        "--/app/extensions/excluded/0=isaacsim.ros2.bridge",
                        "--/app/extensions/excluded/1=isaacsim.ros1.bridge",
                    ],
                }
            )
            import omni.kit.app
            import omni.usd
            from factory_scene import FactoryScene
            from omni.kit.viewport.utility import get_active_viewport

            viewport = get_active_viewport()
            if renderless and viewport:
                viewport.updates_enabled = False
            manager = omni.kit.app.get_app().get_extension_manager()
            for extension in (
                "isaacsim.ros2.bridge",
                "isaacsim.ros1.bridge",
                "omni.isaac.ros2_bridge",
                "omni.isaac.ros_bridge",
            ):
                if manager.is_extension_enabled(extension):
                    manager.set_extension_enabled_immediate(extension, False)
                if manager.is_extension_enabled(extension):
                    raise RuntimeError("ROS bridge unexpectedly enabled: " + extension)
                disabled_ros.append(extension)
            context = omni.usd.get_context()
            context.new_stage()
            stage = context.get_stage()

        # SimulationApp이 준비된 다음에 포트를 엽니다.
        # 사용 중인 다른 프로그램의 포트를 종료하거나 빼앗지 않습니다.
        factory = MultiFactory(config, base_port=args.base_port)
        if stage is not None:
            for index, controller in enumerate(factory.controllers):
                factory.scenes[index] = FactoryScene(
                    stage,
                    controller.config,
                    root_path=f"/World/FactoryCell{index + 1:02d}",
                    origin=CELL_ORIGINS[index],
                    lighting=index == 0,
                )
                factory.scenes[index].update(controller.snapshot())
            viewport = get_active_viewport()
            if viewport:
                viewport.camera_path = factory.scenes[0].camera_path
                viewport.set_texture_resolution((320, 200) if renderless else (1280, 800))
                if renderless:
                    viewport.updates_enabled = False
            for _ in range(3 if renderless else 30):
                app.update()
            if args.export:
                stage.GetRootLayer().Export(str(usd_path))
        for index in range(4):
            recorders.append(Recorder(args.output / f"cell{index + 1:02d}"))
        print(
            "FACTORY_MULTI_READY "
            + json.dumps(
                {
                    "cells": 4,
                    "ports": [bridge.port for bridge in factory.bridges],
                    "isaac_scene": stage is not None,
                    "ros2_enabled": False,
                }
            ),
            flush=True,
        )
        next_checkpoint = 0.0
        while app is None or app.is_running():
            if args.stop_file is not None and args.stop_file.is_file():
                stop_reason = "stop_file"
                print("FACTORY_MULTI_STOP_REQUEST " + str(args.stop_file), flush=True)
                break
            frame_start = time.perf_counter()
            snapshots = factory.step(args.dt)
            for recorder, snapshot in zip(recorders, snapshots):
                recorder.write(snapshot)
            if app:
                app.update()
            steps += 1
            if frame_start >= next_checkpoint:
                report()
                next_checkpoint = frame_start + 2.0
            if args.steps and steps >= args.steps:
                stop_reason = "steps_complete"
                break
            if not args.serve and all(snapshot["mode"] == "bin_full" for snapshot in snapshots):
                stop_reason = "all_bins_full"
                break
            if not args.fast:
                remaining = args.dt - (time.perf_counter() - frame_start)
                if remaining > 0:
                    time.sleep(remaining)
        success = True
        if stop_reason is None:
            stop_reason = "application_closed"
    except KeyboardInterrupt:
        # 사용자가 중단해도 최종 장면과 공정 기록을 저장합니다.
        success = True
        stop_reason = "keyboard_interrupt"
    except Exception:
        # SimulationApp.close가 예외 처리 전에 Python을 종료할 수 있습니다.
        # 종료 전에 실제 시작 실패 원인을 기록합니다.
        import traceback

        traceback.print_exc()
        raise
    finally:
        try:
            if stage is not None and args.export:
                stage.GetRootLayer().Export(str(usd_path))
            if factory:
                for index, recorder in enumerate(recorders):
                    recorder.close(
                        factory.snapshot(index),
                        steps,
                        time.perf_counter() - started,
                        (
                            "controller-only"
                            if args.dry_run
                            else ("headless" if args.headless else "interactive")
                        ),
                        {
                            "success": success,
                            "cell_id": f"Cell{index + 1:02d}",
                            "bridge_port": factory.bridges[index].port,
                            "disabled_ros_extensions": disabled_ros,
                        },
                    )
            final_report = report(final=True)
            print(
                "FACTORY_MULTI_REPORT "
                + json.dumps(
                    {"success": final_report["success"], "path": str(report_path), "steps": steps}
                ),
                flush=True,
            )
        finally:
            if factory:
                factory.close()
            if app:
                app.close()


if __name__ == "__main__":
    run(arguments())
