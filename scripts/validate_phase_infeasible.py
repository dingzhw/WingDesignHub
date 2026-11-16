"""Real infeasible designs and domain errors, with no fallback to initial sizing."""
from pathlib import Path
from dataclasses import replace,asdict
import json,sys,shutil
from wingdesignhub import __version__
from wingdesignhub.requirements import DesignProject,WeightRequirement
from wingdesignhub.sizing_service import run_sizing
from wingdesignhub.coupled_service import run_coupled
from wingdesignhub.propulsion_feedback import CoupledOptions
from wingdesignhub.design_cards import make_card,card_html
from wingdesignhub.service import get_results,write_json
from wingdesignhub.geometry_service import source_hashes
from wingdesignhub.project_archive import build_bundle,read_bundle


def main(target,resume=False):
    repo=Path(__file__).resolve().parents[1];work=Path(target).resolve();root=work/'workspace'
    if not resume:work.mkdir(parents=True,exist_ok=False)
    (root/'local').mkdir(parents=True,exist_ok=True)
    for name in ('tools.json','propulsion-tools.json'):
        if not (root/'local'/name).exists() and (repo/'local'/name).exists():shutil.copy2(repo/'local'/name,root/'local'/name)
    checkpoint=work/'checkpoint.json'
    state=json.loads(checkpoint.read_text('utf-8')) if resume else {'source_hashes':source_hashes(),'cases':{}}
    if state['source_hashes']!=source_hashes():raise ValueError('负例运行源码已变化')
    p=replace(DesignProject(),name='规定1100kg的质量预算负例',weight=WeightRequirement('fixed',1100.)).confirmed()
    cases=[('fixed_budget',p,CoupledOptions()),
           ('tip_mach',DesignProject(name='2700rpm桨尖域外负例').confirmed(),replace(CoupledOptions(),propeller=replace(CoupledOptions().propeller,rpm=2700.))),
           ('upper_bound',replace(DesignProject(),name='起飞重量上限1100kg的约束负例',weight=WeightRequirement('upper_bound',1100.)).confirmed(),CoupledOptions())]
    checks={};rows=[]
    for name,p,options in cases:
        saved=state['cases'].setdefault(name,{})
        if 'seed' not in saved:
            saved['seed']=run_sizing(p,root)['run_id'];write_json(checkpoint,state)
        seed=get_results(root,saved['seed'])
        if 'run' not in saved:
            r=run_coupled(p,root,seed['run_id'],options);saved['run']=r['run_id'];write_json(checkpoint,state)
        r=get_results(root,saved['run']);card=make_card(p,r)
        (work/(name+'.html')).write_text(card_html(card),encoding='utf-8')
        if name=='fixed_budget':
            budget_complete=r['status']=='constraints_not_met' and r.get('summary',{}).get('converged',False) and not r['summary']['checks']['mass_budget']
            polar_failure=r['status']=='polar_failed' and r.get('diagnostic_context',{}).get('surface')=='HorizontalTail'
            checks[name+'_diagnostic']=budget_complete or polar_failure
            role='fixed_weight_budget' if budget_complete else 'solver_failure_diagnostic; fixed-weight budget validation blocked'
            checks[name+'_card_semantics']=card['converged'] if budget_complete else all(value is None for value in card['metrics'].values())
        elif name=='upper_bound':
            checks[name+'_state']=(r['status']=='constraints_not_met' and r['summary']['converged'] and
                                  not r['summary']['checks']['mtow_upper_bound'] and r['summary']['design_mtow_kg']>1100.)
            role='converged weight-upper-bound violation; full native loop'
        else:
            checks[name+'_state']=r['status']=='propeller_tip_mach_exceeded'
            role='propeller domain diagnostic'
        checks[name+'_not_eligible']=not card['eligible']
        bundle=build_bundle(p,root,seed,coupled_record=r);(work/(name+'.wdh')).write_bytes(bundle)
        checks[name+'_reopen']=read_bundle(bundle)['coupled_records']==[r]
        rows.append({'case':name,'seed_run_id':seed['run_id'],'run_id':r['run_id'],'status':r['status'],'validation_role':role,
                     'card':card,'diagnostic_context':r.get('diagnostic_context')})
        print(name,r['status'],r['run_id'],flush=True)
    output={'version':__version__,'passed':all(checks.values()),'checks':checks,'cases':rows,'source_hashes':source_hashes(),
            'fixed_weight_budget_validation_completed':budget_complete,'physical_validation_passed':False}
    write_json(work/'validation.json',output)
    if not output['passed']:raise RuntimeError('负例未按预期诊断')


if __name__=='__main__':main(sys.argv[1],'--resume' in sys.argv)
