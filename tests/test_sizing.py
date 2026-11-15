from dataclasses import replace
import math
import json
import pytest
from wingdesignhub.requirements import DesignProject, MissionRequirement, WeightRequirement, build_design_intent
from wingdesignhub.sizing_config import SizingAssumptions
from wingdesignhub.sizing_physics import geometry, constraints, flight_power, mission, density, G
from wingdesignhub.sizing import solve_design


def test_schema_migration_invalidates_confirmation_and_keeps_requirements():
    data=DesignProject().confirmed().to_dict();data.pop('sizing');data['schema_version']=1
    p=DesignProject.from_dict(data)
    assert p.schema_version==2 and p.payload_kg==350 and p.confirmation_sha256 is None
    assert build_design_intent(p)['status']=='needs_confirmation'
    assert build_design_intent(p.confirmed())['status']=='requirements_ready'
    assert build_design_intent(replace(p.confirmed(),sizing=replace(p.sizing,cd0=.04)))['status']=='needs_confirmation'


@pytest.mark.parametrize('field,value',[('seats',True),('bsfc_kg_kwh',float('nan')),('cd0',.001),('source','')])
def test_invalid_sizing_assumptions(field,value):
    with pytest.raises(ValueError):replace(SizingAssumptions(),**{field:value}).validate()


def test_planform_lift_power_and_fuel_volume_independent_balances():
    p=DesignProject();m=1200.;g=geometry(m,100,p);s=g['wing_area_m2'];b=g['wing_span_m']
    assert (g['root_chord_m']+g['tip_chord_m'])*b/2==pytest.approx(s)
    assert b*b/s==pytest.approx(p.sizing.aspect_ratio)
    power,cl,drag=flight_power(m,s,60,2000,3,p.sizing)
    assert .5*density(2000)*60**2*s*cl==pytest.approx(m*G*math.sqrt(1-(3/60)**2))
    assert power*.8==pytest.approx(drag*60+m*G*3)
    assert g['usable_tank_capacity_kg']==pytest.approx(.98*g['tank_capacity_kg'])


def test_level_mission_fuel_against_closed_form_ode_and_reserve_count():
    # dm/dt = -(A+B*m^2); analytic arctangent solution is independent of the integrator.
    p=replace(DesignProject(),mission=MissionRequirement('endurance_only',None,14400.),
              assumptions=replace(DesignProject().assumptions,cruise_altitude_m=0)).confirmed()
    g=geometry(1200,100,p);pw=constraints(1200,g,p)['installed_power_w'];a=p.sizing
    r=mission(1200,g,pw,p,30);q=.5*1.225*60**2;s=g['wing_area_m2'];c=a.bsfc_kg_kwh/3.6e6
    aa=c*q*s*a.cd0*60/a.propeller_efficiency
    bb=c*G**2/(q*s*math.pi*a.oswald_efficiency*a.aspect_ratio)*60/a.propeller_efficiency
    initial=1200-r['takeoff_roll_fuel_kg']
    final=math.sqrt(aa/bb)*math.tan(math.atan(initial*math.sqrt(bb/aa))-math.sqrt(aa*bb)*14400)
    assert r['segments'][0]['end_mass_kg']==pytest.approx(final,abs=2e-5)
    assert r['reserve_fuel_kg']==pytest.approx((initial-final)/14400*2700,abs=1e-5)
    assert r['block_fuel_kg']==pytest.approx(sum(x['fuel_kg'] for x in r['segments'])+r['reserve_fuel_kg']+r['taxi_in_fuel_kg']+r['taxi_out_fuel_kg']+r['takeoff_roll_fuel_kg'])
    assert r['main_duration_s']==14400 and r['route_distance_m']==864000


@pytest.fixture(scope='module')
def model():
    pytest.importorskip('fastga')
    from wingdesignhub.fastga_mass import FastGAMassModel
    with FastGAMassModel() as m:yield m


def test_native_mass_units_component_formula_and_map_independence(model):
    p=DesignProject();g=geometry(1200,100,p);r=model.evaluate(1200,135000,g,p)
    # Independently evaluate published imperial correlations after SI conversion.
    wing_lb=96.948*((1200/.45359237*5.7/1e5)**.65*7.5**.57*(g['wing_area_m2']/.3048**2/100)**.61*(1.6/.24)**.36*(1+(60*1.2/ .5144444444444445)/500)**.5)**.993
    assert r['components_kg']['data:weight:airframe:wing:mass']==pytest.approx(wing_lb*.45359237,rel=1e-9)
    installed_engine=(135000/745.7-21.55)/.5515*1.4*.45359237
    assert r['components_kg']['data:weight:propulsion:engine:mass']==pytest.approx(installed_engine,rel=1e-8)
    assert r['owe_kg']==pytest.approx(sum(r['categories_kg'].values()))
    assert r['unusable_fuel_added_once_kg']==pytest.approx(.02*g['tank_capacity_kg'])
    assert model.problem.get_val('data:weight:aircraft:payload',units='kg').item()==350
    # Map perturbation must not affect the engine-only mass relation or declared unused fuel.
    key='data:aerodynamics:propeller:sea_level:efficiency'
    old=model.problem.get_val(key).copy();model.problem.set_val(key,old*.97)
    other=model.evaluate(1200,135000,g,p);model.problem.set_val(key,old)
    assert other['owe_kg']==pytest.approx(r['owe_kg'],abs=1e-10)


@pytest.mark.parametrize('mode,value',[('fixed',1400.),('upper_bound',1500.),('solve',None)])
@pytest.mark.parametrize('kind,distance,duration',[
    ('range_only',8e5,None),('endurance_only',None,14400.),
    ('same_route',8e5,14400.),('transit_loiter',4e5,3600.)])
def test_native_mode_task_matrix(model,mode,value,kind,distance,duration):
    p=replace(DesignProject(),weight=WeightRequirement(mode,value),mission=MissionRequirement(kind,distance,duration)).confirmed()
    r=solve_design(p,model)
    assert r['status']=='concept_checked_with_limits',r
    assert all(r['checks'].values()) and r['iterations'][-1]['stable_rounds']>=3
    assert r['cg']['loaded_mass_kg']==pytest.approx(r['weights']['owe_kg']+p.payload_kg+r['mission']['takeoff_fuel_kg'])
    assert r['required_loaded_mass_kg']==pytest.approx(r['cg']['loaded_mass_kg'])
    if mode=='fixed':
        assert r['design_mtow_kg']==value and r['mass_budget_margin_kg']>0
    else:
        assert abs(r['mass_budget_margin_kg']/r['design_mtow_kg'])<1e-4
    if kind=='transit_loiter':
        loiter=next(x for x in r['mission']['segments'] if x['segment']=='loiter')
        assert loiter['duration_s']==3600 and loiter['path_distance_m']==0
    assert r['physical_validation_passed'] is False and r['trim_checked'] is False


def test_infeasible_weight_does_not_clip_or_fabricate_balance(model):
    for mode in ('fixed','upper_bound'):
        r=solve_design(replace(DesignProject(),weight=WeightRequirement(mode,1000.)).confirmed(),model)
        assert r['status']=='constraints_not_met'
        if mode=='fixed':assert r['design_mtow_kg']==1000 and r['mass_budget_margin_kg']<0
        else:assert r['design_mtow_kg']>1000 and r['upper_bound_margin_kg']<0


def test_conflicts_nonconvergence_and_domain_states(model):
    p=DesignProject().confirmed()
    assert solve_design(DesignProject(),model)['status']=='needs_confirmation'
    for task in (MissionRequirement('same_route',8e5,36000),MissionRequirement('endurance_only',None,600)):
        r=solve_design(replace(p,mission=task).confirmed(),model)
        assert r['status']=='out_of_domain' and r['diagnostics']
    r=solve_design(p,model,max_iterations=1)
    assert r['status']=='not_converged' and r['design_mtow_kg']==r['iterations'][-1]['design_mtow_kg']
    assert solve_design(replace(p,payload_kg=700).confirmed(),model)['status']=='out_of_domain'


def test_payload_range_and_timestep_propagate(model):
    p=DesignProject().confirmed();r=solve_design(p,model)
    for q in (replace(p,payload_kg=400).confirmed(),replace(p,mission=MissionRequirement('range_only',1e6)).confirmed()):
        changed=solve_design(q,model)
        assert changed['status']=='concept_checked_with_limits'
        assert changed['design_mtow_kg']>r['design_mtow_kg']
        assert changed['geometry']['wing_area_m2']>r['geometry']['wing_area_m2']
        assert changed['power']['installed_power_w']>r['power']['installed_power_w']
        assert changed['mission']['block_fuel_kg']>r['mission']['block_fuel_kg']
    fine=solve_design(p,model,dt=15)
    assert abs(fine['design_mtow_kg']/r['design_mtow_kg']-1)<.001
    assert abs(fine['mission']['block_fuel_kg']/r['mission']['block_fuel_kg']-1)<.001


def test_service_pending_and_failure_are_recorded(tmp_path,monkeypatch):
    from wingdesignhub import sizing_service
    from wingdesignhub.service import get_results
    r=sizing_service.run_sizing(DesignProject(),tmp_path)
    assert r['status']=='needs_confirmation' and get_results(tmp_path,r['run_id'])==r
    def fail(*args,**kwargs):raise TimeoutError('synthetic timeout')
    monkeypatch.setattr(sizing_service,'execute',fail)
    r=sizing_service.run_sizing(DesignProject().confirmed(),tmp_path)
    assert r['status']=='failed' and 'timeout' in r['error']
    assert get_results(tmp_path,r['run_id'])==r


def test_cli_size_uses_shared_service_and_propagates_status(tmp_path,monkeypatch,capsys):
    from wingdesignhub import cli
    p=DesignProject().confirmed();path=tmp_path/'p.json';path.write_text(json.dumps(p.to_dict()),encoding='utf-8')
    def run(project,root):
        assert project==p and root==tmp_path
        return {'status':'constraints_not_met'}
    monkeypatch.setattr(cli,'run_sizing',run)
    monkeypatch.setattr('sys.argv',['wingdesignhub','size','--input',str(path),'--root',str(tmp_path)])
    assert cli.main()==1 and json.loads(capsys.readouterr().out)['status']=='constraints_not_met'
