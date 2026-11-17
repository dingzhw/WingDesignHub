"""Read the completed native release run; verify selection, archive and UI.

No engineering solver is rerun. Run serially after validate_v031.py collect.
AppTest checks widget data and state, not rendered browser appearance.
"""
from pathlib import Path
import gc
import json
import time
from streamlit.testing.v1 import AppTest
from wingdesignhub.jobs import read,atomic
from wingdesignhub.geometry_service import source_hashes
from wingdesignhub.requirements import DesignProject
from wingdesignhub.service import get_results
from wingdesignhub.project_archive import build_bundle,read_bundle,save_bundle,load_saved,digest

ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT/'local/v031/workflow'


def main():
    state=read(ROOT/'local/v031/native/checkpoint.json')
    assert state['source_hashes']==source_hashes()
    WORK.mkdir(parents=True,exist_ok=True)
    checks={};timings={}
    project=DesignProject.from_dict(state['project'])
    seed=get_results(ROOT,state['seed_run_id']);native=get_results(ROOT,state['native_run_id'])
    assert native['parent_run_id']==seed['run_id']
    start=time.perf_counter()
    data=build_bundle(project,ROOT,seed,coupled_record=native,current_run_id=native['run_id'])
    timings['build_bundle_including_validation_s']=time.perf_counter()-start
    size=len(data);bundle_sha=digest(data)
    start=time.perf_counter();parsed=read_bundle(data);timings['read_and_verify_s']=time.perf_counter()-start
    checks['selected_native_record']=parsed['manifest']['current_run_id']==native['run_id']
    checks['exact_inputs_and_results']=parsed['input']==project.to_dict() and parsed['records']==[seed] and parsed['coupled_records']==[native]
    checks['current_sources_match']=parsed['current_source_matches']
    checks['selected_report_matches']=parsed['files']['reports/report.html']==(ROOT/'runs'/native['run_id']/'report.html').read_bytes()
    checks['final_mesh_preserved']=parsed['files'][f"runs/{native['run_id']}/final_geometry/surface_mesh.json"]==(ROOT/'runs'/native['run_id']/'final_geometry/surface_mesh.json').read_bytes()
    del parsed;gc.collect()
    start=time.perf_counter();index=save_bundle(data,WORK);timings['save_with_verification_s']=time.perf_counter()-start
    del data;gc.collect()
    start=time.perf_counter();opened=load_saved(WORK,index['archive_id']);timings['load_with_verification_s']=time.perf_counter()-start
    checks['saved_reopened_same_bundle']=opened['bundle_sha256']==bundle_sha
    checks['saved_selected_id']=opened['manifest']['current_run_id']==native['run_id']
    del opened;gc.collect()
    atomic(WORK/'archive-validation.json',{'checks':checks,'timings':timings,'bytes':size,'sha256':bundle_sha,'archive_id':index['archive_id']})
    assert all(checks.values()),checks

    code="from wingdesignhub.sizing_ui import results\nimport streamlit as st\nresults(st.session_state['seed'],st.session_state['project'],st.session_state['root'])"
    app=AppTest.from_string(code)
    for key,value in {'seed':seed,'project':project,'root':str(ROOT),'coupled_result':native}.items():app.session_state[key]=value
    key='current_design_run_'+project.definition_hash()
    app.run(timeout=90);assert not app.exception
    switches=[]
    for record in (native,seed,native):
        start=time.perf_counter();app.selectbox(key=key).set_value(record['run_id']).run(timeout=90)
        switches.append(time.perf_counter()-start)
        assert not app.exception
        assert any('当前参数、几何与总体报告来源：'+record['run_id']==c.value for c in app.caption)
        table=app.dataframe[0].value
        assert abs(float(table.loc[table['初步技术参数']=='设计起飞重量','值'].iloc[0])-record['summary']['design_mtow_kg'])<.0001
    checks['actual_initial_native_switch']=True
    checks['native_3d_shown']=len(app.get('plotly_chart'))>0
    checks['native_geometry_id_visible']=any('几何与总体参数对应运行 '+native['run_id'] in c.value for c in app.caption)
    timings['result_switch_AppTest_s']=switches
    del app;gc.collect()

    app=AppTest.from_file(str(ROOT/'app.py')).run(timeout=90)
    app.selectbox(key='selected_job').set_value(state['native_job_id']).run(timeout=90)
    start=time.perf_counter();app.button(key='load_job_'+state['native_job_id']).click().run(timeout=240)
    timings['load_completed_job_full_page_s']=time.perf_counter()-start
    assert not app.exception
    checks['history_loads_exact_chain']=app.session_state['sizing_result']==seed and app.session_state['coupled_result']==native
    checks['history_selects_native']=app.selectbox(key=key).value==native['run_id']
    start=time.perf_counter();app.run(timeout=240);timings['warm_full_page_AppTest_s']=time.perf_counter()-start
    assert not app.exception
    del app;gc.collect()

    # A new UI session opens the saved bundle and clears it again, without relying
    # on the original calculation's session keys or local run directories.
    app=AppTest.from_string(f"from wingdesignhub.project_ui import library\nlibrary({str(WORK)!r})").run(timeout=90)
    app.selectbox(key='saved_archive_choice').set_value(index['archive_id']).run()
    start=time.perf_counter();app.button(key='open_saved_design').click().run(timeout=90)
    timings['reopen_AppTest_s']=time.perf_counter()-start
    assert not app.exception
    checks['ui_reopens_selected_native']=app.session_state['opened_archive']['manifest']['current_run_id']==native['run_id']
    checks['ui_reopened_mesh_shown']=len(app.get('plotly_chart'))>0
    checks['ui_reopened_report_available']=any(x.proto.label=='下载存档报告 report.html' for x in app.get('download_button'))
    app.button(key='new_blank_design').click().run(timeout=90)
    checks['ui_clear_preserves_disk_archive']=app.session_state['opened_archive'] is None and (WORK/'local/projects'/f"{index['archive_id']}.wdh").is_file()
    result={'status':'passed' if all(checks.values()) else 'failed','checks':checks,'timings':timings,
            'bundle_bytes':size,'bundle_sha256':bundle_sha,'archive_id':index['archive_id'],
            'native_run_id':native['run_id'],'source_hashes':source_hashes(),
            'scope':'actual frozen native results and AppTest; browser download/visual rendering not measured'}
    atomic(WORK/'validation.json',result)
    print(json.dumps({k:v for k,v in result.items() if k!='source_hashes'},ensure_ascii=False))
    assert all(checks.values()),checks


if __name__=='__main__':main()
