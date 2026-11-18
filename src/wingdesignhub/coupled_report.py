"""Offline results of the propulsion-coupled overall loop."""
from html import escape
import json
from .design_report import design_report_html,table
from .propulsion_feedback import LIMITS


def write_report(project,record,work):
    s=record.get('summary',{});audit=s.get('propulsion_feedback',{});rows=s.get('redesign_comparison',{}).get('rows',[])
    section='<h2>推进闭环后的重新定尺寸</h2><p>相同需求，各模型重新定尺寸；原记录保留。历史初值不作为本次气动证据。</p>'
    section+=table(['指标','单位','原方案','闭环后','变化比例'],[(r['quantity'],r['unit'],r['before'],r['after'],r['relative_change']) for r in rows])
    section+='<h2>发动机—螺旋桨匹配与耗油覆盖</h2><pre>'+escape(json.dumps(audit,ensure_ascii=False,indent=2))+'</pre>'
    section+='<h2>本次运行选项</h2><pre>'+escape(json.dumps(record['options'],ensure_ascii=False,indent=2))+'</pre>'
    section+='<p>原生几何、配平、极曲线、CCBlade及全部迭代证据保存在 native_evidence.zip。结构仍采用经验重量，专业评审待签署。</p>'
    text=design_report_html(project,record).replace('<h2>输入与假设快照</h2>',section+'<h2>输入与假设快照</h2>')
    (work/'report.html').write_text(text,encoding='utf-8')
    md=['# '+project.name+' — 推进闭环总体','', '状态：'+record['status'],'来源初值：'+record['parent_run_id'],'',
        '|指标|单位|原方案|闭环后|变化|','|---|---|---:|---:|---:|']
    md += [f"|{r['quantity']}|{r['unit']}|{r['before']:.3f}|{r['after']:.3f}|{r['relative_change']:.2%}|" for r in rows]
    from .constraint_states import markdown
    md += ['',markdown(s,project),record.get('error',''),*s.get('diagnostics',[]),'',*s.get('limits',LIMITS)]
    (work/'report.md').write_text('\n'.join(md)+'\n',encoding='utf-8')
