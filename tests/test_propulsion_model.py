"""Independent interpolation, balances, engine identity and mission checks."""
from copy import deepcopy
from dataclasses import replace
import math
import json
from types import SimpleNamespace
import numpy as np
import pytest
from wingdesignhub.propulsion_model import PropulsionOptions,PropellerMap,PropulsionError,EngineModel,PropulsiveFlight
from wingdesignhub.sizing_physics import mission,geometry,density,G
from wingdesignhub.requirements import DesignProject


def analytic_map():
    rows=[];rpm=2400.;omega=rpm*math.pi/30
    for h in (0.,2000.):
        for beta in (0.,1.,2.,3.):
            thrust=(100+300*beta)*(1-h/10000);q=(50+70*beta)*(1-h/10000);pw=q*omega
            rows.append({'status':'valid','speed_m_s':60.,'altitude_m':h,'collective_deg':beta,'rpm':rpm,
                         'thrust_n':thrust,'torque_nm':q,'shaft_power_w':pw,'efficiency':thrust*60/pw})
    return {'no_extrapolation':True,'rpm':rpm,'diameter_m':1.9,'collectives_deg':[0.,1.,2.,3.],
            'altitudes_m':[0.,2000.],'speeds_m_s':[60.],'points':rows}


def test_bilinear_inverse_and_power_from_torque():
    prop=PropellerMap(analytic_map());beta=1.3;h=700.;t=(100+300*beta)*(1-h/10000)
    r=prop.query(t,60.,h)
    assert r['collective_deg']==pytest.approx(beta,abs=1e-12)
    assert r['torque_nm']==pytest.approx((50+70*beta)*(1-h/10000))
    assert r['shaft_power_w']==pytest.approx(r['torque_nm']*80*math.pi)
    assert r['efficiency']==pytest.approx(t*60/r['shaft_power_w'])
    json.dumps({**r,'passed':r['shaft_power_w']>0},allow_nan=False)


@pytest.mark.parametrize('values',[(100,59,0),(100,60,-1),(100,60,2001),(10000,60,0),(0,60,0)])
def test_no_propeller_extrapolation(values):
    with pytest.raises(PropulsionError):PropellerMap(analytic_map()).query(*values)


def test_missing_point_is_not_bridged_and_exact_height_remains_usable():
    data=analytic_map();data['points'][1]['status']='out_of_domain';p=PropellerMap(data)
    with pytest.raises(PropulsionError):p.query(400.,60.,500.)
    assert p.query(400*.8,60,2000)['collective_deg']==pytest.approx(1.)


def test_reopened_map_rejects_corrupt_power_and_duplicate_grid():
    for modify in (lambda d:d['points'][0].update(shaft_power_w=10),lambda d:d['points'].__setitem__(1,deepcopy(d['points'][0])),
                   lambda d:d['points'][0].update(rpm=2300)):
        d=analytic_map();modify(d)
        with pytest.raises(ValueError):PropellerMap(d)


@pytest.mark.parametrize('change',[{'rpm':float('nan')},{'rpm':3000},{'blades':2.5},{'radial_stations':1},{'root_chord_m':.1,'tip_chord_m':.12}])
def test_propulsion_options_domain(change):
    with pytest.raises(ValueError):replace(PropulsionOptions(),**change).validate()


def test_engine_native_lapse_and_rpm_power_scaling():
    pytest.importorskip('fastga')
    from stdatm import Atmosphere
    engine=EngineModel(160000.)
    sigma=Atmosphere(2000,altitude_in_feet=False).density/Atmosphere(0,altitude_in_feet=False).density
    assert engine.available(2000,2700)==pytest.approx(160000*(sigma-(1-sigma)/7.55),rel=1e-12)
    peak=max(engine.evidence['sea_level_power_fraction'])
    assert peak==1
    assert engine.available(0,2425)==pytest.approx((engine.available(0,2400)+engine.available(0,2450))/2)
    with pytest.raises(PropulsionError):engine.available(0,2100)
    with pytest.raises(PropulsionError):engine.available(4001,2400)


def test_tip_mach_checked_before_launching_native_solver(tmp_path):
    from wingdesignhub.ccblade_adapter import build_map
    aero=SimpleNamespace(tables={'x':{'speed_m_s':60.,'altitudes_m':[0.,2000.]}})
    with pytest.raises(PropulsionError) as error:
        build_map(tmp_path,tmp_path/'high-rpm',aero,1.9,replace(PropulsionOptions(),rpm=2700))
    assert error.value.status=='propeller_tip_mach_exceeded'
    assert not (tmp_path/'high-rpm/airfoil').exists()


def test_flight_matches_thrust_with_mass_gravity_and_single_drag():
    class Aero:
        area=20.;dry_mass=500.
        def query(self,*args):return {'cd':.02}
        def cg(self,m):return 2.5
    f=PropulsiveFlight(Aero(),PropellerMap(analytic_map()),SimpleNamespace(available=lambda h,rpm:100000.));f.capture=True
    power,cl,drag=f(900.,20.,60.,1000.,.5,None);r=f.trace[0]
    q=.5*density(1000)*60**2
    assert drag==pytest.approx(q*20*.02)
    assert r['thrust_n']==pytest.approx(drag+900*G*.5/60)
    assert cl*q*20==pytest.approx(900*G*math.cos(math.asin(.5/60)))
    assert power*r['efficiency']==pytest.approx(r['thrust_n']*60)


@pytest.mark.parametrize('scale',[.8,1.])
def test_available_power_hook_preserves_fuel_and_reserve_semantics(scale):
    p=DesignProject().confirmed();p=replace(p,assumptions=replace(p.assumptions,cruise_altitude_m=0.))
    mass=1200.;geo=geometry(mass,120,p)
    def flight(*args):return 50000.,.4,700.
    result=mission(mass,geo,150000,p,flight_model=flight,available_power=lambda h:150000*scale)
    expected=50000*p.sizing.bsfc_kg_kwh/3.6e6
    assert result['reserve_fuel_kg']==pytest.approx(expected*p.assumptions.reserve_duration_s,rel=1e-10)
    assert result['max_power_fraction']==pytest.approx(50000/(150000*scale))
    assert result['takeoff_fuel_kg']==pytest.approx(result['trip_fuel_from_takeoff_kg']+result['reserve_fuel_kg'])
    assert result['block_fuel_kg']==pytest.approx(result['takeoff_fuel_kg']+result['taxi_out_fuel_kg'])
