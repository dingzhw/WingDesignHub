"""Readable reports separate same-condition comparison from redesign effects."""
from html import escape
import json
from .design_report import design_report_html,table
from .aero_feedback import LIMITS


def write_report(project,record,work):
    summary=record.get('summary',{});audit=summary.get('aerodynamic_feedback',{})
    rows=summary.get('redesign_comparison',{}).get('rows',[])
    section='<h2>气动反馈后的重新定尺寸</h2><p>相同需求，气动模型及显式速度安排有变化；原总体结果保留。</p>'
    section+=table(['指标','单位','原总体','气动反馈','变化比例'],[(r['quantity'],r['unit'],r['legacy'],r['feedback'],r['relative_change']) for r in rows])
    section+='<h2>同条件模型差异</h2><pre>'+escape(json.dumps(audit.get('same_condition_comparison',{}),ensure_ascii=False,indent=2))+'</pre>'
    section+='<h2>气动表与任务积分验证</h2><pre>'+escape(json.dumps({k:v for k,v in audit.items() if k in ('direct_checks','timestep_half_relative_fuel_error','table_verified','timestep_verified','speed_schedule_m_s')},ensure_ascii=False,indent=2))+'</pre>'
    section+='<h2>本次气动假设</h2><pre>'+escape(json.dumps(record['options'],ensure_ascii=False,indent=2))+'</pre>'
    section+='<h2>固定构型的假设敏感性</h2><p>保持外形、起始装载、发动机和速度安排，重算需油与需用功率；没有重新优化或增加实际携带油量。负燃油余量表示原装油不足。</p>'
    section+=table(['工况','状态','需总可用油 kg','需安装功率 W','携带油余量 kg'],[(r['case'],r['status'],r.get('required_block_fuel_kg'),r.get('required_installed_power_w'),r.get('carried_fuel_margin_kg')) for r in audit.get('fixed_design_sensitivity',{}).get('rows',[])])
    section+='<p>逐点气动、极曲线和命令保存在 native_evidence.zip；未进行整机试验校准。专业评审待签署。</p>'
    text=design_report_html(project,record).replace('<h2>输入与假设快照</h2>',section+'<h2>输入与假设快照</h2>')
    (work/'report.html').write_text(text,encoding='utf-8')
    md=['# '+project.name+' — 气动驱动总体','', '状态：'+record['status'],'来源总体：'+record['parent_run_id'],'',
        '|指标|单位|原总体|反馈后|变化|','|---|---|---:|---:|---:|']
    md += [f"|{r['quantity']}|{r['unit']}|{r['legacy']:.3f}|{r['feedback']:.3f}|{r['relative_change']:.2%}|" for r in rows]
    md += ['',record.get('error',''),*summary.get('diagnostics',[]),'','同条件比较：','```json',json.dumps(audit.get('same_condition_comparison',{}),ensure_ascii=False,indent=2),'```','',*LIMITS]
    (work/'report.md').write_text('\n'.join(md)+'\n',encoding='utf-8')
