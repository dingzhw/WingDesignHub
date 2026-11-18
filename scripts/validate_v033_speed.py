"""Two fixed-aircraft climb speeds inside the existing CL domain, no resizing."""
from pathlib import Path
from dataclasses import replace
from types import SimpleNamespace
import json,math
from wingdesignhub.requirements import DesignProject
from wingdesignhub.feedback_native import NativeFeedbackGeometry
from wingdesignhub.aircraft_drag import DragOptions
from wingdesignhub.aero_feedback import feedback_schedule,FeedbackOptions
from wingdesignhub.propulsion_model import PropulsionOptions
from wingdesignhub.ccblade_adapter import build_map
from wingdesignhub.engine_fuel import EngineFuelModel
from wingdesignhub.sizing_physics import density,G
from wingdesignhub.service import write_json
from wingdesignhub.jobs import code_identity

root=Path(__file__).resolve().parents[1];w=root/'local/v033/formal3';old=root/'runs/f3d53e6f32534150970ce6bc114a5703'
assert json.loads((w/'freeze.json').read_text('utf8'))==code_identity()
read=lambda n:json.loads((old/n).read_text('utf8'))
s=read('summary.json');p=DesignProject.from_dict(read('input.json'));h=p.assumptions.cruise_altitude_m
speeds=[feedback_schedule(s['design_mtow_kg'],s['geometry'],p,replace(FeedbackOptions(),schedule_cl_ceiling=cl))[0] for cl in (.5,.45)]
n=NativeFeedbackGeometry(root,w/'speed_native',p,s['geometry'],s['cg']['cg_x_m'],s['design_mtow_kg'],DragOptions())
mass=s['cg']['loaded_mass_kg'];cg=s['cg']['cg_x_m'];roc=p.sizing.climb_rate_m_s
points=n.batch([(mass,cg,v,h,roc) for v in speeds])
prop=build_map(root,w/'speed_propeller',SimpleNamespace(tables={str(v):{'speed_m_s':v,'altitudes_m':[h]} for v in speeds}),
    1.9,PropulsionOptions(),read('propeller_map.json')['airfoil'],use_cache=True)
engine=EngineFuelModel(s['power']['installed_power_w']);rows=[]
for speed,point in zip(speeds,points):
    drag=.5*density(h)*speed**2*s['geometry']['wing_area_m2']*point['cd']
    thrust=drag+mass*G*roc/speed
    match=prop.query(thrust,speed,h)
    fuel=engine.operating_point(match['shaft_power_w'],prop.rpm,h,'climb',p.sizing.bsfc_kg_kwh)
    rows.append({'speed_m_s':speed,'point':point,'drag_n':drag,'thrust_n':thrust,'propeller':match,'engine':fuel})
write_json(w/'speed.json',{'basis':'same geometry, mass, CG, installed power; steady climb ROC=3 m/s at 2000 m',
    'cl_ceilings':[.5,.45],'rows':rows,'physical_validation_passed':False,
    'limits':['两个速度均在原小迎角方法域内，不是最佳爬升速度搜索。','功率超限只记录，不改变发动机、任务或模型边界。']})
print([(r['speed_m_s'],r['propeller']['shaft_power_w'],r['engine']['fuel_flow_kg_s']*3600) for r in rows])
