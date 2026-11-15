"""Visible assumptions for the bounded single-engine conceptual design model."""
from dataclasses import dataclass, asdict, fields
import math


@dataclass(frozen=True)
class SizingAssumptions:
    template: str = 'metal_single_v1'
    stall_speed_m_s: float = 28.
    climb_rate_m_s: float = 3.
    aspect_ratio: float = 7.5
    cd0: float = .032
    oswald_efficiency: float = .8
    cl_max_clean: float = 1.4
    cl_max_landing: float = 1.8
    propeller_efficiency: float = .8
    bsfc_kg_kwh: float = .30
    cruise_power_fraction: float = .75
    seats: int = 4
    fuselage_length_m: float = 7.5
    tank_volume_fraction: float = .12
    unusable_fuel_fraction: float = .02
    source: str = 'WingDesignHub V0.1.7 独立金属单发概念模板；系数为待校准工程假设，非真实型号数据'

    def to_dict(self): return asdict(self)

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict) or set(data)-{f.name for f in fields(cls)}:
            raise ValueError('定尺寸假设字段无效')
        result=cls(**data);result.validate();return result

    def validate(self):
        limits={'stall_speed_m_s':(22,35),'climb_rate_m_s':(1,5),'aspect_ratio':(6,10),
                'cd0':(.02,.05),'oswald_efficiency':(.65,.9),'cl_max_clean':(1.1,1.7),
                'cl_max_landing':(1.4,2.2),'propeller_efficiency':(.65,.85),'bsfc_kg_kwh':(.23,.4),
                'cruise_power_fraction':(.6,.85),'fuselage_length_m':(6,9),'tank_volume_fraction':(.06,.18),'unusable_fuel_fraction':(.01,.05)}
        if self.template!='metal_single_v1' or type(self.seats) is not int or not 2<=self.seats<=6:
            raise ValueError('模板须为常规金属单发，座位数限 2–6')
        for k,(lo,hi) in limits.items():
            x=getattr(self,k)
            if isinstance(x,bool) or not isinstance(x,(float,int)) or not math.isfinite(x) or not lo<=x<=hi:
                raise ValueError(f'{k} 超出当前概念模型范围 [{lo}, {hi}]')
        if self.cl_max_landing<self.cl_max_clean or not isinstance(self.source,str) or not self.source.strip():
            raise ValueError('增升系数或假设来源无效')
