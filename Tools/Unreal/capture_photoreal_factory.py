"""저장된 재질을 검토할 화면을 캡처합니다. 임시 카메라는 저장하지 않습니다."""

import time, traceback
from pathlib import Path
import unreal

OUT = Path(__file__).resolve().parents[2] / "Saved/Tests"
unreal.EditorPythonScripting.set_keep_python_script_alive(True)
levels = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
actors = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
levels.load_level("/Game/SmartFactory/Maps/L_SmartFactoryHall")
overview = next(
    a for a in actors.get_all_level_actors() if "SmartFactoryCamera" in [str(t) for t in a.tags]
)
camera = actors.spawn_actor_from_class(unreal.CameraActor, unreal.Vector(400, 130, 320))
camera.set_actor_rotation(
    unreal.MathLibrary.find_look_at_rotation(
        camera.get_actor_location(), unreal.Vector(-20, -450, 75)
    ),
    False,
)
camera.get_component_by_class(unreal.CameraComponent).set_field_of_view(44)
actors.clear_actor_selection_set()
started = time.time()
stage = 0


def tick(dt):
    global stage
    try:
        if stage == 0 and time.time() - started > 20:
            unreal.AutomationLibrary.take_high_res_screenshot(
                1920,
                1080,
                str(OUT / "PhotorealCloseup.png"),
                camera=camera,
                delay=8,
                force_game_view=True,
            )
            stage = 1
        elif (
            stage == 1
            and (OUT / "PhotorealCloseup.png").exists()
            and (OUT / "PhotorealCloseup.png").stat().st_mtime > started
        ):
            unreal.AutomationLibrary.take_high_res_screenshot(
                1920,
                1080,
                str(OUT / "PhotorealHall.png"),
                camera=overview,
                delay=8,
                force_game_view=True,
            )
            stage = 2
        elif (
            stage == 2
            and (OUT / "PhotorealHall.png").exists()
            and (OUT / "PhotorealHall.png").stat().st_mtime > started
        ):
            actors.destroy_actor(camera)
            unreal.unregister_slate_post_tick_callback(handle)
            unreal.SystemLibrary.quit_editor()
        elif time.time() - started > 180:
            raise RuntimeError("Capture timeout")
    except Exception:
        (OUT / "PhotorealCaptureError.txt").write_text(traceback.format_exc())
        unreal.unregister_slate_post_tick_callback(handle)
        unreal.SystemLibrary.quit_editor()


handle = unreal.register_slate_post_tick_callback(tick)
