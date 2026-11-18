"""Three choices from the current requirements, no solver-by-solver workflow."""
from dataclasses import replace
from pathlib import Path
import json
import streamlit as st
from .design_comparison import ComparisonRequest,PURPOSES,AXES,MODELS
from .design_cards import METRICS
from . import comparison_service


from .design_comparison import variants


def show_results(r,request,root):
    if r['definition_sha256']!=request.definition_hash() or any(p.confirmation_sha256!=p.definition_hash() for p in request.projects):
        st.info('三方案定义或确认已变更，下面不再显示旧比较；请重新确认后计算。');return
    if r['status'] in ('failed','needs_confirmation'):
        st.error(r.get('error','比较未完成'));return
    s=r['summary'];st.write(s['interpretation'])
    st.caption(s.get('analysis_label',MODELS['initial']))
    if r['status']=='comparison_incomplete':st.warning('部分方案未满足约束或未完成计算；保留诊断，仅比较有效结果。')
    else:st.success('三个方案已计算并生成方案卡；当前结论限于已检查的概念模型。')
    for col,card in zip(st.columns(3),s['cards']):
        with col:
            st.markdown('**'+card['name']+'**');st.caption(card['status_label'])
            if not card['eligible']:st.warning('未进入有效方案比较')
            for k in ('mtow_kg','area_m2','power_kw','block_fuel_kg'):
                label,unit=METRICS[k];value=card['metrics'][k]
                st.metric(label, '—' if value is None else f'{value:.2f} {unit}')
            for message in card['diagnostics']:st.write(message)
            enhanced=card.get('enhanced',{})
            if enhanced:
                st.caption(f"任务最大需用/可用功率 {enhanced['max_power_fraction']:.4f}；最小轴扭矩余量 {enhanced['minimum_torque_margin_nm']:.2f} N·m")
            states=card.get('constraint_states')
            if states:
                failed=[r['label'] for r in states if r['status']=='exceeded']
                if failed:st.error('超限：'+'、'.join(failed))
                with st.expander('约束状态与适用条件'):
                    from .constraint_ui import render as show_constraints
                    show_constraints({'constraint_states':states})
            elif any(not v for v in card['checks'].values()):
                from .sizing_ui import CHECKS
                st.error('历史未满足项：'+'、'.join(CHECKS.get(k,k) for k,v in card['checks'].items() if not v))
    st.dataframe([{'方案':c['name'],**{f'{label}（{unit}）':c['metrics'][k] for k,(label,unit) in METRICS.items()}} for c in s['cards']],hide_index=True)
    st.caption('相对 A 的变化；空白表示该方案或基准没有可用于比较的有效结果。')
    st.dataframe([{'方案':s['cards'][d['scheme']]['name'],**{METRICS[k][0]+'变化%':None if v['relative'] is None else 100*v['relative'] for k,v in d['values'].items()}} for d in s['deltas']],hide_index=True)
    with st.expander('查看差异、余量和运行证据'):
        st.dataframe(s['differences'],hide_index=True)
        for c in s['cards']:
            st.write(c['name']);st.json({'余量':c['margins'],'控制约束':c['controls'],'迭代残差':c['final_residuals'],
                                       '运行编号':c['run_id'],'模型版本':c['solver_versions'],'推进与耗油':c.get('enhanced',{})})
    work=Path(root)/'runs'/r['run_id']
    for i in range(1,4):
        for suffix,label in [('card.html','方案卡（可打印）'),('input.json','需求配置')]:
            f=work/f'plan-{i}-{suffix}'
            if f.is_file():st.download_button(f'下载 {"ABC"[i-1]} {label}',f.read_bytes(),f.name,key=f'comparison-download-{i}-{suffix}')
    for filename,label in [('scheme-cards.zip','一键下载三个方案卡与配置'),('report.md','下载比较摘要'),('comparison.json','下载完整比较结果')]:
        if (work/filename).is_file():st.download_button(label,(work/filename).read_bytes(),filename)


def render(base,root):
    with st.expander('三方案比较与需求变化',expanded=False):
        st.write('以上方需求为起点，一次选择一个变化参数，形成 A/B/C 三个方案。其他条件保持一致。')
        upload=st.file_uploader('打开三方案配置（可选）',type='json',key='comparison-upload-'+str(st.session_state.get('workspace_revision',0)))
        try:
            opened=st.session_state.get('opened_archive')
            use_opened=False
            if opened and isinstance(opened['project'],ComparisonRequest):
                use_opened=st.checkbox('沿用存档中的三方案参数（取消后按上方需求重新调整）',value=True,key='archive_compare_'+opened['bundle_sha256'])
            if upload:
                request=ComparisonRequest.from_dict(json.loads(upload.getvalue()))
                st.info('当前比较采用导入的三个完整方案，不使用上方单方案表单。')
            elif use_opened:
                request=opened['project']
                st.info('当前比较使用已打开的三方案完整需求；取消上方选项即可在界面调整比较参数。')
            elif st.session_state.get('job_comparison_request') and st.checkbox('查看已载入的三方案任务',value=True,key='use_job_comparison'):
                request=st.session_state['job_comparison_request']
            else:
                choices=['sizing.aspect_ratio','assumptions.cruise_speed_m_s','payload_kg']
                if base.mission.range_m is not None:choices.append('mission.range_m')
                if base.mission.endurance_s is not None:choices.append('mission.endurance_s')
                axis=st.selectbox('比较参数',choices,format_func=AXES.get,key='comparison-axis')
                value=getattr(getattr(base,axis.split('.')[0]),axis.split('.')[1]) if '.' in axis else getattr(base,axis)
                divisor,unit={'assumptions.cruise_speed_m_s':(1/3.6,'km/h'),'mission.range_m':(1000,'km'),
                              'mission.endurance_s':(3600,'h'),'payload_kg':(1,'kg')}.get(axis,(1,''))
                values=[]
                for i,col in enumerate(st.columns(3)):
                    with col:values.append(divisor*st.number_input(f'方案 {"ABC"[i]} {AXES[axis]}（{unit}）',value=float(value/divisor*(1+.1*i)),
                        key=f'comparison-value-{base.definition_hash()}-{axis}-{i}'))
                request=variants(base,axis,values)
                model=st.selectbox('三方案计算方法',['coupled','initial'],format_func=MODELS.get,key='comparison-model')
                if model=='coupled':
                    from dataclasses import asdict
                    from .propulsion_feedback import CoupledOptions
                    options=asdict(CoupledOptions())
                    st.caption('三个方案依次运行完整闭环，计算时间较长；每个已完成方案单独落盘。各方案共用以下设置。')
                    with st.expander('三方案共同分析设置'):
                        options['propeller']['rpm']=st.number_input('螺旋桨转速 rpm',2200.,2700.,2400.,50.,key='comparison-rpm')
                        options['low_load_policy']=st.selectbox('低负荷耗油处理',['base_bsfc','reject'],format_func=lambda x:'基础耗油率估算并单列油量' if x=='base_bsfc' else '超出原生耗油图即停止',key='comparison-low-load')
                        st.json(options)
                    request=replace(request,schema_version=2,analysis_model=model,analysis_options=options)
            st.caption('当前分析方法：'+MODELS[request.analysis_model])
            st.caption(PURPOSES[request.purpose]+'；A 为差分基准。没有自动“综合最优”排名。')
            st.dataframe(request.differences(),hide_index=True)
            confirmed=st.checkbox('我已核对三个方案的需求、变化项和共同假设',
                value=all(p.confirmation_sha256==p.definition_hash() for p in request.projects),key='comparison-confirm-'+request.definition_hash())
            request=replace(request,projects=tuple(p.confirmed() if confirmed else replace(p,confirmation_sha256=None) for p in request.projects))
            st.download_button('保存三方案配置',json.dumps(request.to_dict(),ensure_ascii=False,indent=2),'three-designs.json')
            if st.button('一键计算并比较三个方案',key='run-comparison',disabled=not confirmed):
                from .job_ui import submit
                submit(root,'compare',request)
            if 'comparison_result' in st.session_state:show_results(st.session_state['comparison_result'],request,root)
            from .project_ui import save_controls
            save_controls(request,root,st.session_state.get('comparison_result'),key='comparison')
        except (ValueError,TypeError,KeyError) as exc:st.error(str(exc))
    with st.expander('模型精度检查：公开同条件巡航点'):
        st.caption('V0.3.3：Archer II 构型/重量/装载来源与通用发动机图核查；完整实机条件不足的项目单列。')
        if st.button('核查 Archer II 构型与重量、耗油',key='aircraft-reference'):
            from .aircraft_reference import run_aircraft_reference
            with st.spinner('正在复算固定公开基准，约需数十秒…'):
                st.session_state['aircraft_reference']=run_aircraft_reference(root)
        if 'aircraft_reference' in st.session_state:
            reference=st.session_state['aircraft_reference']
            if reference['status']=='failed':st.error(reference.get('error','基准计算失败'))
            else:
                s=reference['summary'];m=s['mass']
                st.write('固定公开外廓与额定功率下，模板空重相对手册标准空重偏差：'+f"{m['standard_empty_relative_error']:.1%}")
                st.caption('尾翼、设备和空重口径仍有差别；该偏差用于查找原因，未计为实机验证通过。')
                st.dataframe([{'功率比例':r['power_fraction'],'数据角色':r['role'],'手册 gal/h':r['fuel_us_gal_h'],
                    '通用图2400rpm gal/h':r['generic_map_rpm_sensitivity'][1]['fuel_us_gal_h']} for r in s['fuel_rows']],hide_index=True)
                for line in s['limits']:st.caption(line)
                st.download_button('下载公开基准、分项输入与偏差记录',json.dumps(reference,ensure_ascii=False,indent=2),'aircraft-reference.json')
        st.caption('V0.2.0：65% 点已改为校准数据，55%/75% 仅为同源留出；外部资料条件差异单列。')
        if st.button('核查耗油模型与留出数据',key='fuel-evidence'):
            from .fuel_validation import run_fuel_validation
            st.session_state['fuel_evidence']=run_fuel_validation(root)
        if 'fuel_evidence' in st.session_state:
            f=st.session_state['fuel_evidence']['summary']
            st.dataframe([{'数据角色':r['role'],'功率比例':r['power_fraction'],'原耗油 gal/h':r['original_gal_h'],
                          '参考耗油 gal/h':r['predicted_gal_h'],'公开值 gal/h':r['fuel_us_gal_h'],'偏差%':r['relative_error']*100} for r in f['rows']],hide_index=True)
            for line in f['limits']:st.warning(line)
            st.write(f['external_reference']['reason'])
            st.download_button('下载耗油校准和验证记录',json.dumps(st.session_state['fuel_evidence'],ensure_ascii=False,indent=2),'fuel-validation.json')
        st.caption('Piper 原厂 VB-760 手册巡航点；核对重量、压力高度、实际温度、功率和混合比，保留偏差。')
        if st.button('计算公开巡航点对照',key='public-cruise'):
            from .reference_cruise import run_public_cruise
            st.session_state['public_cruise_result']=run_public_cruise(root)
        if 'public_cruise_result' in st.session_state:
            r=st.session_state['public_cruise_result'];s=r['summary']
            (st.warning if r['status']=='model_discrepancy' else st.info)('同条件对照完成；这是模型偏差检查，尚非整机精度验收。')
            st.dataframe([{'输出':'真空速 mph','手册':127.,'模型':s['predicted']['speed_mph'],'偏差%':100*s['relative_errors']['speed']},
                          {'输出':'耗油 US gal/h','手册':7.6,'模型':s['predicted']['fuel_us_gal_h'],'偏差%':100*s['relative_errors']['fuel']}],hide_index=True)
            for line in s['limits']:st.caption(line)
            st.markdown('[查看原厂手册公开镜像]('+s['reference']['url']+')')
            st.download_button('下载公开对照记录',json.dumps(r,ensure_ascii=False,indent=2),'public-cruise-check.json')
