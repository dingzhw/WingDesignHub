"""Service failure, archive and UI provenance tests (injected solver failure)."""
from dataclasses import replace
from pathlib import Path
import json
import pytest
from wingdesignhub.requirements import DesignProject
from wingdesignhub.service import write_json,get_results,generate_report
from wingdesignhub.feedback_service import run_aero_feedback
from wingdesignhub.project_archive import build_bundle,read_bundle


@pytest.fixture(scope='module')
def baseline(tmp_path_factory):
    pytest.importorskip('fastga')
    from wingdesignhub.sizing_service import run_sizing
    root=tmp_path_factory.mktemp('feedback-service');p=DesignProject().confirmed();r=run_sizing(p,root)
    assert r['status']=='concept_checked_with_limits'
    return root,p,r


def failure_record(baseline,monkeypatch):
    root,p,b=baseline
    def fail(argv,work,**kwargs):
        write_json(work/'failure.json',{'status':'polar_missing','error':'injected missing polar','diagnostic_context':{'station':2}})
        raise RuntimeError('injected native process failure')
    monkeypatch.setattr('wingdesignhub.feedback_service.execute',fail)
    return run_aero_feedback(p,root,b['run_id'])


def test_failed_feedback_is_preserved_with_parent_report_archive(baseline,monkeypatch):
    root,p,b=baseline;r=failure_record(baseline,monkeypatch)
    assert r['status']=='polar_missing' and r['diagnostic_context']=={'station':2} and 'summary' not in r
    assert get_results(root,r['run_id'])==r
    assert 'injected missing polar' in generate_report(r,root=root)
    loaded=read_bundle(build_bundle(p,root,b,feedback_record=r))
    assert loaded['feedback_records']==[r] and loaded['current_source_matches']
    assert get_results(root,b['run_id'])==b
    with pytest.raises(ValueError,match='来源总体'):build_bundle(p,root,feedback_record=r)


def test_feedback_rejects_changed_or_unconfirmed_design(baseline):
    root,p,b=baseline
    for altered in (replace(p,payload_kg=p.payload_kg+1).confirmed(),replace(p,confirmation_sha256=None)):
        with pytest.raises(ValueError,match='需求'):run_aero_feedback(altered,root,b['run_id'])


def test_failed_feedback_ui_save_reopen_and_changed_assumption(baseline,monkeypatch):
    from streamlit.testing.v1 import AppTest
    from wingdesignhub import sizing_service,geometry_ui,feedback_ui,project_ui,project_archive
    root,p,b=baseline;r=failure_record(baseline,monkeypatch)
    monkeypatch.setattr(sizing_service,'run_sizing',lambda *a:b)
    monkeypatch.setattr(geometry_ui,'render',lambda *a:None)
    monkeypatch.setattr(feedback_ui,'run_aero_feedback',lambda *a:r)
    render=feedback_ui.render;monkeypatch.setattr(feedback_ui,'render',lambda p,ignored,b:render(p,root,b))
    save=project_ui.save_controls;monkeypatch.setattr(project_ui,'save_controls',lambda p,ignored,b=None,key='design':save(p,root,b,key))
    listing=project_archive.list_saved;loading=project_archive.load_saved
    monkeypatch.setattr(project_archive,'list_saved',lambda ignored:listing(root))
    monkeypatch.setattr(project_archive,'load_saved',lambda ignored,sid:loading(root,sid))
    app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py'),default_timeout=30).run()
    app.checkbox[0].check().run();app.button(key='run_sizing').click().run()
    app.button(key='run_aero_feedback').click().run()
    assert not app.exception and any('injected missing polar' in x.value for x in app.error)
    app.number_input(key='feedback_strut').set_value(1.3).run()
    assert any('假设已修改' in x.value for x in app.warning)
    app.button(key='design_save_local').click().run();sid=listing(root)[0]['archive_id']
    app.selectbox(key='saved_archive_choice').set_value(sid).run();app.button(key='open_saved_design').click().run()
    assert not app.exception and loading(root,sid)['feedback_records']==[r]
    app.button(key='new_blank_design').click().run();assert 'aero_feedback_result' not in app.session_state
