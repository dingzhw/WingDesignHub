"""OpenVSP native worker: explicitly defined skin, spars and ribs, no analysis step."""
import importlib.util
import json
from pathlib import Path
import openvsp as v
from .adapters import sha256
from .fea_mesh import StructureMeshCase, read_inp, audit_mesh, write_preview


def set_value(obj, key, group, value):
    parm = v.FindParm(obj, key, group)
    if not parm:
        raise RuntimeError(f"OpenVSP 参数不存在：{group}/{key}")
    actual = v.SetParmVal(parm, value)
    if abs(actual-value) > 1e-8*max(1.,abs(value)):
        raise ValueError(f"OpenVSP 参数被裁剪：{group}/{key}={actual}，要求 {value}")


def check_errors():
    mgr = v.ErrorMgrSingleton.getInstance(); errors = []
    while mgr.GetNumTotalErrors():
        errors.append(mgr.PopLastError().m_ErrorString)
    if errors:
        raise RuntimeError("; ".join(errors))


def main():
    case = StructureMeshCase.from_dict(json.loads(Path("input.json").read_text(encoding="utf-8")))
    if v.GetVSPVersion() != "OpenVSP 3.56.0":
        raise RuntimeError("结构模板仅验证过 OpenVSP 3.56.0，其他版本须重验")
    v.ClearVSPModel()
    wing = v.AddGeom("WING"); v.SetGeomName(wing,"DemoWing")
    set_value(wing,"Sym_Planar_Flag","Sym",0)  # explicitly one right half-wing
    v.SetDriverGroup(wing,1,v.SPAN_WSECT_DRIVER,v.ROOTC_WSECT_DRIVER,v.TIPC_WSECT_DRIVER)
    for key,value in (("Span",case.half_span_m),("Root_Chord",case.chord_m),("Tip_Chord",case.chord_m),("Sweep",0.),("Twist",0.)):
        set_value(wing,key,"XSec_1",value)
    for i in (0,1):
        set_value(wing,"Camber",f"XSecCurve_{i}",0.)
        set_value(wing,"ThickChord",f"XSecCurve_{i}",.12)
    vehicle = v.FindContainer("Vehicle",0)
    set_value(vehicle,"StructModelUnit","FeaStructure",v.LEN_M)
    set_value(vehicle,"StructUnit","FeaStructure",v.SI_UNIT)
    v.Update()
    index = v.AddFeaStruct(wing); struct = v.GetFeaStructID(wing,index)
    parts = {"Skin": v.GetFeaPartID(struct,0)}
    for name,fraction in (("FrontSpar",case.front_spar_fraction),("RearSpar",case.rear_spar_fraction)):
        part = v.AddFeaPart(wing,index,v.FEA_SPAR)
        set_value(part,"UsePercentChord","FeaSpar",1)
        set_value(part,"PercentRootChord","FeaSpar",fraction)
        set_value(part,"PercentTipChord","FeaSpar",fraction)
        parts[name] = part
    for i,fraction in enumerate(case.rib_fractions):
        part = v.AddFeaPart(wing,index,v.FEA_RIB)
        set_value(part,"RelCenterLocation","FeaPart",fraction)
        parts[f"Rib{i}"] = part
    material = v.AddFeaMaterial()
    for key,value in (("LengthUnit",v.LEN_M),("DensityUnit",v.RHO_UNIT_KG_M3),("ModulusUnit",v.PRES_UNIT_PA),
                      ("ElasticModulus",case.elastic_modulus_pa),("MassDensity",case.density_kg_m3),("PoissonRatio",case.poisson_ratio)):
        set_value(material,key,"FeaMaterial",value)
    for name,part in parts.items():
        v.SetFeaPartName(part,name)
        prop = v.AddFeaProperty(v.FEA_SHELL)
        set_value(prop,"LengthUnit","FeaProperty",v.LEN_M)
        set_value(prop,"Thickness","FeaProperty",case.part_thicknesses[name])
        v.SetFeaPropertyMaterialID(prop,material); v.SetFeaPartPropertyID(part,prop)
        set_value(part,"CreateBeamElements","FeaPart",0)
        set_value(part,"MarkDelShellElements","FeaPart",v.FEA_KEEP)
    # Use first-order triangles for a small, auditable baseline. Keep native skin/caps.
    set_value(struct,"ConvertToQuadsFlag","Global",0)
    set_value(struct,"HighOrderElementFlag","Global",0)
    set_value(struct,"ParallelMeshFlag","Global",0)
    v.SetFeaMeshVal(wing,index,v.CFD_MAX_EDGE_LEN,case.max_edge_m)
    v.SetFeaMeshVal(wing,index,v.CFD_MIN_EDGE_LEN,case.min_edge_m)
    v.Update(); check_errors()
    v.WriteVSPFile("structure.vsp3",v.SET_ALL)
    # WriteVSPFile resets export basenames; set mesh filename afterwards.
    v.SetFeaMeshFileName(wing,index,v.FEA_CALCULIX_FILE_NAME,"wing.inp")
    v.ComputeFeaMesh(wing,index,v.FEA_CALCULIX_FILE_NAME); check_errors()
    mesh = read_inp("wing.inp")
    metrics = audit_mesh(mesh,case)
    write_preview(mesh,"mesh_preview.svg")
    result = {"version": v.GetVSPVersion(), "native_extension_sha256": sha256(importlib.util.find_spec("openvsp._vsp").origin),
              "units": {"length": "m", "mass": "kg", "modulus": "Pa"},
              "coordinates": "x aft, y right, z up; right half-wing y>=0",
              "rib_fractions": case.rib_fractions, "metrics": metrics,
              "status": "mesh_checked", "passed": True, "physical_validation_passed": False,
              "structural_analysis_performed": False,
              "limits": ["参数化 NACA0012 矩形半翼，含全外形蒙皮、两梁和内翼肋",
                         "仅几何与网格检查；文件未定义边界条件、载荷或分析步",
                         "质量为面积×板厚×密度，不含接头、紧固件、工艺余量或强度定尺寸",
                         "网格质量与面积加密检查不等同于应力、变形或屈曲收敛",
                         "部分中心肋/曲面交线组合会产生退化单元，检查失败时保留文件并拒绝通过"]}
    Path("summary.json").write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")


if __name__ == "__main__":
    main()
