"""Explicit mixture-sensitive conceptual fuel model; calibration is not validation."""
import math

HP_W = 745.6998715822702
LB_KG = .45359237
FUEL_MODELS = {
    'constant_bsfc': '统一耗油率（原有概念假设）',
    'piper_economy_reference': '经济巡航参考（Piper 单点校准，范围内使用）',
}
PIPER_SOURCE = {
    'document': 'Piper PA-28-181 VB-760, Fig.5-13 p.5-17; cruise example p.5-5',
    'url': 'https://www.summitaviationspokane.com/wp-content/uploads/2025/08/pa-28-181-archer-ii-poh.pdf',
    'sha256': '0a51a23b0db5d4d1bbb063484a56d7ed12a0a1935da96e5c90e88dd13e1bd43c',
}
# Roles are fixed before model evaluation. Only this 65% point sets the coefficient.
CALIBRATION = {'id':'piper_vb760_economy_65','role':'calibration','rated_hp':180.,
               'power_fraction':.65,'fuel_us_gal_h':7.6,'fuel_lb_us_gal':6.,'mixture':'best_economy'}
HOLDOUT = (
    {'id':'piper_vb760_economy_55','role':'same_source_holdout','rated_hp':180.,
     'power_fraction':.55,'fuel_us_gal_h':6.3,'fuel_lb_us_gal':6.,'mixture':'best_economy'},
    {'id':'piper_vb760_economy_75','role':'same_source_holdout','rated_hp':180.,
     'power_fraction':.75,'fuel_us_gal_h':8.8,'fuel_lb_us_gal':6.,'mixture':'best_economy'},
)
LYCOMING_REFERENCE = {
    'id':'lycoming_o360_ac_65','role':'external_reference_conditions_unresolved',
    'rated_hp':180.,'power_fraction':.65,'fuel_us_gal_h':9.5,'rpm':2350,
    'document':'Lycoming 60297-12, October 2005, p.3-12 (PDF 44), O-360-A/C series',
    'url':'https://www.lycoming.com/sites/default/files/file/2025-11/60297-12%20-%20O-360%2C%20HO-360%2C%20IO-360%2C%20AIO-360%2C%20HIO-360%2C%20and%20TIO-360%20Series.pdf',
    'sha256':'06142d8b252d818d7c3f46baf648dbe6a65c1b33df03332d5256d5af7bf12946',
    'reason':'发动机族表列 economy cruise；与 Piper 峰值 EGT 的安装/混合比条件未完全对应，保留资料差异，不作为同条件通过点。',
}


def calibrated_bsfc():
    p = CALIBRATION
    return p['fuel_us_gal_h']*p['fuel_lb_us_gal']*LB_KG/(p['rated_hp']*HP_W/1000*p['power_fraction'])


def fuel_flow(power_w, rated_power_w, segment, assumptions):
    """kg/s and method tag. Off-reference segments retain the visible base BSFC."""
    if not all(math.isfinite(x) for x in (power_w,rated_power_w)) or power_w<0 or rated_power_w<=0:
        raise ValueError('耗油模型的轴功率须非负、额定功率须为正有限值')
    if assumptions.fuel_model not in FUEL_MODELS:raise ValueError('未知耗油模型')
    fraction=power_w/rated_power_w
    eligible=segment in ('cruise','outbound','inbound','loiter') and .55-1e-12<=fraction<=.75+1e-12
    if assumptions.fuel_model=='piper_economy_reference' and eligible:
        bsfc=calibrated_bsfc();method='economy_reference'
    else:
        bsfc=assumptions.bsfc_kg_kwh
        method='constant_bsfc' if assumptions.fuel_model=='constant_bsfc' else 'off_reference_base_bsfc'
    return power_w*bsfc/3.6e6,method


def fuel_model_description(assumptions):
    return {'model':assumptions.fuel_model,'label':FUEL_MODELS[assumptions.fuel_model],
            'base_bsfc_kg_kwh':assumptions.bsfc_kg_kwh,
            'economy_bsfc_kg_kwh':calibrated_bsfc() if assumptions.fuel_model=='piper_economy_reference' else None,
            'calibration_ids':[CALIBRATION['id']] if assumptions.fuel_model=='piper_economy_reference' else [],
            'reference_power_fraction':[.55,.75], 'fraction_basis':'actual shaft power / sea-level rated installed power',
            'reference_segments':['cruise','outbound','inbound','loiter'],
            'data_source':PIPER_SOURCE,
            'limits':['经济参考系数仅在稳定平飞、55%–75% 额定功率范围使用；其余任务段采用已声明的基础耗油率并单列覆盖。',
                      '范围边界采用显式切换，耗油率可能跳变；当前用于逐案计算，不提供该模型的连续梯度。',
                      '系数按额定功率归一用于概念相似估算；发动机选型、转速/混合比分布和跨机型精度尚未验证。',
                      '55%/75% 为同源留出检查，独立试验数据仍缺；全机物理精度与专业评审待完成。']}
