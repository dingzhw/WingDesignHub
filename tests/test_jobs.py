import json
import os
from pathlib import Path
import subprocess
import sys
import time
import pytest
from wingdesignhub import jobs
from wingdesignhub.processes import launch_owned,stop_owned,matching_process,tree_snapshot
from wingdesignhub.requirements import DesignProject


def test_owned_descendants_and_unrelated_process(tmp_path,monkeypatch):
    marker=tmp_path/'child.json'
    code="import subprocess,sys,time,json,psutil; p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); open(sys.argv[1],'w').write(json.dumps({'pid':p.pid,'created':psutil.Process(p.pid).create_time()})); time.sleep(60)"
    other,other_owner=launch_owned([sys.executable,'-c','import time; time.sleep(60)'])
    p,owner=launch_owned([sys.executable,'-c',code,str(marker)])
    try:
        deadline=time.monotonic()+10
        while not marker.exists() and time.monotonic()<deadline:time.sleep(.05)
        child=json.loads(marker.read_text());assert matching_process(child)
        if os.name=='nt':
            import psutil
            # Simulate a stale PPID edge to an unrelated process, as observed
            # after thousands of solver launches during the native release run.
            monkeypatch.setattr(psutil.Process,'children',lambda *args,**kwargs:[psutil.Process(other.pid)])
            actual=set(owner.process_ids(capacity=1))
            assert {p.pid,child['pid']}<=actual and other.pid not in actual
            assert owner.contains(p.pid) and not owner.contains(other.pid)
            snapshot={r['pid'] for r in tree_snapshot(p,owner)}
            assert {p.pid,child['pid']}<=snapshot and other.pid not in snapshot
        start=time.monotonic();stop_owned(p,owner);owner.close()
        while matching_process(child) and time.monotonic()-start<5:time.sleep(.05)
        assert not matching_process(child)
        assert time.monotonic()-start<10
        assert other.poll() is None
    finally:
        owner.close();stop_owned(other,other_owner);other_owner.close()


def test_queue_idempotency_cancel_and_recovery(tmp_path,monkeypatch):
    monkeypatch.setattr(jobs,'_start',lambda *a:None)
    p=DesignProject().confirmed()
    a=jobs.submit_job(tmp_path,'size',p);b=jobs.submit_job(tmp_path,'size',p)
    assert a['job_id']==b['job_id']
    assert jobs.cancel_job(tmp_path,a['job_id'])['status']=='cancelled'
    c=jobs.retry_job(tmp_path,a['job_id']);assert c['job_id']!=a['job_id']
    work=jobs.job_path(tmp_path,c['job_id']);c['status']='running';jobs.atomic(work/'job.json',c)
    with jobs.locked(tmp_path) as directory:jobs._recover(directory)
    assert jobs.get_job(tmp_path,c['job_id'])['status']=='interrupted'
    assert len(jobs.list_jobs(tmp_path))==2


def test_requests_reject_commands_paths_and_unconfirmed(tmp_path):
    with pytest.raises(ValueError):jobs.submit_job(tmp_path,'shell',DesignProject().confirmed())
    with pytest.raises(ValueError):jobs.submit_job(tmp_path,'size',DesignProject())
    with pytest.raises(ValueError):jobs.submit_job(tmp_path,'coupled',DesignProject().confirmed(),'../outside')
    with pytest.raises(ValueError):jobs.get_job(tmp_path,'../outside')
    from wingdesignhub.propulsion_feedback import CoupledOptions
    request=jobs.validate_request('coupled',DesignProject().confirmed(),'0'*32,CoupledOptions())
    assert request['options']['propeller']['rpm']==2400


def test_dispatcher_stops_after_unconfirmed_cleanup_and_rechecks_before_resume(tmp_path,monkeypatch):
    from wingdesignhub import job_worker
    monkeypatch.setattr(jobs,'_start',lambda *a:None)
    first=jobs.submit_job(tmp_path,'size',DesignProject().confirmed())
    other=DesignProject(name='等待清理确认的第二个方案')
    second=jobs.submit_job(tmp_path,'size',other.confirmed())
    called=[]
    def cleanup_failed(root,record):
        called.append(record['job_id'])
        record.update(status='cleanup_failed',owned_processes=[{'pid':999,'created':1.}])
        jobs.atomic(jobs.job_path(root,record['job_id'])/'job.json',record)
    monkeypatch.setattr(job_worker,'execute_job',cleanup_failed)
    job_worker.main(tmp_path)
    assert called==[first['job_id']]
    assert jobs.read(jobs.job_path(tmp_path,second['job_id'])/'job.json')['status']=='queued'
    assert jobs.read(jobs.queue_path(tmp_path)/'worker.json') is None
    monkeypatch.setattr(jobs,'matching_process',lambda saved:object())
    with jobs.locked(tmp_path) as directory:jobs._recover(directory)
    assert jobs.read(jobs.job_path(tmp_path,first['job_id'])/'job.json')['status']=='cleanup_failed'
    monkeypatch.setattr(jobs,'matching_process',lambda saved:None)
    with jobs.locked(tmp_path) as directory:jobs._recover(directory)
    assert jobs.read(jobs.job_path(tmp_path,first['job_id'])/'job.json')['status']=='interrupted'


def test_recovery_retains_explicit_remaining_members_even_when_last_sample_is_empty(tmp_path,monkeypatch):
    monkeypatch.setattr(jobs,'_start',lambda *a:None)
    record=jobs.submit_job(tmp_path,'size',DesignProject().confirmed())
    record.update(status='cleanup_failed',owned_processes=[],remaining_processes=[{'pid':999,'created':1.}])
    path=jobs.job_path(tmp_path,record['job_id'])/'job.json';jobs.atomic(path,record)
    monkeypatch.setattr(jobs,'matching_process',lambda saved:object())
    with jobs.locked(tmp_path) as directory:jobs._recover(directory)
    assert jobs.read(path)['status']=='cleanup_failed'
    monkeypatch.setattr(jobs,'matching_process',lambda saved:None)
    with jobs.locked(tmp_path) as directory:jobs._recover(directory)
    assert jobs.read(path)['status']=='interrupted'


def test_pid_reuse_does_not_match():
    from wingdesignhub.processes import identity
    saved=identity(os.getpid());saved['created']-=10
    assert matching_process(saved) is None


def test_timeout_logs_and_cleans_child(tmp_path):
    from wingdesignhub.adapters import execute
    with pytest.raises(RuntimeError,match='超过'):
        execute([sys.executable,'-c','import time; time.sleep(60)'],tmp_path,timeout=.2)
    evidence=json.loads((tmp_path/'command.json').read_text())
    assert evidence['returncode']!=0 and evidence['elapsed_s']<10
    assert (tmp_path/'stdout.log').exists()


@pytest.mark.skipif(os.name!='nt',reason='Windows Job Object close-on-crash guarantee')
def test_owner_crash_reclaims_descendant(tmp_path):
    script=tmp_path/'owner.py';marker=tmp_path/'child.json'
    script.write_text("import os,sys,time,json\nfrom wingdesignhub.processes import launch_owned,identity\np,o=launch_owned([sys.executable,'-c','import time;time.sleep(60)'])\nopen(sys.argv[1],'w').write(json.dumps(identity(p.pid)))\nos._exit(23)\n",encoding='utf-8')
    p=subprocess.Popen([sys.executable,str(script),str(marker)])
    assert p.wait(timeout=10)==23
    child=json.loads(marker.read_text('utf-8'));deadline=time.monotonic()+5
    while matching_process(child) and time.monotonic()<deadline:time.sleep(.05)
    assert matching_process(child) is None


def test_unknown_process_access_is_not_claimed_dead(monkeypatch):
    import psutil
    monkeypatch.setattr(psutil,'Process',lambda pid:(_ for _ in ()).throw(psutil.AccessDenied(pid)))
    with pytest.raises(PermissionError,match='进程'):
        matching_process({'pid':123,'created':1.})


def test_progress_is_chronological_across_comparison_workers(tmp_path):
    from wingdesignhub.job_events import latest
    # PID order need not match scheme order. Long solver logs must not hide the stage.
    jobs.atomic(tmp_path/'progress-iteration_completed-100.json',{'event':'iteration_completed','time':20,'iteration':2})
    jobs.atomic(tmp_path/'progress-iteration_completed-999.json',{'event':'iteration_completed','time':10,'iteration':8})
    jobs.atomic(tmp_path/'progress-run-1.json',{'event':'run','time':15,'progress':{'scheme':1,'stage':'coupled'}})
    rows=latest(tmp_path)
    assert rows[-1]['iteration']==2
    assert next(x for x in rows if x['event']=='run')['progress']['scheme']==1


def test_threaded_solver_events_are_complete(tmp_path,monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from wingdesignhub.job_events import event
    monkeypatch.setenv('WDH_JOB_DIRECTORY',str(tmp_path))
    def emit(worker):
        for sequence in range(200):
            event('solver_started',directory=f'{worker}/{sequence}',label='并行翼型')
            event('solver_finished',directory=f'{worker}/{sequence}',elapsed_s=.01)
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(emit,range(8)))
    rows=[json.loads(line) for line in (tmp_path/f'events-{os.getpid()}.jsonl').read_text('utf-8').splitlines()]
    assert len(rows)==3200
    starts=[r['directory'] for r in rows if r['event']=='solver_started']
    ends=[r['directory'] for r in rows if r['event']=='solver_finished']
    assert len(set(starts))==1600 and sorted(starts)==sorted(ends)
    assert [r['time'] for r in rows]==sorted(r['time'] for r in rows)
