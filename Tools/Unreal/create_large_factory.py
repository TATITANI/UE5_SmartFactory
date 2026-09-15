"""편집 가능한 36×24 m 규모의 4셀 공장 홀을 작성합니다.

UnrealEditor-Cmd의 -run=pythonscript -script=<경로> -NullRHI로 실행합니다.
없는 홀 재질과 맵만 생성하고 기존 맵, 블루프린트, 재질을 보존합니다.
Play나 Isaac을 실행하지 않습니다."""

from __future__ import annotations

import json
import math
from pathlib import Path
import traceback

import unreal

PROJECT = Path(__file__).resolve().parents[2]
ROOT = "/Game/SmartFactory"
MAP_PATH = ROOT + "/Maps/L_SmartFactoryHall"
CELL_BP_PATH = ROOT + "/Blueprints/BP_SmartFactoryCell"
MODE_BP_PATH = ROOT + "/Blueprints/BP_SmartFactoryGameMode"
REPORT_PATH = PROJECT / "Saved" / "Tests" / "LargeFactoryGeneration.json"
CAMERA_POSITION = (1200, 2700, 2200)
CAMERA_TARGET = (-400, 0, 0)
CELL_ORIGINS = ((-800, -450, 0), (0, -450, 0), (800, -450, 0), (0, 450, 0))
PALETTE_NAMES = (
    "Floor",
    "Grid",
    "Black",
    "Belt",
    "Slats",
    "Steel",
    "LightSteel",
    "Cabinet",
    "Orange",
    "Yellow",
    "Cyan",
    "Red",
    "Blue",
    "RedTray",
    "BlueTray",
    "Green",
    "White",
)
HALL_COLORS = {
    "Concrete": ((0.205, 0.235, 0.270), 0.83, 0.0),
    "Wall": ((0.43, 0.49, 0.54), 0.68, 0.0),
    "Window": ((0.095, 0.30, 0.39), 0.22, 0.35),
    "Cardboard": ((0.49, 0.275, 0.105), 0.82, 0.0),
    "Asphalt": ((0.055, 0.075, 0.095), 0.82, 0.0),
}
REPORT = {
    "success": False,
    "map": MAP_PATH,
    "hall_metres": [36, 24, 8.5],
    "created_assets": [],
    "preserved_assets": [],
    "cells": [],
    "ros2_enabled": False,
    "play_started": False,
    "camera_position_cm": CAMERA_POSITION,
    "camera_target_cm": CAMERA_TARGET,
    "camera_fov": 55,
    "policy": "Create missing hall assets; preserve existing content.",
}
MESHES = {}
MATERIALS = {}
ACTORS = None


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def load(path, expected_type):
    asset = unreal.EditorAssetLibrary.load_asset(path)
    require(isinstance(asset, expected_type), "Missing or incompatible prerequisite asset: " + path)
    return asset


def save(asset):
    require(
        unreal.EditorAssetLibrary.save_loaded_asset(asset, only_if_is_dirty=False),
        "Could not save new asset: " + asset.get_path_name(),
    )


def load_materials():
    for name in PALETTE_NAMES:
        MATERIALS[name] = load(
            ROOT + "/Materials/MI_Factory" + name, unreal.MaterialInstanceConstant
        )
    master = load(ROOT + "/Materials/M_FactorySurface", unreal.Material)
    editing = unreal.MaterialEditingLibrary
    for name, (rgb, roughness, metallic) in HALL_COLORS.items():
        path = ROOT + "/Materials/MI_Hall" + name
        if unreal.EditorAssetLibrary.does_asset_exist(path):
            material = load(path, unreal.MaterialInstanceConstant)
            REPORT["preserved_assets"].append(path)
        else:
            folder, label = path.rsplit("/", 1)
            material = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
                label,
                folder,
                unreal.MaterialInstanceConstant,
                unreal.MaterialInstanceConstantFactoryNew(),
            )
            require(material is not None, "Could not create hall material: " + path)
            editing.set_material_instance_parent(material, master)
            editing.set_material_instance_vector_parameter_value(
                material, "Color", unreal.LinearColor(*rgb, 1)
            )
            editing.set_material_instance_scalar_parameter_value(material, "Roughness", roughness)
            editing.set_material_instance_scalar_parameter_value(material, "Metallic", metallic)
            editing.update_material_instance(material)
            save(material)
            REPORT["created_assets"].append(path)
        MATERIALS[name] = material


def actor(actor_class, label, folder, position=(0, 0, 0), rotation=None, tags=()):
    result = ACTORS.spawn_actor_from_class(
        actor_class, unreal.Vector(*position), rotation or unreal.Rotator(), transient=False
    )
    require(result is not None, "Could not place: " + label)
    result.set_actor_label(label)
    result.set_folder_path(unreal.Name(folder))
    result.set_editor_property(
        "tags", [unreal.Name("SmartFactoryHallGenerated"), *(unreal.Name(tag) for tag in tags)]
    )
    return result


def box(label, position, dimensions, material, folder, rotation=None, solid=False, shape="Cube"):
    result = actor(unreal.StaticMeshActor, label, folder, position, rotation)
    component = result.get_component_by_class(unreal.StaticMeshComponent)
    component.set_static_mesh(MESHES[shape])
    component.set_material(0, MATERIALS[material])
    component.set_mobility(unreal.ComponentMobility.STATIC)
    component.set_collision_enabled(
        unreal.CollisionEnabled.QUERY_AND_PHYSICS if solid else unreal.CollisionEnabled.NO_COLLISION
    )
    result.set_actor_scale3d(unreal.Vector(*(size / 100.0 for size in dimensions)))
    return result


def beam(label, start, end, thickness, material, folder):
    centre = tuple((a + b) * 0.5 for a, b in zip(start, end))
    length = math.dist(start, end)
    rotation = unreal.MathLibrary.find_look_at_rotation(unreal.Vector(*start), unreal.Vector(*end))
    return box(label, centre, (length, thickness, thickness), material, folder, rotation)


def text(label, words, position, size=45, color=(211, 225, 235), yaw=90, floor=False):
    rotation = unreal.Rotator(90 if floor else 0, yaw, 0)
    result = actor(unreal.TextRenderActor, label, "08_Signage", position, rotation)
    component = result.get_component_by_class(unreal.TextRenderComponent)
    component.set_text(words)
    component.set_world_size(size)
    component.set_horizontal_alignment(unreal.HorizTextAligment.EHTA_CENTER)
    component.set_text_render_color(unreal.Color(*color, 255))
    return result


def window(label, centre, width, side=False):
    x, y, z = centre
    folder = "01_Architecture/Windows"
    if side:
        box(label + " glass", centre, (10, width, 205), "Window", folder)
        for dy in (-width * 0.5, width * 0.5):
            box(label + " mullion", (x + 6, y + dy, z), (20, 15, 235), "LightSteel", folder)
        for dz in (-115, 115):
            box(label + " frame", (x + 6, y, z + dz), (20, width + 15, 15), "LightSteel", folder)
    else:
        box(label + " glass", centre, (width, 10, 205), "Window", folder)
        for dx in (-width * 0.5, width * 0.5):
            box(label + " mullion", (x + dx, y + 6, z), (15, 20, 235), "LightSteel", folder)
        for dz in (-115, 115):
            box(label + " frame", (x, y + 6, z + dz), (width + 15, 20, 15), "LightSteel", folder)


def architecture():
    folder = "01_Architecture"
    # 겹치는 면의 깜빡임을 막기 위해 셀 바닥보다 약간 낮게 배치합니다.
    box(
        "Hall concrete slab 36m x 24m",
        (0, 0, -38),
        (3600, 2400, 60),
        "Concrete",
        folder,
        solid=True,
    )
    for x in range(-1600, 1800, 400):
        box("Concrete expansion joint X", (x, 0, -7.6), (1.5, 2380, 0.4), "Grid", folder + "/Floor")
    for y in range(-1000, 1200, 400):
        box("Concrete expansion joint Y", (0, y, -7.5), (3580, 1.5, 0.4), "Grid", folder + "/Floor")
    # 카메라를 향한 벽은 낮추고 열린 트러스로 건물 규모를 표현합니다.
    box("West insulated wall", (-1810, 0, 190), (30, 2400, 400), "Wall", folder, solid=True)
    box("West upper fascia", (-1810, 0, 748), (30, 2400, 155), "Wall", folder)
    box("North wall central pier", (0, -1210, 185), (1400, 30, 390), "Wall", folder, solid=True)
    for x in (-1700, 1700):
        box("North wall corner pier", (x, -1210, 185), (200, 30, 390), "Wall", folder, solid=True)
    box("North window backing", (0, -1210, 525), (3600, 30, 290), "Wall", folder)
    box("North upper fascia", (0, -1210, 748), (3600, 30, 155), "Wall", folder)
    box("East cutaway wall", (1810, 0, 20), (30, 2400, 60), "Wall", folder)
    for x, width in ((-1050, 1500), (1350, 900)):
        box("South open loading frontage", (x, 1210, 20), (width, 30, 60), "Wall", folder)
    for x in (-1300, -440, 440, 1300):
        window("North clerestory", (x, -1187, 530), 650)
    for y in (-780, 0, 780):
        window("West clerestory", (-1787, y, 530), 590, side=True)

    for side_x in (-1735, 1735):
        for y in (-1100, 0, 1100):
            label = f"Structural column {side_x} {y}"
            box(label + " foot", (side_x, y, 2), (120, 120, 20), "Black", folder + "/Steel")
            box(label, (side_x, y, 410), (42, 55, 820), "Steel", folder + "/Steel", solid=True)
            box(
                label + " safety sleeve",
                (side_x, y, 95),
                (51, 64, 170),
                "Yellow",
                folder + "/Steel",
            )
            box(label + " cap", (side_x, y, 821), (100, 80, 18), "LightSteel", folder + "/Steel")
    # 뒤쪽 트러스와 외곽 레일로 건물의 부피를 표현합니다.
    # 지붕 일부를 열어 생산 바닥이 보이도록 합니다.
    for y in (-1100,):
        box("Roof truss lower chord", (0, y, 760), (3500, 22, 22), "Steel", folder + "/OpenRoof")
        box(
            "Roof truss upper chord",
            (0, y, 850),
            (3500, 22, 22),
            "LightSteel",
            folder + "/OpenRoof",
        )
        for index in range(8):
            x = -1735 + index * 433.75
            beam(
                "Roof truss diagonal",
                (x, y, 765 if index % 2 == 0 else 845),
                (x + 433.75, y, 845 if index % 2 == 0 else 765),
                13,
                "Steel",
                folder + "/OpenRoof",
            )
    for x in (-1735, 1735):
        box("Longitudinal roof rail", (x, 0, 840), (20, 2240, 24), "Steel", folder + "/OpenRoof")
    box("North cyan identity band", (0, -1177, 710), (3540, 12, 27), "Cyan", folder)
    box("West cyan identity band", (-1777, 0, 710), (12, 2320, 27), "Cyan", folder)

    for number, x in enumerate((-1150, 1150), 1):
        box(
            f"Loading bay {number} door",
            (x, -1190, 190),
            (800, 24, 390),
            "Asphalt",
            "02_Logistics/LoadingBays",
        )
        for dx in (-405, 405):
            box(
                "Bay protective jamb",
                (x + dx, -1160, 210),
                (24, 65, 435),
                "Yellow",
                "02_Logistics/LoadingBays",
            )
        box(
            "Loading bay lintel",
            (x, -1160, 422),
            (835, 65, 28),
            "Steel",
            "02_Logistics/LoadingBays",
        )
        for z in (45, 100, 155, 210, 265, 320, 375):
            box("Roller door seam", (x, -1174, z), (770, 7, 5), "Steel", "02_Logistics/LoadingBays")
        text(f"Loading bay {number} sign", f"DOCK 0{number}  /  LOGISTICS", (x, -1128, 465), 40)
    text(
        "Hall identity",
        "SMART FACTORY   /   AUTOMATION HALL",
        (0, -1150, 755),
        55,
        color=(60, 210, 235),
    )


def lanes_and_cell_zones():
    folder = "03_FloorMarkings"
    box("Central circulation aisle", (0, 15, -7.0), (3440, 260, 0.6), "Asphalt", folder)
    box("South logistics spur", (780, 650, -7.0), (230, 1050, 0.6), "Asphalt", folder)
    for y in (-130, 160):
        box("Aisle safety boundary", (0, y, -6.5), (3420, 6, 0.6), "Yellow", folder)
    for x in (650, 910):
        box("Logistics spur boundary", (x, 710, -6.5), (6, 925, 0.6), "Yellow", folder)
    for x in range(-1500, 1700, 300):
        box("Centre aisle dashed guide", (x, 15, -6.3), (100, 4, 0.6), "White", folder)
    for x in (-1570, 1480):
        for y in (-75, -25, 25, 75, 125):
            box("Pedestrian crossing", (x, y, -6.0), (90, 18, 0.6), "White", folder)
    for index, (x, y, _) in enumerate(CELL_ORIGINS, 1):
        for dx in (-290, 290):
            box(f"Cell {index:02d} side boundary", (x + dx, y, -6.2), (5, 470, 0.6), "Cyan", folder)
        for dy in (-235, 235):
            box(f"Cell {index:02d} end boundary", (x, y + dy, -6.2), (585, 5, 0.6), "Cyan", folder)
        text(
            f"Cell {index:02d} floor stencil",
            f"CELL {index:02d}",
            (x, y + 190, -5.8),
            44,
            color=(75, 200, 224),
            yaw=-90,
            floor=True,
        )
    text("Aisle floor stencil", "MATERIAL FLOW", (-550, 90, -5.8), 33, yaw=-90, floor=True)


def rack(label, x, y, width=350):
    folder = "02_Logistics/StorageRacks"
    for dx in (-width * 0.5, width * 0.5):
        for dy in (-85, 85):
            box(
                label + " upright", (x + dx, y + dy, 180), (16, 18, 370), "Cyan", folder, solid=True
            )
    for z in (40, 155, 270):
        box(label + " shelf", (x, y, z), (width, 174, 9), "Steel", folder)
        for dy in (-92, 92):
            box(label + " load beam", (x, y + dy, z - 5), (width + 20, 12, 19), "Orange", folder)
        for number, dx in enumerate((-width * 0.26, width * 0.20)):
            box(
                label + " stored carton",
                (x + dx, y, z + 44),
                (width * 0.32, 125, 78),
                "Cardboard" if number == 0 else "Cabinet",
                folder + "/Stock",
                solid=True,
            )
    beam(
        label + " rear brace",
        (x - width * 0.5, y - 95, 50),
        (x + width * 0.5, y - 95, 345),
        9,
        "Steel",
        folder,
    )


def pallet(label, x, y, rotation=0):
    folder = "02_Logistics/Pallets"
    # 간단한 메시 네 개로 편집 가능한 팔레트 형태를 표현합니다.
    for dx in (-50, 0, 50):
        box(label + " runner", (x + dx, y, 0), (18, 125, 14), "Cardboard", folder)
    box(label + " deck", (x, y, 10), (128, 128, 8), "Cardboard", folder)
    box(
        label + " load",
        (x, y, 58),
        (110, 108, 85),
        "Cabinet",
        folder,
        unreal.Rotator(0, rotation, 0),
        solid=True,
    )
    box(label + " shipping band", (x, y, 102), (20, 108, 2), "Cyan", folder)


def equipment():
    rack("Inbound material rack A", -1380, 500)
    rack("Inbound material rack B", -1380, 955)
    rack("Finished goods rack", 1370, 650)
    for index, (x, y) in enumerate(((-1100, -890), (1150, -890), (1370, 970)), 1):
        pallet(f"Shipping pallet {index:02d}", x, y)
    text("Storage zone stencil", "INBOUND STORAGE", (-1370, 200, -5.8), 38, yaw=-90, floor=True)
    text("Outbound zone stencil", "FINISHED GOODS", (1370, 385, -5.8), 33, yaw=-90, floor=True)
    for index, x in enumerate((-550, -310, 1130, 1370), 1):
        y = 960 if index < 3 else 240
        folder = "04_Utilities"
        box(f"Service cabinet {index} plinth", (x, y, 4), (120, 85, 24), "Black", folder)
        box(f"Service cabinet {index}", (x, y, 120), (112, 75, 215), "Cabinet", folder, solid=True)
        box(
            f"Service cabinet {index} control strip",
            (x, y + 39, 153),
            (88, 5, 66),
            "Asphalt",
            folder,
        )
        box(f"Service cabinet {index} screen", (x - 17, y + 43, 164), (38, 4, 32), "Cyan", folder)
    # 낮은 가드로 시야를 유지하면서 컨베이어 진입부를 구분합니다.
    folder = "05_Safety"
    for y in (-670, -455, -240):
        box(
            "East cell safety fence post",
            (1160, y, 90),
            (12, 12, 195),
            "Yellow",
            folder,
            solid=True,
        )
    for z in (40, 160):
        box("East cell safety rail", (1160, -455, z), (8, 445, 10), "Yellow", folder)
    for y in range(-650, -240, 68):
        box("East safety fence infill", (1160, y, 102), (4, 4, 114), "Steel", folder)


def place_cells(cell_class):
    defaults = {}
    defaults["material_palette"] = {unreal.Name(name): MATERIALS[name] for name in PALETTE_NAMES}
    for index, origin in enumerate(CELL_ORIGINS):
        cell_id = f"Cell{index + 1:02d}"
        cell = actor(
            cell_class,
            f"CELL {index + 1:02d} - Conveyor and Robotic Sorting",
            "06_ActiveCells/" + cell_id,
            origin,
            tags=("SmartFactoryCell", cell_id),
        )
        for name, value in defaults.items():
            cell.set_editor_property(name, value)
        cell.get_bridge().set_editor_property("port", 9847 + index)
        cell.bind_authored_components()
        require(
            len(cell.get_components_by_class(unreal.StaticMeshComponent)) == 120,
            "Cell preview has insufficient visible geometry: " + cell_id,
        )
        require(
            not cell.get_bridge().get_editor_property("connected"),
            "Editor cell unexpectedly connected.",
        )


def lighting_and_camera():
    folder = "07_LightingAndView"
    rotation = unreal.MathLibrary.find_look_at_rotation(
        unreal.Vector(*CAMERA_POSITION), unreal.Vector(*CAMERA_TARGET)
    )
    camera = actor(
        unreal.CameraActor,
        "HALL OVERVIEW - Four Production Cells",
        folder,
        CAMERA_POSITION,
        rotation,
        ("SmartFactoryCamera",),
    )
    camera.get_component_by_class(unreal.CameraComponent).set_editor_property("field_of_view", 55.0)
    sky = actor(unreal.SkyLight, "Factory Single Light - Bright Neutral White", folder)
    light = sky.get_component_by_class(unreal.SkyLightComponent)
    light.set_mobility(unreal.ComponentMobility.MOVABLE)
    light.set_real_time_capture(False)
    light.set_editor_property("source_type", unreal.SkyLightSourceType.SLS_SPECIFIED_CUBEMAP)
    light.set_cubemap(load(ROOT + "/Lighting/T_FactoryNeutralWhite", unreal.TextureCube))
    light.set_intensity(12.0)
    light.set_editor_property("cast_shadows", False)
    light.set_editor_property("lower_hemisphere_is_black", False)
    post = actor(unreal.PostProcessVolume, "Hall exposure", folder)
    post.set_editor_property("unbound", True)
    settings = post.get_editor_property("settings")
    settings.set_editor_property("override_auto_exposure_min_brightness", True)
    settings.set_editor_property("override_auto_exposure_max_brightness", True)
    settings.set_editor_property("auto_exposure_min_brightness", 1.0)
    settings.set_editor_property("auto_exposure_max_brightness", 1.0)
    settings.set_editor_property("override_auto_exposure_bias", True)
    settings.set_editor_property("auto_exposure_bias", 1.0)
    settings.set_editor_property("override_bloom_intensity", True)
    settings.set_editor_property("bloom_intensity", 0.03)
    post.set_editor_property("settings", settings)


def verify_map(cell_class, mode_class, rebuild=False):
    actors = ACTORS.get_all_level_actors()
    cells = [item for item in actors if item.get_class() == cell_class]
    require(len(cells) == 4, "Hall must contain exactly four persistent working cells.")
    found_ids = set()
    details = []
    for cell in cells:
        tags = {str(tag) for tag in cell.get_editor_property("tags")}
        cell_id = next(
            (f"Cell{index + 1:02d}" for index in range(4) if f"Cell{index + 1:02d}" in tags), None
        )
        require(
            cell_id is not None and cell_id not in found_ids,
            "Cell tags must be unique Cell01..Cell04.",
        )
        found_ids.add(cell_id)
        index = int(cell_id[-2:]) - 1
        count = len(cell.get_components_by_class(unreal.StaticMeshComponent))
        require(count == 120, "Saved cell geometry is missing: " + cell_id)
        if rebuild:
            cell.bind_authored_components()
            require(
                count == len(cell.get_components_by_class(unreal.StaticMeshComponent)),
                "Rebuilding duplicated saved geometry: " + cell_id,
            )
        location = cell.get_actor_location()
        require(
            all(
                abs(a - b) < 0.01
                for a, b in zip((location.x, location.y, location.z), CELL_ORIGINS[index])
            ),
            "Cell origin mismatch: " + cell_id,
        )
        scale = cell.get_actor_scale3d()
        require(
            all(abs(value - 1.0) < 1e-6 for value in (scale.x, scale.y, scale.z)),
            "Cell scale must remain one.",
        )
        bridge = cell.get_bridge()
        port = bridge.get_editor_property("port")
        require(port == 9847 + index, "Persisted cell endpoint mismatch: " + cell_id)
        require(
            not bridge.get_editor_property("connected"),
            "Editor construction unexpectedly connected to Isaac.",
        )
        details.append(
            {
                "id": cell_id,
                "label": cell.get_actor_label(),
                "port": port,
                "origin_cm": [location.x, location.y, location.z],
                "mesh_components": count,
            }
        )
    static_actors = [item for item in actors if isinstance(item, unreal.StaticMeshActor)]
    require(len(static_actors) < 500, "Scenery exceeded the 500-static-actor authoring budget.")
    for owner in [*static_actors, *cells]:
        for component in owner.get_components_by_class(unreal.StaticMeshComponent):
            mesh = component.get_editor_property("static_mesh")
            material = component.get_material(0)
            require(
                mesh is not None and mesh.get_path_name().startswith(ROOT + "/Meshes/"),
                "Scenery/cell uses a missing or non-project mesh.",
            )
            require(
                isinstance(material, unreal.MaterialInstanceConstant)
                and material.get_path_name().startswith(ROOT + "/Materials/"),
                "Scenery/cell uses a missing or transient material.",
            )
    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    require(
        world.get_world_settings().get_editor_property("default_game_mode") == mode_class,
        "Hall GameMode is not the saved SmartFactory GameMode.",
    )
    cameras = [
        item
        for item in actors
        if isinstance(item, unreal.CameraActor)
        and "SmartFactoryCamera" in [str(tag) for tag in item.get_editor_property("tags")]
    ]
    require(len(cameras) == 1, "Hall overview camera missing or duplicated.")
    REPORT.update(
        {
            "cells": sorted(details, key=lambda item: item["id"]),
            "actor_count": len(actors),
            "scenery_static_actor_count": len(static_actors),
            "cell_mesh_component_count": sum(item["mesh_components"] for item in details),
            "persistent_references_verified": True,
            "four_ports_verified": True,
            "default_game_mode": mode_class.get_path_name(),
        }
    )


def focus_hall_viewport():
    """맵 로드 후 사용할 선택적 GUI 보조 기능입니다. 생성 커맨드릿은 호출하지 않습니다."""
    editor = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
    rotation = unreal.MathLibrary.find_look_at_rotation(
        unreal.Vector(*CAMERA_POSITION), unreal.Vector(*CAMERA_TARGET)
    )
    editor.set_level_viewport_camera_info(unreal.Vector(*CAMERA_POSITION), rotation)


def main():
    global ACTORS
    try:
        ACTORS = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
        levels = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
        cell_class = unreal.EditorAssetLibrary.load_blueprint_class(CELL_BP_PATH)
        mode_class = unreal.EditorAssetLibrary.load_blueprint_class(MODE_BP_PATH)
        require(
            cell_class is not None and mode_class is not None,
            "Create the existing factory Blueprint assets first.",
        )
        for shape in ("Cube", "Cylinder", "Sphere"):
            MESHES[shape] = load(ROOT + "/Meshes/SM_Factory" + shape, unreal.StaticMesh)
        load_materials()
        if unreal.EditorAssetLibrary.does_asset_exist(MAP_PATH):
            require(
                levels.load_level(MAP_PATH), "Could not load the existing hall; it was preserved."
            )
            REPORT["preserved_assets"].append(MAP_PATH)
            verify_map(cell_class, mode_class)
        else:
            world = unreal.EditorLoadingAndSavingUtils.new_blank_map(save_existing_map=False)
            require(world is not None, "Could not create an unsaved hall world.")
            architecture()
            lanes_and_cell_zones()
            equipment()
            place_cells(cell_class)
            lighting_and_camera()
            world.get_world_settings().set_editor_property("default_game_mode", mode_class)
            verify_map(cell_class, mode_class, rebuild=True)
            ACTORS.clear_actor_selection_set()
            require(
                unreal.EditorLoadingAndSavingUtils.save_map(world, MAP_PATH),
                "Could not save the completed hall.",
            )
            REPORT["created_assets"].append(MAP_PATH)
            require(levels.load_level(MAP_PATH), "Could not reload the completed hall.")
            verify_map(cell_class, mode_class)
            REPORT["saved_map_reload_verified"] = True
        REPORT["success"] = True
    except Exception as error:
        REPORT["error"] = str(error)
        REPORT["traceback"] = traceback.format_exc()
        unreal.log_error("LARGE_FACTORY_FAILED " + str(error))
        raise
    finally:
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(json.dumps(REPORT, indent=2, ensure_ascii=False), encoding="utf-8")
        unreal.log("LARGE_FACTORY_RESULT " + json.dumps(REPORT))


if __name__ == "__main__":
    main()
