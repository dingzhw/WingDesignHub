"""Inert verification of propulsion-coupled archives, without native dependencies."""
import json,hashlib,math
from .propulsion_feedback import CoupledOptions
from .aero_feedback import MissionAeroTable
from .propulsion_model import PropellerMap
from .feedback_evidence import check_native


def check_coupled(record,parents,files):
    r=record;prefix=f'runs/{r["run_id"]}/'
    def data(name):return json.loads(files[prefix+name])
    options=data('options.json');CoupledOptions.from_dict(options)
    snapshot=files[prefix+'parent_result.json']
    parent=next((p for p in parents if p['run_id']==r['parent_run_id']),None)
    if (parent is None or r['mode']!='overall_propulsion' or data('parent_result.json')!=parent or
        hashlib.sha256(snapshot).hexdigest()!=r['parent_result_sha256'] or options!=r['options'] or
        r['definition_sha256']!=parent['definition_sha256']):raise ValueError('方案包推进闭环来源不符')
    check_native(files[prefix+'native_evidence.zip'],data('native_manifest.json'))
    s=r.get('summary',{})
    if 'propulsion_feedback' not in s:return
    audit=data('coupled_verification.json');aero=MissionAeroTable.from_dict(data('aero_table.json'));prop=PropellerMap(data('propeller_map.json'))
    if audit!=s['propulsion_feedback'] or audit['options']!=options or prop.data['options']!=options['propeller']:
        raise ValueError('方案包推进闭环验证与选项不符')
    if aero.area!=s['geometry']['wing_area_m2'] or abs(s['cg']['loaded_mass_kg']-aero.dry_mass-s['mission']['takeoff_fuel_kg'])>1e-6:
        raise ValueError('方案包推进闭环质量或面积不符')
    interface=data('final_geometry/aerodynamic_geometry.json')
    if interface['geometry_file_sha256']!=hashlib.sha256(files[prefix+'final_geometry/aircraft.vsp3']).hexdigest():
        raise ValueError('方案包推进闭环几何文件不符')
    for point in data('mission_trace.json'):
        if abs(point['cg_x_m']-aero.cg(point['mass_kg']))>1e-10 or abs(point['remaining_fuel_kg']-point['mass_kg']+aero.dry_mass)>1e-7:
            raise ValueError('方案包推进闭环任务质量/重心不符')
        if not math.isclose(point['shaft_power_w'],point['torque_nm']*point['rpm']*math.pi/30,rel_tol=1e-10):
            raise ValueError('方案包推进闭环轴功率/扭矩不符')
    if abs(sum(s['mission']['block_fuel_by_method_kg'].values())-s['mission']['block_fuel_kg'])>1e-6:
        raise ValueError('方案包推进闭环耗油账目不符')
