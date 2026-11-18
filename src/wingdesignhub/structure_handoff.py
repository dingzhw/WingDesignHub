"""Preparation inventory, not a design-load envelope or an automatic FEA input."""
from .presentation import constraint_rows


def build(project, record):
    if record.get('definition_sha256') != project.definition_hash():
        raise ValueError('结构准备清单与当前需求不一致，请选回对应运行')
    s=record.get('summary',{});valid=bool(s.get('converged'))
    def available(key):return '已有概念结果' if valid and s.get(key) else '待计算'
    items=[
        ('任务和构型','已有定义','input.json；使用本次确认的载荷、任务、重量模式与构型假设'),
        ('全翼尺寸与参考量',available('geometry'),'summary.geometry：全翼毛面积、翼展、MAC；几何 x 后/y 右/z 上，动力学 x 前/y 右/z 下'),
        ('质量、站位与重心',available('cg'),'summary.cg.rows：概念部件质量/站位；质量预算余量不得自动作为压舱物'),
        ('携油与任务质量变化',available('mission'),'summary.mission：出场/入场滑行、起飞滑跑、主任务与储备分列；卸载使用对应工况实际携油'),
        ('装载及纵向筛查',available('first_level'),'summary.first_level；保留超限；巡航线性尾翼筛查不是起飞拉平或全包线'),
        ('最终原生几何','待核验文件' if valid and record.get('mode') in ('overall_propulsion','overall_feedback') else '待生成/核验',
         'final_geometry/geometry_contract.json 与 aircraft.vsp3；必须核对同一运行及哈希，外形曲面并非承力结构'),
        ('设计载荷工况','待定义','V0.3.6：机动/阵风/着陆、质量/CG/燃油、速度高度、限制载荷与安全系数；当前任务点不能代替包线'),
        ('配平条带与完整载荷','待生成/核验','逐设计工况复算配平、条带、尾翼及集中载荷；检查投影/六分量、参考点、合力与合力矩，保留机身/动力力矩缺项'),
        ('质量与惯性卸载','待定义','同工况部件、发动机与燃油分布；惯性方向/过载只计一次；当前 x 站位台账不足以定义三维分布'),
        ('结构布局与材料','待定义','V0.3.7：两梁翼盒、肋/蒙皮、材料牌号状态、厚度和许用值来源；独立研究假设须确认'),
        ('连接与支承边界','待定义','根部连接、支柱传力及约束自由度须声明；不能把基准算例固支直接当作整机实物连接'),
        ('结构质量回写','待接入','V0.3.8：定尺寸部件替换对应经验重量；接头和非承力项单列，重新收敛总体')]
    return {'schema':1,'kind':'loads_structure_preparation','run_id':record['run_id'],
            'source_version':record.get('version'),'definition_sha256':project.definition_hash(),
            'engineering_status':record['status'],'numerically_converged':valid,
            'ready_for_structural_solution':False,
            'items':[dict(item=n,status=t,source_or_action=d) for n,t,d in items],
            'constraint_rows':constraint_rows(s,project),
            'model_limits':s.get('limits',[]),'diagnostics':s.get('diagnostics',[]),
            'geometry':s.get('geometry',{}),'mass_ledger':s.get('cg',{}),
            'mission':s.get('mission',{}),'loading':s.get('first_level',{}).get('loading',[]),
            'artifact_references':{k:v for k,v in record.get('artifact_hashes',{}).items()
                                   if k.startswith('final_geometry/') or k in ('aero_table.json','native_manifest.json')}}


def markdown(data):
    lines=['# 载荷与结构阶段输入清单','',f"来源运行：{data['run_id']} · V{data['source_version']}",
           '当前工程状态：'+data['engineering_status'],
           '这是输入准备清单；设计载荷、承力布局及支承尚待定义。','',
           '|输入项|准备状态|来源或下一步|','|---|---|---|']
    lines += [f"|{r['item']}|{r['status']}|{r['source_or_action']}|" for r in data['items']]
    lines += ['','## 约束与偏差']
    lines += [f"- {r['项目']}：{r['状态']}；计算值 {r['计算值']}，限值 {r['限值']}，余量 {r['余量']} {r['单位']}；{r['说明']}" for r in data['constraint_rows']]
    lines += ['']+['- '+str(x) for x in data['model_limits']+data['diagnostics']]
    return '\n'.join(lines)+'\n'


def render(project, record, key):
    import json
    import streamlit as st
    data=build(project,record)
    with st.expander('进入载荷与结构阶段：输入准备清单'):
        st.caption('清单绑定当前运行；约束超限可带入研究，但尚未形成可直接求解的结构工况。')
        st.dataframe([{'输入项':r['item'],'准备状态':r['status'],'来源或下一步':r['source_or_action']} for r in data['items']],hide_index=True)
        st.download_button('下载载荷与结构输入清单',markdown(data),'structure-inputs.md',key=key+'_handoff_md')
        st.download_button('下载结构准备数据（SI）',json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False),'structure-inputs.json',key=key+'_handoff_json')
