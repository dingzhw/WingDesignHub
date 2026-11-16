"""Recorded drag child of a checked, immutable trim and geometry chain."""
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
import json
import traceback
from . import __version__
from .adapters import sha256, tool_paths
from .aero_service import checked_geometry_source
from .aircraft_drag import make_drag_contract, solve_drag
from .geometry_service import source_hashes
from .service import get_results, write_json
from .xfoil_polars import PolarError


def run_aircraft_drag(project, root, trim_run_id, options=None):
    root=Path(root).resolve();trim=get_results(root,trim_run_id);tw=root/'runs'/trim_run_id
    if trim.get('run_id')!=trim_run_id or trim.get('mode')!='aircraft_trim':raise ValueError('需要配平运行编号')
    p,root,geometry,gw,sizing,interface=checked_geometry_source(project,root,trim['parent_run_id'])
    if trim.get('version')!=__version__ or trim.get('source_hashes')!=source_hashes():raise ValueError('配平模型版本已变更，请重新计算')
    if (trim['definition_sha256']!=p.definition_hash() or trim['sizing_run_id']!=sizing['run_id'] or
        json.loads((tw/'parent_result.json').read_text('utf-8'))!=geometry or sha256(tw/'parent_result.json')!=trim['parent_result_sha256']):
        raise ValueError('配平来源与当前几何或需求不一致')
    final=json.loads((tw/'final_aero_contract.json').read_text('utf-8')) if trim['status']=='trim_checked_with_limits' else {}
    contract=make_drag_contract(trim,final,options)
    work=root/'runs'/uuid4().hex;work.mkdir(parents=True)
    write_json(work/'input.json',p.to_dict());write_json(work/'drag_contract.json',contract)
    for source,name in [(tw/'result.json','parent_result.json'),(tw/'final_aero_contract.json','final_aero_contract.json'),
                        (tw/'strip_loads.json','trim_strip_loads.json'),(gw/'aircraft.vsp3','aircraft.vsp3'),
                        (gw/'geometry_contract.json','geometry_contract.json')]:
        (work/name).write_bytes(source.read_bytes())
    record={'run_id':work.name,'version':__version__,'mode':'aircraft_drag','status':'running',
            'started_utc':datetime.now(timezone.utc).isoformat(),'definition_sha256':p.definition_hash(),
            'input_hash':sha256(work/'input.json'),'source_hashes':source_hashes(),'parent_run_id':trim_run_id,
            'geometry_run_id':geometry['run_id'],'sizing_run_id':sizing['run_id'],
            'parent_result_sha256':sha256(work/'parent_result.json'),'options':contract['options'],'physical_validation_passed':False}
    write_json(work/'result.json',record)
    try:
        record['summary']=solve_drag(contract,work,root,tool_paths(root)['xfoil'])
        record['summary']['sizing_status']=sizing['status'];record['status']=record['summary']['status']
    except Exception as exc:
        record.update(status=exc.status if isinstance(exc,PolarError) else 'failed',error=str(exc),
                      diagnostic_context=exc.context if isinstance(exc,PolarError) else {})
        (work/'error.log').write_text(traceback.format_exc(),encoding='utf-8')
    if 'summary' in record:write_json(work/'summary.json',record['summary'])
    from .drag_report import write_report
    write_report(work,contract,record)
    record['finished_utc']=datetime.now(timezone.utc).isoformat()
    record['artifact_hashes']={f.relative_to(work).as_posix():sha256(f) for f in work.rglob('*') if f.is_file() and f.name!='result.json'}
    write_json(work/'result.json',record);return record
