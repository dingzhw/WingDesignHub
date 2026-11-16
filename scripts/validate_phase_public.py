"""Public data roles stay separate from software and whole-aircraft acceptance."""
from pathlib import Path
import sys,json
from wingdesignhub import __version__
from wingdesignhub.ccblade_benchmark import official_benchmark
from wingdesignhub.fuel_validation import evaluate_fuel_model
from wingdesignhub.reference_cruise import evaluate_public_cruise
from wingdesignhub.adapters import tool_paths
from wingdesignhub.service import write_json
from wingdesignhub.geometry_service import source_hashes
from validate_engine_fuel import main as engine_check
from validate_aircraft_drag import public_check


def main(target):
    root=Path(__file__).resolve().parents[1];work=Path(target).resolve();work.mkdir(parents=True,exist_ok=False)
    source=source_hashes()
    prop=official_benchmark(root,work/'apc_official')
    engine_source=root/'local/v027-sources/test_basicIC_engine.py'
    engine=engine_check(work/'engine',engine_source if engine_source.is_file() else None)
    airfoil=public_check(root,work/'e387',tool_paths(root)['xfoil'])
    fuel=evaluate_fuel_model();cruise=evaluate_public_cruise()
    matrix=[
        {'item':'APC thin electric 10x5','role':'upstream published example with experimental comparison',
         'matched':['diameter .254 m','two blades','5400 rpm','rho 1.225 kg/m3','17 advance ratios','published blade geometry'],
         'assumptions':['tutorial NACA4412 AlphaAF input','hub radius .1R'],
         'calibration_performed':False,'result':prop['all_within_band'],'whole_aircraft_validation':False},
        {'item':'UIUC E387','role':'independent airfoil-method check',
         'matched':['clean nominal E387 coordinates','measured Reynolds number','measured section lift coefficient'],
         'assumptions':['Mach estimated from tunnel speed','Ncrit=9; actual transition not matched','not the aircraft NACA23012/0012 airfoils'],
         'calibration_performed':False,'result':airfoil['within_diagnostic_band'],'whole_aircraft_validation':False},
        {'item':'FAST-GA 1.4.0 generic engine','role':'official numerical regression and same-map identity',
         'matched':['original upstream tests','330 original RPM/torque SFC nodes','units and installation mass factors'],
         'assumptions':['generic engine scaling; no target engine measured data'],
         'calibration_performed':False,'result':engine['passed'],'whole_aircraft_validation':False},
        {'item':'Piper VB-760 65%','role':'legacy BSFC calibration; NOT enhanced-model validation',
         'matched':['2550 lb','170 ft2','35 ft','6000 ft pressure altitude','55 F','65% of 180 hp','wheel fairings','economy peak EGT'],
         'assumptions':['legacy parabolic aircraft polar and .8 propeller efficiency','65% fuel datum already used for calibration'],
         'result':'historical model discrepancy retained','whole_aircraft_validation':False},
        {'item':'Piper VB-760 55% / 75%','role':'same-source holdout for legacy calibrated BSFC',
         'matched':['same manual and stated economy mixture'],
         'assumptions':['not independent external aircraft validation','new generic engine not identified as O-360'],
         'result':fuel['status'],'whole_aircraft_validation':False},
        {'item':'enhanced full aircraft','role':'independent physical validation pending',
         'matched':[],'assumptions':['synthetic airframe and three-blade propeller','target engine map, propeller map and flight record not available as one matched set'],
         'result':'not_evaluated','whole_aircraft_validation':False}]
    checks={'official_propeller_band':prop['all_within_band'],'official_engine':engine['passed'],
            'airfoil_diagnostic_band':airfoil['within_diagnostic_band'],'sources_frozen':source==source_hashes(),
            'legacy_discrepancy_retained':cruise['status']=='model_discrepancy'}
    output={'version':__version__,'passed':all(checks.values()),'checks':checks,'condition_matrix':matrix,
        'propeller':prop,'engine':engine,'airfoil':airfoil,'legacy_fuel':fuel,'legacy_cruise':cruise,
        'source_hashes':source,'physical_validation_passed':False}
    write_json(work/'validation.json',output);print('PUBLIC',output['passed'],flush=True)
    if not output['passed']:raise RuntimeError('公开检查未通过；误差保留')


if __name__=='__main__':main(sys.argv[1])
