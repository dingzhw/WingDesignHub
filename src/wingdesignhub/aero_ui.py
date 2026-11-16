"""Small-angle analysis on the current checked aircraft geometry."""
import json
from pathlib import Path
import streamlit as st
from .aero_service import run_aircraft_aero
from .aircraft_aero import AeroOptions,LIMITS,CONTROL_TEMPLATE
from .aero_report import strip_figure


def show_files(record,files,key):
    if record['status']=='failed':
        st.error('气动分析失败：'+record.get('error','请查看日志'))
        if 'stdout.log' in files:
            with st.expander('查看气动诊断'):st.code(files['stdout.log'].decode('utf-8',errors='replace'))
        return
    s=record['summary'];c=s['coefficients'];f=s['flow']
    st.success('AVL 全机升力面计算完成，工况、参考量和指定载荷分量检查通过。')
    if s['sizing_status']=='constraints_not_met':st.warning('来源总体方案仍有约束未满足。')
    cols=st.columns(3)
    for col,label,keyname in zip(cols,['升力系数 CL','诱导阻力系数 CDi','俯仰力矩系数 Cm'],['CLtot','CDff','Cmtot']):col.metric(label,f'{c[keyname]:.5f}')
    st.caption(f"速度 {f['speed_m_s']:.2f} m/s · 高度 {f['altitude_m']:.0f} m · 迎角 {f['alpha_deg']:.2f}° · 侧滑 {f['beta_deg']:.2f}° · Mach {f['mach']:.4f}")
    st.write('当前为指定迎角和舵偏的无黏计算，尚未配平；总体任务仍采用原概念极曲线。')
    st.caption(f"平飞目标 CL {s['trim']['level_flight_target_cl']:.4f}；当前升力残差 {s['trim']['residual_cl']:+.4f}，Cm 残差 {s['trim']['residual_cm']:+.4f}。工况质量 {f['mass_kg']:.1f} kg。")
    if 'strip_loads.json' in files:st.plotly_chart(strip_figure(json.loads(files['strip_loads.json'])),width='stretch',key=key+'_strips')
    for name,label in [('report.html','导出气动报告'),('strip_loads.json','下载条带载荷'),('trim_interface.json','下载配平接口'),('model.avl','下载 AVL 模型')]:
        if name in files:st.download_button(label,files[name],name,key=key+'_'+name)
    with st.expander('气动适用边界、舵面与检查'):
        for line in s['limits']:st.caption(line)
        st.json({'controls':s['controls'],'references':s['references'],'options':s['options']})
        st.dataframe(s['checks'],hide_index=True);st.caption('气动运行 '+record['run_id']+'；来源几何 '+record['parent_run_id'])


def render(project,root,geometry_record):
    if geometry_record['status']!='geometry_checked_with_limits':return
    st.subheader('全机小迎角气动')
    st.caption('由当前几何联合计算机翼、平尾和垂尾。默认速度沿用总体实际任务速度，高度沿用需求；工况质量默认设计起飞重量。')
    with st.expander('工况与舵偏（默认即可运行）'):
        alpha=st.number_input('迎角（°）',min_value=-6.,max_value=6.,value=3.,step=.5,key='aero_alpha')
        beta=st.number_input('侧滑角（°）',min_value=-5.,max_value=5.,value=0.,step=.5,key='aero_beta')
        deflections={}
        for name,label in [('aileron','副翼'),('elevator','升降舵'),('rudder','方向舵')]:
            deflections[name+'_deg']=st.number_input(label+'偏角（°）',min_value=-10.,max_value=10.,value=0.,step=.5,key='aero_'+name)
        custom=st.checkbox('自定义速度、高度和工况质量',key='aero_custom')
        v=h=mass=None
        if custom:
            v=st.number_input('工况真空速（m/s）',20.,120.,60.,key='aero_speed')
            h=st.number_input('工况高度（m）',0.,4000.,2000.,key='aero_altitude')
            mass=st.number_input('工况质量（kg，须不大于设计起飞重量）',1.,10000.,1000.,key='aero_mass')
        mesh=st.selectbox('气动离散',options=[1,2,3],index=1,format_func=lambda x:{1:'粗网格',2:'标准网格',3:'加密网格'}[x],key='aero_mesh')
        st.caption('本版安装角、扭转均继承已验证几何的 0°。正副翼：右上左下；正升降舵：后缘向下；正方向舵：后缘向右。')
    options=AeroOptions(alpha,beta,**deflections,speed_m_s=v,altitude_m=h,mass_kg=mass,mesh_level=mesh)
    if st.button('运行全机气动',key='run_aircraft_aero'):
        try:
            with st.spinner('正在计算 AVL 气动、条带载荷及配平接口……'):
                st.session_state['aircraft_aero_result']=run_aircraft_aero(project,root,geometry_record['run_id'],options)
        except (ValueError,OSError) as exc:st.error(str(exc))
    record=st.session_state.get('aircraft_aero_result')
    if record and record.get('parent_run_id')==geometry_record['run_id']:
        from dataclasses import asdict
        if record['options']!=asdict(options):st.warning('下方保留上次工况结果；当前输入已更改，请重新运行。')
        from .service import get_results
        try:
            record=get_results(root,record['run_id']);work=Path(root)/'runs'/record['run_id']
            show_files(record,{n:(work/n).read_bytes() for n in record['artifact_hashes']},'current_aero')
        except (ValueError,OSError) as exc:st.error('气动记录检查失败：'+str(exc))
