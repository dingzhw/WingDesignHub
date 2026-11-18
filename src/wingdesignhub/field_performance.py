"""First-level field performance: Newton integration, explicit ideal disk losses.

Sources: NASA Glenn propth (momentum); ERAU Takeoff and Landing Performance.
No aircraft-specific fit; flap, friction and transient assumptions are inputs.
"""
import math
from .sizing_physics import G, RHO0, density, DesignDomainError
from .configuration import PROPELLER_DIAMETER_M

METHOD='newton_ground_roll_ideal_disk_v1'


def field_density(c):
    h=c['field_altitude_m'];t=288.15-.0065*h
    return density(h)*t/(t+c['temperature_delta_k'])


def disk_thrust(power_w, speed, rho, diameter=PROPELLER_DIAMETER_M, factor=.65):
    if min(power_w,rho,diameter,factor)<=0 or speed<0 or factor>1 or not all(math.isfinite(x) for x in (power_w,speed,rho,diameter,factor)):
        raise ValueError('作用盘输入无效')
    area=math.pi*diameter**2/4;pe=power_w*factor
    lo=0.;hi=(pe/(2*rho*area))**(1/3)
    for _ in range(50):
        vi=(lo+hi)/2
        if 2*rho*area*vi*(speed+vi)**2>pe:hi=vi
        else:lo=vi
    vi=(lo+hi)/2
    return 2*rho*area*vi*(speed+vi)


def integrate_distance(v0,v1,acceleration,n=80):
    """Integral v/|a| dv; caller supplies positive acceleration/deceleration."""
    if type(n) is not int or n<2 or not 0<=v0<v1:raise ValueError('滑跑积分网格无效')
    step=(v1-v0)/n;out=0.
    for i in range(n):
        v=v0+(i+.5)*step;a=acceleration(v)
        if not math.isfinite(a) or a<=0:raise DesignDomainError('起降段加速度非正，当前功率/阻力条件无法完成')
        out+=v/a*step
    return out


def landing(mass,area,p,n=80):
    c=p.sizing.first_level;a=p.sizing;rho=field_density(c);w=mass*G
    vs=math.sqrt(2*w/(rho*area*a.cl_max_landing));va=1.3*vs;vt=1.15*vs
    gamma=math.radians(c['approach_deg']);radius=va**2/(G*(c['flare_load_factor']-1))
    hf=radius*(1-math.cos(gamma))
    if hf>=c['obstacle_m']:raise DesignDomainError('拉平高度超过规定障碍高度；当前分段着陆模型不适用')
    approach=(c['obstacle_m']-hf)/math.tan(gamma);flare=radius*math.sin(gamma)
    # After touchdown: explicit lift dump assumption CL=.3; brake friction acts on W-L.
    cl=.3;cd=a.cd0+c['landing_cd_increment']+cl**2/(math.pi*a.oswald_efficiency*a.aspect_ratio)
    def decel(v):
        q=.5*rho*v*v
        return (q*area*cd+c['braking_friction']*max(0,w-q*area*cl))/mass
    roll=integrate_distance(0,vt,decel,n);delay=vt*c['landing_delay_s']
    return dict(total_m=approach+flare+delay+roll,ground_roll_m=delay+roll,braking_m=roll,
        approach_m=approach,flare_m=flare,delay_m=delay,stall_m_s=vs,approach_m_s=va,
        touchdown_m_s=vt,rho_kg_m3=rho,method=METHOD,
        assumptions='touchdown at 1.15Vs; flare entry 1.3Vs; lift dump CL=.3; zero residual thrust')


def takeoff(mass,area,rated_power,p,n=80,*,diameter_m=PROPELLER_DIAMETER_M):
    c=p.sizing.first_level;a=p.sizing;rho=field_density(c);w=mass*G
    # Explicit engineering density lapse; separate from the native engine cruise map.
    power=rated_power*min(rho/RHO0,1.);vs=math.sqrt(2*w/(rho*area*c['takeoff_cl_max']))
    vlof=1.15*vs;v2=1.2*vs;clg=.6*c['takeoff_cl_max']
    cdg=a.cd0+c['takeoff_cd_increment']+clg**2/(math.pi*a.oswald_efficiency*a.aspect_ratio)
    def thrust(v):return disk_thrust(power,v,rho,diameter_m,c['disk_power_factor'])
    def accel(v):
        q=.5*rho*v*v
        return (thrust(v)-q*area*cdg-c['rolling_friction']*max(0,w-q*area*clg))/mass
    roll=integrate_distance(0,vlof,accel,n);rotation=vlof*c['rotation_time_s']
    def excess(v):
        q=.5*rho*v*v;cl=w/(q*area)
        cd=a.cd0+c['takeoff_cd_increment']+cl**2/(math.pi*a.oswald_efficiency*a.aspect_ratio)
        return thrust(v)-q*area*cd
    # Conservative sequential level acceleration then steady climb, no overlap credit.
    transition=integrate_distance(vlof,v2,lambda v:excess(v)/mass,n)
    sg=excess(v2)/w
    if not 0<sg<.3:raise DesignDomainError('障碍爬升梯度不在一级模型(0,0.3)内')
    obstacle=c['obstacle_m']/math.tan(math.asin(sg))
    return dict(total_m=roll+rotation+transition+obstacle,ground_roll_m=roll+rotation,
        acceleration_m=roll,rotation_m=rotation,transition_m=transition,obstacle_m=obstacle,
        stall_m_s=vs,liftoff_m_s=vlof,safety_m_s=v2,climb_gradient=sg,rho_kg_m3=rho,
        field_available_power_w=power,method=METHOD,
        assumptions='density-lapse shaft power; disk loss factor; no ground effect; sequential acceleration/climb')


def landing_area(mass,p):
    limit=p.sizing.first_level['landing_limit_m']
    if limit is None:return None
    lo=5.;hi=80.
    def value(s):
        try:return landing(mass,s,p)['total_m']
        except DesignDomainError:return float('inf')
    if value(hi)>limit:raise DesignDomainError('着陆距离要求在一级模型翼面积5–80m²内不可达')
    for _ in range(32):
        mid=(lo+hi)/2
        if value(mid)>limit:lo=mid
        else:hi=mid
    return hi


def takeoff_power(mass,area,p):
    # A prescribed MTOW is the full design weight, not ballast at the current CG.
    # Native mission queries still use actual loading; field sizing must retain
    # the prescribed weight even when there is unallocated payload/mass budget.
    if p.weight.mode=='fixed':mass=p.weight.value_kg
    limit=p.sizing.first_level['takeoff_limit_m']
    if limit is None:return None
    lo=40000.;hi=400000.
    def value(pw):
        try:return takeoff(mass,area,pw,p)['total_m']
        except DesignDomainError:return float('inf')
    # Search bounded samples first: very large power can leave the small-gradient domain.
    brackets=[lo+i*(hi-lo)/36 for i in range(37)]
    ok=next((i for i,v in enumerate(brackets) if value(v)<=limit),None)
    if ok is None:raise DesignDomainError('起飞距离要求在40–400kW及一级爬升梯度域内不可达')
    if ok==0:return lo
    lo,hi=brackets[ok-1:ok+1]
    for _ in range(28):
        mid=(lo+hi)/2
        if value(mid)>limit:lo=mid
        else:hi=mid
    return hi
