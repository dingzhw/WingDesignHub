from dataclasses import replace
from copy import deepcopy
from pathlib import Path
import json
import pytest
from wingdesignhub.requirements import DesignProject,WeightRequirement,MissionRequirement
from wingdesignhub.comparison_ui import variants
from wingdesignhub.design_comparison import ComparisonRequest,summarize_comparison
from wingdesignhub.comparison_service import run_comparison,compare_sizing_runs
from wingdesignhub.service import get_results


def confirmed_request(base=None,axis='sizing.aspect_ratio',values=(7.5,8.25,9.)):
    request=variants(base or DesignProject(),axis,values)
    return replace(request,projects=tuple(p.confirmed() for p in request.projects))


@pytest.fixture(scope='module')
def actual(tmp_path_factory):
    pytest.importorskip('fastga')
    root=tmp_path_factory.mktemp('comparison');request=confirmed_request()
    result=run_comparison(request,root)
    assert result['status']=='compared_with_limits',result.get('error')
    return root,request,result


def test_request_roundtrip_and_condition_gate():
    request=confirmed_request()
    assert ComparisonRequest.from_dict(json.loads(json.dumps(request.to_dict())))==request
    changed=replace(request,projects=(request.projects[0],replace(request.projects[1],payload_kg=400),request.projects[2]))
    with pytest.raises(ValueError,match='条件'):changed.validate()
    with pytest.raises(ValueError,match='名称'):
        replace(request,projects=tuple(replace(p,name='same') for p in request.projects)).validate()
    with pytest.raises(ValueError,match='一个变化参数'):variants(DesignProject(),'payload_kg',[350,350,350])
    q=variants(DesignProject(),'payload_kg',[350,400,450])
    assert q.purpose=='requirements_sensitivity'
    assert q.definition_hash()!=request.definition_hash()
    with pytest.raises(ValueError):ComparisonRequest.from_dict({'projects':[],'schema_version':True})


def test_three_actual_designs_cards_deltas_and_reload(actual):
    root,req,r=actual;s=r['summary']
    assert get_results(root,r['run_id'])==r
    assert len(set(r['child_runs']))==3 and s['eligible_schemes']==[0,1,2] and s['ranking'] is None
    assert {x['field'] for x in s['differences']}=={'sizing.aspect_ratio'}
    for i,c in enumerate(s['cards']):
        child=get_results(root,c['run_id'])['summary']
        assert c['metrics']['mtow_kg']==child['design_mtow_kg']
        assert c['metrics']['power_kw']==child['power']['installed_power_w']/1000
        assert s['deltas'][i]['values']['mtow_kg']['absolute']==pytest.approx(c['metrics']['mtow_kg']-s['cards'][0]['metrics']['mtow_kg'])
        html=(root/'runs'/r['run_id']/f'plan-{i+1}-card.html').read_text(encoding='utf-8')
        assert '<svg' in html and c['run_id'] in html and '配平' in html and c['definition_sha256'] in html
    rebuilt=compare_sizing_runs(root,r['child_runs'])
    assert rebuilt['summary']==s
    from zipfile import ZipFile
    with ZipFile(root/'runs'/r['run_id']/'scheme-cards.zip') as z:
        assert all(f'plan-{i}-card.html' in z.namelist() for i in range(1,4))
        assert z.testzip() is None


def test_version_runtime_definition_and_artifact_mismatches(actual):
    root,req,r=actual;records=[get_results(root,x) for x in r['child_runs']]
    for key,value in [('version','old'),('source_hashes',{'other':'different'})]:
        altered=deepcopy(records);altered[1][key]=value
        with pytest.raises(ValueError,match='版本|源码'):summarize_comparison(req,altered)
    altered=deepcopy(records);altered[1]['summary']['versions']['openmdao']='unknown'
    with pytest.raises(ValueError,match='求解器'):summarize_comparison(req,altered)
    altered=deepcopy(records);altered[1]['summary']['model_signature']='changed'
    with pytest.raises(ValueError,match='上游模型'):summarize_comparison(req,altered)
    altered=deepcopy(records);altered[0]['definition_sha256']='wrong'
    with pytest.raises(ValueError,match='定义'):summarize_comparison(req,altered)
    # Mutate a copied artifact in its own new comparison, keeping shared fixture intact.
    new=compare_sizing_runs(root,r['child_runs']);p=root/'runs'/new['run_id']/'plan-2-card.html'
    p.write_text('changed',encoding='utf-8')
    with pytest.raises(ValueError,match='完整性'):get_results(root,new['run_id'])


def test_unconfirmed_request_runs_no_solver(tmp_path,monkeypatch):
    def unexpected(*a,**k):raise AssertionError('should not execute')
    monkeypatch.setattr('wingdesignhub.comparison_service.run_sizing',unexpected)
    req=variants(DesignProject(),'payload_kg',[350,400,450]);r=run_comparison(req,tmp_path)
    assert r['status']=='needs_confirmation' and get_results(tmp_path,r['run_id'])==r


def test_failure_and_nonconvergence_not_ranked_or_zero_filled(actual):
    root,req,r=actual;records=[get_results(root,x) for x in r['child_runs']]
    for status in ['failed','out_of_domain','not_converged','constraints_not_met']:
        altered=deepcopy(records);altered[1]['status']=status
        altered[1]['summary']['converged']=status=='constraints_not_met'
        altered[1]['summary']['checks']['mass_budget']=False
        s=summarize_comparison(req,altered)
        assert s['status']=='comparison_incomplete' and s['eligible_schemes']==[0,2]
        assert s['deltas'][1]['values']=={} and s['ranking'] is None
        if status!='constraints_not_met':assert all(v is None for v in s['cards'][1]['metrics'].values())


def test_html_escapes_user_names(actual):
    from wingdesignhub.design_cards import card_html
    card=deepcopy(actual[2]['summary']['cards'][0]);card['name']='<script>alert(1)</script>'
    html=card_html(card)
    assert '<script>' not in html and '&lt;script&gt;' in html


def test_new_constraint_exceedance_is_explained_in_comparison_ui(actual):
    from streamlit.testing.v1 import AppTest
    from wingdesignhub.constraint_states import row
    root,request,result=actual;r=deepcopy(result)
    r['status']='comparison_incomplete'
    for c in r['summary']['cards']:
        c.update(eligible=False,status='constraints_not_met',status_label='部分概念约束超限')
        c['constraint_states']=[row('loading_cg','规定装载CG研究范围','exceeded',value=.08,limit=[.15,.35],unit='MAC'),
            row('range','航程','met'),row('endurance','航时','not_applicable'),row('structure','结构','not_calculated')]
    app=AppTest.from_string('''import streamlit as st
from wingdesignhub.comparison_ui import show_results
show_results(st.session_state['r'],st.session_state['request'],st.session_state['root'])''')
    for key,value in {'r':r,'request':request,'root':root}.items():app.session_state[key]=value
    app.run()
    assert not app.exception
    assert len([x for x in app.error if '规定装载CG研究范围' in x.value])==3
    shown=[x.value for x in app.dataframe if '状态' in x.value.columns]
    assert len(shown)==3 and all(set(x['状态'])=={'满足','超限','不适用','未计算'} for x in shown)


def test_single_child_failure_is_preserved_and_other_runs_continue(actual,monkeypatch):
    root,req,r=actual;records=[get_results(root,x) for x in r['child_runs']]
    failed=deepcopy(records[1]);failed.update(status='failed',error='synthetic process failure',summary={})
    iterator=iter([records[0],failed,records[2]]);calls=[]
    def run(p,root):calls.append(p.name);return next(iterator)
    monkeypatch.setattr('wingdesignhub.comparison_service.run_sizing',run)
    monkeypatch.setattr('wingdesignhub.comparison_service.get_results',lambda root,rid:failed if rid==failed['run_id'] else next(x for x in records if x['run_id']==rid))
    out=run_comparison(req,root)
    assert len(calls)==3 and out['status']=='comparison_incomplete'
    assert out['summary']['cards'][1]['diagnostics']==['synthetic process failure']


def test_cli_comparison_shared_service(tmp_path,monkeypatch,capsys):
    from wingdesignhub import cli
    req=confirmed_request();path=tmp_path/'batch.json';path.write_text(json.dumps(req.to_dict()),encoding='utf-8')
    def run(data,root):
        assert ComparisonRequest.from_dict(data)==req and root==tmp_path
        return {'status':'comparison_incomplete'}
    monkeypatch.setattr(cli,'run_comparison',run)
    monkeypatch.setattr('sys.argv',['wingdesignhub','compare','--input',str(path),'--root',str(tmp_path)])
    assert cli.main()==1 and json.loads(capsys.readouterr().out)['status']=='comparison_incomplete'


def test_ui_confirmation_change_and_three_cards(actual,monkeypatch):
    from streamlit.testing.v1 import AppTest
    from wingdesignhub import comparison_service
    root,req,r=actual
    monkeypatch.setattr(comparison_service,'run_comparison',lambda q,root,**kw:r)
    a=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py')).run(timeout=30)
    a.selectbox(key='comparison-model').set_value('initial').run()
    assert not a.exception and a.button(key='run-comparison').disabled
    next(c for c in a.checkbox if c.label.startswith('我已核对三个')).check().run()
    a.button(key='run-comparison').click().run()
    assert not a.exception and any('三个方案已计算' in x.value for x in a.success)
    assert len(a.metric)==12
    next(n for n in a.number_input if n.label.startswith('方案 B')).set_value(8.5).run()
    assert not a.exception and a.button(key='run-comparison').disabled
    assert any('定义或确认已变更' in x.value for x in a.info)
