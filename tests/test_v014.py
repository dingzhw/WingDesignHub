from dataclasses import replace
from pathlib import Path
import numpy as np
import pytest
from wingdesignhub.box_comparison import BoxCase,box_mesh,section,tip_loading,bending_tip_couple,beam_response,tip_fit
from wingdesignhub.buckling import plate_screen,panel_screen
from wingdesignhub.flight_loads import FlightLoadCase,structural_mass,combine_loads,aerodynamic_loads,G
from wingdesignhub.mechanics import resultant
from wingdesignhub.shell_static import static_deck


def test_common_box_mass_stiffness_and_analytical_response():
    c=BoxCase();mesh=box_mesh(c,20);props=section(c)
    _,mass=structural_mass(mesh)
    assert mass['mass_kg']==pytest.approx(props['area_m2']*c.length_m*c.density_kg_m3)
    np.testing.assert_allclose(mass['cg_m'],[c.width_m/2,c.length_m/2,0],atol=1e-12)
    ids,f,a=bending_tip_couple(mesh,c,c.tip_bending_moment_nm);r=beam_response(c,mesh,ids,f)
    assert r['tip_displacement_m']==pytest.approx(c.tip_bending_moment_nm*c.length_m**2/(2*c.elastic_modulus_pa*props['Ixx_m4']),rel=1e-8)
    assert r['mapping_force_error_n']<1e-8 and r['mapping_moment_error_nm']<1e-8
    ids,f,a=tip_loading(mesh,c,0,c.tip_torque_nm);r=beam_response(c,mesh,ids,f)
    assert r['tip_twist_rad']==pytest.approx(c.tip_torque_nm*c.length_m/(props['shear_modulus_pa']*props['J_m4']))
    # Exact rigid translation/rotation with a deliberately nonzero twist.
    u={str(n):(np.array([.001,0,.02])+np.cross([0,.01,0],np.array(p)-[c.width_m/2,c.length_m,0])).tolist() for n,p in mesh['nodes'].items()}
    fit=tip_fit(c,mesh,u)
    assert fit['translation_z_m']==pytest.approx(.02) and fit['twist_y_rad']==pytest.approx(.01)
    assert fit['section_fit_rms_m']<1e-14


def test_plate_modes_scaling_signs_and_handbook_limits():
    # NACA TN3781 table3: long simply supported compression k=4, shear 5.35.
    r=plate_screen(1.,.5,.002,70e9,.33,-10e6,2e6)
    assert r['kc']==4 and r['compression_half_waves']==2
    assert abs(r['ks_long_strip']-5.35)/5.35<.002
    # Explicit independently evaluated square-panel critical stress (E=70GPa, nu=.3).
    square=plate_screen(.5,.5,.002,70e9,.3,0,0)
    assert square['compression_critical_pa']==pytest.approx(4.049e6,rel=3e-5)
    thick=plate_screen(1.,.5,.004,70e9,.33,-10e6,-2e6)
    assert thick['compression_critical_pa']==pytest.approx(4*r['compression_critical_pa'])
    assert thick['shear_critical_pa']==pytest.approx(4*r['shear_critical_pa'])
    assert plate_screen(1.,.5,.002,70e9,.33,10e6,0)['interaction_utilization']==0
    for aspect in (1.1,1.42,2.3,5.4):
        x=plate_screen(aspect,1.,.002,70e9,.3,-1,0)
        assert x['kc']==pytest.approx(min((m/aspect+aspect/m)**2 for m in range(1,40)))
    assert not r['screen_passed']
    lam=r['proportional_load_factor_to_buckling']
    assert lam*r['compression_ratio']+(lam*r['shear_ratio'])**2==pytest.approx(1.)
    for bad in (0,-1,float('nan')):
        with pytest.raises(ValueError):plate_screen(bad,.5,.002,70e9,.3,0,0)


def test_mass_relief_factor_and_root_accounting():
    c=BoxCase();mesh=box_mesh(c,20)
    config=FlightLoadCase(mesh=replace(FlightLoadCase().mesh,chord_m=.6),fuel_x_fraction=.45,
                          point_masses=[{'name':'test','mass_kg':10.,'position_m':[.3,1.5,0.]}])
    p=np.array([[.15,1.,0.],[.15,3.,0.]]);f=np.array([[0,0,2000.],[0,0,3000.]])
    ids,nf,r=combine_loads(config,mesh,p,f);F,M=resultant([mesh['nodes'][n] for n in ids],nf)
    mass=r['structure_mass']['mass_kg']
    assert F[2]==pytest.approx((5000-(mass+40)*G)*1.5)
    assert M[0]==pytest.approx((11000-G*(mass*2.5+30*2.+10*1.5))*1.5)
    assert r['root_applied_force_n'][2]<0
    deck,_=static_deck(mesh,ids,nf,allow_root_loads=True)
    assert '*DLOAD' not in deck and 'ROOT,1,6' in deck
    ids2,nf2,r2=combine_loads(replace(config,load_factor=2.),mesh,p,2*f)
    np.testing.assert_allclose(nf2,2*nf,atol=1e-10)
    _,nf3,_=combine_loads(replace(config,ultimate_factor=1.),mesh,p,f)
    np.testing.assert_allclose(nf,1.5*nf3,atol=1e-10)
    _,nf4,_=combine_loads(replace(config,load_factor=-1.),mesh,p,-f)
    np.testing.assert_allclose(nf4,-nf,atol=1e-10)
    _,nf5,_=combine_loads(replace(config,fuel_half_mass_kg=40.),mesh,p,f)
    assert (nf5-nf)[:,2].sum()==pytest.approx(-10*G*1.5)
    with pytest.raises(ValueError,match='台账'):combine_loads(replace(config,aircraft_mass_kg=100),mesh,p,f)


@pytest.mark.parametrize('change',[{'schema_version':True},{'load_factor':0},{'fuel_half_mass_kg':-1},
    {'fuel_start_fraction':.8},{'aircraft_mass_kg':float('nan')},{'aero_panels':True},
    {'point_masses':[{'name':'a','mass_kg':-1,'position_m':[0,1,0]}]}, {'point_masses':'bad'}])
def test_bad_flight_inputs_rejected(change):
    with pytest.raises(ValueError):FlightLoadCase.from_dict({**FlightLoadCase().to_dict(),**change})


def test_aero_solver_targets_without_force_rescaling(tmp_path,monkeypatch):
    from wingdesignhub import flight_loads
    def fake(case,exe,path):
        cl=.08*case.alpha_deg+.00001*case.alpha_deg**3
        return {'coefficients':{'CLtot':cl},'right_wing_strips':[{'y_m':2.5,'cl':cl,'area_m2':7.5}]}
    monkeypatch.setattr(flight_loads,'run_avl',fake)
    p,f,r=aerodynamic_loads(FlightLoadCase(),'fake',tmp_path/'valid')
    assert r['lift_relative_error']<.001 and len(r['lift_iterations'])>1
    with pytest.raises(ValueError,match='线性域'):
        aerodynamic_loads(replace(FlightLoadCase(),speed_m_s=20.),'fake',tmp_path/'outside')


def test_panel_parser_requires_all_nine_points():
    mesh=box_mesh(BoxCase(),10)
    with pytest.raises(ValueError,match='9 个'):
        panel_screen(mesh,FlightLoadCase().mesh,{(e,1):[0]*6 for e in mesh['elements']})


def test_panel_stress_projection_membrane_average_and_coverage():
    mesh=box_mesh(BoxCase(),20)
    for p in mesh['nodes'].values():p[0]+=.375
    web_ids=mesh['sets'].pop('EWeb_box');sec=mesh['sections'].pop('EWeb_box')
    for name,x in (('EFrontSpar_box',.375),('ERearSpar_box',.975)):
        mesh['sets'][name]=[e for e in web_ids if abs(mesh['nodes'][mesh['elements'][e][0]][0]-x)<1e-8]
        mesh['sections'][name]=sec.copy()
    stress={}
    for e,conn in mesh['elements'].items():
        p=np.array([mesh['nodes'][n] for n in conn[:3]])
        skin=np.ptp(p[:,2])<1e-8
        sigma=-10e6 if p[:,2].mean()>0 else 10e6
        for ip in range(1,10):
            # Odd through-thickness bending cancels; tensor shear projects onto panel tangent.
            offset=(1 if ip<=3 else (-1 if ip>=7 else 0))*5e6
            stress[e,ip]=[0,sigma+offset,0,2e6 if skin else 0,0,0 if skin else 3e6]
    r=panel_screen(mesh,FlightLoadCase().mesh,stress)
    assert len(r['panels'])==16
    assert r['screened_area_m2']/r['total_shell_area_m2']==pytest.approx(.9)
    upper=next(p for p in r['panels'] if p['panel']=='upper_skin')
    assert upper['sigma_longitudinal_pa']==pytest.approx(-10e6)
    assert abs(upper['tau_pa'])==pytest.approx(2e6) and upper['width_m']==pytest.approx(.6)
    assert all(p['compression_ratio']==0 for p in r['panels'] if p['panel']=='lower_skin')
    assert abs(next(p for p in r['panels'] if p['panel']=='front_web')['tau_pa'])==pytest.approx(3e6)


def test_native_flight_service_and_hashes(tmp_path,monkeypatch):
    from wingdesignhub import flight_service
    from wingdesignhub.adapters import tool_paths
    from wingdesignhub.service import get_results
    paths=tool_paths(Path(__file__).resolve().parents[1])
    if not all(Path(paths[k]).is_file() for k in ('calculix','avl')):pytest.skip('local AVL and CalculiX required')
    pytest.importorskip('openvsp');monkeypatch.setattr(flight_service,'tool_paths',lambda _:paths)
    r=flight_service.run_flight_structure(FlightLoadCase(),tmp_path)
    assert r['status']=='executed_with_limits',r
    s=r['summary'];assert s['yield_margin']>0 and s['buckling']['max_interaction_utilization']>1
    assert s['mapping']['passed'] and len(s['buckling']['panels'])==16
    assert get_results(tmp_path,r['run_id'])['mode']=='flight_structure'
    (tmp_path/'runs'/r['run_id']/'loads.json').write_text('{}')
    with pytest.raises(ValueError,match='完整性'):get_results(tmp_path,r['run_id'])
