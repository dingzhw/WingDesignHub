"""Serial V0.3.2 numerical/performance acceptance. Never edits old runs or caches.

module: fixed real trim contracts, fresh process vs session vs exact warm cache.
freeze: protect the tested source identity before representative calculations.
cold/warm: same old seed and requirements; separate new full runs.
collect: compare to the immutable old native baseline and between new executions.
"""
from pathlib import Path
from copy import deepcopy
import argparse,json,time,os
from wingdesignhub.adapters import tool_paths,sha256
from wingdesignhub.jobs import atomic,read,code_identity
from wingdesignhub.service import get_results

ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT/'local/v032'
BASELINE='3b8a708c07d54eb7bed4698717ec9bae'
CACHE_NAMESPACE='validation-v032-final'


def module():
    from wingdesignhub.avl_session import AVLSession
    from wingdesignhub.aircraft_trim import solve_trim
    source=ROOT/'runs'/BASELINE/'native'
    paths=sorted(source.glob('trial_001/point_*/trim_contract.json'))
    contracts=[read(paths[i]) for i in (0,1,3,5)]
    # Independent operating conditions, including different CGs and exact Machs.
    w=WORK/'module';w.mkdir(exist_ok=False);exe=tool_paths(ROOT)['avl'];sets={};times={}
    for mode in ('native','cold','warm'):
        folder=w/mode;folder.mkdir();began=time.perf_counter();rows=[]
        session=AVLSession(exe,folder/'session',cache=w/'cache') if mode!='native' else None
        try:
            for i,c in enumerate(contracts):
                point=folder/f'point_{i}';point.mkdir()
                r=solve_trim(c,exe,point,solver=session.solve if session else None)
                assert r['trim']['converged'] and max(abs(r['trim'][k]) for k in ('residual_cl','residual_cm'))<=1e-5
                rows.append(r)
        finally:
            if session:session.close()
        times[mode]=time.perf_counter()-began;sets[mode]=rows
        print(mode,times[mode],flush=True)
    checks=[]
    for mode in ('cold','warm'):
        for i,(old,new) in enumerate(zip(sets['native'],sets[mode])):
            delta={k:abs(old['coefficients'][k]-new['coefficients'][k]) for k in ('CLtot','CDff','Cmtot')}
            angles={k:abs(old['trim'][k]-new['trim'][k]) for k in ('alpha_deg','elevator_deg')}
            assert max(delta.values())<1e-9 and max(angles.values())<1e-7
            a=read(w/'native'/f'point_{i}'/'strip_loads.json');b=read(w/mode/f'point_{i}'/'strip_loads.json')
            load=max(abs(x-y) for sa,sb in zip(a['strips'],b['strips']) for k in ('force_body_n','free_moment_body_nm') for x,y in zip(sa[k],sb[k]))
            assert load<1e-6
            checks.append({'mode':mode,'point':i,'coefficient_absolute_error':delta,'angle_error_deg':angles,'strip_load_absolute_error':load})
    assert read(w/'warm/session/session.json')['cache_hits']>0
    atomic(w/'validation.json',{'elapsed_s':times,'checks':checks,'physical_model_changed':False,'data_role':'same native model numerical regression'})


def main(action):
    WORK.mkdir(exist_ok=True)
    os.environ['WDH_COMPUTATION_CACHE_NAMESPACE']=CACHE_NAMESPACE
    if action=='module':module();return
    state_path=WORK/'checkpoint.json'
    if action=='freeze':
        if state_path.exists():raise ValueError('已有冻结记录，请复用或保留失败后另立尝试')
        old=get_results(ROOT,BASELINE);seed=old['parent_run_id']
        cache=ROOT/'local/cache/computation'/CACHE_NAMESPACE
        atomic(state_path,{'source_hashes':code_identity(),'baseline':BASELINE,'seed':seed,
            'baseline_result_sha256':sha256(ROOT/'runs'/BASELINE/'result.json'),
            'computation_cache_entries_before':len(list(cache.rglob('*.zip'))) if cache.exists() else 0,
            'cache_namespace':CACHE_NAMESPACE,
            'xfoil_cache_basis':'Existing verified XFOIL caches retained for same-cache comparison to V0.3.1; not an empty-airfoil-cache benchmark',
            'project':read(ROOT/'runs'/BASELINE/'input.json'),'options':old['options']});return
    state=read(state_path);assert state['source_hashes']==code_identity(),'源码与冻结版本不同'
    assert state['baseline_result_sha256']==sha256(ROOT/'runs'/BASELINE/'result.json')
    if action in ('cold','warm'):
        if action in state:raise ValueError('该正式运行已有记录，不覆盖')
        if action=='warm':assert state.get('cold',{}).get('status')=='concept_checked_with_limits'
        from wingdesignhub.coupled_service import run_coupled
        events=WORK/'events'/action;events.mkdir(parents=True,exist_ok=False)
        os.environ['WDH_JOB_DIRECTORY']=str(events)
        options=deepcopy(state['options']);options['aero']['execution_mode']='reuse'
        t=time.perf_counter();r=run_coupled(state['project'],ROOT,state['seed'],options)
        state[action]={'run_id':r['run_id'],'elapsed_s':time.perf_counter()-t,'status':r['status'],'error':r.get('error')}
        atomic(state_path,state);print(json.dumps(state[action]),flush=True)
        assert r['status']=='concept_checked_with_limits',r.get('error');return
    if action=='collect':
        results={k:get_results(ROOT,state[k]['run_id']) for k in ('cold','warm')};old=get_results(ROOT,BASELINE)
        keys={'mtow':('design_mtow_kg',),'fuel':('mission','block_fuel_kg'),'power':('power','installed_power_w'),
              'area':('geometry','wing_area_m2'),'cg':('cg','cg_x_m')}
        def value(s,path):
            for k in path:s=s[k]
            return s
        rows=[]
        for k,r in results.items():
            s=r['summary'];assert s['converged'] and all(s['checks'].values())
            row={'mode':k,'run_id':r['run_id'],'wall_s':state[k]['elapsed_s'],'execution_profile':s['execution_profile']}
            row['relative_to_v031']={n:value(s,p)/value(old['summary'],p)-1 for n,p in keys.items()}
            row['relative_to_cold']={n:value(s,p)/value(results['cold']['summary'],p)-1 for n,p in keys.items()}
            assert abs(row['relative_to_v031']['mtow'])<=.005
            assert max(abs(row['relative_to_v031'][n]) for n in ('fuel','power'))<=.01
            assert max(abs(v) for v in row['relative_to_cold'].values())<1e-10
            work=ROOT/'runs'/r['run_id'];sessions=[read(p) for p in (work/'native').glob('trial_*/avl_session/session.json')]
            row['avl_session_calls']=sum(x['calls'] for x in sessions);row['avl_exact_cache_hits']=sum(x['cache_hits'] for x in sessions)
            row['native_archive_bytes']=(work/'native_evidence.zip').stat().st_size
            rows.append(row)
        atomic(WORK/'validation.json',{'baseline_run':BASELINE,'baseline_wall_s':3465.16,'rows':rows,'module':read(WORK/'module/validation.json'),
            'cache_basis':state['xfoil_cache_basis'],'physical_validation_passed':False})


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['module','freeze','cold','warm','collect'])
    main(parser.parse_args().action)
