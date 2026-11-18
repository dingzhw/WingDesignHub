"""Four-state contract shared by UI/cards/reports; keep numerical evidence separate."""
LABELS={'not_applicable':'不适用','not_calculated':'未计算','met':'满足','exceeded':'超限'}
NUMERICAL={'aero_table_accuracy','mission_step_accuracy','propeller_table_accuracy','shaft_torque_balance'}
EXTRA={'takeoff_distance':'越障起飞距离','landing_distance':'越障着陆距离',
       'climb_sea_level':'海平面爬升需用功率','climb_cruise_altitude':'巡航高度爬升需用功率',
       'loading_cg':'规定装载CG研究范围','longitudinal_static':'纵向静稳定一级筛查',
       'longitudinal_control':'纵向配平角度与舵量（含Cm扰动）',
       'lateral_control':'横航向操稳包线','structural_feedback':'结构定尺寸质量反馈'}


def row(key,label,status,reason='',value=None,limit=None,margin=None,unit='',kind='design'):
    if status not in LABELS:raise ValueError('约束状态无效')
    return dict(id=key,label=label,status=status,reason=reason,value=value,limit=limit,margin=margin,unit=unit,kind=kind)


def states(summary,p):
    from .design_cards import CHECK_LABELS
    rows=[]
    for k,v in summary.get('checks',{}).items():
        absent=(k=='mtow_upper_bound' and p.weight.mode!='upper_bound') or (k=='range' and p.mission.range_m is None) or (k=='endurance' and p.mission.endurance_s is None)
        status='not_applicable' if absent else ('not_calculated' if not summary.get('converged') else ('met' if v is True else 'exceeded'))
        rows.append(row(k,CHECK_LABELS.get(k,k),status,'当前任务未规定该项' if absent else '按本次模型与已记录残差检查',kind='numerical' if k in NUMERICAL or (k=='mass_budget' and p.weight.mode!='fixed') else 'design'))
    fl=summary.get('first_level');c=p.sizing.first_level
    if not fl:
        rows.extend(row(k,label,'not_calculated','未启用一级模型，或总体未形成可用结果') for k,label in EXTRA.items())
        return rows
    for name in ('takeoff','landing'):
        key=name+'_distance';limit=c[name+'_limit_m'];r=fl['field'][name];value=r.get('total_m')
        status='not_applicable' if limit is None else ('not_calculated' if value is None else ('met' if value<=limit*(1+1e-6) else 'exceeded'))
        rows.append(row(key,EXTRA[key],status,r.get('reason','干燥跑道工程模型；并非具体机型实测性能'),value,limit,None if value is None or limit is None else limit-value,'m'))
    pw=summary['power']
    for key,src in [('climb_sea_level','climb_at_sea_level'),('climb_cruise_altitude','climb_at_cruise_altitude')]:
        need=pw['power_constraints_w'].get(src);limit=pw['installed_power_w']
        rows.append(row(key,EXTRA[key],'not_calculated' if need is None else ('met' if need<=limit else 'exceeded'),
            f'爬升率要求 {p.sizing.climb_rate_m_s:g}m/s；需用与安装额定功率在同一基准比较',need,limit,None if need is None else limit-need,'W'))
    cg=[x['cg_mac'] for x in fl['loading']];margin=min(min(cg)-c['cg_min_mac'],c['cg_max_mac']-max(cg))
    rows.append(row('loading_cg',EXTRA['loading_cg'],'met' if margin>=0 else 'exceeded','实际装载和主任务结束；仅显式声明的分配场景', [min(cg),max(cg)],[c['cg_min_mac'],c['cg_max_mac']],margin,'MAC'))
    pts=[pt for case in fl['longitudinal'] for pt in case['points']];sm=min(pt['static_margin'] for pt in pts)
    rows.append(row('longitudinal_static',EXTRA['longitudinal_static'],'met' if sm>=c['static_margin_min'] else 'exceeded','固定舵面线性升力斜率，缺失机身/动力修正',sm,c['static_margin_min'],sm-c['static_margin_min'],'MAC'))
    ratio=max(max(abs(pt['alpha_deg'])/c['alpha_limit_deg'],abs(pt['elevator_deg'])/c['elevator_limit_deg']) for pt in pts)
    rows.append(row('longitudinal_control',EXTRA['longitudinal_control'],'met' if ratio<=1 else 'exceeded','所有装载及给定Cm扰动角点；超过角度域表示当前一级方案尚不能确认可用',ratio,1.,1.-ratio,'fraction'))
    rows.extend(row(k,EXTRA[k],'not_calculated','后续节点，当前概念筛查不包含此项') for k in ('lateral_control','structural_feedback'))
    return rows


def attach(summary,p):
    if p.sizing.first_level is not None and summary.get('converged'):
        from .first_level import evaluate
        summary['first_level']=evaluate(summary,p)
        summary['limits']=[x for x in summary['limits'] if '起降距离' not in x]+summary['first_level']['limits']
    summary['constraint_states']=states(summary,p)
    required=[r for r in summary['constraint_states'] if r['id'] in EXTRA and r['id'] not in ('lateral_control','structural_feedback')]
    summary['first_level_complete']=p.sizing.first_level is not None and all(r['status']!='not_calculated' for r in required)
    if p.sizing.first_level is not None and summary.get('converged'):
        if any(r['status']=='exceeded' for r in required):summary['status']='constraints_not_met'
        elif any(r['status']=='not_calculated' for r in required) and summary['status']=='concept_checked_with_limits':summary['status']='constraints_not_evaluated'


def display_rows(summary,p=None):
    rows=summary.get('constraint_states')
    if rows is None and p is not None:rows=states(summary,p)
    if rows is None:
        rows=[row(k,k,'not_calculated','历史布尔项缺少适用条件，请查看原始记录') for k in summary.get('checks',{})]
    return [{'项目':r['label'],'状态':LABELS[r['status']],'类别':'数值检查' if r['kind']=='numerical' else '设计约束',
             '计算值':r['value'],'限值':r['limit'],'余量':r['margin'],'单位':r['unit'],'说明':r['reason']} for r in rows]


def markdown(summary,p=None):
    return '\n'.join('- '+r['项目']+'：'+r['状态']+'（'+r['类别']+'）；'+r['说明'] for r in display_rows(summary,p))
