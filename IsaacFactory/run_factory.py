"""Isaac Sim 단독 공정 실행기입니다. 앱 시작 후 Omniverse 모듈을 가져옵니다."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parent


def arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "config" / "factory.json")
    parser.add_argument("--output", type=Path, default=ROOT / "outputs")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument(
        "--dry-run", action="store_true", help="Run the controller without Isaac Sim."
    )
    parser.add_argument(
        "--steps", type=int, default=0, help="Stop after this many updates; 0 is unlimited."
    )
    parser.add_argument(
        "--cycles", type=int, default=0, help="Stop after this many sorted parts; 0 is unlimited."
    )
    parser.add_argument(
        "--fast", action="store_true", help="Do not pace updates to wall-clock time."
    )
    parser.add_argument(
        "--capture", action="store_true", help="Capture a PNG viewport near the end of a run."
    )
    parser.add_argument("--export", action="store_true", help="Export a reusable USD scene.")
    parser.add_argument(
        "--unreal-bridge", action="store_true", help="Serve Unreal via loopback TCP JSONL (no ROS)."
    )
    parser.add_argument(
        "--bridge-port", type=int, default=9847, help="Loopback bridge port (default: 9847)."
    )
    parser.add_argument(
        "--serve",
        action="store_true",
        help="Keep the simulator running for remote operations; explicit steps/cycles still stop it.",
    )
    parser.add_argument("--dt", type=float, default=1.0 / 60.0)
    args = parser.parse_args()
    if args.steps < 0 or args.cycles < 0 or not 0 < args.dt <= 0.1:
        parser.error("steps/cycles must be nonnegative; dt must be in (0, 0.1].")
    if not 1 <= args.bridge_port <= 65535:
        parser.error("bridge-port must be in [1, 65535].")
    if args.dry_run and not args.serve and not args.steps and not args.cycles:
        args.cycles = 6
    return args


class Recorder:
    def __init__(self, directory):
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)
        self.stream = (directory / "telemetry.jsonl").open("w", encoding="utf-8")
        self.previous = None
        self.last_time = -1.0
        self.events = 0

    def write(self, snapshot, force=False):
        stamp = snapshot["simulation_time"]
        key = (snapshot["mode"], snapshot["state"], snapshot["counters"]["placed"])
        if force or key != self.previous or stamp - self.last_time >= 0.5:
            self.stream.write(json.dumps(snapshot, ensure_ascii=False) + "\n")
            self.stream.flush()
            self.previous, self.last_time = key, stamp
            self.events += 1

    def close(self, snapshot, steps, elapsed, render_mode, extra=None):
        self.write(snapshot, force=True)
        self.stream.close()
        report = {
            "isaac_sim": "4.5.0" if render_mode != "controller-only" else None,
            "mode": render_mode,
            "ros2_enabled": False,
            "model": "kinematic arm with analytical IK and ideal product attachment",
            "steps": steps,
            "wall_seconds": round(elapsed, 3),
            "telemetry_records": self.events,
            "final": snapshot,
            **(extra or {}),
        }
        (self.directory / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print("FACTORY_REPORT " + json.dumps(report), flush=True)


class FactoryPanel:
    """Isaac 내부 운전 패널입니다. 모든 명령은 동일한 제어기 경계를 사용합니다."""

    def __init__(self, controller, export_callback):
        import omni.ui as ui

        self.controller = controller
        self.ui = ui
        self.window = ui.Window("Factory Operations", width=350, height=620)
        self.labels = {}
        style = {
            "Window": {"background_color": 0xFF24201A},
            "Label": {"color": 0xFFE7E5DF, "font_size": 16},
            "Button": {"background_color": 0xFF554732, "margin": 3, "border_radius": 4},
            "Button:hovered": {"background_color": 0xFF776C49},
        }
        with self.window.frame:
            with ui.VStack(spacing=9, style=style):
                ui.Spacer(height=4)
                ui.Label(
                    "CELL 01 / SMART FACTORY",
                    style={"font_size": 23, "color": 0xFFE8C154},
                    height=30,
                )
                ui.Label("Conveyor + robotic color sorting", height=24)
                ui.Separator(height=4)
                for key in ("mode", "state", "production", "bins", "sensor", "clock"):
                    self.labels[key] = ui.Label("", height=25)
                with ui.HStack(height=38):
                    ui.Button("RUN / RESUME", clicked_fn=controller.resume)
                    ui.Button("PAUSE", clicked_fn=controller.pause)
                ui.Button(
                    "EMERGENCY STOP",
                    height=42,
                    style={"background_color": 0xFF3234A7},
                    clicked_fn=controller.emergency_stop,
                )
                with ui.HStack(height=36):
                    ui.Button("RESET CELL", clicked_fn=self.reset)
                    ui.Button("EXPORT USD", clicked_fn=export_callback)
                ui.Label(
                    "Reset clears the stop latch. Press RUN to restart.",
                    height=35,
                    word_wrap=True,
                    style={"font_size": 13},
                )
                ui.Separator(height=4)
                ui.Label(
                    "Kinematic process demo / ideal grasp\nROS 2: disabled",
                    height=38,
                    word_wrap=True,
                    style={"font_size": 13, "color": 0xFFBAB3A9},
                )
                ui.Spacer()
        self.update(controller.snapshot())

    def reset(self):
        self.controller.reset()

    def update(self, snapshot):
        counts = snapshot["counters"]
        self.labels["mode"].text = "STATUS     " + snapshot["mode"].upper()
        self.labels["state"].text = "PROCESS   " + snapshot["state"].replace("_", " ").upper()
        self.labels["production"].text = f"SORTED     {counts['placed']:04d} parts"
        self.labels["bins"].text = (
            f"RED   {counts['by_color'].get('red', 0):03d}       BLUE   {counts['by_color'].get('blue', 0):03d}"
        )
        self.labels["sensor"].text = "BELT         " + (
            "MOVING" if snapshot["conveyor_running"] else "STOPPED"
        )
        stamp = snapshot["simulation_time"]
        self.labels["clock"].text = f"SIM TIME   {stamp:7.1f} s"


def run(args):
    from factory_core import FactoryController, load_config

    controller = FactoryController(load_config(args.config))
    if args.headless and not args.serve and not args.steps and not args.cycles:
        args.cycles = controller.cycle_capacity
    if args.cycles > controller.cycle_capacity:
        raise ValueError(
            f"Requested cycles exceed configured bin capacity ({controller.cycle_capacity})."
        )
    app = None
    panel = None
    scene = None
    stage = None
    bridge = None
    recorder = Recorder(args.output)
    steps = 0
    started = time.perf_counter()
    capture_task = None
    capture_ok = False
    captured_once = False
    disabled_ros = []
    success = False
    try:
        if not args.dry_run:
            renderless_backend = args.headless and args.serve and not args.capture
            os.environ["OMNI_KIT_ACCEPT_EULA"] = "YES"
            os.environ["OMNI_KIT_DISABLE_TELEMETRY"] = "1"
            from isaacsim import SimulationApp

            app = SimulationApp(
                {
                    "headless": args.headless,
                    "width": 320 if renderless_backend else 1280,
                    "height": 200 if renderless_backend else 800,
                    "create_new_stage": not renderless_backend,
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
            import carb
            import omni.kit.app
            import omni.usd
            from factory_scene import FactoryScene
            from omni.kit.viewport.utility import get_active_viewport

            viewport = get_active_viewport()
            if renderless_backend:
                if viewport:
                    viewport.updates_enabled = False
                print(
                    "FACTORY_BACKEND: viewport rendering disabled; USD scene and IK remain active.",
                    flush=True,
                )
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
                    raise RuntimeError(f"ROS extension unexpectedly enabled: {extension}")
                disabled_ros.append(extension)
            settings = carb.settings.get_settings()
            settings.set("/rtx/post/dlss/execMode", 0)
            settings.set("/rtx/sceneDb/ambientLightIntensity", 0.2)
            context = omni.usd.get_context()
            context.new_stage()
            stage = context.get_stage()
            scene = FactoryScene(stage, controller.config)
            app.reset_render_settings()
            viewport = get_active_viewport()
            if viewport:
                viewport.camera_path = scene.camera_path
                viewport.set_texture_resolution((320, 200) if renderless_backend else (1280, 800))

            def export_scene():
                path = args.output / "factory.usda"
                stage.GetRootLayer().Export(str(path))
                print("USD_EXPORTED " + str(path), flush=True)

            if not args.headless:
                panel = FactoryPanel(controller, export_scene)
            scene.update(controller.snapshot())
            for _ in range(3 if renderless_backend else 30):
                app.update()
            if args.export:
                export_scene()
            print("FACTORY_READY: Cell initialized, ROS bridges disabled.", flush=True)
        else:
            print("FACTORY_READY: Controller-only validation.", flush=True)

        if args.unreal_bridge:
            from unreal_bridge import UnrealBridge

            bridge = UnrealBridge(args.bridge_port)

        # 고정된 시뮬레이션 시간 간격을 사용하여 렌더 지연이 공정 시간을 바꾸지 않게 합니다.
        while app is None or app.is_running():
            frame_start = time.perf_counter()
            if bridge:
                bridge.pump(controller)
            controller.update(args.dt)
            snapshot = controller.snapshot()
            if scene:
                scene.update(snapshot)
                snapshot["robot_joint_state"] = scene.joint_state
            if panel:
                panel.update(snapshot)
            if bridge:
                bridge.publish(controller, snapshot)
            recorder.write(snapshot)
            if app:
                app.update()
            steps += 1
            if args.capture and app and not captured_once and snapshot["counters"]["placed"] >= 2:
                from omni.kit.viewport.utility import capture_viewport_to_file, get_active_viewport

                helper = capture_viewport_to_file(
                    get_active_viewport(), str(args.output / "factory.png")
                )
                capture_task = asyncio.ensure_future(helper.wait_for_result())
                captured_once = True
            if args.steps and steps >= args.steps:
                break
            if args.cycles and snapshot["counters"]["completed_cycles"] >= args.cycles:
                break
            if args.headless and not args.serve and snapshot["mode"] == "bin_full":
                break
            if not args.fast and (not args.dry_run or args.serve):
                remaining = args.dt - (time.perf_counter() - frame_start)
                if remaining > 0:
                    time.sleep(remaining)

        if app and args.capture and not captured_once:
            from omni.kit.viewport.utility import capture_viewport_to_file, get_active_viewport

            helper = capture_viewport_to_file(
                get_active_viewport(), str(args.output / "factory.png")
            )
            capture_task = asyncio.ensure_future(helper.wait_for_result())
        if app and capture_task:
            deadline = time.perf_counter() + 30.0
            while not capture_task.done() and time.perf_counter() < deadline and app.is_running():
                app.update()
            if capture_task.done():
                capture_task.result()
                capture_ok = (args.output / "factory.png").is_file()
            if not capture_ok:
                raise RuntimeError("Viewport capture did not complete.")
        if stage and args.export:
            stage.GetRootLayer().Export(str(args.output / "factory.usda"))
        success = True
    finally:
        mode = (
            "controller-only" if args.dry_run else ("headless" if args.headless else "interactive")
        )
        final_snapshot = controller.snapshot()
        if scene:
            final_snapshot["robot_joint_state"] = scene.joint_state
        try:
            recorder.close(
                final_snapshot,
                steps,
                time.perf_counter() - started,
                mode,
                {
                    "success": success,
                    "capture_ok": capture_ok,
                    "disabled_ros_extensions": disabled_ros,
                    "unreal_bridge": {
                        "enabled": bridge is not None,
                        "endpoint": f"{bridge.host}:{bridge.port}" if bridge else None,
                        "protocol": 1 if bridge else None,
                        "session_id": bridge.session_id if bridge else None,
                        "snapshot_sequence": bridge.sequence if bridge else 0,
                    },
                },
            )
        finally:
            if bridge:
                bridge.close()
            if app:
                app.close()


if __name__ == "__main__":
    run(arguments())
