"""Common thin-wall rectangular box: Euler beam/Bredt torsion versus S6 shells.

The same centerline geometry, material, clamp and actual nodal loads are used.
No fitted stiffness, rigid end plates, or borrowed CRM cross-section is involved.
"""
from dataclasses import asdict, dataclass
from pathlib import Path
import json
import numpy as np
from .mechanics import resultant, map_loads, solve_beam
from .shell_static import promote_s6, solve_shell
from .service import write_json


@dataclass(frozen=True)
class BoxCase:
    schema_version: int = 1
    length_m: float = 5.
    width_m: float = .6
    height_m: float = .18
    skin_m: float = .002
    web_m: float = .003
    elastic_modulus_pa: float = 70e9
    poisson_ratio: float = .33
    density_kg_m3: float = 2700.
    tip_bending_moment_nm: float = 5000.
    tip_torque_nm: float = 100.

    def validate(self):
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError('翼盒配置版本不支持')
        for k,v in asdict(self).items():
            if k!='schema_version' and (isinstance(v,bool) or not isinstance(v,(int,float)) or not np.isfinite(v)):
                raise ValueError('翼盒参数须为有限数值')
        if min(self.length_m,self.width_m,self.height_m,self.skin_m,self.web_m,self.elastic_modulus_pa,self.density_kg_m3)<=0:
            raise ValueError('翼盒几何和材料须为正值')
        if not 0<=self.poisson_ratio<.5 or max(self.skin_m,self.web_m)>.03*min(self.width_m,self.height_m):
            raise ValueError('超出各向同性薄壁翼盒范围')
        if self.length_m < 5*max(self.width_m,self.height_m):
            raise ValueError('本对照限长细翼盒')
        if self.tip_bending_moment_nm==0 or self.tip_torque_nm==0:
            raise ValueError('对照的弯矩与扭矩须非零')


def section(case):
    case.validate();b,h,ts,tw=case.width_m,case.height_m,case.skin_m,case.web_m
    return {'area_m2':2*b*ts+2*h*tw,
            'Ixx_m4':2*b*ts*(h/2)**2+2*tw*h**3/12,
            'J_m4':4*(b*h)**2/(2*b/ts+2*h/tw),
            'shear_modulus_pa':case.elastic_modulus_pa/(2*(1+case.poisson_ratio))}


def box_mesh(case,segments):
    case.validate()
    if type(segments) is not int or not 10<=segments<=160:
        raise ValueError('翼盒展向分段须为 10–160 整数')
    # Counter-clockwise cross-section in x,z; normals point outwards.
    b,h=case.width_m,case.height_m
    corners=np.array([[0,-h/2],[b,-h/2],[b,h/2],[0,h/2]])
    perimeter=[];sides=[]
    for j in range(4):
        count=max(2,int(np.ceil(np.linalg.norm(corners[(j+1)%4]-corners[j])/(case.length_m/segments))))
        for k in range(count):
            perimeter.append(corners[j]+k/count*(corners[(j+1)%4]-corners[j]));sides.append(j)
    n=len(perimeter);nodes={};elements={};sets={'ESkin_box':[],'EWeb_box':[]}
    for i in range(segments+1):
        for j,(x,z) in enumerate(perimeter):nodes[i*n+j+1]=[float(x),case.length_m*i/segments,float(z)]
    for i in range(segments):
        for j in range(n):
            a=i*n+j+1;d=i*n+(j+1)%n+1;c=d+n;bnode=a+n
            for tri in ([a,bnode,c],[a,c,d]):
                eid=len(elements)+1;elements[eid]=tri
                sets['ESkin_box' if sides[j]%2==0 else 'EWeb_box'].append(eid)
    mesh={'nodes':nodes,'elements':elements,'sets':sets,'types':{e:'S3' for e in elements},
          'materials':{'metal':{'elastic_modulus_pa':case.elastic_modulus_pa,'poisson_ratio':case.poisson_ratio,'density_kg_m3':case.density_kg_m3}},
          'sections':{k:{'material':'metal','thickness_m':case.skin_m if k.startswith('ESkin') else case.web_m} for k in sets}}
    return promote_s6(mesh)


def tip_loading(mesh,case,force,torque):
    """Consistent quadratic edge forces for uniform perimeter line traction.

    Torsion traction is the Bredt constant shear flow on all four walls. Force
    is a perimeter-uniform z traction. Tip edges remain deformable.
    """
    loads={n:np.zeros(3) for n in mesh['nodes']};seen=set()
    q=torque/(2*case.width_m*case.height_m)
    for conn in mesh['elements'].values():
        for a,b,m in ((conn[0],conn[1],conn[3]),(conn[1],conn[2],conn[4]),(conn[2],conn[0],conn[5])):
            if abs(mesh['nodes'][a][1]-case.length_m)>1e-8 or abs(mesh['nodes'][b][1]-case.length_m)>1e-8:continue
            key=tuple(sorted((a,b)))
            if key in seen:continue
            seen.add(key);pa,pb=np.array(mesh['nodes'][a]),np.array(mesh['nodes'][b]);length=np.linalg.norm(pb-pa)
            center=(pa+pb)/2-np.array([case.width_m/2,case.length_m,0.])
            # Positive y torque has tangential force (z,0,-x).
            tangent=pb-pa
            if np.dot(tangent,[center[2],0,-center[0]])<0:tangent=-tangent
            f=q*tangent+np.array([0,0,force*length/(2*(case.width_m+case.height_m))])
            for node,w in ((a,1/6),(m,2/3),(b,1/6)):loads[node]+=w*f
    ids=np.array([n for n,f in loads.items() if np.linalg.norm(f)>0],int)
    f=np.array([loads[n] for n in ids]);p=np.array([mesh['nodes'][n] for n in ids])
    F,M=resultant(p,f);expected=np.array([case.length_m*force,torque-case.width_m/2*force,0])
    if not np.allclose(F,[0,0,force],atol=1e-8) or not np.allclose(M,expected,atol=1e-8):
        raise ValueError('翼盒端部载荷不守恒')
    return ids,f,{'input_force_n':F.tolist(),'input_moment_nm':M.tolist(),
                  'force_scale_n':max(1.,float(np.linalg.norm(f,axis=1).sum())),
                  'moment_scale_nm':max(1.,float(np.linalg.norm(f,axis=1).sum())*case.length_m)}


def beam_response(case,mesh,ids,forces):
    props=section(case)
    # Every shell span station (including midsides) has a beam station.
    y=np.unique(np.round([p[1] for p in mesh['nodes'].values()],12))
    if not np.allclose(np.diff(y),y[-1]/(len(y)-1),rtol=1e-8):raise ValueError('梁站位不均匀')
    nodes=np.column_stack((np.full(len(y),case.width_m/2),y,np.zeros(len(y))))
    f,m=map_loads([mesh['nodes'][n] for n in ids],forces,nodes)
    if np.max(abs(f[:,:2]))>1e-8 or np.max(abs(m[:,2]))>1e-8:raise ValueError('当前梁仅支持竖向弯曲和绕展向扭转')
    out=solve_beam(case.length_m,case.elastic_modulus_pa,props['Ixx_m4'],f[:,2],m[:,0])
    # Exact Saint-Venant twist from section torque in each uniform segment.
    torque=np.cumsum(m[::-1,1])[::-1][1:]
    theta=np.r_[0.,np.cumsum(torque*np.diff(y)/(props['shear_modulus_pa']*props['J_m4']))]
    a,b=resultant(nodes,f,m);c,d=resultant([mesh['nodes'][n] for n in ids],forces)
    out.update(twist_rad=theta.tolist(),tip_twist_rad=float(theta[-1]),section=props,
               mapping_force_error_n=float(max(abs(a-c))),mapping_moment_error_nm=float(max(abs(b-d))))
    return out


def bending_tip_couple(mesh,case,moment):
    """Linear longitudinal end stress -M*z/I; quadratic edge integration.

    An end bending couple avoids introducing an unsupported skin pressure at the
    open end. The beam receives precisely these forces, including their couples.
    """
    loads={n:np.zeros(3) for n in mesh['nodes']};seen=set();I=section(case)['Ixx_m4']
    gauss,weights=np.polynomial.legendre.leggauss(3)
    for name,eids in mesh['sets'].items():
        t=mesh['sections'][name]['thickness_m']
        for eid in eids:
            conn=mesh['elements'][eid]
            for a,b,m in ((conn[0],conn[1],conn[3]),(conn[1],conn[2],conn[4]),(conn[2],conn[0],conn[5])):
                if abs(mesh['nodes'][a][1]-case.length_m)>1e-8 or abs(mesh['nodes'][b][1]-case.length_m)>1e-8:continue
                key=tuple(sorted((a,b)))
                if key in seen:continue
                seen.add(key);pa,pb=np.array(mesh['nodes'][a]),np.array(mesh['nodes'][b]);length=np.linalg.norm(pb-pa)
                for xi,w in zip(gauss,weights):
                    z=((1-xi)*pa[2]+(1+xi)*pb[2])/2
                    q=-moment*z*t/I
                    for node,N in ((a,xi*(xi-1)/2),(m,1-xi*xi),(b,xi*(xi+1)/2)):
                        loads[node][1]+=N*q*w*length/2
    ids=np.array([n for n,f in loads.items() if np.linalg.norm(f)>0],int);f=np.array([loads[n] for n in ids])
    F,M=resultant([mesh['nodes'][n] for n in ids],f)
    if not np.allclose(F,0,atol=1e-8) or not np.allclose(M,[moment,0,0],atol=1e-8):raise ValueError('端部弯矩不守恒')
    scale=float(np.linalg.norm(f,axis=1).sum())
    return ids,f,{'input_force_n':F.tolist(),'input_moment_nm':M.tolist(),'force_scale_n':max(1.,scale),'moment_scale_nm':max(1.,scale*case.length_m)}


def tip_fit(case,mesh,displacements):
    a=[];rhs=[]
    for n,p in mesh['nodes'].items():
        if abs(p[1]-case.length_m)>1e-8:continue
        x,y,z=np.array(p)-[case.width_m/2,case.length_m,0]
        a.extend(np.column_stack((np.eye(3),[[0,z,-y],[-z,0,x],[y,-x,0]])))
        rhs.extend(displacements[str(n)])
    A=np.array(a);v=np.linalg.lstsq(A,rhs,rcond=None)[0]
    return {'translation_z_m':float(v[2]),'twist_y_rad':float(v[4]),
            'section_fit_rms_m':float(np.sqrt(np.mean((A@v-rhs)**2)))}


def run_box_comparison(executable,work,case=None):
    case=case or BoxCase();case.validate();work=Path(work);work.mkdir(parents=True,exist_ok=True)
    write_json(work/'input.json',asdict(case));rows=[]
    for segments in (40,80):
        mesh=box_mesh(case,segments)
        for name in ('bending','torsion'):
            ids,f,audit=(bending_tip_couple(mesh,case,case.tip_bending_moment_nm) if name=='bending'
                         else tip_loading(mesh,case,0.,case.tip_torque_nm))
            beam=beam_response(case,mesh,ids,f)
            path=work/f'{name}_{segments}'
            shell=solve_shell(executable,path,mesh,ids,f,case.length_m,audit)
            fit=tip_fit(case,mesh,json.loads((path/'nodal_displacement.json').read_text()))
            key='translation_z_m' if name=='bending' else 'twist_y_rad'
            value=beam['tip_displacement_m'] if name=='bending' else beam['tip_twist_rad']
            rows.append({'case':name,'span_segments':segments,'beam':beam,'shell':shell,'tip_fit':fit,
                         'beam_shell_relative_error':abs(fit[key]-value)/abs(value)})
            write_json(path/'comparison.json',rows[-1])
    mesh_diff={}
    for name,key in (('bending','translation_z_m'),('torsion','twist_y_rad')):
        a,b=[v for v in rows if v['case']==name]
        mesh_diff[name]=abs(a['tip_fit'][key]-b['tip_fit'][key])/abs(b['tip_fit'][key])
    out={'rows':rows,'mesh_relative_differences':mesh_diff,'thresholds':{'beam_shell':.1,'shell_mesh':.05},
         'passed':bool(all(v['beam_shell_relative_error']<.1 for v in rows) and max(mesh_diff.values())<.05),
         'physical_validation_passed':False,'limits':['独立等截面矩形闭口薄壁翼盒，非 NACA 半翼或 OAS uCRM',
         '梁忽略剪切挠度及约束翘曲；壳允许截面畸变。仅比较翼尖整体位移/扭转，不以梁验证壳局部峰值应力',
         '相同中面尺寸、材料、根部固支和实际端部线载荷；端部未加刚性端板；截面 I 忽略板自身厚度立方项']}
    out['status']='passed' if out['passed'] else 'failed';write_json(work/'summary.json',out);return out
