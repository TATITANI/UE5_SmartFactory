"""에디터 전용 재질 작성 도구입니다. Fab Megascans High 에셋 다섯 종류가 필요합니다.

원본을 보존하고 편집 가능한 프로젝트 재질 인스턴스를 생성합니다.
설비와 배경에 재질을 적용하고 실제 단위 UV를 스태틱 메시에 저장합니다."""

import hashlib
import json
from pathlib import Path
import unreal

ROOT = "/Game/SmartFactory"
PROJECT = Path(__file__).resolve().parents[2]
LIB = unreal.EditorAssetLibrary
ML = unreal.MaterialEditingLibrary
SM = unreal.get_editor_subsystem(unreal.StaticMeshEditorSubsystem)
ACTORS = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
LEVELS = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
SOURCES = {
    "Metal": ("Scratched_Metal_uh4obh1c", "uh4obh1c", "122dff26-78f7-4c96-a0ae-57da2a656b0a"),
    "Paint": (
        "Scratched_Painted_Metal_tduwejdc",
        "tduwejdc",
        "ef4f6dd7-4d8d-4a59-b0cf-ac12edbdc2cf",
    ),
    "Concrete": (
        "Industrial_Concrete_Floor_sl2qedtp",
        "sl2qedtp",
        "2dece1ec-0941-406c-a7de-ae9fe08085a1",
    ),
    "Rubber": ("Rubber_rmvtcjup", "rmvtcjup", "e81de902-92c5-47ba-bd8b-ad10be2605b6"),
    "Cardboard": ("Cardboard_qhenlop0", "qhenlop0", "a086adb1-88a1-415c-9f7b-7528b2b79a0a"),
}
report = {
    "success": False,
    "provider": "Quixel Megascans via Fab",
    "quality": "High",
    "sources": {},
    "materials": {},
    "maps": [],
    "equipment_meshes": 0,
}


def save(asset):
    assert LIB.save_loaded_asset(asset, only_if_is_dirty=False), asset.get_path_name()


def duplicate(source, dest):
    asset = (
        unreal.load_asset(dest) if LIB.does_asset_exist(dest) else LIB.duplicate_asset(source, dest)
    )
    assert asset, dest
    return asset


# Fab 표면 셰이더를 복사하고 금속성 제어를 추가합니다.
# 도장, 고무, 금속이 스캔을 공유해도 모두 금속처럼 보이지 않게 합니다.
master = duplicate(
    "/Game/Fab/Materials/Standard/M_MS_Srf", ROOT + "/Materials/M_MegascansFactorySurface"
)
if "Factory Metallic" not in [str(n) for n in ML.get_scalar_parameter_names(master)]:
    metallic = ML.create_material_expression(
        master, unreal.MaterialExpressionScalarParameter, 400, 400
    )
    metallic.set_editor_property("parameter_name", "Factory Metallic")
    metallic.set_editor_property("default_value", 0.0)
    assert ML.connect_material_property(metallic, "", unreal.MaterialProperty.MP_METALLIC)
    ML.recompile_material(master)
save(master)
parents = {}
for role, (folder, scan, listing) in SOURCES.items():
    source_path = f"/Game/Fab/Megascans/Surfaces/{folder}/High/{scan}_tier_1/Materials/MI_{scan}"
    source = unreal.load_asset(source_path)
    assert isinstance(source, unreal.MaterialInstanceConstant), source_path
    parent = duplicate(source_path, ROOT + "/Materials/Megascans/MI_MS_" + role)
    ML.set_material_instance_parent(parent, master)
    ML.update_material_instance(parent)
    save(parent)
    parents[role] = parent
    textures = {}
    for param in ML.get_texture_parameter_names(source):
        tex = ML.get_material_instance_texture_parameter_value(source, param)
        if tex and "/Megascans/" in tex.get_path_name():
            textures[str(param)] = {
                "path": tex.get_path_name(),
                "width": tex.blueprint_get_size_x(),
                "height": tex.blueprint_get_size_y(),
            }
            assert tex.blueprint_get_size_x() >= 4096
    assert textures, source_path
    report["sources"][role] = {
        "asset": source_path,
        "listing": "https://www.fab.com/listings/" + listing,
        "quality": "High",
        "textures": textures,
    }

# 기존 팔레트 경로를 유지하여 저장된 메시와 실행 중 신호 및 제품이
# 동일한 영구 재질 인스턴스를 참조하도록 합니다.
for path in LIB.list_assets(ROOT + "/Materials", recursive=False):
    material = unreal.load_asset(path)
    if not isinstance(material, unreal.MaterialInstanceConstant):
        continue
    name = material.get_name()
    if not name.startswith(("MI_Factory", "MI_Hall")):
        continue
    key = name.removeprefix("MI_Factory").removeprefix("MI_Hall")
    # 부모 재질 변경 후에도 저장되어 있는 이전 Color 값을 직접 읽습니다.
    # 현재 셰이더에 노출되지 않아도 원래 팔레트 색상을 복원할 수 있습니다.
    colors = {
        str(v.parameter_info.name): v.parameter_value
        for v in material.get_editor_property("vector_parameter_values")
    }
    assert "Color" in colors, name + ": missing original palette color"
    color = colors["Color"]
    role = "Paint"
    if key in ("Steel", "LightSteel", "Window"):
        role = "Metal"
    elif key in ("Black", "Belt", "Slats"):
        role = "Rubber"
    elif key in ("Floor", "Concrete", "Wall", "Asphalt"):
        role = "Concrete"
    elif key == "Cardboard":
        role = "Cardboard"
    ML.set_material_instance_parent(material, parents[role])
    if role == "Concrete":
        tint = {
            "Floor": (0.42, 0.52, 0.62),
            "Concrete": (0.72, 0.82, 0.93),
            "Wall": (1.15, 1.20, 1.25),
            "Asphalt": (0.22, 0.27, 0.32),
        }[key]
    elif role == "Cardboard":
        tint = (1.0, 1.0, 1.0)
    else:
        tint = (color.r, color.g, color.b)
    ML.set_material_instance_vector_parameter_value(
        material, "BaseColor Tint", unreal.LinearColor(*tint, 1)
    )
    ML.set_material_instance_scalar_parameter_value(
        material, "Factory Metallic", 0.85 if role == "Metal" else 0.0
    )
    ML.set_material_instance_scalar_parameter_value(material, "Tiling", 1.0)
    ML.set_material_instance_scalar_parameter_value(
        material, "Min Roughness", 0.50 if role in ("Concrete", "Rubber", "Cardboard") else 0.25
    )
    ML.set_material_instance_scalar_parameter_value(
        material, "Max Roughness", 0.90 if role in ("Concrete", "Rubber", "Cardboard") else 0.60
    )
    ML.set_material_instance_scalar_parameter_value(material, "Normal Intensity", 0.65)
    ML.update_material_instance(material)
    save(material)
    report["materials"][name] = {
        "path": material.get_path_name(),
        "source_role": role,
        "parent": parents[role].get_path_name(),
    }

# 베이크된 설비 정점은 이미 센티미터 단위입니다.
for path in LIB.list_assets(ROOT + "/Meshes/Equipment", recursive=False):
    if path.rsplit("/", 1)[-1].startswith("SM_SM_"):
        continue
    mesh = unreal.load_asset(path)
    if not isinstance(mesh, unreal.StaticMesh) or mesh.get_name().startswith("SM_SM_"):
        continue
    assert SM.generate_box_uv_channel(
        mesh, 0, 0, unreal.Vector(), unreal.Rotator(), unreal.Vector(100, 100, 100)
    )
    save(mesh)
    report["equipment_meshes"] += 1
assert report["equipment_meshes"] == 32

# 배경의 저장된 변환을 유지하고 원본과 스케일별 UV 변형을 재사용합니다.
# 세 축 모두 실제 1 m 간격으로 질감이 반복되도록 합니다.
variants = {}
for name in ("L_SmartFactory", "L_SmartFactoryHall"):
    assert LEVELS.load_level(ROOT + "/Maps/" + name)
    count = 0
    for actor in ACTORS.get_all_level_actors():
        if isinstance(actor, unreal.SmartFactoryCellActor):
            actor.bind_authored_components()
            continue
        for comp in actor.get_components_by_class(unreal.StaticMeshComponent):
            if comp.get_editor_property("is_editor_only"):
                continue
            mesh = comp.static_mesh
            if not mesh:
                continue
            scale = comp.get_world_scale()
            scales = [max(abs(v), 0.0001) for v in (scale.x, scale.y, scale.z)]
            # 다시 실행할 때 이미 처리한 컴포넌트는 유지합니다.
            if "/Meshes/Scenery/" in mesh.get_path_name():
                count += 1
                continue
            identity = mesh.get_path_name() + "|" + ",".join(f"{v:.6f}" for v in scales)
            if identity not in variants:
                suffix = hashlib.sha1(identity.encode()).hexdigest()[:12]
                variant = duplicate(
                    mesh.get_path_name(),
                    ROOT
                    + "/Meshes/Scenery/SM_"
                    + mesh.get_name().removeprefix("SM_")
                    + "_"
                    + suffix,
                )
                size = unreal.Vector(*(100 / v for v in scales))
                assert SM.generate_box_uv_channel(
                    variant, 0, 0, unreal.Vector(), unreal.Rotator(), size
                )
                save(variant)
                variants[identity] = variant
            comp.set_static_mesh(variants[identity])
            count += 1
    assert LEVELS.save_current_level()
    report["maps"].append({"map": name, "scenery_components": count})
LIB.save_directory("/Game/Fab", only_if_is_dirty=True, recursive=True)
LIB.save_directory(ROOT, only_if_is_dirty=True, recursive=True)
report["success"] = True
(PROJECT / "Saved/Tests/MegascansApplication.json").write_text(json.dumps(report, indent=2))
(PROJECT / "Tools/Unreal/Data/MegascansSources.json").write_text(
    json.dumps(report["sources"], indent=2)
)
unreal.log("MEGASCANS_HIGH_MATERIALS_APPLIED")
