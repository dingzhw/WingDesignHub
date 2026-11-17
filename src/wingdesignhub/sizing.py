"""Deterministic bounded mass/fuel/power sizing, with traceable residuals."""
import math
from .requirements import DesignProject, build_design_intent
from .sizing_physics import geometry, constraints, mission, DesignDomainError


LIMITS=['常规低速金属单发、2–6 座；失速/功率/容量为当前已检查约束',
        '气动为规定抛物线极曲线，桨效率为常数；耗油按所选模型分段记录，未调用全机 AVL/XFOIL/CCBlade，尚未计算配平',
        'FAST-GA 经验重量替代部件结构定尺寸；当前蒙皮稳定性风险不因总体质量收敛而关闭',
        '重心由规定站位估算，未验证操稳重心包线；起降距离、操纵裕度及适航验收另行接入',
        '固定重量为规定满载设计重量；计算装载质量与剩余质量预算分别报告，不把余量当成已配置压舱物']


def cg_ledger(weights,geo,p,ms):
    x=geo['wing_quarter_x_m'];lf=geo['fuselage_length_m']
    stations={'airframe':.44*lf,'propulsion':.12*lf,'systems':.4*lf,'furniture':.4*lf,'unusable_fuel':x}
    rows=[{'component':n,'mass_kg':mass,'x_m':stations[n]} for n,mass in weights['categories_kg'].items()]
    rows += [{'component':'payload','mass_kg':p.payload_kg,'x_m':x}, {'component':'takeoff_fuel','mass_kg':ms['takeoff_fuel_kg'],'x_m':x}]
    total=sum(r['mass_kg'] for r in rows);cg=sum(r['mass_kg']*r['x_m'] for r in rows)/total
    end_mass=total-ms['trip_fuel_from_takeoff_kg']
    end_cg=(cg*total-ms['trip_fuel_from_takeoff_kg']*x)/end_mass
    return {'rows':rows,'loaded_mass_kg':total,'cg_x_m':cg,'end_cg_x_m':end_cg,
            'cg_mac_fraction':(cg-(x-.25*geo['mac_m']))/geo['mac_m'],'stations_source':'conceptual fixed component stations; no trim/CG envelope validation'}


def solve_design(project, mass_model, max_iterations=80, dt=30., *, feedback=None, initial_summary=None):
    if type(max_iterations) is not int or max_iterations<1:
        raise ValueError('最大迭代次数须为正整数')
    if not math.isfinite(dt) or dt<=0: raise ValueError('任务积分步长须为正有限值')
    p=DesignProject.from_dict(project) if isinstance(project,dict) else project
    intent=build_design_intent(p)
    if intent['status']!='requirements_ready':return {'status':intent['status'],'diagnostics':intent['diagnostics'],'converged':False}
    if not 40<=p.assumptions.cruise_speed_m_s<=90 or not 0<=p.assumptions.cruise_altitude_m<=4000 or not 50<=p.payload_kg<=600:
        return {'status':'out_of_domain','converged':False,'diagnostics':['首期载荷 50–600 kg、巡航速度 40–90 m/s、高度 0–4000 m']}
    fixed=p.weight.mode=='fixed'
    mass=p.weight.value_kg if fixed else max(800.,p.payload_kg*2.5)
    fuel=100.;previous=None;consecutive=0;history=[]
    power_guess=None
    if feedback is not None:
        if not initial_summary or not initial_summary.get('converged'):raise ValueError('气动反馈需要已收敛的初始总体方案')
        mass=initial_summary['design_mtow_kg'];fuel=initial_summary['mission']['block_fuel_kg']
        power_guess=initial_summary['power']['installed_power_w']
    try:
        for i in range(max_iterations):
            from .job_events import event
            event('iteration_started',iteration=i+1,mass_kg=mass)
            if not 400<=mass<=2500:raise DesignDomainError('试算质量超出本模板 400–2500 kg 范围')
            geo=geometry(mass,fuel,p);coupling={}
            if feedback is None:
                power=constraints(mass,geo,p)
                ms=mission(mass,geo,power['installed_power_w'],p,dt)
                weights=mass_model.evaluate(mass,power['installed_power_w'],geo,p)
                ledger=cg_ledger(weights,geo,p,ms)
            else:
                power,ms,weights,ledger,coupling=feedback.evaluate(mass,geo,fuel,power_guess,mass_model,i+1,dt)
            if not 40000<=power['installed_power_w']<=400000:raise DesignDomainError('安装功率超出首期 40–400 kW 范围')
            required=ledger['loaded_mass_kg']
            state=[mass,ms['block_fuel_kg'],power['installed_power_w'],weights['owe_kg']]
            residuals={'mass_closure_fraction':(required-mass)/mass,'fuel_capacity_kg':geo['usable_tank_capacity_kg']-ms['block_fuel_kg']}
            residuals.update(coupling)
            if previous:
                residuals['max_state_change']=max(abs(x/y-1) for x,y in zip(state,previous['state']))
                residuals['cg_change_mac']=abs(ledger['cg_x_m']-previous['cg'])/geo['mac_m']
                stable=residuals['max_state_change']<1e-4 and residuals['cg_change_mac']<.001 and (fixed or abs(residuals['mass_closure_fraction'])<1e-4)
                if feedback is not None:stable=stable and coupling['power_weight_coupling']<1e-4 and coupling['dry_weight_coupling']<1e-4
                consecutive=consecutive+1 if stable else 0
            history.append({'iteration':i+1,'design_mtow_kg':mass,'required_loaded_mass_kg':required,
                            'block_fuel_kg':ms['block_fuel_kg'],'installed_power_w':power['installed_power_w'],
                            'wing_area_m2':geo['wing_area_m2'],'owe_kg':weights['owe_kg'],'cg_x_m':ledger['cg_x_m'],
                            'residuals':residuals,'stable_rounds':consecutive})
            event('iteration_completed',**history[-1])
            if consecutive>=3 or i+1==max_iterations:break
            previous={'state':state,'cg':ledger['cg_x_m']}
            relaxation=.5 if feedback is None else .75
            if not fixed:mass=(1-relaxation)*mass+relaxation*required
            fuel=(1-relaxation)*fuel+relaxation*ms['block_fuel_kg']
            if feedback is not None:power_guess=(1-relaxation)*power_guess+relaxation*power['installed_power_w']
        converged=consecutive>=3
        allowance=.005*mass
        # The aerodynamic mission uses actual loaded mass, while area is sized at
        # design mass. Map the declared 1e-4 mass closure tolerance through Vs~sqrt(m).
        stall_factor=math.sqrt(1+1e-4) if feedback is not None and not fixed else 1+1e-9
        checks={'mass_budget':required<=mass+.01 if fixed else abs(required-mass)<=allowance,
                'mtow_upper_bound':p.weight.mode!='upper_bound' or mass<=p.weight.value_kg,
                'fuel_capacity':ms['block_fuel_kg']<=geo['usable_tank_capacity_kg']+1e-4,
                'landing_stall':power['landing_stall_m_s']<=p.sizing.stall_speed_m_s*stall_factor,
                'power_available':ms['max_power_fraction']<=1.001,
                'clean_lift':ms['max_clean_cl']<=p.sizing.cl_max_clean,
                'range':p.mission.range_m is None or abs(ms['route_distance_m']-p.mission.range_m)<max(1.,p.mission.range_m*1e-6),
                'endurance':p.mission.endurance_s is None or ((next(r['duration_s'] for r in ms['segments'] if r['segment']=='loiter') if p.mission.kind=='transit_loiter' else ms['main_duration_s'])>=p.mission.endurance_s-1e-6)}
        status='not_converged' if not converged else ('concept_checked_with_limits' if all(checks.values()) else 'constraints_not_met')
        result={'status':status,'converged':converged,'checks':checks,'iterations':history,
                'design_mtow_kg':mass,'required_loaded_mass_kg':required,'weight_mode':{'mode':p.weight.mode,'value_kg':p.weight.value_kg},
                'convergence_thresholds':{'state_relative':1e-4,'mass_relative':1e-4,'cg_mac':.001,'consecutive_rounds':3},
                'landing_stall_numerical_relative_tolerance':stall_factor-1,
                'mass_budget_margin_kg':mass-required,'ramp_mass_design_kg':mass+ms['taxi_out_fuel_kg'],
                'upper_bound_margin_kg':p.weight.value_kg-mass if p.weight.mode=='upper_bound' else None,
                'geometry':geo,'power':power,'mission':ms,'weights':weights,'cg':ledger,
                'method':'FAST-GA native mass + declared point-mass mission + explicit constraint sizing',
                'physical_validation_passed':False,'trim_checked':False,'limits':LIMITS}
        if feedback is not None:
            result['method']='FAST-GA native mass + bounded native trim/drag tables + shared point-mass mission and sizing iteration'
            feedback.finalize(result)
        return result
    except DesignDomainError as exc:
        return {'status':'out_of_domain','converged':False,'diagnostics':[str(exc)],'error_code':getattr(exc,'status','out_of_domain'),
                'diagnostic_context':getattr(exc,'context',{}),'iterations':history,'limits':getattr(feedback,'limits',LIMITS)}
