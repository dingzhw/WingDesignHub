"""Aerodynamic feedback from the main design screen, without command-line steps."""
from pathlib import Path
from dataclasses import asdict,replace
import streamlit as st
from .aero_feedback import FeedbackOptions,LIMITS
from .feedback_service import run_aero_feedback
from .design_cards import STATUS,CHECK_LABELS


def show_files(record,files,key):
    s=record.get('summary',{})
    if record['status']=='concept_checked_with_limits':st.success('气动驱动总体已收敛，当前检查项满足。')
    else:st.warning('气动反馈状态：'+STATUS.get(record['status'],record['status']))
    if record.get('error'):st.error(record['error'])
    for d in s.get('diagnostics',[]):st.error(d)
    if 'geometry' in s:
        cols=st.columns(3)
        cols[0].metric('反馈后设计起飞重量',f"{s['design_mtow_kg']:.1f} kg")
        cols[1].metric('反馈后总可用燃油',f"{s['mission']['block_fuel_kg']:.1f} kg")
        cols[2].metric('反馈后安装轴功率',f"{s['power']['installed_power_w']/1000:.1f} kW")
        st.dataframe([{'指标':r['quantity'],'单位':r['unit'],'原总体':r['legacy'],'反馈后':r['feedback'],'变化 %':100*r['relative_change']}
                      for r in s['redesign_comparison']['rows']],hide_index=True)
        st.caption('上表比较重新定尺寸后的方案；气动模型和速度安排均有变化。原总体记录保留。')
        with st.expander('同条件差异、任务明细与收敛检查'):
            st.json(s.get('aerodynamic_feedback',{}).get('same_condition_comparison',{}))
            st.dataframe(s['mission']['segments'],hide_index=True);st.dataframe(s['iterations'],hide_index=True)
            from .constraint_ui import render as show_constraints
            show_constraints(s)
            st.json(s.get('aerodynamic_feedback',{}).get('direct_checks',[]))
            st.caption('固定外形、装载和发动机的假设敏感性：需用燃油/功率变化；不代表已重新定尺寸。')
            st.dataframe(s.get('aerodynamic_feedback',{}).get('fixed_design_sensitivity',{}).get('rows',[]),hide_index=True)
    with st.expander('本次假设和适用边界'):
        st.json(record.get('options',{}))
        for line in s.get('limits',LIMITS):st.caption(line)
        st.json(record.get('diagnostic_context',s.get('diagnostic_context',{})))
    for name,label in [('report.html','导出气动反馈报告'),('report.md','下载气动反馈摘要'),('aircraft_parameters.json','下载反馈后参数'),('aero_table.json','下载多工况气动表')]:
        if name in files:st.download_button(label,files[name],name,key=key+'_'+name)
    st.caption('气动反馈运行：'+record['run_id'])


def render(project,root,parent):
    if not parent.get('summary',{}).get('converged'):return
    st.subheader('气动驱动的燃油与功率更新')
    st.write('一键生成多工况几何、配平和阻力，沿任务积分更新燃油、功率和重量。首次完整计算可能需要数十分钟；原总体方案保留供比较。')
    o=FeedbackOptions()
    with st.expander('气动任务假设（运行前确认）'):
        execution=st.selectbox('气动计算方式',['reuse','native_audit'],format_func=lambda x:'加速计算' if x=='reuse' else '原生审计（逐次启动）',key='feedback_execution')
        st.caption('自然转捩 Ncrit=9，翼型面元240；常数桨效率、发动机耗油模型沿用本方案。推力沿航迹通过重心，未计滑流或推力线偏置。')
        strut=st.number_input('任务反馈：支柱横流阻力系数',.1,2.,1.2,step=.1,key='feedback_strut')
        cl=st.number_input('低迎角速度安排的 CL 上限',.35,.55,.50,step=.01,key='feedback_schedule_cl')
        st.caption('该 CL 控制爬升/留空速度安排，实际配平仍检查迎角和舵偏；不用于预测失速或最优速度。')
    o=replace(o,execution_mode=execution,schedule_cl_ceiling=cl,drag=replace(o.drag,strut_crossflow_cd=strut))
    if st.button('运行气动反馈总体计算',key='run_aero_feedback'):
        try:
            from .job_ui import submit
            submit(root,'feedback',project,parent['run_id'],o)
        except (ValueError,OSError) as exc:st.error(str(exc))
    r=st.session_state.get('aero_feedback_result')
    if r and r.get('parent_run_id')==parent['run_id']:
        if r['options']!=asdict(o):st.warning('气动任务假设已修改，下方保留上次结果，请重新计算。')
        from .service import get_results
        try:
            r=get_results(root,r['run_id'],verify_native=False);work=Path(root)/'runs'/r['run_id']
            show_files(r,{n:(work/n).read_bytes() for n in ('report.html','report.md','aircraft_parameters.json','aero_table.json') if n in r['artifact_hashes']},'current_feedback')
            from .propulsion_ui import render as propulsion_render
            propulsion_render(project,root,r)
        except (ValueError,OSError) as exc:st.error('反馈记录检查失败：'+str(exc))
