"""Versioned design intent, independent of any solver's guesses or computed state.

All internal quantities are SI. Payload includes crew, passengers, baggage and
mission equipment once. Range is still-air route distance; duration excludes
ground operations and reserve. Validation here is not aircraft feasibility.
"""
from dataclasses import asdict, dataclass, field, fields, replace
import hashlib
import json
import math
from .sizing_config import SizingAssumptions


DEFAULT_SOURCE = 'WingDesignHub V0.1.6 概念演示假设，须按项目需求复核；非适航储备规定'
ASSUMPTION_KEYS = ('cruise_speed_m_s', 'cruise_altitude_m', 'reserve_duration_s', 'reserve_basis')
WEIGHT_LABELS = {'fixed': '规定起飞重量', 'upper_bound': '起飞重量上限', 'solve': '由任务求起飞重量'}
MISSION_LABELS = {'range_only': '航程任务', 'endurance_only': '航时任务',
                  'same_route': '同一主任务同时要求航程和航时', 'transit_loiter': '往返转场＋额外留空'}


def _decode(cls, data):
    if not isinstance(data, dict) or set(data) - {f.name for f in fields(cls)}:
        raise ValueError(f'{cls.__name__} 配置字段无效')
    return cls(**data)


def _finite(value, name, minimum=0., strictly=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f'{name} 必须是有限数值')
    if value < minimum or (strictly and value == minimum):
        raise ValueError(f'{name} 须{"大于" if strictly else "不小于"} {minimum}')


@dataclass(frozen=True)
class WeightRequirement:
    mode: str = 'solve'
    value_kg: float | None = None


@dataclass(frozen=True)
class MissionRequirement:
    kind: str = 'range_only'
    range_m: float | None = 800000.
    endurance_s: float | None = None


@dataclass(frozen=True)
class DesignAssumptions:
    cruise_speed_m_s: float = 60.
    cruise_altitude_m: float = 2000.
    reserve_duration_s: float = 2700.
    reserve_basis: str = 'cruise_fuel_flow'
    sources: dict = field(default_factory=lambda: {k: DEFAULT_SOURCE for k in ASSUMPTION_KEYS})


@dataclass(frozen=True)
class DesignProject:
    schema_version: int = 3
    name: str = '新飞机方案'
    payload_kg: float = 350.
    weight: WeightRequirement = field(default_factory=WeightRequirement)
    mission: MissionRequirement = field(default_factory=MissionRequirement)
    assumptions: DesignAssumptions = field(default_factory=DesignAssumptions)
    sizing: SizingAssumptions = field(default_factory=SizingAssumptions)
    confirmation_sha256: str | None = None

    def to_dict(self):
        data=asdict(self)
        if data['sizing'].get('layout') is None:data['sizing'].pop('layout',None)
        if data['sizing'].get('first_level') is None:data['sizing'].pop('first_level',None)
        return data

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict):
            raise ValueError('方案必须是 JSON 对象')
        data = dict(data)
        if type(data.get('schema_version')) is int and data['schema_version'] in (1,2):
            if data['schema_version']==1 and 'sizing' in data: raise ValueError('旧版本方案不得携带新版定尺寸字段')
            if data['schema_version']==2 and isinstance(data.get('sizing'),dict) and 'fuel_model' in data['sizing']:
                raise ValueError('旧版本方案不得携带新版耗油模型字段')
            data.update(schema_version=3, confirmation_sha256=None)
        if 'sizing' in data:
            data['sizing']=SizingAssumptions.from_dict(data['sizing'])
        for name, typ in (('weight', WeightRequirement), ('mission', MissionRequirement), ('assumptions', DesignAssumptions)):
            if name in data:
                data[name] = _decode(typ, data[name])
        obj = _decode(cls, data)
        obj.check_schema()
        return obj

    def check_schema(self):
        if type(self.schema_version) is not int or self.schema_version != 3:
            raise ValueError('需求方案版本无效')
        if not isinstance(self.name, str) or not self.name.strip() or len(self.name) > 100:
            raise ValueError('方案名称须为 1–100 个字符')
        if not isinstance(self.weight, WeightRequirement) or not isinstance(self.mission, MissionRequirement) or not isinstance(self.assumptions, DesignAssumptions):
            raise ValueError('需求方案子模型类型无效')
        if self.weight.mode not in WEIGHT_LABELS or self.mission.kind not in MISSION_LABELS:
            raise ValueError('重量模式或任务类型无效')
        _finite(self.payload_kg, '载荷')
        if not isinstance(self.sizing, SizingAssumptions): raise ValueError('定尺寸假设类型无效')
        self.sizing.validate()
        for name, value in (('起飞重量', self.weight.value_kg), ('航程', self.mission.range_m), ('航时', self.mission.endurance_s)):
            if value is not None:
                _finite(value, name, strictly=True)
        a = self.assumptions
        _finite(a.cruise_speed_m_s, '巡航真空速', strictly=True)
        _finite(a.cruise_altitude_m, '巡航高度')
        _finite(a.reserve_duration_s, '储备时长')
        if a.reserve_basis != 'cruise_fuel_flow':
            raise ValueError('当前储备策略仅支持单列时长、按巡航平均耗油率估算')
        if not isinstance(a.sources, dict) or set(a.sources) != set(ASSUMPTION_KEYS) or any(not isinstance(s, str) or not s.strip() for s in a.sources.values()):
            raise ValueError('每项设计假设均须有来源说明')
        if self.confirmation_sha256 is not None and (not isinstance(self.confirmation_sha256, str) or len(self.confirmation_sha256) != 64 or any(c not in '0123456789abcdef' for c in self.confirmation_sha256)):
            raise ValueError('方案确认哈希格式无效')

    def definition_hash(self):
        data = self.to_dict()
        data.pop('confirmation_sha256')
        # Absence of the opt-in layout preserves historical confirmed identities.
        if data['sizing'].get('layout') is None:data['sizing'].pop('layout',None)
        # Normalize numeric forms so 350 and 350.0 represent the same definition.
        def normalize(value):
            if isinstance(value, dict): return {k: normalize(v) for k, v in value.items()}
            if isinstance(value, list): return [normalize(v) for v in value]
            if type(value) in (int, float): return float(value)
            return value
        return hashlib.sha256(json.dumps(normalize(data), ensure_ascii=False, sort_keys=True, allow_nan=False).encode('utf-8')).hexdigest()

    def confirmed(self):
        self.check_schema()
        return replace(self, confirmation_sha256=self.definition_hash())


def validate_design_project(project):
    """Return structural/semantic diagnostics; never claim flight feasibility."""
    try:
        p = DesignProject.from_dict(project) if isinstance(project, dict) else project
        p.check_schema()
    except (ValueError, TypeError, AttributeError) as exc:
        return [{'severity': 'error', 'code': 'invalid_schema', 'field': 'project', 'message': str(exc)}]
    out = []
    def issue(code, field, message, severity='error'):
        out.append(dict(severity=severity, code=code, field=field, message=message))
    w, m, a = p.weight, p.mission, p.assumptions
    if w.mode == 'solve' and w.value_kg is not None:
        issue('solved_weight_has_value', 'weight.value_kg', '待求重量模式应留空；初始猜测由后续求解器单独管理。')
    if w.mode != 'solve' and w.value_kg is None:
        issue('missing_weight', 'weight.value_kg', '规定值或上限模式必须给出重量。')
    if w.value_kg is not None and w.mode != 'solve' and p.payload_kg >= w.value_kg:
        issue('payload_exceeds_weight', 'payload_kg', '载荷已达到或超过起飞重量，无法容纳机体和燃油。')
    required = {'range_only': (True, False), 'endurance_only': (False, True), 'same_route': (True, True), 'transit_loiter': (True, True)}[m.kind]
    for name, needed in zip(('range_m', 'endurance_s'), required):
        present = getattr(m, name) is not None
        if needed != present:
            issue('mission_field_conflict', f'mission.{name}', f'{MISSION_LABELS[m.kind]} 中 {name} {"必须填写" if needed else "应留空，避免遗留指标被忽略"}。')
    if a.reserve_duration_s == 0:
        issue('no_reserve', 'assumptions.reserve_duration_s', '当前显式设置零储备，须评估运行需要。', 'warning')
    if p.confirmation_sha256 != p.definition_hash():
        issue('definition_unconfirmed', 'confirmation_sha256', '请核对需求、任务含义和假设；修改后需重新确认。', 'warning')
    return out


def build_design_intent(project):
    p = DesignProject.from_dict(project) if isinstance(project, dict) else project
    diagnostics = validate_design_project(p)
    if any(d['severity'] == 'error' for d in diagnostics):
        return {'status': 'invalid_input', 'diagnostics': diagnostics, 'aircraft_feasibility': 'not_evaluated'}
    m, a, w = p.mission, p.assumptions, p.weight
    if m.kind == 'transit_loiter':
        segments = [{'id': 'outbound_and_return', 'role': 'route', 'distance_m': m.range_m, 'duration_s': None,
                     'definition': '往返转场总距离；航程不是单程半径，当前模板按往返各半分配'},
                    {'id': 'on_station', 'role': 'loiter', 'distance_m': None, 'duration_s': m.endurance_s,
                     'definition': '额外留空时长，与转场时间分开计算'}]
    else:
        segments = [{'id': 'main_route', 'role': 'route', 'distance_m': m.range_m, 'duration_s': m.endurance_s,
                     'definition': '同一主任务，含爬升/巡航/下降；时长为最低要求，距离为规定航迹长度'}]
    segments += [{'id': 'reserve', 'role': 'reserve', 'distance_m': None, 'duration_s': a.reserve_duration_s,
                  'definition': '额外燃油储备；不计入主任务航程/航时，不作为已执行的留空段'}]
    return {'status': 'requirements_ready' if p.confirmation_sha256 == p.definition_hash() else 'needs_confirmation',
            'definition_sha256': p.definition_hash(), 'diagnostics': diagnostics,
            'aircraft_feasibility': 'not_evaluated', 'sizing_available': True,
            'payload_definition': '机组、乘员、行李和任务设备总和；此处不再自动追加驾驶员质量',
            'weight': {'mode': w.mode, 'prescribed_mtow_kg': w.value_kg if w.mode == 'fixed' else None,
                       'mtow_upper_bound_kg': w.value_kg if w.mode == 'upper_bound' else None,
                       'solve_mtow': w.mode != 'fixed', 'mass_balance_required': True},
            'mission_segments': segments, 'assumptions': asdict(a),
            'environment': {'atmosphere': 'ISA', 'wind_m_s': 0., 'scope': '概念任务定义；环境性能未计算'},
            'target_configuration': '常规单翼、常规尾翼、金属、单发活塞螺旋桨',
            'time_accounting': '地面滑行另列；主任务时长不含储备。航程不除以巡航速度冒充实际航时。',
            'sizing_assumptions': p.sizing.to_dict(),
            'next_step': '运行初步总体设计；完整配平与高保真模型后续验证'}
