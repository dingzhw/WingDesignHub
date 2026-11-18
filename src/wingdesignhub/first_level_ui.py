"""Small opt-in editor; engineering assumptions stay visible and confirmed."""
from copy import deepcopy
import streamlit as st
from .first_level_config import default_first_level, BOUNDS

NAMES={'takeoff_limit_m':'越障起飞距离上限（m）','landing_limit_m':'越障着陆距离上限（m）',
 'field_altitude_m':'起降场地压力高度（m）','temperature_delta_k':'场地偏离标准大气温度（℃）',
 'obstacle_m':'起降障碍高度（m）','takeoff_cl_max':'起飞构型CLmax','takeoff_cd_increment':'起飞襟翼附加CD',
 'landing_cd_increment':'着陆襟翼附加CD','rolling_friction':'滑跑摩擦系数','braking_friction':'制动摩擦系数',
 'disk_power_factor':'作用盘有效功率比例（独立低速工程模型）','approach_deg':'着陆下滑角（度）',
 'flare_load_factor':'拉平过载','rotation_time_s':'抬轮延时（秒）','landing_delay_s':'接地制动延时（秒）',
 'schedule_cl_ceiling':'速度搜索CL上限','schedule_max_speed_m_s':'速度搜索上限（m/s）',
 'cg_min_mac':'CG研究下限（MAC比例）','cg_max_mac':'CG研究上限（MAC比例）','static_margin_min':'静稳定裕度下限（MAC比例）',
 'wing_cm_ac':'机翼气动中心Cm假设','moment_bias_abs':'缺失俯仰矩敏感性±ΔCm',
 'tail_dynamic_pressure_ratio':'平尾动压比','downwash_gradient':'下洗梯度','elevator_effectiveness':'升降舵效率',
 'alpha_zero_lift_deg':'机翼零升迎角（度）','alpha_limit_deg':'一级迎角绝对限值（度）','elevator_limit_deg':'一级舵偏绝对限值（度）'}


def editor(base,key):
    if not st.toggle('启用起降、装载重心与纵向一级约束',value=base is not None,key=key+'_first_on'):return None
    c=deepcopy(base) if base else default_first_level()
    st.caption('概念筛查；默认数值是研究假设。超限将保留方案和原因，不自动移动重心。起降使用独立作用盘估算，未外推CCBlade巡航桨图。')
    for name in ('takeoff_limit_m','landing_limit_m'):
        enabled=st.checkbox('规定'+('起飞' if name.startswith('takeoff') else '着陆')+'距离上限',value=c[name] is not None,key=key+name+'_on')
        c[name]=st.number_input(NAMES[name],min_value=100.,max_value=5000.,value=float(c[name] or 800),step=25.,key=key+name) if enabled else None
    with st.expander('一级方法和适用条件'):
        for name,(lo,hi) in BOUNDS.items():
            if name.endswith('limit_m'):continue
            c[name]=st.number_input(NAMES[name],min_value=float(lo),max_value=float(hi),value=float(c[name]),
                step=.01 if hi<=1 else .1,key=key+'_first_'+name)
        c['source']=st.text_input('一级假设来源',c['source'],key=key+'_first_source')
        st.caption('默认检查规定载荷分配的起飞与任务结束状态。附加装载场景保持总载荷，按比例重新分配；须同时启用部件布局。')
        count=st.number_input('附加装载场景数量',min_value=0,max_value=8,value=len(c['loading_cases']),step=1,key=key+'_loading_count')
        cases=[]
        for i in range(count):
            old=c['loading_cases'][i] if i<len(c['loading_cases']) else {'name':f'装载{i+1}','payload_fractions':{'front_seats':.5,'rear_seats':.4,'baggage':.1}}
            name=st.text_input('场景名称',old['name'],key=f'{key}_loadname{i}')
            front=st.number_input('前排载荷比例',min_value=0.,max_value=1.,value=float(old['payload_fractions']['front_seats']),key=f'{key}_front{i}')
            rear=st.number_input('后排载荷比例',min_value=0.,max_value=1.,value=float(old['payload_fractions']['rear_seats']),key=f'{key}_rear{i}')
            baggage=1-front-rear;st.caption(f'剩余行李比例：{baggage:.1%}，总载荷不变')
            cases.append({'name':name,'payload_fractions':{'front_seats':front,'rear_seats':rear,'baggage':baggage}})
        c['loading_cases']=cases
    return c
