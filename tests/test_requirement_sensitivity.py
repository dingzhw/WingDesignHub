from dataclasses import replace
import pytest
from wingdesignhub.requirements import DesignProject,MissionRequirement,WeightRequirement
from wingdesignhub.comparison_ui import variants
from wingdesignhub.sizing import solve_design


@pytest.fixture(scope='module')
def model():
    pytest.importorskip('fastga')
    from wingdesignhub.fastga_mass import FastGAMassModel
    with FastGAMassModel() as m:yield m


@pytest.mark.parametrize('axis,values,mission',[
    ('payload_kg',[350.,400.,450.],MissionRequirement()),
    ('mission.range_m',[8e5,1e6,1.2e6],MissionRequirement()),
    ('mission.endurance_s',[10800.,14400.,18000.],MissionRequirement('endurance_only',None,10800.)),
    ('mission.endurance_s',[1800.,3600.,7200.],MissionRequirement('transit_loiter',4e5,1800.))])
def test_requirement_increase_flows_through_actual_native_chain(model,axis,values,mission):
    base=replace(DesignProject(),mission=mission)
    results=[solve_design(p.confirmed(),model) for p in variants(base,axis,values).projects]
    assert all(r['status']=='concept_checked_with_limits' for r in results)
    for left,right in zip(results,results[1:]):
        assert right['design_mtow_kg']>left['design_mtow_kg']
        assert right['weights']['owe_kg']>left['weights']['owe_kg']
        assert right['mission']['block_fuel_kg']>left['mission']['block_fuel_kg']
        assert right['power']['installed_power_w']>left['power']['installed_power_w']
        assert right['geometry']['wing_area_m2']>left['geometry']['wing_area_m2']
        assert right['geometry']['wing_span_m']>left['geometry']['wing_span_m']


def test_fixed_weight_does_not_fake_weight_increase_when_payload_grows(model):
    base=replace(DesignProject(),weight=WeightRequirement('fixed',1400.))
    rows=[solve_design(replace(base,payload_kg=p).confirmed(),model) for p in (350,450,600)]
    assert [r['design_mtow_kg'] for r in rows]==[1400.]*3
    assert rows[-1]['status']=='constraints_not_met' and not rows[-1]['checks']['mass_budget']
    assert rows[-1]['mass_budget_margin_kg']<rows[0]['mass_budget_margin_kg']
    # The flight is evaluated at the same prescribed gross mass: fuel need is unchanged.
    assert rows[0]['mission']['block_fuel_kg']==pytest.approx(rows[-1]['mission']['block_fuel_kg'])


def test_repeatability_and_same_route_duration_is_not_extra_loiter(model):
    base=replace(DesignProject(),mission=MissionRequirement('same_route',8e5,14400.)).confirmed()
    first=solve_design(base,model);repeat=solve_design(base,model)
    assert first==repeat
    longer=solve_design(replace(base,mission=MissionRequirement('same_route',8e5,16200.)).confirmed(),model)
    assert longer['status']=='concept_checked_with_limits'
    assert longer['mission']['route_distance_m']==pytest.approx(first['mission']['route_distance_m'])
    assert longer['mission']['cruise_speed_used_m_s']<first['mission']['cruise_speed_used_m_s']
    assert not any(s['segment']=='loiter' for s in longer['mission']['segments'])
