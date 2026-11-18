"""Serial release evidence: registered reference, fixed aircraft, then redesign.

Requires the locally retained V0.3.2.1 A run and configured native tools.
No original PDFs or other-project data are copied into published evidence.
"""
from pathlib import Path
from dataclasses import replace,asdict
from copy import deepcopy
import json,time,argparse
from wingdesignhub.service import write_json
from wingdesignhub.adapters import sha256
from wingdesignhub.jobs import code_identity
from wingdesignhub.requirements import DesignProject
from wingdesignhub.layout import default_layout,component_ledger
from wingdesignhub.aircraft_drag import DragOptions
from wingdesignhub.feedback_native import NativeFeedbackGeometry
from wingdesignhub.aero_feedback import MissionAeroTable
from wingdesignhub.propulsion_model import PropellerMap,PropulsiveFlight
from wingdesignhub.engine_fuel import EngineFuelModel
from wingdesignhub.propulsion_feedback import mission_kwargs,CoupledOptions
from wingdesignhub.sizing_physics import mission


def main(root,work,baseline,stage):
    root=Path(root).resolve();work=Path(work).resolve();work.mkdir(parents=True,exist_ok=True)
    freeze=work/'freeze.json'
    if freeze.exists():assert json.loads(freeze.read_text('utf8'))==code_identity(),'source changed during validation'
    else:write_json(freeze,code_identity())
    old=root/'runs'/baseline
    read=lambda name:json.loads((old/name).read_text('utf8'))
    s=read('summary.json');p=DesignProject.from_dict(read('input.json'))
    layout=default_layout();q=replace(p,sizing=replace(p.sizing,layout=layout)).confirmed()
    ledger=component_ledger(s['weights'],s['geometry'],q,s['mission'])
    if stage=='fixed':
        from wingdesignhub.aircraft_reference import run_aircraft_reference
        ref=run_aircraft_reference(root);write_json(work/'public-reference.json',ref)
        assert ref['status']=='reference_audit_with_open_gaps' and all(ref['summary']['checks'].values())
        data={'baseline_run':baseline,'baseline_hashes':{n:sha256(old/n) for n in ('input.json','summary.json','aero_table.json','propeller_map.json')},
              'fixed_geometry':s['geometry'],'fixed_mass_kg':s['cg']['loaded_mass_kg'],'layout_ledger':ledger,'points':[]}
        write_json(work/'fixed.json',data)
        cg0=s['cg']['cg_x_m'];cg1=ledger['cg_x_m'];mass=s['cg']['loaded_mass_kg']
        angled=deepcopy(layout);angled.update(wing_incidence_deg=2.,tail_incidence_deg=-1.)
        r=replace(q,sizing=replace(q.sizing,layout=angled)).confirmed()
        scenarios=[('legacy',p,cg0,60.,DragOptions()),('leaf_stations',q,cg1,60.,DragOptions()),
            ('incidence',r,cg1,60.,DragOptions()),('strut_low_cd',p,cg0,60.,replace(DragOptions(),strut_crossflow_cd=.3)),
            ('higher_speed',p,cg0,66.,DragOptions())]
        for name,project,cg,speed,drag in scenarios:
            started=time.perf_counter()
            try:
                native=NativeFeedbackGeometry(root,work/name,project,s['geometry'],cg,s['design_mtow_kg'],drag)
                point=native(mass,cg,speed,2000.,0.)
                geom=json.loads((native.geometry_work/'summary.json').read_text('utf8'))
                row={'scenario':name,'status':'computed','project':project.to_dict(),'drag_options':asdict(drag),
                    'point':point,'geometry_passed':geom['passed'],'geometry_measurements':geom['measurements']['lifting_surfaces']}
            except Exception as exc:row={'scenario':name,'status':getattr(exc,'status','failed'),'error':str(exc)}
            row['elapsed_s']=time.perf_counter()-started;data['points'].append(row);write_json(work/'fixed.json',data)
        # Same saved geometry, loading and schedule: isolate fuel and propeller changes.
        # Archived tables carry their original source hashes; no relabelling as freshly solved aerodynamics.
        table=MissionAeroTable.from_dict(read('aero_table.json'));prop=PropellerMap(read('propeller_map.json'))
        rated=s['power']['installed_power_w'];engine=EngineFuelModel(rated)
        schedule=s['propulsion_feedback']['speed_schedule_m_s'];flight=PropulsiveFlight(table,prop,engine)
        variants=[('constant_eta_constant_bsfc',{'flight_model':table,'schedule':schedule}),
            ('constant_eta_native_sfc',{'flight_model':table,'schedule':schedule,'fuel_flow_model':engine.mission_flow(prop.rpm),
                'fuel_description':engine.description(prop.rpm,p.sizing.bsfc_kg_kwh)}),
            ('ccblade_native_sfc',mission_kwargs(flight,schedule,p))]
        data['fixed_missions']=[]
        for name,kw in variants:
            try:out={'name':name,'status':'computed','mission':mission(mass,s['geometry'],rated,p,30.,**kw)}
            except Exception as exc:out={'name':name,'status':getattr(exc,'status','failed'),'error':str(exc)}
            data['fixed_missions'].append(out);write_json(work/'fixed.json',data)
        # The strut sensitivity modifies its unique ledger contribution at every
        # original table node, then repeats exactly the same fixed mission.
        reduced=deepcopy(read('aero_table.json'))
        for branch in reduced['branches'].values():
            for points in branch['points']:
                for pt in points:
                    delta=.75*pt['strut_cd'];pt['components']['body']-=delta;pt['cd']-=delta;pt['strut_cd']*=.25
        reduced=MissionAeroTable.from_dict(reduced);reduced_flight=PropulsiveFlight(reduced,prop,engine)
        try:out={'name':'strut_cd_0.3_ccblade_sfc','status':'computed','mission':mission(mass,s['geometry'],rated,p,30.,**mission_kwargs(reduced_flight,schedule,p))}
        except Exception as exc:out={'name':'strut_cd_0.3_ccblade_sfc','status':getattr(exc,'status','failed'),'error':str(exc)}
        data['fixed_missions'].append(out)
        data['limits']=['固定构型敏感性是独立合成飞机，不是 Archer II 实机预测。',
            '低支柱系数仅为规定面积下的假设情景；未用于更新默认值或实机校准。',
            '固定任务保留原始携油与干重，所需油量变化不重新生成装载或尺寸。',
            '历史气动/桨表按原哈希复用；实际安装角/站位由本次单点原生计算检查。']
        write_json(work/'fixed.json',data)
    elif stage=='redesign':
        assert (work/'fixed.json').is_file(),'fixed comparison must precede redesign'
        from wingdesignhub.sizing_service import run_sizing
        from wingdesignhub.coupled_service import run_coupled
        # Change only the mass-position definition; incidence/strut remain isolated sensitivities.
        started=time.perf_counter();seed=run_sizing(q,root);write_json(work/'seed.json',seed)
        assert seed.get('summary',{}).get('converged'),seed['status']
        out=run_coupled(q,root,seed['run_id'],CoupledOptions());write_json(work/'redesign.json',out)
        write_json(work/'redesign-time.json',{'elapsed_s':time.perf_counter()-started})
        assert out['status']=='concept_checked_with_limits',out.get('error',out['status'])
    assert json.loads(freeze.read_text('utf8'))==code_identity()


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,default=Path.cwd())
    ap.add_argument('--work',type=Path,default=Path('local/v033/formal3'))
    ap.add_argument('--baseline',default='f3d53e6f32534150970ce6bc114a5703')
    ap.add_argument('--stage',choices=['fixed','redesign'],required=True)
    args=ap.parse_args();main(args.root,args.work,args.baseline,args.stage)
