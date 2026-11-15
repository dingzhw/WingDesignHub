"""Analytical and native-reference-scaling checks for representative plate buckling."""
from pathlib import Path
import json
import sys
from wingdesignhub.adapters import tool_paths
from wingdesignhub.structural_sensitivity import plate_validation

if __name__=='__main__':
    root=Path(__file__).resolve().parents[1];work=Path(sys.argv[1]).resolve()
    r=plate_validation(tool_paths(root)['calculix'],work)
    print(json.dumps(r['checks'],indent=2));raise SystemExit(0 if r['passed'] else 1)
