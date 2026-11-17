"""One-click overall propulsion sizing, with saved native geometry and reports."""
from pathlib import Path
from dataclasses import asdict,replace
import streamlit as st
from .propulsion_feedback import CoupledOptions,LIMITS
from .coupled_service import run_coupled
from .design_cards import STATUS,CHECK_LABELS
from .service import get_results


def show_files(record,files,key):
    s=record.get('summary',{})
    if record['status']=='concept_checked_with_limits':st.success('推进闭环总体已收敛，当前功率、携油及数值检查满足。')
    else:st.warning('推进闭环状态：'+STATUS.get(record['status'],record['status']))
    if record.get('error'):st.error(record['error'])
    for d in s.get('diagnostics',[]):st.error(d)
    if 'geometry' in s:
        cols=st.columns(3)
        cols[0].metric('闭环后设计起飞重量',f"{s['design_mtow_kg']:.1f} kg")
        cols[1].metric('闭环后总可用燃油',f"{s['mission']['block_fuel_kg']:.2f} kg")
        cols[2].metric('闭环后额定轴功率',f"{s['power']['installed_power_w']/1000:.2f} kW")
        st.dataframe([{'指标':r['quantity'],'单位':r['unit'],'原方案':r['before'],'闭环后':r['after'],'变化 %':r['relative_change']*100}
                      for r in s['redesign_comparison']['rows']],hide_index=True)
        st.caption('相同需求重新定尺寸。发动机质量、实际携油、重心与原生外形均已更新；具体发动机及桨产品仍待选型。')
        st.write(f"任务最大需用/可用功率：{s['mission']['max_power_fraction']:.4f}")
        st.dataframe([{'检查项':CHECK_LABELS.get(k,k),'结果':'满足' if v else '未满足'} for k,v in s['checks'].items()],hide_index=True)
        with st.expander('匹配、耗油覆盖和迭代明细'):
            st.dataframe([{'耗油方法':k,'燃油 kg':v} for k,v in s['mission']['block_fuel_by_method_kg'].items()],hide_index=True)
            st.dataframe(s['mission']['segments'],hide_index=True);st.dataframe(s['iterations'],hide_index=True)
            st.json(s.get('propulsion_feedback',{}))
    with st.expander('推进闭环假设与适用边界'):
        st.json(record.get('options',{}))
        for line in LIMITS:st.caption(line)
    for name,label in [('report.html','导出推进闭环报告'),('report.md','下载推进闭环摘要'),
                       ('aircraft_parameters.json','下载闭环后总体参数'),('final_geometry/aircraft.vsp3','下载闭环后全机几何')]:
        if name in files:st.download_button(label,files[name],Path(name).name,key=key+'_'+name)
    if 'final_geometry/surface_mesh.json' in files or 'geometry.svg' in files:
        from .geometry_ui import show_final_geometry
        show_final_geometry(record,files,key+'_geometry')
    st.caption('推进闭环运行：'+record['run_id'])


def render(project,root,parent,key='coupled',archived=None):
    if not parent.get('summary',{}).get('converged'):return
    st.subheader('发动机—螺旋桨与总体闭环')
    st.write('一键匹配发动机与桨，更新耗油、发动机质量和携油，重新生成全机几何及气动。完整计算可能需要数十分钟，原方案保留供比较。')
    options=CoupledOptions()
    with st.expander('闭环推进设置'):
        rpm=st.number_input('恒速桨指定转速 rpm',2200.,2700.,2400.,50.,key=key+'_rpm')
        policy=st.selectbox('耗油图低负荷处理',['base_bsfc','reject'],format_func=lambda x:'基础耗油率估算，单列覆盖' if x=='base_bsfc' else '严格拒绝图外工况',key=key+'_low_load')
        st.caption('通用发动机耗油图替代原平飞耗油模型；爬升富油系数1.15。下降低负荷和地面估算使用方案的基础BSFC。合成桨叶与轴向均匀入流假设随报告保存。')
    options=replace(options,propeller=replace(options.propeller,rpm=rpm),low_load_policy=policy)
    present=(Path(root)/'runs'/parent['run_id']/'result.json').is_file()
    if st.button('运行推进闭环总体计算',key=key+'_run',disabled=not present):
        try:
            from .job_ui import submit
            submit(root,'coupled',project,parent['run_id'],options)
        except (ValueError,OSError) as exc:st.error(str(exc))
    if not present:st.caption('来源运行未在本机计算目录中；可查看存档，新计算请先运行当前总体方案。')
    r=st.session_state.get('coupled_result')
    if r and r.get('definition_sha256')==project.definition_hash():
        st.caption('新任务初值来源：'+parent['run_id']+'；下方历史结果初值来源：'+r['parent_run_id'])
        if r['options']!=asdict(options):st.warning('闭环选项已修改，下方保留上次结果，请重新计算。')
        try:
            r=get_results(root,r['run_id'],verify_native=False);work=Path(root)/'runs'/r['run_id']
            show_files(r,{n:(work/n).read_bytes() for n in ('report.html','report.md','aircraft_parameters.json','final_geometry/aircraft.vsp3') if n in r['artifact_hashes']},key)
            if archived is not None and st.button('保存推进闭环后的方案',key=key+'_save'):
                from .project_archive import build_bundle,save_bundle
                feedback=parent if parent['mode']=='overall_feedback' else None
                with st.spinner('正在核查并保存完整来源、几何和计算证据……'):
                    index=save_bundle(build_bundle(project,root,archived['records'][0],feedback_record=feedback,coupled_record=r),root)
                st.success('已另存推进闭环方案：'+index['archive_id'])
        except (ValueError,OSError) as exc:st.error('推进闭环记录检查失败：'+str(exc))
