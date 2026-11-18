"""V035 read-only units, provenance and recovery through actual widgets."""
from copy import deepcopy
from dataclasses import replace
import json
import pytest
from streamlit.testing.v1 import AppTest
from wingdesignhub.requirements import DesignProject
from wingdesignhub.presentation import constraint_rows,mission_rows,mass_rows,redesign_rows
from wingdesignhub.structure_handoff import build,markdown
from wingdesignhub import jobs


def test_units_and_preparation_never_modify_si_or_claim_loads():
    p=DesignProject().confirmed()
    s={'converged':True,'geometry':{'wing_area_m2':12.},'cg':{'rows':[
        {'component':'data:weight:airframe:wing:mass','mass_kg':100.,'x_m':3.}]},
       'mission':{'segments':[{'segment':'cruise','duration_s':3600.,'path_distance_m':216000.,'speed_m_s':60.,'fuel_kg':20.}]},
       'constraint_states':[{'label':'爬升','status':'exceeded','kind':'design','value':160000.,'limit':150000.,'margin':-10000.,'unit':'W','reason':'超限保留'},
                            {'label':'重心','status':'exceeded','kind':'design','value':[.07,.08],'limit':[.15,.35],'margin':-.08,'unit':'MAC','reason':'研究限值'}],
       'limits':['机身俯仰力矩未计入']}
    r={'run_id':'a'*32,'definition_sha256':p.definition_hash(),'version':'0.3.5','mode':'overall_sizing','status':'constraints_not_met','summary':s}
    original=deepcopy(r)
    rows=constraint_rows(s,p)
    assert rows[0]['计算值']=='160' and rows[0]['余量']=='-10' and rows[0]['单位']=='kW'
    assert rows[1]['计算值']=='7 ～ 8' and rows[1]['单位']=='% MAC'
    assert mission_rows(s)[0]['时长（min）']=='60' and mission_rows(s)[0]['真空速（km/h）']=='216'
    assert mass_rows(s)[0]['部件']=='主翼'
    handoff=build(p,r)
    assert not handoff['ready_for_structural_solution'] and handoff['numerically_converged']
    assert handoff['run_id']==r['run_id'] and '超限' in markdown(handoff)
    assert '机身俯仰力矩未计入' in markdown(handoff) and '待定义' in markdown(handoff)
    assert r==original
    with pytest.raises(ValueError,match='不一致'):build(replace(p,payload_kg=400),r)
    shown=redesign_rows([dict(quantity='功率',unit='W',before=100000,after=120000,relative_change=.2)])
    assert shown[0]['更新后']=='120' and shown[0]['变化（%）']=='20'


@pytest.mark.parametrize('kind',['size','compare'])
def test_recover_without_result_and_retry_preserves_failed_task(tmp_path,monkeypatch,kind):
    monkeypatch.setattr(jobs,'_start',lambda *a:None)
    p=DesignProject().confirmed()
    if kind=='compare':
        from wingdesignhub.design_comparison import variants
        p=variants(p,'sizing.aspect_ratio',[7.,7.5,8.])
        p=replace(p,projects=tuple(x.confirmed() for x in p.projects))
    record=jobs.submit_job(tmp_path,kind,p)
    path=jobs.job_path(tmp_path,record['job_id']);record.update(status='failed',error='注入的工具启动失败；未生成工程运行')
    jobs.atomic(path/'job.json',record)
    before=(path/'request.json').read_bytes()
    a=AppTest.from_string(f'from wingdesignhub.job_ui import panel\npanel({str(tmp_path)!r})').run(timeout=30)
    a.button(key='restore_job_'+record['job_id']).click().run()
    assert not a.exception
    assert a.session_state['workspace_project']==(p.projects[0] if kind=='compare' else p)
    if kind=='compare':assert a.session_state['job_comparison_request']==p
    a.button(key='retry_job_'+record['job_id']).click().run()
    assert not a.exception
    new=a.session_state['selected_job']
    assert new!=record['job_id'] and jobs.get_job(tmp_path,new)['status']=='queued'
    assert (path/'request.json').read_bytes()==before
    assert jobs.get_job(tmp_path,record['job_id'])['status']=='failed'
    jobs.cancel_job(tmp_path,new)


def test_failed_result_handoff_is_not_available():
    p=DesignProject().confirmed()
    data=build(p,dict(run_id='b'*32,definition_sha256=p.definition_hash(),status='polar_missing'))
    assert not data['numerically_converged']
    assert all(r['status']=='待计算' for r in data['items'][1:5])
