"""One-click fixed-aircraft propulsion replay and portable results."""
from dataclasses import asdict,replace
from pathlib import Path
import streamlit as st
from .propulsion_model import PropulsionOptions,LIMITS
from .propulsion_service import run_propulsion
from .service import get_results


def show_files(record,files,key):
    s=record.get('summary',{})
    if record['status']=='propulsion_checked_with_limits':st.success('推进任务复算完成，当前数值及功率/燃油检查满足。')
    elif record['status']=='constraints_not_met':st.warning('推进需求已算出，当前装机功率、携油或数值检查存在未满足项。')
    else:st.error('推进任务诊断：'+record.get('error',record['status']))
    if s:
        cols=st.columns(3)
        cols[0].metric('新模型需总可用燃油',f"{s['mission']['block_fuel_kg']:.2f} kg")
        cols[1].metric('新模型需安装轴功率',f"{s['required_installed_power_w']/1000:.2f} kW")
        cols[2].metric('原携油余量',f"{s['carried_fuel_margin_kg']:.2f} kg")
        st.caption(f"实际装机仍为 {s['installed_engine_power_w']/1000:.2f} kW，初始装载 {s['initial_mass_kg']:.2f} kg；本次未重新定尺寸。")
        st.dataframe([{'指标':r['quantity'],'单位':r['unit'],'原推进假设':r['legacy'],'新推进模型':r['updated'],'变化 %':100*r['relative_change']} for r in s['comparison']],hide_index=True)
        labels={'engine_power':'原发动机功率','carried_fuel':'原携油与储备','tank_capacity':'油箱容量','propeller_table_accuracy':'桨图直接复算','mission_step_accuracy':'任务积分步长'}
        st.dataframe([{'检查项':labels.get(k,k),'结果':'满足' if v else '未满足'} for k,v in s['checks'].items()],hide_index=True)
        st.caption(f"任务桨效率范围 {s['efficiency_range'][0]:.3f}–{s['efficiency_range'][1]:.3f}；来源气动 V{s['source_aerodynamics_version']}。")
        with st.expander('推进任务和原生验证明细'):
            st.caption('逐步替换：先更换桨效率，再更换发动机可用功率。耗油率模型保持原设定。')
            st.dataframe(s['replacement_stages'],hide_index=True)
            st.dataframe(s['mission']['segments'],hide_index=True);st.json(s['direct_checks']);st.json(s['engine'])
    with st.expander('推进假设与适用边界'):
        st.json(record.get('options',{}))
        for line in LIMITS:st.caption(line)
    for name,label in [('report.html','导出推进复算报告'),('report.md','下载推进复算摘要'),('propeller_map.json','下载原生螺旋桨图谱')]:
        if name in files:st.download_button(label,files[name],name,key=key+'_'+name)
    st.caption('推进运行：'+record['run_id'])


def render(project,root,parent,key='current_propulsion',archived=None):
    if parent.get('status')!='concept_checked_with_limits':return
    st.subheader('发动机与螺旋桨任务复算')
    st.write('保持当前气动、外形、装载和任务速度，用发动机转速/高度模型与CCBlade桨图复算燃油、功率和余量。合成桨叶数据可见，原结果保留。')
    with st.expander('推进设置（运行前核对）'):
        rpm=st.number_input('螺旋桨与发动机转速 rpm',2200.,2700.,2400.,50.,key=key+'_rpm')
        blades=st.selectbox('合成螺旋桨叶数',[3,2,4],key=key+'_blades')
        st.caption('直径继承飞机外形；默认根/尖弦长0.18/0.08 m，75%半径基准角20°，理想恒速变距。耗油模型沿用原方案，未选定实际发动机或螺旋桨产品。')
    options=replace(PropulsionOptions(),rpm=rpm,blades=blades)
    present=(Path(root)/'runs'/parent['run_id']/'result.json').is_file()
    if st.button('运行推进模型任务复算',key=key+'_run',disabled=not present):
        try:
            with st.spinner('正在生成有界桨图、匹配推力并积分任务……'):
                st.session_state['propulsion_result']=run_propulsion(project,root,parent['run_id'],options)
        except (ValueError,OSError) as exc:st.error(str(exc))
    if not present:st.caption('该历史源运行不在本机runs目录中；可查看和导出存档结果，重新计算需先在本机生成气动任务。')
    result=st.session_state.get('propulsion_result')
    if result and result.get('parent_run_id')==parent['run_id']:
        if result['options']!=asdict(options):st.warning('推进设置已修改，下方保留上次结果，请重新计算。')
        try:
            result=get_results(root,result['run_id']);work=Path(root)/'runs'/result['run_id']
            show_files(result,{n:(work/n).read_bytes() for n in ('report.html','report.md','propeller_map.json') if n in result['artifact_hashes']},key)
            if archived is not None:
                from .project_archive import build_bundle,save_bundle
                if st.button('保存推进复算后的方案',key=key+'_save'):
                    with st.spinner('正在核查并保存完整来源与结果……'):
                        data=build_bundle(project,root,archived['records'][0],feedback_record=parent,propulsion_record=result)
                        index=save_bundle(data,root)
                    st.success('已另存推进方案：'+index['archive_id'])
        except (ValueError,OSError) as exc:st.error('推进记录检查失败：'+str(exc))
