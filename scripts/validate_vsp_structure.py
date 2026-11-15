"""Two mesh densities and a span perturbation; no structural solve is claimed."""
from dataclasses import replace
import json
from pathlib import Path
import sys
from uuid import uuid4
from wingdesignhub.fea_mesh import StructureMeshCase
from wingdesignhub.structure_service import generate_mesh
from wingdesignhub.service import write_json

if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    work = Path(sys.argv[1]).resolve() if len(sys.argv)>1 else root/"runs"/("vsp_structure_"+uuid4().hex)
    work.mkdir(parents=True,exist_ok=True)
    case = StructureMeshCase()
    coarse = generate_mesh(case,work/"coarse")
    fine = generate_mesh(replace(case,max_edge_m=.2,min_edge_m=.02),work/"fine")
    stretched = generate_mesh(replace(case,half_span_m=6.),work/"longer")
    a,b,c = [r["metrics"] for r in (coarse,fine,stretched)]
    diffs = {name:abs(b[name]-a[name])/b[name] for name in ("area_m2","shell_material_mass_kg")}
    part_diffs = {name:abs(b["parts"][name]["area_m2"]-part["area_m2"])/b["parts"][name]["area_m2"] for name,part in a["parts"].items()}
    passed = b["elements"]>a["elements"] and all(v<.02 for v in list(diffs.values())+list(part_diffs.values()))
    passed = passed and c["shell_material_mass_kg"]>a["shell_material_mass_kg"]
    result = {"status":"mesh_checked" if passed else "failed","passed":bool(passed),
              "coarse":coarse,"fine":fine,"longer":stretched,"relative_differences":diffs,
              "part_area_relative_differences":part_diffs,"difference_threshold":.02,
              "evidence_level":"geometry_mesh_screening","structural_analysis_performed":False,
              "physical_validation_passed":False,"limits":coarse["limits"]}
    write_json(work/"summary.json",result)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    raise SystemExit(0 if passed else 1)
