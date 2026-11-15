from dataclasses import replace
import json
import math
from pathlib import Path
import pytest
from wingdesignhub.fuel_model import CALIBRATION,HOLDOUT,HP_W,LB_KG,calibrated_bsfc,fuel_flow
from wingdesignhub.fuel_validation import evaluate_fuel_model,run_fuel_validation
from wingdesignhub.sizing_config import SizingAssumptions
from wingdesignhub.requirements import DesignProject
from wingdesignhub.sizing_physics import mission,geometry,constraints
from wingdesignhub.service import get_results


def test_calibration_units_roles_and_heldout_predictions():
    result=evaluate_fuel_model()
    assert calibrated_bsfc()==pytest.approx(7.6*6*.45359237/(117*.7456998715822702))
    assert set(result['calibration_ids']).isdisjoint(result['holdout_ids'])
    assert result['rows'][0]['holdout_pass'] is None
    assert all(r['holdout_pass'] for r in result['rows'][1:])
    # Independent ratio calculation; no lookup or fitting of held-out values.
    for r in result['rows'][1:]:assert r['predicted_gal_h']==pytest.approx(7.6*r['power_fraction']/.65)
    assert not result['independent_validation_data_available']
    assert result['external_same_condition_validation_passed'] is None
    assert result['external_reference']['fuel_us_gal_h']==9.5
    assert result['rows'][0]['original_gal_h']/7.6-1==pytest.approx(.2654372125131581)


@pytest.mark.parametrize('fraction,segment,expected',[(.55,'cruise','economy_reference'),(.75,'cruise','economy_reference'),
    (.549,'cruise','off_reference_base_bsfc'),(.751,'cruise','off_reference_base_bsfc'),
    (.65,'climb','off_reference_base_bsfc'),(.65,'loiter','economy_reference'),(.1,'taxi','off_reference_base_bsfc')])
def test_reference_range_and_segment_are_explicit(fraction,segment,expected):
    a=replace(SizingAssumptions(),fuel_model='piper_economy_reference')
    rate,method=fuel_flow(180*HP_W*fraction,180*HP_W,segment,a)
    assert method==expected
    assert rate==pytest.approx(180*HP_W*fraction*(calibrated_bsfc() if expected=='economy_reference' else .3)/3.6e6)


def test_segment_and_reserve_ledgers_do_not_count_fuel_twice():
    p=DesignProject();p=replace(p,sizing=replace(p.sizing,fuel_model='piper_economy_reference')).confirmed()
    g=geometry(1200,100,p);power=constraints(1200,g,p)['installed_power_w'];r=mission(1200,g,power,p)
    assert sum(r['block_fuel_by_method_kg'].values())==pytest.approx(r['block_fuel_kg'],abs=1e-9)
    assert 0<r['economy_reference_fuel_fraction']<1
    for row in r['segments']:
        assert sum(row['fuel_by_method_kg'].values())==pytest.approx(row['fuel_kg'],abs=1e-9)
    baseline=mission(1200,g,power,replace(p,sizing=replace(p.sizing,fuel_model='constant_bsfc')))
    assert r['taxi_out_fuel_kg']==baseline['taxi_out_fuel_kg'] and r['takeoff_roll_fuel_kg']==baseline['takeoff_roll_fuel_kg']
    assert r['block_fuel_kg']<baseline['block_fuel_kg']


def test_legacy_schema_preserves_bsfc_and_invalidates_confirmation():
    old=json.loads((Path(__file__).resolve().parents[1]/'examples/three_designs.json').read_text('utf-8'))['projects'][0]
    assert old['schema_version']==2
    new=DesignProject.from_dict(old)
    assert new.schema_version==3 and new.sizing.bsfc_kg_kwh==old['sizing']['bsfc_kg_kwh']
    assert new.sizing.fuel_model=='constant_bsfc' and new.confirmation_sha256 is None
    bad=dict(old);bad['sizing']={**old['sizing'],'fuel_model':'piper_economy_reference'}
    with pytest.raises(ValueError):DesignProject.from_dict(bad)


def test_fuel_evidence_service_and_invalid_power(tmp_path):
    r=run_fuel_validation(tmp_path);assert get_results(tmp_path,r['run_id'])==r
    assert r['summary']['holdout_passed'] and not r['physical_validation_passed']
    for power,rated in [(-1,100),(10,0),(math.nan,100)]:
        with pytest.raises(ValueError):fuel_flow(power,rated,'cruise',SizingAssumptions())
