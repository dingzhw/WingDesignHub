"""Comparison contracts and failure portability; full native matrix is a stage run."""
from dataclasses import replace,asdict
from copy import deepcopy
from pathlib import Path
import json,hashlib
import pytest
from test_comparison import actual,confirmed_request
from wingdesignhub.design_comparison import ComparisonRequest,summarize_comparison
from wingdesignhub.propulsion_feedback import CoupledOptions
from wingdesignhub.comparison_service import run_comparison,compare_sizing_runs
from wingdesignhub.service import get_results,write_json
from wingdesignhub.project_archive import build_bundle,read_bundle,raw_definition
from wingdesignhub.coupled_identity import model_identity


def enhanced(req):return replace(req,schema_version=2,analysis_model='coupled',analysis_options=asdict(CoupledOptions()))


def test_configuration_hash_preserves_legacy_and_confirms_method_options():
    req=confirmed_request();old={'purpose':req.purpose,'schema_version':1,'definitions':[p.definition_hash() for p in req.projects]}
    assert req.definition_hash()==hashlib.sha256(json.dumps(old,sort_keys=True).encode()).hexdigest()
    e=enhanced(req);assert ComparisonRequest.from_dict(e.to_dict())==e
    assert e.definition_hash()==raw_definition(e.to_dict(),'comparison')!=req.definition_hash()
    o=deepcopy(e.analysis_options);o['propeller']['rpm']=2300.
    assert replace(e,analysis_options=o).definition_hash()!=e.definition_hash()
    with pytest.raises(ValueError):replace(e,schema_version=1).validate()
    with pytest.raises(ValueError):replace(e,analysis_model='initial').validate()


def test_method_identity_ignores_only_design_scaling_and_runtime_geometry():
    args=[{'mass':'hash'},{'equivalent_volume_m3':.006,'map_sha256':'a'},
          {'metadata':{'ccblade':'1'},'airfoil':{'cd':[.01]}},
          {'avl_sha256':'avl','xfoil_sha256':'xf','geometry_sha256':'shapeA'},{'openvsp':'3.56'}]
    original=model_identity(*args)[1]
    changed=deepcopy(args);changed[1]['equivalent_volume_m3']=.007;changed[3]['geometry_sha256']='shapeB'
    assert model_identity(*changed)[1]==original
    for i,key,value in [(0,'mass','other'),(1,'map_sha256','b'),(2,'airfoil',{'cd':[.02]}),(3,'xfoil_sha256','changed'),(4,'openvsp','new')]:
        changed=deepcopy(args);changed[i][key]=value
        assert model_identity(*changed)[1]!=original


def test_options_and_mixed_model_rejection(actual):
    root,req,r=actual;req=enhanced(req);records=[get_results(root,rid) for rid in r['child_runs']]
    with pytest.raises(ValueError,match='分析模型'):summarize_comparison(req,records)
    # Contract test only: these are explicitly synthetic discipline results.
    synthetic=deepcopy(records)
    for x in synthetic:x.update(mode='overall_propulsion',options=req.options_dict())
    result=summarize_comparison(req,synthetic)
    assert result['analysis_model']=='coupled'
    synthetic[1]['options']['propeller']['rpm']=2300
    with pytest.raises(ValueError,match='分析选项'):summarize_comparison(req,synthetic)


def test_native_failure_batch_preserves_dependencies_and_rebuild(actual,monkeypatch):
    from wingdesignhub.comparison_service import run_coupled
    root,oldreq,old=actual;req=enhanced(oldreq);seeds=[get_results(root,rid) for rid in old['child_runs']]
    def fail(argv,work,**kw):
        write_json(work/'failure.json',{'status':'engine_sfc_out_of_domain','error':'injected boundary for archive test'})
        raise RuntimeError('injected boundary')
    monkeypatch.setattr('wingdesignhub.coupled_service.execute',fail)
    iterator=iter(seeds);monkeypatch.setattr('wingdesignhub.comparison_service.run_sizing',lambda *a:next(iterator))
    events=[];r=run_comparison(req,root,on_progress=lambda *a:events.append(a))
    assert r['status']=='comparison_incomplete' and len(r['child_runs'])==3
    assert len(events)==9 and [x[1] for x in events]==['initial','coupled','completed']*3
    assert all(c['analysis_model']=='coupled' and not c['eligible'] for c in r['summary']['cards'])
    assert all(all(v is None for v in c['metrics'].values()) for c in r['summary']['cards'])
    parsed=read_bundle(build_bundle(req,root,r))
    assert len(parsed['support_records'])==3 and parsed['current_source_matches']
    assert parsed['records'][0]==r
    rebuilt=compare_sizing_runs(root,r['child_runs']);assert rebuilt['summary']==r['summary']
    reused=run_comparison(req,root,reuse_run_ids=r['child_runs']);assert reused['summary']==r['summary']
    # Recompute container hashes after tampering: semantic lineage still rejects it.
    from io import BytesIO
    from zipfile import ZipFile,ZIP_DEFLATED
    from wingdesignhub.project_archive import encoded,digest
    files=parsed['files'];manifest=deepcopy(parsed['manifest'])
    manifest['support_run_ids']=manifest['support_run_ids'][:-1]
    out=BytesIO()
    with ZipFile(out,'w',compression=ZIP_DEFLATED) as z:
        for name,data in files.items():z.writestr(name,data)
        z.writestr('manifest.json',encoded(manifest))
    with pytest.raises(ValueError,match='来源链'):read_bundle(out.getvalue())


def test_blocked_initial_seed_does_not_appear_as_enhanced_success(actual,monkeypatch):
    root,req,result=actual;req=enhanced(req)
    records=[deepcopy(get_results(root,x)) for x in result['child_runs']]
    for r in records:r.update(status='out_of_domain',summary={},error='test requirement conflict')
    s=summarize_comparison(req,records)
    assert s['eligible_schemes']==[] and all(c['diagnostics'][-1].endswith('未执行。') for c in s['cards'])


def test_new_ui_default_method_and_options_invalidate_confirmation(monkeypatch):
    from streamlit.testing.v1 import AppTest
    from wingdesignhub import project_ui
    monkeypatch.setattr(project_ui,'save_controls',lambda *a,**k:None)
    app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py'),default_timeout=30).run()
    assert not app.exception and app.selectbox(key='comparison-model').value=='coupled'
    next(x for x in app.checkbox if x.label.startswith('我已核对三个')).check().run()
    assert not app.button(key='run-comparison').disabled
    app.number_input(key='comparison-rpm').set_value(2300.).run()
    assert app.button(key='run-comparison').disabled and not app.exception
