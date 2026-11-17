"""Native failures remain visible, portable and non-destructive in the user flow."""
from pathlib import Path
from dataclasses import replace
import pytest
from test_feedback_service import baseline
from wingdesignhub.coupled_service import run_coupled
from wingdesignhub.service import write_json,get_results,generate_report
from wingdesignhub.project_archive import build_bundle,read_bundle


def failure(baseline,monkeypatch):
    root,p,b=baseline
    def fail(argv,work,**kw):
        write_json(work/'failure.json',{'status':'engine_sfc_out_of_domain','error':'injected SFC boundary','diagnostic_context':{'pme':21}})
        raise RuntimeError('injected failure')
    monkeypatch.setattr('wingdesignhub.coupled_service.execute',fail)
    return run_coupled(p,root,b['run_id'])


def test_coupled_failure_report_archive_and_unchanged_seed(baseline,monkeypatch):
    root,p,b=baseline;r=failure(baseline,monkeypatch)
    assert r['status']=='engine_sfc_out_of_domain' and 'summary' not in r
    assert get_results(root,b['run_id'])==b and get_results(root,r['run_id'])==r
    assert 'injected SFC boundary' in generate_report(r,root=root)
    opened=read_bundle(build_bundle(p,root,b,coupled_record=r))
    assert opened['coupled_records']==[r] and opened['current_source_matches']
    selected=read_bundle(build_bundle(p,root,b,coupled_record=r,current_run_id=r['run_id']))
    assert selected['manifest']['current_run_id']==r['run_id']
    assert selected['files']['reports/report.html']==(root/'runs'/r['run_id']/'report.html').read_bytes()
    with pytest.raises(ValueError,match='来源总体'):build_bundle(p,root,coupled_record=r)
    for pp in (replace(p,payload_kg=p.payload_kg+1).confirmed(),replace(p,confirmation_sha256=None)):
        with pytest.raises(ValueError,match='需求'):run_coupled(pp,root,b['run_id'])


def test_coupled_failure_ui_save_reopen_and_reset(baseline,monkeypatch):
    from streamlit.testing.v1 import AppTest
    from wingdesignhub import sizing_service,geometry_ui,feedback_ui,project_ui,project_archive,coupled_ui
    root,p,b=baseline;r=failure(baseline,monkeypatch)
    monkeypatch.setattr(sizing_service,'run_sizing',lambda *a:b)
    monkeypatch.setattr(geometry_ui,'render',lambda *a:None);monkeypatch.setattr(feedback_ui,'render',lambda *a:None)
    monkeypatch.setattr(coupled_ui,'run_coupled',lambda *a:r)
    render=coupled_ui.render;monkeypatch.setattr(coupled_ui,'render',lambda p,ignored,b,*args,**kw:render(p,root,b,*args,**kw))
    save=project_ui.save_controls;monkeypatch.setattr(project_ui,'save_controls',lambda p,ignored,b=None,key='design':save(p,root,b,key))
    listing=project_archive.list_saved;loading=project_archive.load_saved
    monkeypatch.setattr(project_archive,'list_saved',lambda ignored:listing(root))
    monkeypatch.setattr(project_archive,'load_saved',lambda ignored,sid:loading(root,sid))
    app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py'),default_timeout=30).run()
    app.checkbox[0].check().run();app.button(key='run_sizing').click().run()
    app.button(key='coupled_run').click().run()
    assert not app.exception and any('injected SFC boundary' in x.value for x in app.error)
    app.number_input(key='coupled_rpm').set_value(2300.).run()
    assert any('闭环选项已修改' in x.value for x in app.warning)
    app.button(key='design_save_local').click().run();sid=listing(root)[0]['archive_id']
    app.selectbox(key='saved_archive_choice').set_value(sid).run();app.button(key='open_saved_design').click().run()
    assert not app.exception and loading(root,sid)['coupled_records']==[r]
    app.button(key='new_blank_design').click().run();assert 'coupled_result' not in app.session_state
