"""Isolated OpenVSP mesh service shared by the UI, CLI and benchmarks."""
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import traceback
from uuid import uuid4
from . import __version__
from .adapters import execute, sha256
from .fea_mesh import StructureMeshCase
from .service import write_json


def generate_mesh(case, directory):
    case.validate()
    directory = Path(directory); directory.mkdir(parents=True, exist_ok=False)
    write_json(directory/"input.json",case.to_dict())
    execute([sys.executable,"-X","utf8","-m","wingdesignhub.vsp_structure_worker"],directory,timeout=180)
    return json.loads((directory/"summary.json").read_text(encoding="utf-8"))


def run_structure_mesh(case, root):
    if isinstance(case,dict):
        case = StructureMeshCase.from_dict(case)
    case.validate()
    run_id = uuid4().hex; directory = Path(root).resolve()/"runs"/run_id
    directory.mkdir(parents=True)
    write_json(directory/"input.json",case.to_dict())
    source = Path(__file__).parent
    result = {"run_id": run_id, "version": __version__, "mode": "structure_mesh", "status": "running",
              "input_hash": sha256(directory/"input.json"),
              "started_utc": datetime.now(timezone.utc).isoformat(), "physical_validation_passed": False,
              "source_hashes": {p.relative_to(source).as_posix():sha256(p) for p in source.rglob("*.py")}}
    write_json(directory/"result.json",result)
    try:
        result["summary"] = generate_mesh(case,directory/"mesh")
        result["status"] = "mesh_checked"
    except Exception as exc:
        result.update(status="failed",error=str(exc))
        log = directory/"mesh/stdout.log"
        if log.exists():
            result["diagnostic"] = "\n".join(log.read_text(encoding="utf-8",errors="replace").splitlines()[-12:])
        (directory/"error.log").write_text(traceback.format_exc(),encoding="utf-8")
    result["finished_utc"] = datetime.now(timezone.utc).isoformat()
    result["artifact_hashes"] = {p.relative_to(directory).as_posix():sha256(p)
                                 for p in directory.rglob("*") if p.is_file() and p.name!="result.json"}
    write_json(directory/"result.json",result)
    return result
