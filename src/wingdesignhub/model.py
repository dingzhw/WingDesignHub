"""P0 schema: a synthetic rectangular wing and equivalent cantilever spar.

This is deliberately not a complete aircraft definition. Schema changes are versioned.
"""
from dataclasses import asdict, dataclass, fields
import math


@dataclass(frozen=True)
class WingCase:
    name: str = "公开合成机翼示例"
    schema_version: int = 1
    span_m: float = 10.0
    chord_m: float = 1.5
    speed_m_s: float = 40.0
    density_kg_m3: float = 1.225
    alpha_deg: float = 3.0
    elastic_modulus_pa: float = 70e9
    second_moment_m4: float = 8e-6
    beam_depth_m: float = 0.20
    uniform_load_n_m: float = 500.0
    beam_elements: int = 40
    aero_panels: int = 24
    assumption: str = "矩形无后掠 NACA0012 孤立机翼；等截面悬臂梁；无惯性卸载。仅用于接口和数值验证。"

    @property
    def area_m2(self):
        return self.span_m * self.chord_m

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        unknown = set(data) - {f.name for f in fields(cls)}
        if unknown:
            raise ValueError(f"未知输入字段：{sorted(unknown)}")
        obj = cls(**data)
        errors = validate_project(obj)
        if errors:
            raise ValueError("；".join(errors))
        return obj


def validate_project(case):
    errors = []
    if type(case.schema_version) is not int or case.schema_version != 1:
        errors.append("不支持此配置版本")
    if not isinstance(case.name, str) or not case.name.strip():
        errors.append("请输入方案名称")
    positive = ("span_m", "chord_m", "speed_m_s", "density_kg_m3", "elastic_modulus_pa",
                "second_moment_m4", "beam_depth_m")
    for key in positive + ("alpha_deg", "uniform_load_n_m"):
        value = getattr(case, key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            errors.append(f"{key} 必须是有限数值")
        elif key in positive and value <= 0:
            errors.append(f"{key} 必须大于零")
    for key, lower, upper in (("beam_elements", 2, 200), ("aero_panels", 8, 100)):
        value = getattr(case, key)
        if isinstance(value, bool) or not isinstance(value, int) or not lower <= value <= upper:
            errors.append(f"{key} 必须为 {lower}～{upper} 的整数")
    if not errors:
        if not -8 <= case.alpha_deg <= 8:
            errors.append("本验证模型的迎角限定为 -8～8°；不提供失速预测")
        if case.speed_m_s > 100:
            errors.append("本验证模型限低速计算，速度不超过 100 m/s")
    return errors
