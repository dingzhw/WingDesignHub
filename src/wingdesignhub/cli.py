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
from .sizing_service import run_sizing
from .comparison_service import run_comparison, compare_sizing_runs


def main():
    parser = argparse.ArgumentParser(description="WingDesignHub 开发与自动化入口")
    parser.add_argument("action", choices=["run", "doctor", "reference", "mesh", "static", "flight", "plate", "prepare", "size", "geometry", "compare", "compare-runs", "cruise-check", "fuel-check", "archive-save", "archive-open", "report", "fastga-reference", "fastga-contract"])
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--input", type=Path)
    parser.add_argument("--run-ids", nargs=3)
    parser.add_argument("--run-id")
    parser.add_argument("--geometry-run-id")
    parser.add_argument("--tessellation",type=int,choices=[1,2],default=1)
    parser.add_argument("--output",type=Path)
    parser.add_argument("--purpose", choices=['design_trade','requirements_sensitivity'], default='design_trade')
    parser.add_argument("--mode", choices=["beam", "avl", "openvsp_avl"], default="beam")
    parser.add_argument("--benchmark", choices=["fastga","calculix","oas","vsp_structure","oas_wingbox","shell_static","box_comparison","plate_buckling","structural_sensitivity"], default="oas")
    args = parser.parse_args()
    if args.input and (args.action in ("fastga-reference", "fastga-contract") or
                       (args.action == "reference" and args.benchmark == "fastga")):
        parser.error("公开参考任务保留固定输入，不接受自定义需求覆盖；请用 prepare 保存需求。")
    if args.action == "doctor":
        result = inventory(args.root)
    elif args.action == 'geometry':
        from .geometry_service import run_aircraft_geometry
        from .aircraft_geometry import GeometryOptions
        if not args.run_id:parser.error('geometry 需要 --run-id 已收敛总体运行')
        path=args.input or args.root/'runs'/args.run_id/'input.json'
        project=DesignProject.from_dict(json.loads(path.read_text('utf-8')))
        result=run_aircraft_geometry(project,args.root,args.run_id,GeometryOptions(tessellation=args.tessellation))
    elif args.action == 'fuel-check':
        from .fuel_validation import run_fuel_validation
        result=run_fuel_validation(args.root)
    elif args.action in ('archive-save','archive-open','report'):
        from .project_archive import build_bundle,save_bundle,read_bundle
        from .design_comparison import ComparisonRequest
        from .service import get_results,generate_report
        if args.action=='archive-open':
            if not args.input:parser.error('archive-open 需要 --input 方案包')
            data=read_bundle(args.input.read_bytes())
            result={'status':'archive_opened','manifest':data['manifest'],'current_source_matches':data['current_source_matches'],
                    'migration_required':data['migration_required'],'requirements':data['project'].to_dict()}
        else:
            if args.action=='report' and (not args.run_id or not args.output):parser.error('report 需要 --run-id 和 --output')
            record=get_results(args.root,args.run_id) if args.run_id else None
            path=args.input or (args.root/'runs'/args.run_id/'input.json' if args.run_id else None)
            if path is None:parser.error('需要 --input 需求配置或 --run-id')
            raw=json.loads(path.read_text('utf-8'))
            project=ComparisonRequest.from_dict(raw) if 'projects' in raw else DesignProject.from_dict(raw)
            if args.action=='report':
                data=generate_report(record,project=project,root=args.root).encode('utf-8')
                with args.output.open('xb') as f:f.write(data)
                result={'status':'report_exported','output':str(args.output)}
            else:
                geometry=get_results(args.root,args.geometry_run_id) if args.geometry_run_id else None
                data=build_bundle(project,args.root,record,geometry);result={'status':'archive_saved',**save_bundle(data,args.root)}
                if args.output:
                    with args.output.open('xb') as f:f.write(data)
    elif args.action == "compare":
        if not args.input: parser.error('compare 需要 --input 三方案配置')
        result = run_comparison(json.loads(args.input.read_text(encoding='utf-8')),args.root)
    elif args.action == "compare-runs":
        if not args.run_ids: parser.error('compare-runs 需要三个 --run-ids')
        result = compare_sizing_runs(args.root,args.run_ids,args.purpose)
    elif args.action == "cruise-check":
        from .reference_cruise import run_public_cruise
        result = run_public_cruise(args.root)
    elif args.action in ("prepare", "size"):
        case = DesignProject.from_dict(json.loads(args.input.read_text(encoding="utf-8"))) if args.input else DesignProject()
        result = (run_sizing if args.action == "size" else prepare_design_project)(case, args.root)
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
    return 1 if result.get("status") in ("failed", "invalid_input", "needs_confirmation", "out_of_domain", "not_converged", "constraints_not_met", "comparison_incomplete", "model_discrepancy") else 0


if __name__ == "__main__":
    raise SystemExit(main())
