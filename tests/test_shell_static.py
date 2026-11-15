from pathlib import Path
import copy
import numpy as np
import pytest
from wingdesignhub.shell_loads import conservative_transfer,skin_areas
from wingdesignhub.shell_static import StaticWingCase,promote_s6,read_dat,read_frd_balance,static_deck,von_mises,ccx_number
from wingdesignhub.mechanics import resultant


@pytest.fixture
def skin_patch():
    # Two flat surfaces with known area; only mapping geometry, not an aircraft model.
    nodes={};elements={}
    for k,z in enumerate((-.09,.09)):
        for j,y in enumerate(np.linspace(0,5,21)):
            for i,x in enumerate(np.linspace(0,1.5,7)):
                nodes[k*147+j*7+i+1]=[x,y,z]
        for j in range(20):
            for i in range(6):
                a=k*147+j*7+i+1
                for conn in ([a,a+1,a+8],[a,a+8,a+7]):elements[len(elements)+1]=conn
    return {'nodes':nodes,'elements':elements,'types':{n:'S3' for n in elements},
            'sets':{'ESkin_test':list(elements)},'sections':{},'materials':{}}


def test_transfer_conserves_wrench_with_cancellation_and_reference_shift(skin_patch):
    p=np.array([[.3,.2,0.],[.9,2.5,.02],[.6,4.9,-.01]])
    f=np.array([[12.,-23.,100.],[-12.,23.,-100.],[0.,0.,0.]])
    m=np.array([[5.,6.,7.],[-5.,-4.,-1.],[11.,-13.,17.]])
    ids,loads,audit=conservative_transfer(skin_patch,p,f,m,5.,1.5,.5)
    xyz=np.array([skin_patch['nodes'][n] for n in ids])
    assert not np.any(xyz[:,1]==0)
    for origin in ([0,0,0],[2,-3,4]):
        target=resultant(p,f,m,origin);actual=resultant(xyz,loads,origin=origin)
        np.testing.assert_allclose(actual,target,rtol=0,atol=1e-9)
    assert audit['passed'] and audit['force_absolute_error_n']<1e-9


def test_s6_shared_edges_area_and_mapping(skin_patch):
    quadratic=promote_s6(skin_patch)
    assert sum(skin_areas(quadratic).values())==pytest.approx(15.)
    assert set(quadratic['types'].values())=={'S6'}
    a,b=quadratic['elements'][1],quadratic['elements'][2]
    assert a[5]==b[3]  # same diagonal midpoint, shared topology
    ids,loads,_=conservative_transfer(quadratic,[[.6,2.5,0]],[[0,0,7500]],[[0,0,0]],5,1.5,.5)
    force,moment=resultant([quadratic['nodes'][n] for n in ids],loads)
    np.testing.assert_allclose(force,[0,0,7500],atol=1e-8)
    np.testing.assert_allclose(moment,[18750,-4500,0],atol=1e-8)


def test_invalid_transfer_is_rejected(skin_patch):
    with pytest.raises(ValueError,match='超出'):
        conservative_transfer(skin_patch,[[.6,6,0]],[[0,0,1]],[[0,0,0]],5,1.5,.5)
    with pytest.raises(ValueError,match='不足'):
        conservative_transfer(skin_patch,[[.6,.1,0]],[[0,0,1]],[[0,0,0]],5,1.5,.001)
    with pytest.raises(ValueError,match='非有限'):
        conservative_transfer(skin_patch,[[.6,1,0]],[[0,0,float('nan')]],[[0,0,0]],5,1.5,.5)


def test_static_configuration_and_factor():
    base=StaticWingCase().to_dict();assert StaticWingCase.from_dict(base).ultimate_factor==1.5
    for change in ({'ultimate_factor':.5},{'limit_lift_n':0},{'strip_count':True},{'stress_allowable_pa':float('nan')},{'schema_version':2}):
        with pytest.raises(ValueError):StaticWingCase.from_dict({**base,**change})


def test_von_mises_invariants():
    np.testing.assert_allclose(von_mises([[10,10,10,0,0,0],[10,0,0,0,0,0],[0,0,0,10,0,0]]),[0,10,10*np.sqrt(3)])


def test_ccx_field_width_preserves_small_signed_coordinates_and_loads():
    for value in (-1.85000000000001e-5,-.000274301687735674,70e9,1e-100,-1e100):
        field=ccx_number(value)
        assert len(field)<=20
        assert float(field[:20])==pytest.approx(value,rel=1e-12,abs=0)
    with pytest.raises(ValueError):ccx_number(float('nan'))


def test_dat_parser_requires_finite_complete_single_step(tmp_path):
    path=tmp_path/'out.dat';mesh={'nodes':{1:[0,0,0]},'elements':{1:[1]}}
    good=' displacements (vx,vy,vz) for set ALL\n1 0 0 .01\n stresses (elem, integ.pnt.,sxx,syy,szz,sxy,sxz,syz)\n1 1 10 0 0 0 0 0\n'
    path.write_text(good);u,s=read_dat(path,mesh);assert u[1][2]==.01 and s[1,1][0]==10
    for bad in (good+good,good.replace('.01','nan'),good.replace('1 1 10','2 1 10'),good.split(' stresses')[0]):
        path.write_text(bad)
        with pytest.raises(ValueError):read_dat(path,mesh)


def test_frd_windows_exponent_and_incomplete_output(tmp_path):
    p=tmp_path/'out.frd'
    def row(n,v):return ' -1'+f'{n:10d}'+''.join(v)+'\n'
    good='    2C\n'+row(1,['1.00000E-003','0.00000E+000','-1.00000E-003'])+' -3\n -4  FORC\n'+row(1,['0.00000E+000']*3)+' -3\n'
    p.write_text(good);assert read_frd_balance(p)['expanded_nodes']==1
    p.write_text(good.replace(' -4  FORC',' -4  DISP'))
    with pytest.raises(ValueError):read_frd_balance(p)


def test_deck_no_double_factor_or_root_load(skin_patch):
    mesh=promote_s6(skin_patch)
    with pytest.raises(ValueError,match='固支节点'):static_deck(mesh,[1],[[0,0,100]])
    ids,loads,_=conservative_transfer(mesh,[[.6,2.5,0]],[[0,0,7500]],[[0,0,0]],5,1.5,.5)
    deck,fixed=static_deck(mesh,ids,loads)
    assert '*DLOAD' not in deck and 'ROOT,1,6' in deck
    assert all(len(s.split(','))<=16 for s in deck.splitlines())
    assert all(len(v)<=20 for s in deck.splitlines() if s and (s[0].isdigit() or s[0]=='-') for v in s.split(','))


def test_native_static_service_and_artifact_integrity(tmp_path,monkeypatch):
    from wingdesignhub import static_service
    from wingdesignhub.adapters import tool_paths
    from wingdesignhub.service import get_results
    paths=tool_paths(Path(__file__).resolve().parents[1])
    if not paths['calculix'] or not Path(paths['calculix']).is_file():pytest.skip('local CalculiX 2.23 required')
    pytest.importorskip('openvsp')
    monkeypatch.setattr(static_service,'tool_paths',lambda _:paths)
    r=static_service.run_wing_static(StaticWingCase(),tmp_path)
    assert r['status']=='static_checked',r
    assert r['summary']['tip_mean_z_m']>0 and r['summary']['mapping']['passed']
    assert get_results(tmp_path,r['run_id'])['summary']['element']=='S6'
    p=tmp_path/'runs'/r['run_id']/'static/solve/wing.inp';p.write_text(p.read_text()+'** modified\n')
    with pytest.raises(ValueError,match='完整性'):get_results(tmp_path,r['run_id'])


def test_missing_solver_leaves_explicit_failed_record(tmp_path):
    from wingdesignhub.static_service import run_wing_static
    r=run_wing_static(StaticWingCase(),tmp_path)
    assert r['status']=='failed' and 'CalculiX' in r['error']
    assert (tmp_path/'runs'/r['run_id']/'input.json').exists()
