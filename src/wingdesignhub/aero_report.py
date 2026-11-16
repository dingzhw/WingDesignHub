"""Engineering results, explicit scope, and portable human-readable export."""
import html
import json


def write_report(work,contract,record):
    s=record['summary'];c=s['coefficients'];f=s['flow'];r=s['references']
    text=f"# WingDesignHub V{record['version']} 全机升力面气动报告\n\n"
    text+=f"运行：{record['run_id']}\n\n来源几何：{record['parent_run_id']}；总体：{record['sizing_run_id']}\n\n"
    text+=f"AVL {s['solver_version']}；状态 {s['status']}；尚未配平。总体状态 {s['sizing_status']}。\n\n"
    text+='## 工况与参考量\n\n'+json.dumps({'flow':f,'references':r,'options':s['options']},ensure_ascii=False,indent=2)+'\n\n'
    text+='## 求解结果\n\n'
    for key in ('CLtot','CDff','CDtot','CYtot','Cltot','Cmtot','Cntot'):text+=f'- {key}: {c[key]:.8g}\n'
    text+='\nCDff 为诱导阻力；CDtot 是当前无黏模型的近场积分。Cl/Cm/Cn 为前右下机体坐标，力矩参考点为上述几何 CG。\n\n'
    text+='## 配平准备\n\n'+json.dumps(s['trim'],ensure_ascii=False,indent=2)+'\n\n'
    text+='## 舵面与安装角\n\n'+json.dumps({'controls':s['controls'],'incidence_deg':{x['name']:x['incidence_deg'] for x in contract['surfaces']}},ensure_ascii=False,indent=2)+'\n\n'
    text+='## 验证与边界\n\n'+f"本次 {len(s['checks'])} 项参考量、工况及载荷积分检查通过；数值接口检查，独立物理验证尚未完成。\n\n"
    text+='\n'.join('- '+line for line in s['limits'])+'\n'
    (work/'report.md').write_text(text,encoding='utf-8')
    page='<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>气动分析报告</title><style>body{max-width:980px;margin:32px auto;font-family:system-ui}pre{white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.6}@media print{body{margin:0}}</style><body><pre>'+html.escape(text)+'</pre></body></html>'
    (work/'report.html').write_text(page,encoding='utf-8')


def strip_figure(loads):
    import plotly.graph_objects as go
    figure=go.Figure()
    for surface in loads['surface_totals']:
        rows=[s for s in loads['strips'] if s['surface']==surface['name']];vertical=surface['name']=='VerticalTail'
        figure.add_trace(go.Scatter(x=[s['z_le_m'] if vertical else s['y_le_m'] for s in rows],
             y=[s['cn'] for s in rows],mode='lines+markers',name=surface['name']))
    figure.update_layout(xaxis_title='展向位置 y（垂尾为 z），m',yaxis_title='局部法向力系数 cn',height=380)
    return figure
