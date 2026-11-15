"""Local save/reopen workflow for non-programmers; archives remain historical evidence."""
import json
from pathlib import Path
import streamlit as st
from . import project_archive as archive
from .requirements import DesignProject
from .design_comparison import ComparisonRequest
from .design_cards import STATUS,METRICS


def activate(parsed=None):
    for key in ('sizing_result','comparison_result','design_intent_result','archive_saved_note','aircraft_geometry_result'):
        st.session_state.pop(key,None)
    for key in list(st.session_state):
        if key.startswith(('confirm_','comparison-confirm-')):st.session_state.pop(key,None)
    st.session_state['workspace_revision']=st.session_state.get('workspace_revision',0)+1
    st.session_state['opened_archive']=parsed


def library(root):
    if st.button('新建空白方案',key='new_blank_design'):
        activate();st.rerun()
    with st.expander('打开本机方案或导入完整方案包'):
        saved=archive.list_saved(root)
        if saved:
            by_id={x['archive_id']:x for x in saved}
            sid=st.selectbox('本机已保存方案',list(by_id),format_func=lambda x:by_id[x]['name']+' · '+by_id[x]['created_utc'][:19],key='saved_archive_choice')
            if st.button('打开选中方案',key='open_saved_design'):
                try:activate(archive.load_saved(root,sid));st.rerun()
                except (ValueError,OSError) as exc:st.error(str(exc))
        else:st.caption('尚无本机方案。完成输入或计算后，点击下方“保存到本机”。')
        upload=st.file_uploader('导入完整方案包（.wdh）',type=['wdh'],key='archive_upload_'+str(st.session_state.get('workspace_revision',0)))
        if st.button('导入并打开方案包',key='import_design_bundle',disabled=upload is None):
            try:
                data=upload.getvalue();parsed=archive.read_bundle(data);archive.save_bundle(data,root)
                activate(parsed);st.rerun()
            except (ValueError,OSError) as exc:st.error(str(exc))
    opened=st.session_state.get('opened_archive')
    if opened:
        m=opened['manifest']
        st.info('已打开存档：'+m['name']+'。需求已载入下方；存档结果可在下面查看，重新运行会生成新记录。')
        if opened['migration_required']:st.warning('存档需求已迁移，请重新核对确认；历史结果保留原版本。')
        elif not opened['current_source_matches']:st.warning('存档使用的模型或软件与当前版本不同；历史结果仅供查阅。')
        with st.expander('查看存档结果和导出报告'):
            if not opened['records']:st.write('这是需求草案，尚无计算结果。')
            for r in opened['records'][:1]:
                st.caption('历史运行 '+r['run_id']+' · V'+r['version'])
                labels={**STATUS,'compared_with_limits':'三个方案已比较（概念模型）','comparison_incomplete':'比较未完整通过，保留各方案诊断'}
                st.write(labels.get(r['status'],r['status']))
                s=r.get('summary',{})
                if r['mode']=='overall_comparison' and 'cards' in s:
                    st.dataframe([{'方案':c['name'],'状态':c['status_label'],**{f'{METRICS[k][0]}（{METRICS[k][1]}）':v for k,v in c['metrics'].items()}} for c in s['cards']],hide_index=True)
                elif 'geometry' in s:
                    st.dataframe([{'指标':'设计起飞重量 kg','值':s['design_mtow_kg']},
                                  {'指标':'翼面积 m²','值':s['geometry']['wing_area_m2']},
                                  {'指标':'安装功率 kW','值':s['power']['installed_power_w']/1000},
                                  {'指标':'总可用油 kg','值':s['mission']['block_fuel_kg']}],hide_index=True)
                for d in s.get('diagnostics',[]):st.write(d)
                if r.get('error'):st.error(r['error'])
            for filename in ('report.html','report.md'):
                if 'reports/'+filename in opened['files']:
                    st.download_button('下载存档报告 '+filename,opened['files']['reports/'+filename],filename,key='archive_'+filename)
            for r in opened.get('geometry_records',[]):
                from .geometry_ui import show_files
                prefix='runs/'+r['run_id']+'/'
                show_files(r,{n[len(prefix):]:b for n,b in opened['files'].items() if n.startswith(prefix)},'archived_geometry')
        p=opened['project']
        return p.projects[0] if isinstance(p,ComparisonRequest) else p
    return DesignProject()


def save_controls(project,root,record=None,key='design'):
    valid=record is not None and record.get('definition_sha256')==project.definition_hash()
    plans=project.projects if isinstance(project,ComparisonRequest) else (project,)
    valid=valid and all(p.confirmation_sha256==p.definition_hash() for p in plans)
    valid=valid and (Path(root)/'runs'/record['run_id']/'result.json').is_file() if valid else False
    chosen=record if valid else None
    geometry=st.session_state.get('aircraft_geometry_result') if key=='design' else None
    if not chosen or not geometry or geometry.get('parent_run_id')!=chosen['run_id']:geometry=None
    st.caption('保存内容：需求、假设'+('、本次计算结果和报告'+('、全机几何。' if geometry else '。') if chosen else '（草案，无当前有效计算结果）。'))
    try:
        data=archive.build_bundle(project,root,chosen,geometry)
        if st.button('保存'+('三方案' if key=='comparison' else '方案')+'到本机',key=key+'_save_local'):
            index=archive.save_bundle(data,root)
            st.session_state['archive_saved_note']='已保存 '+index['name']+'；可在页面顶部打开，原方案不会被覆盖。'
            st.rerun()
        st.download_button('导出完整'+('三方案包' if key=='comparison' else '方案包')+'（需求与结果）',data,key+'.wdh',key=key+'_bundle_download')
        if chosen:
            path=Path(root)/'runs'/chosen['run_id']/'report.html'
            if path.is_file():st.download_button('导出可打印'+('比较' if key=='comparison' else '总体')+'报告',path.read_bytes(),key+'-report.html',key=key+'_html_report')
        if 'archive_saved_note' in st.session_state:st.success(st.session_state['archive_saved_note'])
    except (ValueError,OSError) as exc:st.error('方案保存检查失败：'+str(exc))
