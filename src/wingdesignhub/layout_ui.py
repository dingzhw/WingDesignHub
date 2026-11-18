"""Optional layout editing without raw JSON or solver terminology."""
from copy import deepcopy
import streamlit as st
from .layout import default_layout


def editor(value,key):
    enabled=st.toggle('启用分项布置与装载位置',value=value is not None,key=key+'_layout_on')
    if not enabled:
        st.caption('沿用旧版大类固定站位。启用后可检查部件位置、安装角和装载分配；修改需重新确认方案。')
        return None
    data=deepcopy(value or default_layout())
    st.caption('以下默认位置是可复核的概念布置假设，不是实机测量，也不保证重心可行。位置以机头为零、向后为正。')
    data['wing_quarter_fraction']=st.number_input('机翼四分之一弦位置（机长比例）',.3,.48,float(data['wing_quarter_fraction']),.01,key=key+'_wing_x')
    for field,label in [('wing_incidence_deg','主翼安装角（度）'),('tail_incidence_deg','平尾安装角（度）')]:
        data[field]=st.number_input(label,-3.,3.,float(data[field]),.25,key=key+'_'+field)
    labels={'fuselage':'机身结构','engine':'安装发动机及附件','systems':'机载系统','controls':'操纵系统',
            'front_seats':'前排','rear_seats':'后排','baggage':'行李','fuel':'燃油'}
    with st.expander('部件与装载位置'):
        for field,label in labels.items():
            data['stations_fraction'][field]=st.number_input(label+'位置（机长比例）',0.,1.,float(data['stations_fraction'][field]),.01,key=key+'_station_'+field)
        for field in ('front_seats','rear_seats','baggage'):
            data['payload_fractions'][field]=st.number_input(labels[field]+'载荷占比',0.,1.,float(data['payload_fractions'][field]),.05,key=key+'_fraction_'+field)
        st.caption('三个载荷比例之和须为1；总载荷包含机组。前后装载敏感性不等于座椅/行李允许重量。')
    data['source']=st.text_input('布局来源或假设说明',data['source'],key=key+'_layout_source')
    return data
