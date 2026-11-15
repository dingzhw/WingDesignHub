from pathlib import Path
from uuid import uuid4
import pytest
from streamlit.testing.v1 import AppTest


def test_flight_page_failure(monkeypatch):
    from wingdesignhub import flight_service
    monkeypatch.setattr(flight_service,'run_flight_structure',lambda *a:{'run_id':'fixture','status':'failed','error':'目标升力超出线性域'})
    app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py')).run(timeout=30)
    app.sidebar.radio[0].set_value('载荷与屈曲').run();app.button[0].click().run(timeout=30)
    assert not app.exception and app.error and not app.success
    assert '线性域' in app.error[0].value


@pytest.mark.parametrize('status',['screened','executed_with_limits'])
def test_flight_page_exposes_screen_and_loads(monkeypatch,status):
    from wingdesignhub import flight_service
    root=Path(__file__).resolve().parents[1];run_id=uuid4().hex;work=root/'runs'/run_id
    for name in ('loads.json','buckling.json','solve/wing.inp','solve/wing.frd'):
        p=work/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('UI fixture')
    s={'aero':{'alpha_deg':5.6},'tip_mean_z_m':.03,'structure_mass':{'mass_kg':100},'yield_margin':4.,
       'buckling':{'max_interaction_utilization':4. if status=='executed_with_limits' else .4,
                   'panels':[{'panel':'upper_skin','bay':0,'interaction_utilization':4. if status=='executed_with_limits' else .4,'screen_passed':status=='screened'}]},
       'load_components':[{'name':'structure','limit_force_n':[0,0,-1000],'limit_moment_nm':[-2000,0,0]}],
       'screening_issues':['局部板屈曲工程筛查未满足'] if status=='executed_with_limits' else [],'limits':['合成材料输入']}
    monkeypatch.setattr(flight_service,'run_flight_structure',lambda *a:{'run_id':run_id,'status':status,'summary':s})
    app=AppTest.from_file(str(root/'app.py')).run(timeout=30);app.sidebar.radio[0].set_value('载荷与屈曲').run()
    app.button[0].click().run(timeout=30)
    assert not app.exception and len(app.metric)==3 and len(app.dataframe)==3
    assert len(app.get('download_button'))==6
    assert bool(app.warning)==(status=='executed_with_limits') and bool(app.success)==(status=='screened')
