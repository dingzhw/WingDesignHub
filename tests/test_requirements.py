from dataclasses import replace
import json
import pytest
from wingdesignhub.requirements import (DesignProject, DesignAssumptions, WeightRequirement,
                                       MissionRequirement, build_design_intent, validate_design_project)
from wingdesignhub.design_service import prepare_design_project
from wingdesignhub.service import get_results
from wingdesignhub.fastga_interface import reference_binding_preview, get_fastga_contract


@pytest.mark.parametrize('mode,value,solve,fixed,upper', [
    ('fixed', 1200., False, 1200., None), ('upper_bound', 1200., True, None, 1200.), ('solve', None, True, None, None)])
def test_weight_modes_never_overwrite_prescribed_input(mode, value, solve, fixed, upper):
    p = replace(DesignProject(), weight=WeightRequirement(mode, value)).confirmed()
    r = build_design_intent(p)
    assert r['status'] == 'requirements_ready' and r['weight']['solve_mtow'] == solve
    assert r['weight']['prescribed_mtow_kg'] == fixed and r['weight']['mtow_upper_bound_kg'] == upper
    assert p.weight.value_kg == value and r['aircraft_feasibility'] == 'not_evaluated'
    assert reference_binding_preview(p)['executable_as_custom_design'] is False


@pytest.mark.parametrize('weight,payload,code', [
    (WeightRequirement('fixed'), 350., 'missing_weight'),
    (WeightRequirement('solve', 1200.), 350., 'solved_weight_has_value'),
    (WeightRequirement('upper_bound', 350.), 350., 'payload_exceeds_weight')])
def test_weight_conflicts_reported(weight, payload, code):
    p = replace(DesignProject(), weight=weight, payload_kg=payload)
    r = build_design_intent(p)
    assert r['status'] == 'invalid_input' and code in {d['code'] for d in r['diagnostics']}


@pytest.mark.parametrize('kind,range_m,time_s,roles', [
    ('range_only', 800000., None, ['route', 'reserve']),
    ('endurance_only', None, 18000., ['route', 'reserve']),
    ('same_route', 800000., 18000., ['route', 'reserve']),
    ('transit_loiter', 800000., 18000., ['route', 'loiter', 'reserve'])])
def test_mission_distance_time_and_reserve_are_not_double_counted(kind, range_m, time_s, roles):
    p = replace(DesignProject(), mission=MissionRequirement(kind, range_m, time_s)).confirmed()
    r = build_design_intent(p); s = r['mission_segments']
    assert [x['role'] for x in s] == roles
    assert sum(x['distance_m'] or 0 for x in s) == (range_m or 0)
    assert sum(x['duration_s'] or 0 for x in s if x['role'] != 'reserve') == (time_s or 0)
    assert s[-1]['duration_s'] == 2700. and s[-1]['distance_m'] is None
    assert r['sizing_available'] is True


@pytest.mark.parametrize('mission', [MissionRequirement('same_route', 8e5, None),
    MissionRequirement('range_only', 8e5, 7200), MissionRequirement('endurance_only', 8e5, 7200),
    MissionRequirement('transit_loiter', None, 7200)])
def test_mission_conflicting_or_ignored_fields_rejected(mission):
    assert build_design_intent(replace(DesignProject(), mission=mission))['status'] == 'invalid_input'


@pytest.mark.parametrize('changes', [{'payload_kg': True}, {'payload_kg': float('nan')}, {'payload_kg': -1},
    {'schema_version': True}, {'name': ''}, {'weight': {'mode': 'fixed', 'value_kg': float('inf')}},
    {'mission': {'kind': 'unknown'}}, {'assumptions': {'sources': {}}}, {'unexpected': 1},
    {'confirmation_sha256': 'wrong'}])
def test_invalid_schema_is_not_coerced(changes):
    data = {**DesignProject().to_dict(), **changes}
    with pytest.raises((ValueError, TypeError)): DesignProject.from_dict(data)
    assert validate_design_project(data)[0]['code'] == 'invalid_schema'


def test_confirmation_survives_serialization_but_changes_invalidate_it():
    p = DesignProject().confirmed()
    q = DesignProject.from_dict(json.loads(json.dumps(p.to_dict())))
    assert build_design_intent(q)['status'] == 'requirements_ready'
    assert replace(p, payload_kg=350).definition_hash() == p.definition_hash()
    for q in (replace(p, payload_kg=400.), replace(p, weight=WeightRequirement('fixed', 1200.)),
              replace(p, assumptions=replace(p.assumptions, reserve_duration_s=1800.)),
              replace(p, mission=MissionRequirement('same_route', 8e5, 7200.))):
        assert build_design_intent(q)['status'] == 'needs_confirmation'
    assert build_design_intent(p.confirmed()) == build_design_intent(p)


def test_zero_reserve_visible_and_service_records_invalid_or_pending_cases(tmp_path):
    p = replace(DesignProject(), assumptions=replace(DesignAssumptions(), reserve_duration_s=0)).confirmed()
    r = prepare_design_project(p, tmp_path)
    assert r['status'] == 'requirements_ready'
    assert any(d['code'] == 'no_reserve' for d in r['summary']['diagnostics'])
    assert get_results(tmp_path, r['run_id']) == r
    for q, status in ((DesignProject(), 'needs_confirmation'),
                      (replace(p, weight=WeightRequirement('fixed', 10)), 'invalid_input')):
        assert prepare_design_project(q, tmp_path)['status'] == status
    (tmp_path/'runs'/r['run_id']/'input.json').write_text('{}')
    with pytest.raises(ValueError, match='完整性'): get_results(tmp_path, r['run_id'])


def test_reference_contract_does_not_allow_custom_aircraft():
    c = get_fastga_contract()
    assert not c['accepts_custom_design']
    assert c['variables']['mtow']['role'] == 'output'
    assert c['variables']['payload']['role'] == 'output'
    assert c['variables']['power_per_engine']['role'] == 'input'


@pytest.mark.parametrize('reference_args', [['fastga-reference'], ['reference', '--benchmark', 'fastga']])
def test_cli_shares_confirmation_and_rejects_reference_overrides(tmp_path, monkeypatch, capsys, reference_args):
    from wingdesignhub.cli import main
    p = tmp_path/'requirements.json'
    p.write_text(json.dumps(DesignProject().confirmed().to_dict()), encoding='utf-8')
    monkeypatch.setattr('sys.argv', ['wingdesignhub', 'prepare', '--root', str(tmp_path), '--input', str(p)])
    assert main() == 0
    result = json.loads(capsys.readouterr().out)
    assert result['status'] == 'requirements_ready' and result['mode'] == 'design_intent'
    monkeypatch.setattr('sys.argv', ['wingdesignhub', *reference_args, '--input', str(p)])
    with pytest.raises(SystemExit) as exc: main()
    assert exc.value.code == 2
