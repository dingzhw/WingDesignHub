"""Local-only configuration and bounded preflight checks, without calibration."""
from pathlib import Path
import math
from .adapters import tool_paths


def preflight(root,kind,project,options):
    diagnostics=[]
    required={'geometry':['openvsp'],'aero':['avl'],'trim':['avl'],
        'drag':['xfoil'],'feedback':['openvsp','avl','xfoil'],'coupled':['openvsp','avl','xfoil'],
        'propulsion':['xfoil']}.get(kind,[])
    paths=tool_paths(root)
    for tool in required:
        p=Path(paths[tool])
        ok=p.is_dir() and (p/'vsp.exe').is_file() if tool=='openvsp' else p.is_file()
        if not ok:diagnostics.append({'severity':'error','code':'tool_missing','tool':tool,'message':f'缺少 {tool}，请在工具设置中配置。'})
    if kind in ('coupled','propulsion'):
        from .ccblade_adapter import runtime
        try:runtime(root)
        except (ValueError,OSError,KeyError) as exc:
            diagnostics.append({'severity':'error','code':'ccblade_not_configured','message':str(exc)})
        opts=options.get('propeller',options);rpm=opts.get('rpm',2400.)
        h=project['assumptions']['cruise_altitude_m'];v=project['assumptions']['cruise_speed_m_s']
        from .configuration import PROPELLER_DIAMETER_M
        tip=math.hypot(v,rpm*math.pi/30*PROPELLER_DIAMETER_M/2)/math.sqrt(1.4*287.05*(288.15-.0065*h))
        if tip>.75:
            diagnostics.append({'severity':'error','code':'propeller_tip_mach_exceeded','tip_mach':tip,
                'message':f'规定巡航工况的桨尖螺旋 Mach={tip:.4f} 超过 0.75；请核对转速与速度。'})
        from .ccblade_adapter import FULL_SCALE_REYNOLDS,conditions
        atmosphere=conditions(v,h,rpm,0);radius=PROPELLER_DIAMETER_M/2
        reynolds=[]
        for fraction in (.2,.4,.6,.8,1.):
            chord=opts.get('root_chord_m',.18)+(opts.get('tip_chord_m',.08)-opts.get('root_chord_m',.18))*(fraction-.2)/.8
            velocity=math.hypot(v,rpm*math.pi/30*radius*fraction)
            reynolds.append(atmosphere['density_kg_m3']*velocity*chord/atmosphere['viscosity_pa_s'])
        covered=min(reynolds)>=FULL_SCALE_REYNOLDS[0] and max(reynolds)<=FULL_SCALE_REYNOLDS[-1]
        diagnostics.append({'severity':'info' if covered else 'warning','code':'uninduced_reynolds_screen',
            'estimated_min':min(reynolds),'estimated_max':max(reynolds),'table_bounds':[FULL_SCALE_REYNOLDS[0],FULL_SCALE_REYNOLDS[-1]],
            'message':'已按桨径、转速、弦长和巡航条件估计未诱导 Re；实际叶素状态仍须由 BEM 检查，超出表范围的估计作为风险提示。'})
        diagnostics.append({'severity':'info','code':'runtime_domain_checks',
            'message':'预检仅检查规定巡航工况；实际爬升/留空速度、叶素迎角/Re、扭矩和耗油图范围在每个原生工况继续检查。'})
    return diagnostics


def check_ccblade(root,work):
    from .ccblade_adapter import runtime
    from .adapters import execute,sha256
    cfg=runtime(root);work=Path(work);work.mkdir(parents=True,exist_ok=True)
    code='using CCBlade; println("WDH_VERSION="*string(pkgversion(CCBlade))); println("WDH_PATH="*pathof(CCBlade)); println("WDH_JULIA="*string(VERSION))'
    output=execute([cfg['julia'],'--startup-file=no','--compiled-modules=existing','--threads=1','--project='+cfg['project'],'-e',code],work,timeout=90)
    parsed=dict(line[4:].split('=',1) for line in output.splitlines() if line.startswith('WDH_'))
    if parsed.get('VERSION')!='1.0.0' or Path(parsed['PATH']).resolve()!= (Path(cfg['package'])/'src/CCBlade.jl').resolve():
        raise ValueError('Julia 实际载入的 CCBlade 版本或路径与配置不符')
    return {'status':'runtime_checked','version':parsed['VERSION'],'julia_version':parsed['JULIA'],
        'source_sha256':sha256(parsed['PATH']),'scope':'导入与版本核查；气动精度见公开桨算例'}
