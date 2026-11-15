"""Shared recorded AVL -> mass relief -> shell -> panel screening service."""
from datetime import datetime,timezone
from pathlib import Path
from uuid import uuid4
import traceback
from . import __version__
from .adapters import tool_paths,sha256
from .fea_mesh import read_inp,audit_mesh
from .structure_service import generate_mesh
from .shell_static import promote_s6,solve_shell,read_dat
from .flight_loads import FlightLoadCase,aerodynamic_loads,combine_loads
from .buckling import panel_screen
from .service import write_json


def run_flight_structure(case,root):
    if isinstance(case,dict):case=FlightLoadCase.from_dict(case)
    case.validate();root=Path(root).resolve();run_id=uuid4().hex;work=root/'runs'/run_id;work.mkdir(parents=True)
    write_json(work/'input.json',case.to_dict());source=Path(__file__).parent
    r={'run_id':run_id,'version':__version__,'mode':'flight_structure','status':'running',
       'started_utc':datetime.now(timezone.utc).isoformat(),'input_hash':sha256(work/'input.json'),
       'source_hashes':{p.relative_to(source).as_posix():sha256(p) for p in source.rglob('*.py')},'physical_validation_passed':False}
    write_json(work/'result.json',r)
    try:
        tools=tool_paths(root)
        for name in ('avl','calculix'):
            if not tools[name] or not Path(tools[name]).is_file():raise FileNotFoundError(f'请配置 {name} 求解器')
        p,f,aero=aerodynamic_loads(case,tools['avl'],work/'aero')
        generate_mesh(case.mesh,work/'mesh');linear=read_inp(work/'mesh/wing.inp');audit_mesh(linear,case.mesh)
        mesh=promote_s6(linear);ids,forces,loads=combine_loads(case,mesh,p,f);write_json(work/'loads.json',loads)
        s=solve_shell(tools['calculix'],work/'solve',mesh,ids,forces,case.mesh.half_span_m,loads['mapping'],allow_root_loads=True)
        _,stress=read_dat(work/'solve/wing.dat',mesh);buckling=panel_screen(mesh,case.mesh,stress);write_json(work/'buckling.json',buckling)
        s.update(aero=aero,mapping=loads['mapping'],load_components=loads['components'],structure_mass=loads['structure_mass'],
                 represented_half_mass_kg=loads['represented_half_mass_kg'],buckling=buckling,
                 yield_margin=case.stress_allowable_pa/s['peak_von_mises_pa']-1.,
                 displacement_span_ratio=s['max_displacement_m']/case.mesh.half_span_m,
                 mesh_sensitivity_checked=False,physical_validation_passed=False,strength_certified=False,
                 limits=['孤立矩形 NACA0012 机翼承担全机规定升力，迎角由 AVL 求得；未包含尾翼/机身配平和失速',
                 '条带升力作为几何 z 载荷施加在 1/4 弦；忽略轴向力与剖面俯仰矩，投影近似误差单独报告',
                 '结构质量由各壳单元面积/厚度/密度生成，燃油和集中质量属于整机质量台账；竖向重力与惯性以 -m*n_z*g 合并一次',
                 '无转动加速度/离心惯性；燃油和设备按合力映射到蒙皮，尚未定义压力场或实际支座',
                 '根部全固支；根部节点质量保留并计入平衡。结构质量尚未回写总体模型；材料限值为合成输入']+buckling['limits'])
        # Any screen failure remains visible even when the numerical solve succeeds.
        issues=[]
        if s['yield_margin']<0:issues.append('规定应力限值未满足')
        if s['displacement_span_ratio']>.05:issues.append('小变形位移筛查未满足')
        if not buckling['screen_passed']:issues.append('局部板屈曲工程筛查未满足')
        s['screening_issues']=issues;r['summary']=s;r['status']='executed_with_limits' if issues else 'screened'
    except Exception as exc:
        r.update(status='failed',error=str(exc));(work/'error.log').write_text(traceback.format_exc(),encoding='utf-8')
    r['finished_utc']=datetime.now(timezone.utc).isoformat()
    r['artifact_hashes']={p.relative_to(work).as_posix():sha256(p) for p in work.rglob('*') if p.is_file() and p.name!='result.json'}
    write_json(work/'result.json',r);return r
