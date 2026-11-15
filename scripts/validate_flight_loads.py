"""Reproducible flight-load sensitivity suite; each child run keeps full artifacts.

This script uses the same public service as the one-click UI. It does not treat
a failed buckling screen as a numerical failure, nor as a strength approval.
"""
from dataclasses import replace
from pathlib import Path
from uuid import uuid4
import json
import sys
import numpy as np
from wingdesignhub.flight_loads import FlightLoadCase,G,aerodynamic_loads
from wingdesignhub.flight_service import run_flight_structure
from wingdesignhub.service import get_results,write_json
from wingdesignhub.adapters import sha256,tool_paths


def run_suite(root,work):
    root=Path(root);work=Path(work);work.mkdir(parents=True,exist_ok=True);base=FlightLoadCase();cases={
        'base':base,'refined':replace(base,mesh=replace(base.mesh,max_edge_m=.15,min_edge_m=.015)),
        'fuel_plus20':replace(base,fuel_half_mass_kg=50.),'negative':replace(base,load_factor=-1.)}
    out={'runs':{},'physical_validation_passed':False,'thresholds':{'tip_mesh':.05,'panel_utilization_mesh':.1,'load_reversal':.001}}
    results={}
    for name,case in cases.items():
        r=run_flight_structure(case,root);get_results(root,r['run_id']);results[name]=r
        out['runs'][name]={'run_id':r['run_id'],'status':r['status'],'artifact_integrity_checked':True,
                          'result_sha256':sha256(root/'runs'/r['run_id']/'result.json')}
        write_json(work/'progress.json',out)
        print(name,r['run_id'],r['status'],r.get('error',''),flush=True)
        if r['status']=='failed':raise RuntimeError(r['error'])
    a,b,f,n=[results[k]['summary'] for k in ('base','refined','fuel_plus20','negative')]
    tip=abs(a['tip_mean_z_m']-b['tip_mean_z_m'])/abs(b['tip_mean_z_m'])
    panel=abs(a['buckling']['max_interaction_utilization']-b['buckling']['max_interaction_utilization'])/b['buckling']['max_interaction_utilization']
    actual=np.array(f['mapping']['input_force_n'])-a['mapping']['input_force_n'];expected=np.array([0,0,-20*G*base.ultimate_factor])
    actual_m=np.array(f['mapping']['input_moment_nm'])-a['mapping']['input_moment_nm']
    expected_m=np.cross([base.fuel_x_fraction*base.mesh.chord_m,(base.fuel_start_fraction+base.fuel_end_fraction)*base.mesh.half_span_m/2,0],expected)
    reverse=abs(a['tip_mean_z_m']+n['tip_mean_z_m'])/abs(a['tip_mean_z_m'])
    # Aerodynamic discretization at identical target lift, using a separate 48-strip run.
    _,_,fine_aero=aerodynamic_loads(replace(base,aero_panels=48),tool_paths(root)['avl'],work/'aero_48')
    def bending(v):return float(sum(p[1]*f[2] for p,f in zip(v['positions_m'],v['forces_n'])))
    aero_moment_difference=abs(bending(a['aero'])-bending(fine_aero))/abs(bending(fine_aero))
    out.update(summary={k:{p:v['summary'][p] for p in ('tip_mean_z_m','peak_von_mises_pa','yield_margin','mapping',
        'structure_mass','represented_half_mass_kg','load_components','screening_issues','aero','buckling')} for k,v in results.items()},
        checks={'tip_mesh_relative_difference':tip,'panel_utilization_mesh_relative_difference':panel,
                'fuel_force_delta_n':actual.tolist(),'expected_fuel_force_delta_n':expected.tolist(),
                'fuel_moment_delta_nm':actual_m.tolist(),'expected_fuel_moment_delta_nm':expected_m.tolist(),
                'fuel_unloads_tip':bool(0<f['tip_mean_z_m']<a['tip_mean_z_m']),
                'load_reversal_tip_relative_error':reverse,'aero_24_48_bending_relative_difference':aero_moment_difference},
        passed=bool(tip<.05 and panel<.1 and np.allclose(actual,expected,rtol=1e-9,atol=1e-7) and
                    np.allclose(actual_m,expected_m,rtol=1e-9,atol=1e-7) and 0<f['tip_mean_z_m']<a['tip_mean_z_m'] and
                    reverse<.001 and aero_moment_difference<.05))
    out['thresholds']['aero_bending_mesh']=.05
    write_json(work/'summary.json',out);return out


if __name__=='__main__':
    root=Path(__file__).resolve().parents[1]
    work=Path(sys.argv[1]).resolve() if len(sys.argv)>1 else root/'runs'/('flight_validation_'+uuid4().hex)
    print(work,flush=True);r=run_suite(root,work);print(json.dumps(r['checks'],indent=2));raise SystemExit(0 if r['passed'] else 1)
