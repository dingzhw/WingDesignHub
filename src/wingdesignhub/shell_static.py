"""Audited S3 mesh -> straight-sided S6 -> CalculiX linear elastic static solve."""
from dataclasses import dataclass, asdict, field, fields
from pathlib import Path
import copy
import math
import re
import numpy as np
from .fea_mesh import StructureMeshCase, read_inp, audit_mesh
from .shell_loads import conservative_transfer
from .adapters import execute, sha256
from .service import write_json
from .mechanics import resultant


@dataclass(frozen=True)
class StaticWingCase:
    schema_version: int = 1
    mesh: StructureMeshCase = field(default_factory=lambda: StructureMeshCase(max_edge_m=.2,min_edge_m=.02))
    limit_lift_n: float = 5000.
    ultimate_factor: float = 1.5
    load_x_fraction: float = .4
    strip_count: int = 20
    stress_allowable_pa: float = 200e6

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls,data):
        if not isinstance(data,dict) or set(data)-{f.name for f in fields(cls)}:
            raise ValueError('静力配置包含未知字段或格式错误')
        values=dict(data)
        if 'mesh' in values: values['mesh']=StructureMeshCase.from_dict(values['mesh'])
        obj=cls(**values);obj.validate();return obj

    def validate(self):
        if type(self.schema_version) is not int or self.schema_version!=1:
            raise ValueError('静力配置版本不支持')
        self.mesh.validate()
        if type(self.strip_count) is not int or not 5<=self.strip_count<=100:
            raise ValueError('条带数须为 5–100 整数')
        for key in ('limit_lift_n','ultimate_factor','load_x_fraction','stress_allowable_pa'):
            x=getattr(self,key)
            if isinstance(x,bool) or not isinstance(x,(float,int)) or not math.isfinite(x):
                raise ValueError(f'{key} 须为有限数值')
        if not 0<abs(self.limit_lift_n)<=20000 or not 1<=self.ultimate_factor<=2:
            raise ValueError('合成工况限非零半翼载荷 ±20000 N、载荷系数 1–2')
        if not .15<=self.load_x_fraction<=.8 or self.stress_allowable_pa<=0:
            raise ValueError('载荷位置或规定应力限值无效')


def promote_s6(mesh):
    """Shared edge midpoints preserve the audited faceted geometry and connectivity."""
    out=copy.deepcopy(mesh);edges={};next_id=max(out['nodes'])+1
    for eid,conn in mesh['elements'].items():
        if mesh['types'][eid]!='S3': raise ValueError('静力模板仅接受已检查的 S3 原始网格')
        mids=[]
        for a,b in ((conn[0],conn[1]),(conn[1],conn[2]),(conn[2],conn[0])):
            key=tuple(sorted((a,b)))
            if key not in edges:
                edges[key]=next_id
                out['nodes'][next_id]=((np.array(mesh['nodes'][a])+mesh['nodes'][b])/2).tolist()
                next_id+=1
            mids.append(edges[key])
        out['elements'][eid]=list(conn)+mids;out['types'][eid]='S6'
    return out


def set_lines(ids):
    ids=list(ids)
    return [','.join(map(str,ids[i:i+16])) for i in range(0,len(ids),16)]


def ccx_number(value):
    """CalculiX data fields are limited to 20 characters; never truncate exponents."""
    if not math.isfinite(value):raise ValueError('CalculiX 输入数值须有限')
    text=f'{value:.12e}'
    if len(text)>20:raise ValueError('CalculiX 数值字段超过 20 字符')
    return text


def static_deck(mesh,ids,forces,allow_root_loads=False,root_support='clamped'):
    if root_support not in ('clamped','translations_fixed'):
        raise ValueError('根部支承类型无效')
    root=[n for n,p in mesh['nodes'].items() if abs(p[1])<1e-7]
    if len(root)<3: raise ValueError('缺少根部固支截面节点')
    if not allow_root_loads and any(n in root and np.linalg.norm(f)>1e-9 for n,f in zip(ids,forces)):
        raise ValueError('禁止将外载直接施加于固支节点')
    lines=['*HEADING','WingDesignHub synthetic half-wing; SI; linear static; S6','*NODE']
    lines += [f'{n},'+','.join(ccx_number(v) for v in p) for n,p in mesh['nodes'].items()]
    for name,eids in mesh['sets'].items():
        lines += [f'*ELEMENT,TYPE=S6,ELSET={name}']
        lines += [f'{eid},'+','.join(map(str,mesh['elements'][eid])) for eid in eids]
    for name,mat in mesh['materials'].items():
        lines += [f'*MATERIAL,NAME={name}','*ELASTIC',f"{ccx_number(mat['elastic_modulus_pa'])},{ccx_number(mat['poisson_ratio'])}",
                  '*DENSITY',ccx_number(mat['density_kg_m3'])]
    for name,sec in mesh['sections'].items():
        lines += [f"*SHELL SECTION,ELSET={name},MATERIAL={sec['material']}",ccx_number(sec['thickness_m'])]
    lines += ['*NSET,NSET=ROOT']+set_lines(root)+['*NSET,NSET=ALL']+set_lines(mesh['nodes'])
    lines += ['*ELSET,ELSET=ALL']+list(mesh['sets'])
    lines += ['*BOUNDARY','ROOT,1,6' if root_support=='clamped' else 'ROOT,1,3','*STEP','*STATIC','*CLOAD']
    lines += [f'{n},{j+1},{ccx_number(v)}' for n,f in zip(ids,forces) for j,v in enumerate(f) if v!=0.]
    lines += ['*NODE PRINT,NSET=ALL','U','*EL PRINT,ELSET=ALL,GLOBAL=YES','S',
              '*NODE FILE,OUTPUT=3D','U,RF','*EL FILE','S','*END STEP']
    return '\n'.join(lines)+'\n',root


def read_dat(path,mesh):
    modes={'displacements (':'u','stresses (':'s'};mode=None;u={};stress={};headers=[]
    for line in Path(path).read_text().splitlines():
        for heading,value in modes.items():
            if line.strip().startswith(heading):
                mode=value;headers.append(value)
        v=line.split()
        if not v or not v[0].isdigit():continue
        if mode=='u' and len(v)==4:
            key=int(v[0])
            if key in u:raise ValueError('位移包含重复节点/多步结果')
            u[key]=[float(x.replace('D','E')) for x in v[1:]]
        elif mode=='s' and len(v)>=8:
            key=(int(v[0]),int(v[1]))
            if key in stress:raise ValueError('应力包含重复积分点/多步结果')
            stress[key]=[float(x.replace('D','E')) for x in v[2:8]]
    if headers!=['u','s'] or set(u)!=set(mesh['nodes']) or {e for e,i in stress}!=set(mesh['elements']):
        raise ValueError('缺少完整单步位移/积分点应力输出')
    if not np.isfinite(list(u.values())).all() or not np.isfinite(list(stress.values())).all():
        raise ValueError('位移或应力包含非有限值')
    return u,stress


def read_frd_balance(path):
    """3D RF includes loads and constraints; sum the complete expanded model.

    Never call averaged RF at original shell nodes a complete support reaction.
    Windows FRD may overflow E12.5 to 13 chars for negative 3-digit exponents.
    """
    xyz={};rf={};mode=None;blocks=0
    for line in Path(path).read_text().splitlines():
        if line.startswith('    2C'):mode='xyz'
        if line.startswith(' -4'):
            mode='rf' if 'FORC' in line else None
            if mode=='rf':blocks+=1
        if line.startswith(' -3'):mode=None
        if line.startswith(' -1') and mode:
            node=int(line[3:13])
            values=[float(v.replace('D','E')) for v in re.findall(r'[-+]?\d\.\d{5}[EeDd][-+]\d{2,3}',line[13:])]
            if len(values)!=3 or not np.isfinite(values).all():raise ValueError('FRD 坐标/力格式或数值无效')
            target=xyz if mode=='xyz' else rf
            if node in target:raise ValueError('FRD 存在重复结果')
            target[node]=values
    if blocks!=1 or not xyz or set(xyz)!=set(rf):raise ValueError('缺少完整展开节点的单步 RF 输出')
    p=np.array([xyz[n] for n in rf]);f=np.array(list(rf.values()))
    return {'force_residual_n':f.sum(0).tolist(),'moment_residual_nm':np.cross(p,f).sum(0).tolist(),
            'coordinate_min_m':p.min(0).tolist(),'coordinate_max_m':p.max(0).tolist(),
            'expanded_nodes':len(rf),'method':'global expanded RF resultant, including applied forces and constraint forces'}


def von_mises(values):
    a=np.asarray(values,float);x,y,z,xy,xz,yz=a.T
    return np.sqrt(.5*((x-y)**2+(y-z)**2+(z-x)**2)+3*(xy**2+xz**2+yz**2))


def solve_shell(executable,work,mesh,ids,forces,length,load_audit,allow_root_loads=False,root_support='clamped'):
    work=Path(work);work.mkdir(parents=True,exist_ok=False)
    deck,fixed=static_deck(mesh,ids,forces,allow_root_loads,root_support);(work/'wing.inp').write_text(deck,encoding='ascii')
    serialized_points=[[float(ccx_number(v)) for v in mesh['nodes'][n]] for n in ids]
    serialized_forces=[[float(ccx_number(v)) for v in f] for f in forces]
    actual_f,actual_m=resultant(serialized_points,serialized_forces)
    expected_f=np.array(load_audit['input_force_n']);expected_m=np.array(load_audit['input_moment_nm'])
    if not (np.all(abs(actual_f-expected_f)<=1e-8+1e-10*abs(expected_f)) and
            np.all(abs(actual_m-expected_m)<=1e-8+1e-10*abs(expected_m))):
        raise ValueError('写入求解器后的数值未保持规定载荷合力矩')
    log=execute([str(executable),'wing'],work,timeout=180)
    version=re.search(r'Version\s+([\d.]+)',log)
    if not version or version[1]!='2.23' or 'Job finished' not in log or re.search(r'\*ERROR|\*WARNING|opposite normals',log,re.I):
        raise ValueError('CalculiX 版本、结束状态或诊断异常，请查日志')
    u,stress=read_dat(work/'wing.dat',mesh)
    balance=read_frd_balance(work/'wing.frd')
    points=np.array(list(mesh['nodes'].values()))
    allowance=max(s['thickness_m'] for s in mesh['sections'].values())+1e-4
    if np.any(np.array(balance['coordinate_min_m'])<points.min(0)-allowance) or np.any(np.array(balance['coordinate_max_m'])>points.max(0)+allowance):
        raise ValueError('求解器展开几何超出预期厚度范围，须核查输入格式或壳法向')
    force_error=max(abs(x) for x in balance['force_residual_n'])/load_audit['force_scale_n']
    moment_error=max(abs(x) for x in balance['moment_residual_nm'])/load_audit['moment_scale_nm']
    if max(force_error,moment_error)>.001:raise ValueError('展开模型合力/力矩平衡残差超出 0.1%')
    tip=[n for n,p in mesh['nodes'].items() if abs(p[1]-length)<1e-7]
    if not tip:raise ValueError('翼尖节点缺失')
    vm=von_mises(list(stress.values()))
    # Exclude clamp and tip regions for a separate, explicitly defined mesh statistic.
    bulk=[v for (e,i),v in zip(stress,vm) if .1*length < np.mean([mesh['nodes'][n][1] for n in mesh['elements'][e][:3]]) < .9*length]
    if not bulk:raise ValueError('缺少远离根/尖部的应力样本')
    root_u=max(np.linalg.norm(u[n]) for n in fixed)
    if root_u>1e-9:raise ValueError('固支节点位移不为零')
    out={'solver_version':'2.23','solver_sha256':sha256(executable),'element':'S6',
         'nodes':len(mesh['nodes']),'elements':len(mesh['elements']),'fixed_nodes':len(fixed),'root_support':root_support,
         'root_displacement_max_m':float(root_u),'tip_mean_z_m':float(np.mean([u[n][2] for n in tip])),
         'max_displacement_m':float(max(np.linalg.norm(v) for v in u.values())),
         'peak_von_mises_pa':float(max(vm)),'bulk_von_mises_p95_pa':float(np.quantile(bulk,.95)),
         'stress_location':'expanded element integration points; bulk statistic uses 10%<element centroid y/span<90%',
         'balance':{**balance,'force_scaled_error':force_error,'moment_scaled_error':moment_error},
         'serialized_load_errors':{'force_n':(actual_f-expected_f).tolist(),'moment_nm':(actual_m-expected_m).tolist()},
         'root_resultant_from_prescribed_load_balance':{
             'force_n':(-np.array(load_audit['input_force_n'])).tolist(),
             'moment_nm':(-np.array(load_audit['input_moment_nm'])).tolist(),
             'source':'negative prescribed resultant, not independently measured support reactions'}}
    write_json(work/'nodal_displacement.json',u);write_json(work/'summary.json',out)
    return out


def run_static_case(case,mesh_path,executable,work):
    case.validate();work=Path(work);work.mkdir(parents=True,exist_ok=False)
    linear=read_inp(mesh_path);metrics=audit_mesh(linear,case.mesh);mesh=promote_s6(linear)
    count=case.strip_count;length=case.mesh.half_span_m
    pos=np.zeros((count,3));pos[:,0]=case.load_x_fraction*case.mesh.chord_m
    pos[:,1]=(np.arange(count)+.5)*length/count
    f=np.zeros_like(pos);f[:,2]=case.limit_lift_n*case.ultimate_factor/count
    m=np.zeros_like(pos);width=length/10
    ids,forces,audit=conservative_transfer(mesh,pos,f,m,length,case.mesh.chord_m,width)
    write_json(work/'input.json',case.to_dict())
    write_json(work/'loads.json',{'kind':'prescribed uniform strip resultants','positions_m':pos.tolist(),
        'forces_n':f.tolist(),'moments_nm':m.tolist(),'nodal_ids':ids.tolist(),'nodal_forces_n':forces.tolist(),
        'patch_half_width_m':width,'support_cutoff':1.5,'mapping':audit,'source_mesh_sha256':sha256(mesh_path)})
    r=solve_shell(executable,work/'solve',mesh,ids,forces,length,audit)
    ratio=r['max_displacement_m']/length
    r.update(mapping=audit,mesh_metrics=metrics,load_definition='limit half-wing force times ultimate_factor, applied once',
        boundary='all six DOF fixed at every root-section shell node; no self weight, fuel, engine or thermal load',
        stress_allowable_pa=case.stress_allowable_pa,yield_margin=case.stress_allowable_pa/r['peak_von_mises_pa']-1.,
        displacement_span_ratio=ratio,physical_validation_passed=False,strength_certified=False,mesh_sensitivity_checked=False,
        limits=['规定均布条带合力；未计算全机机动/阵风载荷或配平',
                'S3 曲面网格保留折面形状，插入共享中边节点形成 S6；未恢复精确曲面',
                '线弹性小变形；未含屈曲、疲劳、塑性、连接件和制造余量',
                '应力限值为合成输入；峰值含根部/交线局部效应，不能直接用于真实飞机定尺寸',
                '根部等效合力矩由规定载荷求得；独立求解平衡检查采用全模型展开节点 RF'])
    r['status']='static_checked' if r['yield_margin']>=0 and ratio<=.05 else 'executed_with_limits'
    if r['yield_margin']<0:r['limits'].append('峰值应力超过当前规定限值')
    if ratio>.05:r['limits'].append('位移超过半翼展 5%，小变形适用性需复核')
    write_json(work/'summary.json',r);return r
