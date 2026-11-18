"""Declared first-level loading and longitudinal constraints, not a stability envelope."""
import math
from .sizing_physics import G, density, speed_candidates, speed_schedule
from .field_performance import takeoff, landing
from .layout import fuel_station


def loading_cases(summary,p):
    g=summary['geometry'];rows=summary['cg']['rows'];ms=summary['mission']
    mass=math.fsum(r['mass_kg'] for r in rows);moment=math.fsum(r['mass_kg']*r['x_m'] for r in rows)
    used=ms['takeoff_roll_fuel_kg']+math.fsum(r['fuel_kg'] for r in ms['segments'])
    if not 0<=used<=ms['takeoff_fuel_kg'] or mass-used<=0:raise ValueError('装载轨迹耗油无效')
    definitions=[('规定装载',moment)]
    if p.sizing.layout is not None:
        stations=p.sizing.layout['stations_fraction'];lf=g['fuselage_length_m']
        payload_moment=math.fsum(r['mass_kg']*r['x_m'] for r in rows if r.get('category')=='payload')
        for case in p.sizing.first_level['loading_cases']:
            pm=p.payload_kg*math.fsum(f*stations[k]*lf for k,f in case['payload_fractions'].items())
            definitions.append((case['name'],moment-payload_moment+pm))
    cases=[];xle=g['wing_quarter_x_m']-.25*g['mac_m'];fx=fuel_station(g,p)
    for name,mo in definitions:
        for phase,burn in (('起飞',0.),('主任务结束',used)):
            m=mass-burn;cg=(mo-burn*fx)/m
            cases.append(dict(name=name+' / '+phase,mass_kg=m,cg_x_m=cg,cg_mac=(cg-xle)/g['mac_m'],
                remaining_usable_fuel_kg=ms['takeoff_fuel_kg']-burn,source='component ledger; airborne burn + takeoff roll; reserve and taxi-in retained'))
    return cases


def longitudinal(mass,cg_x,speed,altitude,geo,p,bias=0.):
    """Two-equation lift/moment balance, angles in radians internally, aft-x/up-z."""
    c=p.sizing.first_level;s=geo['wing_area_m2'];mac=geo['mac_m'];aw=2*math.pi/(1+2/p.sizing.aspect_ratio)
    at=2*math.pi/(1+2/geo['surface_parameters']['horizontal_tail']['aspect_ratio'])
    eta=c['tail_dynamic_pressure_ratio']*geo['horizontal_tail_area_m2']/s;de=c['downwash_gradient'];tau=c['elevator_effectiveness']
    layout=p.sizing.layout or {};iw=math.radians(layout.get('wing_incidence_deg',0.));it=math.radians(layout.get('tail_incidence_deg',0.))
    w0=aw*(iw-math.radians(c['alpha_zero_lift_deg']));t0=at*it
    h=(cg_x-(geo['wing_quarter_x_m']-.25*mac))/mac
    arm=(geo['wing_quarter_x_m']+geo['tail_arm_m']-cg_x)/mac
    cla=aw+eta*at*(1-de);cld=eta*at*tau
    cma=aw*(h-.25)-eta*at*(1-de)*arm;cmd=-eta*at*tau*arm
    cl0=w0+eta*t0;cm0=c['wing_cm_ac']+bias+w0*(h-.25)-eta*t0*arm
    need=mass*G/(.5*density(altitude)*speed**2*s);det=cla*cmd-cld*cma
    if abs(det)<1e-12:raise ValueError('纵向一级模型矩阵奇异')
    alpha=((need-cl0)*cmd+cld*cm0)/det;delta=(-cla*cm0-cma*(need-cl0))/det
    clt=at*(1-de)*alpha+at*tau*delta+t0
    return dict(alpha_deg=math.degrees(alpha),elevator_deg=math.degrees(delta),tail_cl=clt,
        tail_lift_n=.5*density(altitude)*speed**2*geo['horizontal_tail_area_m2']*c['tail_dynamic_pressure_ratio']*clt,
        static_margin=-cma/cla,cma_per_rad=cma,cla_per_rad=cla,moment_bias=bias,
        lift_residual=cla*alpha+cld*delta+cl0-need,moment_residual=cma*alpha+cmd*delta+cm0,
        method='finite_wing_linear_tail_v1',speed_m_s=speed,altitude_m=altitude)


def evaluate(summary,p):
    c=p.sizing.first_level;g=summary['geometry'];mass=summary['design_mtow_kg'];area=g['wing_area_m2']
    result={'config':c,'method':'first_level_concept_v1',
        'field_basis':{'mass_kg':mass,'area_m2':area,'rated_power_w':summary['power']['installed_power_w'],
                       'mass_definition':'design MTOW; landing at MTOW is conservative, not inferred from end-of-mission mass'},
        'field':{},'loading':loading_cases(summary,p),'longitudinal':[],
        'limits':['起降为干燥水平硬跑道、无风、规定工程襟翼/摩擦及作用盘损失模型；未经具体全尺寸桨、襟翼和试飞标定。',
          '场地温度/高度仅用于起降；任务仍采用规定巡航高度的标准大气。起降段耗油仍沿用30s/90%功率，距离校核与瞬态燃油尚未联算。',
          'CG研究区间来自用户假设，不是允许装载包线；额外装载分配须另核座椅/行李舱限重。',
          '纵向一级模型采用有限翼升力斜率和线性下洗；未包括机身、滑流、推力线及黏性俯仰矩修正。给定Cm扰动是情景范围，不是统计置信区间。',
          'AVL/XFOIL和一级模型的俯仰力矩均有误差；力矩平衡、低角度余量与局部静稳定分别报告，完整操稳/操纵力仍未计算。',
          '速度为低CL域内9个候选的初步最小需用功率选择；增强模型沿用并验证实际工况，不宣称原生气动全域最优。']}
    for name,fn in [('takeoff',lambda:takeoff(mass,area,summary['power']['installed_power_w'],p)),
                    ('landing',lambda:landing(mass,area,p))]:
        try:result['field'][name]={'calculation_status':'computed',**fn()}
        except ValueError as exc:result['field'][name]={'calculation_status':'not_calculated','reason':str(exc)}
    for case in result['loading']:
        points=[longitudinal(case['mass_kg'],case['cg_x_m'],p.assumptions.cruise_speed_m_s,
                  p.assumptions.cruise_altitude_m,g,p,bias) for bias in sorted(set((-c['moment_bias_abs'],0.,c['moment_bias_abs'])))]
        result['longitudinal'].append({'loading_case':case['name'],'points':points})
    climb,loiter,vs=speed_schedule(mass,g,p)
    result['speed_selection']={'candidates_m_s':speed_candidates(mass,g,p),'initial_climb_m_s':climb,
         'initial_loiter_m_s':loiter,'cl_ceiling':c['schedule_cl_ceiling'],'method':'finite candidate minimum conceptual shaft power',
         'actual_mission_speeds_m_s':{r['segment']:r['speed_m_s'] for r in summary['mission']['segments']}}
    return result
