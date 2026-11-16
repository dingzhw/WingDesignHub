"""Map node identity and independent dimensional/mixture/scaling checks."""
import math
from dataclasses import replace
import numpy as np
import pytest
from wingdesignhub.engine_fuel import EngineFuelModel
from wingdesignhub.propulsion_model import PropulsionError
from wingdesignhub.requirements import DesignProject,MissionRequirement
from wingdesignhub.sizing_physics import mission,geometry


def test_native_sfc_nodes_units_mixture_and_power_scaling():
    pytest.importorskip('fastga');engine=EngineFuelModel(160000.)
    for j,rpm in enumerate(engine.rpm):
        for i,torque in enumerate(engine.torque_nodes):
            power=torque*rpm*math.pi/30
            r=engine.operating_point(power,float(rpm),1000,'cruise',.3)
            expected=engine.sfc_grid[j,i]/1000
            assert r['bsfc_kg_kwh']==pytest.approx(expected,rel=1e-12)
            assert r['fuel_flow_kg_s']*3600==pytest.approx(power/1000*expected,rel=1e-12)
    torque=float(engine.torque_nodes[15]);power=torque*2400*math.pi/30
    cruise=engine.operating_point(power,2400,2000,'cruise',.3)
    climb=engine.operating_point(power,2400,2000,'climb',.3)
    assert climb['fuel_flow_kg_s']==pytest.approx(cruise['fuel_flow_kg_s']*1.15)
    scaled=EngineFuelModel(240000.).operating_point(power*1.5,2400,2000,'cruise',.3)
    assert scaled['bsfc_kg_kwh']==pytest.approx(cruise['bsfc_kg_kwh'])
    assert scaled['torque_nm']==pytest.approx(cruise['torque_nm']*1.5)
    assert scaled['power_fraction']==pytest.approx(cruise['power_fraction'])


def test_sfc_boundaries_and_explicit_ground_low_load_accounting():
    pytest.importorskip('fastga');e=EngineFuelModel(160000.)
    low=e.torque_nodes[0]*2400*math.pi/30*.9;high=e.torque_nodes[-1]*2400*math.pi/30*1.01
    assert e.operating_point(low,2400,0,'descent',.3)['method']=='engine_map_low_load_base_bsfc'
    assert e.operating_point(144000,2400,0,'takeoff',.3)['method']=='engine_map_ground_base_bsfc'
    with pytest.raises(PropulsionError,match='高负荷'):e.operating_point(high,2400,0,'climb',.3)
    with pytest.raises(PropulsionError,match='低负荷'):EngineFuelModel(160000.,'reject').operating_point(low,2400,0,'descent',.3)
    with pytest.raises(PropulsionError,match='转速'):e.operating_point(80000,2000,0,'cruise',.3)
    with pytest.raises(ValueError,match='额定功率'):e.mission_flow(2400)(80000,150000,'cruise',DesignProject().sizing,0)


def test_fuel_hook_independent_constant_flow_solution_and_reserve():
    p=DesignProject();p=replace(p,mission=MissionRequirement('endurance_only',None,7200.),
                             assumptions=replace(p.assumptions,cruise_altitude_m=0.)).confirmed()
    def flow(power,rated,segment,assumptions,height):
        return (.001 if segment=='taxi' else .002 if segment=='takeoff' else .003),segment
    r=mission(1200.,geometry(1200,100,p),150000,p,flight_model=lambda *a:(50000.,.3,700.),fuel_flow_model=flow)
    assert r['segments'][0]['fuel_kg']==pytest.approx(.003*7200)
    assert r['reserve_fuel_kg']==pytest.approx(.003*p.assumptions.reserve_duration_s)
    assert r['block_fuel_by_method_kg']['taxi']==pytest.approx(.6)
    assert r['block_fuel_by_method_kg']['takeoff']==pytest.approx(.06)
    assert sum(r['block_fuel_by_method_kg'].values())==pytest.approx(r['block_fuel_kg'],abs=1e-9)
    with pytest.raises(ValueError,match='耗油接口'):
        mission(1200.,geometry(1200,100,p),150000,p,fuel_flow_model=lambda *a:(float('nan'),'broken'))
