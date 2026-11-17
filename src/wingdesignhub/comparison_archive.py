from .archive_evidence import check_packaged_native
"""Bounded dependency closure for portable enhanced comparison evidence."""
import json,hashlib
from .service import get_results


def support_runs(root,children,*,verify_native=True):
    seen=set(children);result=[]
    for rid in children:
        record=get_results(root,rid,verify_native=verify_native)
        for _ in range(3):
            if record['mode']=='overall_sizing':break
            if record['mode'] not in ('overall_propulsion','overall_feedback'):raise ValueError('比较包含不支持的来源链')
            parent=get_results(root,record['parent_run_id'],verify_native=verify_native)
            if parent['definition_sha256']!=record['definition_sha256']:raise ValueError('比较来源定义不符')
            if parent['run_id'] in seen:raise ValueError('比较来源链重复或形成环')
            seen.add(parent['run_id']);result.append(parent['run_id']);record=parent
        else:raise ValueError('比较来源链过长')
    return result


def check_feedback(record,parent,files):
    from .aero_feedback import FeedbackOptions,MissionAeroTable
    from .feedback_evidence import check_native
    r=record;prefix=f'runs/{r["run_id"]}/'
    def data(name):return json.loads(files[prefix+name])
    options=data('options.json');FeedbackOptions.from_dict(options)
    if (r['mode']!='overall_feedback' or parent['mode']!='overall_sizing' or
        r['parent_run_id']!=parent['run_id'] or r['definition_sha256']!=parent['definition_sha256'] or
        data('parent_result.json')!=parent or hashlib.sha256(files[prefix+'parent_result.json']).hexdigest()!=r['parent_result_sha256'] or
        r['options']!=options):raise ValueError('方案包气动反馈来源不一致')
    check_packaged_native(files,prefix)
    s=r.get('summary',{})
    if 'aerodynamic_feedback' in s:
        audit=s['aerodynamic_feedback'];aero=MissionAeroTable.from_dict(data('aero_table.json'))
        if data('feedback_verification.json')!=audit or audit['options']!=options or aero.area!=s['geometry']['wing_area_m2']:
            raise ValueError('方案包气动反馈条件或验证不符')
        for state in data('mission_trace.json'):
            if abs(state['remaining_fuel_kg']-state['mass_kg']+aero.dry_mass)>1e-7 or abs(state['cg_x_m']-aero.cg(state['mass_kg']))>1e-10:
                raise ValueError('方案包任务质量和重心不一致')
        if abs(s['cg']['loaded_mass_kg']-aero.dry_mass-s['mission']['takeoff_fuel_kg'])>1e-6:raise ValueError('方案包任务初始质量不闭合')


def check_comparison(request,records,support,files):
    from .design_comparison import check_record,summarize_comparison
    from .coupled_archive import check_coupled
    if not records:return
    children=records[1:];all_records={r['run_id']:r for r in children+support};used=set()
    for project,child in zip(request.projects,children):
        check_record(request,project,child)
        r=child
        for _ in range(3):
            if r['mode']=='overall_sizing':break
            parent=all_records.get(r.get('parent_run_id'))
            if parent is None or parent['run_id'] in used:raise ValueError('比较来源链缺失或重复')
            used.add(parent['run_id'])
            if r['mode']=='overall_propulsion':check_coupled(r,list(all_records.values()),files)
            elif r['mode']=='overall_feedback':check_feedback(r,parent,files)
            else:raise ValueError('比较来源类型无效')
            r=parent
        else:raise ValueError('比较来源链过长')
    if used!={r['run_id'] for r in support}:raise ValueError('比较包含无关来源记录')
    if 'summary' in records[0] and summarize_comparison(request,children)!=records[0]['summary']:
        raise ValueError('方案卡或比较结果与真实子运行不一致')
