from pathlib import Path
from uuid import uuid4
import pytest
from streamlit.testing.v1 import AppTest


def test_plate_failure_visible(monkeypatch):
    from wingdesignhub import plate_service
    monkeypatch.setattr(plate_service,'run_plate_analysis',lambda *a:{'run_id':'fixture','status':'failed','error':'模态输出不完整'})
    app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py')).run(timeout=30)
    app.sidebar.radio[0].set_value('代表板屈曲').run();app.button[0].click().run(timeout=30)
    assert not app.exception and app.error and not app.success


@pytest.mark.parametrize('status',['executed_with_limits','eigenvalue_computed'])
def test_plate_results_preview_and_limits(monkeypatch,status):
    from wingdesignhub import plate_service
    root=Path(__file__).resolve().parents[1];run_id=uuid4().hex;work=root/'runs'/run_id/'plate';work.mkdir(parents=True)
    for name in ('plate.inp','plate.frd','solver_reference.json'):(work/name).write_text('UI fixture')
    (work/'mode_preview.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"/>')
    factor=.075 if status=='executed_with_limits' else 3.
    monkeypatch.setattr(plate_service,'run_plate_analysis',lambda *a:{'run_id':run_id,'status':status,
        'summary':{'first_factor':factor,'critical_compression_pa':3e6,'factors':[factor],'limits':['理想平板']}})
    app=AppTest.from_file(str(root/'app.py')).run(timeout=30);app.sidebar.radio[0].set_value('代表板屈曲').run()
    app.button[0].click().run(timeout=30)
    assert not app.exception and len(app.metric)==2 and len(app.get('download_button'))==5
    assert bool(app.warning)==(factor<1) and bool(app.success)==(factor>=1)
