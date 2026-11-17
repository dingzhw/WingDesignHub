"""Serial V0.3.1 release evidence. Each action is explicit and restartable.

prepare: freeze sources, evaluate fixed-configuration mass correction, submit seed.
cancel-probe: submit one real native coupled job; cancel after an aero point starts.
refreeze: preserve a cancelled/engineering-failed attempt and freeze a reviewed fix.
start: submit the current seed as a fresh native representative run.
collect: verify the finished run, compare frozen V0.3.0 evidence, summarize profiling.
No old record, model coefficient or engineering tolerance is modified.
"""
from pathlib import Path
from copy import deepcopy
import argparse
import json
import time
from wingdesignhub import __version__
from wingdesignhub.jobs import submit_job,get_job,cancel_job,job_path,read,atomic
from wingdesignhub.geometry_service import source_hashes
from wingdesignhub.requirements import DesignProject
from wingdesignhub.service import get_results
from wingdesignhub.configuration import CONFIGURATION_VERSION,surface_parameters
from wingdesignhub.fastga_mass import FastGAMassModel
from wingdesignhub.adapters import sha256

BASELINE='87e7d646dc1e493b9317c39dc6d48533'
ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT/'local/v031/native'


def attribution(old,project):
    s=old['summary'];g=deepcopy(s['geometry'])
    g.update(configuration_version=CONFIGURATION_VERSION,surface_parameters=surface_parameters(project.sizing.aspect_ratio))
    previous=deepcopy(g)
    for name in ('horizontal_tail','vertical_tail'):previous['surface_parameters'][name].update(thickness_ratio=.1,naca='0010')
    previous['surface_parameters']['vertical_tail']['aspect_ratio']=1.8
    actual=read(ROOT/'runs'/BASELINE/'fastga_mass_inputs.json')
    mass=actual['data:weight:aircraft:MTOW']['value'];power=actual['data:propulsion:IC_engine:max_power']['value']
    with FastGAMassModel() as model:
        before=model.evaluate(mass,power,previous,project);old_inputs=deepcopy(model.last_inputs)
        after=model.evaluate(mass,power,g,project);new_inputs=deepcopy(model.last_inputs);audit=deepcopy(model.audit)
    rows=[{'component':k,'before_kg':v,'after_kg':after['components_kg'][k],'delta_kg':after['components_kg'][k]-v}
          for k,v in before['components_kg'].items()]
    result={'basis':'same mass, power, areas, mission and engine; only tail thickness 0.10->0.12 and VT AR1.8->1.6',
        'old_reproduction_max_input_error':max(abs(v['value']-actual[k]['value']) for k,v in old_inputs.items()),
        'old_owe_kg':before['owe_kg'],'new_owe_kg':after['owe_kg'],'delta_owe_kg':after['owe_kg']-before['owe_kg'],
        'changed_inputs':{k:{'before':v,'after':new_inputs[k]} for k,v in old_inputs.items() if v!=new_inputs[k]},
        'components':rows,'domain_ledger':audit['domain_ledger']}
    assert result['old_reproduction_max_input_error']<1e-7,result['old_reproduction_max_input_error']
    assert len(result['changed_inputs'])==3
    atomic(WORK/'mass-attribution.json',result)
    return result


def collect_profile(work):
    events=[]
    for path in work.glob('events-*.jsonl'):
        for line in path.read_text('utf-8').splitlines():
            try:events.append(json.loads(line))
            except ValueError:pass
    starts={e['directory']:e for e in events if e['event']=='solver_started'};groups={}
    finished=[e for e in events if e['event']=='solver_finished']
    assert len(starts)==len(finished),'完整原生运行的求解器开始/结束记录不成对'
    assert all(e['directory'] in starts for e in finished),'求解器开始事件缺失'
    for e in events:
        if e['event']!='solver_finished':continue
        argv=starts.get(e['directory'],{}).get('argv',[])
        if not argv:continue
        name=Path(argv[0]).name.lower()
        if name.startswith('python'):
            name=('OpenVSP full geometry' if 'wingdesignhub.aircraft_vsp_worker' in argv else
                  'OpenVSP area/exposure' if 'wingdesignhub.drag_geometry_worker' in argv else
                  'parent Python worker (inclusive)')
        row=groups.setdefault(name,{'calls':0,'wall_s':0.})
        row['calls']+=1;row['wall_s']+=e['elapsed_s']
    samples=[json.loads(x) for x in (work/'resources.jsonl').read_text('utf-8').splitlines()]
    return {'solver_groups':groups,'aggregation':'parent Python durations include nested solvers; do not sum them with child groups',
            'pack':[e for e in events if e['event']=='pack_finished'],
            'heartbeat_max_interval_s':max((b['time']-a['time'] for a,b in zip(samples,samples[1:])),default=0),
            'resource_samples':len(samples),'peak_rss_bytes':max(x['rss_bytes'] for x in samples),
            'paired_solver_events':len(finished),'aero_points':sum(e['event']=='aero_point' for e in events)}


def compare_preserved_prefix(job_id):
    def values(job):
        result={}
        for path in job_path(ROOT,job).glob('events-*.jsonl'):
            for line in path.read_text('utf-8').splitlines():
                row=json.loads(line)
                if row['event']=='iteration_completed':result[row['iteration']]=row
        return result
    old=values('a2eeb2b89a7b44318e5870b5fe992e4e');new=values(job_id)
    common=sorted(set(old)&set(new))
    keys=('design_mtow_kg','block_fuel_kg','installed_power_w','wing_area_m2','owe_kg','cg_x_m')
    differences={k:max(abs(old[i][k]-new[i][k]) for i in common) for k in keys}
    assert common==list(range(1,11)) and max(differences.values())<1e-9
    return {'completed_common_iterations':common,'max_absolute_differences':differences,
            'basis':'same corrected configuration; before/after bounded numerical recovery; not the V0.3.0 comparison'}


def main(action):
    WORK.mkdir(parents=True,exist_ok=True);checkpoint=WORK/'checkpoint.json'
    if action=='prepare':
        if checkpoint.exists():raise ValueError('已有正式验证状态，请继续对应动作；不覆盖旧证据')
        old=get_results(ROOT,BASELINE);p=DesignProject.from_dict(read(ROOT/'runs'/BASELINE/'input.json'))
        attribution(old,p)
        job=submit_job(ROOT,'size',p)
        state={'version':__version__,'source_hashes':source_hashes(),'baseline_id':BASELINE,
               'baseline_result_sha256':sha256(ROOT/'runs'/BASELINE/'result.json'),'project':p.to_dict(),
               'options':old['options'],'seed_job_id':job['job_id']}
        atomic(checkpoint,state);print(json.dumps({'seed_job_id':job['job_id']}));return
    state=read(checkpoint)
    if action=='refreeze':
        old=get_job(ROOT,state['native_job_id'])
        assert (old['status']=='cancelled' or
                (old['status']=='completed' and old['engineering_status']=='polar_missing') or
                (old['status']=='failed' and old.get('ownership_audit')=='ownership-correction.json')) and not old['remaining_processes']
        archive=WORK/f"checkpoint-attempt-{old['job_id']}.json"
        if archive.exists():raise ValueError('已保存该次尝试，不能覆盖；请继续 start')
        atomic(archive,state)
        job=submit_job(ROOT,'size',state['project'])
        state.setdefault('preserved_attempts',[]).append({'job_id':old['job_id'],'run_ids':old['related_run_ids'],
            'reason':state.pop('refreeze_reason',None) or (
                      'XFOIL 240/280/320-panel oscillation at fixed physical conditions; bounded 360/400 refinement verified'
                      if old['status']=='completed' else 'parallel telemetry append lost events; cancelled, fixed with per-process thread lock'),
            'checkpoint':archive.name})
        state.update(source_hashes=source_hashes(),seed_job_id=job['job_id'])
        for key in ('native_job_id','native_run_id','seed_run_id'):state.pop(key,None)
        atomic(checkpoint,state);print(json.dumps({'seed_job_id':job['job_id']}));return
    assert state['source_hashes']==source_hashes(),'源码与冻结状态不同'
    if action=='cancel-probe':
        seed=get_job(ROOT,state['seed_job_id']);assert seed['status']=='completed'
        assert seed['engineering_status']=='concept_checked_with_limits'
        job=submit_job(ROOT,'coupled',state['project'],seed['run_id'],state['options'])
        state.update(seed_run_id=seed['run_id'],cancel_job_id=job['job_id']);atomic(checkpoint,state)
        print(json.dumps({'cancel_job_id':job['job_id']}))
    elif action=='cancel':
        before=get_job(ROOT,state['cancel_job_id'])
        assert any(e['event']=='aero_point' for e in before['events']),'等待真实原生工况启动后再取消'
        state['cancel_requested_time']=time.time();cancel_job(ROOT,state['cancel_job_id']);atomic(checkpoint,state)
        print('cancel requested')
    elif action=='start':
        old=get_job(ROOT,state['cancel_job_id']);assert old['status']=='cancelled' and not old['remaining_processes']
        state['cancel_latency_s']=old['finished']-state['cancel_requested_time']
        assert state['cancel_latency_s']<10
        seed=get_job(ROOT,state['seed_job_id']);assert seed['status']=='completed'
        assert seed['engineering_status']=='concept_checked_with_limits'
        state['seed_run_id']=seed['run_id']
        job=submit_job(ROOT,'coupled',state['project'],seed['run_id'],state['options'])
        state['native_job_id']=job['job_id'];atomic(checkpoint,state)
        print(json.dumps({'native_job_id':job['job_id']}))
    elif action=='collect':
        job=get_job(ROOT,state['native_job_id']);assert job['status']=='completed',job
        r=get_results(ROOT,job['run_id']);assert r['status']=='concept_checked_with_limits',r.get('error')
        assert r['source_hashes']==state['source_hashes']
        old=get_results(ROOT,BASELINE);s=r['summary'];prior=old['summary']
        assert sha256(ROOT/'runs'/BASELINE/'result.json')==state['baseline_result_sha256']
        assert s['converged'] and all(s['checks'].values())
        directory=ROOT/'runs'/r['run_id'];assert (directory/'final_geometry/surface_mesh.json').is_file()
        geom=read(directory/'final_geometry/geometry_contract.json')
        assert abs(geom['references']['area_m2']-s['geometry']['wing_area_m2'])<1e-9
        rows=[]
        for name,a,b in [('MTOW kg',prior['design_mtow_kg'],s['design_mtow_kg']),('OWE kg',prior['weights']['owe_kg'],s['weights']['owe_kg']),
            ('fuel kg',prior['mission']['block_fuel_kg'],s['mission']['block_fuel_kg']),('power W',prior['power']['installed_power_w'],s['power']['installed_power_w']),
            ('area m2',prior['geometry']['wing_area_m2'],s['geometry']['wing_area_m2'])]:
            rows.append({'quantity':name,'before':a,'after':b,'relative_change':b/a-1})
        result={'version':__version__,'status':'native_checks_passed','run_id':r['run_id'],'job_id':job['job_id'],
            'seed_run_id':state['seed_run_id'],'cancel_job_id':state['cancel_job_id'],'cancel_latency_s':state['cancel_latency_s'],
            'source_hashes':state['source_hashes'],'comparisons':rows,'iteration_count':len(s['iterations']),
            'elapsed_s':job['elapsed_s'],'remaining_processes':job['remaining_processes'],
            'profile':collect_profile(job_path(ROOT,job['job_id'])),'checks':s['checks'],
            'physical_validation_passed':False,'data_role':'same synthetic aircraft and conditions; numerical/model-consistency regression, not independent physical data'}
        result['unchanged_iteration_prefix']=compare_preserved_prefix(job['job_id'])
        monitor_old=get_results(ROOT,'1aa979452aff46d99dfd2fe3cc49d710')
        assert set(monitor_old['source_hashes'])==set(state['source_hashes'])
        changed=sorted(key for key,value in state['source_hashes'].items() if monitor_old['source_hashes'][key]!=value)
        assert set(changed)=={'processes.py','jobs.py','job_worker.py'}
        old_steps=monitor_old['summary']['iterations'];new_steps=s['iterations']
        assert len(old_steps)==len(new_steps)
        keys=('design_mtow_kg','block_fuel_kg','installed_power_w','wing_area_m2','owe_kg','cg_x_m')
        differences={key:max(abs(a[key]-b[key]) for a,b in zip(old_steps,new_steps)) for key in keys}
        assert max(differences.values())<1e-9
        result['unchanged_after_process_membership_fix']={'prior_run_id':monitor_old['run_id'],
            'iterations':len(new_steps),'max_absolute_differences':differences,
            'changed_core_files':changed,'unchanged_core_file_count':len(state['source_hashes'])-len(changed),
            'basis':'completed engineering calculation retained despite false monitoring ownership; all physical model code unchanged'}
        refined=[]
        for path in (directory/'native').rglob('recovery.json'):
            for item in read(path):
                panels=item.get('attempts',[{}])[-1].get('panels',0)
                if panels>=360:
                    parsed=read(path.parent/'parsed.json')
                    spec=read(path.parent/'cache.json')['identity']['spec']
                    refined.append({'polar_directory':path.parent.relative_to(directory/'native').as_posix(),
                                    'cl':item['cl'],'accepted_panels':panels,
                                    'conditions':spec,'accepted_row':next(r for r in parsed['rows'] if r['requested_cl']==item['cl'])})
        result['bounded_refinement_points']=refined
        caches=[read(p) for p in (directory/'native').rglob('cache.json')]
        manifest=read(directory/'native_manifest.json')
        geometry_hashes=[h for name,h in manifest['files'].items() if name.endswith('/aircraft.vsp3')]
        result['profile'].update(trial_aero_points=sum(1 for p in (directory/'native').glob('trial_*/point_*') if p.is_dir()),
            polar_cache_hits=sum(c.get('cache_hit') is True for c in caches),polar_cache_misses=sum(c.get('cache_hit') is False for c in caches),
            geometry_files=len(geometry_hashes),unique_geometry_contents=len(set(geometry_hashes)),
            cache_basis='existing local cache plus preceding cancelled probes; mixed cache, not a cold-cache speed benchmark')
        atomic(WORK/'summary.json',result);state['native_run_id']=r['run_id'];atomic(checkpoint,state)
        print(json.dumps({k:v for k,v in result.items() if k not in ('profile','source_hashes')},ensure_ascii=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['prepare','cancel-probe','cancel','refreeze','start','collect'])
    main(parser.parse_args().action)
