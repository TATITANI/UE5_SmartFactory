"""Unreal 에디터 Python으로 편집 가능한 공장 에셋을 생성합니다.

최신 네이티브 모듈과 PythonScriptPlugin이 있는 전체 에디터에서 실행합니다.
최초 메시 베이크에는 커맨드릿에서 제공하지 않는 StaticMeshEditorSubsystem이 필요합니다.

기존 에셋과 맵을 보존합니다. Isaac 실행이나 공정 명령 전송 없이 JSON 결과를 저장합니다."""

from __future__ import annotations

import json
from pathlib import Path
import runpy
import traceback

import unreal

ROOT = "/Game/SmartFactory"
MAP_PATH = ROOT + "/Maps/L_SmartFactory"
CELL_BP_PATH = ROOT + "/Blueprints/BP_SmartFactoryCell"
MODE_BP_PATH = ROOT + "/Blueprints/BP_SmartFactoryGameMode"
REPORT_PATH = Path(__file__).resolve().parents[2] / "Saved" / "Tests" / "ContentGeneration.json"
PALETTE = {
    "Floor": (0.085, 0.110, 0.140),
    "Grid": (0.12, 0.16, 0.20),
    "Black": (0.016, 0.024, 0.035),
    "Belt": (0.035, 0.043, 0.051),
    "Slats": (0.075, 0.09, 0.10),
    "Steel": (0.38, 0.46, 0.51),
    "LightSteel": (0.66, 0.72, 0.76),
    "Cabinet": (0.72, 0.78, 0.81),
    "Orange": (0.98, 0.38, 0.025),
    "Yellow": (1.0, 0.68, 0.035),
    "Cyan": (0.015, 0.65, 0.78),
    "Red": (0.85, 0.045, 0.055),
    "Blue": (0.045, 0.22, 0.90),
    "RedTray": (0.36, 0.035, 0.045),
    "BlueTray": (0.025, 0.10, 0.36),
    "Green": (0.10, 0.95, 0.35),
    "White": (0.88, 0.92, 0.93),
}
REPORT = {
    "success": False,
    "created_assets": [],
    "preserved_assets": [],
    "asset_paths": [],
    "actors": [],
    "actor_count": 0,
    "map": MAP_PATH,
    "ros2_enabled": False,
    "policy": "Create missing assets; preserve existing assets and existing map.",
}


def note_asset(path, created):
    REPORT["asset_paths"].append(path)
    REPORT["created_assets" if created else "preserved_assets"].append(path)
    unreal.log("FACTORY_CONTENT_ASSET " + json.dumps({"path": path, "created": created}))


def save_asset(asset):
    if not unreal.EditorAssetLibrary.save_loaded_asset(asset, only_if_is_dirty=False):
        raise RuntimeError("Could not save asset: " + asset.get_path_name())


def existing_asset(path, expected_type):
    if not unreal.EditorAssetLibrary.does_asset_exist(path):
        return None
    asset = unreal.EditorAssetLibrary.load_asset(path)
    if not isinstance(asset, expected_type):
        raise RuntimeError(f"Existing asset has an unexpected type; preserved: {path}")
    note_asset(path, False)
    return asset


def create_asset(path, asset_type, factory):
    folder, name = path.rsplit("/", 1)
    unreal.EditorAssetLibrary.make_directory(folder)
    asset = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
        name, folder, asset_type, factory
    )
    if asset is None:
        raise RuntimeError("Asset creation failed: " + path)
    note_asset(path, True)
    return asset


def create_meshes():
    meshes = {}
    for shape in ("Cube", "Cylinder", "Sphere"):
        path = ROOT + "/Meshes/SM_Factory" + shape
        mesh = existing_asset(path, unreal.StaticMesh)
        if mesh is None:
            unreal.EditorAssetLibrary.make_directory(ROOT + "/Meshes")
            mesh = unreal.EditorAssetLibrary.duplicate_asset("/Engine/BasicShapes/" + shape, path)
            if mesh is None:
                raise RuntimeError("Could not duplicate engine mesh: " + shape)
            note_asset(path, True)
            save_asset(mesh)
        meshes[shape] = mesh
    return meshes


def create_master_material():
    path = ROOT + "/Materials/M_FactorySurface"
    material = existing_asset(path, unreal.Material)
    if material is not None:
        return material
    material = create_asset(path, unreal.Material, unreal.MaterialFactoryNew())
    library = unreal.MaterialEditingLibrary
    color = library.create_material_expression(
        material, unreal.MaterialExpressionVectorParameter, -440, -160
    )
    color.set_editor_property("parameter_name", "Color")
    color.set_editor_property("default_value", unreal.LinearColor(0.72, 0.78, 0.81, 1.0))
    roughness = library.create_material_expression(
        material, unreal.MaterialExpressionScalarParameter, -440, 40
    )
    roughness.set_editor_property("parameter_name", "Roughness")
    roughness.set_editor_property("default_value", 0.45)
    metallic = library.create_material_expression(
        material, unreal.MaterialExpressionScalarParameter, -440, 220
    )
    metallic.set_editor_property("parameter_name", "Metallic")
    metallic.set_editor_property("default_value", 0.0)
    for expression, material_property in (
        (color, unreal.MaterialProperty.MP_BASE_COLOR),
        (roughness, unreal.MaterialProperty.MP_ROUGHNESS),
        (metallic, unreal.MaterialProperty.MP_METALLIC),
    ):
        if not library.connect_material_property(expression, "", material_property):
            raise RuntimeError("Could not connect factory material parameter.")
    compile_errors = library.recompile_material(material)
    if compile_errors:
        REPORT.setdefault("material_compile_messages", []).extend(
            str(value) for value in compile_errors
        )
    save_asset(material)
    return material


def create_palette(master):
    materials = {}
    library = unreal.MaterialEditingLibrary
    for name, rgb in PALETTE.items():
        path = ROOT + "/Materials/MI_Factory" + name
        instance = existing_asset(path, unreal.MaterialInstanceConstant)
        if instance is None:
            instance = create_asset(
                path, unreal.MaterialInstanceConstant, unreal.MaterialInstanceConstantFactoryNew()
            )
            library.set_material_instance_parent(instance, master)
            roughness = 0.8 if name == "Floor" else 0.45
            metallic = 0.65 if name in ("Steel", "LightSteel") else 0.0
            # UE 5.8 MaterialEditingLibrary의 setter는 값을 적용해도
            # 항상 false를 반환하므로 저장된 값을 직접 확인합니다.
            library.set_material_instance_vector_parameter_value(
                instance, "Color", unreal.LinearColor(*rgb, 1.0)
            )
            library.set_material_instance_scalar_parameter_value(instance, "Roughness", roughness)
            library.set_material_instance_scalar_parameter_value(instance, "Metallic", metallic)
            library.update_material_instance(instance)
            saved_color = library.get_material_instance_vector_parameter_value(instance, "Color")
            saved_roughness = library.get_material_instance_scalar_parameter_value(
                instance, "Roughness"
            )
            saved_metallic = library.get_material_instance_scalar_parameter_value(
                instance, "Metallic"
            )
            if (
                any(
                    abs(a - b) > 1e-5
                    for a, b in zip((saved_color.r, saved_color.g, saved_color.b), rgb)
                )
                or abs(saved_roughness - roughness) > 1e-5
                or abs(saved_metallic - metallic) > 1e-5
            ):
                raise RuntimeError("Material parameter readback did not match: " + path)
            save_asset(instance)
        materials[unreal.Name(name)] = instance
    return materials


def create_blueprint(path, native_path, defaults=None):
    blueprint = existing_asset(path, unreal.Blueprint)
    if blueprint is None:
        native_class = unreal.load_class(None, native_path)
        if native_class is None:
            raise RuntimeError(
                "Build and load the SmartFactory native module first: " + native_path
            )
        factory = unreal.BlueprintFactory()
        factory.set_editor_property("parent_class", native_class)
        blueprint = create_asset(path, unreal.Blueprint, factory)
        if unreal.BlueprintEditorLibrary.compile_blueprint(blueprint) is False:
            raise RuntimeError("Blueprint compilation failed: " + path)
        generated = unreal.BlueprintEditorLibrary.generated_class(blueprint)
        if generated is None:
            raise RuntimeError("Blueprint generated class is unavailable: " + path)
        cdo = unreal.get_default_object(generated)
        for key, value in (defaults or {}).items():
            # 속성이 없다면 이전 네이티브 모듈을 사용 중입니다.
            # 설정이 빠진 블루프린트를 만들지 않고 오류를 보고합니다.
            cdo.set_editor_property(key, value)
        save_asset(blueprint)
    generated = unreal.EditorAssetLibrary.load_blueprint_class(path)
    if generated is None:
        raise RuntimeError("Could not load generated Blueprint class: " + path)
    return blueprint, generated


def spawn(actor_system, actor_class, label, folder, tag, location=None, rotation=None):
    actor = actor_system.spawn_actor_from_class(
        actor_class, location or unreal.Vector(), rotation or unreal.Rotator(), transient=False
    )
    if actor is None:
        raise RuntimeError("Could not place actor: " + label)
    actor.set_actor_label(label)
    actor.set_folder_path(unreal.Name(folder))
    actor.set_editor_property("tags", [unreal.Name(tag)])
    return actor


def create_map(cell_class, game_mode_class, cell_defaults):
    level_system = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    actor_system = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    map_exists = unreal.EditorAssetLibrary.does_asset_exist(MAP_PATH)
    if map_exists:
        if not level_system.load_level(MAP_PATH):
            raise RuntimeError("Could not open existing map; it was not modified.")
        note_asset(MAP_PATH, False)
    else:
        unreal.EditorAssetLibrary.make_directory(ROOT + "/Maps")
        # new_level은 빈 에셋을 즉시 저장하므로 사용하지 않습니다.
        # 실패 후 다시 실행할 수 있도록 저장되지 않은 월드에서 구성합니다.
        # 빈 맵이 기존 에셋 보존 규칙에 걸려 재생성이 막히는 일을 방지합니다.
        world = unreal.EditorLoadingAndSavingUtils.new_blank_map(save_existing_map=False)
        if world is None:
            raise RuntimeError("Could not create factory map.")
        cell = spawn(
            actor_system,
            cell_class,
            "Cell 01 - Conveyor and Sorting Robot",
            "01_FactoryCell",
            "SmartFactoryCell",
        )
        # 방금 컴파일한 블루프린트는 다시 로드할 때까지 이전 원형을 유지할 수 있습니다.
        # 첫 배치 셀에도 동일한 기본값을 적용한 후 재구성합니다.
        # 이를 통해 최초 생성 시에도 올바른 설정을 사용합니다.
        for key, value in cell_defaults.items():
            cell.set_editor_property(key, value)
        cell.bind_authored_components()
        component_count = len(cell.get_components_by_class(unreal.StaticMeshComponent))
        cell.bind_authored_components()
        rebuilt_components = cell.get_components_by_class(unreal.StaticMeshComponent)
        if component_count == 0 or component_count != len(rebuilt_components):
            raise RuntimeError("Binding the authored factory components changed their count.")
        for component in rebuilt_components:
            material = component.get_material(0)
            mesh = component.get_editor_property("static_mesh")
            if material is None or not material.get_path_name().startswith(ROOT + "/Materials/"):
                REPORT["failed_component"] = {
                    "path": component.get_path_name(),
                    "material": material.get_path_name() if material else None,
                    "mesh": mesh.get_path_name() if mesh else None,
                    "cell_palette": {
                        str(key): value.get_path_name()
                        for key, value in cell.get_editor_property("material_palette").items()
                    },
                }
                raise RuntimeError(
                    "Factory preview contains an unsaved or missing palette material: "
                    + json.dumps(REPORT["failed_component"])
                )
            if mesh is None or not mesh.get_path_name().startswith(ROOT + "/Meshes/"):
                raise RuntimeError("Factory preview is not using the saved project meshes.")
        REPORT["authored_component_bindings_stable"] = True
        REPORT["preview_uses_saved_meshes_and_materials"] = True
        camera_position = unreal.Vector(460, 570, 380)
        camera_rotation = unreal.MathLibrary.find_look_at_rotation(
            camera_position, unreal.Vector(-55, -35, 75)
        )
        camera = spawn(
            actor_system,
            unreal.CameraActor,
            "Factory Overview Camera",
            "03_View",
            "SmartFactoryCamera",
            camera_position,
            camera_rotation,
        )
        camera.get_component_by_class(unreal.CameraComponent).set_editor_property(
            "field_of_view", 52.0
        )
        sky = spawn(
            actor_system,
            unreal.SkyLight,
            "Factory Single Light - Bright Neutral White",
            "02_Lighting",
            "SmartFactorySky",
        )
        light = sky.get_component_by_class(unreal.SkyLightComponent)
        light.set_mobility(unreal.ComponentMobility.MOVABLE)
        light.set_real_time_capture(False)
        light.set_editor_property("source_type", unreal.SkyLightSourceType.SLS_SPECIFIED_CUBEMAP)
        light.set_cubemap(unreal.load_asset(ROOT + "/Lighting/T_FactoryNeutralWhite"))
        light.set_intensity(12.0)
        light.set_editor_property("cast_shadows", False)
        light.set_editor_property("lower_hemisphere_is_black", False)
        post = spawn(
            actor_system,
            unreal.PostProcessVolume,
            "Factory Exposure",
            "02_Lighting",
            "SmartFactoryPost",
        )
        post.set_editor_property("unbound", True)
        settings = post.get_editor_property("settings")
        settings.set_editor_property("override_auto_exposure_min_brightness", True)
        settings.set_editor_property("override_auto_exposure_max_brightness", True)
        settings.set_editor_property("auto_exposure_min_brightness", 1.0)
        settings.set_editor_property("auto_exposure_max_brightness", 1.0)
        settings.set_editor_property("override_auto_exposure_bias", True)
        settings.set_editor_property("auto_exposure_bias", 1.0)
        post.set_editor_property("settings", settings)
        world.get_world_settings().set_editor_property("default_game_mode", game_mode_class)
        actor_system.clear_actor_selection_set()
        if not unreal.EditorLoadingAndSavingUtils.save_map(world, MAP_PATH):
            raise RuntimeError("Could not save completed factory map.")
        note_asset(MAP_PATH, True)
        if not level_system.load_level(MAP_PATH):
            raise RuntimeError("Could not reload the saved factory map for verification.")
        reloaded_cells = [
            actor
            for actor in actor_system.get_all_level_actors()
            if actor.get_class() == cell_class
        ]
        if (
            len(reloaded_cells) != 1
            or len(reloaded_cells[0].get_components_by_class(unreal.StaticMeshComponent))
            != component_count
        ):
            raise RuntimeError("Saved factory geometry did not survive a map reload.")
        REPORT["preview_survives_map_reload"] = True

    actors = actor_system.get_all_level_actors()
    REPORT["actor_count"] = len(actors)
    REPORT["actors"] = [
        {
            "label": actor.get_actor_label(),
            "class": actor.get_class().get_path_name(),
            "path": actor.get_path_name(),
            "folder": str(actor.get_folder_path()),
            "tags": [str(tag) for tag in actor.get_editor_property("tags")],
        }
        for actor in actors
    ]
    cells = [actor for actor in actors if actor.get_class() == cell_class]
    REPORT["factory_cell_count"] = len(cells)
    REPORT["factory_mesh_component_count"] = sum(
        len(actor.get_components_by_class(unreal.StaticMeshComponent)) for actor in cells
    )
    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    default_mode = world.get_world_settings().get_editor_property("default_game_mode")
    REPORT["default_game_mode"] = default_mode.get_path_name() if default_mode else None
    if not cells or REPORT["factory_mesh_component_count"] == 0:
        raise RuntimeError(
            "Factory map does not contain the expected visible cell. Existing assets were preserved."
        )
    if not map_exists and default_mode != game_mode_class:
        raise RuntimeError("Factory map GameMode was not assigned.")


def main():
    try:
        meshes = create_meshes()
        master = create_master_material()
        palette = create_palette(master)
        cell_defaults = {
            "material_palette": palette,
        }
        _, cell_class = create_blueprint(
            CELL_BP_PATH, "/Script/SmartFactory.SmartFactoryCellActor", cell_defaults
        )
        _, mode_class = create_blueprint(MODE_BP_PATH, "/Script/SmartFactory.SmartFactoryGameMode")
        if not unreal.EditorAssetLibrary.does_asset_exist(ROOT + "/Meshes/Equipment/SM_Product"):
            if not unreal.get_editor_subsystem(unreal.StaticMeshEditorSubsystem):
                raise RuntimeError("Initial static mesh baking requires the full Unreal Editor.")
            runpy.run_path(
                str(Path(__file__).with_name("bake_static_factory.py")), run_name="__main__"
            )
            cell_class = unreal.EditorAssetLibrary.load_blueprint_class(CELL_BP_PATH)
        create_map(cell_class, mode_class, cell_defaults)
        REPORT["success"] = True
    except Exception as error:
        REPORT["error"] = str(error)
        REPORT["traceback"] = traceback.format_exc()
        unreal.log_error("FACTORY_CONTENT_FAILED " + str(error))
        raise
    finally:
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(json.dumps(REPORT, indent=2, ensure_ascii=False), encoding="utf-8")
        unreal.log("FACTORY_CONTENT_REPORT " + str(REPORT_PATH))
        unreal.log(
            "FACTORY_CONTENT_RESULT "
            + json.dumps(
                {
                    "success": REPORT["success"],
                    "asset_count": len(REPORT["asset_paths"]),
                    "actor_count": REPORT["actor_count"],
                }
            )
        )


if __name__ == "__main__":
    main()
