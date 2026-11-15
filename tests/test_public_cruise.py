import math
import pytest
from wingdesignhub.reference_cruise import evaluate_public_cruise,run_public_cruise
from wingdesignhub.sizing_config import SizingAssumptions
from wingdesignhub.sizing_physics import density,flight_power,DesignDomainError
from wingdesignhub.service import get_results


def test_same_condition_conversion_and_published_example_boundaries():
    r=evaluate_public_cruise();c=r['conditions_si'];ref=r['reference']
    assert c['gross_mass_kg']==pytest.approx(2550*.45359237) # cruise chart, not 2400-lb flight loading
    assert c['temperature_k']==pytest.approx(285.9277777778)
    assert c['pressure_altitude_m']==pytest.approx(1828.8)
    assert c['shaft_power_w']==pytest.approx(180*.65*745.6998715822702)
    assert c['area_m2']==pytest.approx(170*.09290304)
    assert c['density_kg_m3']<density(1828.8) and ref['configuration'].startswith('wheel fairings installed')
    assert r['coefficients_fitted'] is False and r['physical_validation_passed'] is False
    assert abs(r['numerical_power_residual_w'])<1e-7
    assert r['assumptions']['bsfc_kg_kwh']==SizingAssumptions().bsfc_kg_kwh


def test_fuel_discrepancy_is_visible_not_a_tuned_pass(tmp_path):
    r=run_public_cruise(tmp_path);s=r['summary']
    assert r['status']=='model_discrepancy' and s['checks']['fuel'] is False
    # Independent units: lb per US gallon from handbook; don't confuse Imperial gallons.
    assert s['predicted']['fuel_us_gal_h']==pytest.approx(87.24688497512563*.3/(6*.45359237))
    assert s['relative_errors']['fuel']>.20 and get_results(tmp_path,r['run_id'])==r


def test_explicit_density_matches_isa_path_and_rejects_invalid_inputs():
    a=SizingAssumptions()
    assert flight_power(1200,15,60,2000,0,a)==flight_power(1200,15,60,2000,0,a,air_density_kg_m3=density(2000))
    for invalid in (0,-1,float('nan')):
        with pytest.raises(DesignDomainError):flight_power(1200,15,60,2000,0,a,air_density_kg_m3=invalid)
