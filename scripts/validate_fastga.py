"""Reproduce the installed FAST-GA tutorial in a new local run directory.

No upstream input is changed. This may take several minutes. The parent runner
must enforce a wall-time limit. Results are not equivalent to an independent test.
"""
import json
import os
import sys
import math
from importlib.metadata import version
from pathlib import Path
from uuid import uuid4
import fastga
import fastoad.api as oad
from wingdesignhub.adapters import sha256
from wingdesignhub.fastga_compat import compatibility, PROVIDER, SERVICE_FURNITURE_MASS
from wingdesignhub.fastga_diagnostics import collect_diagnostics, final_domain_checks

root = Path(__file__).resolve().parents[1]
work = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else root/"runs"/("fastga_" + uuid4().hex)
work.mkdir(parents=True, exist_ok=True)
os.chdir(work)
source = Path(fastga.__file__).parent/"notebooks/tutorial/data/beechcraft_76.xml"
config = work/"oad_process.yml"
with compatibility(), collect_diagnostics() as (diagnostics, python_warnings):
    oad.generate_configuration_file(config, distribution_name="fast-oad-cs23", sample_file_name="fastga.yml")
    # Explicit provider selection survives FAST-OAD configuration reloads.
    with config.open("a", encoding="utf-8") as stream:
        stream.write(f"\nsubmodels:\n  {SERVICE_FURNITURE_MASS}: {PROVIDER}\n")
    oad.generate_inputs(config, source)
    problem = oad.evaluate_problem(config)
    domain = final_domain_checks(problem)
    from wingdesignhub.fastga_compat import FurnitureMass
    if not any(isinstance(component, FurnitureMass) for component in problem.model.system_iter()):
        raise RuntimeError("FAST-GA 家具质量替换未生效")
values = {}
for name in ("data:weight:aircraft:MTOW", "data:weight:aircraft:OWE", "data:mission:sizing:fuel"):
    values[name] = float(problem.get_val(name, units="kg").item())
baseline = {"data:weight:aircraft:MTOW": 1710.197080992762,
            "data:weight:aircraft:OWE": 1081.0432731126027,
            "data:mission:sizing:fuel": 249.15380788015943}
deviations = {key: abs(value-baseline[key]) for key, value in values.items()}
solver = problem.model.aircraft_sizing.nonlinear_solver
norm = float(solver._iter_get_norm())
norm0 = float(solver._norm0)
converged = math.isfinite(norm) and (norm <= solver.options["atol"] or norm/norm0 <= solver.options["rtol"])
reference_hash_matches = sha256(source) == "fa81a18c904b5fe6925806d0b647ac99c24e68e9e25889c882b980ab6b7ed3ff"
passed = reference_hash_matches and converged and all(math.isfinite(v) and v <= 1e-5 for v in deviations.values())
limits = any(not row["within_range"] for row in domain) or bool(diagnostics)
result = {"status": ("executed_with_limits" if limits else "executed") if passed else "failed",
          "passed": passed, "source_sha256": sha256(source), "outputs_kg": values,
          "reference_hash_matches": reference_hash_matches,
          "baseline_difference_kg": deviations, "baseline_tolerance_kg": 1e-5,
          "convergence": {"converged": converged, "iterations": solver._iter_count,
                          "residual_norm": norm, "initial_norm": norm0, "rtol": solver.options["rtol"],
                          "atol": solver.options["atol"]},
          "versions": {name: version(name) for name in ("fast-oad-cs23", "fast-oad-core", "openmdao", "pandas", "numpy")},
          "compatibility": ["furniture_identity_derivative_1", "mission_csv_dataframe_map"],
          "final_domain_checks": domain, "domain_check_scope": "observed correlations only",
          "diagnostics": diagnostics, "python_warnings": python_warnings,
          "physical_validation_passed": False, "reference": "FAST-GA 1.4.0 bundled tutorial"}
(work/"summary.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
print(json.dumps(result, indent=2))
raise SystemExit(0 if passed else 1)
