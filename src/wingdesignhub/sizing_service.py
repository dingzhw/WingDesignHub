"""Recorded overall sizing shared by UI, CLI and Python."""
from datetime import datetime,timezone
from pathlib import Path
from uuid import uuid4
import json,sys,traceback
from . import __version__
from .requirements import DesignProject,build_design_intent
from .adapters import execute,sha256
from .service import write_json


def run_sizing(project,root):
    p=DesignProject.from_dict(project) if isinstance(project,dict) else project;p.check_schema()
    root=Path(root).resolve();work=root/'runs'/uuid4().hex;work.mkdir(parents=True)
    write_json(work/'input.json',p.to_dict());source=Path(__file__).parent
    r={'run_id':work.name,'version':__version__,'mode':'overall_sizing','status':'running',
       'started_utc':datetime.now(timezone.utc).isoformat(),'definition_sha256':p.definition_hash(),
       'source_hashes':{f.relative_to(source).as_posix():sha256(f) for f in source.rglob('*.py')},
       'input_hash':sha256(work/'input.json'),'physical_validation_passed':False}
    write_json(work/'result.json',r)
    intent=build_design_intent(p)
    try:
        if intent['status']!='requirements_ready':
            r.update(status=intent['status'],summary=intent)
        else:
            execute([sys.executable,'-X','utf8','-m','wingdesignhub.sizing_worker',str(work)],work,timeout=240)
            r['summary']=json.loads((work/'summary.json').read_text(encoding='utf-8'));r['status']=r['summary']['status']
    except Exception as exc:
        r.update(status='failed',error=str(exc));(work/'error.log').write_text(traceback.format_exc(),encoding='utf-8')
    r['finished_utc']=datetime.now(timezone.utc).isoformat()
    r['artifact_hashes']={f.relative_to(work).as_posix():sha256(f) for f in work.rglob('*') if f.is_file() and f.name!='result.json'}
    write_json(work/'result.json',r);return r
