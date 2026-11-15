from pathlib import Path
from streamlit.testing.v1 import AppTest


def test_first_time_user_can_run_and_view_results():
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1]/"app.py")).run(timeout=30)
    assert not app.exception
    app.button[0].click().run(timeout=30)
    assert not app.exception
    assert app.success
    assert len(app.metric) == 2
    app.sidebar.radio[0].set_value("验证与路线图").run()
    assert not app.exception


def test_reference_limits_are_visible_without_expanding_json(monkeypatch):
    from wingdesignhub import service
    summary = {"outputs_kg": {"data:weight:aircraft:MTOW": 1710., "data:weight:aircraft:OWE": 1081.,
                              "data:mission:sizing:fuel": 249.},
               "final_domain_checks": [{"parameter": "takeoff_elevator_angle_deg", "value": -20.,
                                         "lower": -.08, "upper": 79.32, "within_range": False}]}
    monkeypatch.setattr(service, "run_reference", lambda *a: {"status": "executed_with_limits", "summary": summary})
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1]/"app.py")).run(timeout=30)
    app.sidebar.radio[0].set_value("公开基准算例").run()
    app.button[0].click().run(timeout=30)
    assert not app.exception
    assert len(app.warning) == 2
    assert not app.success
    assert "-20.0000" in app.warning[1].value
