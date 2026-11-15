import argparse
import json
from pathlib import Path
from .model import WingCase
from .service import run_analysis, run_reference
from .structure_service import run_structure_mesh
from .fea_mesh import StructureMeshCase
from .shell_static import StaticWingCase
from .static_service import run_wing_static
from .adapters import inventory
from .flight_loads import FlightLoadCase
from .flight_service import run_flight_structure
from .plate_buckling import PlateCase
from .plate_service import run_plate_analysis
from .requirements import DesignProject
from .design_service import prepare_design_project, run_fastga_reference
from .fastga_interface import get_fastga_contract


def main():
    parser = argparse.ArgumentParser(description="WingDesignHub 开发与自动化入口")
    parser.add_argument("action", choices=["run", "doctor", "reference", "mesh", "static", "flight", "plate", "prepare", "fastga-reference", "fastga-contract"])
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--input", type=Path)
    parser.add_argument("--mode", choices=["beam", "avl", "openvsp_avl"], default="beam")
    parser.add_argument("--benchmark", choices=["fastga","calculix","oas","vsp_structure","oas_wingbox","shell_static","box_comparison","plate_buckling","structural_sensitivity"], default="oas")
    args = parser.parse_args()
    if args.input and (args.action in ("fastga-reference", "fastga-contract") or
                       (args.action == "reference" and args.benchmark == "fastga")):
        parser.error("公开参考任务保留固定输入，不接受自定义需求覆盖；请用 prepare 保存需求。")
    if args.action == "doctor":
        result = inventory(args.root)
    elif args.action == "prepare":
        case = DesignProject.from_dict(json.loads(args.input.read_text(encoding="utf-8"))) if args.input else DesignProject()
        result = prepare_design_project(case, args.root)
    elif args.action == "fastga-reference":
        result = run_fastga_reference(args.root)
    elif args.action == "fastga-contract":
        result = get_fastga_contract()
    elif args.action == "reference":
        result = run_reference(args.root,args.benchmark)
    elif args.action == "static":
        case = StaticWingCase.from_dict(json.loads(args.input.read_text(encoding="utf-8"))) if args.input else StaticWingCase()
        result = run_wing_static(case,args.root)
    elif args.action == "flight":
        case = FlightLoadCase.from_dict(json.loads(args.input.read_text(encoding="utf-8"))) if args.input else FlightLoadCase()
        result = run_flight_structure(case,args.root)
    elif args.action == "mesh":
        case = StructureMeshCase.from_dict(json.loads(args.input.read_text(encoding="utf-8"))) if args.input else StructureMeshCase()
        result = run_structure_mesh(case,args.root)
    elif args.action == "plate":
        case = PlateCase.from_dict(json.loads(args.input.read_text(encoding="utf-8"))) if args.input else PlateCase()
        result = run_plate_analysis(case,args.root)
    else:
        case = WingCase.from_dict(json.loads(args.input.read_text(encoding="utf-8"))) if args.input else WingCase()
        result = run_analysis(case, args.root, args.mode)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result.get("status") in ("failed", "invalid_input", "needs_confirmation") else 0


if __name__ == "__main__":
    raise SystemExit(main())
