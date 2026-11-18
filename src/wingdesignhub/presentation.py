"""Read-only Chinese views. Stored values and model checks always remain in SI."""
from .constraint_states import display_rows

SEGMENTS = {'climb':'爬升', 'cruise':'巡航', 'descent':'下降', 'loiter':'留空',
            'reserve':'额外储备', 'taxi_out':'出场滑行', 'taxi_in':'入场滑行'}
METHODS = {'native_engine_sfc_map':'发动机原生耗油图', 'base_bsfc':'基础耗油率估算',
           'economy_reference':'经济巡航参考', 'constant_bsfc':'统一耗油率'}
COMPONENTS = {'wing':'主翼', 'horizontal_tail':'平尾', 'vertical_tail':'垂尾',
              'fuselage':'机身', 'landing_gear':'起落架', 'engine':'发动机',
              'propeller':'螺旋桨', 'fuel':'可用燃油', 'payload':'任务载荷（含机组）',
              'unusable_fuel':'不可用燃油', 'seats':'座椅', 'avionics':'航电',
              'flight_controls':'操纵系统', 'power_systems':'机载能源系统',
              'life_support':'环境与生命保障', 'fuel_lines':'燃油管路'}


def number(value, factor=1.):
    if value is None:return '—'
    if isinstance(value, (list, tuple)):return ' ～ '.join(number(v, factor) for v in value)
    return f'{value*factor:.4g}' if isinstance(value, (int, float)) else str(value)


def constraint_rows(summary, project=None):
    rows=display_rows(summary, project)
    for row in rows:
        factor, unit={'W':(.001,'kW'),'MAC':(100.,'% MAC'),'fraction':(100.,'%')}.get(row['单位'],(1.,row['单位']))
        for key in ('计算值','限值','余量'):row[key]=number(row[key], factor)
        row['单位']=unit
    return rows


def mission_rows(summary):
    return [{'任务段':SEGMENTS.get(r['segment'],r['segment']),
             '时长（min）':number(r.get('duration_s'),1/60),
             '航迹（km）':number(r.get('path_distance_m'),.001),
             '真空速（km/h）':number(r.get('speed_m_s'),3.6),
             '耗油（kg）':number(r.get('fuel_kg')),
             '耗油分项（kg）':'；'.join(METHODS.get(k,k)+'：'+number(v) for k,v in r.get('fuel_by_method_kg',{}).items())}
            for r in summary.get('mission',{}).get('segments',[])]


def mass_rows(summary):
    rows=[]
    for r in summary.get('cg',{}).get('rows',[]):
        key=r.get('station_key') or r['component']
        label=COMPONENTS.get(key)
        if label is None:
            label=next((COMPONENTS[x] for x in r['component'].split(':') if x in COMPONENTS),r['component'])
        rows.append({'部件':label,'质量（kg）':number(r['mass_kg']),'站位 x（m）':number(r['x_m']),
                     '来源':r.get('source','概念估算；原记录未单列来源')})
    return rows


def redesign_rows(rows, before='before', after='after'):
    return [{'指标':r['quantity'],'单位':'kW' if r['unit']=='W' else r['unit'],
             '原方案':number(r[before],.001 if r['unit']=='W' else 1.),
             '更新后':number(r[after],.001 if r['unit']=='W' else 1.),
             '变化（%）':number(r['relative_change'],100)} for r in rows]


def loading_rows(summary):
    return [{'装载状态':r['name'],'质量（kg）':number(r['mass_kg']),
             '重心 x（m）':number(r['cg_x_m']),'重心（% MAC）':number(r['cg_mac'],100),
             '剩余可用油（kg）':number(r['remaining_usable_fuel_kg'])}
            for r in summary.get('first_level',{}).get('loading',[])]


def tail_rows(summary):
    return [{'装载场景':case['loading_case'],'Cm 扰动':number(p['moment_bias']),
             '迎角（°）':number(p['alpha_deg']),'升降舵（°）':number(p['elevator_deg']),
             '尾翼升力（N）':number(p['tail_lift_n']),'静稳定裕度（% MAC）':number(p['static_margin'],100)}
            for case in summary.get('first_level',{}).get('longitudinal',[]) for p in case['points']]
