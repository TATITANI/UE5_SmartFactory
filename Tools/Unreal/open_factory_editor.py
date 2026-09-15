"""저장된 공장을 에디터에서 열고 Play 이전 화면을 캡처합니다."""

from pathlib import Path
import sys
import json
import time
import unreal

unreal.EditorPythonScripting.set_keep_python_script_alive(True)
root = Path(__file__).resolve().parents[2]
single_cell = "--single-cell" in sys.argv
save_editor_view = "--save-editor-view" in sys.argv
map_path = "/Game/SmartFactory/Maps/" + ("L_SmartFactory" if single_cell else "L_SmartFactoryHall")
level = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
if not level.load_level(map_path):
    raise RuntimeError("Could not open the saved factory map.")
actors = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
actors.clear_actor_selection_set()
camera = next(
    actor
    for actor in actors.get_all_level_actors()
    if "SmartFactoryCamera" in [str(tag) for tag in actor.tags]
)
editor = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
editor.set_level_viewport_camera_info(camera.get_actor_location(), camera.get_actor_rotation())
if save_editor_view and not level.save_current_level():
    raise RuntimeError("Could not save the initial editor overview camera.")
unreal.EditorAssetLibrary.sync_browser_to_objects([map_path])
world = editor.get_editor_world()
unreal.SystemLibrary.execute_console_command(world, "t.MaxFPS 30")
output = (
    root
    / "Saved"
    / "Tests"
    / ("FactoryEditorPreview.png" if single_cell else "FactoryHallEditor.png")
)
output.parent.mkdir(parents=True, exist_ok=True)
capture_started = time.time()
capture_task = unreal.AutomationLibrary.take_high_res_screenshot(
    1600 if not single_cell else 1280,
    900 if not single_cell else 720,
    str(output),
    camera=camera,
    delay=2.0,
    force_game_view=True,
)
unreal.log(
    "FACTORY_EDITOR_PREVIEW_READY: Saved map open in editor before Play; screenshot requested: "
    + str(output)
)

if "--qa-close" in sys.argv:

    def finish_editor_check(delta_seconds):
        if not capture_task.is_task_done() and time.time() - capture_started < 120:
            return
        cells = [
            item
            for item in actors.get_all_level_actors()
            if isinstance(item, unreal.SmartFactoryCellActor)
        ]
        counts = [len(item.get_components_by_class(unreal.StaticMeshComponent)) for item in cells]
        ports = sorted(item.get_bridge().get_editor_property("port") for item in cells)
        expected_ports = [9847] if single_cell else [9847, 9848, 9849, 9850]
        screenshot_saved = output.is_file() and output.stat().st_mtime >= capture_started - 1
        disconnected = all(not item.get_bridge().get_editor_property("connected") for item in cells)
        result = {
            "success": screenshot_saved
            and ports == expected_ports
            and counts == [120] * len(expected_ports)
            and disconnected,
            "map": map_path,
            "play_started": False,
            "ports": ports,
            "mesh_counts": counts,
            "editor_bridges_disconnected": disconnected,
            "screenshot_saved": screenshot_saved,
            "screenshot": str(output),
            "initial_editor_view_saved": save_editor_view,
        }
        (root / "Saved" / "Tests" / "FactoryHallEditorValidation.json").write_text(
            json.dumps(result, indent=2), encoding="utf-8"
        )
        unreal.log("FACTORY_EDITOR_QA_RESULT " + json.dumps(result))
        unreal.unregister_slate_post_tick_callback(qa_callback)
        unreal.SystemLibrary.quit_editor()

    qa_callback = unreal.register_slate_post_tick_callback(finish_editor_check)
