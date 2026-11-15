"""One-click geometry within the overall design workflow."""
import json
from pathlib import Path
import streamlit as st
from . import geometry_service
from .geometry_report import mesh_figure


def show_files(record,files,key):
    if record['status']=='failed':
        st.error('几何生成失败：'+record.get('error','请查看运行日志'))
        if 'stdout.log' in files:
            with st.expander('查看几何诊断'):st.code(files['stdout.log'].decode('utf-8',errors='replace'))
        return
    s=record.get('summary',{})
    st.success('全机参数化几何已生成，尺寸和参考量检查通过。')
    if s.get('parent_status')=='constraints_not_met':st.warning('对应总体方案仍有约束未满足；本模型用于检查布置和后续修改。')
    if 'surface_mesh.json' in files:
        st.plotly_chart(mesh_figure(json.loads(files['surface_mesh.json'])),width='stretch',key=key+'_3d')
    ref=s['references']
    st.caption(f'参考面积 {ref["area_m2"]:.4f} m² · 全翼展 {ref["span_m"]:.4f} m · MAC {ref["chord_m"]:.4f} m；机头朝 x 减小方向。可拖动旋转、滚轮缩放。')
    st.write('全机外形已接通；气动分析与配平将在后续版本使用这套几何和参考量。')
    for name,label in [('aircraft.vsp3','下载 OpenVSP 全机模型'),('report.html','导出几何报告'),
                       ('aerodynamic_geometry.json','下载气动几何接口')]:
        if name in files:st.download_button(label,files[name],name,key=key+'_'+name)
    with st.expander('几何假设、检查和坐标约定'):
        for line in s.get('limits',[]):st.caption(line)
        st.json(s['references']);st.dataframe(s['checks'],hide_index=True)
        st.caption('几何运行 '+record['run_id']+'；来源总体运行 '+record['parent_run_id'])
        if 'airframe_DegenGeom.csv' in files:
            st.download_button('下载 OpenVSP 分析几何',files['airframe_DegenGeom.csv'],'airframe_DegenGeom.csv',key=key+'_degen')


def render(project,root,sizing_record):
    if not sizing_record.get('summary',{}).get('converged'):return
    st.subheader('全机几何')
    st.caption('沿用本次总体尺寸，按已声明的常规单发模板生成机身、机翼、尾翼、螺旋桨盘和起落架外形。')
    with st.expander('查看外形模板假设'):
        from .aircraft_geometry import LIMITS
        for line in LIMITS:st.caption(line)
    if st.button('生成全机几何',key='generate_aircraft_geometry'):
        try:
            with st.spinner('正在生成 OpenVSP 全机模型并检查写出、重读和参考量……'):
                st.session_state['aircraft_geometry_result']=geometry_service.run_aircraft_geometry(project,root,sizing_record['run_id'])
        except (ValueError,OSError) as exc:st.error(str(exc))
    record=st.session_state.get('aircraft_geometry_result')
    if record and record.get('parent_run_id')==sizing_record['run_id'] and record['definition_sha256']==project.definition_hash():
        from .service import get_results
        try:
            record=get_results(root,record['run_id']);directory=Path(root)/'runs'/record['run_id']
            files={n:(directory/n).read_bytes() for n in record['artifact_hashes']}
            show_files(record,files,'current_geometry')
        except (ValueError,OSError) as exc:st.error('几何记录检查失败：'+str(exc))
