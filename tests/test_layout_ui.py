from pathlib import Path
from streamlit.testing.v1 import AppTest
from wingdesignhub.requirements import DesignProject
from wingdesignhub.layout import default_layout
from dataclasses import replace
from wingdesignhub.project_archive import build_bundle,read_bundle


def test_layout_edit_invalidates_confirmation_and_keeps_draft():
    a=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py')).run(timeout=30)
    next(x for x in a.toggle if x.label=='启用分项布置与装载位置').set_value(True).run()
    assert not a.exception
    a.checkbox[0].check().run();assert a.checkbox[0].value
    next(x for x in a.number_input if x.label=='主翼安装角（度）').set_value(2.).run()
    assert not a.exception and not a.checkbox[0].value
    next(x for x in a.number_input if x.label=='行李载荷占比').set_value(.8).run()
    assert not a.exception and a.error
    assert next(x for x in a.number_input if x.label=='主翼安装角（度）').value==2.


def test_layout_draft_archive_roundtrip_and_ui(tmp_path):
    p=DesignProject();p=replace(p,sizing=replace(p.sizing,layout=default_layout())).confirmed()
    bundle=build_bundle(p,tmp_path)
    parsed=read_bundle(bundle);assert parsed['project']==p
    a=AppTest.from_string('from wingdesignhub.layout_ui import editor\nfrom wingdesignhub.layout import default_layout\neditor(default_layout(),"demo")').run()
    assert not a.exception and a.toggle[0].value
    assert next(x for x in a.number_input if x.label=='燃油位置（机长比例）').value==.39
