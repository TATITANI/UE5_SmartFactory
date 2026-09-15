"""새 프로세스에서 저장된 메시 에셋, 컴포넌트 연결 및 맵을 검사합니다."""

import json
from pathlib import Path
import unreal

root = Path(__file__).resolve().parents[2]
levels = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
actors = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
report = {"success": False, "maps": [], "play_started": False}
sources = json.loads((root / "Tools/Unreal/Data/MegascansSources.json").read_text())
assert len(sources) == 5
for source in sources.values():
    assert source["quality"] == "High" and unreal.load_asset(source["asset"])
    for info in source["textures"].values():
        tex = unreal.load_asset(info["path"])
        assert tex and tex.blueprint_get_size_x() >= 4096 and tex.blueprint_get_size_y() >= 4096
report["megascans_high_sources"] = len(sources)


def validate_material(material):
    assert isinstance(material, unreal.MaterialInstanceConstant)
    assert material.get_path_name().startswith("/Game/SmartFactory/Materials/")
    parent = material.parent
    assert parent and "/Materials/Megascans/MI_MS_" in parent.get_path_name()
    assert parent.parent.get_path_name().startswith(
        "/Game/SmartFactory/Materials/M_MegascansFactorySurface."
    )
    textures = [
        unreal.MaterialEditingLibrary.get_material_instance_texture_parameter_value(material, n)
        for n in unreal.MaterialEditingLibrary.get_texture_parameter_names(material)
    ]
    assert any(
        t and "/Fab/Megascans/Surfaces/" in t.get_path_name() and "/High/" in t.get_path_name()
        for t in textures
    )


for name, expected_ports in [
    ("L_SmartFactory", [9847]),
    ("L_SmartFactoryHall", [9847, 9848, 9849, 9850]),
]:
    path = "/Game/SmartFactory/Maps/" + name
    assert levels.load_level(path)
    cells = [
        a for a in actors.get_all_level_actors() if isinstance(a, unreal.SmartFactoryCellActor)
    ]
    assert sorted(c.get_bridge().get_editor_property("port") for c in cells) == expected_ports
    for cell in cells:
        parts = cell.get_components_by_class(unreal.StaticMeshComponent)
        names = sorted(c.get_path_name() for c in parts)
        assert len(parts) == 120, (cell.get_actor_label(), len(parts))
        for _ in range(2):
            cell.bind_authored_components()
            assert cell.get_editor_property("scene_ready")
            assert (
                sorted(
                    c.get_path_name()
                    for c in cell.get_components_by_class(unreal.StaticMeshComponent)
                )
                == names
            )
        assert not cell.get_bridge().get_editor_property("connected")
        for c in parts:
            assert c.static_mesh and c.static_mesh.get_path_name().startswith(
                "/Game/SmartFactory/Meshes/Equipment/"
            )
            assert "SmartFactoryGeneratedGeometry" not in [str(t) for t in c.component_tags]
            assert all(
                m and not isinstance(m, unreal.MaterialInstanceDynamic) for m in c.get_materials()
            )
            for material in c.get_materials():
                validate_material(material)
        products = [c for c in parts if "Product" in [str(t) for t in c.component_tags]]
        assert len(products) == 64 and all(not c.get_editor_property("visible") for c in products)
    scenery = 0
    for actor in actors.get_all_level_actors():
        if isinstance(actor, unreal.SmartFactoryCellActor):
            continue
        for component in actor.get_components_by_class(unreal.StaticMeshComponent):
            if component.get_editor_property("is_editor_only"):
                continue
            if not component.static_mesh:
                continue
            assert "/Meshes/Scenery/" in component.static_mesh.get_path_name(), (
                actor.get_actor_label(),
                component.get_name(),
                component.static_mesh.get_path_name(),
            )
            for material in component.get_materials():
                validate_material(material)
            scenery += 1
    report["maps"].append(
        {
            "path": path,
            "cells": len(cells),
            "ports": expected_ports,
            "components_per_cell": 120,
            "product_pool_per_cell": 64,
            "stable_component_identity": True,
            "megascans_scenery_components": scenery,
        }
    )
report["success"] = True
(root / "Saved/Tests/StaticFactoryValidation.json").write_text(json.dumps(report, indent=2))
unreal.log("STATIC_FACTORY_VALIDATION_PASSED")
