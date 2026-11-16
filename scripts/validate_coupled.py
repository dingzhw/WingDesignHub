"""V0.2.7 complete native propulsion/overall closure, with restartable evidence."""
from pathlib import Path
from dataclasses import replace
import json,sys,math
import numpy as np
from wingdesignhub import __version__
from wingdesignhub.requirements import DesignProject
from wingdesignhub.propulsion_feedback import CoupledOptions,mission_kwargs
from wingdesignhub.coupled_service import run_coupled
from wingdesignhub.engine_fuel import EngineFuelModel
from wingdesignhub.propulsion_model import PropellerMap,PropulsiveFlight,EngineModel,propulsion_constraints
from wingdesignhub.aero_feedback import MissionAeroTable
from wingdesignhub.ccblade_adapter import request_base,conditions,run_batch
from wingdesignhub.ccblade_benchmark import official_benchmark
from wingdesignhub.sizing_physics import mission,G,density
from wingdesignhub.geometry_service import source_hashes
from wingdesignhub.service import write_json,get_results,generate_report
from wingdesignhub.adapters import sha256
from wingdesignhub.project_archive import build_bundle,read_bundle,save_bundle,load_saved
from validate_engine_fuel import main as engine_validation


def fixed_comparison(root,seed,p,options,replay_id=None):
    # Historical evidence is explicitly inspected and kept at its original version.
    from wingdesignhub.propulsion_service import validate_parent,run_propulsion
    work=root/'runs'/seed['run_id']
    files={n:(work/n).read_bytes() for n in ('input.json','summary.json','feedback_verification.json','aero_table.json')}
    aero=validate_parent(p,seed,files);s=seed['summary'];rpm=options.propeller.rpm
    previous=get_results(root,replay_id) if replay_id else run_propulsion(p,root,seed['run_id'],options.propeller)
    if previous['parent_run_id']!=seed['run_id'] or previous['options']!=options.propeller.__dict__:raise ValueError('固定构型对照的推进来源不符')
    prop=PropellerMap(json.loads((root/'runs'/previous['run_id']/'propeller_map.json').read_text('utf-8')))
    schedule=s['aerodynamic_feedback']['speed_schedule_m_s'];mass=s['cg']['loaded_mass_kg'];rated=s['power']['installed_power_w'];geo=s['geometry']
    rows=[]
    for mode in ('constant_efficiency','ccblade_original_bsfc','ccblade_native_sfc'):
        flight=PropulsiveFlight(aero,prop,EngineFuelModel(rated))
        kwargs={'flight_model':aero,'schedule':schedule}
        if mode!='constant_efficiency':kwargs={'flight_model':flight,'schedule':schedule,'available_power':lambda h:flight.engine.available(h,rpm)}
        if mode=='ccblade_native_sfc':kwargs=mission_kwargs(flight,schedule,p)
        ms=mission(mass,geo,rated,p,options.aero.integration_step_s,**kwargs)
        rows.append({'model':mode,'block_fuel_kg':ms['block_fuel_kg'],'max_power_fraction':ms['max_power_fraction'],
            'installed_power_w':rated,'carried_fuel_margin_kg':s['mission']['takeoff_fuel_kg']-ms['takeoff_fuel_kg'],
            'fuel_by_method_kg':ms['block_fuel_by_method_kg']})
    return {'basis':'same original geometry, mass/CG, carried fuel, speeds and installed engine; only named models replaced',
            'reoptimized':False,'source_feedback_id':seed['run_id'],'source_propulsion_id':previous['run_id'],
            'rows':rows,'legacy_reproduced':abs(rows[0]['block_fuel_kg']-s['mission']['block_fuel_kg'])<1e-6,
            'v026_reproduced':abs(rows[1]['block_fuel_kg']-previous['summary']['mission']['block_fuel_kg'])<1e-6}


def main(target,seed_id,resume=False,replay_id=None):
    root=Path(__file__).resolve().parents[1];work=Path(target).resolve()
    if not resume:work.mkdir(parents=True,exist_ok=False)
    sources=source_hashes();worker_hash=sha256(root/'src/wingdesignhub/ccblade_worker.jl')
    parent=get_results(root,seed_id);pw=root/'runs'/seed_id;p=DesignProject.from_dict(json.loads((pw/'input.json').read_text('utf-8')))
    before=sha256(pw/'result.json');o=CoupledOptions();checkpoint=work/'checkpoint.json'
    if resume:
        state=json.loads(checkpoint.read_text('utf-8'))
        assert state['source_hashes']==sources and state['worker_sha256']==worker_hash,'Source changed since native run'
        r=get_results(root,state['run_id'])
    else:
        write_json(checkpoint,{'state':'running','source_hashes':sources,'worker_sha256':worker_hash})
        r=run_coupled(p,root,seed_id,o)
        write_json(checkpoint,{'state':r['status'],'run_id':r['run_id'],'source_hashes':sources,'worker_sha256':worker_hash})
    print('COUPLED',r['run_id'],r['status'],r.get('error',''),flush=True)
    if 'geometry' not in r.get('summary',{}):raise RuntimeError('Native overall did not complete; see checkpoint and preserved run')
    s=r['summary'];rw=root/'runs'/r['run_id'];checks={}
    checks['overall_converged']=s['converged'] and s['iterations'][-1]['stable_rounds']>=3
    checks['all_constraints_and_direct_checks']=all(s['checks'].values())
    checks['parent_unchanged']=sha256(pw/'result.json')==before
    checks['same_source_frozen']=source_hashes()==sources and sha256(root/'src/wingdesignhub/ccblade_worker.jl')==worker_hash
    audits=[json.loads(f.read_text('utf-8')) for f in sorted((rw/'iterations').glob('*.json'))]
    checks['power_enters_engine_mass']=all(abs(x['weights']['components_kg']['data:weight:propulsion:engine:mass']/(1.4*(x['mass_model_power_input_w']/745.7-21.55)/.5515*.45359237)-1)<1e-12 for x in audits)
    checks['engine_and_geometry_changed']=len({x['native']['geometry_sha256'] for x in audits})>1 and len({x['weights']['components_kg']['data:weight:propulsion:engine:mass'] for x in audits})>1
    checks['loaded_mass_closure']=abs(s['cg']['loaded_mass_kg']-s['weights']['owe_kg']-p.payload_kg-s['mission']['takeoff_fuel_kg'])<1e-7
    checks['fuel_methods_close']=abs(sum(s['mission']['block_fuel_by_method_kg'].values())-s['mission']['block_fuel_kg'])<1e-7
    contract=json.loads((rw/'final_geometry/geometry_contract.json').read_text('utf-8'))
    checks['native_geometry_area']=abs(contract['references']['area_m2']-s['geometry']['wing_area_m2'])<1e-9
    matching=json.loads((rw/'matching_trace.json').read_text('utf-8'))
    force=max(abs(x['thrust_n']-x['drag_n']-x['mass_kg']*G*x['roc_m_s']/x['speed_m_s']) for x in matching)
    shaft=max(abs(x['shaft_power_w']-x['torque_nm']*x['rpm']*math.pi/30) for x in matching)
    checks['force_balance']=force<1e-8;checks['shaft_balance']=shaft<1e-8
    checks['power_overrun_resolved']=s['mission']['max_power_fraction']<=1.001 and min(x['torque_margin_nm'] for x in matching)>=-1e-8
    fixed=fixed_comparison(root,parent,p,o,replay_id) if parent['mode']=='overall_feedback' else None
    if fixed:
        write_json(work/'fixed_comparison.json',fixed)
        checks['fixed_original_models_reproduced']=fixed['legacy_reproduced'] and fixed['v026_reproduced']
        checks['fixed_and_redesign_separate']=not fixed['reoptimized'] and s['redesign_comparison']['comparison_type']=='redesign'
    data=json.loads((rw/'propeller_map.json').read_text('utf-8'));prop=PropellerMap(data)
    samples=[matching[i] for i in np.linspace(0,len(matching)-1,6,dtype=int)]
    finefile=work/'radial96/result.json'
    if resume and finefile.exists():fine=json.loads(finefile.read_text('utf-8'))
    else:
        request=request_base(replace(o.propeller,radial_stations=96),prop.diameter,data['airfoil'])
        request['points']=[conditions(x['speed_m_s'],x['altitude_m'],x['rpm'],x['collective_deg']) for x in samples]
        fine=run_batch(root,work/'radial96',request)
    # Fine direct points compared against exact native 48-point runs, not interpolated map points.
    coarsefile=work/'radial48/result.json'
    if resume and coarsefile.exists():coarse=json.loads(coarsefile.read_text('utf-8'))
    else:
        request=request_base(o.propeller,prop.diameter,data['airfoil']);request['points']=[conditions(x['speed_m_s'],x['altitude_m'],x['rpm'],x['collective_deg']) for x in samples]
        coarse=run_batch(root,work/'radial48',request)
    radial=[]
    for a,b in zip(coarse['points'],fine['points']):
        valid=a['status']==b['status']=='valid'
        errors={k:abs(b[k]/a[k]-1) for k in ('thrust_n','shaft_power_w')} if valid else {}
        radial.append({'all_valid':valid,'relative_errors':errors,'passed':valid and max(errors.values())<.02})
    checks['radial96_accuracy']=all(x['passed'] for x in radial)
    officialfile=work/'official/comparison.json'
    official=json.loads(officialfile.read_text('utf-8')) if resume and officialfile.exists() else official_benchmark(root,work/'official')
    checks['official_propeller_diagnostic_band']=official['all_within_band']
    enginefile=work/'engine/validation.json'
    engine_source=root/'local/v027-sources/test_basicIC_engine.py'
    engine=json.loads(enginefile.read_text('utf-8')) if resume and enginefile.exists() else engine_validation(work/'engine',engine_source if engine_source.is_file() else None)
    checks['official_engine_and_mass']=engine['passed']
    base=get_results(root,parent['parent_run_id']) if parent['mode']=='overall_feedback' else parent
    bundle=build_bundle(p,root,base,feedback_record=parent if parent['mode']=='overall_feedback' else None,coupled_record=r)
    (work/'coupled.wdh').write_bytes(bundle);index=save_bundle(bundle,root)
    checks['archive_reopen']=load_saved(root,index['archive_id'])['coupled_records']==[r]
    checks['report']=r['run_id'] in generate_report(r,root=root)
    out={'version':__version__,'passed':all(checks.values()),'checks':checks,'run_id':r['run_id'],'parent_run_id':seed_id,
        'archive_id':index['archive_id'],'summary':s,'fixed_comparison':fixed,'force_residual_n':force,'shaft_residual_w':shaft,
        'radial_convergence':radial,'official':official,'engine':engine,'source_hashes':sources,'worker_sha256':worker_hash,
        'physical_validation_passed':False}
    write_json(work/'validation.json',out);print('STAGE',out['passed'],sum(checks.values()),'/',len(checks),flush=True)
    if not out['passed']:raise RuntimeError('Stage verification failed; results preserved')


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('target');parser.add_argument('seed_id')
    parser.add_argument('--resume',action='store_true');parser.add_argument('--replay-run-id')
    args=parser.parse_args();main(args.target,args.seed_id,args.resume,args.replay_run_id)
