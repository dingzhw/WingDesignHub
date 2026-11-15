"""Reproduce same-configuration box bending/torsion comparison and refinement."""
from pathlib import Path
import sys
import json
from wingdesignhub.box_comparison import run_box_comparison
from wingdesignhub.adapters import tool_paths

if __name__=='__main__':
    root=Path(__file__).resolve().parents[1]
    r=run_box_comparison(tool_paths(root)['calculix'],Path(sys.argv[1]))
    print(json.dumps({'passed':r['passed'],'mesh_relative_differences':r['mesh_relative_differences']}))
    raise SystemExit(0 if r['passed'] else 1)
