"""Portable fixed-configuration propulsion comparison, including failed states."""
from html import escape
import json
from .propulsion_model import LIMITS


def write_report(project,record,work):
    summary=record.get('summary',{});rows=summary.get('comparison',[])
    title=project.name+' — 发动机与螺旋桨任务复算'
    lines=['# '+title,'','状态：'+record['status'],'运行：'+record['run_id'],
           '来源气动：'+record['parent_run_id'],'','比较保持几何、初始携油/装载和速度不变；不重新定尺寸。','']
    if record.get('error'):lines+=['诊断：'+record['error']]
    lines+=['|指标|单位|原推进假设|新推进模型|变化|','|---|---|---:|---:|---:|']
    for row in rows:lines.append(f"|{row['quantity']}|{row['unit']}|{row['legacy']:.5g}|{row['updated']:.5g}|{row['relative_change']:.2%}|")
    lines+=['','实际安装发动机与携油保持原值；需安装功率只是当前构型的需求。','',*[ '- '+s for s in LIMITS]]
    (work/'report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    table=''.join('<tr>'+''.join('<td>'+escape(str(row[k]) if k in ('quantity','unit') else f'{row[k]:.5g}')+'</td>' for k in ('quantity','unit','legacy','updated'))+'</tr>' for row in rows)
    html=f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>{escape(title)}</title>
<style>body{{max-width:1000px;margin:36px auto;font:16px/1.7 sans-serif;color:#172a3a}}table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #ccd6df;padding:8px;text-align:left}}pre{{white-space:pre-wrap;overflow-wrap:anywhere}}@media print{{details{{display:block}}}}</style>
<h1>{escape(title)}</h1><p>状态：{escape(record['status'])} · 运行：{record['run_id']}</p>
<p>固定原气动、几何、装载及速度；发动机和螺旋桨模型单独替换。未重新定尺寸。</p>
<p>{escape(record.get('error',''))}</p><table><tr><th>指标</th><th>单位</th><th>原推进假设</th><th>新推进模型</th></tr>{table}</table>
<h2>适用范围</h2><ul>{''.join('<li>'+escape(s)+'</li>' for s in LIMITS)}</ul>
<h2>计算记录</h2><pre>{escape(json.dumps(summary,ensure_ascii=False,indent=2))}</pre></html>'''
    (work/'report.html').write_text(html,encoding='utf-8')
