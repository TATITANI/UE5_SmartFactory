"""독립적인 네 포트의 동작과 연속적인 컨베이어 속도 변경을 검사합니다."""

import json
import math
from pathlib import Path
import socket
import sys
import time
import unittest
from argparse import Namespace
import tempfile
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from factory_core import FactoryController
from run_factory_multi import CELL_ORIGINS, INITIAL_SPEEDS, MultiFactory, run


class ConveyorSpeedTests(unittest.TestCase):
    def test_mid_transit_change_preserves_position_then_uses_new_speed(self):
        controller = FactoryController()
        controller.update(1.0)
        before = controller.snapshot()
        controller.set_conveyor_speed(0.8)
        after = controller.snapshot()
        self.assertEqual(before["active_product"]["position"], after["active_product"]["position"])
        self.assertEqual(before["simulation_time"], after["simulation_time"])
        self.assertAlmostEqual(before["phase_progress"], after["phase_progress"])
        controller.update(0.5)
        self.assertAlmostEqual(
            controller.snapshot()["active_product"]["position"][0]
            - after["active_product"]["position"][0],
            0.4,
        )

    def test_speed_change_keeps_pause_and_emergency_stop_frozen(self):
        controller = FactoryController()
        controller.update(2.0)
        for mode in ("pause", "emergency_stop"):
            getattr(controller, mode)()
            before = controller.snapshot()
            controller.set_conveyor_speed(0.2)
            controller.update(20)
            after = controller.snapshot()
            for key in ("mode", "active_product", "robot_target", "simulation_time", "counters"):
                self.assertEqual(before[key], after[key])
            self.assertEqual(after["conveyor_speed"], 0)
            self.assertEqual(after["conveyor_speed_setpoint"], 0.2)

    def test_reset_retains_speed_and_remains_paused(self):
        controller = FactoryController()
        controller.set_conveyor_speed(0.65)
        controller.update(0.5)
        controller.reset()
        self.assertEqual(controller.mode, "paused")
        self.assertEqual(controller.snapshot()["conveyor_speed_setpoint"], 0.65)
        controller.resume()
        controller.update(0.5)
        self.assertAlmostEqual(
            controller.snapshot()["active_product"]["position"][0], -1.45 + 0.325
        )

    def test_non_conveying_speed_change_only_affects_future_belt_motion(self):
        controller = FactoryController()
        controller.update(1.7 / 0.35 + 0.2)
        self.assertEqual(controller.state, "approaching")
        before = controller.snapshot()
        controller.set_conveyor_speed(0.1)
        after = controller.snapshot()
        self.assertEqual(before["active_product"], after["active_product"])
        self.assertEqual(before["robot_target"], after["robot_target"])
        self.assertEqual(before["phase_progress"], after["phase_progress"])
        self.assertEqual(after["conveyor_speed"], 0)
        self.assertEqual(after["conveyor_speed_setpoint"], 0.1)

    def test_invalid_values_rejected_without_changing_state(self):
        controller = FactoryController()
        before = controller.snapshot()
        for value in (True, False, None, "0.4", float("nan"), float("inf"), -1, 0, 0.049, 1.001):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    controller.set_conveyor_speed(value)
                self.assertEqual(controller.snapshot(), before)
        for value in (0.05, 1.0):
            self.assertTrue(controller.set_conveyor_speed(value))

    def test_timestep_subdivision_after_speed_change(self):
        whole, split = FactoryController(), FactoryController()
        for controller in (whole, split):
            controller.update(1.2)
            controller.set_conveyor_speed(0.6)
        whole.update(15)
        for _ in range(1500):
            split.update(0.01)
        self.assertEqual(whole.state, split.state)
        self.assertEqual(whole.snapshot()["counters"], split.snapshot()["counters"])
        self.assertLess(
            math.dist(
                whole.snapshot()["robot_target"]["position"],
                split.snapshot()["robot_target"]["position"],
            ),
            1e-9,
        )


class MultiPortFactoryTests(unittest.TestCase):
    def setUp(self):
        self.factory = MultiFactory(base_port=0)
        self.clients = []
        self.buffers = []
        for bridge in self.factory.bridges:
            client = socket.create_connection(("127.0.0.1", bridge.port), timeout=1)
            client.setblocking(False)
            self.clients.append(client)
            self.buffers.append(bytearray())
        self.factory.step(0)

    def tearDown(self):
        for client in self.clients:
            client.close()
        self.factory.close()

    def send(self, index, command, command_id, **extra):
        self.clients[index].sendall(
            (
                json.dumps(
                    {
                        "type": "command",
                        "protocol": 1,
                        "id": command_id,
                        "command": command,
                        **extra,
                    }
                )
                + "\n"
            ).encode()
        )

    def wait_for(self, index, predicate):
        deadline = time.monotonic() + 1
        pending = self.buffers[index]
        while time.monotonic() < deadline:
            self.factory.step(0)
            try:
                pending.extend(self.clients[index].recv(65536))
            except BlockingIOError:
                pass
            while b"\n" in pending:
                end = pending.index(b"\n")
                message = json.loads(pending[:end])
                del pending[: end + 1]
                if predicate(message):
                    return message
            time.sleep(0.001)
        self.fail("Expected bridge frame was not received.")

    def ack(self, index, command_id):
        return self.wait_for(
            index, lambda message: message["type"] == "ack" and message["id"] == command_id
        )

    def test_four_distinct_ports_sessions_and_local_coordinates(self):
        self.assertEqual(len({bridge.port for bridge in self.factory.bridges}), 4)
        self.assertEqual(len({bridge.session_id for bridge in self.factory.bridges}), 4)
        for index in range(4):
            frame = self.wait_for(index, lambda message: message["type"] == "snapshot")
            self.assertEqual(frame["snapshot"]["cell_id"], f"Cell{index + 1:02d}")
            self.assertEqual(frame["snapshot"]["cell_origin_m"], list(CELL_ORIGINS[index]))
            self.assertEqual(frame["snapshot"]["conveyor_speed_setpoint"], INITIAL_SPEEDS[index])
            self.assertEqual(frame["snapshot"]["active_product"]["position"], [-1.45, 0.0, 0.76])
        self.factory.step(1.0)
        positions = [
            controller.snapshot()["active_product"]["position"][0]
            for controller in self.factory.controllers
        ]
        self.assertEqual(len(set(positions)), 4)

    def test_commands_and_speed_changes_are_isolated_by_port(self):
        self.factory.step(1.0)
        self.send(0, "pause", "same-id")
        self.send(1, "emergency_stop", "same-id")
        self.send(2, "set_conveyor_speed", "same-id", value=0.9)
        for index in range(3):
            self.assertTrue(self.ack(index, "same-id")["accepted"])
        before = [controller.snapshot() for controller in self.factory.controllers]
        self.factory.step(0.5)
        after = [controller.snapshot() for controller in self.factory.controllers]
        self.assertEqual(after[0]["active_product"], before[0]["active_product"])
        self.assertEqual(after[1]["active_product"], before[1]["active_product"])
        self.assertAlmostEqual(
            after[2]["active_product"]["position"][0] - before[2]["active_product"]["position"][0],
            0.45,
        )
        self.assertAlmostEqual(
            after[3]["active_product"]["position"][0] - before[3]["active_product"]["position"][0],
            0.15,
        )
        self.assertEqual(after[3]["conveyor_speed_setpoint"], 0.30)

    def test_invalid_and_duplicate_speed_commands_do_not_change_cells(self):
        for index, value in enumerate((True, 0.01, 1.01, "0.4")):
            self.send(index, "set_conveyor_speed", "bad", value=value)
            self.assertFalse(self.ack(index, "bad")["accepted"])
            self.assertEqual(
                self.factory.controllers[index].config["conveyor"]["speed"], INITIAL_SPEEDS[index]
            )
        self.send(0, "set_conveyor_speed", "valid", value=0.8)
        first = self.ack(0, "valid")
        self.send(0, "set_conveyor_speed", "valid", value=0.2)
        self.assertEqual(first, self.ack(0, "valid"))
        self.assertEqual(self.factory.controllers[0].config["conveyor"]["speed"], 0.8)


class GracefulStopFileTests(unittest.TestCase):
    def test_marker_stops_all_cells_and_saves_final_reports(self):
        with tempfile.TemporaryDirectory(prefix="factory-stop-test-") as directory:
            output = Path(directory)
            marker = output / "stop.request"
            args = Namespace(
                config=Path(__file__).resolve().parents[1] / "config" / "factory.json",
                output=output,
                base_port=0,
                headless=True,
                serve=True,
                dry_run=True,
                steps=120,
                fast=False,
                export=False,
                dt=1 / 60,
                stop_file=marker,
            )
            request = threading.Timer(0.15, marker.touch)
            request.start()
            try:
                run(args)
            finally:
                request.join(timeout=1)
            report = json.loads((output / "report.json").read_text(encoding="utf-8"))
            self.assertTrue(report["success"])
            self.assertFalse(report["running"])
            self.assertEqual(report["stop_reason"], "stop_file")
            self.assertLess(report["steps"], args.steps)
            self.assertTrue(marker.is_file())
            self.assertEqual(len(report["cells"]), 4)
            for index, cell in enumerate(report["cells"]):
                final = json.loads(
                    (output / f"cell{index + 1:02d}" / "report.json").read_text(encoding="utf-8")
                )
                self.assertTrue(final["success"])
                self.assertEqual(final["final"], cell["snapshot"])
                port = int(cell["endpoint"].rsplit(":", 1)[1])
                with self.assertRaises(OSError):
                    socket.create_connection(("127.0.0.1", port), timeout=0.1)


if __name__ == "__main__":
    unittest.main()
