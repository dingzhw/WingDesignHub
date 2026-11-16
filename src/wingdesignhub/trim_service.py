"""Audited longitudinal trim child of an immutable checked geometry."""
from datetime import datetime, timezone
from uuid import uuid4
import traceback
from . import __version__
from .adapters import sha256, tool_paths
from .aero_service import checked_geometry_source
from .geometry_service import source_hashes
from .aircraft_trim import make_trim_contract, solve_trim
from .service import write_json


def run_aircraft_trim(project,root,geometry_run_id,options=None):
    p,root,parent,pw,sizing,interface=checked_geometry_source(project,root,geometry_run_id)
    contract=make_trim_contract(interface,p,sizing['summary'],options)
    work=root/'runs'/uuid4().hex;work.mkdir(parents=True)
    write_json(work/'input.json',p.to_dict());write_json(work/'trim_contract.json',contract)
    for source,name in [(pw/'result.json','parent_result.json'),(pw/'aerodynamic_geometry.json','aerodynamic_geometry.json'),
                        (root/'runs'/sizing['run_id']/'summary.json','sizing_summary.json')]:
        (work/name).write_bytes(source.read_bytes())
    record={'run_id':work.name,'version':__version__,'mode':'aircraft_trim','status':'running',
        'started_utc':datetime.now(timezone.utc).isoformat(),'definition_sha256':p.definition_hash(),
        'input_hash':sha256(work/'input.json'),'source_hashes':source_hashes(),'parent_run_id':geometry_run_id,
        'sizing_run_id':sizing['run_id'],'parent_result_sha256':sha256(work/'parent_result.json'),
        'options':contract['trim_options'],'physical_validation_passed':False}
    write_json(work/'result.json',record)
    try:
        record['summary']=solve_trim(contract,tool_paths(root)['avl'],work)
        record['summary']['sizing_status']=sizing['status'];record['status']=record['summary']['status']
        write_json(work/'summary.json',record['summary'])
        from .trim_report import write_report
        write_report(work,contract,record)
    except Exception as exc:
        record.update(status='failed',error=str(exc));(work/'error.log').write_text(traceback.format_exc(),encoding='utf-8')
    record['finished_utc']=datetime.now(timezone.utc).isoformat()
    record['artifact_hashes']={f.relative_to(work).as_posix():sha256(f) for f in work.rglob('*') if f.is_file() and f.name!='result.json'}
    write_json(work/'result.json',record);return record
