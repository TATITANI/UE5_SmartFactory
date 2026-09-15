"""고정 노출과 밝은 HDR SkyLight 하나를 각 공장 맵에 저장합니다."""

import json
from pathlib import Path
import unreal

root = Path(__file__).resolve().parents[2]
actors = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
levels = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
editor = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
lib = unreal.EditorAssetLibrary
cube_path = "/Game/SmartFactory/Lighting/T_FactoryNeutralWhite"
cube = (
    unreal.load_asset(cube_path)
    if lib.does_asset_exist(cube_path)
    else lib.duplicate_asset("/Engine/MapTemplates/Sky/DaylightAmbientCubemap", cube_path)
)
assert cube
cube.set_editor_property("adjust_saturation", 0.0)
lib.save_loaded_asset(cube)
report = {"success": False, "maps": []}
for name in ("L_SmartFactoryHall", "L_SmartFactory"):
    path = "/Game/SmartFactory/Maps/" + name
    if editor.get_editor_world().get_path_name().split(".")[0] != path:
        assert levels.load_level(path)
    existing = actors.get_all_level_actors()
    sky = next((a for a in existing if isinstance(a, unreal.SkyLight)), None)
    if not sky:
        sky = actors.spawn_actor_from_class(unreal.SkyLight, unreal.Vector(0, 0, 600))
    for actor in existing:
        if isinstance(actor, (unreal.Light, unreal.SkyLight)) and actor != sky:
            assert actors.destroy_actor(actor)
    sky.set_actor_label("Factory Single Light - Bright Neutral White")
    sky.set_folder_path("07_LightingAndView")
    light = sky.get_component_by_class(unreal.SkyLightComponent)
    light.set_mobility(unreal.ComponentMobility.MOVABLE)
    light.set_real_time_capture(False)
    light.set_editor_property("source_type", unreal.SkyLightSourceType.SLS_SPECIFIED_CUBEMAP)
    light.set_cubemap(cube)
    light.set_light_color(unreal.LinearColor(1, 1, 1, 1))
    light.set_intensity(12.0)
    light.set_editor_property("cast_shadows", False)
    light.set_editor_property("lower_hemisphere_is_black", False)
    for actor in actors.get_all_level_actors():
        if isinstance(actor, unreal.PostProcessVolume):
            settings = actor.get_editor_property("settings")
            settings.set_editor_property("override_auto_exposure_min_brightness", True)
            settings.set_editor_property("override_auto_exposure_max_brightness", True)
            settings.set_editor_property("auto_exposure_min_brightness", 1.0)
            settings.set_editor_property("auto_exposure_max_brightness", 1.0)
            settings.set_editor_property("override_auto_exposure_bias", True)
            settings.set_editor_property("auto_exposure_bias", 1.0)
            actor.set_editor_property("settings", settings)
    lights = [
        a for a in actors.get_all_level_actors() if isinstance(a, (unreal.Light, unreal.SkyLight))
    ]
    assert len(lights) == 1
    assert levels.save_current_level()
    report["maps"].append(
        {
            "map": path,
            "light_count": 1,
            "type": "SkyLight",
            "intensity": 12.0,
            "exposure_bias": 1.0,
            "color": "white",
            "cubemap": cube_path,
        }
    )
assert levels.load_level("/Game/SmartFactory/Maps/L_SmartFactoryHall")
camera = next(
    a for a in actors.get_all_level_actors() if "SmartFactoryCamera" in [str(t) for t in a.tags]
)
editor.set_level_viewport_camera_info(camera.get_actor_location(), camera.get_actor_rotation())
actors.clear_actor_selection_set()
unreal.AutomationLibrary.take_high_res_screenshot(
    1600,
    900,
    str(root / "Saved/Tests/SingleLightFactory.png"),
    camera=camera,
    delay=8,
    force_game_view=True,
)
report["success"] = True
(root / "Saved/Tests/SingleLightFactory.json").write_text(json.dumps(report, indent=2))
unreal.log("SINGLE_LIGHT_FACTORY_SAVED")
