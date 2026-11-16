"""Portable scheme cards with explicit inputs, computed values and evidence limits."""
from html import escape
import json
import math

STATUS={'concept_checked_with_limits':'已收敛，已检查约束满足（概念模型）',
        'constraints_not_met':'已收敛，存在约束超限','not_converged':'未收敛',
        'out_of_domain':'模型范围或任务冲突','failed':'计算失败',
        'needs_confirmation':'需求待确认','invalid_input':'需求无效'}
METRICS={'mtow_kg':('设计起飞重量','kg'),'owe_kg':('空重（含不可用燃油）','kg'),
         'block_fuel_kg':('总可用燃油（含储备与滑行）','kg'),'reserve_kg':('其中储备燃油','kg'),
         'power_kw':('安装轴功率','kW'),'area_m2':('翼面积','m²'),'span_m':('翼展','m'),
         'duration_h':('主任务空中时长','h'),'route_km':('转场航程（留空另列）','km'),
         'cg_x_m':('估算起飞重心站位','m')}
CHECK_LABELS={'mass_budget':'质量预算或闭合残差','mtow_upper_bound':'起飞重量上限',
              'fuel_capacity':'油箱容量','landing_stall':'着陆构型失速速度','power_available':'任务可用功率',
              'clean_lift':'净构型升力','range':'规定航程','endurance':'最低航时或留空时间',
              'aero_table_accuracy':'气动表直接复算','mission_step_accuracy':'任务积分步长',
              'propeller_table_accuracy':'桨图直接复算','shaft_torque_balance':'发动机与桨轴扭矩一致性'}


def make_card(project,record):
    s=record.get('summary',{});status=record['status']
    converged=s.get('converged') is True and 'geometry' in s
    eligible=status=='concept_checked_with_limits' and converged and bool(s.get('checks')) and all(s['checks'].values())
    metrics={k:None for k in METRICS};margins={};controls={}
    if converged:
        metrics.update(mtow_kg=s['design_mtow_kg'],owe_kg=s['weights']['owe_kg'],
            block_fuel_kg=s['mission']['block_fuel_kg'],reserve_kg=s['mission']['reserve_fuel_kg'],
            power_kw=s['power']['installed_power_w']/1000,area_m2=s['geometry']['wing_area_m2'],
            span_m=s['geometry']['wing_span_m'],duration_h=s['mission']['main_duration_s']/3600,
            route_km=s['mission']['route_distance_m']/1000,cg_x_m=s['cg']['cg_x_m'])
        if any(not math.isfinite(v) for v in metrics.values()):raise ValueError('方案卡输出不是有限数值')
        margins={'mass_budget_kg':s['mass_budget_margin_kg'],'upper_bound_kg':s['upper_bound_margin_kg'],
                 'usable_fuel_capacity_kg':s['geometry']['usable_tank_capacity_kg']-s['mission']['block_fuel_kg']}
        controls={'wing_area':s['geometry']['controlling_area_constraint'],'power':s['power']['controlling_power_constraint']}
    diagnostics=[d if isinstance(d,str) else d.get('message',str(d)) for d in s.get('diagnostics',[])]
    if record.get('error'):diagnostics.append(record['error'])
    return {'name':project.name,'run_id':record['run_id'],'status':status,'status_label':STATUS.get(status,status),
            'eligible':eligible,'converged':converged,'metrics':metrics,'margins':margins,'controls':controls,
            'checks':s.get('checks',{}),'diagnostics':diagnostics,'input':project.to_dict(),
            'definition_sha256':project.definition_hash(),'software_version':record['version'],
            'solver_versions':s.get('versions',{}),'iterations':len(s.get('iterations',[])),
            'final_residuals':s.get('iterations',[{}])[-1].get('residuals',{}) if s.get('iterations') else {},
            'geometry':s.get('geometry') if converged else None,
            'limits':s.get('limits',[])+(['CG 为站位估算；气动任务表已接入，起降距离和结构质量回写尚未接通。'] if 'aerodynamic_feedback' in s or 'propulsion_feedback' in s else ['CG 为站位估算；配平、起降距离和结构质量回写尚未接通。']),
            'physical_validation_passed':False}


def card_html(card):
    """Standalone printable HTML; escape all user values and require no external assets."""
    def esc(x):return escape(str(x))
    rows=''.join(f'<tr><td>{label}</td><td>{"—" if card["metrics"][k] is None else format(card["metrics"][k],".3f")}</td><td>{unit}</td></tr>'
                 for k,(label,unit) in METRICS.items())
    from .sizing_worker import geometry_svg
    svg=geometry_svg(card['geometry']) if card['geometry'] else ''
    notes=''.join('<li>'+esc(x)+'</li>' for x in card['diagnostics']+card['limits'])
    assumptions=esc(json.dumps(card['input'],ensure_ascii=False,indent=2))
    from .requirements import WEIGHT_LABELS,MISSION_LABELS
    p=card['input'];m=p['mission'];a=p['assumptions'];w=p['weight']
    stated=f"载荷 {p['payload_kg']:g} kg（含机组）；{WEIGHT_LABELS[w['mode']]}"
    if w['value_kg'] is not None:stated+=f" {w['value_kg']:g} kg"
    stated+=f"；{MISSION_LABELS[m['kind']]}"
    if m['range_m'] is not None:stated+=f" {m['range_m']/1000:g} km"
    if m['endurance_s'] is not None:stated+=f"，要求时长 {m['endurance_s']/3600:g} h"
    stated+=f"；巡航 {a['cruise_speed_m_s']*3.6:g} km/h、{a['cruise_altitude_m']:g} m，额外储备 {a['reserve_duration_s']/60:g} min。"
    check_text='；'.join(CHECK_LABELS.get(k,k)+('：满足' if v else '：未满足') for k,v in card['checks'].items())
    labels={'landing_stall':'着陆构型失速','cruise_lift':'巡航升力','fuel_volume':'油箱容量','cruise':'巡航需用功率',
            'climb_at_cruise_altitude':'巡航高度爬升','loiter':'留空需用功率'}
    control_text='；'.join(('翼面积' if k=='wing_area' else '功率')+'：'+labels.get(v,v) for k,v in card['controls'].items())
    return f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>{esc(card['name'])} · 方案卡</title>
<style>body{{font:16px/1.6 "Microsoft YaHei",sans-serif;max-width:960px;margin:35px auto;padding:0 24px;color:#24384a}}
h1{{color:#163b52}}.status{{padding:12px;background:#fff2d4;border-left:4px solid #bb8200}}
table{{border-collapse:collapse;width:100%}}td,th{{padding:7px;border-bottom:1px solid #dce2e7;text-align:left}}
svg{{width:100%;max-height:360px}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px}}
@media print{{body{{margin:0;font-size:11pt}}details{{display:block}}pre{{font-size:8pt}}}}</style>
<h1>{esc(card['name'])}</h1><p class="status">{esc(card['status_label'])}。数值结果用于初步方案研究。</p>
<h2>规定需求</h2><p>{esc(stated)}</p>
<table><tr><th>计算输出</th><th>值</th><th>单位</th></tr>{rows}</table>{svg}
<p>迭代 {card['iterations']} 轮；控制约束：{esc(control_text)}；余量（kg）：{esc(card['margins'])}</p>
<p>检查：{esc(check_text)}</p><ul>{notes}</ul><h2>输入与假设快照</h2><pre>{assumptions}</pre>
<p>V{esc(card['software_version'])} · 运行 {esc(card['run_id'])}</p>
<pre>定义 SHA-256：{esc(card['definition_sha256'])}\n求解器：{esc(card['solver_versions'])}</pre></html>'''


def comparison_markdown(summary):
    lines=['# 三方案比较','',summary['interpretation'],'','| 方案 | 状态 | 起飞重量 kg | 翼面积 m² | 功率 kW | 总可用燃油 kg |','|---|---|---:|---:|---:|---:|']
    for c in summary['cards']:
        vals=['—' if c['metrics'][k] is None else f"{c['metrics'][k]:.3f}" for k in ('mtow_kg','area_m2','power_kw','block_fuel_kg')]
        name=c['name'].replace('|','\\|').replace('\n',' ')
        lines.append('| '+' | '.join([name,c['status_label'],*vals])+' |')
    lines+=['','方案 1 为差分基准；未收敛或未满足约束的方案不参与有效结果差分。','',
            '输入差异、完整假设与诊断见 comparison.json 及各方案卡。所有方案仍须配平、起降及结构校核。']
    return '\n'.join(lines)+'\n'
