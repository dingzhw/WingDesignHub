"""Shared conventional-airframe definitions consumed by mass and geometry.

The V1 geometry assumptions are retained; V2 fixes inconsistent mass inputs.
This is a versioned template contract, not an independently validated aircraft.
"""
from copy import deepcopy
import math

CONFIGURATION_VERSION = 'metal_single_shared_v2'
PROPELLER_DIAMETER_M = 1.9
SURFACES = {
    'wing': {'taper_ratio': .6, 'thickness_ratio': .12, 'naca': '2412'},
    'horizontal_tail': {'aspect_ratio': 4., 'taper_ratio': .6, 'thickness_ratio': .12, 'naca': '0012'},
    'vertical_tail': {'aspect_ratio': 1.6, 'taper_ratio': .6, 'thickness_ratio': .12, 'naca': '0012'},
}


def surface_parameters(wing_aspect_ratio):
    result = deepcopy(SURFACES)
    result['wing']['aspect_ratio'] = wing_aspect_ratio
    return result


def geometry_parameters(geometry):
    if geometry.get('configuration_version') != CONFIGURATION_VERSION:
        raise ValueError('构型定义版本不匹配；旧结果可以查看，新计算请重新运行总体方案')
    values = geometry['surface_parameters']
    if set(values) != set(SURFACES):
        raise ValueError('共享升力面定义不完整')
    for name, spec in values.items():
        if any(type(spec[k]) not in (int,float) or not math.isfinite(spec[k]) for k in ('thickness_ratio','taper_ratio','aspect_ratio')):
            raise ValueError('升力面参数必须为有限数值：'+name)
        if not 0 < spec['thickness_ratio'] < .3 or not 0 < spec['taper_ratio'] <= 1 or spec['aspect_ratio'] <= 0:
            raise ValueError('升力面参数无效：' + name)
        if not isinstance(spec['naca'],str) or len(spec['naca'])!=4 or not spec['naca'].isdigit():raise ValueError('仅支持四位 NACA 翼型')
        if abs(int(spec['naca'][-2:]) / 100 - spec['thickness_ratio']) > 1e-12:
            raise ValueError('翼型与厚弦比定义不一致：' + name)
    return values


def domain_ledger(geometry):
    return {
        'configuration_version': CONFIGURATION_VERSION,
        'shared_surface_parameters': deepcopy(geometry_parameters(geometry)),
        'active_models': ['FAST-GA MassBreakdown', 'AVL lifting surfaces', 'XFOIL profiles'],
        'inactive_empirical_components': [{'name': 'FAST-GA k_vh',
            'reason': '垂尾气动经验组件未进入当前重量组与AVL链；参考任务的告警另记'}],
        'template_limits': ['座舱截面、固定站位和发动机包络是研究假设，尚未验证2–6座/40–400 kW的全部组合',
                            '起降距离和完整重心包线未计算；已检查约束满足不等于整机工程验收'],
        'empirical_clipping_policy': '已核查FAST-GA 1.4.0重量目录，未发现clip/interp/min/max裁剪调用；适用性按下表保留边界',
        'component_domains': [
            {'component':'FAST-GA airframe/systems/furniture mass regressions','role':'active mass breakdown',
             'input_source':'fastga_mass_inputs.json and interface bindings','domain':'上游未给出完整标定样本范围；本平台400–2500 kg/2–6座为研究域，非精度保证',
             'clipping':'none identified in pinned mass source'},
            {'component':'FAST-GA BasicICEngine weight','role':'active engine weight',
             'domain':'平台限定40–400 kW；商品发动机质量与几何匹配待验证','clipping':'none; out-of-domain rejected'},
            {'component':'AVL/XFOIL','role':'downstream aerodynamic analysis',
             'domain':'小迎角配平与已收敛极曲线，局部Re/Mach/舵偏单独检查','clipping':'missing/out-of-domain rejected'},
            {'component':'CCBlade/native engine SFC','role':'coupled option only',
             'domain':'旋转尖速预检与叶素、图谱运行期检查；低负荷按显式策略单列','clipping':'no map extrapolation'},
        ],
    }
