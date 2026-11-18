"""Common fuel inventory for model attribution, after the original-load failure.

The original loading/failure is retained. This common diagnostic load is the
existing aerodynamic table's upper node; it is not a resized feasible aircraft.
"""
from pathlib import Path
import json
from wingdesignhub.service import write_json
from wingdesignhub.jobs import code_identity
from wingdesignhub.requirements import DesignProject
from wingdesignhub.aero_feedback import MissionAeroTable
from wingdesignhub.propulsion_model import PropellerMap,PropulsiveFlight
from wingdesignhub.engine_fuel import EngineFuelModel
from wingdesignhub.propulsion_feedback import mission_kwargs
from wingdesignhub.sizing_physics import mission

root=Path(__file__).resolve().parents[1];w=root/'local/v033/formal3'
assert json.loads((w/'freeze.json').read_text('utf8'))==code_identity()
old=root/'runs/f3d53e6f32534150970ce6bc114a5703'
read=lambda name:json.loads((old/name).read_text('utf8'))
s=read('summary.json');p=DesignProject.from_dict(read('input.json'))
table=MissionAeroTable.from_dict(read('aero_table.json'));prop=PropellerMap(read('propeller_map.json'))
mass=table.mass_nodes[-1];rated=s['power']['installed_power_w'];e=EngineFuelModel(rated)
schedule=s['propulsion_feedback']['speed_schedule_m_s'];flight=PropulsiveFlight(table,prop,e)
out={'basis':'same fixed geometry, engine rating, common loaded mass and schedule; diagnostic only',
     'loaded_mass_kg':mass,'fuel_inventory_kg':mass-table.dry_mass,'design_mass_kg':s['design_mtow_kg'],
     'exceeds_design_mass':mass>s['design_mtow_kg'],'cg_x_m':table.cg(mass),'rows':[],'physical_validation_passed':False}
variants=[('constant_eta_constant_bsfc',{'flight_model':table,'schedule':schedule}),
          ('constant_eta_native_sfc',{'flight_model':table,'schedule':schedule,'fuel_flow_model':e.mission_flow(prop.rpm),
                                    'fuel_description':e.description(prop.rpm,p.sizing.bsfc_kg_kwh)}),
          ('ccblade_native_sfc',mission_kwargs(flight,schedule,p))]
for name,kw in variants:
    try:
        r=mission(mass,s['geometry'],rated,p,30.,**kw)
        fine=mission(mass,s['geometry'],rated,p,15.,**kw)
        out['rows'].append({'name':name,'status':'computed','mission':r,'half_step_relative_fuel_error':abs(r['block_fuel_kg']/fine['block_fuel_kg']-1)})
    except Exception as exc:out['rows'].append({'name':name,'status':getattr(exc,'status','failed'),'error':str(exc)})
    write_json(w/'fixed-fuel-common-load.json',out)
assert all(r['status']=='computed' and r['half_step_relative_fuel_error']<.005 for r in out['rows'])
print([(r['name'],r['mission']['block_fuel_kg']) for r in out['rows']])
