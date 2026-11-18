"""Versioned geometry contract downstream of a converged overall design (SI)."""
from dataclasses import asdict, dataclass
import math
import numpy as np
from .configuration import geometry_parameters, CONFIGURATION_VERSION, PROPELLER_DIAMETER_M

TEMPLATE_VERSION = 'conventional_single_v1'
GEOMETRY_AXES = 'x aft from nose, y right, z up'
BODY_ROTATION = np.diag([-1., 1., -1.])
LIMITS = [
    '常规低翼、常规尾翼、单发前三点金属飞机概念外形；总体尺寸沿用本次已收敛结果。',
    '翼型、尾翼展弦比、垂向位置、椭圆机身截面及动力/起落架包络是版本化模板假设，尚未经过气动或布置优化。',
    '主翼NACA2412、尾翼NACA0012；翼/平尾安装角按布局配置（默认零），零扭转/上反及四分之一弦无后掠。AVL安装角采用线性边界条件，CAD实体绕四分之一弦旋转。',
    '螺旋桨仅为直径 1.9 m 的无推力盘，发动机包络含在前机身；起落架仅为支柱和轮罩外形，尺寸未作匹配或强度校核。',
    '气动接口使用全翼毛面积、全翼展和平均气动弦；主翼与机身重叠面积仍在参考面积中。参考点采用总体估算起飞重心 x，y/z 暂取零。',
    '几何任务导出升力面和机身分组、截面及 DegenGeom；独立气动子任务记录求解状态，黏性阻力、配平、动力影响和重心包线仍待接入。',
    '外形交叠是概念布置；没有生成布尔缝合实体、容积/湿面积或全机结构网格，也不修改现有质量台账。',
]


@dataclass(frozen=True)
class GeometryOptions:
    template_version: str = TEMPLATE_VERSION
    tessellation: int = 1

    def validate(self):
        if self.template_version != TEMPLATE_VERSION:
            raise ValueError('不支持此外形模板版本')
        if type(self.tessellation) is not int or self.tessellation not in (1, 2):
            raise ValueError('几何离散档位须为 1 或 2')


def body_points(points, origin_geometry_m):
    """Positions in CG-origin body axes; offsets are applied before rotation."""
    return (np.asarray(points, dtype=float) - np.asarray(origin_geometry_m)) @ BODY_ROTATION.T


def body_vectors(vectors):
    return np.asarray(vectors, dtype=float) @ BODY_ROTATION.T


def transfer_wrench(force_geometry_n, moment_geometry_nm, old_reference_m, new_reference_m):
    """Translate a wrench in geometry axes, then rotate both vectors to body axes."""
    f = np.asarray(force_geometry_n, dtype=float)
    m = np.asarray(moment_geometry_nm, dtype=float)
    translated = m + np.cross(np.asarray(old_reference_m)-np.asarray(new_reference_m), f)
    return body_vectors(f), body_vectors(translated)


def surface(name, area, span, taper, quarter_x, z, vertical=False, camber=0., spec=None):
    root = 2*area/(span*(1+taper)); tip = taper*root
    mac = 2*root*(1+taper+taper*taper)/(3*(1+taper))
    extent = span if vertical else span/2
    root_le = [quarter_x-.25*root, 0., z]
    tip_le = [quarter_x-.25*tip, 0. if vertical else extent, z+extent if vertical else z]
    naca = spec['naca'] if spec else ('2412' if camber else '0012')
    return {'name':name, 'area_m2':area, 'span_m':span, 'root_chord_m':root,
            'tip_chord_m':tip, 'mac_m':mac, 'quarter_x_m':quarter_x, 'z_m':z,
            'symmetric':not vertical, 'vertical':vertical, 'naca':naca,
            'camber':int(naca[0])/100, 'camber_location':int(naca[1])/10 or .4,
            'thickness_ratio':spec['thickness_ratio'] if spec else int(naca[-2:])/100,
            'incidence_deg':0., 'twist_deg':0., 'dihedral_deg':0., 'quarter_sweep_deg':0.,
            'sections':[{'leading_edge_m':root_le, 'chord_m':root, 'twist_deg':0.},
                        {'leading_edge_m':tip_le, 'chord_m':tip, 'twist_deg':0.}]}


def build_geometry_contract(project, record, options=None, *, trial=False):
    options = options or GeometryOptions(); options.validate()
    if trial:
        if record.get('mode')!='overall_trial' or record.get('status')!='trial':raise ValueError('内部几何试算须明确标记 trial')
    elif record.get('mode') != 'overall_sizing' or record.get('status') not in ('concept_checked_with_limits', 'constraints_not_met'):
        raise ValueError('全机几何需要已收敛的总体运行；失败或未收敛试算不可使用')
    if project.confirmation_sha256 != project.definition_hash() or record.get('definition_sha256') != project.definition_hash():
        raise ValueError('需求或确认状态已变更，请重新计算总体方案')
    s = record['summary']
    if not trial and (s.get('converged') is not True or s.get('status') != record['status']):
        raise ValueError('总体收敛状态不一致')
    g = s['geometry']
    parameters = geometry_parameters(g)
    if g.get('configuration') != 'low_wing_conventional_tail_fixed_tricycle_metal' or g.get('engine_count') != 1:
        raise ValueError('外形模板仅适用于常规低翼单发飞机')
    if g.get('axes') != GEOMETRY_AXES:
        raise ValueError('总体几何坐标约定不一致')
    required = ('wing_area_m2','wing_span_m','root_chord_m','tip_chord_m','mac_m','wing_quarter_x_m',
                'horizontal_tail_area_m2','vertical_tail_area_m2','tail_arm_m','fuselage_length_m','fuselage_width_m','fuselage_height_m')
    if any(type(g[k]) not in (float,int) or not math.isfinite(g[k]) or g[k]<=0 for k in required):
        raise ValueError('总体几何尺寸须为正有限值')
    wing = surface('MainWing',g['wing_area_m2'],g['wing_span_m'],g['tip_chord_m']/g['root_chord_m'],
                   g['wing_quarter_x_m'],-.24*g['fuselage_height_m'],spec=parameters['wing'])
    for key in ('root_chord_m','tip_chord_m','mac_m'):
        if not math.isclose(wing[key],g[key],rel_tol=1e-8):raise ValueError('总体面积、弦长或 MAC 定义不一致')
    tail_x = g['wing_quarter_x_m']+g['tail_arm_m']
    hs,vs = parameters['horizontal_tail'],parameters['vertical_tail']
    ht = surface('HorizontalTail',g['horizontal_tail_area_m2'],math.sqrt(hs['aspect_ratio']*g['horizontal_tail_area_m2']),hs['taper_ratio'],
                 tail_x,.12*g['fuselage_height_m'],spec=hs)
    vt = surface('VerticalTail',g['vertical_tail_area_m2'],math.sqrt(vs['aspect_ratio']*g['vertical_tail_area_m2']),vs['taper_ratio'],
                 tail_x,.2*g['fuselage_height_m'],vertical=True,spec=vs)
    if project.sizing.layout is not None:
        wing['incidence_deg']=project.sizing.layout['wing_incidence_deg']
        ht['incidence_deg']=project.sizing.layout['tail_incidence_deg']
    cg = float(s['cg']['cg_x_m'])
    if not math.isfinite(cg) or not 0<cg<g['fuselage_length_m']:raise ValueError('总体重心站位无效')
    ref = {'area_m2':g['wing_area_m2'],'span_m':g['wing_span_m'],'chord_m':g['mac_m'],
           'moment_reference_geometry_m':[cg,0.,0.], 'moment_reference_body_m':[0.,0.,0.],
           'area_definition':'gross full main-wing planform including fuselage overlap',
           'reference_source':'overall takeoff cg_x_m; cg_y=cg_z=0 are template assumptions'}
    return {'schema_version':1,'name':project.name,'options':asdict(options),
            'parent_run_id':record['run_id'],'parent_input_hash':record['input_hash'],
            'definition_sha256':project.definition_hash(),'parent_status':record['status'],
            'units':{'length':'m','area':'m2','angle':'deg'},
            'coordinates':{'geometry':GEOMETRY_AXES,'body':'x forward, y right, z down; origin at reference CG',
                           'body_origin_geometry_m':[cg,0.,0.],'geometry_to_body_rotation':BODY_ROTATION.tolist()},
            'references':ref,'lifting_surfaces':[wing,ht,vt],
            'fuselage':{'length_m':g['fuselage_length_m'],'width_m':g['fuselage_width_m'],
                        'height_m':g['fuselage_height_m'],
                        'sections_fraction':[[0,0,0],[.18,.85,.9],[.45,1,1],[.8,.45,.5],[1,0,0]]},
            'propeller':{'diameter_m':PROPELLER_DIAMETER_M,'center_m':[-.1,0.,0.],'representation':'unpowered disk'},
            'gear':{'main_x_m':cg+.18*g['mac_m'],'nose_x_m':.15*g['fuselage_length_m'],
                    'half_track_m':.18*g['wing_span_m'],'wheel_center_z_m':-1.15,
                    'fairing_length_m':.55,'fairing_fineness':1.8},
            'assumptions':{'configuration_version':CONFIGURATION_VERSION,
                           'layout':project.sizing.layout,
                           'incidence_convention':'CAD rotates about quarter chord; AVL ANGLE changes tangency on unrotated reference sections per linear theory',
                           'tail_aspect_ratios':[hs['aspect_ratio'],vs['aspect_ratio']],'tail_taper':hs['taper_ratio'],'controls_status':'not_defined',
                           'source':'WingDesignHub conventional_single_v1 concept template; not manufacturer geometry'},
            'analysis_contract':{'status':'geometry_ready_aerodynamics_not_run','flow_condition':None,
                                 'controls':[],'trim_state':None,'propulsion_force_included':False,
                                 'coefficient_conventions':{'force':'body CX,CY,CZ = Fx,Fy,Fz / (q*Sref)',
                                                           'moment':'body Cl,Cm,Cn = L/(q*Sref*Bref), M/(q*Sref*Cref), N/(q*Sref*Bref)',
                                                           'sign':'right-hand rule in body axes; wind lift/drag require the flow attitude',
                                                           'required_before_solve':['density','speed','Mach','Reynolds','alpha','beta','control definition']},
                                 'set_definitions':{'lifting_surfaces':3,'body':4,'baseline_airframe':5,'appearance_only':6},
                                 'component_roles':{'lifting_surfaces':['MainWing','HorizontalTail','VerticalTail'],
                                                    'body':['Fuselage'],
                                                    'appearance_only':['PropellerDisk','Spinner','NoseFairing','LeftFairing','RightFairing',
                                                                       'NoseStrut','LeftStrut','RightStrut']}},
            'limits':LIMITS}
