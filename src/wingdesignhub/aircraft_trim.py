"""Bounded two-equation lifting-surface trim; actual residuals decide convergence."""
from copy import deepcopy
from dataclasses import asdict, dataclass
from pathlib import Path
import json
import math
import shutil
import numpy as np
from .aircraft_aero import AeroOptions, make_contract, LIMITS as AERO_LIMITS
from .flight_state import make_flight_state, finite
from .sizing_physics import G
from .service import write_json

LIMITS=AERO_LIMITS[:5]+[
    '对称、水平、零角速度的升力面配平：CL=mg/qS、Cm=0；机身、推进力/力矩及黏性项未计入，轴向力未闭合。',
    '局部 Cma 与舵量余量作为诊断；配平通过不等同于完整静稳定、操纵重心包线或任务可行。',
    '质量/重心来自当前概念台账或明确自定义工况；起飞设计值与实际装载分别记录，未分配预算不自动成为压舱物。',
    '使用原生近似导数作迭代 Jacobian，每步以实际 AVL 残差判断；总体任务仍使用原概念极曲线。',
]


@dataclass(frozen=True)
class TrimOptions:
    mass_state: str = 'takeoff'
    mass_kg: float | None = None
    cg_x_m: float | None = None
    source_note: str = ''
    speed_m_s: float | None = None
    altitude_m: float | None = None
    mesh_level: int = 2
    alpha_min_deg: float = -6.
    alpha_max_deg: float = 6.
    elevator_min_deg: float = -10.
    elevator_max_deg: float = 10.
    initial_alpha_deg: float = 3.
    initial_elevator_deg: float = 0.
    max_iterations: int = 12

    def validate(self):
        AeroOptions(speed_m_s=self.speed_m_s,altitude_m=self.altitude_m,mesh_level=self.mesh_level).validate()
        for name in ('alpha_min_deg','alpha_max_deg','elevator_min_deg','elevator_max_deg','initial_alpha_deg','initial_elevator_deg'):
            finite(getattr(self,name),name)
        if not -6<=self.alpha_min_deg<self.alpha_max_deg<=6:raise ValueError('迎角求解区间须位于 ±6° 内')
        if not -10<=self.elevator_min_deg<self.elevator_max_deg<=10:raise ValueError('升降舵求解区间须位于 ±10° 内')
        if not self.alpha_min_deg<=self.initial_alpha_deg<=self.alpha_max_deg or not self.elevator_min_deg<=self.initial_elevator_deg<=self.elevator_max_deg:
            raise ValueError('配平初值须位于求解区间内')
        if type(self.max_iterations) is not int or not 1<=self.max_iterations<=12:raise ValueError('配平最大迭代次数须为 1–12')


def make_trim_contract(interface,project,sizing,options=None):
    o=TrimOptions(**options) if isinstance(options,dict) else (options or TrimOptions());o.validate()
    state=make_flight_state(sizing,o.mass_state,o.mass_kg,o.cg_x_m,o.source_note)
    c=deepcopy(make_contract(interface,project,sizing,AeroOptions(alpha_deg=o.initial_alpha_deg,elevator_deg=o.initial_elevator_deg,
                      speed_m_s=o.speed_m_s,altitude_m=o.altitude_m,mesh_level=o.mesh_level)))
    c['model']='avl_longitudinal_trim_v1';c['geometry_references']=deepcopy(c['references'])
    c['references']['moment_reference_geometry_m']=state['cg_geometry_m']
    c['references']['reference_source']='operating flight_state CG; '+state['mass_state']+'; geometry axes x aft/y right/z up'
    c['coordinates']['body_origin_geometry_m']=state['cg_geometry_m']
    c['flow'].update(mass_kg=state['operating_mass_kg'],mass_source=state['source'])
    c['options']['mass_kg']=state['operating_mass_kg']
    c.update(flight_state=state,trim_options=asdict(o),limits=LIMITS)
    return c


def bounded_newton(evaluate,initial,lower,upper,*,max_iterations=12,tolerance=1e-5):
    """Evaluate returns true residual and an approximate 2x2 Jacobian, both per degree.

    A bounded linear least-squares step plus backtracking stays in the domain. A failed
    search is a diagnostic, not a proof that no mathematical root exists anywhere.
    """
    x=np.array(initial,float);lo=np.array(lower,float);hi=np.array(upper,float);history=[]
    if x.shape!=(2,) or np.any(lo>=hi) or not np.isfinite([x,lo,hi]).all() or np.any(x<lo) or np.any(x>hi):
        raise ValueError('配平未知量、初值或边界无效')
    def sample(point,iteration,scale):
        residual,jac,payload=evaluate(point.copy());residual=np.asarray(residual,float);jac=np.asarray(jac,float)
        if residual.shape!=(2,) or jac.shape!=(2,2) or not np.isfinite(residual).all() or not np.isfinite(jac).all():
            raise ValueError('配平残差或 Jacobian 无效')
        entry={'evaluation':len(history),'iteration':iteration,'alpha_deg':float(point[0]),'elevator_deg':float(point[1]),
               'residual_cl':float(residual[0]),'residual_cm':float(residual[1]),'step_scale':scale,'accepted':False,
               'evaluation_id':payload.get('evaluation_id')}
        history.append(entry)
        return residual,jac,payload,entry
    r,j,p,entry=sample(x,0,0.);entry['accepted']=True;status='trim_not_converged';reason='达到最大迭代次数'
    for iteration in range(max_iterations+1):
        if np.max(np.abs(r))<=tolerance:status='trim_checked_with_limits';reason='实际升力与俯仰矩残差达到门槛';break
        if iteration==max_iterations:break
        condition=float(np.linalg.cond(j))
        if not math.isfinite(condition) or condition>1e8:
            status='trim_jacobian_singular';reason='局部控制 Jacobian 奇异或条件数过大';break
        step=np.linalg.solve(j,-r)
        if np.any(x+step<lo) or np.any(x+step>hi):
            from scipy.optimize import lsq_linear
            subproblem=lsq_linear(j,-r,bounds=(lo-x,hi-x),method='bvls',tol=1e-12,max_iter=50)
            if not subproblem.success:raise ValueError('配平局部有界最小二乘求解失败')
            step=subproblem.x
        if np.max(np.abs(step))<1e-9:
            at_bound=bool(np.any(np.isclose(x,lo,atol=1e-8,rtol=0)) or np.any(np.isclose(x,hi,atol=1e-8,rtol=0)))
            status='trim_bounds_exceeded' if at_bound else 'trim_not_converged'
            reason='求解步长过小，实际残差仍超限';break
        found=False
        for scale in (1.,.5,.25,.125):
            candidate=x+scale*step;nr,nj,npayload,nentry=sample(candidate,iteration+1,scale)
            if np.linalg.norm(nr)<np.linalg.norm(r) or np.max(np.abs(nr))<=tolerance:
                x,r,j,p=candidate,nr,nj,npayload;nentry['accepted']=True;found=True;break
        if not found:
            at_bound=bool(np.any(np.isclose(x,lo,atol=1e-8,rtol=0)) or np.any(np.isclose(x,hi,atol=1e-8,rtol=0)))
            status='trim_bounds_exceeded' if at_bound else 'trim_not_converged'
            reason='有界迭代未找到降低残差的步骤；可检查构型/工况，不能据此断言全域无根';break
    active=[name for name,hit in zip(['alpha_lower','elevator_lower','alpha_upper','elevator_upper'],
            np.concatenate((np.isclose(x,lo,atol=1e-8,rtol=0),np.isclose(x,hi,atol=1e-8,rtol=0)))) if hit]
    if status=='trim_bounds_exceeded':reason='达到 '+', '.join(active)+' 边界，实际升力/俯仰矩残差仍超限；检查工况或显式修改构型'
    return {'status':status,'converged':status=='trim_checked_with_limits','diagnostic':reason,'active_bounds':active,
            'solution':x.tolist(),'residuals':r.tolist(),'history':history,'payload':p,
            'tolerances':{'absolute_cl':tolerance,'absolute_cm':tolerance},
            'margins_deg':{'alpha_lower':float(x[0]-lo[0]),'alpha_upper':float(hi[0]-x[0]),
                           'elevator_lower':float(x[1]-lo[1]),'elevator_upper':float(hi[1]-x[1])}}


def solve_trim(contract,executable,work,*,solver=None):
    from .avl_aircraft import solve
    solve=solver or solve
    work=Path(work);options=TrimOptions(**contract['trim_options']);f=contract['flow'];r=contract['references']
    normal=f.get('normal_weight_factor',1.)
    if not math.isfinite(normal) or not 0<normal<=1:raise ValueError('定常航迹配平法向重量系数须在 (0,1] 内')
    target=f['mass_kg']*G*normal/(f['dynamic_pressure_pa']*r['area_m2']);evaluations=[]
    def evaluate(x):
        c=deepcopy(contract);c['flow']['alpha_deg']=float(x[0]);c['options'].update(alpha_deg=float(x[0]),elevator_deg=float(x[1]))
        name=f'evaluations/{len(evaluations):03d}';directory=work/name;directory.mkdir(parents=True)
        write_json(directory/'evaluation_contract.json',c)
        summary=solve(c,executable,directory);write_json(directory/'summary.json',summary)
        evaluations.append(name);d=summary['derivatives'];co=summary['coefficients']
        return [co['CLtot']-target,co['Cmtot']],[[d['CLa']*math.pi/180,d['CLd'][1]],
                    [d['Cma']*math.pi/180,d['Cmd'][1]]],{'evaluation_id':name,'summary':summary,'contract':c}
    answer=bounded_newton(evaluate,[options.initial_alpha_deg,options.initial_elevator_deg],
        [options.alpha_min_deg,options.elevator_min_deg],[options.alpha_max_deg,options.elevator_max_deg],max_iterations=options.max_iterations)
    payload=answer.pop('payload');s=payload['summary'];final=payload['contract'];directory=work/payload['evaluation_id']
    loads=json.loads((directory/'strip_loads.json').read_text('utf-8'))
    for name in ('strip_loads.json','model.avl','case.run','total.mrf','strips.mrf','elements.mrf','stability.mrf'):
        shutil.copy2(directory/name,work/name)
    def totals(data):
        return {name:{'lift_n':sum(z['coefficients']['CL']*f['dynamic_pressure_pa']*r['area_m2'] for z in data['surface_totals'] if z['name'].replace(' (YDUP)','')==name),
                      'pitch_moment_about_cg_nm':sum(z['moment_body_nm'][1] for z in data['surface_totals'] if z['name'].replace(' (YDUP)','')==name)}
                for name in ('MainWing','HorizontalTail','VerticalTail')}
    initial=json.loads((work/evaluations[0]/'summary.json').read_text('utf-8'))
    c=s['coefficients'];q=f['dynamic_pressure_pa'];area=r['area_m2']
    trim={**answer,'level_flight_target_cl':target,'normal_weight_factor':normal,'residual_cl':answer['residuals'][0],'residual_cm':answer['residuals'][1],
          'lift_residual_n':answer['residuals'][0]*q*area,'pitch_residual_nm':answer['residuals'][1]*q*area*r['chord_m'],
          'final_evaluation':payload['evaluation_id'],'evaluation_count':len(evaluations),'flight_state':contract['flight_state'],
          'alpha_deg':s['flow']['alpha_deg'],'elevator_deg':s['options']['elevator_deg'],
          'local_cma_per_rad':s['derivatives']['Cma'],'locally_restoring_pitch':s['derivatives']['Cma']<0,
          'surface_loads':totals(loads),'initial_coefficients':initial['coefficients'],
          'initial_surface_loads':totals(json.loads((work/evaluations[0]/'strip_loads.json').read_text('utf-8'))),
          'induced_drag_n':c['CDff']*q*area,'mission_polar_updated':False,'axial_force_balanced':False,
          'scope':'symmetric steady-flight lifting-surface CL/Cm equilibrium with declared normal weight factor; propulsive and fuselage moments omitted'}
    write_json(work/'final_aero_contract.json',final);write_json(work/'trim_solution.json',trim)
    write_json(work/'flight_state.json',contract['flight_state'])
    return {**s,'status':answer['status'],'passed':answer['converged'],'trim_checked':answer['converged'],
            'trim':trim,'flight_state':contract['flight_state'],'trim_options':contract['trim_options'],
            'limits':LIMITS,'physical_validation_passed':False}
