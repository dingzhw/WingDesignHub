"""Domain diagnostics must survive the isolated worker before geometry is available."""
from dataclasses import asdict
from types import SimpleNamespace
import json
import pytest
from wingdesignhub import coupled_worker
from wingdesignhub.requirements import DesignProject
from wingdesignhub.propulsion_feedback import CoupledOptions
from wingdesignhub.propulsion_model import PropulsionError
from wingdesignhub.service import write_json


@pytest.mark.parametrize('code,last',[
    ('propeller_tip_mach_exceeded',None),
    ('engine_sfc_out_of_domain',{'native':object()}),
    (None,None),
])
def test_worker_preserves_solver_domain_result_without_accessing_geometry(tmp_path,monkeypatch,code,last):
    work=tmp_path/'runs'/'case';work.mkdir(parents=True)
    write_json(work/'input.json',DesignProject().confirmed().to_dict())
    write_json(work/'options.json',asdict(CoupledOptions()))
    write_json(work/'parent_result.json',{'summary':{'converged':True}})
    summary={'status':'out_of_domain','converged':False,'diagnostics':['domain boundary encountered'],
             'diagnostic_context':{'actual':.8,'limit':.75},'iterations':[]}
    if code:summary['error_code']=code
    class Mass:
        last_inputs={};audit={}
        def __enter__(self):return self
        def __exit__(self,*args):return False
    monkeypatch.setattr(coupled_worker,'FastGAMassModel',Mass)
    monkeypatch.setattr(coupled_worker,'PropulsionFeedback',lambda *a:SimpleNamespace(last=last))
    monkeypatch.setattr(coupled_worker,'solve_design',lambda *a,**k:summary)
    with pytest.raises(PropulsionError,match='domain boundary encountered') as caught:coupled_worker.main(work)
    assert caught.value.status==(code or 'out_of_domain')
    failure=json.loads((work/'failure.json').read_text('utf-8'))
    assert failure=={'status':code or 'out_of_domain','error':'domain boundary encountered','diagnostic_context':summary['diagnostic_context']}
    assert json.loads((work/'incomplete_summary.json').read_text('utf-8'))==summary
    assert not (work/'summary.json').exists() and not (work/'model_evidence.json').exists()
    assert 'NoneType' not in (work/'error.log').read_text('utf-8')
