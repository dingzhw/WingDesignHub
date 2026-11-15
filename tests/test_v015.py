from dataclasses import replace
from pathlib import Path
import json
import numpy as np
import pytest
from wingdesignhub.plate_buckling import PlateCase,plate_model,plate_deck,read_factors,read_modes,run_plate
from wingdesignhub.flight_loads import FlightLoadCase,combine_loads
from wingdesignhub.box_comparison import BoxCase,box_mesh
from wingdesignhub.shell_static import static_deck
from wingdesignhub.mechanics import resultant


def test_plate_boundary_traction_resultants_and_restraints():
    case=PlateCase(compression_pa=2e6,shear_pa=3e6);model=plate_model(case)
    f,m=resultant(list(model['nodes'].values()),list(model['forces'].values()))
    np.testing.assert_allclose(f,0,atol=1e-8);np.testing.assert_allclose(m,0,atol=1e-8)
    top=sum((model['forces'][n] for n in model['boundary']['top']),np.zeros(3))
    np.testing.assert_allclose(top,[case.shear_pa*case.thickness_m*case.width_m,-case.compression_pa*case.thickness_m*case.width_m,0],atol=1e-8)
    text=plate_deck(case,model)
    assert 'EDGE,3,3' in text and 'EDGE,4,5' not in text and '*BUCKLE' in text
    assert '*STATIC' not in text and 'PERTURBATION' not in text
    assert 'EDGE,4,5' in plate_deck(replace(case,support='clamped'),model)
    assert all(len(v)<=20 for line in text.splitlines() if line and line[0].isdigit() for v in line.split(','))


@pytest.mark.parametrize('change',[{'schema_version':True},{'compression_pa':-1},{'compression_pa':0,'shear_pa':0},
    {'thickness_m':.1},{'poisson_ratio':.5},{'divisions':True},{'modes':0},{'length_m':float('nan')}, {'support':'hinge'}])
def test_plate_invalid_input(change):
    with pytest.raises(ValueError):PlateCase.from_dict({**PlateCase().to_dict(),**change})


def test_buckling_parser_rejects_incomplete_or_ambiguous_data(tmp_path):
    p=tmp_path/'plate.dat';header=' B U C K L I N G F A C T O R O U T P U T\n MODE NO BUCKLING\n FACTOR\n'
    good=header+' 1 1.2E+02\n 2 3.4E+02\n'
    p.write_text(good);assert read_factors(p,2)==[120,340]
    for bad in (good+good,header+'1 nan\n2 3\n',header+'1 -1\n2 2\n',header+'1 2\n',header+'2 2\n1 1\n'):
        p.write_text(bad)
        with pytest.raises(ValueError):read_factors(p,2)


def test_mode_parser_separates_static_frame_and_eigenmode(tmp_path):
    model={'nodes':{1:[0,0,0],2:[1,0,0],3:[.5,.5,0]},'boundary':{'edge':[1,2]}}
    def block(value,z):
        return f'  100CL  101{value:12.5E}\n -4  DISP\n'+''.join(' -1'+f'{n:10d}'+''.join(f'{v:12.5E}' for v in [0,0,z if n==3 else 0])+'\n' for n in model['nodes'])+' -3\n'
    p=tmp_path/'plate.frd';good=block(0,0)+block(123,1);p.write_text(good)
    modes,checks,base=read_modes(p,model,[123]);assert modes[0][3][2]==1 and base[3][2]==0
    assert checks[0]['edge_transverse_relative_residual']==0
    for bad in (block(123,1),good.replace('1.23000E+02','1.25000E+02'),block(0,0)+block(123,0)):
        p.write_text(bad)
        with pytest.raises(ValueError):read_modes(p,model,[123])


def test_mapping_region_and_root_support_do_not_change_resultants():
    mesh=box_mesh(BoxCase(),20);case=FlightLoadCase(mesh=replace(FlightLoadCase().mesh,chord_m=.6),point_masses=[])
    p=np.array([[.15,1,0],[.15,3,0]]);f=np.array([[0,0,2000.],[0,0,3000.]])
    outputs=[combine_loads(case,mesh,p,f,w) for w in (.05,.1,.2)]
    target_f=outputs[0][2]['mapping']['input_force_n'];target_m=outputs[0][2]['mapping']['input_moment_nm']
    for ids,force,loads in outputs:
        a,b=resultant([mesh['nodes'][n] for n in ids],force)
        np.testing.assert_allclose(a,target_f,atol=1e-8);np.testing.assert_allclose(b,target_m,atol=1e-8)
    assert not np.allclose(outputs[0][1],outputs[-1][1])
    ids,force,_=outputs[1]
    assert 'ROOT,1,3' in static_deck(mesh,ids,force,True,'translations_fixed')[0]
    with pytest.raises(ValueError):static_deck(mesh,ids,force,True,'free')
    for bad in (0,1,True,float('nan')):
        with pytest.raises(ValueError):combine_loads(case,mesh,p,f,bad)


def test_native_plate_lowest_mode_scaling_and_service(tmp_path,monkeypatch):
    from wingdesignhub import plate_service
    from wingdesignhub.adapters import tool_paths
    from wingdesignhub.service import get_results
    paths=tool_paths(Path(__file__).resolve().parents[1])
    if not paths['calculix'] or not Path(paths['calculix']).is_file():pytest.skip('local CalculiX 2.23 required')
    c=PlateCase(compression_pa=39.19291e6,shear_pa=5.60563e6,divisions=12)
    r=run_plate(c,paths['calculix'],tmp_path/'first')
    assert .06<r['first_factor']<.09 and r['native_factors'][0]>50
    other=run_plate(c,paths['calculix'],tmp_path/'scaled',reference_scale=r['native_reference_scale']/2)
    assert other['first_factor']==pytest.approx(r['first_factor'],rel=.001)
    x=json.loads((tmp_path/'first/first_mode.json').read_text())['normalized_displacement']
    y=json.loads((tmp_path/'scaled/first_mode.json').read_text())['normalized_displacement']
    a=np.array([x[n][2] for n in x]);b=np.array([y[n][2] for n in x])
    assert (a@b)**2/(a@a)/(b@b)>.999
    monkeypatch.setattr(plate_service,'tool_paths',lambda _:paths)
    result=plate_service.run_plate_analysis(c,tmp_path)
    assert result['status']=='executed_with_limits'
    assert get_results(tmp_path,result['run_id'])['summary']['first_factor']<1
    (tmp_path/'runs'/result['run_id']/'plate/solver_reference.json').write_text('{}')
    with pytest.raises(ValueError,match='完整性'):get_results(tmp_path,result['run_id'])


def test_missing_plate_solver_keeps_failed_record(tmp_path):
    from wingdesignhub.plate_service import run_plate_analysis
    r=run_plate_analysis(PlateCase(),tmp_path)
    assert r['status']=='failed' and 'CalculiX' in r['error']
    assert (tmp_path/'runs'/r['run_id']/'input.json').exists()
