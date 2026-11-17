"""Reconnect and page-switch while the actual representative job is running."""
from pathlib import Path
import json
import time
from streamlit.testing.v1 import AppTest
from wingdesignhub.jobs import get_job,submit_job,read,atomic

ROOT=Path(__file__).resolve().parents[1]


def main():
    path=ROOT/'local/v031/native/checkpoint.json';state=read(path)
    active=get_job(ROOT,state['native_job_id']);assert active['status']=='running'
    # This real lightweight native import check must remain queued until the
    # representative run exits; the second submission must reuse its task.
    one=submit_job(ROOT,'tools');two=submit_job(ROOT,'tools')
    assert one['job_id']==two['job_id'] and one['status']=='queued'
    state['tools_job_id']=one['job_id'];atomic(path,state)
    app=AppTest.from_file(str(ROOT/'app.py')).run(timeout=60)
    assert not app.exception
    start=time.perf_counter();app.selectbox(key='selected_job').set_value(active['job_id']).run(timeout=60)
    selection=time.perf_counter()-start
    start=time.perf_counter();app.sidebar.radio[0].set_value('工具设置').run(timeout=60)
    navigation=time.perf_counter()-start
    assert not app.exception and app.selectbox(key='selected_job').value==active['job_id']
    second=AppTest.from_file(str(ROOT/'app.py')).run(timeout=60)
    assert not second.exception
    second.selectbox(key='selected_job').set_value(active['job_id']).run(timeout=60)
    after=get_job(ROOT,active['job_id'])
    checks={'duplicate_returns_same_job':one['job_id']==two['job_id'],
        'second_task_stays_queued':get_job(ROOT,one['job_id'])['status']=='queued',
        'page_switch_keeps_job':app.selectbox(key='selected_job').value==active['job_id'],
        'new_session_recovers_job':second.selectbox(key='selected_job').value==active['job_id'],
        'same_worker_continues':after['status']=='running' and after['runner']==active['runner'],
        'heartbeat_advances':after['heartbeat']>active['heartbeat'],
        'actual_progress_visible':any('气动工况' in c.value or '已完成第' in c.value for c in second.caption)}
    result={'checks':checks,'timings_s':{'select_task_AppTest':selection,'switch_page_AppTest':navigation},
        'native_job_id':active['job_id'],'queued_tools_job_id':one['job_id'],
        'scope':'real queue and AppTest sessions; no browser rendering latency claim'}
    atomic(ROOT/'local/v031/live-ui.json',result);print(json.dumps(result,ensure_ascii=False))
    assert all(checks.values()),checks


if __name__=='__main__':main()
