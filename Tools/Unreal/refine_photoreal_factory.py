"""에셋의 표면 반응과 밀리미터 단위 베벨을 보정하여 저장합니다.

Geometry Script는 에디터에서만 사용합니다. 게임 실행은 저장된 메시와
고정 컴포넌트 풀을 사용하며 런타임 절차적 메시를 생성하지 않습니다."""

import json
from pathlib import Path
import unreal

ROOT = "/Game/SmartFactory"
PROJECT = Path(__file__).resolve().parents[2]
LIB = unreal.EditorAssetLibrary
ML = unreal.MaterialEditingLibrary
report = {"success": False, "materials": {}, "meshes": [], "maps": []}


def save(a):
    assert LIB.save_loaded_asset(a, only_if_is_dirty=False), a.get_path_name()


master = unreal.load_asset(ROOT + "/Materials/M_MegascansFactorySurface")
master.set_editor_property("shading_model", unreal.MaterialShadingModel.MSM_CLEAR_COAT)
attrs = next(
    (
        e
        for e in ML.get_material_expressions(master)
        if isinstance(e, unreal.MaterialExpressionMakeMaterialAttributes)
    ),
    None,
)
if not attrs:
    attrs = ML.create_material_expression(
        master, unreal.MaterialExpressionMakeMaterialAttributes, 900, 200
    )
    for prop, pin in (
        (unreal.MaterialProperty.MP_BASE_COLOR, "BaseColor"),
        (unreal.MaterialProperty.MP_METALLIC, "Metallic"),
        (unreal.MaterialProperty.MP_SPECULAR, "Specular"),
        (unreal.MaterialProperty.MP_ROUGHNESS, "Roughness"),
        (unreal.MaterialProperty.MP_NORMAL, "Normal"),
        (unreal.MaterialProperty.MP_AMBIENT_OCCLUSION, "AmbientOcclusion"),
        (unreal.MaterialProperty.MP_EMISSIVE_COLOR, "EmissiveColor"),
    ):
        node = ML.get_material_property_input_node(master, prop)
        if node:
            assert ML.connect_material_expressions(
                node, ML.get_material_property_input_node_output_name(master, prop), attrs, pin
            ), pin
master.set_editor_property("use_material_attributes", True)
assert ML.connect_material_property(attrs, "", unreal.MaterialProperty.MP_MATERIAL_ATTRIBUTES)


def parameter(name, pin, default):
    node = next(
        (
            e
            for e in ML.get_material_expressions(master)
            if isinstance(e, unreal.MaterialExpressionScalarParameter)
            and str(e.get_editor_property("parameter_name")) == name
        ),
        None,
    )
    if not node:
        node = ML.create_material_expression(
            master, unreal.MaterialExpressionScalarParameter, 500, 500
        )
    node.set_editor_property("parameter_name", name)
    node.set_editor_property("default_value", default)
    assert ML.connect_material_expressions(node, "", attrs, pin), pin


parameter("Factory Anisotropy", "Anisotropy", 0)
parameter("Factory Clear Coat", "ClearCoat", 0)
parameter("Factory Coat Roughness", "ClearCoatRoughness", 0.22)
ML.recompile_material(master)
save(master)

# 금속, 도장, 고무마다 거칠기와 반사 응답을 다르게 설정합니다.
# 모든 Megascans 텍스처 참조는 유지합니다.
for path in LIB.list_assets(ROOT + "/Materials", recursive=False):
    mi = unreal.load_asset(path)
    if not isinstance(mi, unreal.MaterialInstanceConstant):
        continue
    name = mi.get_name()
    if not name.startswith(("MI_Factory", "MI_Hall")):
        continue
    key = name.removeprefix("MI_Factory").removeprefix("MI_Hall")
    lo, hi, metal, aniso, coat, spec, tiling = 0.30, 0.46, 0, 0, 0.22, 0.5, 2.0
    tint = None
    if key == "Steel":
        lo, hi, metal, aniso, coat, tiling = 0.16, 0.30, 1, 0.55, 0, 6
        tint = (0.56, 0.58, 0.61)
    elif key == "LightSteel":
        lo, hi, metal, aniso, coat, tiling = 0.22, 0.38, 1, 0.40, 0, 5
        tint = (0.70, 0.72, 0.75)
    elif key in ("Belt", "Slats", "Black"):
        lo, hi, coat, spec, tiling = 0.72, 0.92, 0, 0.28, 5
    elif key == "Cardboard":
        lo, hi, coat, spec, tiling = 0.78, 0.94, 0, 0.30, 2
    elif key in ("Floor", "Concrete", "Asphalt", "Wall"):
        lo, hi, coat, tiling = (0.70, 0.88, 0, 1) if key == "Wall" else (0.38, 0.57, 0, 1)
        ML.set_material_instance_scalar_parameter_value(mi, "Normal Intensity", 0.25)
        ML.set_material_instance_scalar_parameter_value(mi, "Contrast", 0.72)
        ML.set_material_instance_scalar_parameter_value(mi, "Saturation", 0.18)
    elif key == "Window":
        lo, hi, metal, coat, tiling = 0.10, 0.17, 0, 0.85, 1
        tint = (0.04, 0.10, 0.13)
    else:
        # 흰색 HDR 조명에서 사용할 도장 색상을 선형 RGB로 지정합니다.
        tint = {
            "Orange": (0.72, 0.16, 0.018),
            "Cyan": (0.018, 0.27, 0.32),
            "Yellow": (0.78, 0.46, 0.018),
            "Red": (0.5, 0.024, 0.02),
            "Blue": (0.015, 0.075, 0.40),
            "Cabinet": (0.55, 0.57, 0.59),
        }.get(key)
    values = {
        "Min Roughness": lo,
        "Max Roughness": hi,
        "Factory Metallic": metal,
        "Factory Anisotropy": aniso,
        "Factory Clear Coat": coat,
        "Factory Coat Roughness": 0.22,
        "Specular": spec,
        "Tiling": tiling,
    }
    for k, v in values.items():
        ML.set_material_instance_scalar_parameter_value(mi, k, v)
    if tint:
        ML.set_material_instance_vector_parameter_value(
            mi, "BaseColor Tint", unreal.LinearColor(*tint, 1)
        )
    ML.update_material_instance(mi)
    save(mi)
    report["materials"][name] = values

for path in LIB.list_assets(ROOT + "/Meshes/Equipment", recursive=False):
    mesh = unreal.load_asset(path)
    if not isinstance(mesh, unreal.StaticMesh):
        continue
    name = mesh.get_name()
    if name == "SM_CellFloor":
        continue  # painted floor markings stay flat
    if LIB.get_metadata_tag(mesh, "PhotorealBevelV1") == "true":
        continue
    dm = unreal.DynamicMesh()
    dm, outcome = unreal.GeometryScript_AssetUtils.copy_mesh_from_static_mesh(
        mesh,
        dm,
        unreal.GeometryScriptCopyMeshFromAssetOptions(),
        unreal.GeometryScriptMeshReadLOD(),
    )
    assert outcome == unreal.GeometryScriptOutcomePins.SUCCESS, (name, str(outcome))
    before = dm.get_triangle_count()
    unreal.GeometryScript_MeshRepair.weld_mesh_edges(
        dm, unreal.GeometryScriptWeldEdgesOptions(tolerance=0.0001)
    )
    unreal.GeometryScript_PolyGroups.compute_polygroups_from_angle_threshold(
        dm, unreal.GeometryScriptGroupLayer(), 40, 1
    )
    distance = 0.12 if name.startswith("SM_Robot_") else 0.06
    if "Cap" in name or "Bolt" in name or "Signal" in name or "Sensor" in name:
        distance = 0.025
    if name == "SM_Product":
        distance = 0.6  # later scaled to 8 cm: a 0.48 mm edge
    options = unreal.GeometryScriptMeshBevelOptions(
        bevel_distance=distance, infer_material_id=True, subdivisions=2
    )
    unreal.GeometryScript_MeshModeling.apply_mesh_polygroup_bevel(dm, options)
    after = dm.get_triangle_count()
    assert after > before, (name, before, after)
    unreal.GeometryScript_Normals.compute_split_normals(
        dm,
        unreal.GeometryScriptSplitNormalsOptions(split_by_opening_angle=True, opening_angle_deg=70),
        unreal.GeometryScriptCalculateNormalsOptions(angle_weighted=True, area_weighted=True),
    )
    material_paths = [s.material_interface.get_path_name() for s in mesh.static_materials]
    write = unreal.GeometryScriptCopyMeshToAssetOptions(
        enable_recompute_normals=False, enable_recompute_tangents=True
    )
    dm, outcome = unreal.GeometryScript_AssetUtils.copy_mesh_to_static_mesh(
        dm, mesh, write, unreal.GeometryScriptMeshWriteLOD()
    )
    assert outcome == unreal.GeometryScriptOutcomePins.SUCCESS
    assert [s.material_interface.get_path_name() for s in mesh.static_materials] == material_paths
    LIB.set_metadata_tag(mesh, "PhotorealBevelV1", "true")
    save(mesh)
    report["meshes"].append(
        {"asset": path, "bevel_cm": distance, "triangles_before": before, "triangles_after": after}
    )

levels = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
actors = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
for name in ("L_SmartFactory", "L_SmartFactoryHall"):
    assert levels.load_level(ROOT + "/Maps/" + name)
    lights = []
    for a in actors.get_all_level_actors():
        if isinstance(a, (unreal.Light, unreal.SkyLight)):
            lights.append(a)
        if isinstance(a, unreal.SkyLight):
            c = a.get_component_by_class(unreal.SkyLightComponent)
            c.set_editor_property("cast_shadows", True)
            c.set_editor_property("occlusion_max_distance", 100.0)
        if isinstance(a, unreal.PostProcessVolume):
            settings = a.get_editor_property("settings")
            for prop, value in {
                "ambient_occlusion_intensity": 0.55,
                "ambient_occlusion_radius": 60.0,
                "lumen_scene_lighting_quality": 2.0,
                "lumen_final_gather_quality": 2.0,
                "lumen_reflection_quality": 2.0,
            }.items():
                settings.set_editor_property("override_" + prop, True)
                settings.set_editor_property(prop, value)
            a.set_editor_property("settings", settings)
        if isinstance(a, unreal.SmartFactoryCellActor):
            assert len(a.get_components_by_class(unreal.StaticMeshComponent)) == 120
    assert len(lights) == 1
    assert levels.save_current_level()
    report["maps"].append({"map": name, "lights": 1, "components_per_cell": 120})
report["success"] = True
(PROJECT / "Saved/Tests/PhotorealRefinement.json").write_text(json.dumps(report, indent=2))
unreal.log("PHOTOREAL_STATIC_ASSETS_REFINED")
