"""IsaacFactory 폴더에서 python -m unittest discover -s tests -v로 실행합니다."""

import json
import math
from pathlib import Path
import random
import unittest

from factory_core import DEFAULT_CONFIG, FactoryController, load_config


class FactoryControllerTests(unittest.TestCase):
    def assertSnapshotEqual(self, first, second):
        if isinstance(first, dict):
            self.assertEqual(first.keys(), second.keys())
            for key in first:
                self.assertSnapshotEqual(first[key], second[key])
        elif isinstance(first, list):
            self.assertEqual(len(first), len(second))
            for a, b in zip(first, second):
                self.assertSnapshotEqual(a, b)
        elif isinstance(first, float):
            self.assertAlmostEqual(first, second, places=8)
        else:
            self.assertEqual(first, second)

    def test_repeated_cycles_alternate_bins_and_stack_without_overlap(self):
        factory = FactoryController()
        state = factory.update(factory.cycle_duration * 24)
        self.assertEqual(state["counters"]["completed_cycles"], 24)
        self.assertEqual(state["counters"]["picked"], 24)
        self.assertEqual(state["counters"]["placed"], 24)
        self.assertEqual(state["counters"]["spawned"], 25)
        self.assertEqual(state["counters"]["by_color"], {"red": 12, "blue": 12})
        self.assertEqual(state["state"], "conveying")
        self.assertEqual([p["color"] for p in state["placed_products"]], ["red", "blue"] * 12)
        self.assertEqual(len({tuple(p["position"]) for p in state["placed_products"]}), 24)
        self.assertTrue(all(not p["attached"] for p in state["placed_products"]))
        self.assertAlmostEqual(state["placed_products"][18]["position"][2], 0.84)

    def test_timestep_subdivision_matches_one_large_step(self):
        one_step = FactoryController()
        many_steps = FactoryController()
        duration = one_step.cycle_duration * 7 + 6.375
        rng = random.Random(42)
        remaining = duration
        while remaining > 0:
            step = min(remaining, rng.uniform(0.001, 0.2))
            many_steps.update(step)
            remaining -= step
        self.assertSnapshotEqual(one_step.update(duration), many_steps.snapshot())

    def test_exact_boundary_stops_belt_then_attaches_and_carries(self):
        factory = FactoryController()
        config = factory.config
        belt = config["conveyor"]
        state = factory.update(math.dist(belt["start"], belt["pickup"]) / belt["speed"])
        self.assertEqual(state["state"], "approaching")
        self.assertFalse(state["conveyor_running"])
        self.assertTrue(state["pickup_sensor"])
        self.assertSnapshotEqual(state["active_product"]["position"], [0.25, 0.0, 0.76])
        state = factory.update(config["timing"]["approaching"] + config["timing"]["picking"] + 0.3)
        self.assertEqual(state["state"], "lifting")
        self.assertTrue(state["active_product"]["attached"])
        self.assertTrue(state["robot_target"]["gripper_closed"])
        self.assertAlmostEqual(
            state["robot_target"]["position"][2] - state["active_product"]["position"][2],
            config["robot"]["grasp_offset"],
        )
        self.assertFalse(state["pickup_sensor"])

    def test_pause_freezes_and_resume_continues(self):
        factory = FactoryController()
        reference = FactoryController()
        factory.update(6.4)
        self.assertTrue(factory.pause())
        frozen = factory.snapshot()
        self.assertFalse(frozen["conveyor_running"])
        self.assertEqual(factory.update(100.0), frozen)
        self.assertTrue(factory.resume())
        self.assertSnapshotEqual(factory.update(0.25), reference.update(6.65))

    def test_emergency_stop_retains_grip_and_requires_reset(self):
        factory = FactoryController()
        factory.update(7.1)
        self.assertTrue(factory.snapshot()["active_product"]["attached"])
        factory.emergency_stop()
        frozen = factory.snapshot()
        self.assertFalse(factory.resume())
        self.assertFalse(factory.pause())
        self.assertEqual(factory.update(500), frozen)
        factory.reset()
        state = factory.snapshot()
        self.assertEqual(state["mode"], "paused")
        self.assertEqual(state["simulation_time"], 0.0)
        self.assertEqual(state["placed_products"], [])
        self.assertEqual(state["active_product"]["id"], 1)
        self.assertEqual(state["counters"]["picked"], 0)
        self.assertFalse(state["robot_target"]["gripper_closed"])
        self.assertTrue(factory.resume())
        self.assertSnapshotEqual(factory.snapshot(), FactoryController().snapshot())

    def test_reset_can_explicitly_restart(self):
        factory = FactoryController()
        factory.update(20)
        factory.reset(start=True)
        self.assertEqual(factory.snapshot(), FactoryController().snapshot())

    def test_full_bins_finish_retraction_then_latch_without_spawning(self):
        factory = FactoryController()
        self.assertEqual(factory.bin_capacity, 18)
        self.assertEqual(factory.cycle_capacity, 36)
        # 마지막 제품을 적재한 후에도 팔의 복귀가 끝나야 합니다.
        # 그다음 적재함 잠금이 후속 제품 생성을 막는지 검사합니다.
        state = factory.update(factory.cycle_duration * factory.cycle_capacity - 0.5)
        self.assertEqual(state["mode"], "running")
        self.assertEqual(state["state"], "retracting")
        self.assertEqual(state["counters"]["placed"], 36)
        self.assertEqual(state["counters"]["completed_cycles"], 35)
        self.assertIsNone(state["active_product"])
        stopped = factory.update(1000)
        self.assertEqual(stopped["mode"], "bin_full")
        self.assertEqual(stopped["state"], "retracting")
        self.assertEqual(stopped["phase_progress"], 1.0)
        self.assertEqual(stopped["counters"]["completed_cycles"], 36)
        self.assertEqual(stopped["counters"]["spawned"], 36)
        self.assertEqual(stopped["counters"]["by_color"], {"red": 18, "blue": 18})
        self.assertEqual(len(stopped["placed_products"]), 36)
        self.assertIsNone(stopped["active_product"])
        self.assertFalse(stopped["conveyor_running"])
        self.assertSnapshotEqual(
            stopped["robot_target"]["position"], factory.config["robot"]["home"]
        )
        self.assertAlmostEqual(stopped["simulation_time"], factory.cycle_duration * 36)
        self.assertFalse(factory.pause())
        self.assertFalse(factory.resume())
        self.assertEqual(factory.update(1000), stopped)
        factory.reset()
        fresh = FactoryController()
        fresh.pause()
        self.assertEqual(factory.snapshot(), fresh.snapshot())
        self.assertTrue(factory.resume())
        self.assertEqual(factory.update(factory.cycle_duration)["counters"]["placed"], 1)

    def test_capacity_tracks_custom_color_schedule(self):
        for colors, expected_capacity in [
            (["red"], 18),
            (["red", "red", "blue"], 27),
            (["blue", "red", "red"], 28),
            (["red", "blue"], 36),
        ]:
            with self.subTest(colors=colors):
                factory = FactoryController({"product": {"colors": colors}})
                self.assertEqual(factory.cycle_capacity, expected_capacity)
                state = factory.update(factory.cycle_duration * 100)
                self.assertEqual(state["mode"], "bin_full")
                self.assertEqual(state["counters"]["completed_cycles"], expected_capacity)
                self.assertEqual(state["counters"]["spawned"], expected_capacity)
                self.assertLessEqual(
                    max(state["counters"]["by_color"].values()), factory.bin_capacity
                )

    def test_snapshot_is_serializable_and_detached(self):
        factory = FactoryController()
        factory.update(factory.cycle_duration + 0.2)
        baseline = factory.snapshot()
        snapshot = factory.snapshot()
        self.assertEqual(json.loads(json.dumps(snapshot, allow_nan=False)), snapshot)
        snapshot["active_product"]["position"][0] = 999
        snapshot["robot_target"]["position"][2] = 999
        snapshot["placed_products"][0]["position"][1] = 999
        snapshot["counters"]["by_color"]["red"] = 999
        self.assertEqual(factory.snapshot(), baseline)

    def test_config_file_matches_defaults_and_partial_override_works(self):
        path = Path(__file__).resolve().parents[1] / "config" / "factory.json"
        self.assertEqual(load_config(path), DEFAULT_CONFIG)
        factory = FactoryController({"conveyor": {"speed": 0.7}})
        factory.update(1)
        self.assertAlmostEqual(factory.snapshot()["active_product"]["position"][0], -0.75)

    def test_invalid_input_fails_early(self):
        for override in [
            {"conveyor": {"speed": 0}},
            {"timing": {"picking": -1}},
            {"robot": {"home": [1, 2]}},
            {"product": {"size": [1, 1, float("nan")]}},
            {"placement": {"rows": 0}},
            {"placement": {"spacing": 0.001}},
            {"placement": {"max_layers": 0}},
            {"placement": {"max_layers": 1.5}},
            {"product": {"colors": ["green"]}},
            {"conveyer": {}},
        ]:
            with self.subTest(override=override), self.assertRaises(ValueError):
                FactoryController(override)
        for dt in [-1, float("nan"), float("inf"), True, "1"]:
            with self.subTest(dt=dt), self.assertRaises(ValueError):
                FactoryController().update(dt)
        factory = FactoryController()
        self.assertEqual(factory.update(0), factory.snapshot())


if __name__ == "__main__":
    unittest.main()
