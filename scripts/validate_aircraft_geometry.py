"""V0.2.1 demand-to-native-geometry evidence; all aircraft inputs are synthetic."""
from dataclasses import replace
from pathlib import Path
import importlib.util
import json
import sys
import unittest
import numpy as np
from wingdesignhub import __version__
from wingdesignhub.requirements import DesignProject,MissionRequirement,WeightRequirement
from wingdesignhub.aircraft_geometry import GeometryOptions
from wingdesignhub.sizing_service import run_sizing
from wingdesignhub.geometry_service import run_aircraft_geometry
from wingdesignhub.service import get_results,write_json
from wingdesignhub.project_archive import build_bundle,read_bundle
from wingdesignhub.adapters import execute,sha256,tool_paths

UPSTREAM_TESTS=['test_SetDriverGroup','test_SetXSecWidthHeight','test_GetVSPAERORefWingID',
                'test_ComputeDegenGeom','test_CompPnt01','test_SetSetFlag','test_WriteVSPFile','test_ReadVSPFile']


def upstream(path):
    spec=importlib.util.spec_from_file_location('installed_vsp_examples',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    suite=unittest.TestSuite(module.TestOpenVSP(name) for name in UPSTREAM_TESTS)
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    write_json('upstream_summary.json',{'passed':result.wasSuccessful(),'tests_run':result.testsRun,
               'methods':UPSTREAM_TESTS,'source_sha256':sha256(path),
               'source':'OpenVSP 3.56.0 installed python/openvsp/openvsp/tests/test_vsp_api.py'})
    return 0 if result.wasSuccessful() else 1


def mesh_areas(path):
    areas={}
    for m in json.loads(path.read_text('utf-8')):
        if m['name'] not in ('MainWing','HorizontalTail','VerticalTail','Fuselage'):continue
        p=np.array(m['vertices_m']);t=np.array(m['triangles']);a,b,c=p[t[:,0]],p[t[:,1]],p[t[:,2]]
        areas[m['name']]=areas.get(m['name'],0.)+float(np.linalg.norm(np.cross(b-a,c-a),axis=1).sum()/2)
    return areas


def main(target):
    root=Path(__file__).resolve().parents[1];work=Path(target).resolve();work.mkdir(parents=True,exist_ok=False)
    p=DesignProject();cases={
        'baseline':p,'payload_450':replace(p,payload_kg=450.),
        'range_1200km':replace(p,mission=MissionRequirement('range_only',1200000.,None)),
        'endurance_4h':replace(p,mission=MissionRequirement('endurance_only',None,14400.)),
        'endurance_5h':replace(p,mission=MissionRequirement('endurance_only',None,18000.)),
        'loiter_1h':replace(p,mission=MissionRequirement('transit_loiter',400000.,3600.)),
        'loiter_2h':replace(p,mission=MissionRequirement('transit_loiter',400000.,7200.)),
        'aspect_ratio_9':replace(p,sizing=replace(p.sizing,aspect_ratio=9.)),
        'fixed_1400':replace(p,weight=WeightRequirement('fixed',1400.)),
        'upper_1000_infeasible':replace(p,weight=WeightRequirement('upper_bound',1000.)),
    }
    rows={};checks={};runs={}
    for name,p in cases.items():
        p=p.confirmed();s=run_sizing(p,root);get_results(root,s['run_id'])
        g=run_aircraft_geometry(p,root,s['run_id']);get_results(root,g['run_id'])
        write_json(work/(name+'.json'),{'overall':s,'geometry':g})
        runs[name]={'overall':s['run_id'],'geometry':g['run_id']}
        checks[name+'_geometry']=g['status']=='geometry_checked_with_limits'
        expected='constraints_not_met' if name=='upper_1000_infeasible' else 'concept_checked_with_limits'
        checks[name+'_overall_status']=s['status']==expected and g['summary']['parent_status']==expected
        summary=s['summary'];ref=g['summary']['references']
        rows[name]={'mtow_kg':summary['design_mtow_kg'],'fuel_kg':summary['mission']['block_fuel_kg'],
                    'power_kw':summary['power']['installed_power_w']/1000.,'area_m2':ref['area_m2'],
                    'span_m':ref['span_m'],'mac_m':ref['chord_m'],'cg_x_m':ref['moment_reference_geometry_m'][0],
                    'geometry_check_count':len(g['summary']['checks'])}
        print(name,s['status'],g['status'],rows[name]['span_m'],flush=True)
        if name=='baseline':
            base_s=s;base_g=g;base_p=p
    for a,b in [('baseline','payload_450'),('baseline','range_1200km'),('endurance_4h','endurance_5h'),('loiter_1h','loiter_2h')]:
        checks[b+'_positive_transmission']=all(rows[b][k]>rows[a][k] for k in ('mtow_kg','fuel_kg','power_kw','area_m2','span_m'))
    checks['aspect_ratio_transmission']=rows['aspect_ratio_9']['span_m']>rows['baseline']['span_m'] and rows['aspect_ratio_9']['mac_m']<rows['baseline']['mac_m']
    checks['legacy_overall_unchanged']=abs(rows['baseline']['mtow_kg']-1229.4159528684945)<1e-8
    fine=run_aircraft_geometry(base_p,root,base_s['run_id'],GeometryOptions(tessellation=2));get_results(root,fine['run_id'])
    write_json(work/'refined.json',fine)
    coarse_area=mesh_areas(root/'runs'/base_g['run_id']/'surface_mesh.json');fine_area=mesh_areas(root/'runs'/fine['run_id']/'surface_mesh.json')
    relative={k:abs(fine_area[k]/v-1) for k,v in coarse_area.items()}
    checks['tessellation_geometry_area_2pct']=all(v<.02 for v in relative.values())
    checks['tessellation_reference_invariant']=fine['summary']['references']==base_g['summary']['references'] and fine['summary']['passed']
    data=build_bundle(base_p,root,base_s,base_g);(work/'complete-aircraft.wdh').write_bytes(data);opened=read_bundle(data)
    checks['portable_geometry_exact']=opened['records']==[base_s] and opened['geometry_records']==[base_g] and opened['current_source_matches']
    official=work/'upstream';official.mkdir()
    source=Path(tool_paths(root)['openvsp'])/'python/openvsp/openvsp/tests/test_vsp_api.py'
    execute([sys.executable,'-X','utf8',str(Path(__file__).resolve()),'--upstream',str(source)],official,timeout=60)
    official_summary=json.loads((official/'upstream_summary.json').read_text('utf-8'));checks['installed_api_examples']=official_summary['passed']
    summary={'version':__version__,'passed':all(checks.values()),'checks':checks,'cases':rows,'runs':runs,
             'refined_run':fine['run_id'],'geometric_surface_area_sensitivity':relative,
             'geometry_area_note':'triangulated component surface areas before intersections; not wetted area or aerodynamic convergence',
             'installed_examples':official_summary,'physical_validation_passed':False,'aerodynamics_run':False,
             'data_role':'synthetic software/numerical verification; no calibration or independent physical dataset',
             'script_sha256':sha256(Path(__file__)),
             'evidence_hashes':{p.relative_to(work).as_posix():sha256(p) for p in work.rglob('*') if p.is_file()}}
    write_json(work/'summary.json',summary);return 0 if summary['passed'] else 1


if __name__=='__main__':
    raise SystemExit(upstream(sys.argv[2]) if sys.argv[1]=='--upstream' else main(sys.argv[1]))
