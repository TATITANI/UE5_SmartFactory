"""에디터에서 메시 에셋을 베이크하고 블루프린트 컴포넌트를 저장합니다.

SmartFactoryEditor 빌드 후 실행합니다. 런타임 생성 스크립트는 사용하지 않습니다.
원본 매니페스트에는 편집 가능한 최초 셀 구성이 들어 있습니다."""

import copy
import json
from pathlib import Path
import unreal

unreal.EditorPythonScripting.set_keep_python_script_alive(True)

PROJECT = Path(__file__).resolve().parents[2]
ROOT = "/Game/SmartFactory"
DEST = ROOT + "/Meshes/Equipment"
BP_PATH = ROOT + "/Blueprints/BP_SmartFactoryCell"
SOURCE = json.loads((Path(__file__).parent / "Data/CellAssembly.json").read_text())
ACTORS = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
MESHES = unreal.get_editor_subsystem(unreal.StaticMeshEditorSubsystem)
SUB = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
LIB = unreal.SubobjectDataBlueprintFunctionLibrary
report = {"meshes": [], "maps": [], "success": False}


def save(obj):
    assert unreal.EditorAssetLibrary.save_loaded_asset(
        obj, only_if_is_dirty=False
    ), obj.get_path_name()


def bake(name, parts):
    path = DEST + "/SM_" + name
    if unreal.EditorAssetLibrary.does_asset_exist(path):
        mesh = unreal.load_asset(path)
        report["meshes"].append(mesh.get_path_name())
        return mesh
    sources = []
    for part in parts:
        a = ACTORS.spawn_actor_from_class(
            unreal.StaticMeshActor,
            unreal.Vector(*part["position"]),
            unreal.Rotator(*part["rotation"]),
        )
        c = a.static_mesh_component
        c.set_static_mesh(unreal.load_asset(part["mesh"]))
        a.set_actor_scale3d(unreal.Vector(*part["scale"]))
        for i, mat in enumerate(part["materials"]):
            c.set_material(i, unreal.load_asset(mat))
        sources.append(a)
    settings = unreal.MeshMergingSettings()
    settings.set_editor_property("pivot_type", unreal.MeshMergePivotType.WORLD_ORIGIN)
    settings.set_editor_property("merge_materials", False)
    settings.set_editor_property("generate_light_map_uv", True)
    options = unreal.MergeStaticMeshActorsOptions()
    # 메시 병합 시스템이 SM_ 접두사를 자동으로 추가합니다.
    options.set_editor_property("base_package_name", DEST + "/" + name)
    options.set_editor_property("destroy_source_actors", True)
    options.set_editor_property("spawn_merged_actor", True)
    options.set_editor_property("mesh_merging_settings", settings)
    merged = MESHES.merge_static_mesh_actors(sources, options)
    assert merged, "Mesh merge failed: " + name
    mesh = merged.static_mesh_component.static_mesh
    save(mesh)
    ACTORS.destroy_actor(merged)
    report["meshes"].append(mesh.get_path_name())
    return mesh


unreal.EditorLoadingAndSavingUtils.new_blank_map(save_existing_map=False)
unreal.EditorAssetLibrary.make_directory(DEST)
bp = unreal.load_asset(BP_PATH)
handles = SUB.k2_gather_subobject_data_for_blueprint(bp)
root_handle = next(h for h in handles if LIB.is_root_component(LIB.get_data(h)))
existing = {str(LIB.get_variable_name(LIB.get_data(h))) for h in handles}


def component(name, mesh, part=None, tag=None, hidden=False):
    if name in existing:
        return
    params = unreal.AddNewSubobjectParams(
        parent_handle=root_handle, new_class=unreal.StaticMeshComponent, blueprint_context=bp
    )
    handle, error = SUB.add_new_subobject(params)
    assert LIB.is_handle_valid(handle), str(error)
    assert SUB.rename_subobject(handle, unreal.Text(name))
    obj = LIB.get_object_for_blueprint(LIB.get_data(handle), bp)
    obj.set_static_mesh(mesh)
    obj.set_editor_property("mobility", unreal.ComponentMobility.MOVABLE)
    obj.set_collision_profile_name("NoCollision")
    obj.set_editor_property("generate_overlap_events", False)
    obj.set_editor_property("component_tags", [unreal.Name(tag)] if tag else [])
    obj.set_editor_property("visible", not hidden)
    if part:
        obj.set_editor_property("relative_location", unreal.Vector(*part["position"]))
        obj.set_editor_property("relative_rotation", unreal.Rotator(*part["rotation"]))
    existing.add(name)


groups = {
    "CellFloor": list(range(0, 49)),
    "ConveyorFrame": list(range(49, 78)) + list(range(104, 108)),
    "SortingTable": list(range(109, 114)),
    "RedBin": list(range(114, 121)),
    "BlueBin": list(range(121, 128)),
    "RobotPedestal": list(range(128, 141)),
    "ControlCabinet": list(range(159, 176)) + [177, 179, 181, 182],
    "SafetyRail": list(range(183, 191)),
}
for name, indices in groups.items():
    component(name, bake(name, [SOURCE[i] for i in indices]))

arm = [
    "Housing",
    "Shoulder",
    "ShoulderCap",
    "ShoulderBolt",
    "Elbow",
    "ElbowCap",
    "ElbowBolt",
    "Wrist",
    "WristCap",
    "WristBolt",
    "Upper",
    "Forearm",
    "UpperPanel",
    "ForearmPanel",
    "Tool",
    "Gripper",
    "LeftFinger",
    "RightFinger",
]
for i, name in enumerate(arm, 141):
    part = copy.deepcopy(SOURCE[i])
    part["position"] = [0, 0, 0]
    part["rotation"] = [0, 0, 0]
    component("Robot_" + name, bake("Robot_" + name, [part]), SOURCE[i], "Arm:" + name)
part = copy.deepcopy(SOURCE[78])
part["position"] = [0, 0, 0]
slat = bake("ConveyorSlat", [part])
for i in range(26):
    component("BeltSlat_%02d" % i, slat, SOURCE[78 + i], "BeltSlat")
for index, name, tag in [
    (108, "PickupSensor", "Sensor"),
    (176, "SignalGreen", "Signal:0"),
    (178, "SignalAmber", "Signal:1"),
    (180, "SignalRed", "Signal:2"),
]:
    part = copy.deepcopy(SOURCE[index])
    part["position"] = [0, 0, 0]
    component(name, bake(name, [part]), SOURCE[index], tag)
body = copy.deepcopy(SOURCE[0])
body.update(
    position=[0, 0, 0],
    rotation=[0, 0, 0],
    scale=[1, 1, 1],
    materials=[ROOT + "/Materials/MI_FactoryRed.MI_FactoryRed"],
)
inset = copy.deepcopy(body)
inset.update(
    position=[0, 0, 52.5],
    scale=[0.66, 0.64, 0.05],
    materials=[ROOT + "/Materials/MI_FactoryWhite.MI_FactoryWhite"],
)
product = bake("Product", [body, inset])
for i in range(64):
    component("Product_%03d" % i, product, tag="Product", hidden=True)
unreal.BlueprintEditorLibrary.compile_blueprint(bp)
save(bp)

levels = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
for name in ("L_SmartFactory", "L_SmartFactoryHall"):
    path = ROOT + "/Maps/" + name
    if not unreal.EditorAssetLibrary.does_asset_exist(path):
        continue
    assert levels.load_level(path)
    cells = [
        a for a in ACTORS.get_all_level_actors() if isinstance(a, unreal.SmartFactoryCellActor)
    ]
    for cell in cells:
        cell.bind_authored_components()
        assert cell.get_editor_property("scene_ready"), cell.get_actor_label()
        assert len(cell.get_components_by_class(unreal.StaticMeshComponent)) == 120
    assert levels.save_current_level()
    report["maps"].append({"path": path, "cells": len(cells), "components_per_cell": 120})
report["success"] = True
(PROJECT / "Saved/Tests/StaticMeshMigration.json").write_text(json.dumps(report, indent=2))
unreal.log("STATIC_MESH_MIGRATION_COMPLETE")
