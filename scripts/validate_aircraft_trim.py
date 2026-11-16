"""V0.2.3 evidence: real residuals, state propagation, bounds and native trim parity.

Run after source freeze. Official inputs stay local; this is numerical validation,
not aircraft flight-test calibration. Checkpoints preserve completed expensive runs.
"""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import hashlib
import json
import math
import shutil
import sys
import numpy as np
from wingdesignhub import __version__
from wingdesignhub.requirements import DesignProject,WeightRequirement
from wingdesignhub.sizing_service import run_sizing
from wingdesignhub.geometry_service import run_aircraft_geometry,source_hashes
from wingdesignhub.trim_service import run_aircraft_trim
from wingdesignhub.aircraft_trim import TrimOptions,bounded_newton
from wingdesignhub.aircraft_aero import commands,avl_input
from wingdesignhub.avl_aircraft import parse_total,parse_derivatives
from wingdesignhub.adapters import execute,tool_paths,sha256
from wingdesignhub.service import write_json,get_results
from wingdesignhub.project_archive import build_bundle,read_bundle

PUBLIC={'vanilla.avl':'28ccdc714456379de6e3f5f5edacfedf45a915484fb4bac646f335c864d339b2',
        'sd7037.dat':'29aa7f654a66adcbfcec0a25b00beeb86df185ad869de632366b68c28ce60d96'}


def controls(text):
    raw=text.split('CONTROL\n',1)[1].split('DESIGN')[0].strip().splitlines()
    return {line.split()[1]:float(line.split()[0]) for line in raw[1:]}


def native_reference(contract,exe,work):
    work.mkdir();(work/'model.avl').write_text(avl_input(contract),encoding='ascii')
    f=contract['flow'];target=f['mass_kg']*9.80665/(f['dynamic_pressure_pa']*contract['references']['area_m2'])
    command=commands(contract).replace(f"A A {f['alpha_deg']}",f'A C {target}').replace(
        f"D2 D2 {contract['options']['elevator_deg']}",'D2 PM 0')
    execute([exe],work,command,timeout=120)
    text=(work/'total.mrf').read_text('ascii');c=parse_total(text)
    return {'alpha_deg':c['Alpha'],'elevator_deg':controls(text)['elevator'],'coefficients':c,
            'residual_cl':c['CLtot']-target,'residual_cm':c['Cmtot'],'method':'native AVL A C target / D2 PM 0'}


def public_reference(exe,work):
    work.mkdir();sources={}
    for name,digest in PUBLIC.items():
        data=(Path(exe).parent/'Sample Input Files'/name).read_bytes()
        if hashlib.sha256(data).hexdigest()!=digest:raise ValueError('公开原始输入哈希不符：'+name)
        (work/name).write_bytes(data);sources[name]={'sha256':digest,'url':'https://web.mit.edu/drela/Public/web/avl/runs/'+name}
    target=.5;counter=0
    def run(name,settings):
        directory=work/name;directory.mkdir()
        for fn in PUBLIC:shutil.copy2(work/fn,directory/fn)
        command='LOAD vanilla.avl\nOPER\n'+settings+'\nX\nMRF\nFT\ntotal.mrf\nST\nstability.mrf\n\nQUIT\n'
        execute([exe],directory,command,timeout=120)
        raw=(directory/'total.mrf').read_text('ascii');return parse_total(raw),parse_derivatives((directory/'stability.mrf').read_text('ascii')),controls(raw)
    def evaluate(x):
        nonlocal counter
        name=f'eval_{counter:02d}';counter+=1
        c,d,u=run(name,f'A A {x[0]}\nD3 D3 {x[1]}')
        if list(u)!=['flap','aileron','elevator','rudder']:raise ValueError('公开算例操纵面顺序不符')
        return [c['CLtot']-target,c['Cmtot']],[[d['CLa']*math.pi/180,d['CLd'][2]],
                        [d['Cma']*math.pi/180,d['Cmd'][2]]],{'evaluation_id':name,'coefficients':c}
    result=bounded_newton(evaluate,[3,0],[-6,-10],[6,10]);result.pop('payload')
    native,_,u=run('native_trim',f'A C {target}\nD3 PM 0')
    difference=[result['solution'][0]-native['Alpha'],result['solution'][1]-u['elevator']]
    return {'sources':sources,'target_cl':target,'outer_solution':result,'native_coefficients':native,'native_elevator_deg':u['elevator'],
            'angle_differences_deg':difference,'role':'unmodified MIT vanilla input; same-solver independent control path, not physical validation',
            'passed':result['converged'] and max(abs(v) for v in difference)<.001 and abs(native['CLtot']-target)<1e-5 and abs(native['Cmtot'])<1e-5}


def brief(record):
    s=record['summary'];t=s['trim']
    return {'run_id':record['run_id'],'status':record['status'],'flight_state':s['flight_state'],'options':record['options'],
            'alpha_deg':t['alpha_deg'],'elevator_deg':t['elevator_deg'],'residual_cl':t['residual_cl'],'residual_cm':t['residual_cm'],
            'evaluation_count':t['evaluation_count'],'induced_drag_n':t['induced_drag_n'],'surface_loads':t['surface_loads'],
            'margins_deg':t['margins_deg'],'active_bounds':t['active_bounds'],'Cma_per_rad':t['local_cma_per_rad'],
            'reference_area_m2':s['references']['area_m2'],'force_checks_passed':all(z['passed'] for z in s['checks'])}


def main(target):
    root=Path(__file__).resolve().parents[1];work=Path(target).resolve();work.mkdir(parents=True,exist_ok=False)
    start_hashes=source_hashes();exe=tool_paths(root)['avl'];records={};rows={};checks={}
    p=DesignProject().confirmed();s=run_sizing(p,root);g=run_aircraft_geometry(p,root,s['run_id'])
    assert g['status']=='geometry_checked_with_limits',g
    def run(name,options=None,project=p,sizing=s,geom=g):
        r=run_aircraft_trim(project,root,geom['run_id'],options)
        if r['status']=='failed':raise RuntimeError(r)
        get_results(root,r['run_id']);records[name]=r;rows[name]=brief(r)
        write_json(work/'checkpoint.json',{'source_hashes':start_hashes,'sizing_run_id':s['run_id'],'geometry_run_id':g['run_id'],'cases':rows})
        print(name,r['status'],rows[name]['alpha_deg'],rows[name]['elevator_deg'],flush=True);return r
    base=run('baseline');mass=s['summary']['design_mtow_kg'];cg=base['summary']['flight_state']['cg_geometry_m'][0];mac=base['summary']['references']['chord_m']
    specs={'mission_end':TrimOptions(mass_state='mission_end'),
        'cg_reference':TrimOptions(mass_state='explicit',mass_kg=mass,cg_x_m=cg,source_note='fixed mass CG sensitivity'),
        'cg_forward':TrimOptions(mass_state='explicit',mass_kg=mass,cg_x_m=cg-.1*mac,source_note='fixed mass CG sensitivity'),
        'cg_aft':TrimOptions(mass_state='explicit',mass_kg=mass,cg_x_m=cg+.1*mac,source_note='fixed mass CG sensitivity'),
        'lighter_same_cg':TrimOptions(mass_state='explicit',mass_kg=.9*mass,cg_x_m=cg,source_note='mass sensitivity at fixed CG'),
        'speed_65':TrimOptions(speed_m_s=65.),'coarse':TrimOptions(mesh_level=1),'fine':TrimOptions(mesh_level=3),
        'different_initial':TrimOptions(initial_alpha_deg=0.,initial_elevator_deg=-3.),
        'elevator_limited':TrimOptions(elevator_min_deg=-1.,elevator_max_deg=1.),
        'alpha_limited':TrimOptions(alpha_max_deg=3.),'iteration_limited':TrimOptions(max_iterations=1)}
    for name,options in specs.items():run(name,options)
    for name in ['baseline','mission_end','cg_reference','cg_forward','cg_aft','lighter_same_cg','speed_65','coarse','fine','different_initial']:
        r=rows[name];checks[name+'_true_residuals']=r['status']=='trim_checked_with_limits' and max(abs(r['residual_cl']),abs(r['residual_cm']))<=1e-5 and r['force_checks_passed']
    checks['elevator_limit_rejected']=rows['elevator_limited']['status']=='trim_bounds_exceeded' and 'elevator_lower' in rows['elevator_limited']['active_bounds']
    checks['alpha_limit_rejected']=rows['alpha_limited']['status']=='trim_bounds_exceeded' and 'alpha_upper' in rows['alpha_limited']['active_bounds']
    checks['iteration_limit_rejected']=rows['iteration_limited']['status']=='trim_not_converged'
    checks['all_trials_in_domain']=all(-6<=h['alpha_deg']<=6 and -10<=h['elevator_deg']<=10 for r in records.values() for h in r['summary']['trim']['history'])
    end=rows['mission_end']['flight_state'];ms=s['summary']['mission']
    checks['end_fuel_accounting']=math.isclose(end['remaining_usable_fuel_kg'],ms['reserve_fuel_kg']+ms['taxi_in_fuel_kg'],abs_tol=1e-6)
    checks['end_mass_changes_trim']=end['operating_mass_kg']<rows['baseline']['flight_state']['operating_mass_kg'] and rows['mission_end']['alpha_deg']<rows['baseline']['alpha_deg']
    seq=[rows[n] for n in ('cg_forward','cg_reference','cg_aft')]
    checks['fixed_mass_cg_sensitivity']=all(x['flight_state']['operating_mass_kg']==mass for x in seq)
    checks['cg_to_elevator_tail_drag']=(seq[0]['elevator_deg']<seq[1]['elevator_deg']<seq[2]['elevator_deg'] and
        seq[0]['surface_loads']['HorizontalTail']['lift_n']<seq[1]['surface_loads']['HorizontalTail']['lift_n']<seq[2]['surface_loads']['HorizontalTail']['lift_n'] and
        len({round(x['induced_drag_n'],6) for x in seq})==3)
    checks['mass_to_trim']=rows['lighter_same_cg']['alpha_deg']<rows['cg_reference']['alpha_deg']
    checks['speed_to_trim']=rows['speed_65']['alpha_deg']<rows['baseline']['alpha_deg']
    checks['initial_guess_independence']=max(abs(rows['different_initial'][k]-rows['baseline'][k]) for k in ('alpha_deg','elevator_deg'))<.001
    mesh={}
    for key in ('alpha_deg','elevator_deg','induced_drag_n'):
        coarse,standard,fine=(rows[n][key] for n in ('coarse','baseline','fine'))
        diff=abs(standard-fine)/abs(fine)
        mesh[key]={'coarse':coarse,'standard':standard,'fine':fine,'standard_to_fine_relative':diff}
        checks['mesh_'+key]=diff<.02
    contract=json.loads((root/'runs'/base['run_id']/'trim_contract.json').read_text('utf-8'))
    native=native_reference(contract,exe,work/'native_baseline')
    checks['native_trim_parity']=max(abs(native[k]-rows['baseline'][k]) for k in ('alpha_deg','elevator_deg'))<.001 and max(abs(native['residual_cl']),abs(native['residual_cm']))<1e-5
    for mode,value in [('fixed',1500.),('upper_bound',1800.)]:
        project=replace(p,weight=WeightRequirement(mode,value)).confirmed();sizing=run_sizing(project,root)
        geom=run_aircraft_geometry(project,root,sizing['run_id']);r=run(mode,project=project,sizing=sizing,geom=geom)
        checks[mode+'_mass_semantics']=r['status']=='trim_checked_with_limits' and math.isclose(r['summary']['flight_state']['operating_mass_kg'],sizing['summary']['required_loaded_mass_kg'],abs_tol=1e-8)
        if mode=='fixed':checks['fixed_budget_not_ballast']=r['summary']['flight_state']['unallocated_mass_budget_kg']>1 and not r['summary']['flight_state']['mass_budget_allocated_as_ballast']
    data=build_bundle(p,root,s,g,trim_record=base);(work/'baseline.wdh').write_bytes(data)
    checks['archive_roundtrip']=read_bundle(data)['trim_records']==[base]
    failed=records['elevator_limited'];checks['failed_archive_roundtrip']=read_bundle(build_bundle(p,root,s,g,trim_record=failed))['trim_records']==[failed]
    public=public_reference(exe,work/'public_vanilla');checks['public_native_parity']=public['passed']
    checks['source_unchanged']=start_hashes==source_hashes()
    checks['no_mission_replacement']=all(not r['summary']['mission_polar_updated'] for r in records.values())
    result={'version':__version__,'passed':all(checks.values()),'checks':checks,'source_hashes':start_hashes,
        'sizing_run_id':s['run_id'],'geometry_run_id':g['run_id'],'cases':rows,'mesh_sensitivity':mesh,'native_reference':native,
        'public_example':public,'solver_sha256':sha256(exe),'physical_validation_passed':False,'calibration_performed':False,
        'scope':'lifting-surface longitudinal trim and conceptual mass/CG ledger; axial balance and mission feedback excluded'}
    write_json(work/'summary.json',result);print('passed',result['passed'],'checks',len(checks),flush=True)
    return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(main(sys.argv[1]))
