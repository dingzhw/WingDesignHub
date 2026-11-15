"""Requirements first: a short form, visible assumptions and an honest next step."""
from dataclasses import replace
import hashlib
import json
import math
from pathlib import Path
import streamlit as st
from . import design_service
from .requirements import (DesignProject, WeightRequirement, MissionRequirement, DesignAssumptions,
                           WEIGHT_LABELS, MISSION_LABELS, ASSUMPTION_KEYS, build_design_intent)
from .fastga_interface import get_fastga_contract, reference_binding_preview


def render(root):
    st.subheader('新建飞机方案')
    st.write('先定义要完成的任务，再进入总体设计。当前版本可检查、保存需求并复算总体参考任务；自动定尺寸在 V0.1.7 接入。')
    base = DesignProject()
    uploaded = st.file_uploader('打开需求方案（可选）', type='json', key='design_upload')
    key = 'design_default'
    if uploaded is not None:
        try:
            base = DesignProject.from_dict(json.loads(uploaded.getvalue()))
            key = 'design_'+hashlib.sha256(uploaded.getvalue()).hexdigest()[:16]
        except (ValueError, TypeError) as exc:
            st.error(f'需求方案无法读取：{exc}')
            return
    name = st.text_input('方案名称', base.name, key=key+'_name')
    payload = st.number_input('任务载荷合计（含机组，kg）', min_value=0., value=float(base.payload_kg), key=key+'_payload',
                              help='机组、乘员、行李和任务设备的总和；平台不再另加驾驶员重量。')
    mode = st.selectbox('起飞重量模式', list(WEIGHT_LABELS), format_func=WEIGHT_LABELS.get,
                        index=list(WEIGHT_LABELS).index(base.weight.mode), key=key+'_weight')
    mtow = None
    if mode != 'solve':
        mtow = st.number_input(WEIGHT_LABELS[mode]+'（kg）', min_value=.1, value=float(base.weight.value_kg or 1200.), key=key+'_mtow')
    st.caption({'fixed': '保持此起飞重量，后续求翼面积、功率和燃油组合，并检查质量平衡。',
                'upper_bound': '后续由任务求重量，同时检查是否超过此上限。',
                'solve': '起飞重量由后续总体迭代求解，此处不填写初始猜测。'}[mode])
    kind = st.selectbox('任务类型', list(MISSION_LABELS), format_func=MISSION_LABELS.get,
                        index=list(MISSION_LABELS).index(base.mission.kind), key=key+'_mission')
    distance = duration = None
    if kind != 'endurance_only':
        label = '往返转场总航程（km）' if kind == 'transit_loiter' else '主任务航程（km）'
        distance = 1000*st.number_input(label, min_value=.001, value=float((base.mission.range_m or 800000.)/1000), key=key+'_range')
    if kind != 'range_only':
        label = '额外留空时长（h）' if kind == 'transit_loiter' else '主任务最低航时（h）'
        duration = 3600*st.number_input(label, min_value=.001, value=float((base.mission.endurance_s or 14400.)/3600), key=key+'_duration')
    st.caption('航程按无风航迹长度定义；航时包含主任务爬升、巡航、下降，不含地面滑行和储备。往返转场的航程填总距离，额外留空单列。')
    with st.expander('查看并调整设计假设', expanded=True):
        a = base.assumptions
        speed = st.number_input('巡航真空速（km/h）', min_value=.1, value=float(a.cruise_speed_m_s*3.6), key=key+'_speed')/3.6
        altitude = st.number_input('巡航高度（m）', min_value=0., value=float(a.cruise_altitude_m), key=key+'_altitude')
        reserve = 60*st.number_input('额外储备时长（min）', min_value=0., value=float(a.reserve_duration_s/60), key=key+'_reserve')
        values = dict(cruise_speed_m_s=speed, cruise_altitude_m=altitude, reserve_duration_s=reserve, reserve_basis='cruise_fuel_flow')
        for n in ('cruise_speed_m_s', 'cruise_altitude_m', 'reserve_duration_s'):
            if math.isclose(values[n], getattr(a, n), rel_tol=1e-13, abs_tol=1e-10):
                values[n] = getattr(a, n)
        sources = {n: a.sources[n] if values[n] == getattr(a, n) else '用户在新建方案入口修改；随方案确认' for n in ASSUMPTION_KEYS}
        st.caption('首期构型：常规单翼/常规尾翼、金属、单发活塞螺旋桨；标准大气、无风。储备独立估算燃油，默认 45 分钟仅为演示假设。')
        st.dataframe([{'假设': n, '来源': sources[n]} for n in ASSUMPTION_KEYS], hide_index=True)
    if distance is not None and base.mission.range_m is not None and math.isclose(distance, base.mission.range_m, rel_tol=1e-13):
        distance = base.mission.range_m
    if duration is not None and base.mission.endurance_s is not None and math.isclose(duration, base.mission.endurance_s, rel_tol=1e-13):
        duration = base.mission.endurance_s
    p = replace(base, name=name, payload_kg=payload, weight=WeightRequirement(mode, mtow),
                mission=MissionRequirement(kind, distance, duration), assumptions=DesignAssumptions(**values, sources=sources))
    try:
        p.check_schema()
        confirmed = st.checkbox('我已核对上述需求、任务含义和设计假设',
                                value=p.confirmation_sha256 == p.definition_hash(), key='confirm_'+p.definition_hash())
        p = p.confirmed() if confirmed else replace(p, confirmation_sha256=None)
        intent = build_design_intent(p)
        for d in intent['diagnostics']:
            (st.error if d['severity'] == 'error' else st.warning)(d['message'])
        if intent.get('mission_segments'):
            st.dataframe([{'任务段': s['id'], '航程（km）': None if s['distance_m'] is None else s['distance_m']/1000,
                           '要求时长（min）': None if s['duration_s'] is None else s['duration_s']/60,
                           '定义': s['definition']} for s in intent['mission_segments']], hide_index=True)
        st.download_button('保存需求配置', json.dumps(p.to_dict(), ensure_ascii=False, indent=2), 'aircraft-requirements.json', 'application/json')
        if st.button('检查并保存需求', type='primary', key='prepare_design'):
            st.session_state['design_intent_result'] = design_service.prepare_design_project(p, root)
        if 'design_intent_result' in st.session_state:
            r = st.session_state['design_intent_result']
            if r['definition_sha256'] != p.definition_hash() or r['status'] != intent['status']:
                st.info('页面定义已变更；下面的保存记录属于上次需求，请重新检查并保存。')
            elif r['status'] == 'requirements_ready':
                st.success('需求定义已保存，可交给下一阶段总体定尺寸。飞机性能和可行性尚未求解。')
            elif r['status'] == 'needs_confirmation':
                st.warning('已保存待确认草案，请核对后确认。')
            else:
                st.error('需求存在冲突，已保存诊断记录。')
            st.caption('需求记录编号：'+r['run_id'])
            st.download_button('下载需求检查记录', json.dumps(r, ensure_ascii=False, indent=2), 'design-intent-result.json')
            report = Path(root)/'runs'/r['run_id']/'report.md'
            if report.is_file():
                st.download_button('下载需求摘要', report.read_text(encoding='utf-8'), 'design-requirements.md')
        with st.expander('后续总体计算的接口准备'):
            st.json(reference_binding_preview(p))
    except (ValueError, TypeError) as exc:
        st.error(str(exc))
    with st.expander('总体服务验证：公开参考任务'):
        st.write('独立复算 FAST-GA 1.4.0 的双发 Beechcraft 76 教学任务。该按钮保留参考机输入，不使用上方的新方案需求。')
        st.caption('参考条件：711 nmi 航程、158 kn 巡航真空速、10000 ft 高度、45 min 额外储备；2 名乘员另加 2 名驾驶员，行李 60 kg。')
        if st.button('复算 FAST-GA 公开参考任务', key='fastga_reference'):
            with st.spinner('正在复算总体参考任务并核查质量、航程和燃油账目……'):
                st.session_state['design_reference_result'] = design_service.run_fastga_reference(root)
        if 'design_reference_result' in st.session_state:
            r = st.session_state['design_reference_result']
            if r['status'] == 'failed':
                st.error(r.get('error', '参考任务未通过'))
            else:
                if r['status'] == 'executed_with_limits':
                    st.warning('参考任务已复算，经验关系存在适用范围限制，详见诊断。')
                else:
                    st.success('参考任务已复算。')
                s = r['summary']
                st.dataframe([{'参考任务输出': n, 'kg': v} for n, v in s.get('outputs_kg', {}).items()], hide_index=True)
                st.write('质量、航程与储备账目：')
                st.json(s.get('mission_ledger', {}))
                for d in s.get('final_domain_checks', []):
                    if not d['within_range']:
                        st.warning(f"{d['parameter']}={d['value']:.4g}，经验范围 [{d['lower']:.4g}, {d['upper']:.4g}]")
            st.download_button('下载总体参考任务记录', json.dumps(r, ensure_ascii=False, indent=2), 'fastga-reference-result.json')
        st.download_button('下载 FAST-GA 接口约定', json.dumps(get_fastga_contract(), ensure_ascii=False, indent=2), 'fastga-contract.json')
