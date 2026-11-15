"""V0.1.8 end-to-end comparisons, causal propagation and public spot check."""
from dataclasses import replace
from pathlib import Path
import sys
from wingdesignhub.requirements import DesignProject,MissionRequirement,WeightRequirement
from wingdesignhub.comparison_ui import variants
from wingdesignhub.comparison_service import run_comparison,compare_sizing_runs
from wingdesignhub.reference_cruise import run_public_cruise
from wingdesignhub.service import get_results,write_json
from wingdesignhub.adapters import sha256


def main(path):
    root=Path(__file__).resolve().parents[1];work=Path(path).resolve();work.mkdir(parents=True,exist_ok=False)
    base=DesignProject();cases=[
        ('aspect_ratio',base,'sizing.aspect_ratio',[7.5,8.25,9.]),
        ('payload',base,'payload_kg',[350.,400.,450.]),
        ('range',base,'mission.range_m',[8e5,1e6,1.2e6]),
        ('endurance',replace(base,mission=MissionRequirement('endurance_only',None,10800.)),'mission.endurance_s',[10800.,14400.,18000.]),
        ('loiter',replace(base,mission=MissionRequirement('transit_loiter',4e5,1800.)),'mission.endurance_s',[1800.,3600.,7200.]),
        ('fixed_budget',replace(base,weight=WeightRequirement('fixed',1400.)),'payload_kg',[350.,450.,600.]),
        ('same_route_conflict',replace(base,mission=MissionRequirement('same_route',8e5,12600.)),'mission.endurance_s',[12600.,14400.,36000.])]
    results={};checks={}
    for name,p,axis,values in cases:
        req=variants(p,axis,values);req=replace(req,projects=tuple(p.confirmed() for p in req.projects))
        record=run_comparison(req,root);get_results(root,record['run_id'])
        results[name]=record;write_json(work/(name+'.json'),record)
        print(name,record['run_id'],record['status'],record.get('error',''),flush=True)
        expected='comparison_incomplete' if name in ('fixed_budget','same_route_conflict') else 'compared_with_limits'
        checks[name+'_status']=record['status']==expected
        if 'summary' not in record:continue
        cards=record['summary']['cards']
        if name in ('payload','range','endurance','loiter'):
            keys=('mtow_kg','owe_kg','block_fuel_kg','power_kw','area_m2','span_m')
            checks[name+'_propagation']=all(b['metrics'][key]>a['metrics'][key] for a,b in zip(cards,cards[1:]) for key in keys)
        if name=='fixed_budget':
            checks['fixed_mass_preserved']=all(c['metrics']['mtow_kg']==1400. for c in cards)
            checks['fixed_overload']=cards[-1]['status']=='constraints_not_met' and cards[-1]['margins']['mass_budget_kg']<0
        if name=='same_route_conflict':
            checks['task_conflict_not_success']=cards[-1]['status']=='out_of_domain' and cards[-1]['metrics']['mtow_kg'] is None
    if results['aspect_ratio']['status']=='compared_with_limits':
        rebuilt=compare_sizing_runs(root,results['aspect_ratio']['child_runs'])
        get_results(root,rebuilt['run_id']);checks['archive_replay']=rebuilt['summary']==results['aspect_ratio']['summary']
    public=run_public_cruise(root);get_results(root,public['run_id']);write_json(work/'public_cruise.json',public)
    checks['public_condition_and_diagnostic']=abs(public['summary']['numerical_power_residual_w'])<1e-7 and not public['summary']['coefficients_fitted'] and public['status']=='model_discrepancy'
    summary={'passed':all(checks.values()),'checks':checks,
             'comparison_runs':{name:{'run_id':r['run_id'],'status':r['status'],'summary':r.get('summary')} for name,r in results.items()},
             'public_check':public,'confirmation_origin':'synthetic validation, not a user design approval',
             'evidence_hashes':{p.name:sha256(p) for p in work.glob('*.json')}}
    write_json(work/'summary.json',summary);return 0 if summary['passed'] else 1


if __name__=='__main__':raise SystemExit(main(sys.argv[1]))
