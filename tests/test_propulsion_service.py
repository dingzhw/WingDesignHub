"""Failure preservation and archive/UI contracts using declared synthetic records."""
from dataclasses import asdict,replace
from pathlib import Path
from uuid import uuid4
import json
import pytest
from wingdesignhub import __version__
from wingdesignhub.requirements import DesignProject
from wingdesignhub.aero_feedback import MissionAeroTable,FeedbackOptions
from wingdesignhub.geometry_service import source_hashes
from wingdesignhub.service import write_json,get_results,generate_report
from wingdesignhub.feedback_evidence import pack_native
from wingdesignhub.propulsion_service import run_propulsion,validate_parent
from wingdesignhub.propulsion_model import PropulsionError
from wingdesignhub.project_archive import build_bundle,read_bundle
from wingdesignhub.adapters import sha256


@pytest.fixture
def frozen(tmp_path):
    p=DesignProject().confirmed();records=[]
    options=asdict(FeedbackOptions());audit={'options':options,'table_verified':True,'timestep_verified':True}
    summary={'converged':True,'geometry':{'wing_area_m2':20.},'cg':{'loaded_mass_kg':1200.},
             'mission':{'takeoff_fuel_kg':200.}}
    def native(m,cg,v,h,r):return {'mass_kg':m,'cg_x_m':cg,'speed_m_s':v,'altitude_m':h,'roc_m_s':r,
        'cd':.04,'components':{'induced':.01,'profile':.01,'body':.01,'allowance':.01},'alpha_deg':2.,'elevator_deg':-1.}
    table=MissionAeroTable(native,1000,2000,2,[1000,1300],3,[(60,0,[0,2000])],20)
    for mode in ('overall_sizing','overall_feedback'):
        work=tmp_path/'runs'/uuid4().hex;work.mkdir(parents=True)
        write_json(work/'input.json',p.to_dict())
        record={'run_id':work.name,'mode':mode,'version':__version__,'status':'concept_checked_with_limits',
            'definition_sha256':p.definition_hash(),'input_hash':sha256(work/'input.json'),'source_hashes':source_hashes()}
        s=dict(summary)
        if records:
            s['aerodynamic_feedback']=audit;record.update(parent_run_id=records[0]['run_id'],options=options)
            write_json(work/'parent_result.json',records[0]);record['parent_result_sha256']=sha256(work/'parent_result.json')
            write_json(work/'options.json',options);write_json(work/'feedback_verification.json',audit)
            write_json(work/'aero_table.json',table.to_dict());write_json(work/'mission_trace.json',[])
            (work/'final_geometry').mkdir();write_json(work/'final_geometry/geometry_contract.json',{'propeller':{'diameter_m':1.9}})
            pack_native(work)
        record['summary']=s;write_json(work/'summary.json',s)
        record['artifact_hashes']={f.relative_to(work).as_posix():sha256(f) for f in work.rglob('*') if f.is_file()}
        write_json(work/'result.json',record);records.append(record)
    return tmp_path,p,records


def fail_run(frozen,monkeypatch):
    root,p,records=frozen
    def fail(*args):raise PropulsionError('propeller_thrust_unavailable','injected uncovered thrust',thrust_n=99999.)
    monkeypatch.setattr('wingdesignhub.propulsion_service.perform_replay',fail)
    return run_propulsion(p,root,records[1]['run_id'])


@pytest.mark.parametrize('version',['0.2.4','99.0.0'])
def test_frozen_parent_rejects_unsupported_version(frozen,version):
    from wingdesignhub.propulsion_service import validate_parent
    root,p,records=frozen
    with pytest.raises(ValueError,match='已验收'):
        validate_parent(p,{**records[1],'version':version},{})


def test_failure_remains_traceable_and_saved_with_exact_frozen_parent(frozen,monkeypatch):
    root,p,records=frozen;r=fail_run(frozen,monkeypatch)
    assert r['status']=='propeller_thrust_unavailable' and 'summary' not in r
    assert get_results(root,r['run_id'])==r
    assert 'injected uncovered thrust' in generate_report(r,root=root)
    loaded=read_bundle(build_bundle(p,root,records[0],feedback_record=records[1],propulsion_record=r))
    assert loaded['propulsion_records']==[r] and loaded['current_source_matches']
    assert get_results(root,records[1]['run_id'])==records[1]
    with pytest.raises(ValueError,match='来源气动'):build_bundle(p,root,records[0],propulsion_record=r)


def test_frozen_parent_rejects_changed_requirement_and_aero_source(frozen):
    root,p,records=frozen
    with pytest.raises(ValueError,match='需求'):run_propulsion(replace(p,payload_kg=351).confirmed(),root,records[1]['run_id'])
    parent=dict(records[1]);parent['source_hashes']={**parent['source_hashes'],'aircraft_drag.py':'changed'}
    work=root/'runs'/parent['run_id'];files={n:(work/n).read_bytes() for n in ('input.json','summary.json','feedback_verification.json','aero_table.json')}
    with pytest.raises(ValueError,match='气动模型'):validate_parent(p,parent,files)


def test_propulsion_ui_failure_and_changed_options(frozen,monkeypatch):
    from streamlit.testing.v1 import AppTest
    root,p,records=frozen;r=fail_run(frozen,monkeypatch)
    monkeypatch.setattr('wingdesignhub.propulsion_ui.run_propulsion',lambda *args:r)
    code=f'''from pathlib import Path
import json
from wingdesignhub.requirements import DesignProject
from wingdesignhub.service import get_results
from wingdesignhub.propulsion_ui import render
root=Path({str(root)!r})
parent=get_results(root,{records[1]['run_id']!r})
p=DesignProject.from_dict(json.loads((root/'runs'/parent['run_id']/'input.json').read_text(encoding='utf-8')))
render(p,root,parent)
'''
    app=AppTest.from_string(code,default_timeout=30).run()
    app.button(key='current_propulsion_run').click().run()
    assert not app.exception and any('injected uncovered thrust' in x.value for x in app.error)
    app.number_input(key='current_propulsion_rpm').set_value(2500.).run()
    assert any('设置已修改' in x.value for x in app.warning)
