"""AVL lifting-surface contract, in SI; no mission-polar replacement or trim solve."""
from dataclasses import dataclass, asdict
import math
import numpy as np
from .sizing_physics import density, G

LIMITS = [
    '联合机翼、平尾、垂尾的无黏小迎角基线；机身、短舱、起落架气动力和螺旋桨滑流尚未计入。',
    'CDff 为远场诱导阻力；未加入翼型黏性、机身寄生阻力，不作为全机总阻力或航程更新依据。',
    '首期工况限 |迎角|≤6°、|侧滑|≤5°、|舵偏|≤10°、Mach≤0.3，零角速度、定常附着流；不预测失速。',
    '安装角、扭转继承几何；舵面为 conventional_controls_v1 概念假设，法向倾转模拟，CAD 外形未切割或转动舵面。',
    '条带接口保留原始局部系数，输出轴向/法向投影及弦向俯仰偶矩；缺少展向切向力与其余局部偶矩，完整六分量以 AVL 总力为准。',
    '配平接口给出当前固定迎角/舵偏的升力与俯仰残差、局部导数；尚未求配平、操纵余量或重心包线。',
    '局部导数采用 AVL 原生近似；基准升降舵升力导数与收敛差分相差约 0.14%，后续配平以实际残差和受控差分复核。',
]
CONTROL_TEMPLATE = [
    dict(name='aileron', surface='MainWing', span_start=.65, span_end=1., hinge_xc=.75,
         gain=-1., hinge_vector=[0.,1.,0.], duplicate_sign=-1., positive='右副翼后缘向上、左副翼向下'),
    dict(name='elevator', surface='HorizontalTail', span_start=0., span_end=1., hinge_xc=.70,
         gain=1., hinge_vector=[0.,1.,0.], duplicate_sign=1., positive='两侧升降舵后缘向下'),
    dict(name='rudder', surface='VerticalTail', span_start=0., span_end=1., hinge_xc=.70,
         gain=1., hinge_vector=[0.,0.,1.], duplicate_sign=1., positive='方向舵后缘向右'),
]


@dataclass(frozen=True)
class AeroOptions:
    alpha_deg: float = 3.
    beta_deg: float = 0.
    aileron_deg: float = 0.
    elevator_deg: float = 0.
    rudder_deg: float = 0.
    speed_m_s: float | None = None
    altitude_m: float | None = None
    mass_kg: float | None = None
    mesh_level: int = 2

    def validate(self):
        if type(self.mesh_level) is not int or self.mesh_level not in (1,2,3):
            raise ValueError('气动离散级别须为 1、2 或 3')
        bounds={'alpha_deg':(-6,6),'beta_deg':(-5,5),'aileron_deg':(-10,10),
                'elevator_deg':(-10,10),'rudder_deg':(-10,10),'speed_m_s':(20,120),
                'altitude_m':(0,4000),'mass_kg':(1,10000)}
        for name,(lo,hi) in bounds.items():
            v=getattr(self,name)
            if v is None and name in ('speed_m_s','altitude_m','mass_kg'):continue
            if type(v) not in (int,float) or not math.isfinite(v) or not lo<=v<=hi:
                raise ValueError(f'{name} 超出本版范围 [{lo}, {hi}]')


def make_contract(interface, project, sizing_summary, options=None):
    o=AeroOptions(**options) if isinstance(options,dict) else (options or AeroOptions());o.validate()
    if interface.get('schema_version')!=1:raise ValueError('气动几何接口版本不支持')
    surfaces=interface['surfaces'];refs=interface['references']
    if [s['name'] for s in surfaces]!=['MainWing','HorizontalTail','VerticalTail']:
        raise ValueError('本版只接收常规机翼/平尾/垂尾构型')
    # Keep the exporter narrow: reject unsupported topology rather than silently flatten it.
    for s in surfaces:
        if len(s['sections'])!=2 or any(s[k]!=0 for k in ('incidence_deg','twist_deg','dihedral_deg','quarter_sweep_deg')):
            raise ValueError('本版接收已验证的零安装角/扭转/上反及四分之一弦无后掠模板')
    values=np.array([refs['area_m2'],refs['span_m'],refs['chord_m'],*refs['moment_reference_geometry_m']],float)
    if not np.isfinite(values).all() or min(values[:3])<=0:raise ValueError('气动参考量无效')
    v=o.speed_m_s if o.speed_m_s is not None else sizing_summary['mission']['cruise_speed_used_m_s']
    h=o.altitude_m if o.altitude_m is not None else project.assumptions.cruise_altitude_m
    mass=o.mass_kg if o.mass_kg is not None else sizing_summary['design_mtow_kg']
    if not 20<=v<=120 or not 0<=h<=4000 or not 0<mass<=sizing_summary['design_mtow_kg']:
        raise ValueError('工况速度/高度越界，或工况质量大于设计起飞重量')
    temperature=288.15-.0065*h;rho=density(h);mu=1.716e-5*(temperature/273.15)**1.5*(273.15+110.4)/(temperature+110.4)
    mach=v/math.sqrt(1.4*287.05287*temperature)
    if mach>.3:raise ValueError('Mach 超过本版 0.3 范围')
    flow={'speed_m_s':v,'altitude_m':h,'density_kg_m3':rho,'temperature_k':temperature,
          'dynamic_viscosity_pa_s':mu,'mach':mach,'reynolds_mac':rho*v*refs['chord_m']/mu,
          'dynamic_pressure_pa':.5*rho*v*v,'alpha_deg':o.alpha_deg,'beta_deg':o.beta_deg,
          'body_rates_rad_s':[0.,0.,0.],'atmosphere':'ISA troposphere; Sutherland viscosity; Re metadata only',
          'mass_kg':mass,'mass_source':'explicit operating mass' if o.mass_kg is not None else 'design MTOW assumption'}
    return {'schema_version':1,'model':'avl_lifting_surfaces_v1','control_template':'conventional_controls_v1',
            'geometry_run_id':interface['source_run_id'],'sizing_run_id':interface['parent_run_id'],
            'references':refs,'coordinates':interface['coordinates'],'surfaces':surfaces,
            'controls':CONTROL_TEMPLATE,'flow':flow,'options':asdict(o),'limits':LIMITS,
            'incidence_source':'unchanged from checked OpenVSP geometry',
            'excluded_components':['Fuselage','Spinner','PropellerDisk','LandingGear'],
            'propulsion_included':False,'viscous_drag_included':False,'mission_polar_updated':False}


def avl_input(contract):
    r=contract['references'];level=contract['options']['mesh_level']
    n,m=[(8,16),(12,24),(18,36)][level-1]
    lines=['WingDesignHub full lifting surfaces',f"{contract['flow']['mach']:.15g}",'0 0 0',
           f"{r['area_m2']:.15g} {r['chord_m']:.15g} {r['span_m']:.15g}",
           ' '.join(f'{v:.15g}' for v in r['moment_reference_geometry_m']),'0.0']
    for index,s in enumerate(contract['surfaces'],1):
        ctrl=next(c for c in contract['controls'] if c['surface']==s['name'])
        lines+=['SURFACE',s['name'],f'{n} 1.0 {m} 1.0','COMPONENT',str(index)]
        if s['symmetric']:lines+=['YDUPLICATE','0.0']
        lines+=['ANGLE',str(s['incidence_deg'])]
        a,b=s['sections'];pa=np.array(a['leading_edge_m']);pb=np.array(b['leading_edge_m'])
        for fraction in sorted({0.,ctrl['span_start'],ctrl['span_end'],1.}):
            pos=pa+(pb-pa)*fraction;chord=a['chord_m']+(b['chord_m']-a['chord_m'])*fraction
            twist=a['twist_deg']+(b['twist_deg']-a['twist_deg'])*fraction
            lines+=['SECTION',' '.join(f'{x:.15g}' for x in [*pos,chord,twist]),'NACA',s['naca']]
            if ctrl['span_start']<=fraction<=ctrl['span_end']:
                lines+=['CONTROL',f"{ctrl['name']} {ctrl['gain']} {ctrl['hinge_xc']} "+
                        ' '.join(map(str,ctrl['hinge_vector']))+f" {ctrl['duplicate_sign']}"]
    return '\n'.join(lines)+'\n'


def commands(contract):
    f=contract['flow'];o=contract['options']
    text=(f"LOAD model.avl\nOPER\nM\nMN {f['mach']}\nV {f['speed_m_s']}\nD {f['density_kg_m3']}\n"
          f"G {G}\nM {f['mass_kg']}\n\nA A {f['alpha_deg']}\nB B {f['beta_deg']}\nR R 0\nP P 0\nY Y 0\n")
    for i,c in enumerate(contract['controls'],1):text+=f"D{i} D{i} {o[c['name']+'_deg']}\n"
    return text+'X\nS\ncase.run\nMRF\nFT\ntotal.mrf\nFS\nstrips.mrf\nFE\nelements.mrf\nST\nstability.mrf\n\nQUIT\n'


def trim_interface(contract, coefficients, derivatives):
    f=contract['flow'];r=contract['references'];target=f['mass_kg']*G/(f['dynamic_pressure_pa']*r['area_m2'])
    return {'status':'not_trimmed','unknowns_next_stage':['alpha_deg','elevator_deg'],
            'fixed_inputs':f,'control_deflections_deg':{c['name']:contract['options'][c['name']+'_deg'] for c in contract['controls']},
            'moment_reference_geometry_m':r['moment_reference_geometry_m'],
            'level_flight_target_cl':target,'residual_cl':coefficients['CLtot']-target,'residual_cm':coefficients['Cmtot'],
            'local_jacobian_per_degree':[[derivatives['CLa']*math.pi/180,derivatives['CLd'][1]],
                                         [derivatives['Cma']*math.pi/180,derivatives['Cmd'][1]]],
            'jacobian_scope':'native AVL approximate derivatives, verify actual residuals in future trim iterations',
            'included':'lifting surfaces only; target CL assumes level flight at stated operating mass',
            'missing':['fuselage forces/moments','propulsion forces/moments','viscous drag','trim iteration and control limits']}
