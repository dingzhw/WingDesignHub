"""Run S6 analytics, conservative wing loads and static mesh/linearity checks."""
from pathlib import Path
import json
import sys
from uuid import uuid4
from wingdesignhub.shell_validation import run_benchmark

if __name__=='__main__':
    root=Path(__file__).resolve().parents[1]
    work=Path(sys.argv[1]).resolve() if len(sys.argv)>1 else root/'runs'/('shell_static_'+uuid4().hex)
    print(work,flush=True);r=run_benchmark(root,work)
    print(json.dumps({'status':r['status'],'mesh_differences':r['relative_mesh_differences'],
                      'load_ratios':r['load_ratios'],'beam_errors':[b['tip_relative_error'] for b in r['plate_beams']]},indent=2))
    raise SystemExit(0 if r['passed'] else 1)
