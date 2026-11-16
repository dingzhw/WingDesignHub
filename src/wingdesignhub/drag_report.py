"""Portable ledger report, including failed polar diagnostics."""
import html
import json


def write_report(work,contract,record):
    text=f"# WingDesignHub V{record['version']} 配平阻力账目报告\n\n"
    text+=f"运行：{record['run_id']}；配平：{record['parent_run_id']}；几何：{record['geometry_run_id']}\n\n状态：{record['status']}\n\n"
    if record.get('error'):
        text+='未形成总阻力：'+record['error']+'\n\n'+json.dumps(record.get('diagnostic_context',{}),ensure_ascii=False,indent=2)+'\n\n'
    else:
        s=record['summary'];ledger=s['ledger']
        text+=f"总 CD {ledger['cd_total']:.7f}；阻力 {ledger['drag_n']:.3f} N；升阻比 {s['lift_to_drag']:.3f}。\n\n"
        text+='\n'.join(s.get('diagnostics',[]))+'\n\n'
        text+='|部件|归属|CD|阻力 N|方法|\n|---|---|---:|---:|---|\n'
        for row in ledger['rows']:text+=f"|{row['component']}|{row['contribution']}|{row['cd']:.7f}|{row['drag_n']:.3f}|{row['method']}|\n"
        text+='\n## 极曲线覆盖\n\n'+json.dumps(s['polar_coverage'],ensure_ascii=False,indent=2)+'\n\n'
    text+='## 工况、参考量与可见假设\n\n'+json.dumps({k:contract[k] for k in ('flow','references','flight_state','trim_options','options','ownership','excluded_from_sum')},ensure_ascii=False,indent=2)+'\n\n'
    text+='## 使用范围与验证状态\n\n'+'\n'.join('- '+line for line in contract['limits'])+'\n'
    (work/'report.md').write_text(text,encoding='utf-8')
    page='<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>配平阻力账目报告</title><style>body{max-width:1000px;margin:32px auto;font-family:system-ui}pre{white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.6}@media print{body{margin:0}}</style><body><pre>'+html.escape(text)+'</pre></body></html>'
    (work/'report.html').write_text(page,encoding='utf-8')
