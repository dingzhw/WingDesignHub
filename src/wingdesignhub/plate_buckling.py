"""CalculiX 2.23 linear eigenvalue buckling of an isotropic representative plate.

Coordinates: x across panel width, y along panel length, z normal. Compression
is positive input; traction on all four edges comes from one uniform stress
tensor, ensuring equilibrated membrane loading. Eigenmodes are normalized shapes.
"""
from dataclasses import asdict,dataclass,fields,replace
from pathlib import Path
import math
import re
import numpy as np
from .adapters import execute,sha256
from .buckling import plate_screen
from .shell_static import ccx_number,set_lines
from .mechanics import resultant
from .service import write_json


@dataclass(frozen=True)
class PlateCase:
    schema_version: int = 1
    length_m: float = .5
    width_m: float = .6
    thickness_m: float = .002
    elastic_modulus_pa: float = 70e9
    poisson_ratio: float = .33
    compression_pa: float = 1e6
    shear_pa: float = 0.
    support: str = 'simply_supported'
    divisions: int = 16
    modes: int = 3

    def to_dict(self):return asdict(self)

    @classmethod
    def from_dict(cls,data):
        if not isinstance(data,dict) or set(data)-{f.name for f in fields(cls)}:raise ValueError('代表板配置字段无效')
        obj=cls(**data);obj.validate();return obj

    def validate(self):
        if type(self.schema_version) is not int or self.schema_version!=1:raise ValueError('代表板配置版本无效')
        if self.support not in ('simply_supported','clamped'):raise ValueError('板支承类型无效')
        for k in ('length_m','width_m','thickness_m','elastic_modulus_pa','poisson_ratio','compression_pa','shear_pa'):
            v=getattr(self,k)
            if isinstance(v,bool) or not isinstance(v,(float,int)) or not math.isfinite(v):raise ValueError('代表板参数须有限')
        if not .05<=self.length_m<=3 or not .05<=self.width_m<=3 or not 0<self.thickness_m<=.05*min(self.width_m,self.length_m):raise ValueError('超出薄板尺寸范围')
        if self.elastic_modulus_pa<=0 or not 0<=self.poisson_ratio<.5 or self.compression_pa<0 or self.compression_pa+abs(self.shear_pa)==0:raise ValueError('材料或参考膜应力无效')
        if type(self.divisions) is not int or not 4<=self.divisions<=48 or type(self.modes) is not int or not 1<=self.modes<=6:raise ValueError('板网格分段或模态数无效')
        if not .2<=self.length_m/self.width_m<=5:raise ValueError('代表板长宽比限 0.2–5')


def plate_model(case):
    case.validate();nx=case.divisions;ny=max(4,round(nx*case.length_m/case.width_m))
    nodes={};grid={}
    for j in range(2*ny+1):
        for i in range(2*nx+1):
            if i%2 and j%2:continue
            n=len(nodes)+1;grid[i,j]=n;nodes[n]=[i*case.width_m/(2*nx),j*case.length_m/(2*ny),0.]
    elements={}
    for j in range(ny):
        for i in range(nx):
            ix,iy=2*i,2*j
            elements[len(elements)+1]=[grid[ix+di,iy+dj] for di,dj in ((0,0),(2,0),(2,2),(0,2),(1,0),(2,1),(1,2),(0,1))]
    boundary={name:[] for name in ('left','right','bottom','top')};forces={n:np.zeros(3) for n in nodes}
    for name,axis,fixed,count,normal in (('left',1,0,ny,[-1,0]),('right',1,2*nx,ny,[1,0]),
                                        ('bottom',0,0,nx,[0,-1]),('top',0,2*ny,nx,[0,1])):
        ids=[grid[fixed,k] if axis==1 else grid[k,fixed] for k in range(2*count+1)]
        boundary[name]=ids
        stress=np.array([[0.,case.shear_pa],[case.shear_pa,-case.compression_pa]])
        traction=np.r_[stress@normal,0.]*case.thickness_m
        for k in range(count):
            a,m,b=ids[2*k:2*k+3];length=np.linalg.norm(np.array(nodes[b])-nodes[a])
            for n,w in ((a,1/6),(m,2/3),(b,1/6)):forces[n]+=traction*length*w
    F,M=resultant(list(nodes.values()),list(forces.values()))
    if max(abs(F).max(),abs(M).max())>1e-8:raise ValueError('代表板参考边载不自平衡')
    return {'nodes':nodes,'elements':elements,'boundary':boundary,'forces':forces,'anchor':grid[0,0],
            'rotation_anchor':grid[2*nx,0],'nx':nx,'ny':ny,'force_residual_n':F.tolist(),'moment_residual_nm':M.tolist()}


def plate_deck(case,model):
    nodes=model['nodes'];edges=sorted(set(n for ids in model['boundary'].values() for n in ids))
    lines=['*HEADING','WingDesignHub representative flat plate; SI; linear buckling','*NODE']
    lines += [f'{n},'+','.join(ccx_number(v) for v in p) for n,p in nodes.items()]
    lines += ['*ELEMENT,TYPE=S8R,ELSET=PLATE']+[f'{e},'+','.join(map(str,conn)) for e,conn in model['elements'].items()]
    lines += ['*MATERIAL,NAME=METAL','*ELASTIC',f'{ccx_number(case.elastic_modulus_pa)},{ccx_number(case.poisson_ratio)}',
              '*SHELL SECTION,ELSET=PLATE,MATERIAL=METAL',ccx_number(case.thickness_m),
              '*NSET,NSET=ALL']+set_lines(nodes)+['*NSET,NSET=EDGE']+set_lines(edges)
    # Minimal in-plane restraints remove three rigid modes; transverse motion is
    # zero along every edge. Clamped comparison adds both bending rotations.
    lines += ['*BOUNDARY','EDGE,3,3',f"{model['anchor']},1,2",f"{model['rotation_anchor']},2,2"]
    if case.support=='clamped':lines += ['EDGE,4,5']
    lines += ['*STEP','*BUCKLE',f'{case.modes},1.e-8,{max(12,4*case.modes)},1000','*CLOAD']
    lines += [f'{n},{i+1},{ccx_number(v)}' for n,f in model['forces'].items() for i,v in enumerate(f) if v!=0]
    lines += ['*NODE FILE,OUTPUT=2D','U','*END STEP']
    return '\n'.join(lines)+'\n'


def read_factors(path,count):
    values=[];reading=False
    for line in Path(path).read_text().splitlines():
        if 'BUCKLINGFACTOROUTPUT' in ''.join(line.upper().split()):
            if reading:raise ValueError('不支持多步屈曲输出')
            reading=True;continue
        fields=line.split()
        if reading and len(fields)==2 and fields[0].isdigit():
            values.append((int(fields[0]),float(fields[1].replace('D','E'))))
    if len(values)!=count or [i for i,v in values]!=list(range(1,count+1)) or not np.isfinite([v for i,v in values]).all():raise ValueError('屈曲系数输出缺失、重复或非有限')
    if any(v<=0 for i,v in values):raise ValueError('存在非正屈曲系数，须检查参考载荷方向/模态选择')
    return [v for i,v in values]


def read_modes(path,model,factors):
    blocks=[];block=None;frame_values=[]
    for line in Path(path).read_text().splitlines():
        if line.startswith('  100CL'):frame_values.append(float(line[12:24]))
        if line.startswith(' -4'):
            block={} if 'DISP' in line else None
            if block is not None:blocks.append(block)
        elif line.startswith(' -3'):block=None
        elif line.startswith(' -1') and block is not None:
            node=int(line[3:13]);v=[float(x.replace('D','E')) for x in re.findall(r'[-+]?\d\.\d{5}[EeDd][-+]\d{2,3}',line[13:])]
            if node in block or len(v)!=3 or not np.isfinite(v).all():raise ValueError('屈曲模态格式无效')
            block[node]=v
    if len(blocks)!=len(factors)+1 or any(set(b)!=set(model['nodes']) for b in blocks):raise ValueError('屈曲模态节点输出不完整')
    if len(frame_values)!=len(blocks) or frame_values[0]!=0 or not np.allclose(frame_values[1:],factors,rtol=1e-6):raise ValueError('FRD 模态与 DAT 屈曲系数不一致')
    base=blocks.pop(0)
    edges=set(n for ids in model['boundary'].values() for n in ids);summaries=[]
    for b in blocks:
        peak=max(abs(v[2]) for v in b.values())
        if peak<1e-10:raise ValueError('未检出板面外屈曲模态')
        edge=max(abs(b[n][2]) for n in edges)/peak
        if edge>1e-6:raise ValueError('板边模态未满足横向支承')
        summaries.append({'max_normalized_transverse_amplitude':peak,'edge_transverse_relative_residual':edge})
    return blocks,summaries,base


def run_plate(case,executable,work,reference_scale=None):
    if isinstance(case,dict):case=PlateCase.from_dict(case)
    case.validate();work=Path(work);work.mkdir(parents=True,exist_ok=False)
    screen=plate_screen(case.length_m,case.width_m,case.thickness_m,case.elastic_modulus_pa,case.poisson_ratio,-case.compression_pa,case.shear_pa)
    # CCX/ARPACK searches around shift 1. A load already above the lowest critical
    # value can return a higher mode near 1. Keep the estimated lowest factor >=100
    # in the native problem and convert back to the actual requested stress tensor.
    safe_scale=min(1.,.01*screen['proportional_load_factor_to_buckling'])
    scale=safe_scale if reference_scale is None else reference_scale
    if isinstance(scale,bool) or not isinstance(scale,(int,float)) or not math.isfinite(scale) or not 0<scale<=safe_scale:
        raise ValueError('屈曲求解参考载荷比例须为正且不高于安全归一化值')
    native=replace(case,compression_pa=case.compression_pa*scale,shear_pa=case.shear_pa*scale)
    model=plate_model(native);write_json(work/'input.json',case.to_dict())
    write_json(work/'solver_reference.json',{'scale':scale,'native_input':native.to_dict(),'factor_conversion':'physical_factor = native_factor * scale'})
    (work/'plate.inp').write_text(plate_deck(native,model),encoding='ascii')
    log=execute([str(executable),'plate'],work,timeout=180)
    if not re.search(r'Version\s+2\.23\b',log) or 'Job finished' not in log or re.search(r'\*ERROR|\*WARNING',log,re.I):raise ValueError('CalculiX 屈曲求解诊断异常')
    native_factors=read_factors(work/'plate.dat',case.modes)
    if native_factors[0]<=5:raise ValueError('特征值过于接近求解器搜索偏移，不能确认最低模态')
    factors=[v*scale for v in native_factors]
    modes,mode_checks,base=read_modes(work/'plate.frd',model,native_factors)
    # Independently verify the pre-buckling membrane state before using its eigenvalues.
    xyz=np.array([model['nodes'][n] for n in base]);u=np.array(list(base.values()))
    fit=np.linalg.lstsq(np.column_stack((xyz[:,:2],np.ones(len(xyz)))),u[:,:2],rcond=None)[0]
    strain=np.array([fit[0,0],fit[1,1],fit[1,0]+fit[0,1]])
    expected=np.array([native.poisson_ratio*native.compression_pa,-native.compression_pa,2*(1+native.poisson_ratio)*native.shear_pa])/native.elastic_modulus_pa
    if not np.allclose(strain,expected,rtol=.001,atol=1e-10) or np.max(abs(u[:,2]))>1e-8:raise ValueError('参考载荷下膜应变与解析应力状态不一致')
    write_json(work/'first_mode.json',{'coordinates_m':model['nodes'],'normalized_displacement':modes[0],'eigenvalue':factors[0]})
    # A normalized transverse mode map, never a physical displacement magnitude.
    peak=max(abs(v[2]) for v in modes[0].values());polygons=[];plot_scale=400/max(case.width_m,case.length_m)
    for conn in model['elements'].values():
        value=sum(modes[0][n][2] for n in conn[:4])/(4*peak)
        faded=round(255*(1-abs(value)))
        color=f'rgb(255,{faded},{faded})' if value>=0 else f'rgb({faded},{faded},255)'
        points=' '.join(f"{50+plot_scale*model['nodes'][n][0]:.3f},{460-plot_scale*model['nodes'][n][1]:.3f}" for n in conn[:4])
        polygons.append(f'<polygon points="{points}" fill="{color}" stroke="none"/>')
    svg='<svg xmlns="http://www.w3.org/2000/svg" width="540" height="530" viewBox="0 0 540 530"><rect width="540" height="530" fill="white"/>'
    svg+=f'<text x="35" y="25" font-size="16">Mode 1: load factor {factors[0]:.6g}</text><text x="35" y="47" font-size="13">Normalized w: blue -1 / white 0 / red +1</text>'
    svg+=''.join(polygons)+f'<text x="45" y="490" font-size="14">x width = {case.width_m:.4g} m; y length = {case.length_m:.4g} m</text><text x="45" y="515" font-size="12">Arbitrary mode amplitude, not a physical deflection.</text></svg>'
    (work/'mode_preview.svg').write_text(svg,encoding='utf-8')
    out={'solver_version':'2.23','solver_sha256':sha256(executable),'element':'S8R','input':case.to_dict(),
         'nodes':len(model['nodes']),'elements':len(model['elements']),'factors':factors,'first_factor':factors[0],'mode_checks':mode_checks,
         'native_reference_scale':scale,'native_factors':native_factors,
         'reference_membrane_strain':strain.tolist(),'analytical_membrane_strain':expected.tolist(),
         'critical_compression_pa':case.compression_pa*factors[0],'critical_shear_pa':case.shear_pa*factors[0],
         'engineering_screen':screen,'reference_force_residual_n':model['force_residual_n'],'reference_moment_residual_nm':model['moment_residual_nm'],
         'analytical_compression_relative_error':abs(case.compression_pa*factors[0]-screen['compression_critical_pa'])/screen['compression_critical_pa'] if case.shear_pa==0 and case.support=='simply_supported' else None,
         'physical_validation_passed':False,'limits':['独立各向同性理想平板，四边横向简支或固支，均匀膜压缩/剪切',
         '线性特征值为参考载荷的比例因子，模态振幅任意；不含初始缺陷、塑性、后屈曲和实际极限承载力',
         '代表板载荷可来自半翼面板应力包络，但并非全翼特征值屈曲模型']}
    write_json(work/'summary.json',out);return out
