"""Small periodically refreshed task panel; no solver or archive work on polling."""
import time
from pathlib import Path
import streamlit as st
from . import jobs

LABELS={'queued':'排队中','running':'计算中','cancel_requested':'正在取消','cancelled':'已取消',
        'completed':'计算已结束','failed':'任务失败','interrupted':'已中断','cleanup_failed':'进程清理待检查'}
KINDS={'size':'初步总体','coupled':'推进总体闭环','feedback':'气动总体反馈','compare':'三方案比较',
       'geometry':'全机几何','aero':'全机气动','trim':'纵向配平','drag':'阻力账目','propulsion':'推进复算','fastga_reference':'公开总体算例','tools':'Julia/CCBlade 检查'}
STATE_KEYS={'overall_sizing':'sizing_result','overall_propulsion':'coupled_result','overall_feedback':'aero_feedback_result',
            'overall_comparison':'comparison_result','aircraft_geometry':'aircraft_geometry_result','aircraft_aero':'aircraft_aero_result',
            'aircraft_trim':'aircraft_trim_result','aircraft_drag':'aircraft_drag_result','propulsion_replay':'propulsion_result'}


def submit(root,kind,project=None,parent_run_id=None,options=None):
    try:
        record=jobs.submit_job(root,kind,project,parent_run_id,options)
        st.session_state['pending_selected_job']=record['job_id']
        st.success('已提交'+KINDS[kind]+'；在页面顶部“计算任务与历史”查看进度和结果。可切页，后台继续计算。')
        return record
    except (ValueError,TypeError,OSError) as exc:
        st.error('任务未提交：'+str(exc))


def load_run(root,run_id):
    from .service import get_results
    from .requirements import DesignProject
    from .project_ui import activate
    chain=[];seen=set();rid=run_id
    while rid:
        if rid in seen:raise ValueError('运行依赖循环')
        seen.add(rid);r=get_results(root,rid,verify_native=False);chain.append(r);rid=r.get('parent_run_id')
    activate()
    if not (Path(root)/'runs'/run_id/'input.json').is_file():
        st.session_state['design_reference_result']=chain[0];return
    raw=jobs.read(Path(root)/'runs'/run_id/'input.json')
    if chain[0].get('mode')=='overall_comparison':
        from .design_comparison import ComparisonRequest
        request=ComparisonRequest.from_dict(raw)
        st.session_state['job_comparison_request']=request
        p=request.projects[0]
    elif 'schema_version' in raw:p=DesignProject.from_dict(raw)
    else:
        st.session_state['design_reference_result']=chain[0];return
    st.session_state['workspace_project']=p
    for r in reversed(chain):
        if r.get('mode') in STATE_KEYS:st.session_state[STATE_KEYS[r['mode']]]=r
    if chain[0].get('mode') in ('overall_sizing','overall_feedback','overall_propulsion'):
        st.session_state['current_design_run_'+p.definition_hash()]=run_id


@st.fragment(run_every=2)
def panel(root):
    with st.expander('计算任务与历史',expanded=True):
        try:rows=jobs.list_jobs(root)
        except (OSError,ValueError) as exc:st.error('任务状态检查失败：'+str(exc));return
        if not rows:
            st.caption('提交计算后在这里查看进度、取消或重开结果。任务按顺序运行。');return
        by_id={r['job_id']:r for r in rows}
        if 'pending_selected_job' in st.session_state:
            st.session_state['selected_job']=st.session_state.pop('pending_selected_job')
        if st.session_state.get('selected_job') not in by_id:st.session_state['selected_job']=rows[0]['job_id']
        selected=st.selectbox('选择计算任务',list(by_id),key='selected_job',
            format_func=lambda k:KINDS.get(by_id[k]['kind'],by_id[k]['kind'])+' · '+by_id[k]['name']+' · '+LABELS[by_id[k]['status']]+' · '+k[:8])
        try:record=jobs.get_job(root,selected)
        except (OSError,ValueError) as exc:st.error('任务状态检查失败：'+str(exc));return
        status=record['status']
        elapsed=record.get('elapsed_s',0)
        st.write(f"{LABELS[status]} · 已用 {elapsed/60:.1f} 分钟 · 任务 {selected[:12]}")
        if record.get('heartbeat') and status in jobs.ACTIVE:
            age=time.time()-record['heartbeat']
            st.caption(f'最近心跳 {age:.1f} 秒前；后台进程 {record.get("process_count",0)} 个。')
            if age>5:st.warning('心跳延迟，正在检查工作进程状态；尚未确认完成。')
        events=record['events']
        stages=[e for e in events if e['event']=='run' and e.get('progress')]
        if stages:
            progress=stages[-1]['progress'];stage={'initial':'初步总体','coupled':'推进总体闭环','completed':'已保存'}.get(progress['stage'],progress['stage'])
            st.caption(f"三方案进度：方案 {'ABC'[progress['scheme']]} · {stage}")
        iterations=[e for e in events if e['event']=='iteration_completed']
        if iterations:
            e=iterations[-1];st.caption(f"已完成第 {e['iteration']} 轮；重量 {e['design_mtow_kg']:.2f} kg；稳定轮数 {e['stable_rounds']}/3。")
            st.json(e['residuals'],expanded=False)
        points=[e for e in events if e['event']=='aero_point']
        if points:
            e=max(points,key=lambda x:x['time']);st.caption(f"气动工况 {Path(e['directory']).name} · {e['speed_m_s']:.2f} m/s · {e['altitude_m']:.0f} m · {e['mass_kg']:.1f} kg")
        elif events:st.caption('最近步骤：'+events[-1]['event']+' · '+Path(events[-1].get('directory','')).name)
        if record.get('error'):st.error(record['error'])
        if record.get('engineering_status'):
            from .design_cards import STATUS
            state=record['engineering_status'];st.write('工程结果状态：'+STATUS.get(state,state)+' ('+state+')')
        if record.get('diagnostic_context'):st.json(record['diagnostic_context'],expanded=False)
        with st.expander('任务日志与保留记录'):
            import json
            st.download_button('下载任务状态记录',json.dumps(record,ensure_ascii=False,indent=2),'job.json',key='job_record_'+selected)
            st.caption('关联工程运行：'+', '.join(record.get('related_run_ids',[])))
            path=jobs.job_path(root,selected)/'worker.log'
            if path.is_file():
                with path.open('rb') as log:
                    log.seek(max(0,path.stat().st_size-8192));tail=log.read().decode('utf-8',errors='replace')
                st.code(tail or '工作进程尚未写出日志。')
        if status in jobs.ACTIVE:
            if st.button('取消此任务',key='cancel_job_'+selected):
                jobs.cancel_job(root,selected);st.rerun()
        else:
            if record.get('run_id') and record['kind']=='tools':
                st.json(jobs.read(Path(root)/'runs'/record['run_id']/'result.json'))
            elif record.get('run_id') and st.button('载入此任务结果',key='load_job_'+selected):
                try:load_run(root,record['run_id']);st.rerun()
                except (ValueError,OSError) as exc:st.error('结果检查失败：'+str(exc))
            if st.button('按原输入重新计算',key='retry_job_'+selected):
                try:
                    new=jobs.retry_job(root,selected);st.session_state['pending_selected_job']=new['job_id'];st.rerun()
                except (ValueError,OSError) as exc:st.error(str(exc))
            st.caption('重新计算创建新任务，原始输入、日志和已有结果保留。')
        st.caption('任务进度不等同于工程可行性；原生多工况计算可能需数十分钟，不显示未经估算的完成百分比。')
