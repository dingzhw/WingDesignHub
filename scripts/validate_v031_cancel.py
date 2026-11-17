"""Cancel one final-source native job after the first aerodynamic point starts.

Run serially after the successful representative; preserve it and every earlier probe.
"""
from pathlib import Path
import json
import sys
import time
from wingdesignhub.jobs import read,atomic,submit_job,cancel_job,job_path,code_identity
from wingdesignhub.geometry_service import source_hashes

ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT/'local/v031/final-cancel'


def bounded(action):
    for attempt in range(10):
        try:return action()
        except PermissionError:
            if attempt==9:raise
            time.sleep(.05)


def read_state(path):
    return bounded(lambda:read(path))


def main(resume=False):
    state=read_state(ROOT/'local/v031/native/checkpoint.json')
    assert state['source_hashes']==source_hashes()
    assert read_state(job_path(ROOT,state['native_job_id'])/'job.json')['status']=='completed'
    if resume:
        assert not (WORK/'validation.json').exists()
        saved=read_state(WORK/'checkpoint.json')
        record=read_state(job_path(ROOT,saved['job_id'])/'job.json')
        assert record['source_hashes']==code_identity()
        request=read_state(job_path(ROOT,record['job_id'])/'request.json')
        assert request['project']==state['project'] and request['parent_run_id']==state['seed_run_id'] and request['options']==state['options']
    else:
        WORK.mkdir(parents=True,exist_ok=False)
        record=submit_job(ROOT,'coupled',state['project'],state['seed_run_id'],state['options'])
    work=job_path(ROOT,record['job_id'])
    atomic(WORK/'checkpoint.json',{'job_id':record['job_id'],'state':'waiting_first_aero_point'})
    deadline=time.monotonic()+300
    while True:
        record=read_state(work/'job.json')
        points=[read_state(path) for path in work.glob('progress-aero_point-*.json')]
        if points:break
        if record['status'] not in ('queued','running'):raise RuntimeError(record)
        if time.monotonic()>deadline:
            cancel_job(ROOT,record['job_id'])
            raise TimeoutError('first aerodynamic point not observed; cancellation requested')
        time.sleep(.1)
    before=time.time();bounded(lambda:cancel_job(ROOT,record['job_id']))
    deadline=time.monotonic()+15
    while True:
        record=read_state(work/'job.json')
        if record['status'] not in ('running','cancel_requested'):break
        if time.monotonic()>deadline:raise TimeoutError('cancellation not confirmed; record retained')
        time.sleep(.1)
    elapsed=record['finished']-before
    checks={'real_aerodynamic_stage_observed':bool(points),
            'cancelled_confirmed':record['status']=='cancelled',
            'no_owned_process_remaining':not record['remaining_processes'],
            'within_10_seconds':0<=elapsed<10,
            'source_still_frozen':state['source_hashes']==source_hashes()}
    result={'checks':checks,'job_id':record['job_id'],'related_run_ids':record['related_run_ids'],
            'cancel_latency_s':elapsed,'status':record['status'],'resumed_same_probe':resume,
            'scope':'final-source native job cancellation; representative completed run retained'}
    atomic(WORK/'validation.json',result)
    print(json.dumps(result,ensure_ascii=False))
    assert all(checks.values()),checks


if __name__=='__main__':main('--resume' in sys.argv)
