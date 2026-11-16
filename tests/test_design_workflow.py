from dataclasses import replace
from pathlib import Path
import json
import pytest
from wingdesignhub.requirements import DesignProject,WeightRequirement,MissionRequirement
from wingdesignhub.comparison_ui import variants
from wingdesignhub.comparison_service import run_comparison
from wingdesignhub.sizing_service import run_sizing
from wingdesignhub.service import get_results,generate_report
from wingdesignhub.project_archive import build_bundle,read_bundle,save_bundle,load_saved


@pytest.fixture(scope='module')
def actual(tmp_path_factory):
    pytest.importorskip('fastga');root=tmp_path_factory.mktemp('workflow')
    p=DesignProject();p=replace(p,sizing=replace(p.sizing,fuel_model='piper_economy_reference')).confirmed()
    request=variants(p,'sizing.aspect_ratio',[7.5,8.25,9.]);request=replace(request,projects=tuple(p.confirmed() for p in request.projects))
    r=run_comparison(request,root);assert r['status']=='compared_with_limits',r.get('error')
    return root,request,r


def test_calculate_compare_save_close_reopen_and_recompute(actual,tmp_path):
    root,req,r=actual;data=build_bundle(req,root,r);saved=save_bundle(data,tmp_path)
    reopened=load_saved(tmp_path,saved['archive_id'])
    assert reopened['project']==req and reopened['records'][0]==r
    assert reopened['current_source_matches'] and not reopened['migration_required']
    assert b'<!doctype html>' in reopened['files']['reports/report.html']
    assert not (tmp_path/'runs').exists()  # Opening is read-only, not a hidden recalculation.
    new=run_sizing(reopened['project'].projects[0],tmp_path)
    old=get_results(root,r['child_runs'][0]);assert old['run_id']!=new['run_id']
    for key in ('design_mtow_kg','mission','power','geometry','weights','cg','checks'):
        assert old['summary'][key]==new['summary'][key]
    assert old['summary']['mission']['economy_reference_fuel_fraction']>0
    assert old['summary']['mission']['block_fuel_kg']<109.415449


def test_reports_contain_inputs_fuel_ledger_and_review_boundaries(actual):
    root,req,r=actual;child=get_results(root,r['child_runs'][0]);p=req.projects[0]
    html=generate_report(child,project=p)
    for token in ('任务与燃油账目','质量与站位','收敛证据','专业评审待签署','55%','校准','耗油方法','总可用油 kg',child['run_id']):assert token in html
    for method,value in child['summary']['mission']['block_fuel_by_method_kg'].items():
        assert method in html and format(value,'.5g') in html
    assert 'piper_economy_reference' in html and 'off_reference_base_bsfc' in html
    with pytest.raises(ValueError,match='一致'):generate_report(child,project=replace(p,payload_kg=400))


@pytest.mark.parametrize('kind',['budget','conflict'])
def test_infeasible_results_survive_archive_without_becoming_success(tmp_path,kind):
    pytest.importorskip('fastga');p=DesignProject()
    p=replace(p,weight=WeightRequirement('fixed',1000.)) if kind=='budget' else replace(p,mission=MissionRequirement('same_route',8e5,36000.))
    p=p.confirmed();r=run_sizing(p,tmp_path)
    expected='constraints_not_met' if kind=='budget' else 'out_of_domain'
    assert r['status']==expected
    opened=read_bundle(build_bundle(p,tmp_path,r));assert opened['records'][0]['status']==expected
    assert not opened['records'][0]['physical_validation_passed']


def test_library_reopen_then_new_design_does_not_reuse_archived_state(actual,tmp_path,monkeypatch):
    from streamlit.testing.v1 import AppTest
    from wingdesignhub import project_archive
    root,req,r=actual;idx=save_bundle(build_bundle(req,root,r),tmp_path)
    original_list=project_archive.list_saved;original_load=project_archive.load_saved
    monkeypatch.setattr(project_archive,'list_saved',lambda ignored:original_list(tmp_path))
    monkeypatch.setattr(project_archive,'load_saved',lambda ignored,rid:original_load(tmp_path,rid))
    a=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py')).run(timeout=30)
    a.selectbox(key='saved_archive_choice').set_value(idx['archive_id']).run()
    a.button(key='open_saved_design').click().run()
    assert not a.exception and any('已打开存档' in x.value for x in a.info)
    assert a.session_state['opened_archive']['records'][0]['run_id']==r['run_id']
    assert any('三个方案已比较（概念模型）' in x.value for x in a.markdown)
    assert next(x for x in a.selectbox if x.label=='耗油计算方式').value=='piper_economy_reference'
    a.button(key='new_blank_design').click().run()
    assert not a.exception and a.session_state['opened_archive'] is None
    assert next(x for x in a.selectbox if x.label=='耗油计算方式').value=='constant_bsfc'
    assert not next(x for x in a.checkbox if x.label.startswith('我已核对上述')).value


def test_report_cli_preserves_existing_output(actual,tmp_path,monkeypatch,capsys):
    from wingdesignhub.cli import main
    root,req,r=actual;out=tmp_path/'report.html'
    monkeypatch.setattr('sys.argv',['wingdesignhub','report','--root',str(root),'--run-id',r['child_runs'][0],'--output',str(out)])
    assert main()==0 and out.is_file();capsys.readouterr()
    with pytest.raises(FileExistsError):main()


def test_failed_comparison_retains_printable_diagnostic(tmp_path,monkeypatch):
    req=variants(DesignProject(),'sizing.aspect_ratio',[7.5,8.25,9.])
    req=replace(req,projects=tuple(p.confirmed() for p in req.projects))
    def fail(*a,**k):raise OSError('synthetic worker unavailable')
    monkeypatch.setattr('wingdesignhub.comparison_service.run_sizing',fail)
    r=run_comparison(req,tmp_path);assert r['status']=='failed'
    reopened=read_bundle(build_bundle(req,tmp_path,r))
    assert 'synthetic worker unavailable' in reopened['files']['reports/report.html'].decode()
    assert 'failed' in generate_report(r,project=req)
