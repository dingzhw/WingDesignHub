import math
import pytest
from wingdesignhub.fastga_interface import VARIABLES
from wingdesignhub.fastga_worker import audit_problem, mission_ledger


def test_runtime_contract_rejects_source_role_changes():
    import numpy as np
    class Problem:
        def __init__(self): self.model=self
        def get_io_metadata(self, **kw):
            return {('_auto_ivc.' if role=='input' else 'solver.')+key:
                    {'prom_name': name, 'units':unit} for key,(name,unit,role) in VARIABLES.items()}
        def get_val(self,name,units=None):return np.array([1.])
    p=Problem();values,bindings=audit_problem(p)
    assert len(bindings)==20 and bindings['mtow']['role']=='output'
    original=p.get_io_metadata
    p.get_io_metadata=lambda **kw:{'_auto_ivc.'+k:v for k,v in original(**kw).items()}
    with pytest.raises(ValueError,match='角色变化'):audit_problem(p)


def test_mission_ledger_independently_checks_mass_fuel_range_and_reserve():
    import numpy as np
    prefix='data:mission:sizing:'
    entries={prefix+p+':fuel':1. for p in ('taxi_out','takeoff','initial_climb','main_route:climb','main_route:descent','taxi_in')}
    entries.update({prefix+'main_route:cruise:fuel':10.,prefix+'main_route:reserve:fuel':5.,
                    'settings:mission:sizing:main_route:reserve:k_factor':1.})
    for phase in ('climb','cruise','descent'):
        entries[prefix+'main_route:'+phase+':distance']=1000.
        entries[prefix+'main_route:'+phase+':duration']=100.
    class Problem:
        def get_val(self,name,units=None):return np.array([entries[name]])
    v={'mtow':501.,'owe':100.,'payload':380.,'fuel':21.,'range':3000.,'reserve_duration':50.,
       'passengers_excluding_two_pilots':2.,'person_mass':80.,'luggage':60.}
    r=mission_ledger(Problem(),v)
    assert all(r['checks'].values()) and r['non_reserve_fuel_kg']==16.
    # Deliberate duplicate reserve and distance errors must remain visible.
    r=mission_ledger(Problem(),{**v,'fuel':26.,'range':4000.,'payload':220.})
    assert not r['checks']['fuel_sum_kg'] and not r['checks']['range_m'] and not r['checks']['payload_formula_kg']


def test_pinned_upstream_reserve_primal_and_gradient_boundary():
    # The interface is evaluation-only until this upstream analytic Jacobian is fixed.
    import wingdesignhub.fastga_compat  # initialize decorated upstream registry
    from fastga.models.performances.mission.mission_components.reserve import ComputeReserve
    c=ComputeReserve();p='data:mission:sizing:main_route:';o=p+'reserve:fuel'
    values={p+'cruise:fuel':120.,p+'cruise:duration':7200.,p+'reserve:duration':2700.,
            'settings:mission:sizing:main_route:reserve:k_factor':1.}
    out={};c.compute(values,out);assert out[o]==pytest.approx(45.)
    analytic={};c.compute_partials(values,analytic)
    fd={}
    for k,x in values.items():
        h=max(abs(x)*1e-5,1e-5);plus={};minus={}
        c.compute({**values,k:x+h},plus);c.compute({**values,k:x-h},minus)
        fd[k]=(plus[o]-minus[o])/(2*h)
    expected=[.375,-45/7200,1/60,45.]
    assert list(fd.values())==pytest.approx(expected,rel=1e-8)
    assert all(not math.isclose(analytic[o,k],fd[k],rel_tol=.01) for k in values)
