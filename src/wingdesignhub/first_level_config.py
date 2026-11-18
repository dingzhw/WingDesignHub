"""Opt-in, confirmed research limits; none of these defaults is type-certificate data."""
import math


def default_first_level():
    return dict(version='concept_constraints_v1', takeoff_limit_m=800., landing_limit_m=700.,
        field_altitude_m=0., temperature_delta_k=0., obstacle_m=15.24,
        takeoff_cl_max=1.6, takeoff_cd_increment=.025, landing_cd_increment=.075,
        rolling_friction=.025, braking_friction=.30, disk_power_factor=.65,
        approach_deg=3., flare_load_factor=1.2, rotation_time_s=2., landing_delay_s=2.,
        schedule_cl_ceiling=.50, schedule_max_speed_m_s=90.,
        cg_min_mac=.15, cg_max_mac=.35, static_margin_min=.05,
        wing_cm_ac=-.05, moment_bias_abs=.05, tail_dynamic_pressure_ratio=.9,
        downwash_gradient=.35, elevator_effectiveness=.6, alpha_zero_lift_deg=-2.,
        alpha_limit_deg=6., elevator_limit_deg=10., loading_cases=[],
        source='V0.3.4 一级概念研究假设；干燥水平硬跑道、无风，非具体机型性能或适航限值')


BOUNDS={'takeoff_limit_m':(100,5000),'landing_limit_m':(100,5000),
 'field_altitude_m':(0,4000),'temperature_delta_k':(-20,35),'obstacle_m':(5,20),
 'takeoff_cl_max':(1.1,2.2),'takeoff_cd_increment':(0,.15),'landing_cd_increment':(0,.3),
 'rolling_friction':(.01,.08),'braking_friction':(.1,.6),'disk_power_factor':(.4,.85),
 'approach_deg':(2,5),'flare_load_factor':(1.1,1.4),'rotation_time_s':(0,5),'landing_delay_s':(0,5),
 'schedule_cl_ceiling':(.35,.55),'schedule_max_speed_m_s':(40,90),
 'cg_min_mac':(-.1,.5),'cg_max_mac':(0,.6),'static_margin_min':(0,.3),
 'wing_cm_ac':(-.15,.05),'moment_bias_abs':(0,.15),'tail_dynamic_pressure_ratio':(.7,1.),
 'downwash_gradient':(0,.7),'elevator_effectiveness':(.3,.8),'alpha_zero_lift_deg':(-4,0),
 'alpha_limit_deg':(1,6),'elevator_limit_deg':(1,10)}


def validate_first_level(c):
    if c is None:return
    ref=default_first_level()
    if not isinstance(c,dict) or set(c)!=set(ref) or c['version']!=ref['version']:
        raise ValueError('一级约束字段或版本无效')
    for k,(lo,hi) in BOUNDS.items():
        v=c[k]
        if k in ('takeoff_limit_m','landing_limit_m') and v is None:continue
        if type(v) not in (float,int) or not math.isfinite(v) or not lo<=v<=hi:
            raise ValueError(f'一级约束 {k} 须在 [{lo}, {hi}] 范围')
    if c['cg_min_mac']>=c['cg_max_mac']:raise ValueError('CG下限须小于上限')
    if not isinstance(c['source'],str) or not c['source'].strip():raise ValueError('一级约束须声明来源')
    if not isinstance(c['loading_cases'],list) or len(c['loading_cases'])>8:raise ValueError('装载工况限8组')
    names=set()
    for r in c['loading_cases']:
        if not isinstance(r,dict) or set(r)!={'name','payload_fractions'} or not isinstance(r['name'],str) or not r['name'].strip() or r['name'] in names:
            raise ValueError('装载工况须有唯一名称及载荷分配')
        names.add(r['name']);f=r['payload_fractions']
        if not isinstance(f,dict) or set(f)!={'front_seats','rear_seats','baggage'} or any(type(v) not in (int,float) or not math.isfinite(v) or not 0<=v<=1 for v in f.values()) or abs(sum(f.values())-1)>1e-12:
            raise ValueError('装载分配须非负且和为1；按原总载荷，不改变任务')
