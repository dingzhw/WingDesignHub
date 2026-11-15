"""Symmetric isolated-wing vertical loads; g and inertia occur exactly once.

n_z = 1 + a_z/g in the local upward frame. Angular acceleration and centrifugal
loads are outside this interface. All masses belong to the prescribed aircraft
mass, so adding fuel here does not silently increase that aircraft mass.
"""
from dataclasses import asdict, dataclass, field, fields, replace
from pathlib import Path
import numpy as np
from .fea_mesh import StructureMeshCase
from .model import WingCase
from .adapters import run_avl
from .mechanics import resultant
from .shell_loads import conservative_transfer
from .service import write_json

G=9.80665


@dataclass(frozen=True)
class FlightLoadCase:
    schema_version: int = 1
    mesh: StructureMeshCase = field(default_factory=lambda:StructureMeshCase(max_edge_m=.2,min_edge_m=.02))
    aircraft_mass_kg: float = 1000.
    load_factor: float = 1.
    ultimate_factor: float = 1.5
    speed_m_s: float = 50.
    density_kg_m3: float = 1.225
    aero_panels: int = 24
    fuel_half_mass_kg: float = 30.
    fuel_start_fraction: float = .1
    fuel_end_fraction: float = .7
    fuel_x_fraction: float = .45
    point_masses: list = field(default_factory=lambda:[{'name':'合成设备','mass_kg':10.,'position_m':[.675,1.5,0.]}])
    stress_allowable_pa: float = 200e6

    def to_dict(self):return asdict(self)

    @classmethod
    def from_dict(cls,data):
        if not isinstance(data,dict) or set(data)-{f.name for f in fields(cls)}:raise ValueError('载荷方案字段无效')
        values=dict(data)
        if 'mesh' in values:values['mesh']=StructureMeshCase.from_dict(values['mesh'])
        case=cls(**values);case.validate();return case

    def validate(self):
        self.mesh.validate()
        if type(self.schema_version) is not int or self.schema_version!=1:raise ValueError('载荷配置版本不支持')
        for key,v in self.to_dict().items():
            if key not in ('mesh','point_masses','schema_version','aero_panels'):
                if isinstance(v,bool) or not isinstance(v,(int,float)) or not np.isfinite(v):raise ValueError(f'{key} 须有限')
        if not 100<=self.aircraft_mass_kg<=5000 or not -2<=self.load_factor<=4 or abs(self.load_factor)<.1:
            raise ValueError('质量限 100–5000 kg；非零法向载荷因数限 -2–4 且绝对值至少 0.1')
        if not 1<=self.ultimate_factor<=2 or not 20<=self.speed_m_s<=100 or not .5<=self.density_kg_m3<=1.4:
            raise ValueError('极限系数、低速条件或空气密度超出模板范围')
        if type(self.aero_panels) is not int or not 8<=self.aero_panels<=100:raise ValueError('AVL 展向面板数限 8–100 整数')
        if self.fuel_half_mass_kg<0 or self.stress_allowable_pa<=0:raise ValueError('质量不得为负，应力限值须为正')
        if not 0<=self.fuel_start_fraction<self.fuel_end_fraction<=1:raise ValueError('燃油展向范围无效')
        if not self.mesh.front_spar_fraction<=self.fuel_x_fraction<=self.mesh.rear_spar_fraction:
            raise ValueError('燃油合力作用点须位于翼盒内')
        if not isinstance(self.point_masses,list):raise ValueError('集中质量须为列表')
        names=set()
        for p in self.point_masses:
            if not isinstance(p,dict) or set(p)!={'name','mass_kg','position_m'}:raise ValueError('集中质量字段无效')
            if not isinstance(p['name'],str) or not p['name'].strip() or p['name'] in names:raise ValueError('集中质量名称须非空且唯一')
            names.add(p['name'])
            mass=p['mass_kg'];pos=p['position_m']
            if isinstance(mass,bool) or not isinstance(mass,(float,int)) or not np.isfinite(mass) or mass<=0:raise ValueError('集中质量须为正有限值')
            if not isinstance(pos,list) or len(pos)!=3 or any(isinstance(v,bool) or not isinstance(v,(float,int)) for v in pos) or not np.isfinite(pos).all():raise ValueError('质量位置须为三个有限坐标')
            if not 0<=pos[0]<=self.mesh.chord_m or not 0<pos[1]<=self.mesh.half_span_m or abs(pos[2])>.2*self.mesh.chord_m:raise ValueError('集中质量超出当前半翼安装范围')


def structural_mass(mesh):
    """Straight S6: exact constant body force quadrature (0 at corners, A/3 at mids).

    Physical element mass/CG and equivalent nodal mass are independently checked.
    The root share stays on the clamp and participates in the reaction balance.
    """
    nodal={n:0. for n in mesh['nodes']};mass=0.;first=np.zeros(3);parts={};visited=set()
    for name,ids in mesh['sets'].items():
        sec=mesh['sections'][name];rho=mesh['materials'][sec['material']]['density_kg_m3'];part=0.
        for eid in ids:
            if eid in visited:raise ValueError('结构质量包含重复单元')
            visited.add(eid);conn=mesh['elements'][eid]
            if mesh['types'][eid]!='S6':raise ValueError('质量卸载仅支持直边 S6')
            p=np.array([mesh['nodes'][n] for n in conn[:3]])
            area=np.linalg.norm(np.cross(p[1]-p[0],p[2]-p[0]))/2
            dm=area*sec['thickness_m']*rho
            if dm<=0:raise ValueError('结构单元质量须为正')
            mass+=dm;part+=dm;first+=dm*p.mean(0)
            for n in conn[3:]:nodal[n]+=dm/3
        parts[name]=part
    if visited!=set(mesh['elements']):raise ValueError('结构质量漏项')
    actual=sum((v*np.array(mesh['nodes'][n]) for n,v in nodal.items()),np.zeros(3))
    if not np.isclose(sum(nodal.values()),mass,rtol=1e-12) or not np.allclose(actual,first,rtol=1e-12,atol=1e-10):
        raise ValueError('结构质量与一阶质量矩不守恒')
    return nodal,{'mass_kg':mass,'cg_m':(first/mass).tolist(),'parts_kg':parts,
                  'nodal_mass_error_kg':sum(nodal.values())-mass,'first_moment_error_kg_m':(actual-first).tolist()}


def aerodynamic_loads(case,executable,work):
    case.validate();work=Path(work);work.mkdir(parents=True,exist_ok=False)
    base=WingCase(span_m=2*case.mesh.half_span_m,chord_m=case.mesh.chord_m,speed_m_s=case.speed_m_s,
                  density_kg_m3=case.density_kg_m3,aero_panels=case.aero_panels)
    q=.5*case.density_kg_m3*case.speed_m_s**2;target=case.aircraft_mass_kg*G*case.load_factor/(q*base.area_m2)
    # Bracket the admitted linear alpha domain; never extrapolate or renormalize strips.
    low=run_avl(replace(base,alpha_deg=-8.),executable,work/'minus8')
    high=run_avl(replace(base,alpha_deg=8.),executable,work/'plus8')
    lo,hi=low['coefficients']['CLtot'],high['coefficients']['CLtot']
    if not lo<=target<=hi or hi<=lo:raise ValueError('目标升力超出 AVL ±8° 线性域，须调整构型/速度/工况')
    lower_alpha,upper_alpha=-8.,8.;history=[]
    for iteration in range(6):
        alpha=lower_alpha+(upper_alpha-lower_alpha)*(target-lo)/(hi-lo)
        r=run_avl(replace(base,alpha_deg=alpha),executable,work/f'target_{iteration}')
        cl=r['coefficients']['CLtot'];history.append({'alpha_deg':alpha,'CL':cl})
        if abs(cl-target)<=2e-5:break
        if cl<target:lower_alpha,lo=alpha,cl
        else:upper_alpha,hi=alpha,cl
    else:raise ValueError('AVL 升力目标迭代未收敛')
    rows=r['right_wing_strips'];p=np.array([[.25*base.chord_m,v['y_m'],0.] for v in rows])
    f=np.array([[0.,0.,q*v['area_m2']*v['cl']] for v in rows])
    expected=case.aircraft_mass_kg*G*case.load_factor/2
    if abs(f[:,2].sum()-expected)>1e-6+.001*abs(expected):raise ValueError('AVL 条带升力与目标载荷偏差超过 0.1%')
    summary={'alpha_deg':alpha,'target_CL':target,'solved_CL':r['coefficients']['CLtot'],'lift_iterations':history,
             'target_half_lift_n':expected,'strip_half_lift_n':float(f[:,2].sum()),
             'lift_relative_error':float(abs(f[:,2].sum()-expected)/abs(expected)),
             'approximation':'strip lift projected entirely onto geometric +z, quarter-chord application; drag and section pitching moment omitted',
             'vertical_projection_relative_bound':float(1-np.cos(np.deg2rad(alpha))),
             'positions_m':p.tolist(),'forces_n':f.tolist(),'reference_area_m2':base.area_m2,
             'reference_chord_m':base.chord_m,'reference_span_m':base.span_m}
    write_json(work/'summary.json',summary);return p,f,summary


def combine_loads(case,mesh,aero_positions,aero_forces):
    case.validate();L,c=case.mesh.half_span_m,case.mesh.chord_m
    nodes=list(mesh['nodes']);index={n:i for i,n in enumerate(nodes)};xyz=np.array([mesh['nodes'][n] for n in nodes])
    total=np.zeros_like(xyz);ledger=[]
    def add(name,p,f,ids=None,nf=None,mass=None):
        source_f,source_m=resultant(p,f)
        if ids is None:ids,nf,_=conservative_transfer(mesh,p,f,np.zeros_like(f),L,c,L/10)
        F,M=resultant([mesh['nodes'][n] for n in ids],nf)
        if not np.all(abs(F-source_f)<=1e-8+.001*abs(source_f)) or not np.all(abs(M-source_m)<=1e-8+.001*abs(source_m)):
            raise ValueError('分项载荷不守恒')
        for n,v in zip(ids,nf):total[index[n]]+=v
        ledger.append({'name':name,'mass_kg':mass,'limit_force_n':source_f.tolist(),'limit_moment_nm':source_m.tolist(),
                       'mapping_force_error_n':float(max(abs(F-source_f))),'mapping_moment_error_nm':float(max(abs(M-source_m)))})
    add('aerodynamic',aero_positions,aero_forces)
    masses,structure=structural_mass(mesh)
    sf=np.zeros_like(xyz);sf[:,2]=-case.load_factor*G*np.array([masses[n] for n in nodes])
    add('structure_gravity_and_inertia',xyz,sf,nodes,sf,structure['mass_kg'])
    if case.fuel_half_mass_kg:
        y=np.linspace(case.fuel_start_fraction,case.fuel_end_fraction,21)
        p=np.array([[case.fuel_x_fraction*c,L*v,0.] for v in (y[:-1]+y[1:])/2])
        f=np.zeros_like(p);f[:,2]=-case.load_factor*G*case.fuel_half_mass_kg/len(p)
        add('fuel_gravity_and_inertia',p,f,mass=case.fuel_half_mass_kg)
    for point in case.point_masses:
        add('point:'+point['name'],np.array([point['position_m']]),np.array([[0,0,-case.load_factor*G*point['mass_kg']]]),mass=point['mass_kg'])
    represented=structure['mass_kg']+case.fuel_half_mass_kg+sum(p['mass_kg'] for p in case.point_masses)
    if 2*represented>case.aircraft_mass_kg:raise ValueError('两侧翼内质量超过整机规定质量，质量台账不一致')
    total*=case.ultimate_factor
    F,M=resultant(xyz,total)
    expected_f=case.ultimate_factor*np.sum([v['limit_force_n'] for v in ledger],axis=0)
    expected_m=case.ultimate_factor*np.sum([v['limit_moment_nm'] for v in ledger],axis=0)
    if not np.allclose(F,expected_f,rtol=1e-10,atol=1e-8) or not np.allclose(M,expected_m,rtol=1e-10,atol=1e-8):raise ValueError('总载荷不守恒')
    fs=max(1.,float(np.linalg.norm(total,axis=1).sum()));ms=fs*max(L,c)
    audit={'input_force_n':expected_f.tolist(),'input_moment_nm':expected_m.tolist(),'force_scale_n':fs,'moment_scale_nm':ms,
           'force_absolute_error_n':float(max(abs(F-expected_f))),'moment_absolute_error_nm':float(max(abs(M-expected_m))),
           'passed':True,'origin_m':[0.,0.,0.]}
    root_f=total[abs(xyz[:,1])<1e-7].sum(0)
    return nodes,total,{'mapping':audit,'components':ledger,'structure_mass':structure,'represented_half_mass_kg':represented,
                       'ultimate_factor':case.ultimate_factor,'root_applied_force_n':root_f.tolist(),
                       'definition':'n_z=1+a_z/g; effective mass force=-m*n_z*g; ultimate factor multiplies complete sum once; no GRAV card',
                       'nodal_ids':nodes,'nodal_forces_n':total.tolist()}
