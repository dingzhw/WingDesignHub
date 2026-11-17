"""Exercise the asynchronous UI contract separately from result-rendering doubles."""
from pathlib import Path
import time
import pytest
from streamlit.testing.v1 import AppTest
from wingdesignhub import jobs,job_ui
from wingdesignhub.requirements import DesignProject


def test_submission_returns_without_running_solver(monkeypatch):
    seen=[]
    monkeypatch.setattr(jobs,'list_jobs',lambda root:[])
    def submit(root,kind,project,*args):
        seen.append((kind,project.confirmation_sha256==project.definition_hash()))
        return {'job_id':'1'*32}
    monkeypatch.setattr(jobs,'submit_job',submit)
    a=AppTest.from_file(str(Path(__file__).parents[1]/'app.py')).run(timeout=30)
    a.checkbox[0].check().run();a.button(key='run_sizing').click().run()
    assert not a.exception and seen==[('size',True)]
    assert any('已提交' in x.value for x in a.success)
    assert 'sizing_result' not in a.session_state
    a.sidebar.radio[0].set_value('工具设置').run()
    assert not a.exception and any('Julia' in x.label for x in a.text_input)


def test_reconnect_and_cancel_queued_task(tmp_path,monkeypatch):
    monkeypatch.setattr(jobs,'_start',lambda *args:None)
    r=jobs.submit_job(tmp_path,'size',DesignProject().confirmed())
    code=f"from wingdesignhub.job_ui import panel\npanel({str(tmp_path)!r})"
    a=AppTest.from_string(code).run(timeout=30)
    assert not a.exception and a.selectbox(key='selected_job').value==r['job_id']
    # A new browser session reads the persisted queue, with no prior session state.
    b=AppTest.from_string(code).run(timeout=30)
    b.button(key='cancel_job_'+r['job_id']).click().run()
    assert not b.exception and jobs.get_job(tmp_path,r['job_id'])['status']=='cancelled'
    assert jobs.read(jobs.job_path(tmp_path,r['job_id'])/'request.json')['project']['name']==DesignProject().name


def test_form_bounds_and_crossfield_error_keep_draft(monkeypatch):
    monkeypatch.setattr(jobs,'list_jobs',lambda root:[])
    a=AppTest.from_file(str(Path(__file__).parents[1]/'app.py')).run(timeout=30)
    cd=next(x for x in a.number_input if 'CD0' in x.label)
    assert cd.min==.02 and cd.max==.05
    next(x for x in a.number_input if x.label=='净构型最大升力系数').set_value(1.7).run()
    next(x for x in a.number_input if x.label=='着陆构型最大升力系数').set_value(1.4).run()
    assert not a.exception and a.error
    assert any(x.proto.label=='保存待修正草案' for x in a.get('download_button'))
    next(x for x in a.number_input if x.label=='着陆构型最大升力系数').set_value(1.8).run()
    assert not a.exception and a.button(key='run_sizing').disabled


def test_current_result_survives_parent_change(monkeypatch):
    from copy import deepcopy
    import json
    root=Path(__file__).parents[1]
    # Frozen public/synthetic native results are local release evidence, optional in CI.
    old=root/'runs'/'87e7d646dc1e493b9317c39dc6d48533'/'result.json'
    if not old.exists():pytest.skip('local native representative result')
    native=json.loads(old.read_text('utf-8'))
    p=DesignProject.from_dict(json.loads((old.parent/'input.json').read_text('utf-8')))
    seed=deepcopy(native);seed.update(mode='overall_sizing',run_id='initial-test')
    feedback=deepcopy(native);feedback.update(mode='overall_feedback',run_id='feedback-test',parent_run_id=seed['run_id'])
    monkeypatch.setattr('wingdesignhub.coupled_ui.render',lambda *a:None)
    monkeypatch.setattr('wingdesignhub.feedback_ui.render',lambda *a:None)
    monkeypatch.setattr('wingdesignhub.geometry_ui.render',lambda *a:None)
    monkeypatch.setattr('wingdesignhub.geometry_ui.show_final_geometry',lambda r,*a:__import__('streamlit').caption('selected-geometry:'+r['run_id']))
    code="from wingdesignhub.sizing_ui import results\nimport streamlit as st\nresults(st.session_state['seed'],st.session_state['project'],st.session_state['root'])"
    a=AppTest.from_string(code)
    for k,v in {'seed':seed,'project':p,'root':str(root),'coupled_result':native}.items():a.session_state[k]=v
    a.run(timeout=30);key='current_design_run_'+p.definition_hash()
    a.selectbox(key=key).set_value(native['run_id']).run()
    a.session_state['aero_feedback_result']=feedback;a.run()
    assert not a.exception and a.selectbox(key=key).value==native['run_id']
    assert any('selected-geometry:'+native['run_id'] in c.value for c in a.caption)
