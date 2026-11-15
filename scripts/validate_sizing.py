"""V0.1.7 native matrix, sensitivity and unchanged public reference regression.

Run with the project interpreter. All confirmations below are synthetic tests.
Full evidence stays in the user-selected local directory and isolated runs.
"""
from dataclasses import replace
from pathlib import Path
import sys
from wingdesignhub.requirements import DesignProject,WeightRequirement,MissionRequirement
from wingdesignhub.fastga_mass import FastGAMassModel
from wingdesignhub.sizing import solve_design
from wingdesignhub.sizing_service import run_sizing
from wingdesignhub.design_service import run_fastga_reference
from wingdesignhub.service import write_json,get_results
from wingdesignhub.adapters import sha256


def main(work):
    root=Path(__file__).resolve().parents[1];work=Path(work).resolve();work.mkdir(parents=True,exist_ok=False)
    p=DesignProject().confirmed();rows=[];checks={}
    tasks=[('range_only',8e5,None),('endurance_only',None,14400.),('same_route',8e5,14400.),('transit_loiter',4e5,3600.)]
    with FastGAMassModel() as model:
        for mode,value in [('fixed',1400.),('upper_bound',1500.),('solve',None)]:
            for kind,distance,duration in tasks:
                q=replace(p,weight=WeightRequirement(mode,value),mission=MissionRequirement(kind,distance,duration)).confirmed()
                r=solve_design(q,model);name=mode+'-'+kind
                write_json(work/(name+'.json'),{'input':q.to_dict(),'summary':r})
                rows.append({'case':name,'status':r['status'],'mtow_kg':r.get('design_mtow_kg'),
                             'iterations':len(r['iterations']),'checks':r.get('checks')})
                print(name,r['status'],r.get('design_mtow_kg'),flush=True)
        base=solve_design(p,model);fine=solve_design(p,model,dt=15)
        sensitivity={}
        for name,q in [('payload400',replace(p,payload_kg=400)),('range1000km',replace(p,mission=MissionRequirement('range_only',1e6)))]:
            r=solve_design(q.confirmed(),model);sensitivity[name]=r
            checks[name]=r['status']=='concept_checked_with_limits' and all([
                r['design_mtow_kg']>base['design_mtow_kg'],r['geometry']['wing_area_m2']>base['geometry']['wing_area_m2'],
                r['power']['installed_power_w']>base['power']['installed_power_w'],r['mission']['block_fuel_kg']>base['mission']['block_fuel_kg']])
        rejected={}
        for mode in ['fixed','upper_bound']:
            rejected[mode]=solve_design(replace(p,weight=WeightRequirement(mode,1000.)).confirmed(),model)
        rejected['same_route_too_long']=solve_design(replace(p,mission=MissionRequirement('same_route',8e5,36000.)).confirmed(),model)
        rejected['iteration_limit']=solve_design(p,model,max_iterations=1)
        step_errors={'mtow_relative':abs(fine['design_mtow_kg']/base['design_mtow_kg']-1),
                     'fuel_relative':abs(fine['mission']['block_fuel_kg']/base['mission']['block_fuel_kg']-1)}
        checks.update(matrix=all(r['status']=='concept_checked_with_limits' for r in rows),
                      step=max(step_errors.values())<.001,
                      infeasible_weight=all(rejected[k]['status']=='constraints_not_met' for k in ('fixed','upper_bound')),
                      conflict=rejected['same_route_too_long']['status']=='out_of_domain',
                      not_converged=rejected['iteration_limit']['status']=='not_converged')
        write_json(work/'sensitivity.json',{'base':base,'refined':fine,'variants':sensitivity,'rejected':rejected})
        write_json(work/'native_interface.json',model.audit)
    service=run_sizing(p,root);get_results(root,service['run_id'])
    checks['isolated_service']=service['status']=='concept_checked_with_limits'
    print('service',service['run_id'],service['status'],flush=True)
    reference=run_fastga_reference(root);get_results(root,reference['run_id'])
    checks['public_reference']=reference.get('summary',{}).get('passed') is True
    print('reference',reference['run_id'],reference['status'],flush=True)
    summary={'matrix':rows,'step_errors':step_errors,'checks':checks,'passed':all(checks.values()),
             'service_run_id':service['run_id'],'reference_run_id':reference['run_id'],
             'service_summary':service.get('summary'),'reference_summary':reference.get('summary'),
             'confirmation_origin':'synthetic validation, not user aircraft approval',
             'evidence_hashes':{f.name:sha256(f) for f in work.glob('*.json')}}
    write_json(work/'summary.json',summary)
    return 0 if summary['passed'] else 1


if __name__=='__main__':raise SystemExit(main(sys.argv[1]))
