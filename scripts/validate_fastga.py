"""Reproduce the installed FAST-GA tutorial in a new local run directory.

No upstream input is changed. This may take several minutes. The parent runner
must enforce a wall-time limit. Results are not equivalent to an independent test.
"""
import json
import os
import sys
from pathlib import Path
from uuid import uuid4
import fastga
import fastoad.api as oad
from wingdesignhub.adapters import sha256

root = Path(__file__).resolve().parents[1]
work = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else root/"runs"/("fastga_" + uuid4().hex)
work.mkdir(parents=True, exist_ok=True)
os.chdir(work)
source = Path(fastga.__file__).parent/"notebooks/tutorial/data/beechcraft_76.xml"
config = work/"oad_process.yml"
oad.generate_configuration_file(config, distribution_name="fast-oad-cs23", sample_file_name="fastga.yml")
oad.generate_inputs(config, source)
problem = oad.evaluate_problem(config)
values = {}
for name in ("data:weight:aircraft:MTOW", "data:weight:aircraft:OWE", "data:mission:sizing:fuel"):
    values[name] = float(problem.get_val(name, units="kg").item())
result = {"status": "executed", "source_sha256": sha256(source), "outputs_kg": values,
          "physical_validation_passed": False, "reference": "FAST-GA 1.4.0 bundled tutorial"}
(work/"summary.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
print(json.dumps(result, indent=2))
