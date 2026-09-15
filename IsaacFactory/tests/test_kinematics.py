"""Isaac Sim이나 GPU 없이 기하학적 IK를 검사합니다."""

import math
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from factory_scene import solve_arm_ik
from factory_core import FactoryController


def distance(a, b):
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


class ArmKinematicsTests(unittest.TestCase):
    def test_entire_pick_and_place_workspace_is_reachable(self):
        for x in (-0.2, 0.0, 0.25, 0.65, 0.9, 1.15):
            for y in (0.0, 0.4, 0.68, 1.0, 1.15):
                for z in (0.79, 1.0, 1.25):
                    with self.subTest(target=(x, y, z)):
                        pose = solve_arm_ik((x, y, z))
                        self.assertTrue(pose.reachable)
                        self.assertLess(pose.distance_error, 1e-7)
                        self.assertAlmostEqual(distance(pose.shoulder, pose.elbow), 0.65, places=7)
                        self.assertAlmostEqual(distance(pose.elbow, pose.wrist), 0.60, places=7)
                        self.assertAlmostEqual(
                            pose.wrist[2] - pose.tool_position[2], 0.15, places=7
                        )

    def test_unreachable_target_reports_projection_error(self):
        pose = solve_arm_ik((10, 0, 0.8))
        self.assertFalse(pose.reachable)
        self.assertGreater(pose.distance_error, 8.0)
        self.assertLessEqual(distance(pose.shoulder, pose.wrist), 1.25)

    def test_every_default_production_pose_is_reachable(self):
        controller = FactoryController()
        samples = 0
        while controller.mode == "running":
            snapshot = controller.snapshot()
            pose = solve_arm_ik(snapshot["robot_target"]["position"])
            self.assertTrue(pose.reachable, (snapshot["state"], pose))
            self.assertLess(pose.distance_error, 1e-7)
            # 전완과 손목의 절대 피치가 아래쪽을 유지하는지 확인합니다.
            _, shoulder, elbow, wrist = pose.joint_angles
            self.assertAlmostEqual(shoulder + elbow + wrist, -math.pi / 2, places=7)
            controller.update(1.0 / 60.0)
            samples += 1
            self.assertLess(samples, 60000)
        self.assertEqual(controller.snapshot()["counters"]["completed_cycles"], 36)
        self.assertGreater(samples, 20000)

    def test_vertical_target_and_singularity_do_not_produce_nan(self):
        for target in ((0.25, 0.68, 1.10), (0.25, 0.68, 0.90)):
            pose = solve_arm_ik(target)
            self.assertTrue(all(math.isfinite(value) for value in (*pose.elbow, *pose.wrist)))
            self.assertAlmostEqual(distance(pose.elbow, pose.wrist), 0.60, places=7)

    def test_invalid_targets_fail_explicitly(self):
        with self.assertRaises(ValueError):
            solve_arm_ik((math.nan, 0, 0))
        with self.assertRaises(ValueError):
            solve_arm_ik((0, 0, 0), upper_length=0)


if __name__ == "__main__":
    unittest.main()
