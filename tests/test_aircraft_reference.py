import math
import pytest
from wingdesignhub.aircraft_reference import registry,evaluate


def test_registry_roles_and_unresolved_coordinates():
    r=registry()
    assert [p['role'] for p in r['fuel_points']]==['calibration','same_source_holdout','same_source_holdout']
    assert r['registered_before_evaluation'] and not r['new_fit_parameters']
    assert r['propeller']['control']=='fixed_pitch' and r['propeller']['blades']==2
    assert 'datum' in r['loading_source'] and r['missing']
    assert r['mass']['fuel_total_kg']-r['mass']['fuel_usable_kg']==pytest.approx(2*6*.45359237)


def test_native_fixed_reference_retains_errors_and_mass_definitions():
    pytest.importorskip('fastga')
    r=evaluate();assert all(r['checks'].values())
    m=r['mass'];assert not r['physical_validation_passed']
    assert m['condition_status']=='partially_matched'
    assert m['weights']['unusable_fuel_added_once_kg']==pytest.approx(2*6*.45359237)
    installed=m['weights']['components_kg']['data:weight:propulsion:engine:mass']
    assert installed==pytest.approx(m['engine_uninstalled_regression_kg']+m['engine_installation_allowance_kg'])
    assert m['optional_equipment_kg'] and m['unmatched']
    for row in r['fuel_rows']:
        assert row['comparison_status']=='conditions_incomplete' and not row['independent_validation_passed']
        for x in row['generic_map_rpm_sensitivity']:
            assert math.isfinite(x['relative_error'])
            assert x['fuel_us_gal_h']/row['fuel_us_gal_h']-1==pytest.approx(x['relative_error'])
