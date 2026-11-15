"""Shared UI/CLI/Python static-wing service with inputs, logs and artifact hashes."""
from datetime import datetime,timezone
from pathlib import Path
import traceback
from uuid import uuid4
from . import __version__
from .shell_static import StaticWingCase,run_static_case
from .structure_service import generate_mesh
from .adapters import sha256,tool_paths
from .service import write_json


def run_wing_static(case,root):
    if isinstance(case,dict):case=StaticWingCase.from_dict(case)
    case.validate();root=Path(root).resolve();run_id=uuid4().hex
    work=root/'runs'/run_id;work.mkdir(parents=True)
    write_json(work/'input.json',case.to_dict());source=Path(__file__).parent
    r={'run_id':run_id,'version':__version__,'mode':'wing_static','status':'running',
       'started_utc':datetime.now(timezone.utc).isoformat(),'input_hash':sha256(work/'input.json'),
       'source_hashes':{p.relative_to(source).as_posix():sha256(p) for p in source.rglob('*.py')},
       'physical_validation_passed':False}
    write_json(work/'result.json',r)
    try:
        exe=tool_paths(root)['calculix']
        if not exe or not Path(exe).is_file():raise FileNotFoundError('请在工具设置配置 CalculiX 2.23')
        generate_mesh(case.mesh,work/'mesh')
        r['summary']=run_static_case(case,work/'mesh/wing.inp',exe,work/'static')
        r['status']=r['summary']['status']
    except Exception as exc:
        r.update(status='failed',error=str(exc))
        logs=[p for p in (work/'mesh/stdout.log',work/'static/solve/stdout.log') if p.exists()]
        if logs:r['diagnostic']='\n'.join(logs[-1].read_text(encoding='utf-8',errors='replace').splitlines()[-16:])
        (work/'error.log').write_text(traceback.format_exc(),encoding='utf-8')
    r['finished_utc']=datetime.now(timezone.utc).isoformat()
    r['artifact_hashes']={p.relative_to(work).as_posix():sha256(p) for p in work.rglob('*') if p.is_file() and p.name!='result.json'}
    write_json(work/'result.json',r);return r
