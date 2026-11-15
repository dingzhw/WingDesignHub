"""Public synthetic square-section cantilever, compare with Euler–Bernoulli.

Uses the official-linked GE Windows 2.10 distribution for P0 only.
Later representative aircraft structures require a current-version baseline.
"""
import json
from pathlib import Path
import re
import sys
from uuid import uuid4
from wingdesignhub.adapters import execute, sha256

root = Path(__file__).resolve().parents[1]
executables = list((root/".runtime/calculix-2.10").rglob("ccx.exe"))
if len(executables) != 1:
    raise RuntimeError("本地 CalculiX 2.10 基准环境不存在")
work = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else root/"runs"/("calculix_" + uuid4().hex)
work.mkdir(parents=True, exist_ok=True)
L, E, side, P, ne = 2., 70e9, .1, 100., 20
last = 2*ne+1
lines = ["*HEADING", "WingDesignHub public synthetic cantilever SI", "*NODE"]
lines += [f"{i+1},{i*L/(2*ne)},0,0" for i in range(last)]
lines += ["*ELEMENT,TYPE=B32R,ELSET=BEAM"]
lines += [f"{i+1},{2*i+1},{2*i+2},{2*i+3}" for i in range(ne)]
lines += ["*NSET,NSET=TIP", str(last), "*MATERIAL,NAME=ALUMINUM", "*ELASTIC", f"{E},0.3",
          "*BEAM SECTION,ELSET=BEAM,MATERIAL=ALUMINUM,SECTION=RECT", f"{side},{side}", "0,0,1",
          "*BOUNDARY", "1,1,6", "*STEP", "*STATIC", "*CLOAD", f"{last},2,{P}",
          "*NODE PRINT,NSET=TIP", "U", "*NODE FILE", "U", "*END STEP"]
(work/"beam.inp").write_text("\n".join(lines)+"\n", encoding="ascii")
execute([str(executables[0]), "beam"], work, timeout=90)
data = (work/"beam.dat").read_text()
row = next(line.split() for line in data.splitlines() if re.match(rf"\s*{last}\s+[-+0-9.]", line))
tip = float(row[2]); exact = P*L**3/(3*E*(side**4/12))
result = {"solver": "CalculiX GE 2.10", "element": "B32R", "case": "square cantilever end load",
          "tip_displacement_m": tip, "analytical_tip_m": exact,
          "relative_error": abs(tip-exact)/abs(exact), "threshold": .02,
          "solver_sha256": sha256(executables[0]), "physical_validation_passed": False}
result["passed"] = result["relative_error"] < .02
(work/"summary.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
print(json.dumps(result, indent=2))
raise SystemExit(0 if result["passed"] else 1)
