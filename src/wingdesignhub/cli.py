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


def main():
    parser = argparse.ArgumentParser(description="WingDesignHub 开发与自动化入口")
    parser.add_argument("action", choices=["run", "doctor", "reference", "mesh", "static"])
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--input", type=Path)
    parser.add_argument("--mode", choices=["beam", "avl", "openvsp_avl"], default="beam")
    parser.add_argument("--benchmark", choices=["fastga","calculix","oas","vsp_structure","oas_wingbox","shell_static"], default="oas")
    args = parser.parse_args()
    if args.action == "doctor":
        result = inventory(args.root)
    elif args.action == "reference":
        result = run_reference(args.root,args.benchmark)
    elif args.action == "static":
        case = StaticWingCase.from_dict(json.loads(args.input.read_text(encoding="utf-8"))) if args.input else StaticWingCase()
        result = run_wing_static(case,args.root)
    elif args.action == "mesh":
        case = StructureMeshCase.from_dict(json.loads(args.input.read_text(encoding="utf-8"))) if args.input else StructureMeshCase()
        result = run_structure_mesh(case,args.root)
    else:
        case = WingCase.from_dict(json.loads(args.input.read_text(encoding="utf-8"))) if args.input else WingCase()
        result = run_analysis(case, args.root, args.mode)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result.get("status") == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
