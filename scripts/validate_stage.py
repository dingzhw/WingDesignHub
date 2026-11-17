"""V0.2.0 software-stage evidence; professional acceptance remains a separate gate."""
from dataclasses import replace
from pathlib import Path
import sys
from wingdesignhub.requirements import DesignProject,WeightRequirement,MissionRequirement
from wingdesignhub.sizing_service import run_sizing
from wingdesignhub.design_comparison import variants
from wingdesignhub.comparison_service import run_comparison
from wingdesignhub.project_archive import build_bundle,save_bundle,load_saved,read_bundle
from wingdesignhub.design_service import run_fastga_reference
from wingdesignhub.fuel_validation import run_fuel_validation
from wingdesignhub.reference_cruise import run_public_cruise
from wingdesignhub.service import write_json,get_results
from wingdesignhub.adapters import sha256


def main(target):
    root=Path(__file__).resolve().parents[1];work=Path(target).resolve();work.mkdir(parents=True,exist_ok=False)
    missions={'range':MissionRequirement(),'endurance':MissionRequirement('endurance_only',None,14400.),
              'same_route':MissionRequirement('same_route',8e5,14400.),'loiter':MissionRequirement('transit_loiter',4e5,3600.)}
    weights={'solve':WeightRequirement(),'fixed':WeightRequirement('fixed',1400.),'upper_bound':WeightRequirement('upper_bound',1500.)}
    runs={};checks={};definitions={}
    for fuel in ('constant_bsfc','piper_economy_reference'):
        for wname,w in weights.items():
            for mname,m in missions.items():
                name=f'{fuel}_{wname}_{mname}';p=DesignProject();p=replace(p,name=name,weight=w,mission=m,sizing=replace(p.sizing,fuel_model=fuel)).confirmed()
                r=run_sizing(p,root);get_results(root,r['run_id']);write_json(work/(name+'.json'),r)
                runs[name]=r;definitions[name]=p
                s=r.get('summary',{});checks[name]=r['status']=='concept_checked_with_limits'
                if 'mission' in s:
                    checks[name+'_fuel_ledger']=abs(sum(s['mission']['block_fuel_by_method_kg'].values())-s['mission']['block_fuel_kg'])<1e-8
                print(name,r['run_id'],r['status'],flush=True)
    key='piper_economy_reference_solve_range';p=definitions[key];r=runs[key]
    data=build_bundle(p,root,r);(work/'complete-design.wdh').write_bytes(data)
    saved=save_bundle(data,work/'fresh_workspace');opened=load_saved(work/'fresh_workspace',saved['archive_id'])
    checks['save_reopen_exact']=opened['project']==p and opened['records'][0]==r
    replay=run_sizing(opened['project'],root);get_results(root,replay['run_id']);write_json(work/'replay.json',replay)
    checks['recompute_identical']=all(r['summary'][k]==replay['summary'][k] for k in ('design_mtow_kg','mission','geometry','power','weights','cg','checks'))
    req=variants(p,'sizing.aspect_ratio',[7.5,8.25,9.]);req=replace(req,projects=tuple(x.confirmed() for x in req.projects))
    comp=run_comparison(req,root);get_results(root,comp['run_id']);write_json(work/'comparison.json',comp)
    checks['three_designs']=comp['status']=='compared_with_limits'
    packed=build_bundle(req,root,comp);(work/'complete-comparison.wdh').write_bytes(packed)
    checks['comparison_reopen']=read_bundle(packed)['records'][0]==comp
    for name,q in [('fixed_excess',replace(p,weight=WeightRequirement('fixed',1000.))),
                   ('upper_excess',replace(p,weight=WeightRequirement('upper_bound',1000.))),
                   ('task_conflict',replace(p,mission=MissionRequirement('same_route',8e5,36000.)))]:
        q=q.confirmed();rr=run_sizing(q,root);get_results(root,rr['run_id']);write_json(work/(name+'.json'),rr);runs[name]=rr
        expected='out_of_domain' if name=='task_conflict' else 'constraints_not_met'
        checks[name]=rr['status']==expected and read_bundle(build_bundle(q,root,rr))['records'][0]['status']==expected
    fuel=run_fuel_validation(root);get_results(root,fuel['run_id']);write_json(work/'fuel_evidence.json',fuel)
    checks['heldout_only']=fuel['summary']['holdout_passed'] and not fuel['summary']['independent_validation_data_available']
    legacy=run_public_cruise(root);get_results(root,legacy['run_id']);write_json(work/'legacy_cruise.json',legacy)
    checks['historical_bias_preserved']=abs(legacy['summary']['relative_errors']['fuel']-.2654372125131581)<1e-12
    default=runs['constant_bsfc_solve_range']['summary'];checks['legacy_sizing_preserved']=abs(default['design_mtow_kg']-1229.4159528684945)<1e-8
    reference=run_fastga_reference(root);get_results(root,reference['run_id']);write_json(work/'fastga_reference.json',reference)
    checks['fastga_reference']=reference['status']=='executed_with_limits'
    summary={'software_stage_passed':all(checks.values()),'engineering_review':'pending_professional_review',
             'physical_validation_passed':False,'checks':checks,'runs':{k:v['run_id'] for k,v in runs.items()},
             'comparison_run':comp['run_id'],'replay_run':replay['run_id'],'fuel_run':fuel['run_id'],
             'legacy_cruise_run':legacy['run_id'],'fastga_reference_run':reference['run_id'],
             'confirmation_origin':'synthetic validation only, not engineering approval',
             'evidence_hashes':{p.name:sha256(p) for p in work.iterdir() if p.is_file()}}
    write_json(work/'summary.json',summary);return 0 if summary['software_stage_passed'] else 1


if __name__=='__main__':raise SystemExit(main(sys.argv[1]))
