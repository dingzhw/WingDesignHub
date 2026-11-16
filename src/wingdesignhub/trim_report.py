"""Traceable trim export; residual success and scope remain separate."""
import html
import json


def write_report(work,contract,record):
    s=record['summary'];t=s['trim']
    text=f"# WingDesignHub V{record['version']} 纵向配平报告\n\n运行：{record['run_id']}\n\n"
    text+=f"状态：{s['status']}；{t['diagnostic']}。来源总体状态：{s['sizing_status']}。\n\n"
    text+=f"迎角 {t['alpha_deg']:.7f}°；升降舵 {t['elevator_deg']:.7f}°（后缘向下为正）。\n\n"
    text+=f"CL 残差 {t['residual_cl']:.8g}；Cm 残差 {t['residual_cm']:.8g}；升力残差 {t['lift_residual_n']:.8g} N；俯仰残差 {t['pitch_residual_nm']:.8g} N·m。\n\n"
    for title,data in [('工况质量与重心来源',s['flight_state']),('工况和参考量',{'flow':s['flow'],'references':s['references']}),
                       ('载荷、诱导阻力及局部诊断',{'surface_loads':t['surface_loads'],'induced_drag_n':t['induced_drag_n'],
                         'Cma_per_rad':t['local_cma_per_rad'],'locally_restoring_pitch':t['locally_restoring_pitch'],'margins_deg':t['margins_deg']}),
                       ('求解设置与实际迭代',{'options':record['options'],'tolerances':t['tolerances'],'history':t['history']})]:
        text+='## '+title+'\n\n'+json.dumps(data,ensure_ascii=False,indent=2)+'\n\n'
    text+='## 方法与适用边界\n\n'+'\n'.join('- '+x for x in s['limits'])+'\n\n'
    text+='来源几何：'+record['parent_run_id']+'；总体：'+record['sizing_run_id']+'。\n'
    text+='采用实际 AVL 输出检查残差；独立物理精度仍待验证。配平结果尚未回写总体任务燃油。\n'
    (work/'report.md').write_text(text,encoding='utf-8')
    (work/'report.html').write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>纵向配平报告</title><style>body{max-width:980px;margin:32px auto;font-family:system-ui}pre{white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.6}</style><body><pre>'+html.escape(text)+'</pre></body></html>',encoding='utf-8')
