from pathlib import Path
import pytest
from streamlit.testing.v1 import AppTest


def test_first_time_user_can_run_and_view_results():
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1]/"app.py")).run(timeout=30)
    assert not app.exception
    app.sidebar.radio[0].set_value("开始计算").run()
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


def test_mesh_page_displays_failure_diagnostics(monkeypatch):
    from wingdesignhub import structure_service
    monkeypatch.setattr(structure_service,'run_structure_mesh',lambda *args:{'run_id':'test','status':'failed',
                        'error':'网格未通过','diagnostic':'存在零面积或退化单元'})
    app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py')).run(timeout=30)
    app.sidebar.radio[0].set_value('结构网格').run()
    app.button[0].click().run(timeout=30)
    assert not app.exception
    assert app.error and '退化' in app.code[0].value


def test_mesh_page_success_has_preview_and_downloads(monkeypatch):
    from uuid import uuid4
    from wingdesignhub import structure_service
    root=Path(__file__).resolve().parents[1];run_id=uuid4().hex
    work=root/'runs'/run_id/'mesh';work.mkdir(parents=True)
    (work/'mesh_preview.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><path d="M0,0 L10,10"/></svg>')
    (work/'structure.vsp3').write_text('UI fixture');(work/'wing.inp').write_text('UI fixture')
    monkeypatch.setattr(structure_service,'run_structure_mesh',lambda *args:{'run_id':run_id,'status':'mesh_checked',
        'summary':{'metrics':{'nodes':3,'elements':1,'shell_material_mass_kg':1.},'limits':['仅网格检查']}})
    app=AppTest.from_file(str(root/'app.py')).run(timeout=30)
    app.sidebar.radio[0].set_value('结构网格').run()
    app.button[0].click().run(timeout=30)
    assert not app.exception
    assert app.success and len(app.metric)==3
    assert len(app.get('download_button'))==4


@pytest.mark.parametrize('edges',[(.05,.01),(.8,.6)])
def test_mesh_page_accepts_valid_config_ranges(monkeypatch,edges):
    from wingdesignhub import fea_mesh
    base=fea_mesh.StructureMeshCase(half_span_m=2.,chord_m=3.,max_edge_m=edges[0],min_edge_m=edges[1],
                                  skin_thickness_m=.02,elastic_modulus_pa=63e9)
    base.validate()
    monkeypatch.setattr(fea_mesh,'StructureMeshCase',lambda:base)
    app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py')).run(timeout=30)
    app.sidebar.radio[0].set_value('结构网格').run()
    assert not app.exception
    assert any('E=63 GPa' in item.value for item in app.caption)
    values={item.label:item.value for item in app.number_input}
    assert values['蒙皮厚度（mm）']==20.
    assert values['目标最大网格边长（m）']==edges[0]
    assert values['最小网格边长（m）']==edges[1]


def test_mesh_benchmark_failure_never_claims_pass(monkeypatch):
    from wingdesignhub import service
    case={'metrics':{'nodes':3,'elements':1,'shell_material_mass_kg':1.}}
    monkeypatch.setattr(service,'run_reference',lambda *args:{'status':'failed','error':'差异超过阈值',
        'summary':{'coarse':case,'fine':case,'longer':case,'passed':False}})
    app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py')).run(timeout=30)
    app.sidebar.radio[0].set_value('公开基准算例').run()
    app.selectbox[0].set_value('OpenVSP 结构网格加密与翼展变化').run()
    app.button[0].click().run(timeout=30)
    assert not app.exception and app.error and not app.success
    assert any('未通过验收' in item.value for item in app.warning)
    assert not any('检查通过' in item.value for item in app.caption)


def test_static_page_failure_is_visible(monkeypatch):
    from wingdesignhub import static_service
    monkeypatch.setattr(static_service,'run_wing_static',lambda *args:{'run_id':'fixture','status':'failed',
        'error':'静力检查失败','diagnostic':'展开几何超出预期厚度范围'})
    app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py')).run(timeout=30)
    app.sidebar.radio[0].set_value('机翼静力').run();app.button[0].click().run(timeout=30)
    assert not app.exception and app.error and not app.success
    assert '展开几何' in app.code[0].value


@pytest.mark.parametrize('status',['static_checked','executed_with_limits'])
def test_static_page_outputs_and_limit_status(monkeypatch,status):
    from uuid import uuid4
    from wingdesignhub import static_service
    root=Path(__file__).resolve().parents[1];run_id=uuid4().hex;work=root/'runs'/run_id
    for name in ('static/solve/wing.inp','static/solve/wing.frd','static/loads.json'):
        p=work/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('UI fixture')
    summary={'tip_mean_z_m':.06,'peak_von_mises_pa':60e6,'yield_margin':2.,
             'mapping':{'input_force_n':[0.,0.,7500.]},'limits':['尚未校核屈曲']}
    monkeypatch.setattr(static_service,'run_wing_static',lambda *args:{'run_id':run_id,'status':status,'summary':summary})
    app=AppTest.from_file(str(root/'app.py')).run(timeout=30)
    app.sidebar.radio[0].set_value('机翼静力').run();app.button[0].click().run(timeout=30)
    assert not app.exception and len(app.metric)==3
    assert len(app.get('download_button'))==5
    assert bool(app.warning)==(status=='executed_with_limits')
    assert bool(app.success)==(status=='static_checked')
