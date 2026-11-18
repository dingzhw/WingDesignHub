"""Optional concept assumptions and readable, provenance-aware overall results."""
from dataclasses import replace
from pathlib import Path
import json
import streamlit as st
from .design_cards import CHECK_LABELS as CHECKS


from .sizing_config import FIELD_LABELS as FIELDS


def assumptions(base, key):
    from .sizing_config import LIMITS
    with st.expander('初始构型与计算假设（通常可保留默认值）'):
        from .fuel_model import FUEL_MODELS, calibrated_bsfc
        st.write('常规低翼、常规尾翼、金属、固定前三点起落架、机头单发。默认系数为概念假设，确认后参与本次定尺寸。')
        values={}
        for n,label in FIELDS.items():
            lo,hi=LIMITS[n];value=float(getattr(base,n))
            bounds={'min_value':float(lo),'max_value':float(hi)} if lo<=value<=hi else {}
            if not bounds:st.error(f'{label} 当前为 {value}，允许范围 [{lo}, {hi}]，请修正。')
            values[n]=st.number_input(label,value=value,step=.001 if hi<1 else .1,
                                     help=f'当前方法范围 [{lo}, {hi}]',key=key+'_'+n,**bounds)
        values['fuel_model']=st.selectbox('耗油计算方式',list(FUEL_MODELS),format_func=FUEL_MODELS.get,
                index=list(FUEL_MODELS).index(base.fuel_model),key=key+'_fuel_model')
        if values['fuel_model']=='piper_economy_reference':
            st.info(f'经济平飞参考耗油率 {calibrated_bsfc():.4f} kg/kWh，使用范围为 55%–75% 额定轴功率。起飞/爬升及范围外仍用基础值；报告逐段列出。')
            st.caption('65% 手册点用于校准，55%/75% 为同源留出检查；独立试验及跨机型精度待验证。')
        else:st.caption('默认 0.30 是混合比未细分的概念假设；在 Piper 经济巡航点高估约 26.5%。可按任务选择经济参考，或填入有依据的基础值。')
        values['seats'] = st.number_input('总座位数（仅用于设备重量）', min_value=2, max_value=6,
                                           value=base.seats, step=1, key=key+'_seats')
        from .layout_ui import editor
        values['layout']=editor(base.layout,key)
        if any(v != getattr(base, n) for n, v in values.items()):
            values['source'] = '用户调整的概念假设；随方案确认'
        result = replace(base, **values)
        st.caption(result.source)
        st.caption('模板固定参数：梢根比 0.6、厚弦比 0.12、四分之一弦后掠 0°；尾容量系数平尾 0.7/垂尾 0.04，尾臂 0.45 倍机身长；极限过载 5.7。机身宽 1.2 m、高 1.35 m；机翼站位默认0.39倍机长，启用布置后按配置。')
        st.caption('任务采用标准大气、无风、密度比例可用功率；下降率 2 m/s、爬升速度 1.3 倍净构型失速速度。滑行各 300 s/10% 功率，起飞地面段 30 s/90% 功率；下降至少 5% 功率。油箱与功率各留 2% 定尺寸余量。')
        st.caption('重心按本次布局台账计算，重心包线后续校核。' if result.layout is not None else '旧版概念站位：机体0.44、动力0.12、系统/座椅0.40倍机长，载荷和燃油位于翼四分之一弦；不是允许重心包线。')
    return result


def results(record, project, root):
    seed_record=record
    if record['definition_sha256'] != project.definition_hash() or project.confirmation_sha256 != project.definition_hash():
        st.info('需求或确认状态已变更；上次总体结果不适用于当前定义，请确认后重新运行。')
        return
    candidates={r['run_id']:r for r in [record,st.session_state.get('aero_feedback_result'),st.session_state.get('coupled_result')]
                if r and r.get('definition_sha256')==project.definition_hash()}
    key='current_design_run_'+project.definition_hash()
    if st.session_state.get(key) not in candidates:st.session_state[key]=record['run_id']
    labels={'overall_sizing':'初步总体','overall_feedback':'气动反馈总体','overall_propulsion':'推进闭环总体'}
    selected=st.selectbox('当前总体结果',list(candidates),key=key,
        format_func=lambda rid:labels[candidates[rid]['mode']]+' · '+rid[:12]+' · '+candidates[rid]['status'])
    record=candidates[selected]
    st.caption('当前参数、几何与总体报告来源：'+selected)
    status = record['status']; s = record.get('summary', {})
    if status == 'concept_checked_with_limits':
        st.warning('总体迭代已收敛，当前模型检查项满足；具体适用边界见本次运行记录。起降距离和结构重量闭环仍待接入。')
    elif status == 'constraints_not_met':
        st.error('迭代已收敛，但存在未满足的约束，请查看余量与检查表。')
    elif status == 'not_converged':
        st.error('总体迭代未收敛，以下仅为最后一次试算。')
    elif status == 'failed':
        st.error(record.get('error', '总体计算失败，请查看运行记录。'))
    else:
        st.error('当前方案未进入有效计算：'+status)
    for d in s.get('diagnostics', []):
        st.write(d if isinstance(d, str) else d.get('message', d))
    if 'geometry' in s:
        g=s['geometry']; ms=s['mission']
        if 'fuel_model' in ms:
            st.write('耗油计算：'+ms['fuel_model']['label'])
            st.caption(f"经济参考燃油覆盖 {ms['economy_reference_fuel_fraction']:.1%}；各任务段和基础耗油率部分在报告中单列。")
        st.dataframe([
            {'初步技术参数': n, '值': round(v, 4), '单位': u} for n,v,u in [
                ('设计起飞重量',s['design_mtow_kg'],'kg'),('计算装载质量',s['required_loaded_mass_kg'],'kg'),
                ('质量预算余量',s['mass_budget_margin_kg'],'kg'),('空重（含不可用燃油）',s['weights']['owe_kg'],'kg'),
                ('翼面积',g['wing_area_m2'],'m²'),('翼展',g['wing_span_m'],'m'),
                ('安装轴功率',s['power']['installed_power_w']/1000,'kW'),('总可用燃油（含储备和滑行）',ms['block_fuel_kg'],'kg'),
                ('其中储备油',ms['reserve_fuel_kg'],'kg'),('主任务空中时长',ms['main_duration_s']/3600,'h'),
                ('转场航程（留空另列）',ms['route_distance_m']/1000,'km'),('估算起飞重心站位',s['cg']['cg_x_m'],'m')]], hide_index=True)
        if s['upper_bound_margin_kg'] is not None:
            st.write(f"起飞重量上限余量：{s['upper_bound_margin_kg']:.2f} kg")
        st.dataframe([{'检查项': CHECKS.get(k,k), '结果': '满足' if v else '未满足'} for k,v in s['checks'].items()], hide_index=True)
        with st.expander('查看构型、迭代和质量/任务明细'):
            work=Path(root)/'runs'/record['run_id']
            if (work/'geometry.svg').is_file(): st.image((work/'geometry.svg').read_text(encoding='utf-8'))
            st.write('几何由本方案需求生成，图中机头朝左；当前为参数布局。')
            st.dataframe(s['iterations'], hide_index=True)
            st.dataframe(s['cg']['rows'], hide_index=True)
            st.dataframe(ms['segments'], hide_index=True)
            for name,label in [('aircraft_parameters.json','下载初步参数'),('report.md','下载总体摘要'),('geometry.svg','下载构型图')]:
                if (work/name).is_file(): st.download_button(label,(work/name).read_bytes(),name)
        for line in s['limits']: st.caption(line)
    st.caption('总体运行编号：'+record['run_id'])
    st.download_button('下载总体运行记录',json.dumps(record,ensure_ascii=False,indent=2),'overall-result.json')
    work=Path(root)/'runs'/record['run_id']
    if (work/'report.html').is_file():st.download_button('导出当前总体报告',(work/'report.html').read_bytes(),'current-design-report.html')
    if record['mode'] in ('overall_feedback','overall_propulsion'):
        from .geometry_ui import show_final_geometry
        show_final_geometry(record,{n:(work/n).read_bytes() for n in ('final_geometry/surface_mesh.json','final_geometry/geometry_contract.json','final_geometry/aircraft.vsp3','geometry.svg') if (work/n).is_file()},'selected_final_geometry')
    from .coupled_ui import render as render_coupled
    seed=st.session_state.get('aero_feedback_result')
    if not seed or seed.get('parent_run_id')!=seed_record['run_id'] or not seed.get('summary',{}).get('converged'):seed=seed_record
    render_coupled(project,root,seed)
    from .feedback_ui import render as render_feedback
    render_feedback(project,root,seed_record)
    from .geometry_ui import render
    if record['mode']=='overall_sizing':render(project,root,record)
