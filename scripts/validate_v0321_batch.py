"""One bounded three-design cold/warm experiment with immutable checkpoints."""
from pathlib import Path
from dataclasses import replace
import argparse,json,os,time
from wingdesignhub.jobs import code_identity,atomic,read
from wingdesignhub.service import get_results
from wingdesignhub.requirements import DesignProject
from wingdesignhub.design_comparison import variants,ComparisonRequest
from wingdesignhub.comparison_service import run_comparison
from wingdesignhub.project_archive import build_bundle,read_bundle,save_bundle

ROOT=Path(__file__).resolve().parents[1];WORK=ROOT/'local/v0321'
NAMESPACE='validation-v0321-batch'


def main(action):
    path=WORK/'checkpoint.json';os.environ['WDH_COMPUTATION_CACHE_NAMESPACE']=NAMESPACE
    if action=='freeze':
        assert not path.exists()
        baseline=get_results(ROOT,'4a326e4aa1144d29ba3cac2ca9d2330a')
        project=DesignProject.from_dict(read(ROOT/'runs'/baseline['run_id']/'input.json'))
        req=variants(project,'sizing.aspect_ratio',(7.5,8.25,9.))
        req=replace(req,projects=tuple(p.confirmed() for p in req.projects),schema_version=2,
                    analysis_model='coupled',analysis_options=baseline['options'])
        cache=ROOT/'local/cache/computation'/NAMESPACE
        assert not list(cache.rglob('*.zip'))
        atomic(path,{'source_hashes':code_identity(),'request':req.to_dict(),'baseline_a':baseline['run_id'],
                     'cache_basis':'new computation namespace; existing verified XFOIL cache retained',
                     'native_three_design_speedup_verified':False});return
    state=read(path);assert state['source_hashes']==code_identity(),'Frozen sources changed'
    req=ComparisonRequest.from_dict(state['request'])
    if action in ('cold','warm'):
        assert action not in state,'Do not repeat an existing attempt'
        if action=='warm':assert state['cold']['status']=='compared_with_limits'
        events=WORK/'events'/action;events.mkdir(parents=True,exist_ok=False)
        os.environ['WDH_JOB_DIRECTORY']=str(events)
        state[action]={'status':'running','started':time.time()};atomic(path,state)
        def progress(i,stage,rid):
            state[action].update(run_id=rid,scheme=i,stage=stage);atomic(path,state)
            print(action,i,stage,rid,flush=True)
        start=time.perf_counter();r=run_comparison(req,ROOT,on_progress=progress)
        state[action].update(run_id=r['run_id'],status=r['status'],elapsed_s=time.perf_counter()-start)
        atomic(path,state);print(json.dumps(state[action]),flush=True)
        assert r['status']=='compared_with_limits',r.get('error');return
    output={'version':'0.3.2.1','rows':[],'same_model_three_design_speedup_verified':False,
            'independent_physical_validation':False,'cache_basis':state['cache_basis']}
    groups={}
    for mode in ('cold','warm'):
        comp=get_results(ROOT,state[mode]['run_id']);children=[get_results(ROOT,r) for r in comp['child_runs']]
        assert len(children)==3
        for i,r in enumerate(children):
            s=r['summary'];assert s['converged'] and all(s['checks'].values())
            assert comp['summary']['cards'][i]['metrics']['block_fuel_kg']==s['mission']['block_fuel_kg']
        groups[mode]=children
        start=time.perf_counter();blob=build_bundle(req,ROOT,comp,profile='portable');elapsed=time.perf_counter()-start
        parsed=read_bundle(blob);index=save_bundle(blob,WORK/('archive-'+mode))
        reopened=read_bundle((WORK/('archive-'+mode)/'local/projects'/(index['archive_id']+'.wdh')).read_bytes())
        assert parsed['records']==reopened['records']==[comp,*children]
        output['rows'].append({'mode':mode,'elapsed_s':state[mode]['elapsed_s'],'run_id':comp['run_id'],
             'bundle_bytes':len(blob),'bundle_build_s':elapsed,'save_reopen':True,
             'schemes':[{'run_id':r['run_id'],'mtow_kg':r['summary']['design_mtow_kg'],
                'fuel_kg':r['summary']['mission']['block_fuel_kg'],'power_w':r['summary']['power']['installed_power_w'],
                'area_m2':r['summary']['geometry']['wing_area_m2'],'cg_x_m':r['summary']['cg']['cg_x_m'],
                'iterations':len(r['summary']['iterations']),'execution_profile':r['summary']['execution_profile']} for r in children]})
    keys=[('design_mtow_kg',),('mission','block_fuel_kg'),('power','installed_power_w'),('geometry','wing_area_m2'),('cg','cg_x_m')]
    def values(r):
        out=[]
        for path in keys:
            v=r['summary']
            for k in path:v=v[k]
            out.append(v)
        return out
    differences=[max(abs(x/y-1) for x,y in zip(values(a),values(b))) for a,b in zip(groups['cold'],groups['warm'])]
    assert max(differences)<1e-10
    baseline=get_results(ROOT,state['baseline_a']);delta=max(abs(x/y-1) for x,y in zip(values(groups['cold'][0]),values(baseline)))
    assert delta<1e-8
    output.update(cold_warm_max_relative_differences=differences,a_relative_to_v032=delta,
                  three_design_three_minute_target_met=state['warm']['elapsed_s']<=180)
    atomic(WORK/'validation.json',output);print(json.dumps(output),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['freeze','cold','warm','collect']);main(p.parse_args().action)
