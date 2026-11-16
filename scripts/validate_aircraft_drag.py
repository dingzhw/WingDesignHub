"""V0.2.4: bounded real-solver evidence and independent, uncalibrated UIUC check."""
from dataclasses import replace
from pathlib import Path
import json
import math
import shutil
import sys
from urllib.request import urlopen
import numpy as np
from wingdesignhub import __version__
from wingdesignhub.requirements import DesignProject
from wingdesignhub.sizing_service import run_sizing
from wingdesignhub.geometry_service import run_aircraft_geometry,source_hashes
from wingdesignhub.trim_service import run_aircraft_trim
from wingdesignhub.aircraft_trim import TrimOptions
from wingdesignhub.aircraft_drag import DragOptions,body_friction
from wingdesignhub.drag_service import run_aircraft_drag
from wingdesignhub.xfoil_polars import PolarSpec,run_polar,interpolate,PolarError
from wingdesignhub.adapters import sha256,tool_paths,execute
from wingdesignhub.service import write_json,get_results
from wingdesignhub.project_archive import build_bundle,read_bundle

PUBLIC={
    'e387.dat':('https://m-selig.ae.illinois.edu/ads/coord_seligFmt/e387.dat','98aa8a4076edbfd1c52e3a2d0cf17b1ef1cbc51ae5da3ab8e5361047b89ee523'),
    'e387_c_drg.txt':('https://m-selig.ae.illinois.edu/pd/pub/lsat/vol4/e387_c_drg.txt','ffd629b2baec8eca82d155081f0f0d9a0d8a496cf4ee0a7c300773d9ff55fb76')}


def public_check(root,work,exe):
    work.mkdir();sources={}
    for name,(url,digest) in PUBLIC.items():
        local=root/'local/v024-public-sources'/name
        data=local.read_bytes() if local.is_file() else urlopen(url,timeout=30).read()
        path=work/name;path.write_bytes(data)
        if sha256(path)!=digest:raise ValueError('公开数据变更：'+name)
        sources[name]={'url':url,'sha256':digest}
    blocks=(work/'e387_c_drg.txt').read_text('utf-8').split('Average Reynolds #:')[1:];cases=[]
    for target in (300000,500000):
        block=min(blocks,key=lambda b:abs(float(b.strip().splitlines()[0])-target))
        re=float(block.strip().splitlines()[0]);rows=[]
        for line in block.split('Spanwise Cd\'s >>>')[1].splitlines():
            try:values=list(map(float,line.split()))
            except ValueError:continue
            if len(values)>=3 and .25<=values[1]<=1.:rows.append(values[:3])
        # Report p.3 gives V=24.38 m/s at Re=500000 for the 0.305 m model.
        # Mach is an explicit low-speed approximation, not a recorded test input.
        mach=24.38*(re/500000)/343.;grid=tuple(row[1] for row in rows)
        spec=PolarSpec(re,mach,grid,panels=240)
        result=run_polar(work/'e387.dat',spec,exe,work/f're_{int(re)}')
        points=[{'experimental_alpha_deg':a,'cl':cl,'experimental_cd':cd,'xfoil_cd':r['cd'],
                 'relative_cd_error':r['cd']/cd-1} for (a,cl,cd),r in zip(rows,result['rows'])]
        cases.append({'reynolds':re,'mach_approximation':mach,'ncrit_assumption':9.,'trip_top':1.,'trip_bottom':1.,
                      'points':points,'max_abs_relative_error':max(abs(x['relative_cd_error']) for x in points)})
    return {'role':'independent airfoil-method check, no calibration; not the project NACA airfoils or whole aircraft',
            'report':'https://m-selig.ae.illinois.edu/uiuc_lsat/vol4/NREL-SR-500-34515.pdf',
            'attribution':'UIUC Low-Speed Airfoil Test program; Selig & McGranahan, NREL/SR-500-34515, revised October 2004',
            'conditions':'E387(E), clean model, measured Re and cl; nominal coordinates; Mach approximated; Ncrit=9 fixed before comparison, actual transition not matched',
            'calibration_performed':False,'sources':sources,'cases':cases,'diagnostic_relative_band':.2,
            'within_diagnostic_band':all(c['max_abs_relative_error']<=.2 for c in cases),
            'physical_validation_passed':False}


def brief(r):
    if 'summary' not in r:return {'run_id':r['run_id'],'status':r['status'],'error':r.get('error'),'context':r.get('diagnostic_context')}
    s=r['summary'];return {'run_id':r['run_id'],'status':r['status'],'cd_total':s['ledger']['cd_total'],'drag_n':s['ledger']['drag_n'],
            'lift_to_drag':s['lift_to_drag'],'components':s['components'],'options':r['options'],'coverage':s['polar_coverage']}


def main(target):
    root=Path(__file__).resolve().parents[1];work=Path(target).resolve();work.mkdir(parents=True,exist_ok=False)
    start=source_hashes();exe=tool_paths(root)['xfoil'];cases={};records={};checks={}
    p=DesignProject().confirmed();s=run_sizing(p,root);g=run_aircraft_geometry(p,root,s['run_id']);t=run_aircraft_trim(p,root,g['run_id'])
    assert t['status']=='trim_checked_with_limits',t
    def run(name,options=None,trim=t):
        r=run_aircraft_drag(p,root,trim['run_id'],options);get_results(root,r['run_id']);records[name]=r;cases[name]=brief(r)
        write_json(work/'checkpoint.json',{'source_hashes':start,'sizing_run_id':s['run_id'],'geometry_run_id':g['run_id'],'trim_run_id':t['run_id'],'cases':cases})
        print(name,r['status'],cases[name].get('cd_total'),flush=True);return r
    base=run('baseline')
    if base['status']!='drag_checked_with_limits':raise RuntimeError(base)
    run('cache_only',DragOptions(cache_only=True))
    run('panels_160',DragOptions(panels=160))
    run('polar_refined',DragOptions(re_stations=5,cl_step=.05))
    run('area_refined',DragOptions(area_samples=24))
    run('body_mesh_refined',DragOptions(geometry_tessellation=2))
    run('early_transition',DragOptions(trip_top=.05,trip_bottom=.05))
    run('strut_lower',DragOptions(strut_crossflow_cd=.8))
    run('strut_upper',DragOptions(strut_crossflow_cd=1.6))
    run('missing_polar',DragOptions(ncrit=8.,cache_only=True))
    end=run_aircraft_trim(p,root,g['run_id'],TrimOptions(mass_state='mission_end'));run('mission_end',trim=end)
    fast=run_aircraft_trim(p,root,g['run_id'],TrimOptions(speed_m_s=65.));run('speed_65',trim=fast)
    for name,r in records.items():
        checks[name+'_state']=r['status']==('polar_missing' if name=='missing_polar' else 'drag_checked_with_limits')
    # Later checks only inspect complete numerical cases; every failure stays in checkpoint.
    if not all(checks.values()):
        write_json(work/'summary.json',{'passed':False,'checks':checks,'cases':cases});return 1
    b=base['summary'];bw=root/'runs'/base['run_id'];diffs={}
    for name,key in [('panels_160','profile'),('polar_refined','profile'),('body_mesh_refined','body')]:
        diffs[name]=abs(cases[name]['components'][key]/b['components'][key]-1)
        checks[name+'_sensitivity']=diffs[name]<.02
    ga=json.loads((bw/'drag_geometry.json').read_text('utf-8'));gb=json.loads((root/'runs'/records['area_refined']['run_id']/'drag_geometry.json').read_text('utf-8'))
    for surface in ('MainWing','HorizontalTail','VerticalTail'):
        a=sum(x['exposed_area_m2'] for x in ga['strips'] if x['surface'].replace(' (YDUP)','')==surface)
        barea=sum(x['exposed_area_m2'] for x in gb['strips'] if x['surface'].replace(' (YDUP)','')==surface)
        diffs['exposed_'+surface]=abs(a/barea-1);checks['area_'+surface]=diffs['exposed_'+surface]<.01
    queries=json.loads((bw/'profile_queries.json').read_text('utf-8'))
    for surface in ('MainWing','HorizontalTail'):
        a=sum(x['cd_aircraft'] for x in queries if x['surface']==surface);c=sum(x['cd_aircraft'] for x in queries if x['surface']==surface+' (YDUP)')
        checks['symmetry_'+surface]=abs(a-c)<1e-10
    checks['induced_once']=b['components']['induced']==t['summary']['coefficients']['CDff']
    checks['sum_and_dimensions']=abs(sum(b['components'].values())-b['ledger']['cd_total'])<1e-10 and abs(b['ledger']['drag_n']/(b['flow']['dynamic_pressure_pa']*b['references']['area_m2'])-b['ledger']['cd_total'])<1e-10
    checks['no_legacy_cd0']=all(row['component']!='CD0' for row in b['ledger']['rows']) and not b['mission_polar_updated']
    checks['cache_identical']=records['cache_only']['summary']['ledger']==b['ledger'] and sum(c['cache_hits'] for c in cases['cache_only']['coverage'])==9
    checks['transition_sensitivity']=cases['early_transition']['components']['profile']>b['components']['profile']
    checks['strut_sensitivity']=cases['strut_lower']['cd_total']<cases['baseline']['cd_total']<cases['strut_upper']['cd_total']
    checks['fuel_state_to_drag']=cases['mission_end']['components']['induced']<b['components']['induced']
    checks['speed_to_reynolds']=cases['speed_65']['coverage'][0]['reynolds'][0]>cases['baseline']['coverage'][0]['reynolds'][0]
    # Compare interpolation with a fresh, exact-condition XFOIL solve at an interior strip.
    sample=min((x for x in queries if x['surface']=='MainWing'),key=lambda x:abs(x['cl']-.5))
    exact=run_polar(bw/'airfoils/MainWing.dat',PolarSpec(sample['reynolds'],b['flow']['mach'],(sample['cl'],),panels=240),exe,work/'direct_strip')
    diffs['direct_strip_cd']=abs(sample['cd']/exact['rows'][0]['cd']-1);checks['direct_strip_interpolation']=diffs['direct_strip_cd']<.02
    polar=run_polar(bw/'airfoils/VerticalTail.dat',PolarSpec(3e6,.18,(-.2,0.,.2)),exe,work/'symmetric_0012')
    checks['xfoil_symmetric_0012']=abs(polar['rows'][0]['cd']-polar['rows'][2]['cd'])<1e-5
    for re,cl in [(1e5,0.),(3e6,.21)]:
        try:interpolate([{**polar,'reynolds':3e6}],re,cl);rejected=False
        except PolarError as exc:rejected=exc.status=='polar_out_of_domain'
        checks[f'query_domain_{re}_{cl}']=rejected
    data=build_bundle(p,root,s,g,trim_record=t,drag_record=base);(work/'baseline.wdh').write_bytes(data)
    checks['archive_roundtrip']=read_bundle(data)['drag_records']==[base]
    missing=records['missing_polar'];checks['failed_archive']=read_bundle(build_bundle(p,root,s,g,trim_record=t,drag_record=missing))['drag_records']==[missing]
    public=public_check(root,work/'public_uiuc',exe);write_json(work/'public_check.json',public)
    print('public independent max errors',[c['max_abs_relative_error'] for c in public['cases']],flush=True)
    checks['source_unchanged']=start==source_hashes()
    result={'version':__version__,'passed':all(checks.values()),'checks':checks,'source_hashes':start,'sizing_run_id':s['run_id'],
            'geometry_run_id':g['run_id'],'trim_run_id':t['run_id'],'cases':cases,'sensitivities':diffs,'baseline_ledger':b['ledger'],
            'public_independent_check':public,'solver_sha256':sha256(exe),'physical_validation_passed':False,'calibration_performed':False,
            'scope':'single inviscid trim state with viscous/profile and nonlifting drag; no mission replacement'}
    write_json(work/'summary.json',result);print('passed',result['passed'],'checks',len(checks),flush=True)
    return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(main(sys.argv[1]))
