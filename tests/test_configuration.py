from copy import deepcopy
import math
import pytest
from wingdesignhub.fastga_mass import mass_inputs
from wingdesignhub.configuration import geometry_parameters,domain_ledger
from wingdesignhub.aircraft_geometry import build_geometry_contract
from test_aircraft_geometry import synthetic_source


@pytest.mark.parametrize('changed',[False,True])
def test_mass_and_cad_share_tail_parameters(changed):
    p,r=synthetic_source();g=r['summary']['geometry']
    if changed:
        g['surface_parameters']['vertical_tail'].update(aspect_ratio=1.9,thickness_ratio=.1,naca='0010')
        g['surface_parameters']['horizontal_tail'].update(aspect_ratio=4.5,thickness_ratio=.15,naca='0015')
    inputs=mass_inputs(1200,150000,g,p);contract=build_geometry_contract(p,r)
    for key,surface in zip(('wing','horizontal_tail','vertical_tail'),contract['lifting_surfaces']):
        prefix='data:geometry:'+key+':'
        span=surface['span_m']
        assert inputs[prefix+'aspect_ratio'][0]==pytest.approx(span**2/surface['area_m2'])
        assert inputs[prefix+'thickness_ratio'][0]==surface['thickness_ratio']==int(surface['naca'][-2:])/100
        assert inputs[prefix+'taper_ratio'][0]==pytest.approx(surface['tip_chord_m']/surface['root_chord_m'])
    assert domain_ledger(g)['inactive_empirical_components'][0]['name']=='FAST-GA k_vh'


def test_inconsistent_airfoil_or_nonfinite_parameter_rejected():
    p,r=synthetic_source();g=r['summary']['geometry']
    g['surface_parameters']['vertical_tail']['thickness_ratio']=.1
    with pytest.raises(ValueError,match='翼型'):geometry_parameters(g)
    g['surface_parameters']['vertical_tail']['thickness_ratio']=.12
    g['surface_parameters']['vertical_tail']['aspect_ratio']=float('nan')
    with pytest.raises(ValueError,match='有限'):geometry_parameters(g)


def test_model_domains_preflight_preserves_inputs(monkeypatch,tmp_path):
    from wingdesignhub.tool_health import preflight
    from wingdesignhub.requirements import DesignProject
    from wingdesignhub.propulsion_feedback import CoupledOptions
    from dataclasses import asdict,replace
    monkeypatch.setattr('wingdesignhub.ccblade_adapter.runtime',lambda root:{})
    p=DesignProject().confirmed().to_dict();before=deepcopy(p)
    o=CoupledOptions();o=replace(o,propeller=replace(o.propeller,rpm=2700))
    rows=preflight(tmp_path,'coupled',p,asdict(o))
    assert any(r['code']=='propeller_tip_mach_exceeded' for r in rows)
    re=next(r for r in rows if r['code']=='uninduced_reynolds_screen')
    assert re['estimated_max']>re['estimated_min']>0
    assert p==before
