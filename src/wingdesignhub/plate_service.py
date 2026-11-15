"""Recorded plate eigenvalue service shared by UI and CLI."""
from datetime import datetime,timezone
from pathlib import Path
from uuid import uuid4
import traceback
from . import __version__
from .adapters import tool_paths,sha256
from .plate_buckling import PlateCase,run_plate
from .service import write_json


def run_plate_analysis(case,root):
    if isinstance(case,dict):case=PlateCase.from_dict(case)
    case.validate();root=Path(root).resolve();work=root/'runs'/uuid4().hex;work.mkdir(parents=True)
    write_json(work/'input.json',case.to_dict());source=Path(__file__).parent
    r={'run_id':work.name,'version':__version__,'mode':'plate_buckling','status':'running',
       'started_utc':datetime.now(timezone.utc).isoformat(),'input_hash':sha256(work/'input.json'),
       'source_hashes':{p.relative_to(source).as_posix():sha256(p) for p in source.rglob('*.py')},'physical_validation_passed':False}
    write_json(work/'result.json',r)
    try:
        exe=tool_paths(root)['calculix']
        if not exe or not Path(exe).is_file():raise FileNotFoundError('请配置 CalculiX 2.23')
        s=run_plate(case,exe,work/'plate');r['summary']=s
        r['status']='executed_with_limits' if s['first_factor']<1 else 'eigenvalue_computed'
    except Exception as exc:
        r.update(status='failed',error=str(exc));(work/'error.log').write_text(traceback.format_exc(),encoding='utf-8')
    r['finished_utc']=datetime.now(timezone.utc).isoformat()
    r['artifact_hashes']={p.relative_to(work).as_posix():sha256(p) for p in work.rglob('*') if p.is_file() and p.name!='result.json'}
    write_json(work/'result.json',r);return r
