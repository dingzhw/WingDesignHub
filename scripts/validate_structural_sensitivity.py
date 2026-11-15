"""Same-aircraft mapping/support sensitivity and controlling-panel diagnosis."""
from pathlib import Path
import json
import sys
from wingdesignhub.structural_sensitivity import run_sensitivity

if __name__=='__main__':
    root=Path(__file__).resolve().parents[1];work=Path(sys.argv[1]).resolve()
    r=run_sensitivity(root,work)
    print(json.dumps(r['checks'],indent=2));raise SystemExit(0 if r['passed'] else 1)
