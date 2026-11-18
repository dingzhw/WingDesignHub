"""Validate reusable solved batches without expanding their physical validity mask."""
import math
from .propulsion_model import PropulsionError


def cacheable_batch(request,result):
    points=result.get('points',[])
    if len(points)!=len(request['points']):
        raise PropulsionError('ccblade_output_invalid','CCBlade 批次点数不符')
    reusable=True
    for expected,p in zip(request['points'],points):
        if any(p.get(k)!=v for k,v in expected.items()):
            raise PropulsionError('ccblade_output_invalid','CCBlade 工况读回与请求不符')
        status=p.get('status')
        if status=='solver_failed':
            reusable=False;continue
        if status not in ('valid','out_of_domain'):
            raise PropulsionError('ccblade_output_invalid','CCBlade 输出状态无效')
        def finite(value):
            if isinstance(value,dict):return all(finite(v) for v in value.values())
            if isinstance(value,list):return all(finite(v) for v in value)
            return not isinstance(value,(int,float)) or math.isfinite(value)
        if not finite(p):
            raise PropulsionError('ccblade_output_invalid','CCBlade 输出含非有限数值')
        t,q,power,eta=(p[k] for k in ('thrust_n','torque_nm','shaft_power_w','efficiency'))
        if not math.isclose(power,q*p['rpm']*math.pi/30,rel_tol=1e-10,abs_tol=1e-8):
            raise PropulsionError('ccblade_output_invalid','CCBlade 功率与扭矩不一致')
        if status=='valid' and (min(t,q,power)<=0 or not 0<=eta<=1 or
                not math.isclose(eta,t*p['speed_m_s']/power,rel_tol=1e-10,abs_tol=1e-12)):
            raise PropulsionError('ccblade_output_invalid','CCBlade 有效点效率不一致')
        if status=='out_of_domain' and not p.get('diagnostics'):
            raise PropulsionError('ccblade_output_invalid','CCBlade 域外点缺少原因')
    return reusable
