"""Isaac Sim용 USD 작업 셀을 생성합니다.

해석적 IK를 사용하는 기구학 시연이며 관절 구동, 접촉력, 실제 파지 검증은 포함하지 않습니다.
USD 및 Isaac 모듈은 호출자가 SimulationApp을 시작한 이후에 가져옵니다."""

from dataclasses import dataclass
import math
from typing import Any, Sequence, Tuple

Vec3 = Tuple[float, float, float]


@dataclass(frozen=True)
class ArmPose:
    shoulder: Vec3
    elbow: Vec3
    wrist: Vec3
    tool_position: Vec3
    yaw: float
    reachable: bool
    distance_error: float
    joint_angles: Tuple[float, float, float, float]


def solve_arm_ik(
    tool_position: Sequence[float],
    base: Sequence[float] = (0.25, 0.68, 0.72),
    shoulder_height: float = 0.33,
    upper_length: float = 0.65,
    forearm_length: float = 0.60,
    tool_length: float = 0.15,
) -> ArmPose:
    """아래로 향하는 도구와 두 링크 팔의 자세를 팔꿈치 위쪽 IK로 계산합니다.

    각도는 라디안, 좌표는 미터 단위이며 tool_position은 그리퍼 기준점입니다.
    도달 불가능한 목표는 도달 경계로 투영하고 오차를 함께 반환합니다."""
    values = tuple(float(v) for v in (*tool_position, *base))
    if len(tool_position) != 3 or len(base) != 3 or not all(math.isfinite(v) for v in values):
        raise ValueError("tool_position and base must be finite 3D coordinates")
    if min(upper_length, forearm_length) <= 0 or tool_length < 0:
        raise ValueError("Arm link lengths must be positive and tool length nonnegative")
    shoulder = (float(base[0]), float(base[1]), float(base[2]) + shoulder_height)
    tx, ty, tz = (float(v) for v in tool_position)
    wx, wy, wz = tx, ty, tz + tool_length
    dx, dy, dz = wx - shoulder[0], wy - shoulder[1], wz - shoulder[2]
    radial = math.hypot(dx, dy)
    distance = math.hypot(radial, dz)
    yaw = math.atan2(dy, dx) if radial > 1e-12 else 0.0
    reach_min = abs(upper_length - forearm_length) + 1e-8
    reach_max = upper_length + forearm_length - 1e-8
    solved_distance = max(reach_min, min(reach_max, distance))
    reachable = reach_min - 1e-7 <= distance <= reach_max + 1e-7
    if distance < 1e-12:
        radial, dz = solved_distance, 0.0
    else:
        factor = solved_distance / distance
        radial *= factor
        dz *= factor
    cosine = (solved_distance**2 - upper_length**2 - forearm_length**2) / (
        2.0 * upper_length * forearm_length
    )
    elbow_angle = -math.acos(max(-1.0, min(1.0, cosine)))
    shoulder_angle = math.atan2(dz, radial) - math.atan2(
        forearm_length * math.sin(elbow_angle),
        upper_length + forearm_length * math.cos(elbow_angle),
    )
    c, s = math.cos(yaw), math.sin(yaw)
    er = upper_length * math.cos(shoulder_angle)
    elbow = (
        shoulder[0] + er * c,
        shoulder[1] + er * s,
        shoulder[2] + upper_length * math.sin(shoulder_angle),
    )
    wrist = (shoulder[0] + radial * c, shoulder[1] + radial * s, shoulder[2] + dz)
    achieved_tool = (wrist[0], wrist[1], wrist[2] - tool_length)
    error = math.sqrt(sum((a - b) ** 2 for a, b in zip(achieved_tool, (tx, ty, tz))))
    wrist_pitch = -math.pi / 2.0 - shoulder_angle - elbow_angle
    return ArmPose(
        shoulder,
        elbow,
        wrist,
        achieved_tool,
        yaw,
        reachable,
        error,
        (yaw, shoulder_angle, elbow_angle, wrist_pitch),
    )


class FactoryScene:
    """외부 에셋 없이 USD 공장 장면을 생성하고 갱신합니다."""

    root_path = "/World/Factory"
    camera_path = "/World/Factory/Camera"
    joint_prim_paths = {
        "base_yaw": "/World/Factory/Robot/BaseYaw",
        "shoulder": "/World/Factory/Robot/ShoulderJoint",
        "elbow": "/World/Factory/Robot/ElbowJoint",
        "wrist_pitch": "/World/Factory/Robot/WristJoint",
    }

    def __init__(
        self,
        stage: Any,
        config: Any,
        *,
        root_path="/World/Factory",
        origin=(0.0, 0.0, 0.0),
        lighting=True,
    ):
        from pxr import Gf, Sdf, UsdGeom, UsdLux, UsdShade

        path = Sdf.Path(root_path)
        if (
            not path.IsAbsolutePath()
            or not path.IsPrimPath()
            or not root_path.startswith("/World/")
        ):
            raise ValueError("Factory scene root must be an absolute prim path beneath /World.")
        if len(origin) != 3 or not all(math.isfinite(float(value)) for value in origin):
            raise ValueError("Factory origin must contain three finite metre coordinates.")
        self.root_path = root_path
        self.camera_path = root_path + "/Camera"
        self.joint_prim_paths = {
            name: root_path + value[len("/World/Factory") :]
            for name, value in type(self).joint_prim_paths.items()
        }
        self.origin = tuple(float(value) for value in origin)
        self.Gf, self.Sdf = Gf, Sdf
        self.UsdGeom, self.UsdLux, self.UsdShade = UsdGeom, UsdLux, UsdShade
        self.stage, self.config = stage, config
        self._transforms = {}
        self._bindings = {}
        self._product_prims = {}
        self._slats = []
        self.materials = {}
        self.last_ik_error = 0.0
        self.joint_state = {
            "names": ["base_yaw", "shoulder", "elbow", "wrist_pitch"],
            "positions": [0.0, 0.0, 0.0, 0.0],
        }
        self._last_poses = {}
        UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
        UsdGeom.SetStageMetersPerUnit(stage, 1.0)
        world = UsdGeom.Xform.Define(stage, "/World")
        stage.SetDefaultPrim(world.GetPrim())
        root = self._group(self.root_path)
        UsdGeom.Xformable(root.GetPrim()).AddTranslateOp().Set(Gf.Vec3d(*self.origin))
        root.GetPrim().SetCustomDataByKey(
            "description", "Offline conveyor and color sorting robot cell"
        )
        root.GetPrim().SetCustomDataByKey(
            "motionModel", "Analytical kinematic process demonstration; no ROS"
        )
        self._create_materials()
        self._build_floor()
        self._build_conveyor()
        self._build_trays()
        self._build_robot()
        self._build_equipment()
        if lighting:
            self._build_lighting_and_camera()
        self._group(self.root_path + "/Products")
        self._update_arm(self.config["robot"]["home"], False)

    def _group(self, path):
        return self.UsdGeom.Xform.Define(self.stage, path)

    def _material(self, name, color, roughness=0.45, metallic=0.0, emission=0.0):
        path = self.root_path + "/Materials/" + name
        material = self.UsdShade.Material.Define(self.stage, path)
        shader = self.UsdShade.Shader.Define(self.stage, path + "/Shader")
        shader.CreateIdAttr("UsdPreviewSurface")
        shader.CreateInput("diffuseColor", self.Sdf.ValueTypeNames.Color3f).Set(
            self.Gf.Vec3f(*color)
        )
        shader.CreateInput("roughness", self.Sdf.ValueTypeNames.Float).Set(roughness)
        shader.CreateInput("metallic", self.Sdf.ValueTypeNames.Float).Set(metallic)
        if emission:
            shader.CreateInput("emissiveColor", self.Sdf.ValueTypeNames.Color3f).Set(
                self.Gf.Vec3f(*(component * emission for component in color))
            )
        material.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(), "surface")
        self.materials[name] = material

    def _create_materials(self):
        self._group(self.root_path + "/Materials")
        for name, color, roughness, metallic, emission in (
            ("Floor", (0.085, 0.110, 0.140), 0.75, 0.0, 0.0),
            ("Grid", (0.12, 0.16, 0.20), 0.65, 0.0, 0.0),
            ("Black", (0.016, 0.024, 0.035), 0.36, 0.25, 0.0),
            ("Belt", (0.035, 0.043, 0.051), 0.88, 0.0, 0.0),
            ("Slats", (0.075, 0.09, 0.10), 0.60, 0.15, 0.0),
            ("Steel", (0.38, 0.46, 0.51), 0.24, 0.75, 0.0),
            ("LightSteel", (0.66, 0.72, 0.76), 0.28, 0.60, 0.0),
            ("Cabinet", (0.72, 0.78, 0.81), 0.50, 0.20, 0.0),
            ("Orange", (0.98, 0.38, 0.025), 0.28, 0.30, 0.0),
            ("Yellow", (1.0, 0.68, 0.035), 0.38, 0.15, 0.0),
            ("Cyan", (0.015, 0.65, 0.78), 0.32, 0.40, 0.0),
            ("CyanGlow", (0.02, 0.75, 0.95), 0.22, 0.10, 2.0),
            ("Red", (0.85, 0.045, 0.055), 0.27, 0.12, 0.0),
            ("Blue", (0.045, 0.22, 0.90), 0.27, 0.12, 0.0),
            ("RedTray", (0.36, 0.035, 0.045), 0.48, 0.35, 0.0),
            ("BlueTray", (0.025, 0.10, 0.36), 0.48, 0.35, 0.0),
            ("GreenGlow", (0.10, 0.95, 0.35), 0.22, 0.0, 2.0),
            ("AmberGlow", (1.0, 0.48, 0.01), 0.22, 0.0, 2.0),
            ("RedGlow", (1.0, 0.025, 0.02), 0.22, 0.0, 2.0),
            ("White", (0.88, 0.92, 0.93), 0.50, 0.0, 0.0),
        ):
            self._material(name, color, roughness, metallic, emission)

    def _bind(self, prim, material):
        path = str(prim.GetPath())
        if self._bindings.get(path) != material:
            self.UsdShade.MaterialBindingAPI.Apply(prim).Bind(self.materials[material])
            self._bindings[path] = material

    def _pose(self, prim, position, rotation=None, scale=None):
        path = str(prim.GetPath())
        if path not in self._transforms:
            xform = self.UsdGeom.Xformable(prim)
            self._transforms[path] = (
                xform.AddTranslateOp(),
                xform.AddOrientOp(),
                xform.AddScaleOp(),
            )
        translate, orient, size = self._transforms[path]
        translate.Set(self.Gf.Vec3d(*position))
        if rotation is not None:
            orient.Set(self.Gf.Quatf(rotation.GetQuat()))
        if scale is not None:
            size.Set(self.Gf.Vec3f(*scale))

    def _cube(self, path, position, size, material, rotation=None):
        shape = self.UsdGeom.Cube.Define(self.stage, path)
        shape.CreateSizeAttr(1.0)
        self._pose(shape.GetPrim(), position, rotation, size)
        self._bind(shape.GetPrim(), material)
        return shape.GetPrim()

    def _cylinder(self, path, position, radius, height, material, axis="Z"):
        shape = self.UsdGeom.Cylinder.Define(self.stage, path)
        shape.CreateRadiusAttr(radius)
        shape.CreateHeightAttr(height)
        shape.CreateAxisAttr(axis)
        self._pose(shape.GetPrim(), position)
        self._bind(shape.GetPrim(), material)
        return shape.GetPrim()

    def _sphere(self, path, position, radius, material):
        shape = self.UsdGeom.Sphere.Define(self.stage, path)
        shape.CreateRadiusAttr(radius)
        self._pose(shape.GetPrim(), position)
        self._bind(shape.GetPrim(), material)
        return shape.GetPrim()

    def _beam(self, path, start, end, width, depth, material):
        vector = self.Gf.Vec3d(*(b - a for a, b in zip(start, end)))
        center = tuple((a + b) * 0.5 for a, b in zip(start, end))
        rotation = self.Gf.Rotation(self.Gf.Vec3d(0, 0, 1), vector.GetNormalized())
        return self._cube(path, center, (width, depth, vector.GetLength()), material, rotation)

    def _build_floor(self):
        p = self.root_path + "/Floor"
        self._group(p)
        self._cube(p + "/Slab", (0, 0.38, -0.07), (4.7, 3.55, 0.14), "Floor")
        for i in range(19):
            self._cube(
                p + f"/GridX{i}", (-2.25 + i * 0.25, 0.38, 0.002), (0.006, 3.45, 0.002), "Grid"
            )
        for i in range(14):
            self._cube(p + f"/GridY{i}", (0, -1.25 + i * 0.25, 0.003), (4.60, 0.006, 0.002), "Grid")
        for x in (-1.94, 1.60):
            self._cube(
                p + ("/ZoneLeft" if x < 0 else "/ZoneRight"),
                (x, 0.39, 0.009),
                (0.045, 2.35, 0.006),
                "Yellow",
            )
        for y in (-0.78, 1.56):
            self._cube(
                p + ("/ZoneFront" if y < 0 else "/ZoneRear"),
                (-0.17, y, 0.009),
                (3.58, 0.045, 0.006),
                "Yellow",
            )
        # 대각선 주의 표시와 세 개의 화살표로 제품 흐름을 표시합니다.
        for i in range(11):
            self._cube(
                p + f"/Caution{i}",
                (-1.55 + i * 0.26, -0.61, 0.01),
                (0.13, 0.055, 0.008),
                "Yellow",
                self.Gf.Rotation(self.Gf.Vec3d(0, 0, 1), -45),
            )
        for i in range(3):
            x = -1.25 + i * 0.26
            self._beam(
                p + f"/Flow{i}A", (x, -0.48, 0.014), (x + 0.09, -0.39, 0.014), 0.025, 0.01, "Cyan"
            )
            self._beam(
                p + f"/Flow{i}B", (x + 0.09, -0.39, 0.014), (x, -0.30, 0.014), 0.025, 0.01, "Cyan"
            )

    def _build_conveyor(self):
        p = self.root_path + "/Conveyor"
        self._group(p)
        self._cube(p + "/Frame", (-0.61, 0, 0.61), (2.22, 0.57, 0.16), "Steel")
        self._cube(p + "/Belt", (-0.61, 0, 0.704), (2.16, 0.46, 0.03), "Belt")
        for side in (-1, 1):
            y = side * 0.279
            suffix = "Front" if side < 0 else "Rear"
            self._cube(p + "/Rail" + suffix, (-0.61, y, 0.687), (2.27, 0.04, 0.12), "Cyan")
            self._cube(
                p + "/RailInsert" + suffix,
                (-0.61, y + side * 0.022, 0.692),
                (2.16, 0.012, 0.037),
                "Black",
            )
            for j, x in enumerate((-1.48, 0.25)):
                self._cube(
                    p + f"/Leg{suffix}{j}", (x, side * 0.225, 0.30), (0.075, 0.075, 0.59), "Steel"
                )
                self._cube(
                    p + f"/Foot{suffix}{j}", (x, side * 0.225, 0.026), (0.16, 0.15, 0.052), "Black"
                )
                for k, dx in enumerate((-0.048, 0.048)):
                    self._cylinder(
                        p + f"/FootBolt{suffix}{j}{k}",
                        (x + dx, side * 0.225, 0.057),
                        0.012,
                        0.016,
                        "LightSteel",
                    )
            self._cube(
                p + "/LowBrace" + suffix,
                (-0.615, side * 0.225, 0.20),
                (1.80, 0.038, 0.045),
                "Steel",
            )
        for i, x in enumerate((-1.68, 0.46)):
            self._cylinder(p + f"/EndRoller{i}", (x, 0, 0.66), 0.065, 0.49, "LightSteel", "Y")
            self._cylinder(p + f"/Bearing{i}", (x, -0.295, 0.66), 0.04, 0.045, "Black", "Y")
        self._cylinder(p + "/Motor", (0.34, 0.41, 0.605), 0.09, 0.22, "Black", "Y")
        self._cylinder(p + "/MotorCap", (0.34, 0.53, 0.605), 0.075, 0.025, "Steel", "Y")
        for i in range(26):
            x = -1.65 + i * 2.10 / 26
            prim = self._cube(p + f"/Slat{i:02d}", (x, 0, 0.722), (0.012, 0.442, 0.004), "Slats")
            self._slats.append((prim, x))
        sensor_x = float(self.config["conveyor"]["pickup"][0])
        for i, y in enumerate((-0.32, 0.32)):
            self._cube(p + f"/SensorPost{i}", (sensor_x, y, 0.79), (0.036, 0.045, 0.24), "Black")
            self._cube(p + f"/SensorHead{i}", (sensor_x, y, 0.825), (0.07, 0.06, 0.064), "Cyan")
        self._sensor = self._cube(
            p + "/SensorBeam", (sensor_x, 0, 0.788), (0.006, 0.585, 0.006), "CyanGlow"
        )
        self._sensor.SetCustomDataByKey("semanticLabel", "virtual photoelectric pick sensor")

    def _build_trays(self):
        p = self.root_path + "/Receiving"
        self._group(p)
        self._cube(p + "/Table", (1.02, 0.70, 0.665), (0.92, 1.32, 0.07), "LightSteel")
        for i, x in enumerate((0.65, 1.40)):
            for j, y in enumerate((0.12, 1.28)):
                self._cube(p + f"/Leg{i}{j}", (x, y, 0.33), (0.055, 0.055, 0.66), "Steel")
                self._cube(p + f"/Foot{i}{j}", (x, y, 0.025), (0.11, 0.11, 0.05), "Black")
        for kind, material in (("Red", "RedTray"), ("Blue", "BlueTray")):
            cx, y, surface_z = self.config["bins"][kind.lower()]
            tray = p + "/" + kind + "Tray"
            self._group(tray).GetPrim().SetCustomDataByKey(
                "semanticLabel", kind.lower() + " output bin"
            )
            self._cube(tray + "/Base", (cx, y, surface_z - 0.0245), (0.67, 0.51, 0.037), material)
            self._cube(tray + "/Liner", (cx, y, surface_z - 0.003), (0.61, 0.45, 0.006), "Black")
            for i, x in enumerate((cx - 0.33, cx + 0.33)):
                self._cube(
                    tray + f"/Side{i}", (x, y, surface_z + 0.046), (0.027, 0.53, 0.11), material
                )
            for i, yy in enumerate((y - 0.25, y + 0.25)):
                self._cube(
                    tray + f"/Wall{i}", (cx, yy, surface_z + 0.046), (0.67, 0.023, 0.11), material
                )
            self._cube(
                tray + "/ColorPlate", (cx + 0.349, y, surface_z + 0.046), (0.009, 0.20, 0.062), kind
            )
            for i in range(3):
                self._cube(
                    tray + f"/Index{i}",
                    (cx + 0.12 + 0.047 * i, y - 0.263, surface_z + 0.046),
                    (0.021, 0.006, 0.052),
                    "White",
                )

    def _build_robot(self):
        p = self.root_path + "/Robot"
        self._group(p).GetPrim().SetCustomDataByKey(
            "semanticLabel", "analytical industrial sorting manipulator"
        )
        bx, by, bz = self._robot_base()
        self._cube(p + "/Plinth", (bx, by, 0.036), (0.48, 0.48, 0.072), "Black")
        self._cube(p + "/Pedestal", (bx, by, bz / 2), (0.33, 0.33, bz - 0.045), "Cabinet")
        self._cube(p + "/PedestalAccent", (bx, by - 0.168, bz / 2), (0.24, 0.008, 0.32), "Black")
        self._cube(
            p + "/PedestalStripe", (bx, by - 0.174, bz / 2 + 0.12), (0.24, 0.006, 0.018), "Cyan"
        )
        self._cylinder(p + "/Mount", (bx, by, bz + 0.026), 0.198, 0.055, "Steel")
        self._cylinder(p + "/BaseYaw", (bx, by, bz + 0.125), 0.15, 0.16, "Orange")
        self._cylinder(p + "/BaseRing", (bx, by, bz + 0.058), 0.156, 0.025, "Black")
        for i in range(6):
            angle = i * math.pi / 3
            self._cylinder(
                p + f"/MountBolt{i}",
                (bx + 0.171 * math.cos(angle), by + 0.171 * math.sin(angle), bz + 0.06),
                0.013,
                0.014,
                "LightSteel",
            )
        self._robot = {}
        self._robot["shoulder_body"] = self._cube(
            p + "/ShoulderHousing", (0, 0, 0), (0.20, 0.19, 0.22), "Orange"
        )
        for name, radius, height in (
            ("Shoulder", 0.108, 0.245),
            ("Elbow", 0.088, 0.195),
            ("Wrist", 0.062, 0.14),
        ):
            self._robot[name] = self._cylinder(
                p + "/" + name + "Joint", (0, 0, 0), radius, height, "Black", "Y"
            )
            self._robot[name + "Cap"] = self._cylinder(
                p + "/" + name + "Cap", (0, 0, 0), radius * 0.71, 0.016, "Orange", "Y"
            )
            self._robot[name + "Bolt"] = self._cylinder(
                p + "/" + name + "Bolt", (0, 0, 0), radius * 0.26, 0.020, "Steel", "Y"
            )
        self._robot["Upper"] = self._cube(p + "/UpperArm", (0, 0, 0), (0.13, 0.15, 0.57), "Orange")
        self._robot["UpperPanel"] = self._cube(
            p + "/UpperArmPanel", (0, 0, 0), (0.070, 0.156, 0.40), "Black"
        )
        self._robot["Forearm"] = self._cube(
            p + "/Forearm", (0, 0, 0), (0.105, 0.115, 0.54), "Orange"
        )
        self._robot["ForearmPanel"] = self._cube(
            p + "/ForearmPanel", (0, 0, 0), (0.045, 0.120, 0.33), "LightSteel"
        )
        self._robot["Tool"] = self._cylinder(p + "/ToolFlange", (0, 0, 0), 0.052, 0.082, "Steel")
        self._robot["Gripper"] = self._cube(
            p + "/GripperBody", (0, 0, 0), (0.11, 0.20, 0.065), "Black"
        )
        for side in (-1, 1):
            name = "LeftFinger" if side < 0 else "RightFinger"
            self._robot[name] = self._cube(
                p + "/" + name, (0, 0, 0), (0.035, 0.018, 0.11), "LightSteel"
            )
            self._robot[name + "Pad"] = self._cube(
                p + "/" + name + "Pad", (0, 0, 0), (0.039, 0.01, 0.045), "Black"
            )
        for name, path in self.joint_prim_paths.items():
            self.stage.GetPrimAtPath(path).SetCustomDataByKey("jointName", name)

    def _robot_base(self):
        return tuple(self.config["robot"]["base"])

    def _build_equipment(self):
        p = self.root_path + "/Equipment"
        self._group(p)
        self._cube(p + "/CabinetFoot", (-1.41, 1.06, 0.08), (0.49, 0.42, 0.16), "Black")
        self._cube(p + "/Cabinet", (-1.41, 1.06, 0.61), (0.48, 0.38, 0.97), "Cabinet")
        self._cube(p + "/CabinetDoor", (-1.41, 0.859, 0.62), (0.425, 0.018, 0.87), "Steel")
        self._cube(p + "/CabinetHandle", (-1.24, 0.839, 0.62), (0.017, 0.027, 0.14), "Black")
        self._cube(p + "/HmiFrame", (-1.44, 0.837, 0.82), (0.25, 0.03, 0.20), "Black")
        self._cube(p + "/HmiScreen", (-1.44, 0.818, 0.82), (0.214, 0.008, 0.161), "Cyan")
        for i, width in enumerate((0.145, 0.105, 0.165)):
            self._cube(
                p + f"/HmiLine{i}",
                (-1.46, 0.811, 0.86 - i * 0.041),
                (width, 0.006, 0.013),
                "CyanGlow",
            )
        self._cylinder(p + "/EmergencyStopBezel", (-1.52, 0.827, 0.54), 0.035, 0.025, "Yellow", "Y")
        self._cylinder(p + "/EmergencyStop", (-1.52, 0.805, 0.54), 0.021, 0.030, "Red", "Y")
        for i in range(5):
            self._cube(
                p + f"/Vent{i}", (-1.43, 0.845, 0.36 + i * 0.022), (0.22, 0.009, 0.008), "Black"
            )
        self._cylinder(p + "/SignalPost", (-1.41, 1.06, 1.19), 0.018, 0.20, "Steel")
        self._signals = {}
        for i, (name, material) in enumerate(
            (("green", "GreenGlow"), ("amber", "AmberGlow"), ("red", "RedGlow"))
        ):
            self._signals[name] = self._cylinder(
                p + "/Signal" + name, (-1.41, 1.06, 1.31 + i * 0.06), 0.045, 0.052, material
            )
            self._cylinder(
                p + "/SignalRing" + name, (-1.41, 1.06, 1.282 + i * 0.06), 0.047, 0.008, "Black"
            )
        self._cylinder(p + "/SignalCap", (-1.41, 1.06, 1.468), 0.047, 0.017, "Black")
        # 앞면을 열고 뒤쪽 장벽을 낮춰 전체 시점에서도 공정이 보이도록 합니다.
        for i, x in enumerate((-1.84, -0.45, 1.53)):
            self._cube(p + f"/GuardFoot{i}", (x, 1.49, 0.034), (0.15, 0.14, 0.068), "Black")
            self._cube(p + f"/GuardPost{i}", (x, 1.49, 0.37), (0.047, 0.047, 0.74), "Yellow")
        for i, z in enumerate((0.33, 0.69)):
            self._cube(p + f"/GuardRail{i}", (-0.155, 1.49, z), (3.37, 0.036, 0.04), "Yellow")

    def _build_lighting_and_camera(self):
        p = self.root_path + "/Lights"
        self._group(p)
        dome = self.UsdLux.DomeLight.Define(self.stage, p + "/Ambient")
        dome.CreateIntensityAttr(420.0)
        dome.CreateColorAttr(self.Gf.Vec3f(0.78, 0.86, 1.0))
        key = self.UsdLux.DistantLight.Define(self.stage, p + "/Key")
        key.CreateIntensityAttr(2500.0)
        key.CreateAngleAttr(1.5)
        key.CreateColorAttr(self.Gf.Vec3f(1.0, 0.92, 0.82))
        self.UsdGeom.Xformable(key.GetPrim()).AddRotateXYZOp().Set(self.Gf.Vec3f(-28, -30, -25))
        fill = self.UsdLux.RectLight.Define(self.stage, p + "/Overhead")
        fill.CreateIntensityAttr(900.0)
        fill.CreateWidthAttr(3.0)
        fill.CreateHeightAttr(2.0)
        self.UsdGeom.Xformable(fill.GetPrim()).AddTranslateOp().Set(self.Gf.Vec3d(-0.5, 0.3, 3.4))
        camera = self.UsdGeom.Camera.Define(self.stage, self.camera_path)
        eye = self.Gf.Vec3d(3.4, -4.3, 3.2)
        target = self.Gf.Vec3d(-0.15, 0.40, 0.62)
        matrix = self.Gf.Matrix4d(1.0).SetLookAt(eye, target, self.Gf.Vec3d(0, 0, 1)).GetInverse()
        self.UsdGeom.Xformable(camera.GetPrim()).AddTransformOp().Set(matrix)
        camera.CreateFocalLengthAttr(37.0)
        camera.CreateHorizontalApertureAttr(36.0)
        camera.CreateVerticalApertureAttr(20.25)
        camera.CreateClippingRangeAttr(self.Gf.Vec2f(0.05, 100.0))
        camera.CreateFocusDistanceAttr((eye - target).GetLength())

    def _update_arm(self, tool_position, gripper_closed):
        pose = solve_arm_ik(tool_position, self._robot_base())
        self.last_ik_error = pose.distance_error
        self.joint_state["positions"] = list(pose.joint_angles)
        self.joint_state["reach_error"] = pose.distance_error
        self.joint_state["reachable"] = pose.reachable
        yaw_rotation = self.Gf.Rotation(self.Gf.Vec3d(0, 0, 1), math.degrees(pose.yaw))
        direction = (-math.sin(pose.yaw), math.cos(pose.yaw), 0.0)
        self._pose(
            self._robot["shoulder_body"],
            (pose.shoulder[0], pose.shoulder[1], pose.shoulder[2] - 0.10),
            yaw_rotation,
        )
        for name, point, cap_offset in (
            ("Shoulder", pose.shoulder, 0.129),
            ("Elbow", pose.elbow, 0.104),
            ("Wrist", pose.wrist, 0.077),
        ):
            self._pose(self._robot[name], point, yaw_rotation)
            cap = tuple(point[i] - direction[i] * cap_offset for i in range(3))
            bolt = tuple(point[i] - direction[i] * (cap_offset + 0.012) for i in range(3))
            self._pose(self._robot[name + "Cap"], cap, yaw_rotation)
            self._pose(self._robot[name + "Bolt"], bolt, yaw_rotation)
        for name, start, end in (
            ("Upper", pose.shoulder, pose.elbow),
            ("Forearm", pose.elbow, pose.wrist),
        ):
            vector = self.Gf.Vec3d(*(b - a for a, b in zip(start, end)))
            center = tuple((a + b) / 2.0 for a, b in zip(start, end))
            rotation = self.Gf.Rotation(self.Gf.Vec3d(0, 0, 1), vector.GetNormalized())
            self._pose(self._robot[name], center, rotation)
            self._pose(self._robot[name + "Panel"], center, rotation)
        x, y, z = pose.tool_position
        self._pose(self._robot["Tool"], (x, y, z + 0.112))
        self._pose(self._robot["Gripper"], (x, y, z + 0.052))
        product_half_width = self.config["product"]["size"][1] / 2.0
        gap = product_half_width + (0.017 if gripper_closed else 0.047)
        for sign, name in ((-1, "LeftFinger"), (1, "RightFinger")):
            self._pose(self._robot[name], (x, y + sign * gap, z - 0.003))
            self._pose(self._robot[name + "Pad"], (x, y + sign * (gap - 0.012), z - 0.030))

    def _set_visible(self, prim, visible):
        attr = self.UsdGeom.Imageable(prim).GetVisibilityAttr()
        desired = self.UsdGeom.Tokens.inherited if visible else self.UsdGeom.Tokens.invisible
        if attr.Get() != desired:
            attr.Set(desired)

    def _create_product(self, product_id, kind, size):
        # 제품 ID는 코어가 생성하며 임의 문자열도 안전한 이름으로 변환합니다.
        label = "p_" + "".join(c if c.isalnum() and c.isascii() else "_" for c in str(product_id))
        path = self.root_path + "/Products/" + label
        group = self._group(path).GetPrim()
        group.SetCustomDataByKey("productId", str(product_id))
        group.SetCustomDataByKey("classification", str(kind))
        material = "Red" if str(kind).lower() == "red" else "Blue"
        sx, sy, sz = size if isinstance(size, (tuple, list)) else (size, size, size)
        self._cube(path + "/Body", (0, 0, 0), (sx, sy, sz), material)
        self._cube(
            path + "/TopInset", (0, 0, sz / 2 + 0.001), (sx * 0.66, sy * 0.64, 0.004), "White"
        )
        for i, width in enumerate((0.009, 0.005, 0.012)):
            self._cube(
                path + f"/Mark{i}",
                (-sx * 0.2 + i * sx * 0.18, 0, sz / 2 + 0.004),
                (width, sy * 0.37, 0.002),
                "Black",
            )
        self._pose(group, (0, 0, 0))
        return group

    def update(self, snapshot):
        """코어 스냅샷을 적용하며 초기화 시 제품의 가시성도 갱신합니다."""
        target = snapshot["robot_target"]
        tool = target["position"]
        closed = bool(target["gripper_closed"])
        self._update_arm(tool, closed)
        # 제품 진행률로 정확한 벨트 이동 거리를 계산합니다.
        # 큰 시간 간격, 일시정지, 비상정지, 초기화에도 시각적 위치 오차가 쌓이지 않습니다.
        conveyor = self.config["conveyor"]
        belt_length = math.dist(conveyor["start"], conveyor["pickup"])
        active = snapshot["active_product"]
        progress = (
            min(belt_length, math.dist(active["position"][:2], conveyor["start"][:2]))
            if (active and snapshot["state"] == "conveying")
            else belt_length
        )
        belt_offset = max(0, snapshot["counters"]["spawned"] - 1) * belt_length + progress
        for prim, original_x in self._slats:
            x = -1.65 + ((original_x + 1.65 + belt_offset) % 2.10)
            self._pose(prim, (x, 0, 0.722))
        visible_ids = set()
        product_size = self.config["product"]["size"]
        products = {}
        if active is not None:
            products[active["id"]] = active
        for item in snapshot["placed_products"]:
            products[item["id"]] = item
        for item in products.values():
            product_id = str(item["id"])
            kind = item["color"]
            visible_ids.add(product_id)
            if product_id not in self._product_prims:
                self._product_prims[product_id] = self._create_product(
                    product_id, kind, product_size
                )
            prim = self._product_prims[product_id]
            self._set_visible(prim, True)
            position = tuple(item["position"])
            if self._last_poses.get(product_id) != position:
                self._pose(prim, position)
                self._last_poses[product_id] = position
        for product_id, prim in self._product_prims.items():
            if product_id not in visible_ids:
                self._set_visible(prim, False)
        sensor_active = bool(snapshot["pickup_sensor"])
        self._bind(self._sensor, "GreenGlow" if sensor_active else "CyanGlow")
        running = snapshot["mode"] == "running"
        fault = snapshot["mode"] == "emergency_stopped"
        for name, prim in self._signals.items():
            enabled = (
                (name == "red" and fault)
                or (name == "green" and running and not fault)
                or (name == "amber" and not running and not fault)
            )
            self._bind(
                prim,
                (
                    {"red": "RedGlow", "green": "GreenGlow", "amber": "AmberGlow"}[name]
                    if enabled
                    else "Black"
                ),
            )
