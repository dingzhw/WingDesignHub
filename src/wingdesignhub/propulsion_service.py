"""Recorded propulsion replacement on a verified, frozen aerodynamic design."""
from pathlib import Path
from dataclasses import asdict
from datetime import datetime,timezone
from uuid import uuid4
import json,math,traceback,shutil
from . import __version__
from .requirements import DesignProject,build_design_intent
from .geometry_service import source_hashes
from .service import get_results,write_json
from .adapters import sha256
from .aero_feedback import MissionAeroTable
from .propulsion_model import PropulsionOptions,EngineModel,PropulsiveFlight,propulsion_constraints,LIMITS
from .ccblade_adapter import build_map,run_batch,request_base,conditions
from .sizing_physics import mission,density,G
from .feedback_evidence import pack_native


def validate_parent(project,parent,files):
    if (parent.get('mode')!='overall_feedback' or parent.get('version') not in ('0.2.5','0.2.6','0.2.7',__version__) or
        parent.get('status')!='concept_checked_with_limits' or not parent.get('summary',{}).get('converged')):
        raise ValueError('推进复算需要V0.2.5及以后已验收的气动反馈任务')
    if build_design_intent(project)['status']!='requirements_ready' or project.definition_hash()!=parent['definition_sha256']:
        raise ValueError('需求已变化或未确认，不能使用该气动任务')
    if DesignProject.from_dict(json.loads(files['input.json'])).definition_hash()!=project.definition_hash():raise ValueError('气动输入快照不符')
    if json.loads(files['summary.json'])!=parent['summary']:raise ValueError('气动摘要快照不符')
    audit=json.loads(files['feedback_verification.json'])
    if audit!=parent['summary']['aerodynamic_feedback'] or not audit.get('table_verified') or not audit.get('timestep_verified'):
        raise ValueError('来源气动表尚未通过数值检查')
    # Changes in the mission/propulsion model are intended. The native geometry,
    # trim and drag implementation producing this table must remain identical.
    current=source_hashes()
    for name in ('aircraft_geometry.py','aircraft_vsp_worker.py','aircraft_aero.py','aircraft_trim.py',
                 'aircraft_drag.py','drag_geometry_worker.py','avl_aircraft.py','xfoil_polars.py','feedback_native.py','aero_feedback.py'):
        if parent['source_hashes'].get(name)!=current[name]:raise ValueError('来源气动模型已变化，请先重新计算：'+name)
    table=MissionAeroTable.from_dict(json.loads(files['aero_table.json']))
    s=parent['summary']
    if abs(table.area-s['geometry']['wing_area_m2'])>1e-10 or abs(table.dry_mass+s['mission']['takeoff_fuel_kg']-s['cg']['loaded_mass_kg'])>1e-6:
        raise ValueError('冻结气动表与质量/面积不一致')
    return table


def verify_queries(root,work,flight,options,diameter,airfoil):
    aero=flight.aero;requests=[];predictions=[]
    for branch in aero.tables.values():
        fractions=(.5,) if len(branch['altitudes_m'])==1 else (.25,.75)
        for fraction in fractions:
            h=branch['altitudes_m'][0]+fraction*(branch['altitudes_m'][-1]-branch['altitudes_m'][0])
            mass=aero.mass_nodes[0]+.55*(aero.mass_nodes[-1]-aero.mass_nodes[0]);v=branch['speed_m_s'];roc=branch['roc_m_s']
            r=aero.query(mass,v,h,roc);t=.5*density(h)*v*v*aero.area*r['cd']+mass*G*roc/v
            pred=flight.propeller.query(t,v,h);predictions.append(pred)
            requests.append(conditions(v,h,options.rpm,pred['collective_deg']))
    request=request_base(options,diameter,airfoil);request['points']=requests
    direct=run_batch(root,work,request);rows=[]
    for prediction,actual in zip(predictions,direct['points']):
        if actual['status']!='valid':rows.append({'passed':False,'actual':actual});continue
        te=abs(actual['thrust_n']/prediction['thrust_n']-1);pe=abs(actual['shaft_power_w']/prediction['shaft_power_w']-1)
        rows.append({'passed':max(te,pe)<.02,'speed_m_s':actual['speed_m_s'],'altitude_m':actual['altitude_m'],
                     'collective_deg':actual['collective_deg'],'relative_thrust_error':te,'relative_power_error':pe,
                     'predicted':prediction,'direct':{k:actual[k] for k in ('thrust_n','torque_nm','shaft_power_w','efficiency')}})
    return rows


def perform_replay(project,root,work,parent,options,aero):
    s=parent['summary'];mass=s['cg']['loaded_mass_kg'];geo=s['geometry'];installed=s['power']['installed_power_w']
    interface=json.loads((work/'geometry_contract.json').read_text('utf-8'))
    diameter=interface['propeller']['diameter_m']
    engine=EngineModel(installed);write_json(work/'engine_model.json',engine.evidence)
    shutil.copy2(engine.map_path,work/'native/engine_map.csv')
    prop=build_map(root,work/'native/propeller',aero,diameter,options)
    write_json(work/'propeller_map.json',prop.data)
    flight=PropulsiveFlight(aero,prop,engine);schedule=s['aerodynamic_feedback']['speed_schedule_m_s']
    kwargs={'flight_model':flight,'schedule':schedule,'available_power':lambda h:engine.available(h,options.rpm)}
    baseline=mission(mass,geo,installed,project,options.integration_step_s,flight_model=aero,schedule=schedule)
    flight.capture=True
    try:updated=mission(mass,geo,installed,project,options.integration_step_s,**kwargs)
    finally:
        flight.capture=False;write_json(work/'mission_trace.json',flight.trace)
    power=propulsion_constraints(mass,geo,project,flight,schedule)
    fine=mission(mass,geo,installed,project,options.integration_step_s/2,**kwargs)
    step_error=abs(fine['block_fuel_kg']/updated['block_fuel_kg']-1)
    direct=verify_queries(root,work/'native/direct',flight,options,diameter,prop.data['airfoil'])
    checks={'propeller_table_accuracy':all(r['passed'] for r in direct),'mission_step_accuracy':step_error<.005,
            'engine_power':updated['max_power_fraction']<=1.001,
            'carried_fuel':updated['takeoff_fuel_kg']<=s['mission']['takeoff_fuel_kg']+1e-6,
            'tank_capacity':updated['block_fuel_kg']<=geo['usable_tank_capacity_kg']+1e-6}
    old_power=s['power']['installed_power_w']
    # Recompute the old required power at the exact loaded mass, rather than
    # comparing to its nearly converged design-mass iteration input.
    from .sizing_physics import constraints
    old_required=constraints(mass,geo,project,flight_model=aero,schedule=schedule)['installed_power_w']
    prop_only=mission(mass,geo,installed,project,options.integration_step_s,flight_model=flight,schedule=schedule)
    prop_only_power=constraints(mass,geo,project,flight_model=flight,schedule=schedule)['installed_power_w']
    comparison=[{'quantity':'总可用燃油','unit':'kg','legacy':baseline['block_fuel_kg'],'updated':updated['block_fuel_kg']},
        {'quantity':'需安装轴功率','unit':'W','legacy':old_required,'updated':power['installed_power_w']},
        {'quantity':'任务最大需用/可用功率','unit':'ratio','legacy':baseline['max_power_fraction'],'updated':updated['max_power_fraction']}]
    for row in comparison:row['relative_change']=row['updated']/row['legacy']-1
    summary={'status':'propulsion_checked_with_limits' if all(checks.values()) else 'constraints_not_met','reoptimized':False,
        'checks':checks,'initial_mass_kg':mass,'design_mtow_kg':s['design_mtow_kg'],'geometry':geo,
        'installed_engine_power_w':old_power,'carried_takeoff_fuel_kg':s['mission']['takeoff_fuel_kg'],
        'required_installed_power_w':power['installed_power_w'],'power_constraints':power,
        'carried_fuel_margin_kg':s['mission']['takeoff_fuel_kg']-updated['takeoff_fuel_kg'],
        'mission':updated,'legacy_mission':baseline,'comparison':comparison,
        'replacement_stages':[
            {'model':'原常数效率/密度比例功率','block_fuel_kg':baseline['block_fuel_kg'],'required_installed_power_w':old_required,'max_power_fraction':baseline['max_power_fraction']},
            {'model':'仅替换CCBlade桨图','block_fuel_kg':prop_only['block_fuel_kg'],'required_installed_power_w':prop_only_power,'max_power_fraction':prop_only['max_power_fraction']},
            {'model':'CCBlade＋发动机转速/高度图','block_fuel_kg':updated['block_fuel_kg'],'required_installed_power_w':power['installed_power_w'],'max_power_fraction':updated['max_power_fraction']}],
        'comparison_basis':'same frozen aerodynamic table, geometry, dry mass, initial fuel/CG, rated engine, mission speeds and BSFC; propulsion replacement only',
        'engine':engine.evidence,'propeller':{k:prop.data[k] for k in ('rpm','diameter_m','blades','options','metadata','geometry_role')},
        'direct_checks':direct,'timestep_half_relative_fuel_error':step_error,
        'efficiency_range':[min(r['efficiency'] for r in flight.trace),max(r['efficiency'] for r in flight.trace)],
        'source_aerodynamics_version':parent['version'],'source_aerodynamics_run_id':parent['run_id'],
        'physical_validation_passed':False,'limits':LIMITS}
    write_json(work/'summary.json',summary);return summary


def run_propulsion(project,root,feedback_run_id,options=None):
    p=DesignProject.from_dict(project) if isinstance(project,dict) else project;p.check_schema()
    options=PropulsionOptions.from_dict(options) if isinstance(options,dict) else options or PropulsionOptions();options.validate()
    root=Path(root).resolve();parent=get_results(root,feedback_run_id);pw=root/'runs'/feedback_run_id
    names=('input.json','summary.json','feedback_verification.json','aero_table.json')
    files={n:(pw/n).read_bytes() for n in names};aero=validate_parent(p,parent,files)
    work=root/'runs'/uuid4().hex;work.mkdir(parents=True);(work/'native').mkdir()
    write_json(work/'input.json',p.to_dict());write_json(work/'options.json',asdict(options))
    write_json(work/'parent_result.json',parent)
    for name in names:
        if name!='input.json':(work/('source_'+name)).write_bytes(files[name])
    shutil.copy2(pw/'final_geometry/geometry_contract.json',work/'geometry_contract.json')
    record={'run_id':work.name,'version':__version__,'mode':'propulsion_replay','status':'running',
        'started_utc':datetime.now(timezone.utc).isoformat(),'definition_sha256':p.definition_hash(),
        'input_hash':sha256(work/'input.json'),'source_hashes':source_hashes(),'parent_run_id':feedback_run_id,
        'parent_result_sha256':sha256(work/'parent_result.json'),'options':asdict(options),'physical_validation_passed':False}
    write_json(work/'result.json',record)
    try:record['summary']=perform_replay(p,root,work,parent,options,aero);record['status']=record['summary']['status']
    except Exception as exc:
        record.update(status=getattr(exc,'status','failed'),error=str(exc),diagnostic_context=getattr(exc,'context',{}))
        (work/'error.log').write_text(traceback.format_exc(),encoding='utf-8')
    pack_native(work)
    from .propulsion_report import write_report
    write_report(p,record,work)
    record['finished_utc']=datetime.now(timezone.utc).isoformat()
    record['artifact_hashes']={f.relative_to(work).as_posix():sha256(f) for f in work.rglob('*')
        if f.is_file() and f!=work/'result.json' and not f.is_relative_to(work/'native')}
    write_json(work/'result.json',record);return record
