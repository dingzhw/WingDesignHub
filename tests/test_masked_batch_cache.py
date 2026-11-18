from copy import deepcopy
import math
import pytest
from wingdesignhub.batch_validation import cacheable_batch
from wingdesignhub.propulsion_model import PropulsionError


def batch():
    point={'speed_m_s':50.,'rpm':2400.}
    power=100.*2400.*math.pi/30
    solved={**point,'status':'valid','thrust_n':300.,'torque_nm':100.,'shaft_power_w':power,'efficiency':15000./power,'diagnostics':[]}
    return {'points':[point,point]}, {'points':[solved,{**solved,'status':'out_of_domain','diagnostics':['outside polar']}]}


def test_completed_batch_preserves_domain_mask_and_values():
    request,result=batch();original=deepcopy(result)
    assert cacheable_batch(request,result)
    assert result==original and result['points'][1]['status']=='out_of_domain'


def test_solver_failure_is_never_reusable():
    request,result=batch();result['points'][1]={'speed_m_s':50.,'rpm':2400.,'status':'solver_failed','error':'iteration failed'}
    assert not cacheable_batch(request,result)


@pytest.mark.parametrize('field,value', [('rpm',2400.+1e-10),('status','unknown'),('shaft_power_w',1.),('efficiency',float('nan')),('diagnostics',[])])
def test_bad_mask_or_physics_rejected(field,value):
    request,result=batch();result['points'][1][field]=value
    with pytest.raises(PropulsionError):cacheable_batch(request,result)
