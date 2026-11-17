from dataclasses import asdict
import pytest
from wingdesignhub.requirements import DesignProject
from wingdesignhub.propulsion_feedback import CoupledOptions
from wingdesignhub.tool_health import preflight,check_ccblade


def test_missing_tools_and_julia_reported_before_launch(tmp_path,monkeypatch):
    monkeypatch.setattr('wingdesignhub.tool_health.tool_paths',lambda root:{k:str(tmp_path/k) for k in ('openvsp','avl','xfoil')})
    rows=preflight(tmp_path,'coupled',DesignProject().confirmed().to_dict(),asdict(CoupledOptions()))
    assert {r['tool'] for r in rows if r['code']=='tool_missing'}=={'openvsp','avl','xfoil'}
    assert any(r['code']=='ccblade_not_configured' and r['severity']=='error' for r in rows)
    from wingdesignhub.jobs import submit_job
    with pytest.raises(ValueError,match='ccblade_not_configured'):
        submit_job(tmp_path,'coupled',DesignProject().confirmed(),'0'*32,CoupledOptions())
    assert not (tmp_path/'local/jobs').exists()


@pytest.mark.parametrize('bad',['version','path'])
def test_actual_julia_import_must_match_config(tmp_path,monkeypatch,bad):
    package=tmp_path/'package';(package/'src').mkdir(parents=True)
    source=package/'src/CCBlade.jl';source.write_text('# test fixture',encoding='utf-8')
    monkeypatch.setattr('wingdesignhub.ccblade_adapter.runtime',lambda root:{'julia':'julia','project':str(tmp_path),'package':str(package)})
    version='9.9.9' if bad=='version' else '1.0.0'
    actual=source if bad=='version' else tmp_path/'different/src/CCBlade.jl'
    monkeypatch.setattr('wingdesignhub.adapters.execute',lambda *a,**k:f'WDH_VERSION={version}\nWDH_PATH={actual}\nWDH_JULIA=1.12.4\n')
    with pytest.raises(ValueError,match='版本或路径'):
        check_ccblade(tmp_path,tmp_path/'check')
