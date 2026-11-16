"""Bounded native FAST-GA shaft SFC, independently coupled to CCBlade power.

The equivalent volume and torque convention follow FAST-GA 1.4.0 unchanged.
They are scaling coordinates, not a measured engine displacement.
"""
from types import SimpleNamespace
import math
import numpy as np
from .propulsion_model import EngineModel,PropulsionError


class EngineFuelModel(EngineModel):
    def __init__(self,rated_power_w,low_load_policy='base_bsfc'):
        super().__init__(rated_power_w)
        if low_load_policy not in ('base_bsfc','reject'):raise ValueError('未知低负荷耗油策略')
        rpm,pme,limit,sfc=self.native.read_map(self.map_path)
        self.volume=float(self.rated_power_w/np.max(limit*1e5*rpm/240.))
        self.pme=np.asarray(pme);self.sfc_grid=np.asarray(sfc)
        self.torque_nodes=self.pme*1e5*self.volume/(8*math.pi)
        context=SimpleNamespace(rpm_vect_ref=rpm,pme_vect_ref=pme,sfc_matrix_ref=sfc,
                                volume=self.volume,_sfc_interpolator=None)
        self.interpolator=self.native.sfc_interpolator.fget(context)
        self.low_load_policy=low_load_policy;self.capture=False;self.trace=[]
        self.evidence={**self.evidence,'fuel':'native FAST-GA 1.4.0 torque/RPM SFC with explicit domain guards',
            'sfc_units':'g/kWh','pme_bounds_bar':[float(pme[0]),float(pme[-1])],
            'equivalent_volume_m3':self.volume,'volume_role':'upstream scaling coordinate; not measured displacement',
            'mixture_factors':{'climb':1.15,'level_and_descent':1.0},'low_load_policy':low_load_policy,
            'ground_policy':'declared base BSFC; no ground propeller matching',
            'calibration_ids':[],'data_role':'upstream generic map; no target-engine calibration or independent physical validation'}

    def operating_point(self,power_w,rpm,altitude_m,segment,base_bsfc):
        if not math.isfinite(power_w) or power_w<0 or not math.isfinite(base_bsfc) or base_bsfc<=0:
            raise ValueError('轴功率和基础耗油率无效')
        available=self.available(altitude_m,rpm);omega=rpm*math.pi/30
        torque=power_w/omega;pme=torque*8*math.pi/(self.volume*1e5)
        mixture=1.15 if segment=='climb' else 1.
        if segment in ('taxi','takeoff'):
            bsfc=base_bsfc;method='engine_map_ground_base_bsfc'
        elif pme<self.pme[0]-1e-10:
            if self.low_load_policy=='reject':raise PropulsionError('engine_sfc_out_of_domain','低负荷低于原始耗油图范围',pme_bar=pme)
            bsfc=base_bsfc;method='engine_map_low_load_base_bsfc'
        elif pme>self.pme[-1]+1e-10:
            raise PropulsionError('engine_sfc_out_of_domain','高负荷超出原始耗油图，禁止外推',pme_bar=pme)
        else:
            bsfc=float(self.interpolator(torque,rpm).item())/1000*mixture;method='native_engine_sfc_map'
        if not math.isfinite(bsfc) or bsfc<=0:raise PropulsionError('engine_sfc_invalid','原生耗油图输出无效')
        return {'shaft_power_w':float(power_w),'torque_nm':torque,'rpm':float(rpm),'altitude_m':float(altitude_m),
            'segment':segment,'pme_bar':pme,'bsfc_kg_kwh':bsfc,'fuel_flow_kg_s':float(power_w)*bsfc/3.6e6,
            'method':method,'mixture_factor':mixture if method=='native_engine_sfc_map' else None,
            'available_power_w':available,'power_fraction':float(power_w)/available}

    def mission_flow(self,rpm):
        def flow(power,rated,segment,assumptions,height):
            if not math.isclose(rated,self.rated_power_w,rel_tol=1e-12):raise ValueError('耗油图额定功率与当前发动机不一致')
            point=self.operating_point(power,rpm,height,segment,assumptions.bsfc_kg_kwh)
            if self.capture:self.trace.append(point)
            return point['fuel_flow_kg_s'],point['method']
        return flow

    def description(self,rpm,base_bsfc):
        return {**self.evidence,'model':'native_engine_sfc_map','label':'原生发动机耗油图＋显式低负荷/地面估算','rpm':rpm,'base_bsfc_kg_kwh':base_bsfc,
                'limits':['耗油图为上游通用图，转速/扭矩插值不代表具体发动机标定。',
                          '高度只影响可用功率；图内按实际轴扭矩查询，上游没有单独的高度/温度SFC修正。',
                          '爬升按上游富油系数1.15，平飞/下降为1；低负荷及地面基础估算单列覆盖。']}
