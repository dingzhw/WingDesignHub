"""Persistent, serial local jobs shared by GUI, CLI and Python services.

Recovery retains evidence and submits a new run; it does not resume a solver's
internal iteration. No command strings or executable paths are accepted here.
"""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from uuid import UUID,uuid4
from .processes import identity,matching_process

ACTIVE = {'queued','running','cancel_requested'}
KINDS = ('size','feedback','coupled','compare','geometry','aero','trim','drag','propulsion','fastga_reference','tools')


def code_identity():
    from .geometry_service import source_hashes
    result=source_hashes()
    for path in Path(__file__).parent.glob('*.jl'):
        result[path.name]=hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def atomic(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name(path.name+'.'+uuid4().hex+'.tmp')
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    for attempt in range(6):
        try:temporary.replace(path);return
        except PermissionError:
            if attempt==5:raise
            time.sleep(.03*2**attempt)


def read(path):
    return json.loads(Path(path).read_text('utf-8'))


def queue_path(root):
    return Path(root).resolve()/'local'/'jobs'


@contextmanager
def locked(root):
    directory=queue_path(root);directory.mkdir(parents=True,exist_ok=True)
    with (directory/'queue.lock').open('a+b') as stream:
        if stream.tell()==0:stream.write(b'0');stream.flush()
        deadline=time.monotonic()+10
        while True:
            try:
                stream.seek(0)
                if os.name=='nt':
                    import msvcrt
                    msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
                else:
                    import fcntl
                    fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic()>deadline:raise TimeoutError('任务队列忙，请稍后重试')
                time.sleep(.03)
        try:yield directory
        finally:
            stream.seek(0)
            if os.name=='nt':msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)
            else:fcntl.flock(stream,fcntl.LOCK_UN)


def job_path(root,job_id):
    if UUID(job_id).hex!=job_id:raise ValueError('无效任务编号')
    return queue_path(root)/job_id


def validate_request(kind,project=None,parent_run_id=None,options=None):
    if kind not in KINDS:raise ValueError('未注册的后台任务')
    if parent_run_id is not None and UUID(parent_run_id).hex!=parent_run_id:raise ValueError('无效来源编号')
    if kind in ('fastga_reference','tools'):return {'kind':kind,'project':None,'parent_run_id':None,'options':{}}
    if kind=='compare':
        from .design_comparison import ComparisonRequest
        p=ComparisonRequest.from_dict(project) if isinstance(project,dict) else project
        p.validate();data=p.to_dict()
        if any(x.confirmation_sha256!=x.definition_hash() for x in p.projects):raise ValueError('请先确认三个方案')
    else:
        from .requirements import DesignProject,build_design_intent
        p=DesignProject.from_dict(project) if isinstance(project,dict) else project
        p.check_schema();data=p.to_dict()
        if build_design_intent(p)['status']!='requirements_ready':raise ValueError('请先核对需求与假设并确认')
    if kind not in ('size','compare') and not parent_run_id:raise ValueError('此任务需要来源运行编号')
    options={} if options is None else options
    if not isinstance(options,dict):
        from dataclasses import asdict
        options=asdict(options)
    if kind in ('size','compare') and options:raise ValueError('此任务选项应写在需求配置中')
    if kind not in ('size','compare'):
        from .propulsion_feedback import CoupledOptions
        from .aero_feedback import FeedbackOptions
        from .aircraft_geometry import GeometryOptions
        from .aircraft_aero import AeroOptions
        from .aircraft_trim import TrimOptions
        from .aircraft_drag import DragOptions
        from .propulsion_model import PropulsionOptions
        cls={'feedback':FeedbackOptions,'coupled':CoupledOptions,'geometry':GeometryOptions,
             'aero':AeroOptions,'trim':TrimOptions,'drag':DragOptions,'propulsion':PropulsionOptions}[kind]
        from dataclasses import asdict
        obj=cls.from_dict(options) if hasattr(cls,'from_dict') else cls(**options)
        obj.validate();options=asdict(obj)
    return {'kind':kind,'project':data,'parent_run_id':parent_run_id,'options':options}


def _records(directory):
    return [read(p) for p in directory.glob('*/job.json')]


def _recover(directory):
    worker=read(directory/'worker.json') if (directory/'worker.json').exists() else None
    if worker and matching_process(worker):return worker
    for record in _records(directory):
        if record['status'] in ('running','cancel_requested','cleanup_failed'):
            saved={ (p['pid'],p['created']):p for p in
                    record.get('owned_processes',[])+record.get('remaining_processes',[]) }
            remaining=[p for p in saved.values() if matching_process(p)]
            if remaining:
                record.update(status='cleanup_failed',remaining_processes=remaining,error='失联任务尚有进程存活；队列等待清理确认。')
                atomic(directory/record['job_id']/'job.json',record)
                continue
            record.update(status='interrupted',finished=time.time(),error='后台工作进程已退出；原始文件保留，可重新提交新任务。')
            from .job_worker import mark_incomplete
            record['related_run_ids']=mark_incomplete(directory.parent.parent,directory/record['job_id'],'interrupted')
            atomic(directory/record['job_id']/'job.json',record)
    return None


def _start(root,directory):
    if _recover(directory):return
    if any(r['status']=='cleanup_failed' for r in _records(directory)):return
    if not any(r['status']=='queued' for r in _records(directory)):return
    with (directory/'dispatcher.log').open('ab') as log:
        process=subprocess.Popen([sys.executable,'-X','utf8','-m','wingdesignhub.job_worker',str(Path(root).resolve())],
            stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0,
            start_new_session=os.name!='nt')
    atomic(directory/'worker.json',identity(process.pid))


def submit_job(root,kind,project=None,parent_run_id=None,options=None):
    request=validate_request(kind,project,parent_run_id,options)
    from .tool_health import preflight
    checks=[]
    if kind=='compare':
        for p in request['project']['projects']:
            checks+=preflight(root,'coupled' if request['project'].get('analysis_model')=='coupled' else 'size',p,request['project'].get('analysis_options',{}))
    else:checks=preflight(root,kind,request['project'],request['options'])
    errors=[r for r in checks if r['severity']=='error']
    if errors:raise ValueError('；'.join(r['code']+'：'+r['message'] for r in errors))
    sources=code_identity()
    from .computation_identity import calculation
    calculation_id=calculation(root,kind)
    signature=hashlib.sha256(json.dumps({'request':request,'calculation':calculation_id},sort_keys=True).encode()).hexdigest()
    with locked(root) as directory:
        _recover(directory)
        for record in _records(directory):
            if record['signature']==signature and record['status'] in ACTIVE:
                _start(root,directory);return record
        record={'job_id':uuid4().hex,'kind':kind,'status':'queued','signature':signature,
                'source_hashes':sources,'calculation_identity':calculation_id,'preflight':checks,
                'created':time.time(),'name':(request.get('project') or {}).get('name',kind),
                'definition_sha256':hashlib.sha256(json.dumps(request,sort_keys=True).encode()).hexdigest()}
        work=directory/record['job_id'];atomic(work/'request.json',request);atomic(work/'job.json',record)
        _start(root,directory)
        return record


def list_jobs(root):
    with locked(root) as directory:
        _start(root,directory)
        return sorted(_records(directory),key=lambda r:r['created'],reverse=True)


def get_job(root,job_id):
    job_path(root,job_id)
    with locked(root) as directory:
        _start(root,directory)
        result=read(directory/job_id/'job.json')
    from .job_events import latest
    result['events']=latest(job_path(root,job_id))
    return result


def cancel_job(root,job_id):
    path=job_path(root,job_id)
    with locked(root):
        record=read(path/'job.json')
        if record['status']=='queued':
            record.update(status='cancelled',finished=time.time());atomic(path/'job.json',record)
        elif record['status'] in ('running','cancel_requested'):
            atomic(path/'cancel.json',{'requested':time.time()})
            record['status']='cancel_requested';atomic(path/'job.json',record)
    return record


def retry_job(root,job_id):
    old=get_job(root,job_id)
    if old['status'] in ACTIVE:return old
    request=read(job_path(root,job_id)/'request.json')
    return submit_job(root,**request)
