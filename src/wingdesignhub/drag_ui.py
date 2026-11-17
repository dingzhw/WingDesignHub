"""One-click profile and nonlifting drag after the accepted trim."""
from dataclasses import asdict
from pathlib import Path
import streamlit as st
from .aircraft_drag import DragOptions
from .drag_service import run_aircraft_drag

LABELS={'induced':'诱导阻力','profile':'翼尾剖面','body':'非升力部件','allowance':'显式修正'}
COMPONENTS={'lifting_system':'联合升力系统','MainWing':'机翼','HorizontalTail':'平尾','VerticalTail':'垂尾',
            'Fuselage':'机身','Spinner':'桨帽','NoseFairing':'前轮整流罩','LeftFairing':'左主轮整流罩',
            'RightFairing':'右主轮整流罩','NoseStrut':'前支柱','LeftStrut':'左支柱','RightStrut':'右支柱',
            'junction':'接合部预算','cooling':'冷却预算','roughness':'粗糙度增量预算'}


def show_files(record,files,key):
    if record['status']!='drag_checked_with_limits':
        st.error('阻力账目未完成：'+record.get('error',record['status']))
        st.caption('缺失或越界项不会按零阻力计入。调整工况、检查翼型或重新计算后再使用总阻力。')
        with st.expander('定位极曲线问题'):st.json(record.get('diagnostic_context',{}))
    else:
        s=record['summary'];ledger=s['ledger'];columns=st.columns(3)
        columns[0].metric('总阻力系数 CD',f"{ledger['cd_total']:.5f}")
        columns[1].metric('阻力（N）',f"{ledger['drag_n']:.1f}")
        columns[2].metric('当前工况升阻比',f"{s['lift_to_drag']:.2f}")
        st.success('阻力账目计算完成；各项来源和面积已记录。')
        if s['sizing_status']=='constraints_not_met':st.warning('来源总体方案仍有约束未满足。')
        st.dataframe([{'部件':COMPONENTS[r['component']],'归属':LABELS[r['contribution']],'CD':r['cd'],'阻力 N':r['drag_n']} for r in ledger['rows']],hide_index=True)
        st.caption('沿用无黏配平状态叠加阻力；总体燃油、功率与任务结果尚未更新。')
        for line in s.get('diagnostics',[]):st.caption(line)
        with st.expander('极曲线覆盖、假设和适用边界'):
            st.json(s['polar_coverage']);st.json(s['options'])
            for line in s['limits']:st.caption(line)
    for name,label in [('report.html','导出阻力报告'),('drag_ledger.json','下载阻力账目'),('profile_queries.json','下载条带剖面阻力')]:
        if name in files:st.download_button(label,files[name],name,key=key+'_'+name)


def render(project,root,trim):
    if trim['status']!='trim_checked_with_limits':return
    st.subheader('配平状态下的阻力账目')
    st.caption('计算翼尾剖面、机身及起落架阻力，并与当前配平诱导阻力汇总。首次运行需生成极曲线，后续复用已验证缓存。')
    with st.expander('阻力模型假设（可使用默认值）'):
        st.write('默认采用光滑翼型、自然转捩上限 x/c=1、Ncrit=9。机身等顺流体采用全湍流摩阻；以下修正为未校准的概念预算。')
        n=st.number_input('转捩环境 Ncrit',1.,14.,9.,key='drag_ncrit')
        trip=st.number_input('翼型上、下表面强制转捩位置 x/c',.01,1.,1.,step=.05,key='drag_trip')
        strut=st.number_input('支柱横流阻力系数',.1,2.,1.2,step=.1,key='drag_strut')
        junction=st.number_input('接合部修正 CD',0.,.02,.0015,step=.0005,format='%.4f',key='drag_junction')
        cooling=st.number_input('冷却修正 CD',0.,.02,.001,step=.0005,format='%.4f',key='drag_cooling')
        roughness=st.number_input('粗糙度增量 CD',0.,.02,.0005,step=.0005,format='%.4f',key='drag_roughness')
        panels=st.selectbox('翼型求解面元',options=[240,160],format_func=lambda x:'240（默认）' if x==240 else '160（离散对照）',key='drag_panels')
    o=DragOptions(panels=panels,ncrit=n,trip_top=trip,trip_bottom=trip,strut_crossflow_cd=strut,junction_cd=junction,cooling_cd=cooling,roughness_cd=roughness)
    if st.button('计算阻力账目',key='run_aircraft_drag'):
        try:
            from .job_ui import submit
            submit(root,'drag',project,trim['run_id'],o)
        except (ValueError,OSError) as exc:st.error(str(exc))
    r=st.session_state.get('aircraft_drag_result')
    if r and r.get('parent_run_id')==trim['run_id']:
        if r['options']!=asdict(o):st.warning('阻力假设已更改，下方保留上次结果，请重新计算。')
        from .service import get_results
        try:
            r=get_results(root,r['run_id']);work=Path(root)/'runs'/r['run_id']
            show_files(r,{n:(work/n).read_bytes() for n in r['artifact_hashes']},'current_drag')
        except (ValueError,OSError) as exc:st.error('阻力记录检查失败：'+str(exc))
