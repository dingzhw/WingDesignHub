"""Bounded V0.2.2 evidence. Run after source freeze; external inputs remain local."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import hashlib
import json
import math
import shutil
import sys
from urllib.request import urlopen
import numpy as np
from wingdesignhub import __version__
from wingdesignhub.requirements import DesignProject,MissionRequirement
from wingdesignhub.sizing_service import run_sizing
from wingdesignhub.geometry_service import run_aircraft_geometry,source_hashes
from wingdesignhub.aero_service import run_aircraft_aero
from wingdesignhub.aircraft_aero import AeroOptions
from wingdesignhub.avl_aircraft import solve,parse_total,parse_elements
from wingdesignhub.aircraft_geometry import transfer_wrench,body_vectors
from wingdesignhub.adapters import execute,sha256,tool_paths
from wingdesignhub.service import write_json,get_results
from wingdesignhub.project_archive import build_bundle,read_bundle

PUBLIC={'vanilla.avl':'28ccdc714456379de6e3f5f5edacfedf45a915484fb4bac646f335c864d339b2',
        'sd7037.dat':'29aa7f654a66adcbfcec0a25b00beeb86df185ad869de632366b68c28ce60d96',
        'ellip.avl':'e62356d640ba72e9cbe92fea8fa52b5b8c6d8f1a95ebb706f4d76ba9e1458927'}


def public_cases(work,exe):
    inputs=work/'public_inputs';inputs.mkdir();sources={}
    for name,digest in PUBLIC.items():
        local=Path(exe).parent/'Sample Input Files'/name
        url='https://web.mit.edu/drela/Public/web/avl/runs/'+name
        data=local.read_bytes() if local.is_file() else urlopen(url,timeout=40).read()
        if hashlib.sha256(data).hexdigest()!=digest:raise ValueError('公开算例哈希不符：'+name)
        (inputs/name).write_bytes(data);sources[name]={'url':url,'sha256':digest,'role':'upstream numerical example; not experimental calibration'}
    rows={}
    for name in ('vanilla','ellip'):
        case=work/name;case.mkdir()
        shutil.copy2(inputs/(name+'.avl'),case/'model.avl')
        if name=='vanilla':shutil.copy2(inputs/'sd7037.dat',case/'sd7037.dat')
        out=execute([exe],case,'LOAD model.avl\nOPER\nA A 3\nX\nMRF\nFT\ntotal.mrf\nFE\nelements.mrf\n\nQUIT\n')
        c=parse_total((case/'total.mrf').read_text('ascii'));parse_elements((case/'elements.mrf').read_text('ascii'))
        rows[name]={'coefficients':c,'input_sha256':sha256(case/'model.avl'),'solver_sha256':sha256(exe)}
    c=rows['ellip']['coefficients'];ar=c['Bref']**2/c['Sref'];theory=2*math.pi/(1+2/ar)*math.radians(3)
    cd=c['CLff']**2/(math.pi*ar)
    rows['ellip']['lifting_line_comparison']={'aspect_ratio':ar,'cl_theory':theory,
        'cl_relative_difference':(c['CLtot']-theory)/theory,'ideal_induced_cd':cd,
        'induced_cd_relative_difference':(c['CDff']-cd)/cd,
        'role':'independent ideal elliptic lifting-line relation, not measured aircraft validation'}
    return {'sources':sources,'results':rows}


def main(target):
    root=Path(__file__).resolve().parents[1];work=Path(target).resolve();work.mkdir(parents=True,exist_ok=False)
    p=DesignProject();cases={'baseline':p,'payload_450':replace(p,payload_kg=450.),
        'range_1200km':replace(p,mission=MissionRequirement('range_only',1200000.,None)),
        'endurance_5h':replace(p,mission=MissionRequirement('endurance_only',None,18000.)),
        'aspect_ratio_9':replace(p,sizing=replace(p.sizing,aspect_ratio=9.))}
    checks={};rows={};records={};start_hashes=source_hashes()
    for name,project in cases.items():
        project=project.confirmed();s=run_sizing(project,root);assert s['summary']['converged'],s
        g=run_aircraft_geometry(project,root,s['run_id']);a=run_aircraft_aero(project,root,g['run_id'])
        assert a['status']=='aero_checked_with_limits',a
        records[name]=(project,s,g,a);ref=a['summary']['references']
        rows[name]={'overall_run_id':s['run_id'],'geometry_run_id':g['run_id'],'aero_run_id':a['run_id'],
            'mtow_kg':s['summary']['design_mtow_kg'],'fuel_kg':s['summary']['mission']['block_fuel_kg'],
            'references':ref,'coefficients':a['summary']['coefficients'],'force_body_n':a['summary']['force_body_n']}
        checks[name+'_source_and_refs']=ref==g['summary']['references'] and all(x['passed'] for x in a['summary']['checks'])
        for r in (s,g,a):get_results(root,r['run_id'])
        write_json(work/'checkpoint.json',rows);print(name,a['run_id'],flush=True)
    for name in list(cases)[1:]:
        checks[name+'_demand_to_aero']=rows[name]['references']!=rows['baseline']['references'] and rows[name]['force_body_n']!=rows['baseline']['force_body_n']
    p,s,g,base=records['baseline'];basec=base['summary']['coefficients'];variants={}
    specs={
        'mesh_coarse':AeroOptions(mesh_level=1),'mesh_fine':AeroOptions(mesh_level=3),
        'beta_plus':AeroOptions(beta_deg=2.),'beta_minus':AeroOptions(beta_deg=-2.),
        'aileron_plus':AeroOptions(aileron_deg=2.),'aileron_minus':AeroOptions(aileron_deg=-2.),
        'rudder_plus':AeroOptions(rudder_deg=2.),'rudder_minus':AeroOptions(rudder_deg=-2.),
        'alpha_plus':AeroOptions(alpha_deg=3.05),'alpha_minus':AeroOptions(alpha_deg=2.95),
        'elevator_plus':AeroOptions(elevator_deg=.05),'elevator_minus':AeroOptions(elevator_deg=-.05),
        'elevator_fine_plus':AeroOptions(elevator_deg=.002),'elevator_fine_minus':AeroOptions(elevator_deg=-.002),
        'edge':AeroOptions(alpha_deg=6.,beta_deg=5.,aileron_deg=10.,elevator_deg=-10.,rudder_deg=10.),
    }
    for name,o in specs.items():
        a=run_aircraft_aero(p,root,g['run_id'],o);assert a['status']=='aero_checked_with_limits',a
        variants[name]=a;get_results(root,a['run_id']);print(name,a['run_id'],flush=True)
        write_json(work/'variants.json',variants)
    checks['zero_beta_symmetry']=all(abs(basec[k])<1e-10 for k in ('CYtot','Cltot','Cntot'))
    for name in ('beta','aileron','rudder'):
        pos=variants[name+'_plus']['summary']['coefficients'];neg=variants[name+'_minus']['summary']['coefficients']
        checks[name+'_odd_lateral']=all(abs(pos[k]+neg[k])<1e-10 for k in ('CYtot','Cltot','Cntot'))
        checks[name+'_even_longitudinal']=all(abs(pos[k]-neg[k])<1e-10 for k in ('CLtot','CDff','Cmtot'))
    checks['positive_controls_signs']=(variants['aileron_plus']['summary']['coefficients']['Cltot']>0 and
        variants['rudder_plus']['summary']['coefficients']['Cntot']>0 and
        variants['elevator_plus']['summary']['coefficients']['Cmtot']<basec['Cmtot'])
    sensitivity={}
    for key in ('CLtot','CDff','Cmtot'):
        coarse=variants['mesh_coarse']['summary']['coefficients'][key];fine=variants['mesh_fine']['summary']['coefficients'][key]
        sensitivity[key]={'coarse':coarse,'standard':basec[key],'fine':fine,
            'standard_to_fine_relative':abs(fine-basec[key])/abs(fine),'coarse_to_standard_relative':abs(basec[key]-coarse)/abs(basec[key])}
        checks['mesh_'+key]=abs(fine-basec[key])<=max(.002 if abs(fine)<1e-4 else 0.,.02*abs(fine))
    fd={}
    for var,deriv,suffix in [('alpha','a',''),('elevator','d',1)]:
        for coefficient,prefix in [('CLtot','CL'),('Cmtot','Cm')]:
            derivative=base['summary']['derivatives'][prefix+deriv]
            analytic=derivative[suffix] if var=='elevator' else derivative*math.pi/180
            finite=(variants[var+'_plus']['summary']['coefficients'][coefficient]-variants[var+'_minus']['summary']['coefficients'][coefficient])/.1
            fd[var+'_'+prefix]={'analytic_per_degree':analytic,'central_difference':finite,'relative_error':abs(finite-analytic)/abs(analytic)}
            tolerance=.002 if var=='elevator' else 1e-4
            fd[var+'_'+prefix]['relative_tolerance']=tolerance
            checks['derivative_'+var+'_'+prefix]=math.isclose(finite,analytic,rel_tol=tolerance,abs_tol=1e-7)
            if var=='elevator':
                fine=(variants['elevator_fine_plus']['summary']['coefficients'][coefficient]-variants['elevator_fine_minus']['summary']['coefficients'][coefficient])/.004
                fd[var+'_'+prefix]['fine_difference']=fine
                checks['derivative_step_'+prefix]=math.isclose(finite,fine,rel_tol=1e-6,abs_tol=1e-8)
    # Reference translation is an explicitly altered diagnostic contract, not a new design geometry.
    original=variants['beta_plus'];contract=json.loads((root/'runs'/original['run_id']/'aero_contract.json').read_text('utf-8'))
    old=contract['references']['moment_reference_geometry_m'].copy();new=np.array(old)+[.3,.1,.2]
    contract['references']['moment_reference_geometry_m']=new.tolist();shiftwork=work/'reference_shift';shiftwork.mkdir()
    shifted=solve(contract,tool_paths(root)['avl'],shiftwork);b=original['summary']
    f,m=transfer_wrench(body_vectors(b['force_body_n']),body_vectors(b['moment_body_nm']),old,new)
    checks['reference_shift']=bool(np.allclose(f,shifted['force_body_n'],atol=1e-8) and np.allclose(m,shifted['moment_body_nm'],atol=1e-7))
    shift={'old_reference_m':old,'new_reference_m':new.tolist(),'maximum_moment_error_nm':float(np.max(np.abs(m-shifted['moment_body_nm'])))}
    # Direct left-right normal-load pairing (no global cancellation only check).
    loads=json.loads((root/'runs'/base['run_id']/'strip_loads.json').read_text('utf-8'))
    for name in ('MainWing','HorizontalTail'):
        right=sorted([x for x in loads['strips'] if x['surface']==name],key=lambda x:x['y_le_m'])
        left=sorted([x for x in loads['strips'] if x['surface']==name+' (YDUP)'],key=lambda x:-x['y_le_m'])
        checks[name+'_strip_symmetry']=all(abs(x['cn']-y['cn'])<1e-10 and abs(x['y_le_m']+y['y_le_m'])<1e-10 for x,y in zip(right,left))
    data=build_bundle(p,root,s,g,base);(work/'baseline.wdh').write_bytes(data);opened=read_bundle(data)
    checks['archive_reopen']=opened['aero_records']==[base] and opened['current_source_matches']
    public=public_cases(work,tool_paths(root)['avl']);ellip=public['results']['ellip']['lifting_line_comparison']
    checks['public_elliptic_lift']=abs(ellip['cl_relative_difference'])<.03
    checks['public_elliptic_induced_drag']=abs(ellip['induced_cd_relative_difference'])<.03
    vc=public['results']['vanilla']['coefficients'];checks['public_vanilla_symmetry']=max(abs(vc[k]) for k in ('CYtot','Cltot','Cntot'))<1e-10
    checks['source_unchanged']=start_hashes==source_hashes()
    result={'version':__version__,'passed':all(checks.values()),'checks':checks,'source_hashes':start_hashes,'designs':rows,
        'variants':{k:{'run_id':a['run_id'],'coefficients':a['summary']['coefficients'],'checks_passed':all(c['passed'] for c in a['summary']['checks'])} for k,a in variants.items()},
        'mesh_sensitivity':sensitivity,'derivative_check':fd,'reference_shift':shift,'public_examples':public,
        'maximum_audited_load_coefficient_error':max(c.get('coefficient_error',0.) for a in [base,*variants.values()] for c in a['summary']['checks']),
        'physical_validation_passed':False,'calibration_performed':False,'trim_solved':False,
        'evidence':'public solver regression + independent ideal theory + symmetry + numerical sensitivity; no experimental aircraft accuracy claim'}
    write_json(work/'summary.json',result);print('passed',result['passed'],'checks',len(checks),flush=True)
    return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(main(sys.argv[1]))
