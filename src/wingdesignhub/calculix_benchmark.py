"""Elastic B32R cantilever checks, with explicit solver/version provenance."""
import json
import math
from pathlib import Path
import re
from .adapters import execute, sha256, tool_paths

SUPPORTED_VERSION = "2.23"


def beam_deck(elements=20, length=2., modulus=70e9, side=.1, force=100.):
    if isinstance(elements, bool) or not isinstance(elements, int) or elements < 1:
        raise ValueError("单元数须为正整数")
    if not all(math.isfinite(v) and v > 0 for v in (length, modulus, side, force)):
        raise ValueError("梁参数须为有限正数")
    last = 2*elements+1
    lines = ["*HEADING", "WingDesignHub public synthetic cantilever SI", "*NODE"]
    lines += [f"{i+1},{i*length/(2*elements)},0,0" for i in range(last)]
    lines += ["*ELEMENT,TYPE=B32R,ELSET=BEAM"]
    lines += [f"{i+1},{2*i+1},{2*i+2},{2*i+3}" for i in range(elements)]
    lines += ["*NSET,NSET=TIP", str(last), "*MATERIAL,NAME=ALUMINUM", "*ELASTIC", f"{modulus},0.3",
              "*BEAM SECTION,ELSET=BEAM,MATERIAL=ALUMINUM,SECTION=RECT", f"{side},{side}", "0,0,1",
              "*BOUNDARY", "1,1,6", "*STEP", "*STATIC", "*CLOAD", f"{last},2,{force}",
              "*NODE PRINT,NSET=TIP", "U", "*NODE FILE,OUTPUT=2D", "U", "*END STEP"]
    return "\n".join(lines)+"\n"


def parse_tip(data, node):
    """Require exactly one finite displacement row in the single-step benchmark."""
    blocks = re.split(r"displacements[^\n]*\n", data, flags=re.IGNORECASE)
    rows = []
    for block in blocks[1:]:
        for line in block.splitlines():
            parts = line.split()
            if len(parts) == 4 and parts[0] == str(node):
                values = [float(v.replace("D", "E").replace("d", "e")) for v in parts[1:]]
                if not all(math.isfinite(v) for v in values):
                    raise ValueError("CalculiX 位移包含非有限值")
                rows.append(values[1])
    if len(rows) != 1:
        raise ValueError("CalculiX 位移行缺失或存在多步/重复结果")
    return rows[0]


def run_beam(executable, work, elements=20, **parameters):
    work = Path(work); work.mkdir(parents=True, exist_ok=False)
    deck = work/"beam.inp"
    deck.write_text(beam_deck(elements, **parameters), encoding="ascii")
    log = execute([str(executable), "beam"], work, timeout=90)
    match = re.search(r"Version\s+([\d.]+)", log)
    if not match or match[1] != SUPPORTED_VERSION:
        raise ValueError(f"基准要求 CalculiX {SUPPORTED_VERSION}；实际版本为 {match[1] if match else '未知'}")
    tip = parse_tip((work/"beam.dat").read_text(), 2*elements+1)
    p = {"length": 2., "modulus": 70e9, "side": .1, "force": 100., **parameters}
    exact = p["force"]*p["length"]**3/(3*p["modulus"]*(p["side"]**4/12))
    return {"elements": elements, "parameters_si": p, "tip_displacement_m": tip,
            "analytical_tip_m": exact, "relative_error": abs(tip-exact)/abs(exact),
            "input_sha256": sha256(deck), "solver_version": match[1]}


def run_benchmark(root, work):
    configured = tool_paths(root)["calculix"]
    if not configured or not Path(configured).is_file():
        raise FileNotFoundError("请在工具设置中配置 CalculiX 2.23 的 ccx.exe 路径")
    executable = Path(configured).resolve()
    work = Path(work); work.mkdir(parents=True, exist_ok=True)
    mesh = [run_beam(executable, work/f"mesh_{n}", n) for n in (10, 20, 40)]
    # Same dimensions/material/load as the documented simplebeam example, converted to SI.
    manual = run_beam(executable, work/"manual_beam", 10,
                      length=.1, modulus=100e9, side=.002, force=1.)
    errors = [r["relative_error"] for r in mesh]
    result = {"solver": "CalculiX", "solver_version": SUPPORTED_VERSION,
              "solver_sha256": sha256(executable), "element": "B32R", "threshold": .02,
              "mesh_study": mesh, "manual_dimensions_case": manual,
              "relative_error": errors[1], "physical_validation_passed": False,
              "evidence_level": "analytical_and_manual_dimensions",
              "passed": all(e < .02 for e in errors) and errors[0] > errors[1] > errors[2]
                        and manual["relative_error"] < .02}
    result["status"] = "passed" if result["passed"] else "failed"
    (work/"summary.json").write_text(json.dumps(result, indent=2, allow_nan=False), encoding="utf-8")
    return result
