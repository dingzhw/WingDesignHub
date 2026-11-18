"""Registered PA-28-181 evidence; comparisons retain unmatched conditions."""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime,timezone
from pathlib import Path
from uuid import uuid4
import json,math,sys
from .fuel_model import CALIBRATION,HOLDOUT,PIPER_SOURCE,LYCOMING_REFERENCE,HP_W,LB_KG,calibrated_bsfc


def registry():
    return {'id':'pa28_181_vb760_v1','aircraft':'Piper PA-28-181 Archer II',
        'sources':{'piper':PIPER_SOURCE,'lycoming':{k:LYCOMING_REFERENCE[k] for k in ('document','url','sha256')}},
        'revision_policy':'VB-760 issued 1975-08-15; mixed revisions, pinned PDF SHA and individual pages govern',
        'geometry':{'wing_area_m2':170*.3048**2,'wing_span_m':35*.3048,'length_m':(23*12+9.60)*.0254,
            'source_page':'1-2 / PDF 9','role':'unfitted_specification_reference'},
        'engine':{'model':'Lycoming O-360-A4M','rated_power_w':180*HP_W,'rated_rpm':2700.,'dry_mass_kg':295*LB_KG,
            'source_page':'Piper 1-3 / PDF 10; Lycoming 2-7/2-8 / PDF 25/26',
            'mass_definition':'standard dry engine including listed accessories, starter and generator/alternator; excludes complete aircraft installation',
            'role':'external_manufacturer_specification_not_fitted'},
        'propeller':{'model':'Sensenich 76EM8S5-0-60','diameter_m':76*.0254,'blades':2,'control':'fixed_pitch',
            'source_page':'1-3 / PDF 10','performance_data_available':False},
        'mass':{'mtow_kg':2550*LB_KG,'standard_empty_kg':1390*LB_KG,'fuel_total_kg':50*6*LB_KG,
            'fuel_usable_kg':48*6*LB_KG,'source_page':'1-3/1-4 / PDF 10/11',
            'empty_definition':'approximate standard empty, unusable fuel and full operating fluids including oil',
            'role':'unfitted_approximate_specification; not a specific aircraft weighing'},
        'loading_arms_in':{'front':80.5,'rear':118.1,'fuel':95.,'baggage':142.8},
        'loading_source':'6-11 Fig.6-9 / PDF 101; aircraft datum is not platform nose origin; empty CG absent',
        'fuel_points':[deepcopy(CALIBRATION),*[deepcopy(p) for p in HOLDOUT]],
        'best_power_gal_h':{'55':7.8,'65':9.0,'75':10.5},
        'best_power_role':'unfitted_same_source_reference; 100 F rich of peak EGT, not equivalent to generic map mixture=1',
        'fuel_source_page':'5-17 Fig.5-13 / PDF 80; economy peak EGT vs best power rich mixture',
        'registered_before_evaluation':True,'new_fit_parameters':[],
        'missing':['measured empty CG and datum-to-nose offset','individual component masses and stations',
            'exact broken-taper wing/stabilator and incidence geometry','matched installed fixed-pitch propeller map',
            'RPM/OAT/mixture matched target engine SFC data','independent aircraft flight-test data'],
        'limits':['载荷力臂保留手册基准；未取得机头坐标转换量前不灌入平台重心台账。',
            '65%经济点已用于旧耗油系数校准；55%/75%为同源留出，均不是独立验证数据。',
            '通用图没有目标型号混合比标定；缺少精确RPM时只给规定转速敏感性，不把误差判成同条件验收。',
            '重量计算固定公开外廓与功率，其余模板输入逐项保存；标准空重对照属于部分条件匹配。']}


def evaluate():
    from .engine_fuel import EngineFuelModel
    from .fastga_mass import FastGAMassModel
    from .requirements import DesignProject
    from .sizing_physics import geometry
    ref=registry();e=EngineFuelModel(ref['engine']['rated_power_w']);rows=[]
    for point in ref['fuel_points']:
        pw=e.rated_power_w*point['power_fraction'];observed=point['fuel_us_gal_h'];native=[]
        for rpm in (2350.,2400.,2450.,2500.):
            r=e.operating_point(pw,rpm,6000*.3048,'cruise',.3)
            gal=r['fuel_flow_kg_s']*3600/(6*LB_KG)
            native.append({'rpm':rpm,'fuel_us_gal_h':gal,'relative_error':gal/observed-1,
                'method':r['method'],'power_feasible_in_generic_model':r['power_fraction']<=1.,
                'torque_nm':r['torque_nm'],'bsfc_kg_kwh':r['bsfc_kg_kwh']})
        rows.append({**point,'constant_bsfc_gal_h':pw/1000*.3/(6*LB_KG),
            'old_calibrated_gal_h':pw/1000*calibrated_bsfc()/(6*LB_KG),'generic_map_rpm_sensitivity':native,
            'comparison_status':'conditions_incomplete','unmatched':['exact RPM','OAT effect','engine mixture calibration'],
            'independent_validation_passed':False})
    p=DesignProject();p=replace(p,sizing=replace(p.sizing,aspect_ratio=ref['geometry']['wing_span_m']**2/ref['geometry']['wing_area_m2'],
        fuselage_length_m=ref['geometry']['length_m']),assumptions=replace(p.assumptions,cruise_speed_m_s=127*.44704,
        cruise_altitude_m=6000*.3048)).confirmed()
    mass=ref['mass']['mtow_kg'];geo=geometry(mass,ref['mass']['fuel_usable_kg'],p)
    area=ref['geometry']['wing_area_m2'];span=ref['geometry']['wing_span_m'];root=2*area/(span*1.6)
    mac=2/3*root*(1+.6+.6**2)/1.6
    geo.update(wing_area_m2=area,wing_span_m=span,root_chord_m=root,tip_chord_m=.6*root,mac_m=mac,
        horizontal_tail_area_m2=.7*area*mac/geo['tail_arm_m'],vertical_tail_area_m2=.04*area*span/geo['tail_arm_m'],
        tank_capacity_kg=ref['mass']['fuel_total_kg'],usable_tank_capacity_kg=ref['mass']['fuel_usable_kg'])
    # Unusable fuel matches the handbook's 2/50 US gal, counted once by the mass plugin.
    p=replace(p,sizing=replace(p.sizing,unusable_fuel_fraction=2/50)).confirmed()
    with FastGAMassModel() as model:
        weights=model.evaluate(mass,e.rated_power_w,geo,p);inputs=deepcopy(model.last_inputs);audit=deepcopy(model.audit)
    installed=weights['components_kg']['data:weight:propulsion:engine:mass']
    # Upstream B1 uses a 1.4 installation multiplier; inversion is an accounting
    # decomposition, not an independently solved accessory or propeller mass.
    bare=installed/1.4
    optional={k:v for k,v in weights['components_kg'].items() if 'air_conditioning' in k or 'fixed_oxygen' in k}
    error=weights['owe_kg']/ref['mass']['standard_empty_kg']-1
    return {'status':'reference_audit_with_open_gaps','registry':ref,'fuel_rows':rows,'engine_evidence':e.evidence,
        'mass':{'weights':weights,'geometry':geo,'project':p.to_dict(),'inputs':inputs,'source_audit':audit,
            'standard_empty_relative_error':error,'diagnostic_band_fraction':.2,'inside_diagnostic_band':abs(error)<=.2,
            'condition_status':'partially_matched','optional_equipment_kg':optional,
            'engine_uninstalled_regression_kg':bare,'engine_installation_allowance_kg':installed-bare,
            'engine_bare_relative_error':bare/ref['engine']['dry_mass_kg']-1,
            'unmatched':['tail geometry and wing planform','equipment inventory and oil accounting','load factors/design speeds','specific aircraft empty weight']},
        'checks':{'empty_mass_sum':math.isclose(sum(weights['categories_kg'].values()),weights['owe_kg'],abs_tol=1e-8),
            'no_new_calibration':not ref['new_fit_parameters'],'roles_preserved':rows[0]['role']=='calibration' and all(r['role']=='same_source_holdout' for r in rows[1:]),
            'shaft_units':all(math.isclose(x['torque_nm']*x['rpm']*math.pi/30,e.rated_power_w*r['power_fraction'],rel_tol=1e-12) for r in rows for x in r['generic_map_rpm_sensitivity'])},
        'physical_validation_passed':False,'limits':ref['limits']}


def run_aircraft_reference(root):
    from . import __version__
    from .adapters import execute,sha256
    from .service import write_json
    from .geometry_service import source_hashes
    work=Path(root).resolve()/'runs'/uuid4().hex;work.mkdir(parents=True)
    write_json(work/'input.json',registry())
    r={'run_id':work.name,'mode':'aircraft_reference','version':__version__,'status':'running',
       'started_utc':datetime.now(timezone.utc).isoformat(),'source_hashes':source_hashes(),'input_hash':sha256(work/'input.json')}
    write_json(work/'result.json',r)
    try:
        execute([sys.executable,'-X','utf8','-m','wingdesignhub.aircraft_reference',str(work)],work,timeout=180)
        r['summary']=json.loads((work/'summary.json').read_text('utf8'));r['status']=r['summary']['status']
    except Exception as exc:r.update(status='failed',error=str(exc))
    r['finished_utc']=datetime.now(timezone.utc).isoformat();r['physical_validation_passed']=False
    r['artifact_hashes']={p.name:sha256(p) for p in work.iterdir() if p.is_file() and p.name!='result.json'}
    write_json(work/'result.json',r);return r


if __name__=='__main__':
    from .service import write_json
    w=Path(sys.argv[1]);result=evaluate();write_json(w/'summary.json',result)
    (w/'report.md').write_text('# Archer II 公开基准核查\n\n'+result['status']+'\n\n'+
        '\n'.join('- '+s for s in result['limits'])+'\n\n质量与耗油逐点记录见 summary.json。\n',encoding='utf8')
