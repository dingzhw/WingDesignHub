"""Portable, inert project bundles; loading never executes or overwrites a run."""
from datetime import datetime,timezone
from io import BytesIO
from pathlib import Path,PurePosixPath
from uuid import uuid4,UUID
from zipfile import ZipFile,ZIP_DEFLATED,BadZipFile
from importlib.metadata import version,PackageNotFoundError
import hashlib
import json
from . import __version__
from .requirements import DesignProject
from .design_comparison import ComparisonRequest
from .service import get_results
from .archive_evidence import check_packaged_native

MAX_BYTES=1024*1024*1024  # three iterative native designs plus bounded source runs
MAX_FILES=1024  # bounded trim evaluations include their original commands and outputs


def digest(data):return hashlib.sha256(data).hexdigest()


def encoded(value):return (json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+'\n').encode('utf-8')


def safe_name(name):
    p=PurePosixPath(name)
    if not isinstance(name,str) or not name or '\\' in name or ':' in name or p.is_absolute() or '..' in p.parts or p.as_posix()!=name:
        raise ValueError('方案包含非法路径')
    return name


def raw_definition(data,kind):
    # Preserve the original schema when checking archived records; migration is separate.
    if kind=='comparison':
        obj={'purpose':data['purpose'],'schema_version':data['schema_version'],
             'definitions':[raw_definition(p,'design') for p in data['projects']]}
        if data['schema_version']==2:
            request=ComparisonRequest.from_dict(data)
            obj.update(analysis_model=request.analysis_model,analysis_options=request.options_dict())
        return digest(json.dumps(obj,sort_keys=True).encode())
    obj=dict(data);obj.pop('confirmation_sha256',None)
    def normalize(x):
        if isinstance(x,dict):return {k:normalize(v) for k,v in x.items()}
        return float(x) if type(x) in (int,float) else x
    return digest(json.dumps(normalize(obj),ensure_ascii=False,sort_keys=True,allow_nan=False).encode())


def build_bundle(project,root,record=None,geometry_record=None,aero_record=None,trim_record=None,drag_record=None,feedback_record=None,propulsion_record=None,coupled_record=None,*,current_run_id=None,profile="full"):
    if profile not in ('full','portable'):raise ValueError('未知归档层级')
    detached={}
    kind='comparison' if isinstance(project,ComparisonRequest) else 'design'
    project.validate() if kind=='comparison' else project.check_schema()
    source=project.to_dict();files={'project.json':encoded(source)};ids=[];geometry_ids=[];aero_ids=[];trim_ids=[];drag_ids=[];feedback_ids=[]
    propulsion_ids=[];coupled_ids=[];support_ids=[]
    if coupled_record is not None and (record is None or kind!='design'):raise ValueError('推进闭环须与来源总体一起保存')
    if propulsion_record is not None and feedback_record is None:raise ValueError('推进结果须与来源气动反馈一起保存')
    if feedback_record is not None and (record is None or kind!='design'):raise ValueError('气动反馈须与来源总体一起保存')
    if drag_record is not None and trim_record is None:raise ValueError('阻力结果须与来源配平一起保存')
    if trim_record is not None and geometry_record is None:raise ValueError('配平结果须与来源几何一起保存')
    if aero_record is not None and geometry_record is None:raise ValueError('气动结果须与来源几何一起保存')
    if geometry_record is not None and (record is None or kind!='design'):
        raise ValueError('全机几何须与其单方案总体结果一起保存')
    if record is not None:
        actual=get_results(root,record['run_id'],verify_native=profile=="full")
        if actual!=record:raise ValueError('待保存结果与实际运行记录不符')
        expected='overall_comparison' if kind=='comparison' else 'overall_sizing'
        if actual['mode']!=expected or actual['definition_sha256']!=project.definition_hash():
            raise ValueError('结果属于其他定义，请先重新计算或仅保存需求草案')
        if kind=='comparison' and any(p.confirmation_sha256!=p.definition_hash() for p in project.projects):
            raise ValueError('当前比较尚未确认，不能附上旧计算结果')
        if kind=='design' and project.confirmation_sha256!=project.definition_hash():
            raise ValueError('当前需求尚未确认，不能附上旧计算结果')
        ids=[actual['run_id'],*actual.get('child_runs',[])]
        if kind=='comparison' and project.analysis_model=='coupled':
            from .comparison_archive import support_runs
            support_ids=support_runs(root,ids[1:],verify_native=profile=="full")
        if geometry_record is not None:
            gr=get_results(root,geometry_record['run_id'],verify_native=profile=="full")
            if gr!=geometry_record or gr.get('mode')!='aircraft_geometry' or gr.get('parent_run_id')!=actual['run_id']:
                raise ValueError('几何结果与总体运行不匹配')
            geometry_ids=[gr['run_id']]
        if aero_record is not None:
            ar=get_results(root,aero_record['run_id'],verify_native=profile=="full")
            if ar!=aero_record or ar.get('mode')!='aircraft_aero' or ar.get('parent_run_id')!=gr['run_id']:
                raise ValueError('气动结果与几何运行不匹配')
            aero_ids=[ar['run_id']]
        if trim_record is not None:
            tr=get_results(root,trim_record['run_id'],verify_native=profile=="full")
            if tr!=trim_record or tr.get('mode')!='aircraft_trim' or tr.get('parent_run_id')!=gr['run_id']:
                raise ValueError('配平结果与几何运行不匹配')
            trim_ids=[tr['run_id']]
        if drag_record is not None:
            dr=get_results(root,drag_record['run_id'],verify_native=profile=="full")
            if dr!=drag_record or dr.get('mode')!='aircraft_drag' or dr.get('parent_run_id')!=tr['run_id']:
                raise ValueError('阻力结果与配平运行不匹配')
            drag_ids=[dr['run_id']]
        if feedback_record is not None:
            fr=get_results(root,feedback_record['run_id'],verify_native=profile=="full")
            if fr!=feedback_record or fr.get('mode')!='overall_feedback' or fr.get('parent_run_id')!=actual['run_id']:
                raise ValueError('气动反馈与总体运行不匹配')
            feedback_ids=[fr['run_id']]
        if propulsion_record is not None:
            pr=get_results(root,propulsion_record['run_id'],verify_native=profile=="full")
            if pr!=propulsion_record or pr.get('mode')!='propulsion_replay' or pr.get('parent_run_id')!=fr['run_id']:
                raise ValueError('推进结果与气动反馈运行不匹配')
            propulsion_ids=[pr['run_id']]
        if coupled_record is not None:
            cr=get_results(root,coupled_record['run_id'],verify_native=profile=="full")
            if cr!=coupled_record or cr.get('mode')!='overall_propulsion' or cr.get('parent_run_id') not in [actual['run_id'],*feedback_ids]:
                raise ValueError('推进闭环与来源总体或气动反馈不匹配')
            coupled_ids=[cr['run_id']]
        for rid in ids+geometry_ids+aero_ids+trim_ids+drag_ids+feedback_ids+propulsion_ids+coupled_ids+support_ids:
            r=get_results(root,rid,verify_native=profile=="full");work=Path(root)/'runs'/rid
            for name in ['result.json',*r.get('artifact_hashes',{})]:
                safe_name(name);p=(work/name).resolve()
                if not p.is_relative_to(work.resolve()):raise ValueError('运行产物路径越界')
                if profile=='portable' and name=='native_evidence.zip':
                    detached[f'runs/{rid}/{name}']=r['artifact_hashes'][name]
                else:files[f'runs/{rid}/{name}']=p.read_bytes()
        for filename in ('report.html','report.md'):
            p=Path(root)/'runs'/ids[0]/filename
            if p.is_file():files['reports/'+filename]=p.read_bytes()
    name=source['name'] if kind=='design' else source['projects'][0]['name']+' 等三方案'
    current_run_id=current_run_id or (ids[0] if ids else None)
    if current_run_id is not None and current_run_id not in ids+feedback_ids+coupled_ids:
        raise ValueError('当前运行必须属于本方案的总体结果')
    if current_run_id:
        for filename in ('report.html','report.md'):
            p=Path(root)/'runs'/current_run_id/filename
            if p.is_file():files['reports/'+filename]=p.read_bytes()
    manifest={'bundle_schema':2 if profile=='portable' else 1,'profile':profile,'detached_evidence':detached,'kind':kind,'name':name,'software_version':__version__,
              'created_utc':datetime.now(timezone.utc).isoformat(),'run_ids':ids,'geometry_run_ids':geometry_ids,'aero_run_ids':aero_ids,'trim_run_ids':trim_ids,'drag_run_ids':drag_ids,'feedback_run_ids':feedback_ids,'propulsion_run_ids':propulsion_ids,'coupled_run_ids':coupled_ids,
              'definition_sha256':project.definition_hash(),'files':{n:digest(b) for n,b in files.items()},
              'support_run_ids':support_ids,
              'current_run_id':current_run_id,
              'integrity_scope':'SHA-256 detects damaged contents; this is not a signed authenticity certificate'}
    stream=BytesIO()
    with ZipFile(stream,'w',ZIP_DEFLATED) as z:
        for name,data in files.items():z.writestr(name,data)
        z.writestr('manifest.json',encoded(manifest))
    result=stream.getvalue();read_bundle(result);return result


def read_bundle(data):
    """Check all members in memory, with no extraction and no HTML execution."""
    if not isinstance(data,bytes) or len(data)>MAX_BYTES:raise ValueError('方案包大小超出 1024 MB 限制')
    try:
        with ZipFile(BytesIO(data)) as z:
            infos=z.infolist();names=[safe_name(i.filename) for i in infos]
            if len(names)>MAX_FILES or len(names)!=len(set(names)) or 'manifest.json' not in names:
                raise ValueError('方案包文件数量、重复项或清单无效')
            if sum(i.file_size for i in infos)>MAX_BYTES or any(i.flag_bits&1 or i.is_dir() or (i.external_attr>>16)&0o170000==0o120000 for i in infos):
                raise ValueError('方案包解压大小或文件类型不支持')
            files={i.filename:z.read(i) for i in infos}
    except (BadZipFile,RuntimeError,EOFError) as exc:raise ValueError('方案包无法读取或已损坏') from exc
    try:
        manifest=json.loads(files.pop('manifest.json'))
        if type(manifest.get('bundle_schema')) is not int or manifest['bundle_schema'] not in (1,2):raise ValueError('方案包版本不支持')
        if manifest['kind'] not in ('design','comparison'):raise ValueError('方案包类型无效')
        if set(manifest['files'])!=set(files) or any(digest(b)!=manifest['files'][n] for n,b in files.items()):
            raise ValueError('方案包文件完整性检查失败')
        from .archive_evidence import EvidenceFiles
        detached=manifest.get('detached_evidence',{})
        if not isinstance(detached,dict) or (detached and manifest['bundle_schema']!=2):raise ValueError('归档证据层级无效')
        files=EvidenceFiles(files,detached)
        source=json.loads(files['project.json']);kind=manifest['kind']
        project=ComparisonRequest.from_dict(source) if kind=='comparison' else DesignProject.from_dict(source)
        if raw_definition(source,kind)!=manifest['definition_sha256']:raise ValueError('方案包需求哈希不符')
        records=[];geometry_records=[];aero_records=[];trim_records=[];drag_records=[];ids=manifest['run_ids'];geometry_ids=manifest.get('geometry_run_ids',[]);aero_ids=manifest.get('aero_run_ids',[]);trim_ids=manifest.get('trim_run_ids',[]);drag_ids=manifest.get('drag_run_ids',[])
        if len(set(ids))!=len(ids) or len(ids)>(4 if kind=='comparison' else 1):raise ValueError('方案包运行列表无效')
        if (len(geometry_ids)>1 or set(geometry_ids)&set(ids) or
                (geometry_ids and (kind!='design' or len(ids)!=1))):raise ValueError('方案包几何运行列表无效')
        if len(aero_ids)>1 or set(aero_ids)&set(ids+geometry_ids) or (aero_ids and not geometry_ids):
            raise ValueError('方案包气动运行列表无效')
        if len(trim_ids)>1 or set(trim_ids)&set(ids+geometry_ids+aero_ids) or (trim_ids and not geometry_ids):
            raise ValueError('方案包配平运行列表无效')
        if len(drag_ids)>1 or set(drag_ids)&set(ids+geometry_ids+aero_ids+trim_ids) or (drag_ids and not trim_ids):
            raise ValueError('方案包阻力运行列表无效')
        feedback_ids=manifest.get('feedback_run_ids',[]);feedback_records=[]
        if len(feedback_ids)>1 or set(feedback_ids)&set(ids+geometry_ids+aero_ids+trim_ids+drag_ids) or (feedback_ids and (kind!='design' or len(ids)!=1)):
            raise ValueError('方案包气动反馈列表无效')
        propulsion_ids=manifest.get('propulsion_run_ids',[]);propulsion_records=[]
        if len(propulsion_ids)>1 or set(propulsion_ids)&set(ids+geometry_ids+aero_ids+trim_ids+drag_ids+feedback_ids) or (propulsion_ids and not feedback_ids):
            raise ValueError('方案包推进运行列表无效')
        coupled_ids=manifest.get('coupled_run_ids',[]);coupled_records=[]
        if len(coupled_ids)>1 or set(coupled_ids)&set(ids+geometry_ids+aero_ids+trim_ids+drag_ids+feedback_ids+propulsion_ids) or (coupled_ids and (kind!='design' or len(ids)!=1)):
            raise ValueError('方案包推进闭环运行列表无效')
        support_ids=manifest.get('support_run_ids',[]);support_records=[]
        other_ids=ids+geometry_ids+aero_ids+trim_ids+drag_ids+feedback_ids+propulsion_ids+coupled_ids
        if (len(support_ids)>6 or len(set(support_ids))!=len(support_ids) or set(support_ids)&set(other_ids) or
            (support_ids and (kind!='comparison' or project.analysis_model!='coupled'))):raise ValueError('比较来源记录列表无效')
        for rid in other_ids+support_ids:
            if UUID(rid).hex!=rid:raise ValueError('方案包运行编号无效')
            prefix=f'runs/{rid}/';r=json.loads(files[prefix+'result.json'])
            if r['run_id']!=rid:raise ValueError('方案包运行身份不符')
            for name,h in r['artifact_hashes'].items():
                safe_name(name)
                if prefix+name in files.detached:
                    if files.detached[prefix+name]!=h:raise ValueError('分离证据与原记录哈希不符')
                elif digest(files[prefix+name])!=h:raise ValueError('方案包运行产物哈希不符')
            if digest(files[prefix+'input.json'])!=r['input_hash']:raise ValueError('方案包运行输入哈希不符')
            run_kind='comparison' if r['mode']=='overall_comparison' else 'design'
            if raw_definition(json.loads(files[prefix+'input.json']),run_kind)!=r['definition_sha256']:
                raise ValueError('方案包运行输入与定义不符')
            summary_name='comparison.json' if run_kind=='comparison' else 'summary.json'
            if prefix+summary_name in files and json.loads(files[prefix+summary_name])!=r.get('summary'):
                raise ValueError('方案包摘要与运行结果不符')
            (support_records if rid in support_ids else coupled_records if rid in coupled_ids else propulsion_records if rid in propulsion_ids else feedback_records if rid in feedback_ids else drag_records if rid in drag_ids else trim_records if rid in trim_ids else aero_records if rid in aero_ids else geometry_records if rid in geometry_ids else records).append(r)
        if records:
            expected='overall_comparison' if kind=='comparison' else 'overall_sizing'
            if records[0]['mode']!=expected or records[0]['definition_sha256']!=manifest['definition_sha256']:
                raise ValueError('方案包结果与需求不符')
            if records[0].get('child_runs',[])!=ids[1:]:raise ValueError('方案包子运行列表不符')
            for i,r in enumerate(records[1:]):
                expected_modes=('overall_sizing','overall_propulsion') if kind=='comparison' and project.analysis_model=='coupled' else ('overall_sizing',)
                if r['mode'] not in expected_modes or r['definition_sha256']!=raw_definition(source['projects'][i],'design'):
                    raise ValueError('方案包子运行与需求不符')
            for filename in ('report.html','report.md'):
                report_id=manifest.get('current_run_id') or ids[0]
                if 'reports/'+filename in files and files['reports/'+filename]!=files[f'runs/{report_id}/{filename}']:
                    raise ValueError('方案包报告与运行产物不一致')
        for r in geometry_records:
            prefix=f'runs/{r["run_id"]}/';parent=records[0]
            contract=json.loads(files[prefix+'geometry_contract.json'])
            snapshot=files[prefix+'parent_result.json']
            if (r['mode']!='aircraft_geometry' or r['parent_run_id']!=parent['run_id'] or
                    r['definition_sha256']!=parent['definition_sha256'] or
                    digest(snapshot)!=r['parent_result_sha256'] or json.loads(snapshot)!=parent or
                    contract['parent_run_id']!=parent['run_id'] or contract['parent_input_hash']!=parent['input_hash'] or
                    contract['definition_sha256']!=parent['definition_sha256'] or contract['options']!=r['options']):
                raise ValueError('方案包几何来源与总体运行不符')
            if r['status']=='geometry_checked_with_limits':
                interface=json.loads(files[prefix+'aerodynamic_geometry.json'])
                if (interface['references']!=contract['references'] or r['summary']['references']!=contract['references'] or
                        interface['geometry_file_sha256']!=digest(files[prefix+'aircraft.vsp3']) or
                        interface['degen_file_sha256']!=digest(files[prefix+'airframe_DegenGeom.csv'])):
                    raise ValueError('方案包气动接口与几何文件不一致')
        for r in aero_records:
            prefix=f'runs/{r["run_id"]}/';parent=geometry_records[0];gp=f'runs/{parent["run_id"]}/'
            contract=json.loads(files[prefix+'aero_contract.json']);snapshot=files[prefix+'parent_result.json']
            interface=json.loads(files[prefix+'aerodynamic_geometry.json'])
            if (r['mode']!='aircraft_aero' or r['parent_run_id']!=parent['run_id'] or
                r['sizing_run_id']!=records[0]['run_id'] or r['definition_sha256']!=parent['definition_sha256'] or
                digest(snapshot)!=r['parent_result_sha256'] or json.loads(snapshot)!=parent or
                files[prefix+'aerodynamic_geometry.json']!=files[gp+'aerodynamic_geometry.json'] or
                contract['geometry_run_id']!=parent['run_id'] or contract['sizing_run_id']!=records[0]['run_id'] or
                contract['surfaces']!=interface['surfaces'] or contract['references']!=interface['references'] or
                contract['options']!=r['options']):raise ValueError('方案包气动来源不一致')
            if r['status']=='aero_checked_with_limits' and (r['summary']['references']!=contract['references'] or
                r['summary']['flow']!=contract['flow'] or json.loads(files[prefix+'trim_interface.json'])!=r['summary']['trim']):
                raise ValueError('方案包气动工况或配平接口不一致')
        for r in trim_records:
            from .aircraft_trim import make_trim_contract
            prefix=f'runs/{r["run_id"]}/';parent=geometry_records[0];gp=f'runs/{parent["run_id"]}/'
            contract=json.loads(files[prefix+'trim_contract.json']);snapshot=files[prefix+'parent_result.json']
            interface=json.loads(files[prefix+'aerodynamic_geometry.json'])
            sizing=json.loads(files[prefix+'sizing_summary.json'])
            if (r['mode']!='aircraft_trim' or r['parent_run_id']!=parent['run_id'] or r['sizing_run_id']!=records[0]['run_id'] or
                r['definition_sha256']!=parent['definition_sha256'] or digest(snapshot)!=r['parent_result_sha256'] or json.loads(snapshot)!=parent or
                files[prefix+'aerodynamic_geometry.json']!=files[gp+'aerodynamic_geometry.json'] or sizing!=records[0]['summary']):
                raise ValueError('方案包配平来源不一致')
            expected=make_trim_contract(interface,project,sizing,r['options'])
            for field in ('model','geometry_run_id','sizing_run_id','surfaces','references','geometry_references','coordinates','flow','options','trim_options','flight_state'):
                if contract[field]!=expected[field]:raise ValueError('方案包配平工况与来源不一致：'+field)
            if 'summary' in r:
                s=r['summary'];t=s['trim'];final=json.loads(files[prefix+'final_aero_contract.json'])
                if (s['references']!=contract['references'] or s['flow']!=final['flow'] or s['options']!=final['options'] or
                    s['flight_state']!=contract['flight_state'] or s['trim_options']!=r['options'] or
                    json.loads(files[prefix+'trim_solution.json'])!=t or json.loads(files[prefix+'flight_state.json'])!=s['flight_state'] or
                    final['flight_state']!=s['flight_state'] or final['references']!=s['references']):
                    raise ValueError('方案包配平结果与工况不一致')
                accepted=files[prefix+t['final_evaluation']+'/evaluation_contract.json']
                if json.loads(accepted)!=final:raise ValueError('方案包配平终态与实际求解工况不一致')
        for r in drag_records:
            from .aircraft_drag import make_drag_contract,finish_ledger
            prefix=f'runs/{r["run_id"]}/';parent=trim_records[0];tp=f'runs/{parent["run_id"]}/';gp=f'runs/{geometry_ids[0]}/'
            snapshot=files[prefix+'parent_result.json'];contract=json.loads(files[prefix+'drag_contract.json'])
            final=json.loads(files[prefix+'final_aero_contract.json'])
            if (r['mode']!='aircraft_drag' or r['parent_run_id']!=parent['run_id'] or r['geometry_run_id']!=geometry_ids[0] or
                    r['sizing_run_id']!=ids[0] or r['definition_sha256']!=parent['definition_sha256'] or
                    digest(snapshot)!=r['parent_result_sha256'] or json.loads(snapshot)!=parent or
                    files[prefix+'final_aero_contract.json']!=files[tp+'final_aero_contract.json'] or
                    files[prefix+'trim_strip_loads.json']!=files[tp+'strip_loads.json'] or
                    files[prefix+'aircraft.vsp3']!=files[gp+'aircraft.vsp3'] or
                    files[prefix+'geometry_contract.json']!=files[gp+'geometry_contract.json']):
                raise ValueError('方案包阻力来源与配平/几何不一致')
            if contract!=make_drag_contract(parent,final,r['options']):raise ValueError('方案包阻力工况或假设不一致')
            if 'summary' in r:
                s=r['summary'];ledger=json.loads(files[prefix+'drag_ledger.json'])
                if (s['flow']!=contract['flow'] or s['references']!=contract['references'] or s['options']!=r['options'] or
                        s['flight_state']!=contract['flight_state'] or s['ledger']!=ledger or
                        ledger!=finish_ledger(ledger['rows'],s['flow']['dynamic_pressure_pa'],s['references']['area_m2'])):
                    raise ValueError('方案包阻力账目与工况不一致')
        for r in feedback_records:
            from .aero_feedback import FeedbackOptions,MissionAeroTable
            from .feedback_evidence import check_native
            prefix=f'runs/{r["run_id"]}/';parent=records[0];snapshot=files[prefix+'parent_result.json']
            options=json.loads(files[prefix+'options.json']);FeedbackOptions.from_dict(options)
            if (r['mode']!='overall_feedback' or r['parent_run_id']!=parent['run_id'] or
                r['definition_sha256']!=parent['definition_sha256'] or json.loads(snapshot)!=parent or
                digest(snapshot)!=r['parent_result_sha256'] or r['options']!=options):raise ValueError('方案包气动反馈来源不一致')
            check_packaged_native(files,prefix)
            s=r.get('summary',{})
            if 'aerodynamic_feedback' in s:
                audit=s['aerodynamic_feedback'];aero=json.loads(files[prefix+'aero_table.json'])
                MissionAeroTable.from_dict(aero)
                if (json.loads(files[prefix+'feedback_verification.json'])!=audit or audit['options']!=options or
                    aero['reference_area_m2']!=s['geometry']['wing_area_m2'] or not aero['no_extrapolation']):
                    raise ValueError('方案包气动反馈条件或验证不符')
                dry=aero['dry_mass_kg'];moment=aero['dry_moment_kg_m'];fuel_x=aero['fuel_x_m']
                for state in json.loads(files[prefix+'mission_trace.json']):
                    mass=state['mass_kg']
                    if (abs(state['remaining_fuel_kg']-(mass-dry))>1e-7 or
                        abs(state['cg_x_m']-(moment+(mass-dry)*fuel_x)/mass)>1e-10):raise ValueError('方案包任务质量和重心不一致')
                if abs(s['cg']['loaded_mass_kg']-dry-s['mission']['takeoff_fuel_kg'])>1e-6:raise ValueError('方案包任务初始质量不闭合')
        for r in propulsion_records:
            from .propulsion_model import PropulsionOptions,PropellerMap
            prefix=f'runs/{r["run_id"]}/';parent=feedback_records[0];pp=f'runs/{parent["run_id"]}/'
            options=json.loads(files[prefix+'options.json']);PropulsionOptions.from_dict(options)
            snapshot=files[prefix+'parent_result.json']
            if (r['mode']!='propulsion_replay' or r['parent_run_id']!=parent['run_id'] or r['definition_sha256']!=parent['definition_sha256'] or
                json.loads(snapshot)!=parent or digest(snapshot)!=r['parent_result_sha256'] or options!=r['options']):raise ValueError('方案包推进来源不符')
            for name in ('aero_table.json','summary.json','feedback_verification.json'):
                if files[prefix+'source_'+name]!=files[pp+name]:raise ValueError('方案包冻结气动输入不符')
            if files[prefix+'geometry_contract.json']!=files[pp+'final_geometry/geometry_contract.json']:raise ValueError('方案包推进几何不符')
            check_packaged_native(files,prefix)
            if 'summary' in r:
                s=r['summary'];table=MissionAeroTable.from_dict(json.loads(files[prefix+'source_aero_table.json']))
                prop=PropellerMap(json.loads(files[prefix+'propeller_map.json']))
                if prop.data['options']!=options or s['reoptimized'] or s['initial_mass_kg']!=parent['summary']['cg']['loaded_mass_kg']:
                    raise ValueError('方案包固定构型条件不符')
                for point in json.loads(files[prefix+'mission_trace.json']):
                    if abs(point['cg_x_m']-table.cg(point['mass_kg']))>1e-10 or abs(point['remaining_fuel_kg']-point['mass_kg']+table.dry_mass)>1e-7:
                        raise ValueError('方案包推进任务质量或CG不符')
        from .coupled_archive import check_coupled
        for r in coupled_records:check_coupled(r,records+feedback_records,files)
        if kind=='comparison' and project.analysis_model=='coupled':
            from .comparison_archive import check_comparison
            check_comparison(project,records,support_records,files)
        expected_detached={f'runs/{r["run_id"]}/native_evidence.zip' for r in records+feedback_records+propulsion_records+coupled_records+support_records if 'native_evidence.zip' in r.get('artifact_hashes',{})}
        if not set(files.detached)<=expected_detached:raise ValueError('存在无关分离证据')
        current={p.relative_to(Path(__file__).parent).as_posix():digest(p.read_bytes()) for p in Path(__file__).parent.rglob('*.py')}
        all_records=records+geometry_records+aero_records+trim_records+drag_records+feedback_records+propulsion_records+coupled_records+support_records
        selected=manifest.get('current_run_id',ids[0] if ids else None)
        if selected is not None and selected not in ids+feedback_ids+coupled_ids:raise ValueError('存档当前总体运行无效')
        compatible=all(r.get('version')==__version__ and r.get('source_hashes')==current for r in all_records)
        for r in all_records:
            for package,recorded in r.get('summary',{}).get('versions',{}).items():
                try:compatible=compatible and version(package)==recorded
                except PackageNotFoundError:compatible=False
        return {'evidence_status':'detached_not_verified' if files.detached else 'embedded_verified','manifest':manifest,'input':source,'project':project,'records':records,'geometry_records':geometry_records,'aero_records':aero_records,'trim_records':trim_records,'drag_records':drag_records,'feedback_records':feedback_records,'propulsion_records':propulsion_records,'coupled_records':coupled_records,'files':files,
                'migration_required':project.definition_hash()!=manifest['definition_sha256'],
                'support_records':support_records,
                'current_source_matches':compatible,'bundle_sha256':digest(data)}
    except (KeyError,TypeError,UnicodeError,json.JSONDecodeError,AttributeError) as exc:
        raise ValueError('方案包清单或记录格式无效') from exc


def save_bundle(data,root):
    parsed=read_bundle(data);directory=Path(root)/'local'/'projects';directory.mkdir(parents=True,exist_ok=True)
    identity={k:v for k,v in parsed['manifest'].items() if k!='created_utc'}
    fingerprint=digest(encoded(identity))
    for saved in list_saved(root):
        if saved.get('content_fingerprint')==fingerprint:
            old=load_saved(root,saved['archive_id'])
            if {k:v for k,v in old['manifest'].items() if k!='created_utc'}==identity:return saved
    sid=uuid4().hex;path=directory/(sid+'.wdh')
    with path.open('xb') as f:f.write(data)
    index={k:parsed['manifest'][k] for k in ('name','kind','created_utc','software_version')}
    index.update(content_fingerprint=fingerprint,archive_id=sid,bundle_sha256=digest(data),has_results=bool(parsed['records']))
    with (directory/(sid+'.json')).open('xb') as f:f.write(encoded(index))
    return index


def list_saved(root):
    rows=[]
    for p in (Path(root)/'local'/'projects').glob('*.json'):
        try:
            row=json.loads(p.read_text('utf-8'))
            if UUID(p.stem).hex!=p.stem or row['archive_id']!=p.stem:continue
            if p.with_suffix('.wdh').is_file():rows.append(row)
        except (ValueError,KeyError,TypeError):continue
    return sorted(rows,key=lambda r:r['created_utc'],reverse=True)


def load_saved(root,archive_id):
    if UUID(archive_id).hex!=archive_id:raise ValueError('本机方案编号无效')
    directory=Path(root)/'local'/'projects';data=(directory/(archive_id+'.wdh')).read_bytes()
    index=json.loads((directory/(archive_id+'.json')).read_text('utf-8'))
    if digest(data)!=index['bundle_sha256']:raise ValueError('本机方案文件完整性检查失败')
    return read_bundle(data)
