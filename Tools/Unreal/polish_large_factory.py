"""새 공장 홀 맵의 개방형 지붕, 구조 및 조명을 보정합니다.

기존 소형 맵과 네 셀의 변환, 포트, 형상 및 재질을 유지합니다.
UnrealEditor-Cmd -NullRHI로 실행합니다."""

from __future__ import annotations

import json
from pathlib import Path
import traceback

import unreal

PROJECT = Path(__file__).resolve().parents[2]
MAP_PATH = "/Game/SmartFactory/Maps/L_SmartFactoryHall"
CAMERA_POSITION = (1200, 2700, 2200)
CAMERA_TARGET = (-400, 0, 0)
ORIGINS = ((-800, -450, 0), (0, -450, 0), (800, -450, 0), (0, 450, 0))
REPORT_PATH = PROJECT / "Saved" / "Tests" / "LargeFactoryPolish.json"
REPORT = {
    "success": False,
    "map": MAP_PATH,
    "removed_roof_or_fixture_actors": [],
    "camera_position_cm": CAMERA_POSITION,
    "camera_target_cm": CAMERA_TARGET,
    "camera_fov": 55,
    "task_light_lumens": 2200,
    "bloom_intensity": 0.03,
    "play_started": False,
}


def check_cells(actors):
    result = []
    for item in actors:
        tags = {str(tag) for tag in item.get_editor_property("tags")}
        ids = [f"Cell{index + 1:02d}" for index in range(4) if f"Cell{index + 1:02d}" in tags]
        if not ids:
            continue
        assert len(ids) == 1, "Cell tags are ambiguous."
        index = int(ids[0][-2:]) - 1
        pos = item.get_actor_location()
        assert all(abs(a - b) < 0.01 for a, b in zip((pos.x, pos.y, pos.z), ORIGINS[index]))
        scale = item.get_actor_scale3d()
        assert all(abs(value - 1) < 1e-6 for value in (scale.x, scale.y, scale.z))
        assert item.get_bridge().get_editor_property("port") == 9847 + index
        assert not item.get_bridge().get_editor_property("connected")
        meshes = item.get_components_by_class(unreal.StaticMeshComponent)
        assert len(meshes) == 120, "Working cell geometry changed unexpectedly."
        result.append(
            {
                "cell_id": ids[0],
                "port": 9847 + index,
                "mesh_components": len(meshes),
                "origin_cm": [pos.x, pos.y, pos.z],
            }
        )
    assert len(result) == 4 and len({item["cell_id"] for item in result}) == 4
    return sorted(result, key=lambda item: item["cell_id"])


def main():
    try:
        levels = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
        actor_system = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
        assert levels.load_level(MAP_PATH), "Could not load the new hall."
        actors = actor_system.get_all_level_actors()
        before = check_cells(actors)
        lights = 0
        cameras = 0
        for item in actors:
            name = item.get_actor_label()
            position = item.get_actor_location()
            remove = (
                (name.startswith("Roof truss") and position.y > -1000)
                or (name.startswith("Longitudinal roof rail") and abs(position.x) < 100)
                or name.startswith("Overhead LED luminaire")
            )
            if remove:
                REPORT["removed_roof_or_fixture_actors"].append(name)
                assert actor_system.destroy_actor(
                    item
                ), "Could not remove the requested roof-cutaway piece."
                continue
            if isinstance(item, unreal.CameraActor) and "SmartFactoryCamera" in [
                str(tag) for tag in item.tags
            ]:
                rotation = unreal.MathLibrary.find_look_at_rotation(
                    unreal.Vector(*CAMERA_POSITION), unreal.Vector(*CAMERA_TARGET)
                )
                item.set_actor_location(unreal.Vector(*CAMERA_POSITION), False, False)
                item.set_actor_rotation(rotation, False)
                item.get_component_by_class(unreal.CameraComponent).set_editor_property(
                    "field_of_view", 55.0
                )
                cameras += 1
            if isinstance(item, unreal.RectLight):
                component = item.get_component_by_class(unreal.RectLightComponent)
                component.set_editor_property("intensity_units", unreal.LightUnits.LUMENS)
                component.set_intensity(2200.0)
                lights += 1
            if isinstance(item, unreal.DirectionalLight):
                item.get_component_by_class(unreal.DirectionalLightComponent).set_intensity(2.5)
            if isinstance(item, unreal.SkyLight):
                item.get_component_by_class(unreal.SkyLightComponent).set_intensity(0.7)
            if isinstance(item, unreal.PostProcessVolume):
                settings = item.get_editor_property("settings")
                settings.set_editor_property("override_bloom_intensity", True)
                settings.set_editor_property("bloom_intensity", 0.03)
                item.set_editor_property("settings", settings)
        assert lights == 4 and cameras == 1
        assert before == check_cells(actor_system.get_all_level_actors())
        actor_system.clear_actor_selection_set()
        assert levels.save_current_level(), "Could not save polished hall."
        assert levels.load_level(MAP_PATH), "Could not reload polished hall."
        REPORT["cells"] = check_cells(actor_system.get_all_level_actors())
        assert before == REPORT["cells"]
        REPORT["saved_map_reload_verified"] = True
        REPORT["actor_count"] = len(actor_system.get_all_level_actors())
        REPORT["success"] = True
    except Exception as error:
        REPORT["error"] = str(error)
        REPORT["traceback"] = traceback.format_exc()
        unreal.log_error("LARGE_FACTORY_POLISH_FAILED " + str(error))
        raise
    finally:
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(json.dumps(REPORT, indent=2), encoding="utf-8")
        unreal.log("LARGE_FACTORY_POLISH_RESULT " + json.dumps(REPORT))


if __name__ == "__main__":
    main()
