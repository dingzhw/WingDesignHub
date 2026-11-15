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
