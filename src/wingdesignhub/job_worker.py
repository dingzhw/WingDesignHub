"""One dispatcher per workspace, with a separately owned process tree per job."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from .jobs import locked,read,atomic,_records
from .processes import identity,matching_process,launch_owned,stop_owned,tree_snapshot


def mark_incomplete(root,work,status):
    runs=set()
    for path in work.glob('events-*.jsonl'):
        for line in path.read_text('utf-8').splitlines():
            try:row=json.loads(line)
            except ValueError:continue
            if row.get('event')=='run':runs.add(row['run_id'])
    for run_id in runs:
        path=Path(root)/'runs'/run_id/'result.json'
        if path.is_file():
            r=read(path)
            if r.get('status')=='running':
                r.update(status=status,error='任务已停止，未完成结果保留供诊断；重新计算会创建新运行。')
                atomic(path,r)
    return sorted(runs)


def execute_job(root,record):
    from .jobs import job_path
    work=job_path(root,record['job_id']);env=dict(os.environ,WDH_JOB_DIRECTORY=str(work))
    started=time.monotonic();process=owner=None;observed={};peak=0;cancelled=False;failure=None
    try:
        from .jobs import code_identity
        if record['source_hashes']!=code_identity():raise ValueError('排队期间源码已改变，请按原输入重新提交，避免混用版本。')
        with (work/'worker.log').open('ab') as log:
            process,owner=launch_owned([sys.executable,'-X','utf8','-m','wingdesignhub.job_runner',str(root),str(work)],
                stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,env=env)
            record['runner']=identity(process.pid)
            while True:
                members=tree_snapshot(process,owner)
                observed.update({(m['pid'],m['created']):m for m in members})
                peak=max(peak,sum(m['rss'] for m in members))
                record.update(heartbeat=time.time(),elapsed_s=time.monotonic()-started,
                              process_count=len(members),peak_rss_bytes=peak,owned_processes=members)
                with (work/'resources.jsonl').open('a',encoding='utf-8') as log:
                    log.write(json.dumps({'time':record['heartbeat'],'rss_bytes':sum(m['rss'] for m in members),'process_count':len(members)})+'\n')
                if (work/'cancel.json').exists():
                    record['status']='cancel_requested';cancelled=True
                    stop_owned(process,owner);break
                if process.poll() is not None:break
                # Whole-job cap includes report/packing, not just native solvers.
                if time.monotonic()-started>43200:raise TimeoutError('任务总时长超过 12 小时')
                atomic(work/'job.json',record);time.sleep(.5)
            owner.close();owner=None
        record.update(read(work/'outcome.json') if (work/'outcome.json').is_file() else {})
        record['status']='cancelled' if cancelled else ('completed' if process.returncode==0 and record.get('run_id') else 'failed')
    except Exception as exc:
        failure=str(exc);record.update(status='failed',error=failure)
    finally:
        if owner:
            try:stop_owned(process,owner)
            finally:owner.close()
        remaining=[p for p in observed.values() if matching_process(p)]
        deadline=time.monotonic()+5
        while remaining and time.monotonic()<deadline:
            time.sleep(.05);remaining=[p for p in remaining if matching_process(p)]
        if remaining:
            record.update(status='cleanup_failed',error='进程清理尚未确认，请查看任务记录。')
        record['remaining_processes']=remaining
        record['observed_processes']=list(observed.values())
        record['related_run_ids']=mark_incomplete(root,work,record['status'])
        record.update(finished=time.time(),elapsed_s=time.monotonic()-started,peak_rss_bytes=peak)
        atomic(work/'job.json',record)


def main(root):
    root=Path(root).resolve()
    while True:
        with locked(root) as directory:
            records=_records(directory)
            if any(r['status']=='cleanup_failed' for r in records):
                # A live dispatcher must obey the same gate as a fresh dispatcher.
                # A later service read rechecks the owned process identities.
                atomic(directory/'worker.json',None);return
            rows=sorted((r for r in records if r['status']=='queued'),key=lambda r:r['created'])
            if not rows:
                # Clear while holding queue lock: an enqueue cannot lose its worker.
                atomic(directory/'worker.json',None);return
            record=rows[0];record.update(status='running',started=time.time(),worker=identity(os.getpid()))
            atomic(directory/record['job_id']/'job.json',record)
        execute_job(root,record)


if __name__=='__main__':main(sys.argv[1])
