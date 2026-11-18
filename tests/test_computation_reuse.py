import json
from pathlib import Path
from copy import deepcopy
import shutil
import zipfile
import pytest
from wingdesignhub.computation_identity import BASE,sources,digest,ENTRIES,environment
from wingdesignhub.exact_cache import ExactCache
from wingdesignhub.aero_feedback import FeedbackOptions


def test_dependency_closure_ui_independent_and_numerical_sensitive(tmp_path):
    shutil.copytree(BASE,tmp_path/'src',ignore=shutil.ignore_patterns('__pycache__'))
    base=tmp_path/'src';before=sources(ENTRIES['coupled'],base)
    assert 'ccblade_adapter.py' in before and 'aircraft_vsp_worker.py' in before
    assert 'configuration.py' in before and 'xfoil_polars.py' in before
    assert not any(n.endswith('_ui.py') for n in before)
    (base/'coupled_ui.py').write_text('presentation changed')
    assert sources(ENTRIES['coupled'],base)==before
    geometry=sources(ENTRIES['geometry'],base)
    with (base/'engine_fuel.py').open('a') as f:f.write('\n# model revision\n')
    assert sources(ENTRIES['coupled'],base)!=before
    assert sources(ENTRIES['geometry'],base)==geometry


def test_julia_source_environment_and_missing_resource_identity(tmp_path):
    from wingdesignhub.computation_identity import environment
    (tmp_path/'local').mkdir();package=tmp_path/'package';(package/'src').mkdir(parents=True)
    julia=tmp_path/'julia.exe';julia.write_bytes(b'fixture binary')
    for n in ('Project.toml','Manifest.toml'):(package/n).write_text('version="1"')
    worker=package/'src/model.jl';worker.write_text('x=1')
    (tmp_path/'local/propulsion-tools.json').write_text(json.dumps({'julia':str(julia),'package':str(package),'project':str(package)}))
    before=environment(tmp_path,'propulsion');worker.write_text('x=2')
    assert environment(tmp_path,'propulsion')!=before
    worker.unlink();assert 'CCBlade/src/model.jl' not in environment(tmp_path,'propulsion')


def test_exact_cache_no_rounding_hash_validation_and_no_overwrite(tmp_path):
    w=tmp_path/'work';w.mkdir();(w/'raw.txt').write_text('numerical evidence')
    c=ExactCache(tmp_path/'cache','unit');key={'speed':58.,'model':'v1'}
    c.publish(key,w,['raw.txt']);out=tmp_path/'new';out.mkdir()
    assert not c.restore({**key,'speed':58.+1e-12},out)
    assert c.restore(key,out) and (out/'raw.txt').read_text()=='numerical evidence'
    with pytest.raises(ValueError,match='覆盖'):c.restore(key,out)
    path=c.root/(digest(key)+'.zip')
    with zipfile.ZipFile(path) as z:manifest=json.loads(z.read('manifest.json'))
    with zipfile.ZipFile(path,'w') as z:
        z.writestr('manifest.json',json.dumps(manifest));z.writestr('raw.txt','corrupt')
    with pytest.raises(ValueError,match='哈希'):c.restore(key,tmp_path/'bad')


def test_cache_rejects_traversal_and_execution_mode(tmp_path):
    c=ExactCache(tmp_path,'bad')
    with pytest.raises(ValueError):c.publish({},tmp_path,['../outside'])
    with pytest.raises(ValueError):FeedbackOptions(execution_mode='approximate').validate()
    FeedbackOptions(execution_mode='native_audit').validate()


def test_table_batch_preserves_order_and_exact_values():
    from wingdesignhub.aero_feedback import MissionAeroTable
    class Native:
        def __call__(self,m,cg,v,h,r):return {'mass_kg':m,'altitude_m':h,'cd':m+h+v+r}
    class Batch(Native):
        def batch(self,requests):return [self(*r) for r in requests]
    args=(500.,1200.,2.,[500.,600.],3,[(50.,2.,[0.,2000.]),(60.,0.,[2000.,2000.])],15.)
    assert MissionAeroTable(Native(),*args).to_dict()==MissionAeroTable(Batch(),*args).to_dict()


def test_comparison_allows_blocked_seed_subset_but_rejects_shared_model_conflict():
    from wingdesignhub.computation_identity import comparison_compatible
    a={'version':'0.3.2','calculation_identity':{'sources':{'sizing.py':'a'},'environment':{'numpy':'1'}}}
    b=deepcopy(a);b['calculation_identity']['sources']['aero.py']='b'
    assert comparison_compatible([a,b,b])
    b['calculation_identity']['sources']['sizing.py']='c'
    assert not comparison_compatible([a,b,b])


def test_session_waits_past_load_prompt_before_reading_outputs(tmp_path):
    import io,queue
    from types import SimpleNamespace
    from wingdesignhub.avl_session import AVLSession
    s=AVLSession.__new__(AVLSession);s.work=tmp_path;s.timeout=1.;s.total=0;s.limit=1024
    s.log=io.BytesIO();s.process=SimpleNamespace(stdin=io.BytesIO(),poll=lambda:None)
    s.messages=queue.Queue();s.messages.put(b'Loaded geometry\n AVL   c>  ')
    s.messages.put(b'Computed and wrote files\n AVL   c>  ')
    output=s._exchange('LOAD model.avl\nOPER\n',prompts=2)
    assert 'Computed and wrote files' in output and s.messages.empty()


def test_session_identity_keeps_full_precision_reference(tmp_path):
    from wingdesignhub.avl_session import AVLSession
    exe=tmp_path/'solver.exe';exe.write_bytes(b'not executed')
    c={'references':{'area_m2':1.,'chord_m':1.,'span_m':1.,'moment_reference_geometry_m':[2.,0.,0.]},
       'flow':{'mach':.1,'speed_m_s':30.,'density_kg_m3':1.,'mass_kg':100.,'alpha_deg':3.,'beta_deg':0.},
       'options':{'mesh_level':1},'surfaces':[],'controls':[]}
    keys=[]
    class Capture:
        def restore(self,key,work):keys.append(key);raise ValueError('captured')
    for i,x in enumerate((2.,2.+1e-15)):
        c['references']['moment_reference_geometry_m']=[x,0.,0.]
        s=AVLSession(exe,tmp_path/str(i));s.cache=Capture()
        with pytest.raises(ValueError,match='captured'):s.solve(c,str(exe),tmp_path)
    assert keys[0]['model']==keys[1]['model']
    assert digest(keys[0])!=digest(keys[1])


def test_legacy_comparison_definition_keeps_original_execution_options():
    from dataclasses import asdict,replace
    import hashlib
    from wingdesignhub.requirements import DesignProject
    from wingdesignhub.design_comparison import ComparisonRequest
    from wingdesignhub.propulsion_feedback import CoupledOptions
    p=DesignProject();projects=tuple(replace(p,name=str(i),sizing=replace(p.sizing,aspect_ratio=float(i+7))).confirmed() for i in range(3))
    options=asdict(CoupledOptions());options['aero'].pop('execution_mode')
    req=ComparisonRequest(projects,'design_trade',2,'coupled',options)
    original={'purpose':req.purpose,'schema_version':2,'definitions':[p.definition_hash() for p in projects],
              'analysis_model':'coupled','analysis_options':options}
    assert req.definition_hash()==hashlib.sha256(json.dumps(original,sort_keys=True).encode()).hexdigest()
    assert ComparisonRequest.from_dict(req.to_dict()).options_dict()==options


def test_new_execution_of_legacy_comparison_explicitly_records_mode(tmp_path,monkeypatch):
    from dataclasses import asdict
    from wingdesignhub.design_comparison import ComparisonRequest
    from wingdesignhub.propulsion_feedback import CoupledOptions
    from wingdesignhub import comparison_service
    options=asdict(CoupledOptions());options['aero'].pop('execution_mode')
    req=ComparisonRequest((),'design_trade',2,'coupled',options)
    monkeypatch.setattr(comparison_service,'_save',lambda request,*a,**k:request)
    actual=comparison_service.run_comparison(req,tmp_path)
    assert actual.options_dict()['aero']['execution_mode']=='reuse'
    assert 'execution_mode' not in req.analysis_options['aero']
