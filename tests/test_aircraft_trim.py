from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import json
import numpy as np
import pytest
from wingdesignhub.requirements import DesignProject
from wingdesignhub.sizing_physics import geometry
from wingdesignhub.flight_state import make_flight_state
from wingdesignhub.aircraft_trim import TrimOptions, bounded_newton, make_trim_contract


def ledger_summary():
    p=DesignProject().confirmed()
    return {'design_mtow_kg':1200.,'required_loaded_mass_kg':1100.,'geometry':geometry(1200,100,p),
            'cg':{'cg_x_m':3120/1100,'rows':[{'component':'airframe','mass_kg':700.,'x_m':3.},
                 {'component':'payload','mass_kg':300.,'x_m':2.5},{'component':'takeoff_fuel','mass_kg':100.,'x_m':2.7}]},
            'mission':{'takeoff_fuel_kg':100.,'takeoff_roll_fuel_kg':5.,'taxi_in_fuel_kg':5.,'reserve_fuel_kg':35.,
                       'segments':[{'fuel_kg':20.},{'fuel_kg':35.}],'cruise_speed_used_m_s':60.}}


def test_mass_fuel_and_first_moment_against_independent_hand_ledger():
    s=ledger_summary();original=deepcopy(s);start=make_flight_state(s);end=make_flight_state(s,'mission_end')
    assert start['operating_mass_kg']==1100 and start['unallocated_mass_budget_kg']==100
    assert not start['mass_budget_allocated_as_ballast']
    assert start['cg_geometry_m']==pytest.approx([3120/1100,0,0])
    assert end['operating_mass_kg']==1040 and end['remaining_usable_fuel_kg']==40
    assert end['cg_geometry_m']==pytest.approx([(3120-60*2.7)/1040,0,0])
    assert end['fuel_burned_from_takeoff_kg']==60 and s==original
    custom=make_flight_state(s,'explicit',1000,2.8,'same-condition research assumption')
    assert custom['component_ledger'] is None and custom['remaining_usable_fuel_kg'] is None


@pytest.mark.parametrize('mode,mass,cg,note',[('explicit',1000,None,'x'),('explicit',None,2.8,'x'),('explicit',True,2.8,'x'),
    ('explicit',1000,2.8,''),('explicit',1201,2.8,'x'),('explicit',1000,99,'x'),('takeoff',1000,None,''),
    ('takeoff',None,None,'override'),('unknown',None,None,'')])
def test_rejects_ambiguous_or_out_of_range_flight_state(mode,mass,cg,note):
    with pytest.raises(ValueError):make_flight_state(ledger_summary(),mode,mass,cg,note)


def test_rejects_inconsistent_mass_fuel_and_cg_records():
    s=ledger_summary();s['required_loaded_mass_kg']+=10
    with pytest.raises(ValueError,match='质量台账'):make_flight_state(s)
    s=ledger_summary();s['mission']['reserve_fuel_kg']=0
    with pytest.raises(ValueError,match='储备'):make_flight_state(s,'mission_end')
    s=ledger_summary();s['cg']['cg_x_m']+=.1
    with pytest.raises(ValueError,match='重心'):make_flight_state(s)


@pytest.mark.parametrize('options',[{'alpha_min_deg':-7},{'elevator_max_deg':11},{'initial_alpha_deg':7},
    {'max_iterations':True},{'max_iterations':13},{'alpha_min_deg':6},{'mesh_level':4}])
def test_trim_option_bounds(options):
    with pytest.raises(ValueError):TrimOptions(**options).validate()


def test_control_readback_tolerates_print_rounding_but_rejects_real_deviation():
    from wingdesignhub.avl_aircraft import controls_match
    expected={'elevator':-6.5918320114313245}
    assert controls_match({'elevator':-6.591832011431324},expected)
    assert not controls_match({'elevator':-6.591831},expected)
    assert not controls_match({},expected)


def test_bounded_solver_matches_independent_linear_system_with_approximate_jacobian():
    j=np.array([[.1,.02],[-.04,-.05]]);b=np.array([.4,-.15]);truth=np.linalg.solve(j,b)
    def evaluate(x):return j@x-b,j*1.001,{'evaluation_id':'analytical'}
    result=bounded_newton(evaluate,[0,0],[-6,-10],[6,10])
    assert result['converged']
    np.testing.assert_allclose(result['solution'],truth,atol=1e-4)
    assert max(abs(x) for x in result['residuals'])<=1e-5
    assert len(result['history'])>=3  # one approximate Newton prediction is insufficient


def test_solver_reports_bounds_iteration_limit_and_singular_jacobian():
    fun=lambda x:(x-np.array([2,-12]),np.eye(2),{})
    r=bounded_newton(fun,[0,0],[-6,-10],[6,10]);assert r['status']=='trim_bounds_exceeded' and not r['converged']
    assert r['margins_deg']['elevator_lower']==0 and abs(r['residuals'][1])==2
    r=bounded_newton(lambda x:(x-1,np.eye(2)*2,{}),[0,0],[-6,-10],[6,10],max_iterations=1)
    assert r['status']=='trim_not_converged'
    r=bounded_newton(lambda x:([1,1],np.ones((2,2)),{}),[0,0],[-6,-10],[6,10])
    assert r['status']=='trim_jacobian_singular'
    r=bounded_newton(lambda x:([1,1],np.eye(2),{}),[0,0],[-6,-10],[6,10])
    assert not r['converged'] and r['solution']==[0,0]
    assert len([z for z in r['history'] if z['accepted']])==1


@pytest.fixture(scope='module')
def native(tmp_path_factory):
    pytest.importorskip('openvsp');pytest.importorskip('fastga')
    if not Path('C:/apps/avl/avl.exe').is_file():pytest.skip('AVL native executable unavailable')
    from wingdesignhub.sizing_service import run_sizing
    from wingdesignhub.geometry_service import run_aircraft_geometry
    from wingdesignhub.trim_service import run_aircraft_trim
    root=tmp_path_factory.mktemp('aircraft_trim');p=DesignProject().confirmed();s=run_sizing(p,root)
    g=run_aircraft_geometry(p,root,s['run_id']);t=run_aircraft_trim(p,root,g['run_id'])
    assert t['status']=='trim_checked_with_limits',t
    return root,p,s,g,t


def test_native_trim_true_residuals_mass_and_tail_load(native):
    root,p,s,g,r=native;o=r['summary'];t=o['trim']
    assert max(abs(t['residual_cl']),abs(t['residual_cm']))<=1e-5
    assert o['flight_state']['operating_mass_kg']==pytest.approx(s['summary']['required_loaded_mass_kg'])
    assert sum(v['lift_n'] for v in t['surface_loads'].values())==pytest.approx(o['flow']['mass_kg']*9.80665,rel=3e-5)
    assert abs(sum(v['pitch_moment_about_cg_nm'] for v in t['surface_loads'].values()))<1
    assert t['surface_loads']['HorizontalTail']['lift_n']!=pytest.approx(t['initial_surface_loads']['HorizontalTail']['lift_n'])
    assert t['locally_restoring_pitch'] and not o['mission_polar_updated'] and not t['axial_force_balanced']
    assert all(-6<=x['alpha_deg']<=6 and -10<=x['elevator_deg']<=10 for x in t['history'])
    assert all(x['passed'] for x in o['checks'])


def test_native_end_state_and_explicit_cg_propagate(native):
    from wingdesignhub.trim_service import run_aircraft_trim
    root,p,s,g,r=native;baseline=r['summary'];mass=baseline['flow']['mass_kg'];cg=baseline['references']['moment_reference_geometry_m'][0]
    end=run_aircraft_trim(p,root,g['run_id'],TrimOptions(mass_state='mission_end'))
    aft=run_aircraft_trim(p,root,g['run_id'],TrimOptions(mass_state='explicit',mass_kg=min(mass,s['summary']['design_mtow_kg']),cg_x_m=cg+.1,source_note='CG sensitivity'))
    for t in (end,aft):assert t['status']=='trim_checked_with_limits',t
    assert end['summary']['flight_state']['remaining_usable_fuel_kg']==pytest.approx(s['summary']['mission']['reserve_fuel_kg']+s['summary']['mission']['taxi_in_fuel_kg'])
    assert end['summary']['flow']['mass_kg']<mass
    assert aft['summary']['trim']['elevator_deg']>baseline['trim']['elevator_deg']
    assert aft['summary']['trim']['surface_loads']['HorizontalTail']['lift_n']>baseline['trim']['surface_loads']['HorizontalTail']['lift_n']
    assert aft['summary']['references']['moment_reference_geometry_m'][0]==cg+.1


def test_native_coarse_trim_control_readback_handles_noninteger_deflection(native):
    from wingdesignhub.trim_service import run_aircraft_trim
    root,p,s,g,r=native
    coarse=run_aircraft_trim(p,root,g['run_id'],TrimOptions(mesh_level=1))
    assert coarse['status']=='trim_checked_with_limits',coarse.get('error')
    assert all(x['passed'] for x in coarse['summary']['checks'])


def test_native_bound_failure_and_archive_preserve_real_status(native):
    from wingdesignhub.trim_service import run_aircraft_trim
    from wingdesignhub.project_archive import build_bundle,read_bundle
    root,p,s,g,r=native
    t=run_aircraft_trim(p,root,g['run_id'],TrimOptions(elevator_min_deg=-1.,elevator_max_deg=1.))
    assert t['status']=='trim_bounds_exceeded' and not t['summary']['trim_checked']
    data=build_bundle(p,root,s,g,trim_record=t);assert read_bundle(data)['trim_records']==[t]


def test_native_archive_report_and_corrupt_flight_state(native):
    from wingdesignhub.project_archive import build_bundle,read_bundle,digest,encoded
    from wingdesignhub.service import get_results,generate_report
    from test_project_archive import edit_zip
    root,p,s,g,r=native;data=build_bundle(p,root,s,g,trim_record=r)
    assert read_bundle(data)['trim_records']==[r] and get_results(root,r['run_id'])==r
    assert '纵向配平报告' in generate_report(r,root=root)
    def corrupt(files):
        prefix='runs/'+r['run_id']+'/';c=json.loads(files[prefix+'trim_contract.json']);c['flight_state']['operating_mass_kg']+=100
        files[prefix+'trim_contract.json']=encoded(c);rr=json.loads(files[prefix+'result.json'])
        rr['artifact_hashes']['trim_contract.json']=digest(files[prefix+'trim_contract.json']);files[prefix+'result.json']=encoded(rr)
        m=json.loads(files['manifest.json']);m['files']={n:digest(b) for n,b in files.items() if n!='manifest.json'};files['manifest.json']=encoded(m)
    with pytest.raises(ValueError,match='配平工况'):read_bundle(edit_zip(data,corrupt))


def test_native_timeout_and_changed_definition(native,monkeypatch):
    from wingdesignhub.trim_service import run_aircraft_trim
    from wingdesignhub.project_archive import build_bundle,read_bundle
    root,p,s,g,r=native
    with pytest.raises(ValueError,match='需求'):run_aircraft_trim(replace(p,payload_kg=500).confirmed(),root,g['run_id'])
    def timeout(*args):raise TimeoutError('synthetic timeout')
    monkeypatch.setattr('wingdesignhub.trim_service.solve_trim',timeout)
    failed=run_aircraft_trim(p,root,g['run_id']);assert failed['status']=='failed' and 'error.log' in failed['artifact_hashes']
    assert read_bundle(build_bundle(p,root,s,g,trim_record=failed))['trim_records']==[failed]


def test_native_ui_trim_save_reopen_and_reset(native,monkeypatch):
    from streamlit.testing.v1 import AppTest
    from wingdesignhub import sizing_service,geometry_service,geometry_ui,trim_ui,project_ui,project_archive
    root,p,s,g,t=native
    monkeypatch.setattr(sizing_service,'run_sizing',lambda *args:s);monkeypatch.setattr(geometry_service,'run_aircraft_geometry',lambda *args:g)
    monkeypatch.setattr(trim_ui,'run_aircraft_trim',lambda *args:t)
    render=geometry_ui.render;monkeypatch.setattr(geometry_ui,'render',lambda p,ignored,r:render(p,root,r))
    save=project_ui.save_controls;monkeypatch.setattr(project_ui,'save_controls',lambda p,ignored,r=None,key='design':save(p,root,r,key))
    listing=project_archive.list_saved;load=project_archive.load_saved
    monkeypatch.setattr(project_archive,'list_saved',lambda ignored:listing(root));monkeypatch.setattr(project_archive,'load_saved',lambda ignored,rid:load(root,rid))
    app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py')).run(timeout=30)
    app.checkbox[0].check().run();app.button(key='run_sizing').click().run(timeout=30)
    app.button(key='generate_aircraft_geometry').click().run(timeout=30);app.button(key='run_aircraft_trim').click().run(timeout=30)
    assert not app.exception and any('纵向升力面配平完成' in x.value for x in app.success)
    app.selectbox(key='trim_mass_state').set_value('mission_end').run()
    assert any('当前输入已更改' in x.value for x in app.warning)
    app.button(key='design_save_local').click().run();saved=listing(root)[0]
    app.selectbox(key='saved_archive_choice').set_value(saved['archive_id']).run();app.button(key='open_saved_design').click().run(timeout=30)
    assert not app.exception and any('纵向升力面配平完成' in x.value for x in app.success)
    assert load(root,saved['archive_id'])['trim_records']==[t]
    app.button(key='new_blank_design').click().run();assert 'aircraft_trim_result' not in app.session_state


def test_native_cli_returns_failed_status_and_exports_report(native,tmp_path):
    import subprocess,sys
    root,p,s,g,r=native
    result=subprocess.run([sys.executable,'-X','utf8','-m','wingdesignhub.cli','report','--root',str(root),'--run-id',r['run_id'],
                           '--output',str(tmp_path/'report.html')],capture_output=True,text=True,encoding='utf-8',timeout=30)
    assert result.returncode==0,result.stderr
    options=tmp_path/'options.json';options.write_text(json.dumps({'elevator_min_deg':-1,'elevator_max_deg':1}),encoding='utf-8')
    result=subprocess.run([sys.executable,'-X','utf8','-m','wingdesignhub.cli','trim','--root',str(root),'--geometry-run-id',g['run_id'],
                           '--trim-options',str(options)],capture_output=True,text=True,encoding='utf-8',timeout=180)
    assert result.returncode==1,result.stderr+result.stdout
    assert json.loads(result.stdout)['status']=='trim_bounds_exceeded'
