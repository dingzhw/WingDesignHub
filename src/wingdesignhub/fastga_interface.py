"""Explicit contract for the pinned, fixed FAST-GA tutorial process.

This module imports no FAST-GA code; unsupported intent cannot leak into a
reference run as silently ignored overrides.
"""
REFERENCE_ID = 'fastga-1.4.0-beechcraft-76'
REFERENCE_SOURCE = 'https://github.com/supaero-aircraft-design/FAST-GA/blob/v1.4.0/src/fastga/notebooks/tutorial/data/beechcraft_76.xml'
REFERENCE_HASH = 'fa81a18c904b5fe6925806d0b647ac99c24e68e9e25889c882b980ab6b7ed3ff'
BASELINE_KG = {'data:weight:aircraft:MTOW': 1710.197080992762,
               'data:weight:aircraft:OWE': 1081.0432731126027,
               'data:mission:sizing:fuel': 249.15380788015943}
# Public promoted variable, SI reporting unit, role in this exact configuration.
VARIABLES = {
    'range': ('data:TLAR:range', 'm', 'input'),
    'cruise_speed': ('data:TLAR:v_cruise', 'm/s', 'input'),
    'cruise_altitude': ('data:mission:sizing:main_route:cruise:altitude', 'm', 'input'),
    'reserve_duration': ('data:mission:sizing:main_route:reserve:duration', 's', 'input'),
    'passengers_excluding_two_pilots': ('data:TLAR:NPAX_design', None, 'input'),
    'luggage': ('data:TLAR:luggage_mass_design', 'kg', 'input'),
    'person_mass': ('settings:weight:aircraft:payload:design_mass_per_passenger', 'kg', 'input'),
    'engine_count': ('data:geometry:propulsion:engine:count', None, 'input'),
    'power_per_engine': ('data:propulsion:IC_engine:max_power', 'W', 'input'),
    'payload': ('data:weight:aircraft:payload', 'kg', 'output'),
    'mtow': ('data:weight:aircraft:MTOW', 'kg', 'output'),
    'owe': ('data:weight:aircraft:OWE', 'kg', 'output'),
    'zfw': ('data:weight:aircraft:ZFW', 'kg', 'output'),
    'fuel': ('data:mission:sizing:fuel', 'kg', 'output'),
    'wing_area': ('data:geometry:wing:area', 'm**2', 'output'),
    'wing_span': ('data:geometry:wing:span', 'm', 'output'),
    'wing_mac': ('data:geometry:wing:MAC:length', 'm', 'output'),
    'fuselage_length': ('data:geometry:fuselage:length', 'm', 'output'),
    'horizontal_tail_area': ('data:geometry:horizontal_tail:area', 'm**2', 'output'),
    'vertical_tail_area': ('data:geometry:vertical_tail:area', 'm**2', 'output'),
}


def get_fastga_contract():
    return {'reference_id': REFERENCE_ID, 'version': '1.4.0', 'reference_url': REFERENCE_SOURCE,
            'execution': 'fixed_public_reference', 'accepts_custom_design': False,
            'configuration': '双发 Beechcraft 76 公开教学任务，所有上游输入保持原样',
            'variables': {k: {'name': n, 'unit': u or 'unitless', 'role': r} for k, (n, u, r) in VARIABLES.items()},
            'rules': ['参考流程由 ZFW + 总任务燃油求 MTOW；规定 MTOW 需要另建固定重量流程',
                      '重量上限需在求解后检查余量并参与后续约束定尺寸，不能直接覆盖 MTOW',
                      '参考载荷 = (NPAX_design + 2) × 单人质量 + 行李；新方案总载荷不直接映射到 NPAX',
                      'range 为主航线距离，巡航扣除爬升/下降距离；主航时为输出',
                      '储备油 = 巡航燃油 / 巡航时长 × 储备时长 × k；总燃油包含储备一次',
                      '发动机台数/单台功率为输入，不是本参考任务自动选出的动力方案'],
            'limits': ['本接口仅执行固定公开任务；新单发方案调用独立 run_sizing 服务',
                       'evaluate_problem 是耦合模型求值，不运行 YAML 中的优化设计变量',
                       '储备导数由已验证插件修复；全模型梯度及梯度优化尚未验证']}


def reference_binding_preview(project):
    """Keep the reference boundary explicit; custom sizing is a separate service."""
    from .requirements import DesignProject
    p = DesignProject.from_dict(project) if isinstance(project, dict) else project
    p.check_schema()
    return {'executable_as_custom_design': False, 'weight_mode': p.weight.mode,
            'custom_sizing_service': 'wingdesignhub.sizing_service.run_sizing',
            'weight_action': {'fixed': '保留规定重量，检查装载质量预算并报告剩余量',
                              'upper_bound': '求解重量并检查上限，超限进入约束诊断',
                              'solve': '由质量与任务燃油闭环求重量'}[p.weight.mode],
            'mission_action': '独立质点任务积分处理航程、航时、同段双约束及转场留空；储备单列',
            'payload_action': 'MassBreakdown(payload_from_npax=False) 直接接收含机组的总载荷；座位数仅参与设备质量',
            'reference_id': REFERENCE_ID, 'available_since': 'V0.1.7'}
