"""Offline printable engineering reports generated from actual recorded results."""
from html import escape
import json
from .design_cards import make_card,card_html,METRICS,CHECK_LABELS


def table(headers,rows):
    def fmt(value):
        if value is None:return '—'
        return f'{value:.5g}' if isinstance(value,float) else str(value)
    return '<table><tr>'+''.join('<th>'+escape(x)+'</th>' for x in headers)+'</tr>'+''.join(
        '<tr>'+''.join('<td>'+escape(fmt(v))+'</td>' for v in row)+'</tr>' for row in rows)+'</table>'


def design_report_html(project,record):
    card=make_card(project,record);s=record.get('summary',{});sections=[]
    coverage='气动配平/阻力任务表与燃油、功率迭代已接通；起降距离、操稳重心包线和结构定尺寸质量反馈尚未覆盖。' if 'aerodynamic_feedback' in s else '配平、起降距离、操稳重心包线和结构定尺寸质量反馈尚未覆盖。'
    sections.append('<h2>工程覆盖与评审状态</h2><p>本报告保留实际计算状态、诊断及已检查约束；专业评审待签署。'+coverage+'</p>')
    if s.get('converged') and 'geometry' in s:
        ms=s['mission'];fuel=ms.get('fuel_model',{})
        sections += ['<h2>任务与燃油账目</h2>',table(['任务段','时长 s','航迹 m','耗油 kg','使用方法'],[
            (r['segment'],r['duration_s'],r['path_distance_m'],r['fuel_kg'],json.dumps(r.get('fuel_by_method_kg',{}),ensure_ascii=False)) for r in ms['segments']]),
            table(['账目','燃油 kg'],[(label,ms[key]) for key,label in [('taxi_out_fuel_kg','出场滑行'),('takeoff_roll_fuel_kg','起飞地面段'),('taxi_in_fuel_kg','返场滑行'),('reserve_fuel_kg','额外储备（不作为已飞段）'),('takeoff_fuel_kg','起飞携带可用油'),('block_fuel_kg','总可用油')]]),
            '<p>耗油模型：'+escape(fuel.get('label','历史统一耗油率'))+'；经济参考燃油覆盖比例 '+f"{ms.get('economy_reference_fuel_fraction',0):.1%}"+'。基础值和校准来源见完整假设。</p>',
            '<ul>'+''.join('<li>'+escape(x)+'</li>' for x in fuel.get('limits',[]))+'</ul>',
            '<h2>质量与站位</h2>',table(['部件','质量 kg','站位 x m'],[(r['component'],r['mass_kg'],r['x_m']) for r in s['cg']['rows']]),
            '<h2>收敛证据</h2><pre>'+escape(json.dumps(s['iterations'][-1],ensure_ascii=False,indent=2))+'</pre>']
    sections += ['<h2>可追溯证据</h2><pre>'+escape(json.dumps({'run_id':record['run_id'],'version':record['version'],
        'input_hash':record.get('input_hash'),'model_signature':s.get('model_signature'),'source_hashes':record.get('source_hashes',{})},ensure_ascii=False,indent=2))+'</pre>']
    return card_html(card).replace('<h2>输入与假设快照</h2>',''.join(sections)+'<h2>输入与假设快照</h2>')


def comparison_report_html(summary,record=None):
    rows=[(c['name'],c['status_label'],*[c['metrics'][k] for k in ('mtow_kg','area_m2','power_kw','block_fuel_kg')]) for c in summary.get('cards',[])]
    text='<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>三方案总体比较</title><style>body{font:16px/1.6 "Microsoft YaHei",sans-serif;max-width:1100px;margin:30px auto;padding:20px}table{border-collapse:collapse;width:100%}td,th{border:1px solid #ddd;padding:8px}pre{white-space:pre-wrap;overflow-wrap:anywhere}</style><h1>三方案总体比较</h1>'
    if record:
        text+='<p>'+escape('运行 '+record['run_id']+' · V'+record['version']+' · '+record['status'])+'</p>'
        if record.get('error'):text+='<p>'+escape(record['error'])+'</p>'
    text+='<p>'+escape(summary.get('interpretation','本次比较未形成有效结果，诊断保留在运行记录中。'))+'</p>'+table(['方案','状态','起飞重量 kg','翼面积 m²','安装功率 kW','总可用油 kg'],rows)
    text+='<h2>变化项</h2>'+table(['方案编号（0 为 A）','字段','基准','值'],[(d['scheme'],d['field'],d['base'],d['value']) for d in summary.get('differences',[])])
    text+='<h2>约束与证据</h2>'
    for c in summary.get('cards',[]):
        text+='<h3>'+escape(c['name'])+'</h3><p>'+escape('；'.join(c['diagnostics']))+'</p>'
        text+=table(['检查项','结果'],[(CHECK_LABELS.get(k,k),'满足' if v else '未满足') for k,v in c['checks'].items()])
        text+='<pre>'+escape(json.dumps({'run_id':c['run_id'],'definition_sha256':c['definition_sha256'],'input':c['input']},ensure_ascii=False,indent=2))+'</pre>'
    return text+'<p>概念模型；专业评审待签署。配平、起降距离和结构质量反馈尚未覆盖。完整子任务报告与假设保存在方案包中。</p></html>'
