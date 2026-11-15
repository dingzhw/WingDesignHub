from pathlib import Path
import pytest
from streamlit.testing.v1 import AppTest


def app():
    return AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py')).run(timeout=30)


def test_main_entry_confirm_save_and_invalidate():
    a = app()
    assert not a.exception and a.sidebar.radio[0].value == '新建飞机方案'
    a.checkbox[0].check().run()
    a.button(key='prepare_design').click().run()
    assert not a.exception and a.success and '尚未求解' in a.success[0].value
    next(x for x in a.number_input if x.label.startswith('任务载荷')).set_value(400.).run()
    assert not a.checkbox[0].value and not a.success
    assert any('上次需求' in x.value for x in a.info)


def test_ui_weight_and_mission_relations():
    a = app()
    a.selectbox[0].set_value('fixed').run()
    assert any(x.label == '规定起飞重量（kg）' for x in a.number_input)
    a.selectbox[1].set_value('transit_loiter').run()
    assert any(x.label == '往返转场总航程（km）' for x in a.number_input)
    assert any(x.label == '额外留空时长（h）' for x in a.number_input)
    a.selectbox[0].set_value('solve').run()
    assert not any(x.label == '规定起飞重量（kg）' for x in a.number_input)
    a.selectbox[1].set_value('endurance_only').run()
    assert not any('航程（km）' in x.label for x in a.number_input)
    assert not a.exception


def test_ui_conflicting_weight_is_not_success():
    a = app();a.selectbox[0].set_value('upper_bound').run()
    next(x for x in a.number_input if x.label.startswith('起飞重量上限')).set_value(300.).run()
    a.checkbox[0].check().run();a.button(key='prepare_design').click().run()
    assert not a.exception and a.error and not a.success


@pytest.mark.parametrize('status', ['failed', 'executed_with_limits'])
def test_reference_explicit_separate_task_and_status(monkeypatch, status):
    from wingdesignhub import design_service
    seen=[]
    def run(root):
        seen.append(root)
        return {'status':status,'error':'测试失败诊断','summary':{'outputs_kg':{'MTOW':1710.},'mission_ledger':{'checks':{'mass':True}}}}
    monkeypatch.setattr(design_service, 'run_fastga_reference', run)
    a = app();a.button(key='fastga_reference').click().run()
    assert not a.exception and len(seen)==1 and not a.success
    assert a.error if status == 'failed' else a.warning
