"""Novice-facing mass relief and stability screen, sharing the engineering API."""
import json
import pandas as pd
import streamlit as st
from .flight_loads import FlightLoadCase


def render(root):
    from .flight_service import run_flight_structure
    st.subheader('气动载荷、质量卸载与局部屈曲')
    st.write('选择飞行条件 → 自动求迎角和条带升力 → 扣除翼内质量的竖向重力/惯性 → 静力与板屈曲筛查。')
    st.caption('本页为孤立 NACA0012 矩形机翼。整机质量已包含两侧结构、燃油和设备；质量载荷不再额外加一次重力。')
    base=FlightLoadCase();upload=st.file_uploader('打开载荷方案（可选）',type='json')
    if upload:
        try:base=FlightLoadCase.from_dict(json.loads(upload.getvalue()))
        except (ValueError,TypeError) as exc:st.error(f'方案无法读取：{exc}');st.stop()
    with st.form('flight_loads'):
        a,b,c=st.columns(3)
        mass=a.number_input('整机质量（kg）',min_value=100.,max_value=5000.,value=float(base.aircraft_mass_kg),step=50.)
        factor=b.number_input('法向载荷因数 n_z',min_value=-2.,max_value=4.,value=float(base.load_factor),step=.1,help='平飞取 1；定义 n_z=1+a_z/g。程序会检查目标升力是否超出当前线性气动范围。')
        speed=c.number_input('真空速（m/s）',min_value=20.,max_value=100.,value=float(base.speed_m_s),step=5.)
        a,b,c=st.columns(3)
        fuel=a.number_input('单侧机翼燃油质量（kg）',min_value=0.,value=float(base.fuel_half_mass_kg))
        ultimate=b.number_input('极限载荷系数',min_value=1.,max_value=2.,value=float(base.ultimate_factor),step=.1)
        density=c.number_input('空气密度（kg/m³）',min_value=.5,max_value=1.4,value=float(base.density_kg_m3),format='%.3f')
        with st.expander('几何、板厚和材料限值'):
            a,b=st.columns(2)
            span=a.number_input('半翼展（m）',min_value=2.,max_value=12.,value=float(base.mesh.half_span_m))
            chord=b.number_input('弦长（m）',min_value=.5,max_value=3.,value=float(base.mesh.chord_m))
            skin=a.number_input('蒙皮厚度（mm）',min_value=.1,max_value=30.,value=base.mesh.skin_thickness_m*1000)
            spar=b.number_input('梁腹板厚度（mm）',min_value=.1,max_value=30.,value=base.mesh.spar_thickness_m*1000)
            allowable=a.number_input('规定应力限值（MPa）',min_value=.1,value=base.stress_allowable_pa/1e6)
            edge=b.number_input('最大网格边长（m）',min_value=.01,max_value=1.,value=float(base.mesh.max_edge_m),step=.01)
            st.caption(f'最小边长 {base.mesh.min_edge_m:g} m；前/后梁 {base.mesh.front_spar_fraction:.0%}/{base.mesh.rear_spar_fraction:.0%} 弦长，内翼肋 {base.mesh.rib_count} 道。材料及其余网格参数随配置保留。')
        with st.expander('燃油位置与集中质量'):
            a,b,c=st.columns(3)
            start=a.number_input('燃油展向起点（半翼展比例）',min_value=0.,max_value=1.,value=base.fuel_start_fraction)
            end=b.number_input('燃油展向终点（半翼展比例）',min_value=0.,max_value=1.,value=base.fuel_end_fraction)
            fuel_x=c.number_input('燃油弦向位置（弦长比例）',min_value=0.,max_value=1.,value=base.fuel_x_fraction)
            st.caption('以下为单侧机翼设备。位置采用 x 向后、y 向翼尖、z 向上，单位 m；可增加或删除行。')
            records=[{'名称':p['name'],'质量 kg':p['mass_kg'],'x m':p['position_m'][0],'y m':p['position_m'][1],'z m':p['position_m'][2]} for p in base.point_masses]
            table=st.data_editor(pd.DataFrame(records,columns=['名称','质量 kg','x m','y m','z m']),num_rows='dynamic',hide_index=True)
        clicked=st.form_submit_button('一键计算载荷与结构',type='primary')
    data=base.to_dict();data.update(aircraft_mass_kg=mass,load_factor=factor,speed_m_s=speed,fuel_half_mass_kg=fuel,
        ultimate_factor=ultimate,density_kg_m3=density,stress_allowable_pa=allowable*1e6,
        fuel_start_fraction=start,fuel_end_fraction=end,fuel_x_fraction=fuel_x,
        point_masses=[{'name':p['名称'],'mass_kg':p['质量 kg'],'position_m':[p['x m'],p['y m'],p['z m']]} for p in table.to_dict('records')])
    data['mesh'].update(half_span_m=span,chord_m=chord,skin_thickness_m=skin/1000,spar_thickness_m=spar/1000,max_edge_m=edge)
    st.download_button('保存载荷方案',json.dumps(data,ensure_ascii=False,indent=2),'flight-loads.json')
    if clicked:
        try:
            with st.spinner('正在计算升力、生成网格并校核结构……'):st.session_state['flight_result']=run_flight_structure(data,root)
        except (ValueError,TypeError) as exc:st.error(str(exc))
    if 'flight_result' not in st.session_state:return
    r=st.session_state['flight_result'];st.caption(f"运行编号：{r['run_id']}。修改参数后需重新运行。")
    if r['status']=='failed':st.error(r['error'])
    else:
        s=r['summary']
        if r['status']=='executed_with_limits':st.warning('计算已完成：'+'；'.join(s['screening_issues']))
        else:st.success('本次有限范围的工程筛查通过。')
        a,b,c=st.columns(3)
        a.metric('求解迎角',f"{s['aero']['alpha_deg']:.3f}°")
        b.metric('平均翼尖竖向位移',f"{s['tip_mean_z_m']*1000:.3f} mm")
        c.metric('最大屈曲相互作用指标',f"{s['buckling']['max_interaction_utilization']:.3f}",help='大于 1 表示该工程筛查未满足，实际结构仍需专业复核。')
        st.write(f"单侧结构材料量 {s['structure_mass']['mass_kg']:.2f} kg；规定限值下屈服裕度 {s['yield_margin']:.3f}。")
        st.dataframe(pd.DataFrame([{'分项':p['name'],'限制载荷 Fz N':p['limit_force_n'][2],'限制载荷 Mx N·m':p['limit_moment_nm'][0]} for p in s['load_components']]),hide_index=True)
        st.caption('表中为乘极限系数之前的分项。实际求解载荷见载荷记录。')
        st.dataframe(pd.DataFrame([{'面板':p['panel'],'肋间段':p['bay'],'相互作用指标':p['interaction_utilization'],'筛查通过':p['screen_passed']} for p in s['buckling']['panels']]),hide_index=True)
        for line in s['limits']:st.caption(line)
        for label,name in (('下载载荷台账','loads.json'),('下载屈曲筛查','buckling.json'),('下载求解输入','solve/wing.inp'),('下载三维结果','solve/wing.frd')):
            st.download_button(label,(root/'runs'/r['run_id']/name).read_bytes(),name.split('/')[-1])
    with st.expander('完整计算记录'):st.json(r)
    st.download_button('下载计算记录',json.dumps(r,ensure_ascii=False,indent=2),'flight-result.json')
