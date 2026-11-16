from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import json
import math
import numpy as np
import pytest
from wingdesignhub.aircraft_drag import DragOptions,body_friction,finish_ledger
from wingdesignhub.xfoil_polars import PolarError,PolarSpec,commands,parse_polar,interpolate,run_polar


def polar_text():
    return '''XFOIL Version 6.99
1 1 Reynolds number fixed Mach number fixed
xtrf = 1.000 (top) 1.000 (bottom)
Mach = 0.100 Re = 1.000 e 6 Ncrit = 9.000
alpha CL CD CDp CM Top_Xtr Bot_Xtr
-2.000 -0.2000 0.00600 0.00100 0.0000 0.5000 0.3000
0.000 0.0000 0.00500 0.00100 0.0000 0.4000 0.4000
2.000 0.2000 0.00600 0.00100 0.0000 0.3000 0.5000
'''


def test_condition_readback_and_missing_point_no_gap_bridging():
    spec=PolarSpec(1e6,.1,(-.2,0.,.2));p=parse_polar(polar_text(),spec)
    assert len(p['rows'])==3
    for wrong in [polar_text().replace('1.000 e 6','1.100 e 6'),polar_text().replace('0.100 Re','0.150 Re'),
                  polar_text().replace('9.000','8.000'),polar_text().replace('1.000 (top)','0.100 (top)'),polar_text().replace('6.99','6.98')]:
        with pytest.raises(PolarError) as error:parse_polar(wrong,spec)
        assert error.value.status=='polar_invalid'
    missing='\n'.join(line for line in polar_text().splitlines() if not line.startswith('0.000'))
    with pytest.raises(PolarError) as error:parse_polar(missing,spec)
    assert error.value.status=='polar_missing' and error.value.context['cl']==0
    with pytest.raises(PolarError):parse_polar(polar_text()+'2.000 0.2000 0.006 0.001 0 0.3 0.5\n',spec)


def test_interpolation_matches_independent_bilinear_equation_and_rejects_extrapolation():
    # Affine in cl and ln(Re); off-grid reference is analytically known.
    polars=[]
    for re in (1e6,4e6):
        rows=[{'requested_cl':cl,'cd':.005+.002*cl+.001*math.log(re/1e6),'cm':0.,'alpha_deg':cl*10} for cl in (-.2,.3)]
        polars.append({'reynolds':re,'cl_grid':[-.2,.3],'rows':rows})
    expected=.005+.002*.1+.001*math.log(2)
    assert interpolate(polars,2e6,.1)['cd']==pytest.approx(expected,abs=1e-14)
    for re,cl in [(1e5,.1),(5e6,.1),(2e6,.31),(2e6,-.21),(float('nan'),0)]:
        with pytest.raises(PolarError) as error:interpolate(polars,re,cl)
        assert error.value.status=='polar_out_of_domain'
    broken=deepcopy(polars);broken[0]['rows'].pop()
    with pytest.raises(PolarError,match='缺失点'):interpolate(broken,2e6,.1)


@pytest.mark.parametrize('options',[{'re_stations':2},{'panels':100},{'area_samples':True},{'cl_step':.2},
    {'ncrit':0},{'trip_top':0},{'cooling_cd':-.01},{'strut_crossflow_cd':float('nan')},{'cache_only':1}])
def test_options_reject_invalid_assumptions(options):
    with pytest.raises(ValueError):DragOptions(**options).validate()


@pytest.mark.parametrize('kwargs',[{'reynolds':1e5},{'mach':.31},{'cl_grid':(1.3,)}])
def test_polar_domain_diagnostic(kwargs):
    with pytest.raises(PolarError) as e:replace(PolarSpec(1e6,.1,(0.,)),**kwargs).validate()
    assert e.value.status=='polar_out_of_domain'


def test_flap_condition_is_explicit_and_has_correct_sign():
    text=commands(PolarSpec(2e6,.2,(-.1,0.),flap_deg=-6.5))
    assert 'FLAP\n0.7\n0.0\n-6.5\nEXEC' in text and 'PSAV analyzed_foil.dat' in text
    assert 'FLAP' not in commands(PolarSpec(2e6,.2,(0.,)))


def test_body_drag_against_independent_tabulated_formula_value():
    cf,ff=body_friction(1e7,5.)
    assert cf==pytest.approx(.003003713133159046,rel=1e-10)
    assert ff==pytest.approx(1.1901640786499874,rel=1e-10)
    with pytest.raises(ValueError):body_friction(1e4,5)


def ledger_rows():
    return [{'component':name,'contribution':kind,'cd':.001} for kind,names in {
        'induced':['lifting_system'],'profile':['MainWing','HorizontalTail','VerticalTail'],
        'body':['Fuselage','Spinner','NoseFairing','LeftFairing','RightFairing','NoseStrut','LeftStrut','RightStrut'],
        'allowance':['junction','cooling','roughness']}.items() for name in names]


def test_ledger_has_complete_unique_ownership_and_no_input_mutation():
    rows=ledger_rows();original=deepcopy(rows);r=finish_ledger(rows,2000,12)
    assert r['cd_total']==pytest.approx(.015) and r['drag_n']==pytest.approx(360) and rows==original
    with pytest.raises(ValueError,match='重复'):finish_ledger(rows+[rows[0]],2000,12)
    with pytest.raises(ValueError,match='缺项'):finish_ledger(rows[:-1],2000,12)
    with pytest.raises(ValueError,match='归属'):finish_ledger(rows+[{'component':'MainWing','contribution':'body','cd':.005}],2000,12)
    r['rows'][1]['cd']=-.001
    with pytest.raises(ValueError,match='无效'):finish_ledger(r['rows'],2000,12)


@pytest.fixture(scope='module')
def native(tmp_path_factory):
    pytest.importorskip('openvsp');pytest.importorskip('fastga')
    if not all(Path(p).is_file() for p in ('C:/apps/avl/avl.exe','C:/apps/XFOIL6.99/xfoil.exe')):pytest.skip('native AVL/XFOIL unavailable')
    from wingdesignhub.requirements import DesignProject
    from wingdesignhub.sizing_service import run_sizing
    from wingdesignhub.geometry_service import run_aircraft_geometry
    from wingdesignhub.trim_service import run_aircraft_trim
    from wingdesignhub.drag_service import run_aircraft_drag
    root=tmp_path_factory.mktemp('aircraft_drag');p=DesignProject().confirmed();s=run_sizing(p,root)
    g=run_aircraft_geometry(p,root,s['run_id']);t=run_aircraft_trim(p,root,g['run_id']);d=run_aircraft_drag(p,root,t['run_id'])
    assert d['status']=='drag_checked_with_limits',d
    return root,p,s,g,t,d


def test_native_drag_lineage_symmetry_area_exclusion_and_no_double_count(native):
    from wingdesignhub.service import get_results
    root,p,s,g,t,d=native;summary=d['summary'];ledger=summary['ledger'];work=root/'runs'/d['run_id']
    assert get_results(root,d['run_id'])==d
    assert summary['flow']==t['summary']['flow'] and summary['references']==t['summary']['references']
    assert summary['components']['induced']==t['summary']['coefficients']['CDff']
    assert ledger['cd_total']==pytest.approx(sum(summary['components'].values()),abs=1e-12)
    assert all(row['cd']>0 for row in ledger['rows'])
    assert not summary['mission_polar_updated'] and not summary['viscous_retrimmed']
    areas=json.loads((work/'drag_geometry.json').read_text('utf-8'))
    assert all(x['points']>300 for x in areas['airfoils'].values())
    assert any(x['exposed_fraction']==0 for x in areas['strips']) and any(0<x['exposed_fraction']<1 for x in areas['strips'])
    queries=json.loads((work/'profile_queries.json').read_text('utf-8'))
    for name in ('MainWing','HorizontalTail'):
        left=sum(x['cd_aircraft'] for x in queries if x['surface']==name+' (YDUP)')
        right=sum(x['cd_aircraft'] for x in queries if x['surface']==name)
        assert left==pytest.approx(right,abs=1e-10)
    assert summary['polar_coverage'][1]['flap_deg']==t['summary']['trim']['elevator_deg']
    tail=np.loadtxt(work/'polars/HorizontalTail/0/analyzed_foil.dat')
    assert tail[[0,-1],1].mean()>0  # negative elevator is trailing-edge up


def test_native_cache_reuse_and_missing_cache_return_auditable_status(native):
    from wingdesignhub.drag_service import run_aircraft_drag
    from wingdesignhub.project_archive import build_bundle,read_bundle
    root,p,s,g,t,d=native
    hit=run_aircraft_drag(p,root,t['run_id'],DragOptions(cache_only=True))
    assert hit['status']=='drag_checked_with_limits',hit
    assert hit['summary']['ledger']==d['summary']['ledger']
    assert sum(x['cache_hits'] for x in hit['summary']['polar_coverage'])==9
    missing=run_aircraft_drag(p,root,t['run_id'],DragOptions(ncrit=8.,cache_only=True))
    assert missing['status']=='polar_missing' and 'summary' not in missing and 'report.html' in missing['artifact_hashes']
    assert read_bundle(build_bundle(p,root,s,g,trim_record=t,drag_record=missing))['drag_records']==[missing]


def test_native_cache_corruption_is_rejected_and_restored(native):
    root,p,s,g,t,d=native;work=root/'runs'/d['run_id'];sub=work/'polars/MainWing/0'
    metadata=json.loads((sub/'cache.json').read_text('utf-8'));path=root/'local/cache/xfoil'/metadata['cache_key']/'polar.txt'
    original=path.read_bytes();spec=PolarSpec(**metadata['identity']['spec'])
    try:
        path.write_text('corrupt',encoding='utf-8')
        with pytest.raises(PolarError,match='缓存损坏'):run_polar(sub/'foil.dat',spec,'C:/apps/XFOIL6.99/xfoil.exe',root/'corrupt_probe',root/'local/cache/xfoil')
    finally:path.write_bytes(original)


def test_native_missing_point_recovery_uses_real_same_condition_output(native):
    from wingdesignhub.xfoil_polars import read_attempts
    root,p,s,g,t,d=native;foil=root/'runs'/d['run_id']/'airfoils/MainWing.dat'
    spec=PolarSpec(6236874.715112676,.19547158457194648,(0.,.1,.2,.3,.4,.5),panels=240)
    work=root/'recovery_probe';cache=root/'recovery_cache'
    result=run_polar(foil,spec,'C:/apps/XFOIL6.99/xfoil.exe',work,cache)
    assert result.get('recovery') and result['recovery'][0]['cl']==.1
    assert read_attempts(work,spec)['rows']==result['rows']
    repeated=run_polar(foil,spec,'C:/apps/XFOIL6.99/xfoil.exe',root/'recovery_cached',cache,True)
    assert repeated['cache_hit'] and repeated['rows']==result['rows']
    assert (work/'recovery_0/stdout.log').is_file()


def test_native_archive_report_and_semantic_tamper_rejection(native):
    from wingdesignhub.project_archive import build_bundle,read_bundle,digest,encoded
    from wingdesignhub.service import generate_report
    from test_project_archive import edit_zip
    root,p,s,g,t,d=native;data=build_bundle(p,root,s,g,trim_record=t,drag_record=d)
    assert read_bundle(data)['drag_records']==[d] and '配平阻力账目报告' in generate_report(d,root=root)
    def corrupt(files):
        prefix='runs/'+d['run_id']+'/';c=json.loads(files[prefix+'drag_contract.json']);c['flow']['speed_m_s']+=1
        files[prefix+'drag_contract.json']=encoded(c);r=json.loads(files[prefix+'result.json'])
        r['artifact_hashes']['drag_contract.json']=digest(files[prefix+'drag_contract.json']);files[prefix+'result.json']=encoded(r)
        m=json.loads(files['manifest.json']);m['files']={n:digest(b) for n,b in files.items() if n!='manifest.json'};files['manifest.json']=encoded(m)
    with pytest.raises(ValueError,match='阻力工况'):read_bundle(edit_zip(data,corrupt))


def test_native_cli_missing_polar_nonzero_and_report(native,tmp_path):
    import subprocess,sys
    root,p,s,g,t,d=native
    options=tmp_path/'drag.json';options.write_text(json.dumps({'ncrit':7.,'cache_only':True}),encoding='utf-8')
    cmd=[sys.executable,'-X','utf8','-m','wingdesignhub.cli','drag','--root',str(root),'--trim-run-id',t['run_id'],'--drag-options',str(options)]
    r=subprocess.run(cmd,capture_output=True,text=True,encoding='utf-8',timeout=180)
    assert r.returncode==1 and json.loads(r.stdout)['status']=='polar_missing',r.stderr


def test_native_ui_save_reopen_and_stale_assumptions(native,monkeypatch):
    from streamlit.testing.v1 import AppTest
    from wingdesignhub import sizing_service,geometry_service,geometry_ui,trim_ui,drag_ui,project_ui,project_archive
    root,p,s,g,t,d=native
    monkeypatch.setattr(sizing_service,'run_sizing',lambda *a:s);monkeypatch.setattr(geometry_service,'run_aircraft_geometry',lambda *a:g)
    monkeypatch.setattr(trim_ui,'run_aircraft_trim',lambda *a:t);monkeypatch.setattr(drag_ui,'run_aircraft_drag',lambda *a:d)
    render=geometry_ui.render;monkeypatch.setattr(geometry_ui,'render',lambda p,ignored,r:render(p,root,r))
    save=project_ui.save_controls;monkeypatch.setattr(project_ui,'save_controls',lambda p,ignored,r=None,key='design':save(p,root,r,key))
    listing=project_archive.list_saved;load=project_archive.load_saved
    monkeypatch.setattr(project_archive,'list_saved',lambda ignored:listing(root));monkeypatch.setattr(project_archive,'load_saved',lambda ignored,rid:load(root,rid))
    app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py'),default_timeout=30).run()
    app.checkbox[0].check().run();app.button(key='run_sizing').click().run(timeout=30)
    app.button(key='generate_aircraft_geometry').click().run(timeout=30);app.button(key='run_aircraft_trim').click().run(timeout=30)
    app.button(key='run_aircraft_drag').click().run(timeout=30)
    assert not app.exception and any('阻力账目计算完成' in x.value for x in app.success)
    app.number_input(key='drag_ncrit').set_value(8.).run();assert any('阻力假设已更改' in x.value for x in app.warning)
    app.button(key='design_save_local').click().run();saved=listing(root)[0]
    app.selectbox(key='saved_archive_choice').set_value(saved['archive_id']).run();app.button(key='open_saved_design').click().run(timeout=30)
    assert not app.exception and any('阻力账目计算完成' in x.value for x in app.success)
    assert load(root,saved['archive_id'])['drag_records']==[d]
    app.button(key='new_blank_design').click().run();assert 'aircraft_drag_result' not in app.session_state
