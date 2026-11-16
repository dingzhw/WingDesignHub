"""An immutable aerodynamic child run of a checked OpenVSP geometry run."""
from datetime import datetime,timezone
from pathlib import Path
from uuid import uuid4
import json
import traceback
from . import __version__
from .adapters import sha256,tool_paths
from .requirements import DesignProject
from .service import get_results,write_json
from .geometry_service import source_hashes
from .aircraft_aero import make_contract
from .avl_aircraft import solve


def run_aircraft_aero(project,root,geometry_run_id,options=None):
    p=DesignProject.from_dict(project) if isinstance(project,dict) else project;p.check_schema()
    root=Path(root).resolve();parent=get_results(root,geometry_run_id);pw=root/'runs'/geometry_run_id
    if parent.get('run_id')!=geometry_run_id or parent.get('mode')!='aircraft_geometry' or parent.get('status')!='geometry_checked_with_limits':
        raise ValueError('气动分析需要已通过检查的全机几何运行')
    if parent.get('version')!=__version__ or parent.get('source_hashes')!=source_hashes():
        raise ValueError('模型或版本已变更，请重新运行总体和全机几何')
    if p.confirmation_sha256!=p.definition_hash() or parent['definition_sha256']!=p.definition_hash():
        raise ValueError('需求或确认状态已变更，请重新计算总体和几何')
    sizing=get_results(root,parent['parent_run_id']);sw=root/'runs'/sizing['run_id']
    if (json.loads((pw/'parent_result.json').read_text('utf-8'))!=sizing or
        sha256(pw/'parent_result.json')!=parent['parent_result_sha256'] or
        sha256(pw/'input.json')!=parent['input_hash'] or
        DesignProject.from_dict(json.loads((pw/'input.json').read_text('utf-8'))).definition_hash()!=p.definition_hash()):
        raise ValueError('几何来源记录不一致')
    interface=json.loads((pw/'aerodynamic_geometry.json').read_text('utf-8'))
    gc=json.loads((pw/'geometry_contract.json').read_text('utf-8'))
    if (interface['source_run_id']!=geometry_run_id or interface['parent_run_id']!=sizing['run_id'] or
        interface['geometry_file_sha256']!=sha256(pw/'aircraft.vsp3') or
        interface['degen_file_sha256']!=sha256(pw/'airframe_DegenGeom.csv') or
        interface['surfaces']!=gc['lifting_surfaces'] or interface['references']!=gc['references'] or
        interface['references']!=parent['summary']['references'] or
        json.loads((sw/'summary.json').read_text('utf-8'))!=sizing['summary']):
        raise ValueError('气动接口与已验证几何不一致')
    contract=make_contract(interface,p,sizing['summary'],options)
    work=root/'runs'/uuid4().hex;work.mkdir(parents=True)
    write_json(work/'input.json',p.to_dict());write_json(work/'aero_contract.json',contract)
    for source,name in [(pw/'result.json','parent_result.json'),(pw/'aerodynamic_geometry.json','aerodynamic_geometry.json')]:
        (work/name).write_bytes(source.read_bytes())
    record={'run_id':work.name,'version':__version__,'mode':'aircraft_aero','status':'running',
            'started_utc':datetime.now(timezone.utc).isoformat(),'definition_sha256':p.definition_hash(),
            'input_hash':sha256(work/'input.json'),'source_hashes':source_hashes(),'parent_run_id':geometry_run_id,
            'sizing_run_id':sizing['run_id'],'parent_result_sha256':sha256(work/'parent_result.json'),
            'options':contract['options'],'physical_validation_passed':False}
    write_json(work/'result.json',record)
    try:
        record['summary']=solve(contract,tool_paths(root)['avl'],work)
        record['summary']['sizing_status']=sizing['status']
        write_json(work/'summary.json',record['summary']);record['status']=record['summary']['status']
        from .aero_report import write_report
        write_report(work,contract,record)
    except Exception as exc:
        record.update(status='failed',error=str(exc));(work/'error.log').write_text(traceback.format_exc(),encoding='utf-8')
    record['finished_utc']=datetime.now(timezone.utc).isoformat()
    record['artifact_hashes']={f.relative_to(work).as_posix():sha256(f) for f in work.rglob('*') if f.is_file() and f.name!='result.json'}
    write_json(work/'result.json',record);return record
