"""Reproduce V0.1.6 intent-mode matrix and the fixed public overall task."""
from dataclasses import replace
from pathlib import Path
import sys
from wingdesignhub.requirements import DesignProject, WeightRequirement, MissionRequirement
from wingdesignhub.design_service import prepare_design_project, run_fastga_reference
from wingdesignhub.service import get_results, write_json

root = Path(__file__).resolve().parents[1]
work = Path(sys.argv[1]).resolve() if len(sys.argv)>1 else root/'local/v016-design-validation'
work.mkdir(parents=True, exist_ok=False)
rows=[]
for mode in ('fixed', 'upper_bound', 'solve'):
    for kind in ('range_only', 'endurance_only', 'same_route', 'transit_loiter'):
        p = replace(DesignProject(), weight=WeightRequirement(mode, None if mode=='solve' else 1200.),
                    mission=MissionRequirement(kind, None if kind=='endurance_only' else 8e5,
                                               None if kind=='range_only' else 14400.)).confirmed()
        r = prepare_design_project(p, root)
        get_results(root, r['run_id'])
        rows.append({'mode':mode, 'mission':kind, 'run_id':r['run_id'], 'status':r['status'],
                     'definition_sha256':r['definition_sha256']})
        print(mode,kind,r['status'],flush=True)
r = run_fastga_reference(root)
get_results(root, r['run_id'])
out = {'intent_matrix':rows, 'confirmation_origin':'automated synthetic validation, not a user design approval',
       'reference_run_id':r['run_id'], 'reference_status':r['status'], 'reference_summary':r.get('summary'),
       'passed':all(x['status']=='requirements_ready' for x in rows) and r.get('summary',{}).get('passed') is True,
       'custom_design_solved':False}
write_json(work/'summary.json',out)
print('reference',r['run_id'],r['status'],flush=True)
raise SystemExit(0 if out['passed'] else 1)
