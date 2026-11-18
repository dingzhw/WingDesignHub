from dataclasses import replace
import math
import pytest
from wingdesignhub.requirements import DesignProject
from wingdesignhub.first_level_config import default_first_level,validate_first_level
from wingdesignhub.field_performance import disk_thrust,integrate_distance,landing,takeoff,landing_area,takeoff_power
from wingdesignhub.sizing_physics import geometry, constraints, speed_candidates, speed_schedule, G, DesignDomainError
from wingdesignhub.first_level import longitudinal,loading_cases
from wingdesignhub.constraint_states import states,attach,display_rows


def project(**changes):
    p=DesignProject();c=default_first_level();c.update(changes)
    return replace(p,sizing=replace(p.sizing,first_level=c)).confirmed()


def test_old_definition_hash_and_new_confirmation():
    p=DesignProject().confirmed();assert 'first_level' not in p.to_dict()['sizing']
    raw=p.to_dict();raw['sizing']['first_level']=None
    assert DesignProject.from_dict(raw).definition_hash()==p.definition_hash()
    assert project().definition_hash()!=p.definition_hash()
    assert project(moment_bias_abs=.06).definition_hash()!=project().definition_hash()


def test_loading_numbers_normalize_through_archive_identity():
    from wingdesignhub.layout import default_layout
    from wingdesignhub.project_archive import raw_definition
    from copy import deepcopy
    p=project();c=deepcopy(p.sizing.first_level)
    c['loading_cases']=[{'name':'front','payload_fractions':{'front_seats':1,'rear_seats':0,'baggage':0}}]
    p=replace(p,sizing=replace(p.sizing,layout=default_layout(),first_level=c)).confirmed()
    raw=p.to_dict();raw['sizing']['first_level']['loading_cases'][0]['payload_fractions'].update(front_seats=1.,rear_seats=0.,baggage=0.)
    assert DesignProject.from_dict(raw).definition_hash()==p.definition_hash()==raw_definition(raw,'design')


def test_fixed_mtow_field_sizing_does_not_consume_unallocated_budget():
    from wingdesignhub.requirements import WeightRequirement
    p=replace(project(takeoff_limit_m=700),weight=WeightRequirement('fixed',1500.)).confirmed()
    assert takeoff_power(1100,18,p)==takeoff_power(1500,18,p)


@pytest.mark.parametrize('key,value',[('disk_power_factor',float('nan')),('braking_friction',True),('cg_min_mac',.4),('source',''),('loading_cases',[{'name':'bad'}])])
def test_invalid_profile(key,value):
    c=default_first_level();c[key]=value
    with pytest.raises(ValueError):validate_first_level(c)


def test_disk_static_analytic_power_and_momentum():
    rho=1.225;diameter=1.9;area=math.pi*diameter**2/4;power=135000;factor=.65
    t=disk_thrust(power,0,rho,diameter,factor)
    assert t==pytest.approx((2*rho*area)**(1/3)*(power*factor)**(2/3),rel=1e-9)
    for v in (0,10,30,60):
        t=disk_thrust(power,v,rho,diameter,factor)
        vi=(-v+math.sqrt(v*v+2*t/(rho*area)))/2
        assert t*(v+vi)==pytest.approx(power*factor,rel=1e-9)
    assert disk_thrust(power,30,rho)<t*2 # order check, not propeller validation


def test_ground_roll_independent_constant_acceleration():
    assert integrate_distance(3,35,lambda v:2.4)==pytest.approx((35**2-3**2)/(2*2.4),rel=1e-12)
    with pytest.raises(DesignDomainError):integrate_distance(0,30,lambda v:-1)


def test_field_refinement_sizing_and_sensitivity():
    p=project();mass=1156.6605;area=15.7935168
    for fn in (lambda n:landing(mass,area,p,n),lambda n:takeoff(mass,area,134225.976,p,n)):
        a,b=fn(80),fn(160)
        assert abs(a['total_m']/b['total_m']-1)<.01
    assert landing(mass,area,project(braking_friction=.2))['total_m']>landing(mass,area,p)['total_m']
    assert takeoff(mass,area,134225.976,project(disk_power_factor=.55))['total_m']>takeoff(mass,area,134225.976,p)['total_m']
    s=landing_area(mass,project(landing_limit_m=600))
    assert landing(mass,s,project(landing_limit_m=600))['total_m']==pytest.approx(600,rel=1e-6)
    power=takeoff_power(mass,area,project(takeoff_limit_m=700))
    assert takeoff(mass,area,power,project(takeoff_limit_m=700))['total_m']==pytest.approx(700,rel=1e-6)
    assert landing_area(mass,project(landing_limit_m=None)) is None
    with pytest.raises(DesignDomainError):takeoff_power(mass,area,project(takeoff_limit_m=100))


def test_schedule_domain_and_two_height_climb_constraints():
    p=project();g=geometry(1200,100,p);speeds=speed_candidates(1200,g,p);climb,loiter,_=speed_schedule(1200,g,p)
    assert climb in speeds and loiter in speeds and max(speeds)<=90
    r=constraints(1200,g,p)
    assert {'takeoff_distance','climb_at_sea_level','climb_at_cruise_altitude'}<=r['power_constraints_w'].keys()
    with pytest.raises(DesignDomainError):speed_candidates(1200,g,project(schedule_max_speed_m_s=40))


def test_tail_balance_and_bias_are_not_fitted():
    p=project();g=geometry(1200,100,p);cg=g['wing_quarter_x_m']
    nominal=longitudinal(1200,cg,60,2000,g,p)
    assert abs(nominal['moment_residual'])<1e-9 and abs(nominal['lift_residual'])<1e-9
    positive=longitudinal(1200,cg,60,2000,g,p,.05)
    aft=longitudinal(1200,cg+.1*g['mac_m'],60,2000,g,p)
    assert positive['elevator_deg']>nominal['elevator_deg']
    assert aft['static_margin']==pytest.approx(nominal['static_margin']-.1)
    assert g['wing_quarter_x_m']==cg


def test_states_absent_requirement_and_uncomputed_are_not_green():
    p=DesignProject();r={'converged':True,'checks':{'mtow_upper_bound':True,'range':True,'endurance':True,'aero_table_accuracy':True}}
    s={x['id']:x for x in states(r,p)}
    assert s['mtow_upper_bound']['status']==s['endurance']['status']=='not_applicable'
    assert s['range']['status']=='met' and s['aero_table_accuracy']['kind']=='numerical'
    assert s['takeoff_distance']['status']=='not_calculated'
    assert display_rows({'checks':{'x':True}})[0]['状态']=='未计算'


def test_loading_keeps_reserve_and_taxi_in_and_conserves_moment():
    p=project();g=geometry(1200,100,p)
    s={'geometry':g,'cg':{'rows':[{'mass_kg':1000,'x_m':2.8},{'mass_kg':100,'x_m':g['wing_quarter_x_m']}]},
       'mission':{'takeoff_roll_fuel_kg':1.,'segments':[{'fuel_kg':50.}], 'takeoff_fuel_kg':100.}}
    cases=loading_cases(s,p);assert cases[1]['remaining_usable_fuel_kg']==49
    assert cases[1]['mass_kg']==1049
    assert cases[1]['cg_x_m']*1049==pytest.approx(1000*2.8+49*g['wing_quarter_x_m'])


def test_native_sizing_constraint_propagation():
    pytest.importorskip('fastga')
    from wingdesignhub.fastga_mass import FastGAMassModel
    from wingdesignhub.sizing import solve_design
    with FastGAMassModel() as model:
        base=solve_design(project(),model)
        tighter=solve_design(project(landing_limit_m=500),model)
    assert base['converged'] and tighter['converged'],(base.get('diagnostics'),tighter.get('diagnostics'))
    assert tighter['geometry']['wing_area_m2']>base['geometry']['wing_area_m2']
    assert tighter['design_mtow_kg']!=base['design_mtow_kg']
    assert tighter['mission']['block_fuel_kg']!=base['mission']['block_fuel_kg']
    assert base['first_level_complete']
    assert any(r['status']=='exceeded' for r in base['constraint_states'] if r['id']=='loading_cg')
    assert base['status']=='constraints_not_met'
