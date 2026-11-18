"""Recorded downstream geometry service; upstream calculations stay immutable."""
from dataclasses import asdict
from datetime import datetime,timezone
from pathlib import Path
from importlib.metadata import version,PackageNotFoundError
from uuid import uuid4
import json
import sys
import traceback
from . import __version__
from .adapters import execute,sha256
from .requirements import DesignProject
from .service import get_results,write_json
from .aircraft_geometry import build_geometry_contract,GeometryOptions


def source_hashes():
    source=Path(__file__).parent
    return {p.relative_to(source).as_posix():sha256(p) for p in source.rglob('*.py')}


def run_aircraft_geometry(project,root,sizing_run_id,options=None):
    p=DesignProject.from_dict(project) if isinstance(project,dict) else project;p.check_schema()
    options=GeometryOptions(**options) if isinstance(options,dict) else (options or GeometryOptions())
    options.validate();root=Path(root).resolve();parent=get_results(root,sizing_run_id)
    from .computation_identity import compatible
    if parent.get('version')!=__version__ or not compatible(parent,root):
        raise ValueError('总体结果的软件或模型已变更，请在当前版本重新运行总体设计')
    for package,recorded in parent.get('summary',{}).get('versions',{}).items():
        try:matches=version(package)==recorded
        except PackageNotFoundError:matches=False
        if not matches:raise ValueError('总体求解依赖已变更，请重新运行总体设计：'+package)
    if parent['run_id']!=sizing_run_id:raise ValueError('总体运行编号不一致')
    parent_work=root/'runs'/sizing_run_id
    if sha256(parent_work/'input.json')!=parent['input_hash'] or json.loads((parent_work/'summary.json').read_text('utf-8'))!=parent.get('summary'):
        raise ValueError('总体运行输入或摘要不一致')
    # Reconcile the actual source input; confirmation in a newly supplied object is insufficient.
    actual=DesignProject.from_dict(json.loads((parent_work/'input.json').read_text('utf-8')))
    if actual.definition_hash()!=p.definition_hash():raise ValueError('总体输入与当前需求不一致')
    contract=build_geometry_contract(p,parent,options)
    work=root/'runs'/uuid4().hex;work.mkdir(parents=True)
    write_json(work/'input.json',p.to_dict());write_json(work/'geometry_contract.json',contract)
    (work/'parent_result.json').write_bytes((parent_work/'result.json').read_bytes())
    record={'run_id':work.name,'version':__version__,'mode':'aircraft_geometry','status':'running',
            'started_utc':datetime.now(timezone.utc).isoformat(),'definition_sha256':p.definition_hash(),
            'input_hash':sha256(work/'input.json'),'source_hashes':source_hashes(),
            'parent_run_id':sizing_run_id,'parent_result_sha256':sha256(work/'parent_result.json'),
            'options':asdict(options),'physical_validation_passed':False}
    write_json(work/'result.json',record)
    try:
        execute([sys.executable,'-X','utf8','-m','wingdesignhub.aircraft_vsp_worker',str(work)],work,timeout=180)
        record['summary']=json.loads((work/'summary.json').read_text('utf-8'))
        record['status']=record['summary']['status']
    except Exception as exc:
        record.update(status='failed',error=str(exc));(work/'error.log').write_text(traceback.format_exc(),encoding='utf-8')
        if (work/'summary.json').is_file():record['summary']=json.loads((work/'summary.json').read_text('utf-8'))
    record['finished_utc']=datetime.now(timezone.utc).isoformat()
    record['artifact_hashes']={f.relative_to(work).as_posix():sha256(f) for f in work.rglob('*') if f.is_file() and f.name!='result.json'}
    write_json(work/'result.json',record);return record
