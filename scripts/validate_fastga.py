"""Fixed upstream task through the shared, audited FAST-GA worker."""
import sys
from pathlib import Path
from uuid import uuid4
from wingdesignhub.fastga_worker import evaluate_reference

root = Path(__file__).resolve().parents[1]
work = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else root/"runs"/("fastga_"+uuid4().hex)
result = evaluate_reference(work)
print({"status": result["status"], "passed": result["passed"], "outputs_kg": result["outputs_kg"]})
raise SystemExit(0 if result["passed"] else 1)
