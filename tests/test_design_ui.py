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
    next(x for x in a.selectbox if x.label=='起飞重量模式').set_value('fixed').run()
    assert any(x.label == '规定起飞重量（kg）' for x in a.number_input)
    next(x for x in a.selectbox if x.label=='任务类型').set_value('transit_loiter').run()
    assert any(x.label == '往返转场总航程（km）' for x in a.number_input)
    assert any(x.label == '额外留空时长（h）' for x in a.number_input)
    next(x for x in a.selectbox if x.label=='起飞重量模式').set_value('solve').run()
    assert not any(x.label == '规定起飞重量（kg）' for x in a.number_input)
    next(x for x in a.selectbox if x.label=='任务类型').set_value('endurance_only').run()
    assert not any('航程（km）' in x.label for x in a.number_input)
    assert not a.exception


def test_ui_conflicting_weight_is_not_success():
    a = app();next(x for x in a.selectbox if x.label=='起飞重量模式').set_value('upper_bound').run()
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


@pytest.mark.parametrize('status',['failed','not_converged','constraints_not_met','out_of_domain'])
def test_sizing_unsuccessful_states_are_visible(monkeypatch,status):
    from wingdesignhub import sizing_service
    def run(p,root):
        return {'run_id':'test','definition_sha256':p.definition_hash(),'status':status,
                'error':'测试总体失败','summary':{'diagnostics':['测试诊断']}}
    monkeypatch.setattr(sizing_service,'run_sizing',run)
    a=app();assert a.button(key='run_sizing').disabled
    a.checkbox[0].check().run();a.button(key='run_sizing').click().run()
    assert not a.exception and a.error and not a.success


def test_actual_new_design_ui_and_assumption_change_invalidate_result():
    pytest.importorskip('fastga')
    a=app();a.checkbox[0].check().run();a.button(key='run_sizing').click().run(timeout=60)
    assert not a.exception and not a.error and any('迭代已收敛' in x.value for x in a.warning)
    assert len(a.dataframe)>=5
    next(x for x in a.number_input if x.label=='机翼展弦比').set_value(8.).run()
    assert not a.exception and not a.checkbox[0].value and a.button(key='run_sizing').disabled
    assert any('上次总体结果' in x.value for x in a.info)
