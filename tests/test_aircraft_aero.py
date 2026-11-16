from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import json
import math
import numpy as np
import pytest
from wingdesignhub.requirements import DesignProject
from wingdesignhub.aircraft_geometry import build_geometry_contract
from wingdesignhub.sizing_physics import geometry
from wingdesignhub.aircraft_aero import AeroOptions,make_contract,avl_input,commands,trim_interface
from wingdesignhub.avl_aircraft import numbers,labelled,header,parse_total,parse_elements,dimensional_loads


def synthetic():
    p=DesignProject().confirmed();s={'converged':True,'status':'concept_checked_with_limits','geometry':geometry(1200,100,p),
        'cg':{'cg_x_m':2.7},'mission':{'cruise_speed_used_m_s':61.},'design_mtow_kg':1200.}
    r={'run_id':'sizing','input_hash':'synthetic','mode':'overall_sizing','status':s['status'],
       'definition_sha256':p.definition_hash(),'summary':s}
    g=build_geometry_contract(p,r)
    i={'schema_version':1,'source_run_id':'geometry','parent_run_id':'sizing','references':g['references'],
       'surfaces':g['lifting_surfaces'],'coordinates':g['coordinates']}
    return i,p,s


@pytest.mark.parametrize('kwargs',[{'alpha_deg':7},{'beta_deg':6},{'elevator_deg':11},{'aileron_deg':-11},
    {'rudder_deg':float('nan')},{'speed_m_s':True},{'altitude_m':4001},{'mesh_level':True},{'mesh_level':4},{'alpha_deg':None}])
def test_domain_rejection(kwargs):
    with pytest.raises(ValueError):AeroOptions(**kwargs).validate()


def test_flow_defaults_use_solved_task_speed_and_explicit_mass():
    i,p,s=synthetic();c=make_contract(i,p,s);f=c['flow']
    assert f['speed_m_s']==61. and f['mass_kg']==1200
    assert f['dynamic_pressure_pa']==pytest.approx(.5*f['density_kg_m3']*61**2)
    assert f['mach']==pytest.approx(61/math.sqrt(1.4*287.05287*(288.15-.0065*2000)))
    assert f['reynolds_mac']>1e6
    low=make_contract(i,p,s,AeroOptions(mass_kg=900));assert low['flow']['mass_kg']==900
    with pytest.raises(ValueError):make_contract(i,p,s,AeroOptions(mass_kg=1300))
    with pytest.raises(ValueError):make_contract(i,p,s,AeroOptions(speed_m_s=120))


def test_export_preserves_reference_sections_and_declares_controls():
    i,p,s=synthetic();c=make_contract(i,p,s);text=avl_input(c);cmd=commands(c)
    assert text.count('\nSURFACE\n')==3 and text.count('\nYDUPLICATE\n')==2
    assert '\nBODY\n' not in text and '\n0 0 0\n' in text
    lines=text.splitlines();ref=np.array(list(map(float,lines[3].split())))
    np.testing.assert_allclose(ref,[c['references'][k] for k in ('area_m2','chord_m','span_m')],rtol=1e-14)
    sections=[list(map(float,lines[j+1].split())) for j,x in enumerate(lines) if x=='SECTION']
    assert len(sections)==7 and all(row[4]==0 for row in sections)
    assert 'aileron -1.0 0.75 0.0 1.0 0.0 -1.0' in text
    assert 'elevator 1.0 0.7 0.0 1.0 0.0 1.0' in text
    assert 'rudder 1.0 0.7 0.0 0.0 1.0 1.0' in text
    assert '\nMN ' in cmd and '\nD1 D1 0.0\n' in cmd and '\nMRF\n' in cmd
    bad=deepcopy(i);bad['surfaces'][0]['incidence_deg']=2
    with pytest.raises(ValueError,match='零安装角'):make_contract(bad,p,s)


def test_mrf_numeric_precision_fixed_integer_fields_and_errors():
    assert numbers(' 1.000E+00-2.000D-03 | test')==[1.,-.002]
    assert labelled('  85  121009 | Strip #, # Chordwise, First Vortex','Strip #, # Chordwise, First Vortex',3)==[85,12,1009]
    for bad in ('NaN','********','1e309','hello 1.0',''):
        with pytest.raises(ValueError):numbers(bad)
    with pytest.raises(ValueError):labelled('1 | x\n2 | x','x')
    with pytest.raises(ValueError):header('TOT\nVERSION 1.0\nGeometry axis orientation','TOT')


def test_strip_projection_matches_hand_calculated_wrench_and_does_not_invent_tangent_force():
    i,p,s=synthetic();c=make_contract(i,p,s);c['flow']['dynamic_pressure_pa']=100.
    c['references'].update(area_m2=10.,span_m=5.,chord_m=2.,moment_reference_geometry_m=[0.,0.,0.])
    row={'x_le_m':.5,'y_le_m':2.,'z_le_m':0.,'chord_m':2.,'area_m2':1.,'dihedral_deg':0.,
         'ca':.02,'cn':1.,'cm_quarter':-.1,'strip_id':1,'surface':'MainWing'}
    # qA=(2,0,100); position=(1,2,0); local My=-20; global body moment=(-200,-120,+4).
    surf={'name':'MainWing','strips':[row],'coefficients':{'CD':.002,'CL':.1,'CY':.007,'Cl':-.04,'Cm':-.06,'Cn':.0008}}
    t={'Alpha':0,'CXtot':-.002,'CYtot':.007,'CZtot':-.1,'Cltot':-.04,'Cmtot':-.06,'Cntot':.0008}
    data=dimensional_loads([surf],t,c);rr=data['strips'][0]
    np.testing.assert_allclose(rr['point_body_m'],[-1,2,0]);np.testing.assert_allclose(rr['force_body_n'],[-2,0,-100])
    np.testing.assert_allclose(rr['free_moment_body_nm'],[0,-20,0])
    assert not data['complete_six_component_strip_loads']
    assert data['surface_totals'][0]['projected_force_residual_geometry_n'][1]==-7.
    assert all(x['passed'] for x in data['checks'])


@pytest.fixture(scope='module')
def native(tmp_path_factory):
    pytest.importorskip('openvsp');pytest.importorskip('fastga')
    if not Path('C:/apps/avl/avl.exe').is_file():pytest.skip('AVL native executable unavailable')
    from wingdesignhub.sizing_service import run_sizing
    from wingdesignhub.geometry_service import run_aircraft_geometry
    from wingdesignhub.aero_service import run_aircraft_aero
    root=tmp_path_factory.mktemp('aircraft_aero');p=DesignProject().confirmed();s=run_sizing(p,root)
    g=run_aircraft_geometry(p,root,s['run_id']);a=run_aircraft_aero(p,root,g['run_id'])
    assert a['status']=='aero_checked_with_limits',a
    return root,p,s,g,a


def test_native_references_strips_controls_and_trim_state(native):
    root,p,s,g,a=native;out=a['summary'];c=out['coefficients']
    assert all(x['passed'] for x in out['checks']) and out['strip_count']==120
    assert out['references']==g['summary']['references'] and c['Mach']>0
    assert abs(c['CYtot'])<1e-10 and abs(c['Cltot'])<1e-10 and abs(c['Cntot'])<1e-10
    assert out['trim']['status']=='not_trimmed' and not out['mission_polar_updated']
    assert out['derivatives']['Cma']<0 and out['derivatives']['Cmd'][1]<0
    assert out['trim']['level_flight_target_cl']==pytest.approx(s['summary']['design_mtow_kg']*9.80665/(out['flow']['dynamic_pressure_pa']*c['Sref']))
    loads=json.loads((root/'runs'/a['run_id']/'strip_loads.json').read_text('utf-8'))
    assert {x['surface'] for x in loads['strips']}=={'MainWing','MainWing (YDUP)','HorizontalTail','HorizontalTail (YDUP)','VerticalTail'}


def test_native_archive_roundtrip_chain_and_report(native):
    from wingdesignhub.project_archive import build_bundle,read_bundle
    from wingdesignhub.service import generate_report,get_results
    root,p,s,g,a=native;data=build_bundle(p,root,s,g,a);opened=read_bundle(data)
    assert opened['aero_records']==[a] and opened['geometry_records']==[g] and opened['current_source_matches']
    assert get_results(root,a['run_id'])==a
    report=generate_report(a,root=root);assert '尚未配平' in report and 'CDff' in report
    with pytest.raises(ValueError):build_bundle(p,root,s,None,a)
    with pytest.raises(ValueError):build_bundle(p,root,s,g,{**a,'parent_run_id':'wrong'})


def test_native_rejects_changed_project_and_geometry(native):
    from wingdesignhub.aero_service import run_aircraft_aero
    from wingdesignhub.service import write_json
    root,p,s,g,a=native
    with pytest.raises(ValueError,match='需求'):run_aircraft_aero(replace(p,payload_kg=500).confirmed(),root,g['run_id'])
    path=root/'runs'/g['run_id']/'result.json';original=path.read_bytes()
    try:
        write_json(path,{**g,'source_hashes':{}})
        with pytest.raises(ValueError,match='版本'):run_aircraft_aero(p,root,g['run_id'])
    finally:path.write_bytes(original)


def test_native_failed_solver_is_preserved_without_fake_results(native,monkeypatch):
    from wingdesignhub.aero_service import run_aircraft_aero
    from wingdesignhub.project_archive import build_bundle,read_bundle
    root,p,s,g,a=native
    def fail(*args,**kwargs):raise TimeoutError('synthetic timeout')
    monkeypatch.setattr('wingdesignhub.aero_service.solve',fail)
    failed=run_aircraft_aero(p,root,g['run_id'])
    assert failed['status']=='failed' and 'summary' not in failed and 'error.log' in failed['artifact_hashes']
    assert read_bundle(build_bundle(p,root,s,g,failed))['aero_records'][0]['error']=='synthetic timeout'


def test_archive_rejects_changed_aero_reference_even_when_hashes_are_rebuilt(native):
    from io import BytesIO
    from zipfile import ZipFile,ZIP_DEFLATED
    from wingdesignhub.project_archive import build_bundle,read_bundle,digest,encoded
    root,p,s,g,a=native
    with ZipFile(BytesIO(build_bundle(p,root,s,g,a))) as z:files={n:z.read(n) for n in z.namelist()}
    prefix='runs/'+a['run_id']+'/';name=prefix+'aero_contract.json';value=json.loads(files[name])
    value['references']['area_m2']*=1.1;files[name]=encoded(value)
    r=json.loads(files[prefix+'result.json']);r['artifact_hashes']['aero_contract.json']=digest(files[name]);files[prefix+'result.json']=encoded(r)
    m=json.loads(files['manifest.json']);m['files']={n:digest(b) for n,b in files.items() if n!='manifest.json'};files['manifest.json']=encoded(m)
    stream=BytesIO()
    with ZipFile(stream,'w',ZIP_DEFLATED) as z:
        for n,b in files.items():z.writestr(n,b)
    with pytest.raises(ValueError,match='气动来源'):read_bundle(stream.getvalue())


def test_native_aero_ui_runs_changes_condition_saves_and_reopens(native,monkeypatch):
    from streamlit.testing.v1 import AppTest
    from wingdesignhub import sizing_service,geometry_service,geometry_ui,aero_ui,project_ui,project_archive
    root,p,s,g,a=native
    monkeypatch.setattr(sizing_service,'run_sizing',lambda *args:s)
    monkeypatch.setattr(geometry_service,'run_aircraft_geometry',lambda *args:g)
    monkeypatch.setattr(aero_ui,'run_aircraft_aero',lambda *args:a)
    render=geometry_ui.render;monkeypatch.setattr(geometry_ui,'render',lambda p,ignored,r:render(p,root,r))
    save=project_ui.save_controls;monkeypatch.setattr(project_ui,'save_controls',lambda p,ignored,r=None,key='design':save(p,root,r,key))
    listing=project_archive.list_saved;load=project_archive.load_saved
    monkeypatch.setattr(project_archive,'list_saved',lambda ignored:listing(root))
    monkeypatch.setattr(project_archive,'load_saved',lambda ignored,rid:load(root,rid))
    app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py')).run(timeout=30)
    app.checkbox[0].check().run();app.button(key='run_sizing').click().run(timeout=30)
    app.button(key='generate_aircraft_geometry').click().run(timeout=30);app.button(key='run_aircraft_aero').click().run(timeout=30)
    assert not app.exception and any('AVL 全机升力面计算完成' in x.value for x in app.success)
    app.number_input(key='aero_alpha').set_value(4.).run()
    assert any('当前输入已更改' in x.value for x in app.warning)
    app.button(key='design_save_local').click().run();saved=listing(root)[0]
    app.selectbox(key='saved_archive_choice').set_value(saved['archive_id']).run();app.button(key='open_saved_design').click().run(timeout=30)
    assert not app.exception and any('AVL 全机升力面计算完成' in x.value for x in app.success)
    reopened=load(root,saved['archive_id']);assert reopened['aero_records']==[a]
    app.button(key='new_blank_design').click().run();assert not app.exception and 'aircraft_aero_result' not in app.session_state


def test_native_cli_aero_and_report(native,tmp_path):
    import subprocess,sys
    root,p,s,g,a=native
    result=subprocess.run([sys.executable,'-X','utf8','-m','wingdesignhub.cli','aero','--root',str(root),'--geometry-run-id',g['run_id']],capture_output=True,text=True,encoding='utf-8',timeout=150)
    assert result.returncode==0,result.stderr+result.stdout
    r=json.loads(result.stdout);assert r['status']=='aero_checked_with_limits'
    out=tmp_path/'aero.html'
    result=subprocess.run([sys.executable,'-X','utf8','-m','wingdesignhub.cli','report','--root',str(root),'--run-id',r['run_id'],'--output',str(out)],capture_output=True,text=True,encoding='utf-8',timeout=30)
    assert result.returncode==0,result.stderr
    assert '尚未配平' in out.read_text('utf-8')
