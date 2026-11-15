"""Small plate validation tool, separate from the planned aircraft design flow."""
import json
import streamlit as st
from .plate_buckling import PlateCase


def render(root):
    from .plate_service import run_plate_analysis
    st.subheader('代表板线性屈曲校核')
    st.write('给定板尺寸、参考膜应力和支承，计算参考载荷增大或减小到线性失稳时的比例。')
    st.caption('这是独立代表板验证。全翼失稳、缺陷与后屈曲，以及需求驱动的总体设计流程按各自路线推进。')
    base=PlateCase();upload=st.file_uploader('打开代表板配置（可选）',type='json')
    if upload:
        try:base=PlateCase.from_dict(json.loads(upload.getvalue()))
        except (ValueError,TypeError) as exc:st.error(f'配置无法读取：{exc}');st.stop()
    support_names={'四边横向简支':'simply_supported','四边横向固支':'clamped'}
    with st.form('plate_buckling'):
        a,b,c=st.columns(3)
        length=a.number_input('沿载荷方向长度（m）',min_value=.05,max_value=3.,value=float(base.length_m))
        width=b.number_input('板宽（m）',min_value=.05,max_value=3.,value=float(base.width_m))
        thickness=c.number_input('板厚（mm）',min_value=.01,max_value=100.,value=base.thickness_m*1000)
        compression=a.number_input('参考压应力（MPa，正值为压缩）',min_value=0.,value=base.compression_pa/1e6)
        shear=b.number_input('参考剪应力（MPa）',value=base.shear_pa/1e6)
        support=c.selectbox('边缘支承',list(support_names),index=list(support_names.values()).index(base.support))
        with st.expander('材料与网格'):
            E=st.number_input('弹性模量（GPa）',min_value=.1,value=base.elastic_modulus_pa/1e9)
            nu=st.number_input('泊松比',min_value=0.,max_value=.499,value=base.poisson_ratio)
            n=st.number_input('板宽方向分段数',min_value=4,max_value=48,value=base.divisions,step=1)
            st.caption('长度方向分段按长宽比自动匹配，求解模态数量随配置保留。')
        clicked=st.form_submit_button('一键计算代表板屈曲',type='primary')
    data=base.to_dict();data.update(length_m=length,width_m=width,thickness_m=thickness/1000,compression_pa=compression*1e6,
          shear_pa=shear*1e6,support=support_names[support],elastic_modulus_pa=E*1e9,poisson_ratio=nu,divisions=int(n))
    st.download_button('保存代表板配置',json.dumps(data,ensure_ascii=False,indent=2),'plate-buckling.json')
    if clicked:
        try:
            with st.spinner('正在核查参考载荷并求解屈曲模态……'):st.session_state['plate_result']=run_plate_analysis(data,root)
        except (ValueError,TypeError) as exc:st.error(str(exc))
    if 'plate_result' not in st.session_state:return
    r=st.session_state['plate_result'];st.caption(f"运行编号：{r['run_id']}。更改输入后须重新运行。")
    if r['status']=='failed':st.error(r['error'])
    else:
        s=r['summary']
        if r['status']=='executed_with_limits':st.warning('首阶系数小于 1：当前参考应力超过该理想板的线性屈曲载荷。')
        else:st.success('线性特征值计算完成；系数针对当前理想板与支承。')
        a,b=st.columns(2);a.metric('首阶实际工况载荷系数',f"{s['first_factor']:.6g}")
        b.metric('临界压应力分量',f"{s['critical_compression_pa']/1e6:.3f} MPa")
        st.write('前几阶系数',s['factors']);work=root/'runs'/r['run_id']/'plate'
        st.image((work/'mode_preview.svg').read_text(encoding='utf-8'),caption='首阶归一化面外模态，幅值不是实际变形。')
        for limit in s['limits']:st.caption(limit)
        for label,name in (('下载求解输入','plate.inp'),('下载模态文件','plate.frd'),('下载参考载荷换算','solver_reference.json')):
            st.download_button(label,(work/name).read_bytes(),name)
    with st.expander('完整计算记录'):st.json(r)
    st.download_button('下载代表板结果',json.dumps(r,ensure_ascii=False,indent=2),'plate-result.json')
