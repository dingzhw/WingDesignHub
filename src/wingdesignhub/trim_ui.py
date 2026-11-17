"""Longitudinal trim in the existing zero-code design workflow."""
from dataclasses import asdict
from pathlib import Path
import json
import streamlit as st
from .aircraft_trim import TrimOptions
from .trim_service import run_aircraft_trim
from .aero_report import strip_figure


def show_files(record,files,key):
    if record['status']=='failed':
        st.error('配平计算失败：'+record.get('error','请查看日志'))
        if 'error.log' in files:
            with st.expander('查看配平错误'):st.code(files['error.log'].decode('utf-8',errors='replace'))
        return
    s=record['summary'];t=s['trim'];state=s['flight_state']
    if t['converged']:st.success('纵向升力面配平完成，实际升力和俯仰矩残差检查通过。')
    else:st.error('配平未通过：'+t['diagnostic'])
    if s['sizing_status']=='constraints_not_met':st.warning('来源总体方案仍有约束未满足。')
    cols=st.columns(3)
    cols[0].metric('配平迎角（°）' if t['converged'] else '最后迎角（°）',f"{t['alpha_deg']:.4f}")
    cols[1].metric('升降舵偏角（°）',f"{t['elevator_deg']:.4f}")
    cols[2].metric('升降舵最小余量（°）',f"{min(t['margins_deg']['elevator_lower'],t['margins_deg']['elevator_upper']):.3f}")
    st.caption(f"CL 残差 {t['residual_cl']:+.3g} · Cm 残差 {t['residual_cm']:+.3g} · 实际计算 {t['evaluation_count']} 个工况点")
    st.write(f"本工况质量 {state['operating_mass_kg']:.2f} kg；重心距机头 {state['cg_geometry_m'][0]:.4f} m。")
    st.caption('质量/重心来源：'+state['source'])
    st.write('本次为机翼、平尾和垂尾的纵向平衡；机身、推进和黏性贡献待接入，总体任务燃油尚未更新。')
    if not t['locally_restoring_pitch']:st.warning('当前升力面模型的局部 Cma 非负，存在纵向静稳定问题，不能据配平通过认定操稳满足。')
    if min(t['margins_deg'].values())<.5:st.warning('迎角或升降舵距设定边界不足 0.5°；这是本工具诊断阈值，需检查余量。')
    st.dataframe([{'状态':'迭代初值','CL':t['initial_coefficients']['CLtot'],'Cm':t['initial_coefficients']['Cmtot'],
                   '诱导阻力系数':t['initial_coefficients']['CDff'],
                   '平尾升力 N':t['initial_surface_loads']['HorizontalTail']['lift_n']},
                  {'状态':'配平解' if t['converged'] else '最后接受点','CL':s['coefficients']['CLtot'],'Cm':s['coefficients']['Cmtot'],
                   '诱导阻力系数':s['coefficients']['CDff'],'平尾升力 N':t['surface_loads']['HorizontalTail']['lift_n']}],hide_index=True)
    if 'strip_loads.json' in files:st.plotly_chart(strip_figure(json.loads(files['strip_loads.json'])),width='stretch',key=key+'_strips')
    for name,label in [('report.html','导出配平报告'),('trim_solution.json','下载配平结果'),('flight_state.json','下载工况台账'),('strip_loads.json','下载配平条带载荷')]:
        if name in files:st.download_button(label,files[name],name,key=key+'_'+name)
    with st.expander('工况台账、迭代记录和适用边界'):
        st.json(state);st.dataframe(t['history'],hide_index=True)
        for line in s['limits']:st.caption(line)
        st.caption('配平运行 '+record['run_id']+'；来源几何 '+record['parent_run_id'])


def render(project,root,geometry_record):
    st.subheader('纵向配平')
    st.caption('一键求迎角与升降舵，使当前工况的升力和俯仰矩平衡。默认使用已配置装载质量，预算余量不自动计入。')
    labels={'takeoff':'起飞装载状态','mission_end':'空中任务结束（入场滑行前）','explicit':'自定义同一工况的质量与重心'}
    mode=st.selectbox('配平质量与燃油状态',list(labels),format_func=labels.get,key='trim_mass_state')
    mass=cg=None;note=''
    if mode=='explicit':
        mass=st.number_input('配平工况质量（kg）',min_value=1.,max_value=10000.,value=1000.,key='trim_mass')
        cg=st.number_input('配平重心 x（m，从机头向后）',min_value=0.,max_value=30.,value=float(geometry_record['summary']['references']['moment_reference_geometry_m'][0]),key='trim_cg')
        note=st.text_input('质量与重心的共同来源或假设',key='trim_source_note')
    v=h=None;amin,amax,emin,emax=-6.,6.,-10.,10.;mesh=2
    with st.expander('配平工况和求解范围（默认即可运行）'):
        custom=st.checkbox('自定义配平速度与高度',key='trim_custom_flow')
        if custom:
            v=st.number_input('配平真空速（m/s）',20.,120.,60.,key='trim_speed')
            h=st.number_input('配平高度（m）',0.,4000.,2000.,key='trim_altitude')
        amin=st.number_input('迎角下限（°）',-6.,5.9,-6.,key='trim_alpha_min')
        amax=st.number_input('迎角上限（°）',-5.9,6.,6.,key='trim_alpha_max')
        emin=st.number_input('升降舵下限（°）',-10.,9.9,-10.,key='trim_elevator_min')
        emax=st.number_input('升降舵上限（°）',-9.9,10.,10.,key='trim_elevator_max')
        mesh=st.selectbox('配平离散',options=[1,2,3],index=1,format_func=lambda x:{1:'粗网格',2:'标准网格',3:'加密网格'}[x],key='trim_mesh')
        st.caption('侧滑、副翼、方向舵及角速度固定为零；升降舵后缘向下为正。安装角继承几何。')
    options=TrimOptions(mass_state=mode,mass_kg=mass,cg_x_m=cg,source_note=note,speed_m_s=v,altitude_m=h,mesh_level=mesh,
        alpha_min_deg=amin,alpha_max_deg=amax,elevator_min_deg=emin,elevator_max_deg=emax,
        initial_alpha_deg=min(max(3.,amin),amax),initial_elevator_deg=min(max(0.,emin),emax))
    if st.button('求解纵向配平',key='run_aircraft_trim'):
        try:
            from .job_ui import submit
            submit(root,'trim',project,geometry_record['run_id'],options)
        except (ValueError,OSError) as exc:st.error(str(exc))
    record=st.session_state.get('aircraft_trim_result')
    if record and record.get('parent_run_id')==geometry_record['run_id']:
        if record['options']!=asdict(options):st.warning('下方配平结果采用上次工况；当前输入已更改，请重新求解。')
        from .service import get_results
        try:
            record=get_results(root,record['run_id']);work=Path(root)/'runs'/record['run_id']
            show_files(record,{n:(work/n).read_bytes() for n in record['artifact_hashes']},'current_trim')
            from .drag_ui import render as render_drag
            render_drag(project,root,record)
        except (ValueError,OSError) as exc:st.error('配平记录检查失败：'+str(exc))
