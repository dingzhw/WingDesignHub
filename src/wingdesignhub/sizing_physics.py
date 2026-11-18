"""Point-mass mission and constraints; SI, still air, parabolic polar.

Lift/drag: NASA Glenn lift/drag equations. Propulsive power is (D V + W ROC)/eta.
Constant BSFC, density-proportional naturally aspirated power and geometry ratios
are declared conceptual assumptions, not empirical validation of an aircraft.
"""
import math
from .configuration import CONFIGURATION_VERSION, surface_parameters

G=9.80665
RHO0=1.225
FUEL_DENSITY=718.9


class DesignDomainError(ValueError): pass


def density(altitude):
    if not 0<=altitude<=4000: raise DesignDomainError('首期标准大气高度限 0–4000 m')
    return RHO0*(1-.0065*altitude/288.15)**4.2558797


def flight_power(mass, area, speed, altitude, roc, assumptions, *, air_density_kg_m3=None):
    if min(mass,area,speed)<=0: raise DesignDomainError('质量、面积和速度必须为正')
    gamma=math.asin(roc/speed)
    rho=density(altitude) if air_density_kg_m3 is None else air_density_kg_m3
    if not math.isfinite(rho) or rho<=0: raise DesignDomainError('空气密度必须为正有限值')
    q=.5*rho*speed**2
    cl=mass*G*math.cos(gamma)/(q*area)
    cd=assumptions.cd0+cl**2/(math.pi*assumptions.oswald_efficiency*assumptions.aspect_ratio)
    drag=q*area*cd
    power=(drag*speed+mass*G*roc)/assumptions.propeller_efficiency
    return power,cl,drag


def geometry(mass, fuel_capacity, p):
    a=p.sizing;rho=density(p.assumptions.cruise_altitude_m)
    parameters=surface_parameters(a.aspect_ratio)
    thickness=parameters['wing']['thickness_ratio']
    areas={'landing_stall':2*mass*G/(RHO0*a.stall_speed_m_s**2*a.cl_max_landing),
           'cruise_lift':2*mass*G/(rho*p.assumptions.cruise_speed_m_s**2*.8*a.cl_max_clean),
           'fuel_volume':(1.02*max(fuel_capacity,1)*math.sqrt(a.aspect_ratio)/(a.tank_volume_fraction*thickness*FUEL_DENSITY*(1-a.unusable_fuel_fraction)))**(2/3)}
    if a.first_level is not None:
        from .field_performance import landing_area
        field_area=landing_area(mass,p)
        if field_area is not None:areas['landing_distance']=field_area
    area=max(areas.values());span=math.sqrt(area*a.aspect_ratio);taper=parameters['wing']['taper_ratio']
    root=2*area/(span*(1+taper));tip=taper*root;mac=2/3*root*(1+taper+taper*taper)/(1+taper)
    arm=.45*a.fuselage_length_m
    return {'configuration_version':CONFIGURATION_VERSION,'surface_parameters':parameters,
            'wing_area_m2':area,'wing_span_m':span,'root_chord_m':root,'tip_chord_m':tip,'mac_m':mac,
            'wing_quarter_x_m':(.39 if a.layout is None else a.layout['wing_quarter_fraction'])*a.fuselage_length_m,'horizontal_tail_area_m2':.7*area*mac/arm,
            'vertical_tail_area_m2':.04*area*span/arm,'tail_arm_m':arm,'fuselage_length_m':a.fuselage_length_m,
            'fuselage_width_m':1.2,'fuselage_height_m':1.35,'tank_capacity_kg':a.tank_volume_fraction*area*math.sqrt(area/a.aspect_ratio)*thickness*FUEL_DENSITY,
            'usable_tank_capacity_kg':a.tank_volume_fraction*area*math.sqrt(area/a.aspect_ratio)*thickness*FUEL_DENSITY*(1-a.unusable_fuel_fraction),
            'capacity_sizing_margin_fraction':.02,
            'sizing_areas_m2':areas,'controlling_area_constraint':max(areas,key=areas.get),'engine_count':1,
            'configuration':'low_wing_conventional_tail_fixed_tricycle_metal','axes':'x aft from nose, y right, z up'}


def speed_schedule(mass, geo, p):
    a=p.sizing;h=p.assumptions.cruise_altitude_m;s=geo['wing_area_m2']
    vs=math.sqrt(2*mass*G/(density(h)*s*a.cl_max_clean))
    climb_speed=1.3*vs;loiter_cl=min(math.sqrt(3*a.cd0*math.pi*a.oswald_efficiency*a.aspect_ratio),.8*a.cl_max_clean)
    loiter_speed=math.sqrt(2*mass*G/(density(h)*s*loiter_cl))
    if a.first_level is not None:
        candidates=speed_candidates(mass,geo,p)
        climb_speed=min(candidates,key=lambda v:flight_power(mass,s,v,h,a.climb_rate_m_s,a)[0])
        loiter_speed=min(candidates,key=lambda v:flight_power(mass,s,v,h,0.,a)[0])
    return climb_speed,loiter_speed,vs


def speed_candidates(mass,geo,p):
    """Finite clean, low-CL search; no stall/high-lift or global optimum claim."""
    c=p.sizing.first_level
    lo=math.sqrt(2*mass*G/(density(p.assumptions.cruise_altitude_m)*geo['wing_area_m2']*c['schedule_cl_ceiling']))
    hi=c['schedule_max_speed_m_s']
    if lo>hi:raise DesignDomainError('速度候选有效域为空：所需CL下限速度超过规定搜索上限')
    return [lo+(hi-lo)*i/8 for i in range(9)]


def constraints(mass, geo, p, *, flight_model=None, schedule=None, include_field=True):
    a=p.sizing;h=p.assumptions.cruise_altitude_m;s=geo['wing_area_m2']
    climb,loiter,vs=schedule or speed_schedule(mass,geo,p);sigma=density(h)/RHO0
    power_at=flight_model or (lambda mm,ss,v,z,r,aa:flight_power(mm,ss,v,z,r,aa))
    pc=power_at(mass,s,p.assumptions.cruise_speed_m_s,h,0,a)[0]/(sigma*a.cruise_power_fraction)
    pcl=power_at(mass,s,climb,h,a.climb_rate_m_s,a)[0]/sigma
    pl=power_at(mass,s,loiter,h,0,a)[0]/(sigma*a.cruise_power_fraction)
    demand={'cruise':pc,'climb_at_cruise_altitude':pcl,'loiter':pl}
    if a.first_level is not None:
        demand['climb_at_sea_level']=power_at(mass,s,climb,0.,a.climb_rate_m_s,a)[0]
        if include_field:
            from .field_performance import takeoff_power
            field_power=takeoff_power(mass,s,p)
            if field_power is not None:demand['takeoff_distance']=field_power
    return {'installed_power_w':max(demand.values())*1.02,'power_constraints_w':demand,
            'controlling_power_constraint':max(demand,key=demand.get),'clean_stall_at_altitude_m_s':vs,
            'landing_stall_m_s':math.sqrt(2*mass*G/(RHO0*s*a.cl_max_landing))}


def mission_legs(mass, geo, p, schedule=None):
    """Shared route semantics; a supplied speed schedule is an explicit model input."""
    a=p.sizing;m=p.mission;h=p.assumptions.cruise_altitude_m;s=geo['wing_area_m2']
    climb_speed,loiter_speed,vs=schedule or speed_schedule(mass,geo,p)
    tc=h/a.climb_rate_m_s;td=h/2.
    xc=math.sqrt(climb_speed**2-a.climb_rate_m_s**2)*tc
    xd=math.sqrt(climb_speed**2-4)*td
    v=p.assumptions.cruise_speed_m_s
    if m.kind=='same_route':
        remain=m.range_m-xc-xd;need=m.endurance_s-tc-td
        if need>0: v=min(v,remain/need)
        if v<1.12*vs:raise DesignDomainError('同航段航程/航时要求需低于当前允许最小平飞速度；不能自动追加留空')
    legs=[]
    if tc: legs.append(('climb',tc,climb_speed,0,h,a.climb_rate_m_s,True))
    if m.kind=='endurance_only':
        level=m.endurance_s-tc-td
        if level<60:raise DesignDomainError('航时短于爬升、下降及最少 60 秒平飞所需时间')
        legs.append(('cruise',level,v,h,h,0,True))
    elif m.kind=='transit_loiter':
        outbound=m.range_m/2-xc;inbound=m.range_m/2-xd
        if min(outbound,inbound)<v*30:raise DesignDomainError('往返距离不足以容纳爬升/下降和转场')
        legs += [('outbound',outbound/v,v,h,h,0,True),('loiter',m.endurance_s,loiter_speed,h,h,0,False),('inbound',inbound/v,v,h,h,0,True)]
    else:
        distance=m.range_m-xc-xd
        if distance<v*60:raise DesignDomainError('航程短于爬升/下降及最少 60 秒巡航所需距离')
        legs.append(('cruise',distance/v,v,h,h,0,True))
    if td:legs.append(('descent',td,climb_speed,h,0,-2.,True))
    return legs,v


def mission(mass, geo, installed_power, p, dt=30., *, flight_model=None, schedule=None, available_power=None,
            fuel_flow_model=None, fuel_description=None):
    from .fuel_model import fuel_flow, fuel_model_description
    if not math.isfinite(dt) or dt<=0: raise ValueError('任务积分步长须为正有限值')
    a=p.sizing;s=geo['wing_area_m2'];legs,v=mission_legs(mass,geo,p,schedule)
    power_at=flight_model or flight_power
    def flow_at(power,segment,height):
        value,method=(fuel_flow_model(power,installed_power,segment,a,height) if fuel_flow_model is not None
                      else fuel_flow(power,installed_power,segment,a))
        if not math.isfinite(value) or value<0 or not isinstance(method,str):raise DesignDomainError('耗油接口须返回非负有限kg/s和方法标识')
        return value,method
    taxi_rate,taxi_method=flow_at(installed_power*.1,'taxi',0.)
    takeoff_rate,takeoff_method=flow_at(installed_power*.9,'takeoff',0.)
    taxi_out=taxi_rate*300;takeoff_roll=takeoff_rate*30
    current=mass-takeoff_roll;rows=[];worst_power=0.;max_cl=0.
    cruise_fuel=cruise_time=0.;cruise_models={};all_models={}
    for name,duration,speed,h0,h1,roc,counts_distance in legs:
        before=current;n=max(1,math.ceil(duration/dt));step=duration/n
        models={};fractions=[]
        for i in range(n):
            z=h0+(h1-h0)*(i+.5)/n
            # Explicit midpoint integration of fuel burn with density at midpoint height.
            def rate(mm):
                pw,cl,_=power_at(mm,s,speed,z,roc,a)
                available=available_power(z) if available_power is not None else installed_power*density(z)/RHO0
                if not math.isfinite(available) or available<=0:raise DesignDomainError('可用功率必须为正有限值')
                idle=.05*available
                if flight_model is not None and pw<idle:
                    raise DesignDomainError('下降所需功率低于当前怠速假设；需要阻力/推进模型支持，不能保持航迹而静默增加推力')
                pw=max(pw,idle)
                flow,method=flow_at(pw,name,z)
                return flow,pw,cl,method
            r0,_,_,_=rate(current);r,pw,cl,method=rate(current-r0*step/2)
            current-=r*step
            models[method]=models.get(method,0.)+r*step;fractions.append(pw/installed_power)
            if current<=0:raise DesignDomainError('任务耗油超过试算质量')
            available=available_power(z) if available_power is not None else installed_power*density(z)/RHO0
            worst_power=max(worst_power,pw/available);max_cl=max(max_cl,cl)
        burned=before-current
        rows.append({'segment':name,'duration_s':duration,'path_distance_m':math.sqrt(speed**2-roc**2)*duration if counts_distance else 0.,
                     'fuel_kg':burned,'speed_m_s':speed,'start_mass_kg':before,'end_mass_kg':current,
                     'fuel_by_method_kg':models,'rated_power_fraction_min':min(fractions),'rated_power_fraction_max':max(fractions)})
        for method,value in models.items():all_models[method]=all_models.get(method,0.)+value
        if name in ('cruise','outbound','inbound'):
            cruise_fuel+=burned;cruise_time+=duration
            for method,value in models.items():cruise_models[method]=cruise_models.get(method,0.)+value
    reserve=cruise_fuel/cruise_time*p.assumptions.reserve_duration_s
    taxi_in=taxi_out
    trip=sum(row['fuel_kg'] for row in rows)+takeoff_roll+taxi_in
    duration=sum(r['duration_s'] for r in rows);distance=sum(r['path_distance_m'] for r in rows)
    for method,value in cruise_models.items():
        all_models[method]=all_models.get(method,0.)+value/cruise_time*p.assumptions.reserve_duration_s
    all_models[taxi_method]=all_models.get(taxi_method,0.)+taxi_out+taxi_in
    all_models[takeoff_method]=all_models.get(takeoff_method,0.)+takeoff_roll
    return {'segments':rows,'cruise_speed_used_m_s':v,'main_duration_s':duration,'route_distance_m':distance,
            'takeoff_roll_fuel_kg':takeoff_roll,'taxi_in_fuel_kg':taxi_in,'taxi_out_fuel_kg':taxi_out,
            'reserve_fuel_kg':reserve,'trip_fuel_from_takeoff_kg':trip,'takeoff_fuel_kg':trip+reserve,
            'block_fuel_kg':trip+reserve+taxi_out,'max_power_fraction':worst_power,'max_clean_cl':max_cl,
            'reserve_basis':'mean cruise fuel flow; not flown and not added to mission time/range',
            'integration_step_s':dt,'fuel_model':fuel_description if fuel_description is not None else fuel_model_description(a),'block_fuel_by_method_kg':all_models,
            'economy_reference_fuel_fraction':all_models.get('economy_reference',0.)/(trip+reserve+taxi_out)}
