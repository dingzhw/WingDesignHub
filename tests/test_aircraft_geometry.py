from dataclasses import replace
from copy import deepcopy
import json
from pathlib import Path
import numpy as np
import pytest
from wingdesignhub.requirements import DesignProject
from wingdesignhub.sizing_physics import geometry
from wingdesignhub.aircraft_geometry import (build_geometry_contract,GeometryOptions,body_points,
                                           body_vectors,transfer_wrench,BODY_ROTATION)


def synthetic_source():
    p=DesignProject().confirmed()
    r={'run_id':'test-only','input_hash':'test-only','mode':'overall_sizing','status':'concept_checked_with_limits',
       'definition_sha256':p.definition_hash(),'summary':{'converged':True,'status':'concept_checked_with_limits',
            'geometry':geometry(1200,100,p),'cg':{'cg_x_m':2.7}}}
    return p,r


def test_independent_planform_references_and_coordinate_contract():
    p,r=synthetic_source();c=build_geometry_contract(p,r);ref=c['references']
    for s in c['lifting_surfaces']:
        root,tip=s['sections'];a=np.array(root['leading_edge_m']);b=np.array(tip['leading_edge_m'])
        extent=np.linalg.norm((b-a)[1:]);copies=2 if s['symmetric'] else 1
        area=copies*extent*(root['chord_m']+tip['chord_m'])/2
        # Simpson quadrature of c(y)^2, independent of the closed-form MAC function.
        integral=copies*extent*(root['chord_m']**2+4*((root['chord_m']+tip['chord_m'])/2)**2+tip['chord_m']**2)/6
        assert area==pytest.approx(s['area_m2'])
        assert integral/area==pytest.approx(s['mac_m'])
        assert a[0]+root['chord_m']/4==pytest.approx(s['quarter_x_m'])
        assert b[0]+tip['chord_m']/4==pytest.approx(s['quarter_x_m'])
    assert ref['area_m2']==r['summary']['geometry']['wing_area_m2']
    assert ref['moment_reference_geometry_m']==[2.7,0.,0.]
    assert c['analysis_contract']['flow_condition'] is None and not c['analysis_contract']['controls']
    assert c['propeller']['representation']=='unpowered disk'


def test_wrench_translation_rotation_and_power_invariance():
    points=np.array([[3.,2.,1.],[5.,-3.,2.]]);forces=np.array([[100.,30.,400.],[-50.,-70.,200.]])
    free=np.array([[1.,2.,3.],[4.,5.,6.]])
    old=np.array([1.,0.,.5]);new=np.array([2.7,.2,-.3])
    f=forces.sum(axis=0);m=(np.cross(points-old,forces)+free).sum(axis=0)
    fb,mb=transfer_wrench(f,m,old,new)
    pb=body_points(points,new);expected=(np.cross(pb,body_vectors(forces))+body_vectors(free)).sum(axis=0)
    np.testing.assert_allclose(mb,expected,atol=1e-12)
    np.testing.assert_allclose(fb,[-50.,-40.,-600.],atol=1e-12)
    np.testing.assert_allclose(body_points(new,new),[0,0,0])
    assert np.linalg.det(BODY_ROTATION)==1.
    velocity=np.array([60.,2.,3.]);assert fb@body_vectors(velocity)==pytest.approx(f@velocity)
    # A positive geometric z lift becomes negative body z, not positive.
    np.testing.assert_array_equal(body_vectors([0,0,100]),[0,0,-100])


@pytest.mark.parametrize('change',['unconfirmed','different','not_converged','failed','bad_axes','bad_mac','bad_cg','nan','other_configuration'])
def test_rejects_unusable_overall_geometry(change):
    p,r=synthetic_source()
    if change=='unconfirmed':p=replace(p,confirmation_sha256=None)
    elif change=='different':p=replace(p,payload_kg=400).confirmed()
    elif change in ('failed','not_converged'):r['status']=change
    elif change=='bad_axes':r['summary']['geometry']['axes']='body'
    elif change=='bad_mac':r['summary']['geometry']['mac_m']*=1.2
    elif change=='bad_cg':r['summary']['cg']['cg_x_m']=float('nan')
    elif change=='nan':r['summary']['geometry']['wing_span_m']=float('nan')
    else:r['summary']['geometry']['configuration']='biplane'
    with pytest.raises(ValueError):build_geometry_contract(p,r)


@pytest.mark.parametrize('options',[GeometryOptions('unknown'),GeometryOptions(tessellation=True),GeometryOptions(tessellation=3)])
def test_only_validated_template_and_discretizations(options):
    with pytest.raises(ValueError):options.validate()


def test_infeasible_converged_design_keeps_its_status():
    p,r=synthetic_source();r['status']=r['summary']['status']='constraints_not_met'
    assert build_geometry_contract(p,r)['parent_status']=='constraints_not_met'


@pytest.fixture(scope='module')
def native(tmp_path_factory):
    pytest.importorskip('openvsp');pytest.importorskip('fastga')
    from wingdesignhub.sizing_service import run_sizing
    from wingdesignhub.geometry_service import run_aircraft_geometry
    root=tmp_path_factory.mktemp('full_aircraft');p=DesignProject().confirmed();r=run_sizing(p,root)
    assert r['status']=='concept_checked_with_limits'
    g=run_aircraft_geometry(p,root,r['run_id'])
    assert g['status']=='geometry_checked_with_limits',g
    return root,p,r,g


def test_native_roundtrip_and_degen_independent_integrals(native):
    root,p,r,g=native;s=g['summary']
    assert all(c['passed'] for c in s['checks']) and s['component_count']==12
    assert not s['aerodynamics_run'] and not s['physical_validation_passed'] and not s['trim_checked']
    assert s['measurements']['sets']['lifting_surfaces']==['HorizontalTail','MainWing','VerticalTail']
    assert 'PropellerDisk' not in s['measurements']['sets']['baseline_airframe']
    assert s['degen_metrics']['MainWing']['integrated_area_m2']==pytest.approx(r['summary']['geometry']['wing_area_m2'],rel=1e-6)
    work=root/'runs'/g['run_id'];a=json.loads((work/'aerodynamic_geometry.json').read_text('utf-8'))
    assert a['references']==s['references'] and a['analysis']['flow_condition'] is None
    assert (work/'aircraft.vsp3').stat().st_size>10000


def test_native_save_reopen_geometry_and_report_are_bound_to_parent(native,tmp_path):
    from wingdesignhub.project_archive import build_bundle,save_bundle,load_saved
    from wingdesignhub.service import generate_report
    root,p,r,g=native;data=build_bundle(p,root,r,g);index=save_bundle(data,tmp_path)
    reopened=load_saved(tmp_path,index['archive_id'])
    assert reopened['records']==[r] and reopened['geometry_records']==[g]
    assert reopened['current_source_matches'] and not (tmp_path/'runs').exists()
    assert reopened['files'][f'runs/{g["run_id"]}/aircraft.vsp3']==(root/'runs'/g['run_id']/'aircraft.vsp3').read_bytes()
    assert '全机几何' in generate_report(g,root=root)
    wrong=deepcopy(g);wrong['parent_run_id']='other'
    with pytest.raises(ValueError,match='不匹配'):build_bundle(p,root,r,wrong)
    with pytest.raises(ValueError):build_bundle(p,root,None,g)


def test_service_rejects_changed_model_and_records_solver_failure(native,monkeypatch):
    from wingdesignhub import geometry_service
    from wingdesignhub.service import get_results
    from wingdesignhub.project_archive import build_bundle,read_bundle
    root,p,r,g=native;original=geometry_service.source_hashes
    monkeypatch.setattr(geometry_service,'source_hashes',lambda:{})
    with pytest.raises(ValueError,match='模型已变更'):geometry_service.run_aircraft_geometry(p,root,r['run_id'])
    monkeypatch.setattr(geometry_service,'source_hashes',original)
    monkeypatch.setattr(geometry_service,'execute',lambda *a,**k:(_ for _ in ()).throw(TimeoutError('test timeout')))
    failed=geometry_service.run_aircraft_geometry(p,root,r['run_id'])
    assert failed['status']=='failed' and 'test timeout' in failed['error']
    assert get_results(root,failed['run_id'])==failed
    assert read_bundle(build_bundle(p,root,r,failed))['geometry_records'][0]['status']=='failed'


def test_archive_rejects_geometry_reference_mismatch_even_with_updated_hashes(native):
    from io import BytesIO
    from zipfile import ZipFile,ZIP_DEFLATED
    from wingdesignhub.project_archive import build_bundle,read_bundle,digest,encoded
    root,p,r,g=native
    with ZipFile(BytesIO(build_bundle(p,root,r,g))) as z:files={n:z.read(n) for n in z.namelist()}
    prefix='runs/'+g['run_id']+'/';name=prefix+'aerodynamic_geometry.json'
    interface=json.loads(files[name]);interface['references']['area_m2']*=1.1;files[name]=encoded(interface)
    record=json.loads(files[prefix+'result.json']);record['artifact_hashes']['aerodynamic_geometry.json']=digest(files[name])
    files[prefix+'result.json']=encoded(record);manifest=json.loads(files['manifest.json'])
    manifest['files']={n:digest(b) for n,b in files.items() if n!='manifest.json'};files['manifest.json']=encoded(manifest)
    stream=BytesIO()
    with ZipFile(stream,'w',ZIP_DEFLATED) as z:
        for name,value in files.items():z.writestr(name,value)
    with pytest.raises(ValueError,match='气动接口'):read_bundle(stream.getvalue())


def test_geometry_ui_reopen_then_input_edit_invalidates(native,monkeypatch):
    from streamlit.testing.v1 import AppTest
    from wingdesignhub import sizing_service,geometry_service,project_archive,geometry_ui,project_ui
    root,p,r,g=native
    monkeypatch.setattr(sizing_service,'run_sizing',lambda p,ignored:r)
    monkeypatch.setattr(geometry_service,'run_aircraft_geometry',lambda p,ignored,rid:g)
    # Run the genuine rendering/file service against a private test root.
    render=geometry_ui.render
    monkeypatch.setattr(geometry_ui,'render',lambda p,ignored,r:render(p,root,r))
    save=project_ui.save_controls
    monkeypatch.setattr(project_ui,'save_controls',lambda p,ignored,r=None,key='design':save(p,root,r,key))
    original_list=project_archive.list_saved;original_load=project_archive.load_saved
    monkeypatch.setattr(project_archive,'list_saved',lambda ignored:original_list(root))
    monkeypatch.setattr(project_archive,'load_saved',lambda ignored,rid:original_load(root,rid))
    a=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py')).run(timeout=30)
    a.checkbox[0].check().run();a.button(key='run_sizing').click().run(timeout=30)
    a.button(key='generate_aircraft_geometry').click().run(timeout=30)
    assert not a.exception and any('全机参数化几何已生成' in x.value for x in a.success)
    a.button(key='design_save_local').click().run();saved=original_list(root)[0]
    a.selectbox(key='saved_archive_choice').set_value(saved['archive_id']).run();a.button(key='open_saved_design').click().run(timeout=30)
    assert not a.exception and a.session_state['opened_archive']['geometry_records'][0]==g
    assert 'aircraft_geometry_result' not in a.session_state
    a.button(key='run_sizing').click().run(timeout=30)
    next(x for x in a.number_input if x.label.startswith('任务载荷')).set_value(400.).run()
    assert not a.exception and not any(b.key=='generate_aircraft_geometry' for b in a.button)
