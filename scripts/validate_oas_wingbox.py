"""Run the pinned official wingbox case through the common benchmark service."""
import json
from pathlib import Path
import sys
from uuid import uuid4
from wingdesignhub.oas_wingbox import run_benchmark

if __name__=='__main__':
    root=Path(__file__).resolve().parents[1]
    work=Path(sys.argv[1]).resolve() if len(sys.argv)>1 else root/'runs'/('oas_wingbox_'+uuid4().hex)
    result=run_benchmark(work);print(json.dumps(result,ensure_ascii=False,indent=2))
    raise SystemExit(0 if result['passed'] else 1)
