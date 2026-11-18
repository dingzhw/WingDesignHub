from pathlib import Path
from streamlit.testing.v1 import AppTest


def test_first_level_editor_confirmation_and_invalid_loading():
    a=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py')).run(timeout=30)
    next(x for x in a.toggle if x.label=='启用起降、装载重心与纵向一级约束').set_value(True).run()
    assert not a.exception
    confirm=lambda:next(x for x in a.checkbox if x.label.startswith('我已核对上述'))
    confirm().check().run();assert confirm().value
    next(x for x in a.number_input if x.label=='缺失俯仰矩敏感性±ΔCm').set_value(.06).run()
    assert not a.exception and not confirm().value
    next(x for x in a.number_input if x.label=='附加装载场景数量').set_value(1).run()
    assert not a.exception and any('启用部件' in x.value for x in a.error)
    assert a.button(key='new_blank_design')


def test_constraint_display_units_and_states_preserve_inputs():
    from copy import deepcopy
    from wingdesignhub.constraint_states import row
    rows=[row('p','爬升','met',value=120000.,limit=130000.,margin=10000.,unit='W'),
          row('cg','重心','exceeded',value=[.08,.09],limit=[.15,.35],margin=-.07,unit='MAC'),
          row('r','航程','not_applicable'),row('s','结构','not_calculated')]
    original=deepcopy(rows)
    a=AppTest.from_string("import streamlit as st\nfrom wingdesignhub.constraint_ui import render\nrender({'constraint_states':st.session_state['rows']})")
    a.session_state['rows']=rows;a.run()
    assert not a.exception and rows==original
    shown=a.dataframe[0].value
    assert set(shown['状态'])=={'满足','超限','不适用','未计算'}
    assert shown.iloc[0]['计算值']=='120' and shown.iloc[0]['单位']=='kW'
    assert shown.iloc[1]['计算值']=='8 ～ 9' and shown.iloc[1]['单位']=='% MAC'
