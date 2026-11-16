"""V0.2.5 bounded native overall closure and reproducible stage evidence."""
from pathlib import Path
from dataclasses import replace
import json,sys,math
from wingdesignhub import __version__
from wingdesignhub.requirements import DesignProject
from wingdesignhub.sizing_service import run_sizing
from wingdesignhub.feedback_service import run_aero_feedback
from wingdesignhub.aero_feedback import FeedbackOptions,MissionAeroTable,FeedbackError
from wingdesignhub.aircraft_drag import DragOptions
from wingdesignhub.geometry_service import source_hashes
from wingdesignhub.project_archive import build_bundle,read_bundle,save_bundle,load_saved
from wingdesignhub.service import get_results,write_json,generate_report
from wingdesignhub.adapters import sha256,tool_paths
from wingdesignhub.sizing_physics import density,G


def main(target):
    root=Path(__file__).resolve().parents[1];work=Path(target).resolve();work.mkdir(parents=True,exist_ok=False)
    start=source_hashes();p=DesignProject().confirmed();baseline=run_sizing(p,root)
    write_json(work/'checkpoint.json',{'source_hashes':start,'baseline':baseline['run_id'],'state':'native_feedback_running'})
    print('baseline',baseline['run_id'],baseline['status'],flush=True)
    r=run_aero_feedback(p,root,baseline['run_id'])
    write_json(work/'checkpoint.json',{'source_hashes':start,'baseline':baseline['run_id'],'feedback':r['run_id'],'state':r['status']})
    print('feedback',r['run_id'],r['status'],r.get('error',''),flush=True)
    if r['status']!='concept_checked_with_limits':raise RuntimeError('Native closure did not pass; see checkpoint and run evidence')
    s=r['summary'];audit=s['aerodynamic_feedback'];rw=root/'runs'/r['run_id'];checks={}
    checks['record_integrity']=get_results(root,r['run_id'])==r
    checks['three_stable_rounds']=s['iterations'][-1]['stable_rounds']>=3
    checks['constraints']=all(s['checks'].values())
    checks['mass_closure']=abs(s['required_loaded_mass_kg']/s['design_mtow_kg']-1)<1e-4
    checks['engine_mass_coupling']=s['iterations'][-1]['residuals']['power_weight_coupling']<1e-4 and s['iterations'][-1]['residuals']['dry_weight_coupling']<1e-4
    checks['independent_interior_queries']=all(x['relative_cd_error']<.02 for x in audit['direct_checks'])
    checks['timestep_halving']=audit['timestep_half_relative_fuel_error']<.005
    table=MissionAeroTable.from_dict(json.loads((rw/'aero_table.json').read_text('utf-8')))
    trace=json.loads((rw/'mission_trace.json').read_text('utf-8'));area=s['geometry']['wing_area_m2'];eta=p.sizing.propeller_efficiency
    errors={'normal':0.,'axial':0.,'power':0.,'cg':0.}
    for state in trace:
        m=state['mass_kg'];v=state['speed_m_s'];gamma=math.asin(state['roc_m_s']/v);q=.5*density(state['altitude_m'])*v*v
        errors['normal']=max(errors['normal'],abs(q*area*state['cl']-m*G*math.cos(gamma)))
        errors['axial']=max(errors['axial'],abs(state['thrust_n']-state['drag_n']-m*G*math.sin(gamma)))
        errors['power']=max(errors['power'],abs(state['shaft_power_w']*eta-state['thrust_n']*v))
        errors['cg']=max(errors['cg'],abs(state['cg_x_m']-table.cg(m)))
    checks['point_mass_balances']=max(errors.values())<1e-8
    checks['fuel_bookkeeping']=abs(s['cg']['loaded_mass_kg']-table.dry_mass-s['mission']['takeoff_fuel_kg'])<1e-6
    checks['reserve_once']=abs(s['mission']['takeoff_fuel_kg']-s['mission']['trip_fuel_from_takeoff_kg']-s['mission']['reserve_fuel_kg'])<1e-8
    br=next(iter(table.tables.values()))
    try:table.query(table.mass_nodes[-1]+1.,br['speed_m_s'],br['altitudes_m'][0],br['roc_m_s'])
    except FeedbackError as exc:checks['no_extrapolation']=exc.status=='aero_table_out_of_domain'
    else:checks['no_extrapolation']=False
    data=build_bundle(p,root,baseline,feedback_record=r);(work/'baseline.wdh').write_bytes(data)
    saved=save_bundle(data,root);opened=load_saved(root,saved['archive_id'])
    checks['archive_reopen']=opened['feedback_records']==[r] and read_bundle(data)['current_source_matches']
    checks['report']=generate_report(r,root=root)==(rw/'report.html').read_text('utf-8')
    # A deliberately distinct transition condition has no cache. It must stay failed.
    missing=run_aero_feedback(p,root,baseline['run_id'],FeedbackOptions(max_iterations=1,drag=DragOptions(ncrit=7.731,cache_only=True)))
    checks['missing_polar_diagnostic']=missing['status']=='polar_missing' and 'summary' not in missing
    checks['failed_archive']=read_bundle(build_bundle(p,root,baseline,feedback_record=missing))['feedback_records']==[missing]
    sensitivities={x['case']:x for x in audit['fixed_design_sensitivity']['rows']}
    checks['strut_sensitivity']=sensitivities['strut_cd_0.8']['required_block_fuel_kg']<sensitivities['baseline']['required_block_fuel_kg']<sensitivities['strut_cd_1.6']['required_block_fuel_kg']
    checks['allowance_sensitivity']=sensitivities['allowance_plus_0.001']['required_installed_power_w']>sensitivities['baseline']['required_installed_power_w']
    checks['propeller_assumption_sensitivity']=sensitivities['propeller_efficiency_minus_0.05']['required_block_fuel_kg']>sensitivities['baseline']['required_block_fuel_kg']
    # Reuse the declared independent public dataset, never fit the aircraft to it.
    from validate_aircraft_drag import public_check
    public=public_check(root,work/'public_check',tool_paths(root)['xfoil']);checks['public_airfoil_diagnostic']=public['within_diagnostic_band']
    checks['source_frozen']=source_hashes()==start
    manifest=json.loads((rw/'native_manifest.json').read_text('utf-8'))
    result={'version':__version__,'passed':all(checks.values()),'checks':checks,'baseline_run_id':baseline['run_id'],
            'feedback_run_id':r['run_id'],'missing_polar_run_id':missing['run_id'],'archive_id':saved['archive_id'],
            'redesign_comparison':s['redesign_comparison'],'aerodynamic_feedback':audit,'force_balance_absolute_errors':errors,
            'iterations':s['iterations'],'native_evidence':{'files':len(manifest['files']),'uncompressed_bytes':manifest['uncompressed_bytes'],
                'zip_bytes':(rw/'native_evidence.zip').stat().st_size,'sha256':manifest['archive_sha256']},
            'public_airfoil_check':public,'source_hashes':start,'physical_validation_passed':False}
    write_json(work/'validation.json',result)
    print('STAGE',result['passed'],sum(checks.values()),'/',len(checks),'checks',flush=True)
    if not result['passed']:raise RuntimeError({k:v for k,v in checks.items() if not v})


if __name__=='__main__':main(sys.argv[1])
