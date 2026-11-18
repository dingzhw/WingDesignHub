"""Visible concept layout; exact leaf-mass accounting, never a fitted CG."""
from copy import deepcopy
import math


def default_layout():
    return {'version':'component_layout_v1','wing_quarter_fraction':.39,
            'wing_incidence_deg':0.,'tail_incidence_deg':0.,
            'stations_fraction':{'fuselage':.45,'engine':.12,'systems':.40,'controls':.40,
                                 'front_seats':.32,'rear_seats':.46,'baggage':.58,'fuel':.39},
            'payload_fractions':{'front_seats':.5,'rear_seats':.4,'baggage':.1},
            'source':'WingDesignHub V0.3.3 概念布置研究假设；部件站位须由布置/称重资料核实，非 Piper 实机站位'}


def validate_layout(value):
    if value is None:return
    reference=default_layout()
    if not isinstance(value,dict) or set(value)!=set(reference) or value['version']!=reference['version']:
        raise ValueError('布局配置字段或版本无效')
    if not isinstance(value['source'],str) or not value['source'].strip():raise ValueError('布局须声明来源')
    def bounded(x,lo,hi):return type(x) in (int,float) and math.isfinite(x) and lo<=x<=hi
    if not bounded(value['wing_quarter_fraction'],.3,.48):raise ValueError('机翼站位须在机长的30%–48%')
    if any(not bounded(value[k],-3,3) for k in ('wing_incidence_deg','tail_incidence_deg')):
        raise ValueError('安装角研究域为正负3度')
    for group in ('stations_fraction','payload_fractions'):
        data=value[group]
        if not isinstance(data,dict) or set(data)!=set(reference[group]) or any(not bounded(x,0,1) for x in data.values()):
            raise ValueError('布局站位或载荷分配无效：'+group)
    if abs(math.fsum(value['payload_fractions'].values())-1)>1e-12:raise ValueError('载荷分配比例之和须为1')


def fuel_station(geo,project):
    layout=project.sizing.layout
    return geo['wing_quarter_x_m'] if layout is None else layout['stations_fraction']['fuel']*geo['fuselage_length_m']


def component_ledger(weights,geo,project,mission):
    layout=project.sizing.layout;validate_layout(layout)
    lf=geo['fuselage_length_m'];stations={k:v*lf for k,v in layout['stations_fraction'].items()}
    stations.update(wing=geo['wing_quarter_x_m'],horizontal_tail=geo['wing_quarter_x_m']+geo['tail_arm_m'],
                    vertical_tail=geo['wing_quarter_x_m']+geo['tail_arm_m'],
                    main_gear=geo['wing_quarter_x_m']+.18*geo['mac_m'],front_gear=.15*lf)
    rows=[];details=weights['components_kg'];sums={k:0. for k in weights['categories_kg']}
    for full,mass in details.items():
        parts=full.split(':')[2:-1]
        if len(parts)<2:continue # category totals are never counted again
        category=parts[0];name=':'.join(parts[1:])
        if name=='unusable_fuel':category='unusable_fuel';station='fuel'
        elif category=='airframe':
            station={'wing':'wing','fuselage':'fuselage','horizontal_tail':'horizontal_tail','vertical_tail':'vertical_tail',
                     'flight_controls':'controls','landing_gear:main':'main_gear','landing_gear:front':'front_gear','paint':'fuselage'}[name]
        elif category=='propulsion':station={'engine':'engine','fuel_lines':'fuel'}[name]
        elif category=='systems':station='systems'
        elif category=='furniture':station='front_seats'
        else:raise ValueError('未定义部件站位：'+full)
        if not math.isfinite(mass) or mass<0:raise ValueError('部件质量无效')
        sums[category]+=mass
        rows.append({'component':full,'category':category,'mass_kg':mass,'x_m':stations[station],
                     'station_key':station,'source':layout['source'],'position_uncertainty_m':.05*lf})
    if any(not math.isclose(sums[k],v,rel_tol=1e-9,abs_tol=1e-8) for k,v in weights['categories_kg'].items()):
        raise ValueError('叶级部件质量与类别合计不一致，禁止静默分摊差值')
    for name,fraction in layout['payload_fractions'].items():
        rows.append({'component':'payload_'+name,'category':'payload','mass_kg':project.payload_kg*fraction,
                     'x_m':stations[name],'source':layout['source']})
    fx=fuel_station(geo,project)
    rows.append({'component':'takeoff_fuel','category':'usable_fuel','mass_kg':mission['takeoff_fuel_kg'],'x_m':fx})
    total=math.fsum(r['mass_kg'] for r in rows);moment=math.fsum(r['mass_kg']*r['x_m'] for r in rows)
    used=mission['trip_fuel_from_takeoff_kg'];end=total-used
    if end<=0 or used<0 or used>mission['takeoff_fuel_kg']+1e-8:raise ValueError('任务耗油超过实际装载')
    cg=moment/total;end_cg=(moment-used*fx)/end
    variations={}
    for name in ('front_seats','rear_seats','baggage'):
        payload_moment=math.fsum(r['mass_kg']*r['x_m'] for r in rows if r['category']=='payload')
        variations[name]=(moment-payload_moment+project.payload_kg*stations[name])/total
    full_mass=total-mission['takeoff_fuel_kg']+geo['usable_tank_capacity_kg']
    return {'rows':rows,'loaded_mass_kg':total,'cg_x_m':cg,'end_cg_x_m':end_cg,
            'cg_mac_fraction':(cg-(geo['wing_quarter_x_m']-.25*geo['mac_m']))/geo['mac_m'],
            'stations_source':layout['source'],'layout':deepcopy(layout),'fuel_station_x_m':fx,
            'loading_sensitivity':{'all_payload_at_station_cg_x_m':variations,
                'component_position_cg_shift_m':{r['component']:r['mass_kg']*.05*lf/total for r in rows if r.get('position_uncertainty_m')},
                'full_tank_mass_kg':full_mass,'full_tank_cg_x_m':(moment+(geo['usable_tank_capacity_kg']-mission['takeoff_fuel_kg'])*fx)/full_mass,
                'status':'position sensitivity only; seat/baggage limits and CG envelope not checked'},
            'limits':['安装发动机经验重量未独立拆分螺旋桨/附件；缺少目标部件称重数据。',
                      '部件位置±5%机长仅为未校准敏感性范围，不是制造公差。',
                      '全部座椅重量暂放前排站位；需具体座椅拆分，装载轨迹不是允许重心包线。']}
