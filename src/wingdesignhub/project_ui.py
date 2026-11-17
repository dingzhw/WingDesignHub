"""Local save/reopen workflow for non-programmers; archives remain historical evidence."""
import json
from pathlib import Path
import streamlit as st
from . import project_archive as archive
from .requirements import DesignProject
from .design_comparison import ComparisonRequest
from .design_cards import STATUS,METRICS


@st.cache_data(max_entries=2,show_spinner=False)
def feedback_bundle(project,root,record,geometry,aero,trim,drag,feedback,source_token,propulsion=None,coupled=None,current_run_id=None):
    return archive.build_bundle(project,root,record,geometry,aero,trim,drag,feedback,propulsion,coupled,current_run_id=current_run_id)


@st.cache_data(max_entries=1,show_spinner=False)
def comparison_bundle(project,root,record,evidence_token):
    return archive.build_bundle(project,root,record)


def activate(parsed=None):
    st.session_state.pop('workspace_project',None)
    st.session_state.pop('job_comparison_request',None)
    for key in ('sizing_result','comparison_result','design_intent_result','archive_saved_note','aircraft_geometry_result','aircraft_aero_result','aircraft_trim_result','aircraft_drag_result','aero_feedback_result','propulsion_result','coupled_result'):
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
        elif not opened['current_source_matches']:st.warning('存档包含与当前版本不同的来源记录，按原版本查阅；推进复算会单独核查冻结气动接口。')
        with st.expander('查看存档结果和导出报告'):
            if not opened['records']:st.write('这是需求草案，尚无计算结果。')
            selected=m.get('current_run_id')
            current=[r for r in opened['records']+opened.get('feedback_records',[])+opened.get('coupled_records',[]) if r['run_id']==selected]
            for r in current or opened['records'][:1]:
                st.caption('历史运行 '+r['run_id']+' · V'+r['version'])
                labels={**STATUS,'compared_with_limits':'三个方案已比较（概念模型）','comparison_incomplete':'比较未完整通过，保留各方案诊断'}
                st.write(labels.get(r['status'],r['status']))
                s=r.get('summary',{})
                if r['mode']=='overall_comparison' and 'cards' in s:
                    st.caption(s.get('analysis_label','初步总体（概念气动与推进）'))
                    st.dataframe([{'方案':c['name'],'状态':c['status_label'],**{f'{METRICS[k][0]}（{METRICS[k][1]}）':v for k,v in c['metrics'].items()}} for c in s['cards']],hide_index=True)
                    for c in s['cards']:
                        if c.get('enhanced'):st.write(c['name']);st.json(c['enhanced'])
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
            for r in opened.get('aero_records',[]):
                from .aero_ui import show_files
                prefix='runs/'+r['run_id']+'/'
                show_files(r,{n[len(prefix):]:b for n,b in opened['files'].items() if n.startswith(prefix)},'archived_aero')
            for r in opened.get('trim_records',[]):
                from .trim_ui import show_files
                prefix='runs/'+r['run_id']+'/'
                show_files(r,{n[len(prefix):]:b for n,b in opened['files'].items() if n.startswith(prefix)},'archived_trim')
            for r in opened.get('drag_records',[]):
                from .drag_ui import show_files
                prefix='runs/'+r['run_id']+'/'
                show_files(r,{n[len(prefix):]:b for n,b in opened['files'].items() if n.startswith(prefix)},'archived_drag')
            for r in opened.get('feedback_records',[]):
                from .feedback_ui import show_files
                prefix='runs/'+r['run_id']+'/'
                show_files(r,{n[len(prefix):]:b for n,b in opened['files'].items() if n.startswith(prefix)},'archived_feedback')
                from .propulsion_ui import render as propulsion_render
                propulsion_render(opened['project'],root,r,'archive_propulsion',archived=opened)
            for r in opened.get('propulsion_records',[]):
                from .propulsion_ui import show_files
                prefix='runs/'+r['run_id']+'/'
                show_files(r,{n[len(prefix):]:b for n,b in opened['files'].items() if n.startswith(prefix)},'archived_propulsion_result')
            for r in opened.get('coupled_records',[]):
                from .coupled_ui import show_files
                prefix='runs/'+r['run_id']+'/'
                show_files(r,{n[len(prefix):]:b for n,b in opened['files'].items() if n.startswith(prefix)},'archived_coupled_result')
            if opened['manifest']['kind']=='design' and opened['records']:
                from .coupled_ui import render as coupled_render
                seeds=opened.get('feedback_records') or opened['records']
                coupled_render(opened['project'],root,seeds[0],'archive_coupled',archived=opened)
        p=opened['project']
        return p.projects[0] if isinstance(p,ComparisonRequest) else p
    return st.session_state.get('workspace_project',DesignProject())


def save_controls(project,root,record=None,key='design'):
    valid=record is not None and record.get('definition_sha256')==project.definition_hash()
    plans=project.projects if isinstance(project,ComparisonRequest) else (project,)
    valid=valid and all(p.confirmation_sha256==p.definition_hash() for p in plans)
    valid=valid and (Path(root)/'runs'/record['run_id']/'result.json').is_file() if valid else False
    chosen=record if valid else None
    geometry=st.session_state.get('aircraft_geometry_result') if key=='design' else None
    if not chosen or not geometry or geometry.get('parent_run_id')!=chosen['run_id']:geometry=None
    aero=st.session_state.get('aircraft_aero_result') if key=='design' else None
    if not geometry or not aero or aero.get('parent_run_id')!=geometry['run_id']:aero=None
    trim=st.session_state.get('aircraft_trim_result') if key=='design' else None
    if not geometry or not trim or trim.get('parent_run_id')!=geometry['run_id']:trim=None
    drag=st.session_state.get('aircraft_drag_result') if key=='design' else None
    if not trim or not drag or drag.get('parent_run_id')!=trim['run_id']:drag=None
    st.caption('保存内容：需求、假设'+('、本次计算结果和报告'+('、全机几何'+('、气动与条带载荷。' if aero else '。') if geometry else '。') if chosen else '（草案，无当前有效计算结果）。'))
    try:
        if trim:st.caption('同时保存纵向配平、工况台账及全部迭代原始记录。')
        if drag:st.caption('同时保存阻力账目、极曲线、面积和诊断记录。')
        feedback=st.session_state.get('aero_feedback_result') if key=='design' else None
        if not chosen or not feedback or feedback.get('parent_run_id')!=chosen['run_id']:feedback=None
        if feedback:st.caption('同时保存气动驱动任务、总体反馈结果及原生计算证据包。')
        propulsion=st.session_state.get('propulsion_result') if key=='design' else None
        if not feedback or not propulsion or propulsion.get('parent_run_id')!=feedback['run_id']:propulsion=None
        if propulsion:st.caption('同时保存发动机/螺旋桨图谱、推进任务复算及原始输出。')
        coupled=st.session_state.get('coupled_result') if key=='design' else None
        if not chosen or not coupled or coupled.get('parent_run_id') not in [chosen['run_id'],*( [feedback['run_id']] if feedback else [])]:coupled=None
        if coupled:st.caption('同时保存推进闭环、发动机/携油/几何联动及全部原生计算证据。')
        selected=st.session_state.get('current_design_run_'+project.definition_hash()) if key=='design' else None
        if selected not in [r['run_id'] for r in (chosen,feedback,coupled) if r]:selected=chosen['run_id'] if chosen else None
        if feedback or coupled:
            # Verify mutable disk inputs before reusing the large portable byte stream.
            from .service import get_results
            from .geometry_service import source_hashes
            for r in (chosen,geometry,aero,trim,drag,feedback,propulsion,coupled):
                if r is not None and get_results(root,r['run_id'])!=r:raise ValueError('当前运行记录已改变')
            data=feedback_bundle(project,str(root),chosen,geometry,aero,trim,drag,feedback,source_hashes(),propulsion,coupled,selected)
        elif chosen and isinstance(project,ComparisonRequest) and project.analysis_model=='coupled':
            from .comparison_archive import support_runs
            from .service import get_results
            children=chosen.get('child_runs',[])
            records=[get_results(root,rid) for rid in [chosen['run_id'],*children,*support_runs(root,children)]]
            if records[0]!=chosen:raise ValueError('当前比较记录已改变')
            data=comparison_bundle(project,str(root),chosen,records)
        else:data=archive.build_bundle(project,root,chosen,geometry,aero,trim,drag)
        if st.button('保存'+('三方案' if key=='comparison' else '方案')+'到本机',key=key+'_save_local'):
            index=archive.save_bundle(data,root)
            st.session_state['archive_saved_note']='已保存 '+index['name']+'；可在页面顶部打开，原方案不会被覆盖。'
            st.rerun()
        st.download_button('导出完整'+('三方案包' if key=='comparison' else '方案包')+'（需求与结果）',data,key+'.wdh',key=key+'_bundle_download')
        if chosen:
            path=Path(root)/'runs'/selected/'report.html'
            if path.is_file():st.download_button('导出可打印'+('比较' if key=='comparison' else '总体')+'报告',path.read_bytes(),key+'-report.html',key=key+'_html_report')
        if 'archive_saved_note' in st.session_state:st.success(st.session_state['archive_saved_note'])
    except (ValueError,OSError) as exc:st.error('方案保存检查失败：'+str(exc))
