"""Force-only transfer to shell skin patches, conserving all six resultants in SI."""
import numpy as np
from .mechanics import resultant


def skin_areas(mesh):
    weights = {n: 0. for n in mesh['nodes']}
    keys = [s for s in mesh['sets'] if s.startswith('ESkin_')]
    if len(keys) != 1:
        raise ValueError('载荷映射需要唯一蒙皮部件')
    for eid in mesh['sets'][keys[0]]:
        conn = mesh['elements'][eid]
        corners = conn[:3] if mesh['types'][eid]=='S6' else conn
        p = np.array([mesh['nodes'][n] for n in corners])
        area = sum(np.linalg.norm(np.cross(p[i]-p[0],p[i+1]-p[0]))/2 for i in range(1,len(p)-1))
        for n in conn:
            weights[n] += area/len(conn)
    return weights


def conservative_transfer(mesh, positions, forces, moments, half_span, chord, patch_width):
    """Local area-weighted minimum correction; couples are realized by nodal forces.

    Patches span the skin chord and a fixed physical spanwise support. No load is
    put on clamped root nodes. This transfers strip resultants, not surface pressure.
    """
    p, f, m = (np.asarray(v,dtype=float) for v in (positions,forces,moments))
    target_f,target_m = resultant(p,f,m)
    if not len(p) or not np.isfinite([half_span,chord,patch_width]).all() or min(half_span,chord,patch_width)<=0:
        raise ValueError('映射长度与条带数组无效')
    if np.any(p[:,1]<0) or np.any(p[:,1]>half_span) or np.any(p[:,0]<0) or np.any(p[:,0]>chord):
        raise ValueError('条带作用点超出当前半翼范围')
    area = skin_areas(mesh)
    ids = np.array([n for n,a in area.items() if a>0 and mesh['nodes'][n][1]>1e-7],dtype=int)
    xyz = np.array([mesh['nodes'][n] for n in ids])
    nodal = np.zeros_like(xyz); conditions=[]; patch_errors=[]
    for pos,force,moment in zip(p,f,m):
        dy = xyz[:,1]-pos[1]
        selected = np.flatnonzero(abs(dy)<=1.5*patch_width)
        if len(selected)<6:
            raise ValueError('条带附近的蒙皮节点不足；须调整网格或载荷带宽')
        local = xyz[selected]-pos
        w = np.array([area[ids[i]] for i in selected])*np.exp(-.5*(dy[selected]/patch_width)**2)
        w /= w.sum()
        a = np.zeros((6,3*len(selected)))
        for i,r in enumerate(local/chord):
            x,y,z=r
            a[:3,3*i:3*i+3]=np.eye(3)
            a[3:,3*i:3*i+3]=[[0,-z,y],[z,0,-x],[-y,x,0]]
        weights = np.repeat(w,3); gram=(a*weights)@a.T
        condition=float(np.linalg.cond(gram));conditions.append(condition)
        if not np.isfinite(condition) or condition>1e10:
            raise ValueError('局部节点几何不足以守恒六分量载荷')
        desired=np.r_[force,moment/chord]; initial=(w[:,None]*force).ravel()
        answer=initial+weights*(a.T@np.linalg.solve(gram,desired-a@initial))
        patch_errors.append(float(np.max(abs(a@answer-desired))))
        nodal[selected] += answer.reshape(-1,3)
    actual_f,actual_m=resultant(xyz,nodal)
    force_scale=max(float(np.linalg.norm(target_f)),float(np.linalg.norm(f,axis=1).sum()),1.)
    moment_scale=max(float(np.linalg.norm(target_m)),force_scale*max(chord,half_span),float(np.linalg.norm(m,axis=1).sum()),1.)
    ef=float(np.max(abs(actual_f-target_f)));em=float(np.max(abs(actual_m-target_m)))
    # Near-zero components use the absolute tolerance, not another component's scale.
    passed=bool(np.all(abs(actual_f-target_f)<=1e-8+.001*abs(target_f))
                and np.all(abs(actual_m-target_m)<=1e-8+.001*abs(target_m)))
    if not passed:
        raise ValueError('载荷映射未满足合力/合力矩守恒门槛')
    return ids,nodal,{'input_force_n':target_f.tolist(),'input_moment_nm':target_m.tolist(),
                     'mapped_force_n':actual_f.tolist(),'mapped_moment_nm':actual_m.tolist(),
                     'origin_m':[0.,0.,0.],'force_absolute_error_n':ef,'moment_absolute_error_nm':em,
                     'force_scaled_error':ef/force_scale,'moment_scaled_error':em/moment_scale,
                     'force_scale_n':force_scale,'moment_scale_nm':moment_scale,
                     'max_patch_residual_scaled_units':max(patch_errors),'max_condition':max(conditions),
                     'relative_threshold':.001,'absolute_threshold':1e-8,'passed':passed}
