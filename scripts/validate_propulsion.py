"""V0.2.6 native modules and same-aircraft propulsion replay, without resizing."""
from pathlib import Path
from dataclasses import replace
import json,sys,math,tomllib
import numpy as np
from wingdesignhub import __version__
from wingdesignhub.requirements import DesignProject
from wingdesignhub.propulsion_service import run_propulsion
from wingdesignhub.propulsion_model import PropulsionOptions,PropellerMap,PropulsionError
from wingdesignhub.ccblade_benchmark import official_benchmark
from wingdesignhub.ccblade_adapter import run_batch,request_base,conditions
from wingdesignhub.geometry_service import source_hashes
from wingdesignhub.service import get_results,write_json,generate_report
from wingdesignhub.adapters import sha256
from wingdesignhub.project_archive import build_bundle,read_bundle,save_bundle,load_saved
from wingdesignhub.sizing_physics import G


def main(target,feedback_id,resume=False):
    root=Path(__file__).resolve().parents[1];work=Path(target).resolve()
    if not resume:work.mkdir(parents=True,exist_ok=False)
    sources=source_hashes();worker=root/'src/wingdesignhub/ccblade_worker.jl';worker_hash=sha256(worker)
    parent=get_results(root,feedback_id);pw=root/'runs'/feedback_id
    p=DesignProject.from_dict(json.loads((pw/'input.json').read_text('utf-8')))
    before={n:sha256(pw/n) for n in ('result.json','aero_table.json','summary.json')}
    if resume:
        checkpoint=json.loads((work/'checkpoint.json').read_text('utf-8'))
        assert checkpoint['source_hashes']==sources and checkpoint['worker_sha256']==worker_hash,'Source changed since checkpoint'
        r=get_results(root,checkpoint['run_id']);assert r['parent_run_id']==feedback_id
    else:
        write_json(work/'checkpoint.json',{'state':'running','source_hashes':sources,'worker_sha256':worker_hash})
        r=run_propulsion(p,root,feedback_id);write_json(work/'checkpoint.json',{'state':r['status'],'run_id':r['run_id'],'source_hashes':sources,'worker_sha256':worker_hash})
    print('propulsion',r['run_id'],r['status'],r.get('error',''),flush=True)
    if 'summary' not in r:raise RuntimeError('Native replay failed; see checkpoint')
    s=r['summary'];rw=root/'runs'/r['run_id'];checks={}
    checks['record_integrity']=get_results(root,r['run_id'])==r
    checks['parent_unchanged']=all(sha256(pw/n)==h for n,h in before.items())
    checks['fixed_geometry_and_loading']=s['geometry']==parent['summary']['geometry'] and s['initial_mass_kg']==parent['summary']['cg']['loaded_mass_kg'] and not s['reoptimized']
    checks['same_condition_legacy_reproduced']=abs(s['legacy_mission']['block_fuel_kg']-parent['summary']['mission']['block_fuel_kg'])<1e-6
    checks['direct_query_accuracy']=s['checks']['propeller_table_accuracy']
    checks['mission_step_accuracy']=s['checks']['mission_step_accuracy']
    checks['engine_constraint_status']=(s['checks']['engine_power']==(s['mission']['max_power_fraction']<=1.001))
    checks['fuel_constraint_status']=(s['checks']['carried_fuel']==(s['carried_fuel_margin_kg']>=-1e-6))
    checks['separate_replacement_stages']=len(s['replacement_stages'])==3 and abs(s['replacement_stages'][1]['block_fuel_kg']-s['mission']['block_fuel_kg'])<1e-8
    prop=PropellerMap(json.loads((rw/'propeller_map.json').read_text('utf-8')));data=prop.data
    errors={'thrust_integral':0.,'torque_integral':0.,'cp_cq':0.,'shaft_power':0.}
    for point in prop.points:
        if point['status']!='valid':continue
        radius=np.array([.2*prop.diameter/2,*point['radius_m'],prop.diameter/2]);normal=[0,*point['normal_load_n_m'],0]
        tangent=[0,*(np.array(point['tangential_load_n_m'])*np.array(point['radius_m'])),0]
        t=data['blades']*np.trapezoid(normal,radius);q=data['blades']*np.trapezoid(tangent,radius)
        errors['thrust_integral']=max(errors['thrust_integral'],abs(t/point['thrust_n']-1))
        errors['torque_integral']=max(errors['torque_integral'],abs(q/point['torque_nm']-1))
        errors['cp_cq']=max(errors['cp_cq'],abs(point['cp']/(2*math.pi*point['cq'])-1))
        errors['shaft_power']=max(errors['shaft_power'],abs(point['shaft_power_w']/(point['torque_nm']*point['rpm']*math.pi/30)-1))
    checks['independent_radial_integrals_and_units']=max(errors.values())<1e-12
    trace=json.loads((rw/'mission_trace.json').read_text('utf-8'))
    balance=max(abs(t['thrust_n']-t['drag_n']-t['mass_kg']*G*t['roc_m_s']/t['speed_m_s']) for t in trace)
    power=max(abs(t['shaft_power_w']*t['efficiency']-t['thrust_n']*t['speed_m_s']) for t in trace)
    checks['flight_force_power_balance']=balance<1e-8 and power<1e-8
    ms=s['mission'];checks['fuel_reserve_ledger']=abs(ms['takeoff_fuel_kg']-ms['trip_fuel_from_takeoff_kg']-ms['reserve_fuel_kg'])<1e-8 and abs(ms['block_fuel_kg']-ms['takeoff_fuel_kg']-ms['taxi_out_fuel_kg'])<1e-8
    base_request=json.loads((rw/'native/direct/request.json').read_text('utf-8'))
    original=json.loads((rw/'native/direct/result.json').read_text('utf-8'))['points']
    radial={48:original}
    for n in (24,96):
        request={**base_request,'radial_stations':n}
        directory=work/f'radial_{n}'
        if resume and (directory/'result.json').is_file():
            assert json.loads((directory/'request.json').read_text('utf-8'))==request
            assert sha256(directory/'worker.jl')==worker_hash
            cached=json.loads((directory/'result.json').read_text('utf-8'))
            assert cached['points']==tomllib.loads((directory/'output.toml').read_text('utf-8'))['points']
            radial[n]=cached['points']
        else:radial[n]=run_batch(root,directory,request)['points']
    convergence=[]
    for i in range(len(original)):
        row={'point':i,'all_valid':all(radial[n][i]['status']=='valid' for n in radial)}
        for n in (24,48):
            for name in ('thrust_n','shaft_power_w'):row[f'{name}_{n}_to_{n*2}']=abs(radial[n][i][name]/radial[n*2][i][name]-1)
        convergence.append(row)
    checks['radial_grid_convergence']=all(x['all_valid'] and max(x['thrust_n_48_to_96'],x['shaft_power_w_48_to_96'])<.02 for x in convergence)
    if resume and (work/'official/comparison.json').is_file():
        assert sha256(work/'official/worker.jl')==worker_hash
        official=json.loads((work/'official/comparison.json').read_text('utf-8'))
        actual=tomllib.loads((work/'official/output.toml').read_text('utf-8'))['points']
        assert len(actual)==len(official['rows'])
        for row,point in zip(official['rows'],actual):
            assert all(row[k]['computed']==point[k] for k in ('ct','cp','efficiency'))
    else:official=official_benchmark(root,work/'official')
    checks['official_public_diagnostic_band']=official['all_within_band']
    bad=run_propulsion(p,root,feedback_id,replace(PropulsionOptions(),rpm=2700.))
    checks['tip_mach_diagnostic']=bad['status']=='propeller_tip_mach_exceeded'
    with_missing=json.loads(json.dumps(data));with_missing['points'][0]['status']='out_of_domain'
    checks['no_extrapolation']=False
    try:PropellerMap(with_missing).query(1000,999,0)
    except PropulsionError:checks['no_extrapolation']=True
    base=get_results(root,parent['parent_run_id'])
    bundle=build_bundle(p,root,base,feedback_record=parent,propulsion_record=r)
    if not (work/'propulsion.wdh').exists():(work/'propulsion.wdh').write_bytes(bundle)
    else:assert read_bundle((work/'propulsion.wdh').read_bytes())['propulsion_records']==[r]
    saved=save_bundle(bundle,root)
    opened=load_saved(root,saved['archive_id']);checks['archive_reopen']=opened['propulsion_records']==[r] and opened['feedback_records']==[parent]
    failed=read_bundle(build_bundle(p,root,base,feedback_record=parent,propulsion_record=bad))
    checks['failed_archive']=failed['propulsion_records']==[bad]
    checks['report']=s['source_aerodynamics_run_id'] in generate_report(r,root=root) or r['run_id'] in generate_report(r,root=root)
    checks['source_frozen']=source_hashes()==sources and sha256(worker)==worker_hash
    checks={k:bool(v) for k,v in checks.items()}
    output={'version':__version__,'passed':all(checks.values()),'checks':checks,'run_id':r['run_id'],'parent_run_id':feedback_id,
        'failed_run_id':bad['run_id'],'archive_id':saved['archive_id'],'summary':s,'native_points':len(prop.points),
        'valid_native_points':sum(x['status']=='valid' for x in prop.points),'tip_mach':data['max_tip_mach'],
        'independent_integral_relative_errors':errors,'force_error_n':balance,'power_error_w':power,
        'radial_convergence':convergence,'official':official,'source_hashes':sources,'worker_sha256':worker_hash,
        'physical_validation_passed':False}
    write_json(work/'validation.json',output);print('STAGE',output['passed'],sum(checks.values()),'/',len(checks),flush=True)
    print(json.dumps(s['comparison'],ensure_ascii=False),flush=True)
    if not output['passed']:raise RuntimeError('Stage check failed; see validation.json')


if __name__=='__main__':main(sys.argv[1],sys.argv[2],resume='--resume' in sys.argv[3:])
