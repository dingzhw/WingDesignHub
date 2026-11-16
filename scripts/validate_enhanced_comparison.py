"""V0.3.0 native three-design stage. Checkpoints never turn partial work into success."""
from pathlib import Path
from dataclasses import replace,asdict
import json,math,sys
from wingdesignhub import __version__
from wingdesignhub.requirements import DesignProject,WeightRequirement
from wingdesignhub.comparison_ui import variants
from wingdesignhub.comparison_service import run_comparison,compare_sizing_runs
from wingdesignhub.propulsion_feedback import CoupledOptions
from wingdesignhub.coupled_service import run_coupled
from wingdesignhub.sizing_service import run_sizing
from wingdesignhub.service import get_results,write_json,generate_report
from wingdesignhub.geometry_service import source_hashes
from wingdesignhub.adapters import sha256
from wingdesignhub.project_archive import build_bundle,read_bundle,save_bundle,load_saved


def main(target,resume=False):
    root=Path(__file__).resolve().parents[1];work=Path(target).resolve()
    if not resume:work.mkdir(parents=True,exist_ok=False)
    checkpoint=work/'checkpoint.json';sources=source_hashes();julia=sha256(root/'src/wingdesignhub/ccblade_worker.jl')
    req=variants(DesignProject(),'sizing.aspect_ratio',(7.5,8.25,9.))
    req=replace(req,projects=tuple(p.confirmed() for p in req.projects),schema_version=2,analysis_model='coupled',analysis_options=asdict(CoupledOptions()))
    write_json(work/'request.json',req.to_dict())
    state=json.loads(checkpoint.read_text('utf-8')) if resume else {'source_hashes':sources,'worker_sha256':julia}
    if state['source_hashes']!=sources or state['worker_sha256']!=julia:raise ValueError('正式运行后源码已改变')
    write_json(checkpoint,state)
    def progress(i,stage,rid):
        state.update(comparison_run_id=rid,scheme=i,stage=stage);write_json(checkpoint,state)
        print('PROGRESS',i,stage,rid,flush=True)
    if 'comparison_run_id' in state:
        record=get_results(root,state['comparison_run_id'])
        if record['status']=='running':raise ValueError('原批次尚在运行；先检查原进程，禁止重复启动')
    else:record=run_comparison(req,root,on_progress=progress)
    state['comparison_run_id']=record['run_id'];write_json(checkpoint,state)
    if 'summary' not in record:raise RuntimeError(record.get('error','比较未完成'))
    records=[get_results(root,rid) for rid in record['child_runs']];checks={};details=[]
    checks['three_native_converged']=len(records)==3 and all(r['mode']=='overall_propulsion' and r.get('summary',{}).get('converged') for r in records)
    for i,(p,r) in enumerate(zip(req.projects,records)):
        s=r.get('summary',{});rw=root/'runs'/r['run_id']
        if 'geometry' not in s:raise RuntimeError(f"方案 {i} 未完成：{r['status']}")
        checks[f'{i}_all_constraints']=all(s['checks'].values())
        checks[f'{i}_three_rounds']=len(s['iterations'])>=3 and [x['stable_rounds'] for x in s['iterations'][-3:]]==[1,2,3]
        trace=json.loads((rw/'matching_trace.json').read_text('utf-8'))
        force=max(abs(x['thrust_n']-x['drag_n']-x['mass_kg']*9.80665*x['roc_m_s']/x['speed_m_s']) for x in trace)
        shaft=max(abs(x['shaft_power_w']-x['torque_nm']*x['rpm']*math.pi/30) for x in trace)
        checks[f'{i}_balances']=force<1e-8 and shaft<1e-8
        checks[f'{i}_mass_ledger']=abs(s['cg']['loaded_mass_kg']-s['weights']['owe_kg']-p.payload_kg-s['mission']['takeoff_fuel_kg'])<1e-7
        checks[f'{i}_fuel_ledger']=abs(sum(s['mission']['block_fuel_by_method_kg'].values())-s['mission']['block_fuel_kg'])<1e-7
        c=record['summary']['cards'][i]
        checks[f'{i}_card']=c['metrics']['block_fuel_kg']==s['mission']['block_fuel_kg'] and c['enhanced']['max_power_fraction']==s['mission']['max_power_fraction']
        geometry=json.loads((rw/'final_geometry/geometry_contract.json').read_text('utf-8'))
        checks[f'{i}_geometry']=abs(geometry['references']['area_m2']-s['geometry']['wing_area_m2'])<1e-9
        audits=[json.loads(f.read_text('utf-8')) for f in sorted((rw/'iterations').glob('*.json'))]
        details.append({'run_id':r['run_id'],'seed_run_id':r['parent_run_id'],'status':r['status'],
            'summary':s,'native_points':sum(x['native']['points'] for x in audits)+len(s['propulsion_feedback']['direct_aero_checks']),
            'force_residual_n':force,'shaft_residual_w':shaft})
    checks['common_model']=len({r['summary']['model_signature'] for r in records})==1
    rebuilt=compare_sizing_runs(root,record['child_runs'])
    checks['rebuild']=rebuilt.get('summary')==record['summary']
    bundle=build_bundle(req,root,record);(work/'three-designs.wdh').write_bytes(bundle)
    parsed=read_bundle(bundle);index=save_bundle(bundle,root)
    checks['archive']=parsed['records']==[record,*records] and len(parsed['support_records'])==3 and load_saved(root,index['archive_id'])['records']==parsed['records']
    checks['report']=all(r['run_id'] in generate_report(record,project=req) for r in records)
    checks['source_frozen']=sources==source_hashes() and all(r['source_hashes']==sources for r in records)
    output={'version':__version__,'passed':all(checks.values()),'checks':checks,'comparison_run_id':record['run_id'],
        'archive_id':index['archive_id'],'archive_bytes':len(bundle),'request':req.to_dict(),'comparison':record['summary'],
        'designs':details,'source_hashes':sources,'worker_sha256':julia,'physical_validation_passed':False}
    write_json(work/'validation.json',output);print('STAGE',output['passed'],sum(checks.values()),'/',len(checks),flush=True)
    if not output['passed']:raise RuntimeError('阶段检查存在未通过项')


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('target');parser.add_argument('--resume',action='store_true')
    args=parser.parse_args();main(args.target,args.resume)
