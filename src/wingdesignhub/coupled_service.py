"""Recorded propulsion-coupled overall service. Prior results are seeds, not new evidence."""
from pathlib import Path
from dataclasses import asdict
from datetime import datetime,timezone
from uuid import uuid4
import json,sys,traceback
from . import __version__
from .requirements import DesignProject,build_design_intent
from .propulsion_feedback import CoupledOptions
from .geometry_service import source_hashes
from .service import get_results,write_json
from .adapters import execute,sha256
from .feedback_evidence import pack_native


def run_coupled(project,root,seed_run_id,options=None):
    p=DesignProject.from_dict(project) if isinstance(project,dict) else project;p.check_schema()
    options=CoupledOptions.from_dict(options) if isinstance(options,dict) else options or CoupledOptions();options.validate()
    root=Path(root).resolve();parent=get_results(root,seed_run_id);pw=root/'runs'/seed_run_id
    if parent.get('run_id')!=seed_run_id or parent.get('mode') not in ('overall_sizing','overall_feedback') or not parent.get('summary',{}).get('converged'):
        raise ValueError('推进闭环需要已收敛的初始总体或气动反馈方案作为初值')
    if build_design_intent(p)['status']!='requirements_ready' or parent['definition_sha256']!=p.definition_hash():
        raise ValueError('需求已改变或尚未确认，请先运行当前总体方案')
    if (DesignProject.from_dict(json.loads((pw/'input.json').read_text('utf-8'))).definition_hash()!=p.definition_hash() or
        json.loads((pw/'summary.json').read_text('utf-8'))!=parent['summary']):raise ValueError('来源输入或摘要不一致')
    work=root/'runs'/uuid4().hex;work.mkdir(parents=True)
    write_json(work/'input.json',p.to_dict());write_json(work/'options.json',asdict(options))
    (work/'parent_result.json').write_bytes((pw/'result.json').read_bytes())
    record={'run_id':work.name,'version':__version__,'mode':'overall_propulsion','status':'running',
        'started_utc':datetime.now(timezone.utc).isoformat(),'definition_sha256':p.definition_hash(),'input_hash':sha256(work/'input.json'),
        'source_hashes':source_hashes(),'parent_run_id':seed_run_id,'parent_result_sha256':sha256(work/'parent_result.json'),
        'options':asdict(options),'physical_validation_passed':False,
        'seed_role':'initial values and historical comparison only; native geometry/aerodynamics rebuilt with current code'}
    write_json(work/'result.json',record)
    try:
        execute([sys.executable,'-X','utf8','-m','wingdesignhub.coupled_worker',str(work)],work,timeout=10800)
        record['summary']=json.loads((work/'summary.json').read_text('utf-8'));record['status']=record['summary']['status']
    except Exception as exc:
        record.update(status='failed',error=str(exc))
        if (work/'failure.json').is_file():record.update(json.loads((work/'failure.json').read_text('utf-8')))
        if not (work/'error.log').exists():(work/'error.log').write_text(traceback.format_exc(),encoding='utf-8')
    pack_native(work)
    from .coupled_report import write_report
    write_report(p,record,work)
    record['finished_utc']=datetime.now(timezone.utc).isoformat()
    record['artifact_hashes']={f.relative_to(work).as_posix():sha256(f) for f in work.rglob('*')
        if f.is_file() and f!=work/'result.json' and not f.is_relative_to(work/'native')}
    write_json(work/'result.json',record);return record
