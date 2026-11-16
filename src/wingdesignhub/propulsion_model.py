"""Bounded propulsion queries. Geometry, loading and airframe drag remain fixed."""
from dataclasses import dataclass, asdict
from pathlib import Path
from types import SimpleNamespace
import math
import numpy as np
from .sizing_physics import DesignDomainError, G, density, constraints
from .adapters import sha256


class PropulsionError(DesignDomainError):
    def __init__(self, status, message, **context):
        super().__init__(message); self.status=status; self.context=context


@dataclass(frozen=True)
class PropulsionOptions:
    rpm: float = 2400.
    blades: int = 3
    root_chord_m: float = .18
    tip_chord_m: float = .08
    reference_pitch_deg: float = 20.
    collective_min_deg: float = -8.
    collective_max_deg: float = 16.
    collective_step_deg: float = 1.
    radial_stations: int = 48
    altitude_stations: int = 3
    integration_step_s: float = 30.

    @classmethod
    def from_dict(cls, data):
        obj=cls(**data); obj.validate(); return obj

    def validate(self):
        bounds={'rpm':(2200,2700),'root_chord_m':(.1,.25),'tip_chord_m':(.04,.15),
                'reference_pitch_deg':(15,30),'collective_min_deg':(-12,0),
                'collective_max_deg':(8,20),'collective_step_deg':(.5,2),
                'integration_step_s':(5,60)}
        for name,(lo,hi) in bounds.items():
            value=getattr(self,name)
            if type(value) not in (int,float) or not math.isfinite(value) or not lo<=value<=hi:
                raise ValueError('推进选项超出范围：'+name)
        if type(self.blades) is not int or self.blades not in (2,3,4):raise ValueError('桨叶数须为2–4')
        if type(self.radial_stations) is not int or self.radial_stations not in (24,48,96):raise ValueError('径向节点须为24/48/96')
        if type(self.altitude_stations) is not int or self.altitude_stations not in (3,5):raise ValueError('高度节点须为3或5')
        if self.tip_chord_m>self.root_chord_m:raise ValueError('本模板桨尖弦长不得大于根部')


LIMITS=[
    '固定已有气动外形、干重、初始携油、重心台账与任务速度；本节点复算需求和余量，不自动换装发动机、增加燃油或重新定尺寸。',
    '独立合成三维桨叶布局，直径继承飞机外形；轴向均匀入流、理想恒速变距、无滑流对机翼反馈及安装损失。',
    'CCBlade原生BEM；NACA4412的XFOIL多Re剖面，Prandtl-Glauert修正。求解试探可用Viterna延拓，接受结果的迎角/Re必须在原极曲线内，局部未诱导Mach≤0.75；不预测激波/失速。',
    '发动机采用FAST-GA 1.4.0通用转速功率图和自然吸气高度关系，非特定型号台架标定；保留原耗油/混合比假设以隔离效率与可用功率变化。',
    '地面滑行和起飞滑跑耗油沿用既有假设，未计算地面桨匹配、起降距离、调速器瞬态或风车工况。公开小桨算例与全尺寸合成桨的物理精度分别记录。',
]


class EngineModel:
    """Reuse pinned FAST-GA map and its native altitude method, without prop maps."""
    def __init__(self, rated_power_w):
        from fastga.models.propulsion.fuel_propulsion.basicIC_engine.basicIC_engine import BasicICEngine
        import inspect
        if not math.isfinite(rated_power_w) or not 40000<=rated_power_w<=400000:raise ValueError('发动机额定功率须为40–400 kW')
        self.rated_power_w=float(rated_power_w);self.native=BasicICEngine
        source=Path(inspect.getfile(BasicICEngine));self.map_path=source.parent/'resources/FourCylindersAtmospheric.csv'
        rpm,_,pme,_=BasicICEngine.read_map(self.map_path)
        self.rpm=np.asarray(rpm);curve=np.asarray(pme)*self.rpm
        self.power_fraction=curve/np.max(curve)
        self.evidence={'provider':'FAST-GA 1.4.0 BasicICEngine native map and compute_max_power',
                       'source_sha256':sha256(source),'map_sha256':sha256(self.map_path),
                       'rpm':self.rpm.tolist(),'sea_level_power_fraction':self.power_fraction.tolist(),
                       'fuel':'existing explicitly selected BSFC model; no new fuel calibration',
                       'physical_validation_passed':False}

    def available(self, altitude_m, rpm):
        if not math.isfinite(altitude_m) or not 0<=altitude_m<=4000:raise PropulsionError('engine_out_of_domain','发动机高度限0–4000 m')
        if not math.isfinite(rpm) or not self.rpm[0]<=rpm<=self.rpm[-1]:raise PropulsionError('engine_out_of_domain','发动机转速超出原生图谱',rpm=rpm)
        # compute_max_power accepts a flight point with an altitude attribute.
        power_kw=self.native.compute_max_power(SimpleNamespace(max_power=self.rated_power_w),SimpleNamespace(altitude=altitude_m))
        return float(power_kw)*1000*float(np.interp(rpm,self.rpm,self.power_fraction))


class PropellerMap:
    def __init__(self, data):
        self.data=data; self.rpm=data['rpm']; self.diameter=data['diameter_m']
        self.collectives=np.asarray(data['collectives_deg'],dtype=float)
        self.heights=np.asarray(data['altitudes_m'],dtype=float)
        self.speeds=np.asarray(data['speeds_m_s'],dtype=float)
        self.points=data['points']
        if not math.isfinite(self.rpm) or not 2200<=self.rpm<=2700 or not math.isfinite(self.diameter) or not .5<=self.diameter<=3:
            raise ValueError('螺旋桨转速或直径无效')
        if (not data.get('no_extrapolation') or len(self.collectives)<2 or len(self.heights)<1 or
            any(not np.isfinite(x).all() or (len(x)>1 and np.any(np.diff(x)<=0)) for x in (self.collectives,self.heights,self.speeds))):
            raise ValueError('螺旋桨图谱节点无效')
        expected=len(self.speeds)*len(self.heights)*len(self.collectives)
        if len(self.points)!=expected:raise ValueError('螺旋桨图谱不完整')
        self.grid={}
        for p in self.points:
            key=(p['speed_m_s'],p['altitude_m'],p['collective_deg'])
            if p['rpm']!=self.rpm:raise ValueError('螺旋桨图谱转速不一致')
            if key in self.grid:raise ValueError('螺旋桨图谱点重复')
            if key[0] not in self.speeds or key[1] not in self.heights or key[2] not in self.collectives:raise ValueError('螺旋桨图谱点不属于规定网格')
            if p['status']=='valid':
                t,q,pw=p['thrust_n'],p['torque_nm'],p['shaft_power_w']
                if not all(math.isfinite(v) for v in (t,q,pw)) or min(t,q,pw)<=0 or not math.isclose(pw,q*self.rpm*math.pi/30,rel_tol=1e-10):raise ValueError('螺旋桨功率/扭矩关系无效')
                eta=t*key[0]/pw
                if not 0<=eta<=1 or not math.isclose(eta,p['efficiency'],rel_tol=1e-10):raise ValueError('螺旋桨效率关系无效')
            self.grid[key]=p

    def query(self, thrust_n, speed_m_s, altitude_m):
        if not math.isfinite(thrust_n) or thrust_n<=0:raise PropulsionError('propeller_requires_braking','当前螺旋桨模型仅接受正推力')
        match=np.flatnonzero(np.isclose(self.speeds,speed_m_s,rtol=0,atol=1e-8))
        if len(match)!=1 or not self.heights[0]-1e-8<=altitude_m<=self.heights[-1]+1e-8:
            raise PropulsionError('propeller_map_out_of_domain','速度或高度没有螺旋桨图谱；禁止外推',speed_m_s=speed_m_s,altitude_m=altitude_m)
        speed=float(self.speeds[match[0]]);j=int(np.searchsorted(self.heights,altitude_m))
        exact=np.flatnonzero(np.isclose(self.heights,altitude_m,rtol=0,atol=1e-8))
        a=b=int(exact[0]) if len(exact) else -1
        if not len(exact):a=max(0,j-1);b=min(j,len(self.heights)-1)
        f=0. if a==b else float((altitude_m-self.heights[a])/(self.heights[b]-self.heights[a]))
        curves=[]
        for beta in self.collectives:
            lo=self.grid[(speed,float(self.heights[a]),float(beta))];hi=self.grid[(speed,float(self.heights[b]),float(beta))]
            curves.append(None if lo['status']!='valid' or hi['status']!='valid' else
                          {k:(1-f)*lo[k]+f*hi[k] for k in ('thrust_n','torque_nm','shaft_power_w')})
        candidates=[]
        for i,(lo,hi) in enumerate(zip(curves,curves[1:])):
            if lo is None or hi is None:continue
            if hi['thrust_n']<=lo['thrust_n']:continue
            if lo['thrust_n']-1e-8<=thrust_n<=hi['thrust_n']+1e-8:
                t=(thrust_n-lo['thrust_n'])/(hi['thrust_n']-lo['thrust_n'])
                q=float((1-t)*lo['torque_nm']+t*hi['torque_nm']);pw=q*self.rpm*math.pi/30
                candidates.append({'thrust_n':thrust_n,'torque_nm':q,'shaft_power_w':pw,
                    'efficiency':thrust_n*speed_m_s/pw,'collective_deg':float(self.collectives[i]+t*(self.collectives[i+1]-self.collectives[i])),
                    'rpm':self.rpm,'advance_ratio':speed_m_s/(self.rpm/60*self.diameter)})
        if not candidates:raise PropulsionError('propeller_thrust_unavailable','有效桨图内没有可匹配推力；未跨缺点或失速区插值',thrust_n=thrust_n,speed_m_s=speed_m_s,altitude_m=altitude_m)
        first=candidates[0]
        if any(abs(x['collective_deg']-first['collective_deg'])>1e-6 for x in candidates[1:]):raise PropulsionError('propeller_ambiguous_branch','存在多个有效变距分支，需明确调速策略')
        return first


class PropulsiveFlight:
    def __init__(self, aero, propeller, engine):
        self.aero=aero; self.propeller=propeller; self.engine=engine; self.trace=[];self.capture=False

    def __call__(self,mass,area,speed,altitude,roc,assumptions):
        if not math.isclose(area,self.aero.area,rel_tol=1e-12):raise PropulsionError('propulsion_reference_mismatch','气动参考面积不一致')
        aero=self.aero.query(mass,speed,altitude,roc)
        gamma=math.asin(roc/speed);q=.5*density(altitude)*speed**2
        drag=q*area*aero['cd'];thrust=drag+mass*G*math.sin(gamma)
        point=self.propeller.query(thrust,speed,altitude)
        cl=mass*G*math.cos(gamma)/(q*area)
        if self.capture:self.trace.append({'mass_kg':mass,'remaining_fuel_kg':mass-self.aero.dry_mass,
            'cg_x_m':self.aero.cg(mass),'speed_m_s':speed,'altitude_m':altitude,'roc_m_s':roc,
            'drag_n':drag,'cl':cl,'available_power_w':self.engine.available(altitude,self.propeller.rpm),**point})
        return point['shaft_power_w'],cl,drag


def propulsion_constraints(mass,geo,p,flight,schedule):
    # Existing constraint definitions, with the engine's actual RPM/height capacity.
    base=constraints(mass,geo,p,flight_model=flight,schedule=schedule)
    h=p.assumptions.cruise_altitude_m
    from .sizing_physics import RHO0
    correction=(density(h)/RHO0)/(flight.engine.available(h,flight.propeller.rpm)/flight.engine.rated_power_w)
    demands={k:v*correction for k,v in base['power_constraints_w'].items()}
    return {**base,'power_constraints_w':demands,'controlling_power_constraint':max(demands,key=demands.get),
            'installed_power_w':max(demands.values())*1.02,
            'basis':'required sea-level rated engine power at selected RPM; fixed installed engine retained for mission'}
