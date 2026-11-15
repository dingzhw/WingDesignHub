"""Elastic isotropic flat-panel screening, NACA TN 3781 eqs 20/53/55.

The shear check uses the infinite simply-supported strip lower estimate 5.34,
rounded down from the handbook's 5.35 (table 3); no finite-length benefit.
This is an engineering screen, not a shell eigenvalue or postbuckling analysis.
"""
import math
import numpy as np


def plate_screen(length,width,thickness,E,nu,sigma_longitudinal,tau):
    vals=[length,width,thickness,E,nu,sigma_longitudinal,tau]
    if any(isinstance(x,bool) or not isinstance(x,(int,float,np.floating)) for x in vals) or not np.isfinite(vals).all():
        raise ValueError('板屈曲输入须有限')
    if min(length,width,thickness,E)<=0 or not 0<=nu<.5 or thickness/min(length,width)>.05:
        raise ValueError('超出各向同性薄板范围')
    aspect=length/width
    if not .05<=aspect<=100:raise ValueError('板长宽比限 0.05–100')
    modes=range(1,math.ceil(aspect)+2)
    mode=min(modes,key=lambda m:(m/aspect+aspect/m)**2)
    kc=(mode/aspect+aspect/mode)**2
    factor=math.pi**2*E/(12*(1-nu**2))
    compression=factor*kc*(thickness/width)**2
    # Shear is invariant under exchanging the panel axes.
    shear=factor*5.34*(thickness/min(length,width))**2
    rc=max(0.,-sigma_longitudinal)/compression;rs=abs(tau)/shear
    utilization=rc+rs*rs
    # Proportional combined-load reserve from lambda*Rc+(lambda*Rs)^2=1.
    reserve=(2/(rc+math.sqrt(rc*rc+4*rs*rs))) if rc+rs>0 else None
    return {'kc':kc,'compression_half_waves':mode,'ks_long_strip':5.34,'compression_critical_pa':compression,
            'shear_critical_pa':shear,'compression_ratio':rc,'shear_ratio':rs,'interaction_utilization':utilization,
            'proportional_load_factor_to_buckling':reserve,'screen_passed':bool(utilization<=1),
            'sigma_longitudinal_pa':sigma_longitudinal,'tau_pa':tau,
            'assumptions':'four simply supported edges; isotropic elastic flat panel; uniform envelope stresses; no tensile stabilization'}


def panel_screen(mesh,mesh_case,stress):
    """Finite rib bays of the NACA wingbox; root to last internal rib.

    Each S6 expands to a 15-node wedge with 9 integration points. Equal averaging
    cancels linear through-thickness bending, then panel maxima envelope element
    membrane stresses. This is a screening approximation for nonuniform stress.
    Curved skins are replaced by their measured root-section arc width.
    """
    by_element={e:[] for e in mesh['elements']}
    for (e,ip),v in stress.items():by_element[e].append((ip,v))
    if any({ip for ip,v in rows}!=set(range(1,10)) for rows in by_element.values()):
        raise ValueError('局部屈曲需要每个 S6 完整的 9 个积分点应力')
    E,nu=mesh_case.elastic_modulus_pa,mesh_case.poisson_ratio
    L,c=mesh_case.half_span_m,mesh_case.chord_m
    x1,x2=c*mesh_case.front_spar_fraction,c*mesh_case.rear_spar_fraction
    skin_nodes=set()
    for name,eids in mesh['sets'].items():
        if not name.startswith('ESkin_'):continue
        for eid in eids:
            conn=mesh['elements'][eid];p=np.array([mesh['nodes'][n] for n in conn[:3]])
            normal=np.cross(p[1]-p[0],p[2]-p[0])
            if abs(normal[1])/np.linalg.norm(normal)<.01:skin_nodes.update(conn)
    root=np.array([mesh['nodes'][n] for n in skin_nodes if abs(mesh['nodes'][n][1])<1e-7])
    widths={}
    for name,sign in (('upper_skin',1),('lower_skin',-1)):
        pts=root[(root[:,0]>=x1-1e-6)&(root[:,0]<=x2+1e-6)&(sign*root[:,2]>1e-7)]
        pts=np.unique(pts[:,[0,2]],axis=0);pts=pts[np.argsort(pts[:,0])]
        if len(pts)<2 or abs(pts[0,0]-x1)>1e-5 or abs(pts[-1,0]-x2)>1e-5:
            raise ValueError('无法确定翼盒蒙皮边界和弧长')
        widths[name]=float(np.linalg.norm(np.diff(pts,axis=0),axis=1).sum())
    for name,x in (('front_web',x1),('rear_web',x2)):
        z=root[abs(root[:,0]-x)<1e-5,2]
        if len(z)<2:raise ValueError('缺少梁腹板端点')
        widths[name]=float(z.max()-z.min())
    bounds=[0.]+[v*L for v in mesh_case.rib_fractions]
    panels={(name,i):[] for name in widths for i in range(len(bounds)-1)}
    covered=0.;total=0.;excluded={}
    for name,eids in mesh['sets'].items():
        for e in eids:
            p=np.array([mesh['nodes'][n] for n in mesh['elements'][e][:3]]);cent=p.mean(0)
            normal=np.cross(p[1]-p[0],p[2]-p[0]);area=np.linalg.norm(normal)/2;total+=area
            part=None
            if name.startswith('ESkin_') and x1-1e-6<=cent[0]<=x2+1e-6 and abs(cent[2])>1e-6 and abs(normal[1])/np.linalg.norm(normal)<.01:
                part='upper_skin' if cent[2]>0 else 'lower_skin'
            elif name.startswith('EFrontSpar_'):part='front_web'
            elif name.startswith('ERearSpar_'):part='rear_web'
            bay=np.searchsorted(bounds,cent[1],side='right')-1
            if part is None or not 0<=bay<len(bounds)-1:
                excluded[name]=excluded.get(name,0.)+area;continue
            normal/=np.linalg.norm(normal);tangent=np.cross([0,1,0],normal);tangent/=np.linalg.norm(tangent)
            s=np.mean([v for ip,v in by_element[e]],axis=0)
            # Global stress order: xx, yy, zz, xy, xz, yz.
            shear=s[3]*tangent[0]+s[5]*tangent[2]
            panels[part,bay].append((float(s[1]),float(shear),e,float(area),cent.tolist()));covered+=area
    result=[]
    for (name,bay),values in panels.items():
        if not values:raise ValueError(f'面板 {name}/{bay} 缺少应力采样')
        compression=min(values,key=lambda v:v[0]);shear=max(values,key=lambda v:abs(v[1]))
        t=mesh_case.skin_thickness_m if 'skin' in name else mesh_case.spar_thickness_m
        r=plate_screen(bounds[bay+1]-bounds[bay],widths[name],t,E,nu,compression[0],shear[1])
        r.update(panel=name,bay=bay,y_start_m=bounds[bay],y_end_m=bounds[bay+1],width_m=widths[name],thickness_m=t,
                 compression_element= compression[2],shear_element=shear[2],sampled_elements=len(values))
        mean=np.average(np.array([v[:2] for v in values]),axis=0,weights=[v[3] for v in values])
        coincident=max(values,key=lambda v:max(0.,-v[0])/r['compression_critical_pa']+(v[1]/r['shear_critical_pa'])**2)
        r['diagnostics']={'compression_control_centroid_m':compression[4],'shear_control_centroid_m':shear[4],
             'compression_contribution':r['compression_ratio'],'shear_squared_contribution':r['shear_ratio']**2,
             'max_coincident_utilization':max(0.,-coincident[0])/r['compression_critical_pa']+(coincident[1]/r['shear_critical_pa'])**2,
             'coincident_element':coincident[2],
             'area_mean_sigma_pa':float(mean[0]),'area_mean_tau_pa':float(mean[1]),
             'area_mean_screen':plate_screen(bounds[bay+1]-bounds[bay],widths[name],t,E,nu,float(mean[0]),float(mean[1])),
             'purpose':'diagnostic stress averaging; does not replace the envelope acceptance screen'}
        result.append(r)
    return {'panels':result,'screen_passed':all(v['screen_passed'] for v in result),
            'max_interaction_utilization':max(v['interaction_utilization'] for v in result),
            'screened_area_m2':covered,'total_shell_area_m2':total,'excluded_area_by_part_m2':excluded,
            'eigenvalue_buckling_checked':False,'physical_validation_passed':False,
            'limits':['仅筛查根部至最后一道内肋的两梁间上下蒙皮及两梁腹板；前后缘、翼尖末段、肋板和根/尖封板未筛查',
            '曲面蒙皮按平板弧宽等效，四边简支属工程假设；真实肋/梁弹性支承、曲率与连接需另行验证',
            '每单元 9 积分点等权平均近似膜应力，取面板最大压应力与最大剪应力作为均匀包络；两峰值可不共点',
            '剪切系数采用长板下限估计，不计有限长收益；不考虑横向压应力、后屈曲、塑性、缺陷或疲劳']}
