"""Public services used by CLI, GUI and future AI tool calls."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import traceback
from uuid import uuid4, UUID
import numpy as np
from . import __version__
from .model import WingCase, validate_project
from .mechanics import uniform_beam, map_loads, resultant, solve_beam
from .adapters import run_avl, run_openvsp, tool_paths, sha256, execute


def write_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    temporary.replace(path)


def run_reference(root, name):
    import sys
    if name not in ("fastga", "calculix", "oas", "vsp_structure", "oas_wingbox", "shell_static", "box_comparison", "plate_buckling", "structural_sensitivity"):
        raise ValueError("未注册的基准任务")
    root = Path(root).resolve()
    run_id = uuid4().hex
    work = root/"runs"/run_id; work.mkdir(parents=True)
    result = {"run_id": run_id, "version": __version__, "benchmark": name, "status": "running",
              "started_utc": datetime.now(timezone.utc).isoformat(),
              "source_hashes": {p.relative_to(Path(__file__).parent).as_posix(): sha256(p)
                                for p in Path(__file__).parent.rglob("*.py")},
              "worker_sha256": sha256(root/"scripts"/f"validate_{name}.py"),
              "physical_validation_passed": False}
    try:
        execute([sys.executable, "-X", "utf8", str(root/"scripts"/f"validate_{name}.py"), str(work)], work, timeout=600)
        result["summary"] = json.loads((work/"summary.json").read_text(encoding="utf-8"))
        result["status"] = result["summary"].get("status", "executed")
        if result["summary"].get("passed") is False:
            raise ValueError("基准验收未通过")
    except Exception as exc:
        result.update(status="failed", error=str(exc))
        if (work/"summary.json").exists():
            result["summary"] = json.loads((work/"summary.json").read_text(encoding="utf-8"))
            if result["summary"].get("passed") is False:
                result["error"] = "基准计算已执行，但验收未通过；请查看误差、收敛状态与阈值。"
    result["finished_utc"] = datetime.now(timezone.utc).isoformat()
    result["artifact_hashes"] = {p.relative_to(work).as_posix(): sha256(p) for p in work.rglob("*") if p.is_file()}
    write_json(work/"result.json", result)
    return result


def run_analysis(case, root, mode="beam"):
    if isinstance(case, dict):
        case = WingCase.from_dict(case)
    errors = validate_project(case)
    if errors:
        raise ValueError("；".join(errors))
    if mode not in ("beam", "avl", "openvsp_avl"):
        raise ValueError("未知计算任务")
    root = Path(root).resolve(); run_id = uuid4().hex
    directory = root/"runs"/run_id; directory.mkdir(parents=True)
    inputs = case.to_dict()
    signature = hashlib.sha256(json.dumps({"input": inputs, "mode": mode}, sort_keys=True).encode()).hexdigest()
    record = {"run_id": run_id, "version": __version__, "mode": mode, "status": "running",
              "input_hash": signature, "started_utc": datetime.now(timezone.utc).isoformat(),
              "source_hashes": {p.relative_to(Path(__file__).parent).as_posix(): sha256(p)
                                for p in Path(__file__).parent.rglob("*.py")},
              "evidence_level": "numerical_demo", "physical_validation_passed": False,
              "assumptions": [case.assumption], "outputs": {}}
    write_json(directory/"input.json", inputs); write_json(directory/"result.json", record)
    try:
        if mode == "beam":
            beam = uniform_beam(case.span_m/2, case.elastic_modulus_pa, case.second_moment_m4,
                                case.uniform_load_n_m, case.beam_elements)
            record["outputs"]["beam"] = beam
            if beam["tip_relative_error"] > .02:
                raise ValueError("梁解析解验证误差超过 2%")
        else:
            if mode == "openvsp_avl":
                record["outputs"]["geometry"] = run_openvsp(case, directory/"openvsp")
            aero = run_avl(case, tool_paths(root)["avl"], directory/"avl")
            record["outputs"]["aerodynamics"] = aero
            rows = aero["right_wing_strips"]
            q = .5*case.density_kg_m3*case.speed_m_s**2
            # Small-angle vertical lift-only transfer: excludes drag/torsion/inertial relief.
            p = np.array([[0., r["y_m"], 0.] for r in rows])
            f = np.array([[0., 0., q*r["area_m2"]*r["cl"]] for r in rows])
            n = np.zeros((case.beam_elements+1, 3)); n[:, 1] = np.linspace(0, case.span_m/2, len(n))
            nf, nm = map_loads(p, f, n)
            before = resultant(p, f); after = resultant(n, nf, nm)
            ferr = float(np.linalg.norm(before[0]-after[0]))
            merr = float(np.linalg.norm(before[1]-after[1]))
            if ferr > max(1e-8, .001*np.linalg.norm(before[0])) or merr > max(1e-8, .001*np.linalg.norm(before[1])):
                raise ValueError("载荷映射守恒检查失败")
            reconstructed_cl = 2*before[0][2]/(q*case.area_m2)
            if abs(reconstructed_cl-aero["coefficients"]["CLtot"]) > max(.002, .02*abs(reconstructed_cl)):
                raise ValueError("条带升力积分与总升力不一致")
            record["outputs"]["loads"] = {"force_error_n": ferr, "moment_error_nm": merr,
                "right_wing_lift_n": float(before[0][2]), "root_bending_nm": float(before[1][0]),
                "nodes_m": n.tolist(), "forces_n": nf.tolist(), "moments_nm": nm.tolist()}
            beam = solve_beam(case.span_m/2, case.elastic_modulus_pa, case.second_moment_m4, nf[:, 2], nm[:, 0])
            record["outputs"]["beam"] = beam
            record["assumptions"].append("右半翼竖向升力映射到等效梁；未包括阻力、扭转、重量卸载和强度定尺寸。")
        if abs(beam["tip_displacement_m"])/(case.span_m/2) > .1:
            raise ValueError("梁挠度超过半展长 10%，小变形模型超出使用范围")
        record["status"] = "success"
    except Exception as exc:
        record["status"] = "failed"; record["error"] = str(exc)
        (directory/"error.log").write_text(traceback.format_exc(), encoding="utf-8")
    record["finished_utc"] = datetime.now(timezone.utc).isoformat()
    record["artifact_hashes"] = {p.relative_to(directory).as_posix(): sha256(p)
                                for p in directory.rglob("*") if p.is_file() and p.name != "result.json"}
    write_json(directory/"result.json", record)
    generate_report(record, directory/"report.md")
    return record


def get_results(root, run_id):
    if UUID(run_id).hex != run_id:
        raise ValueError("无效运行编号")
    directory = Path(root)/"runs"/run_id
    record = json.loads((directory/"result.json").read_text(encoding="utf-8"))
    for name, digest in record.get("artifact_hashes", {}).items():
        p = (directory/name).resolve()
        if not p.is_relative_to(directory.resolve()) or not p.is_file() or sha256(p) != digest:
            raise ValueError(f"运行文件完整性检查失败：{name}")
    return record


def compare_designs(records, projects=None, purpose='design_trade'):
    if projects is not None:
        from .design_comparison import ComparisonRequest, summarize_comparison
        return summarize_comparison(ComparisonRequest(tuple(projects),purpose),records)
    if any(r["status"] != "success" for r in records):
        raise ValueError("仅比较成功运行")
    if len({(r["mode"], r["version"], json.dumps(r["source_hashes"], sort_keys=True)) for r in records}) > 1:
        raise ValueError("比较需要相同计算模式、版本和代码")
    return [{"run_id": r["run_id"], "tip_displacement_m": r["outputs"]["beam"]["tip_displacement_m"],
             "root_moment_nm": r["outputs"]["beam"]["root_moment_nm"]} for r in records]


def generate_report(record, path=None, project=None, root=None):
    if record.get('mode') in ('aircraft_geometry','aircraft_aero'):
        if root is None or get_results(root,record['run_id'])!=record:
            raise ValueError('几何报告需要完整且一致的本地运行记录')
        report=Path(root)/'runs'/record['run_id']/'report.html'
        if not report.is_file():raise ValueError('本次几何未完成报告生成，请查看失败日志')
        text=report.read_text('utf-8')
        if path:Path(path).write_text(text,encoding='utf-8')
        return text
    if record.get('mode') in ('overall_sizing','overall_comparison'):
        if project is None or record.get('definition_sha256')!=project.definition_hash():
            raise ValueError('总体报告需要与运行一致的需求定义')
        from .design_report import design_report_html,comparison_report_html
        text=(design_report_html(project,record) if record['mode']=='overall_sizing' else comparison_report_html(record.get('summary',{}),record))
        if path:Path(path).write_text(text,encoding='utf-8')
        return text
    text = f"# WingDesignHub 运行记录\n\n版本：{record['version']}\n\n任务：{record['mode']}\n\n状态：{record['status']}\n\n"
    text += "证据等级：接口与数值演示，尚未进行独立物理验证。\n\n"
    text += "## 模型假设\n\n" + "\n".join(f"- {a}" for a in record["assumptions"]) + "\n\n"
    if record["status"] == "failed":
        text += f"失败原因：{record['error']}\n"
    else:
        b = record["outputs"]["beam"]
        text += f"梁尖挠度：{b['tip_displacement_m']:.6g} m\n\n根部反力矩：{b['root_moment_nm']:.6g} N·m\n"
    text += f"\n运行编号：{record['run_id']}\n\n输入 SHA-256：{record['input_hash']}\n"
    if path:
        Path(path).write_text(text, encoding="utf-8")
    return text
