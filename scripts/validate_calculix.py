"""Run the versioned CalculiX cantilever and mesh-refinement benchmark."""
import json
from pathlib import Path
import sys
from uuid import uuid4
from wingdesignhub.calculix_benchmark import run_benchmark

if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    work = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else root/"runs"/("calculix_"+uuid4().hex)
    result = run_benchmark(root, work)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["passed"] else 1)
