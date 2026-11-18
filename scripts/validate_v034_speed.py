"""Bounded native climb candidates, fixed converged design, no cross-gap interpolation."""
from pathlib import Path
from types import SimpleNamespace
import argparse,json,math,time
from wingdesignhub.requirements import DesignProject
from wingdesignhub.feedback_native import NativeFeedbackGeometry
from wingdesignhub.aircraft_drag import DragOptions
from wingdesignhub.propulsion_model import PropulsionOptions
from wingdesignhub.ccblade_adapter import build_map
from wingdesignhub.engine_fuel import EngineFuelModel
from wingdesignhub.sizing_physics import G,density
from wingdesignhub.configuration import PROPELLER_DIAMETER_M
from wingdesignhub.service import write_json
from wingdesignhub.jobs import code_identity


def main(root,work):
    root=Path(root).resolve();work=Path(work).resolve()
    assert json.loads((work/'freeze.json').read_text('utf8'))==code_identity()
    r=json.loads((work/'coupled.json').read_text('utf8'));s=r['summary'];assert s['converged']
    source=root/'runs'/r['run_id'];p=DesignProject.from_dict(json.loads((source/'input.json').read_text('utf8')))
    mass=s['cg']['loaded_mass_kg'];cg=s['cg']['cg_x_m'];h=p.assumptions.cruise_altitude_m;roc=p.sizing.climb_rate_m_s
    v0=s['propulsion_feedback']['speed_schedule_m_s'][0]
    speeds=sorted(set([v0,min(v0*1.05,90.),min(v0*1.10,90.)]));rows=[];start=time.perf_counter()
    for altitude in sorted(set([0.,h])):
        for speed in speeds:
            row={'speed_m_s':speed,'altitude_m':altitude,'roc_m_s':roc}
            try:
                native=NativeFeedbackGeometry(root,work/f'candidate_{len(rows):02d}',p,s['geometry'],cg,s['design_mtow_kg'],DragOptions())
                point=native(mass,cg,speed,altitude,roc);row.update(status='aero_computed',point=point)
            except Exception as exc:row.update(status=getattr(exc,'status','failed'),error=str(exc))
            rows.append(row);write_json(work/'speed_candidates.json',{'rows':rows,'stage':'aerodynamics'})
    valid=[r for r in rows if r['status']=='aero_computed']
    if valid:
        prop=build_map(root,work/'candidate_propeller',SimpleNamespace(tables={str(i):{'speed_m_s':r['speed_m_s'],'altitudes_m':[r['altitude_m']]} for i,r in enumerate(valid)}),
            PROPELLER_DIAMETER_M,PropulsionOptions(),json.loads((source/'propeller_map.json').read_text('utf8'))['airfoil'],use_cache=True)
        engine=EngineFuelModel(s['power']['installed_power_w'])
        for row in valid:
            try:
                v,z=row['speed_m_s'],row['altitude_m'];drag=.5*density(z)*v*v*s['geometry']['wing_area_m2']*row['point']['cd']
                match=prop.query(drag+mass*G*roc/v,v,z);available=engine.available(z,prop.rpm)
                row.update(status='computed',propeller=match,available_power_w=available,power_margin_w=available-match['shaft_power_w'])
            except Exception as exc:row.update(status=getattr(exc,'status','failed'),error=str(exc))
    selected=[]
    for altitude in sorted(set([0.,h])):
        eligible=[r for r in rows if r['altitude_m']==altitude and r['status']=='computed' and r['power_margin_w']>=0]
        selected.append({'altitude_m':altitude,'candidate_best_speed_m_s':min(eligible,key=lambda r:r['propeller']['shaft_power_w'])['speed_m_s'] if eligible else None})
    write_json(work/'speed_candidates.json',{'rows':rows,'selected':selected,'source_run':source.name,'elapsed_s':time.perf_counter()-start,
        'basis':'same geometry/mass/CG/rated power; requested ROC=3m/s; finite candidates, no mission replacement or map extrapolation',
        'physical_validation_passed':False})
    assert json.loads((work/'freeze.json').read_text('utf8'))==code_identity()


if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('--root',default='.');a.add_argument('--work',required=True);v=a.parse_args();main(v.root,v.work)
