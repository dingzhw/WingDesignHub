import pytest
pytest.importorskip('fastga')
from wingdesignhub.fastga_compat import compatibility
from wingdesignhub.fastga_plugins.reserve import (CorrectReserve,ComputeReserve,FUEL,TIME,RESERVE_TIME,FACTOR,OUTPUT,
                                                SUBMODEL_RESERVES,RESERVE_PROVIDER,MIN_CRUISE_DURATION)


@pytest.mark.parametrize('duration',[7200.,3600.,MIN_CRUISE_DURATION/4])
def test_correct_jacobian_independent_fd_and_unchanged_primal(duration):
    c=CorrectReserve();values={FUEL:120.,TIME:duration,RESERVE_TIME:2700.,FACTOR:1.2}
    actual={};original={};c.compute(values,actual);ComputeReserve().compute(values,original)
    assert actual==original
    jac={};c.compute_partials(values,jac)
    for key,value in values.items():
        step=abs(value)*1e-5;plus={};minus={}
        c.compute({**values,key:value+step},plus);c.compute({**values,key:value-step},minus)
        fd=(plus[OUTPUT]-minus[OUTPUT])/(2*step)
        assert jac[OUTPUT,key]==pytest.approx(fd,rel=1e-8,abs=1e-8)


def test_reserve_openmdao_registered_totals_and_restore():
    import openmdao.api as om
    import fastoad.api as oad
    models=dict(oad.RegisterSubmodel.active_models)
    with compatibility():
        assert oad.RegisterSubmodel.active_models[SUBMODEL_RESERVES]==RESERVE_PROVIDER
        c=oad.RegisterSubmodel.get_submodel(SUBMODEL_RESERVES);assert isinstance(c,CorrectReserve)
        prob=om.Problem(reports=False);prob.model.add_subsystem('reserve',c,promotes=['*']);prob.setup()
        for n,v in {FUEL:120.,TIME:7200.,RESERVE_TIME:2700.,FACTOR:1.}.items():prob.set_val(n,v)
        prob.run_model();totals=prob.compute_totals(of=[OUTPUT],wrt=[FUEL,TIME,RESERVE_TIME,FACTOR])
        for n,v in {FUEL:.375,TIME:-45/7200,RESERVE_TIME:1/60,FACTOR:45.}.items():
            assert totals[OUTPUT,n].item()==pytest.approx(v)
        prob.cleanup()
    assert oad.RegisterSubmodel.active_models==models
