"""Versioned half-wing mesh input and independent shell export audit (SI)."""
from dataclasses import asdict, dataclass, fields
import math
from pathlib import Path
import numpy as np


@dataclass(frozen=True)
class StructureMeshCase:
    schema_version: int = 1
    name: str = "公开金属半翼结构网格"
    half_span_m: float = 5.
    chord_m: float = 1.5
    front_spar_fraction: float = .25
    rear_spar_fraction: float = .65
    rib_count: int = 4
    max_edge_m: float = .4
    min_edge_m: float = .04
    skin_thickness_m: float = .002
    spar_thickness_m: float = .003
    rib_thickness_m: float = .002
    elastic_modulus_pa: float = 70e9
    poisson_ratio: float = .33
    density_kg_m3: float = 2700.

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict) or set(data)-{f.name for f in fields(cls)}:
            raise ValueError("结构网格配置包含未知字段或格式错误")
        case = cls(**data); case.validate(); return case

    def validate(self):
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError("不支持此结构网格配置版本")
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("方案名称不能为空")
        if type(self.rib_count) is not int or not 2 <= self.rib_count <= 11:
            raise ValueError("翼肋数须为 2–11 整数")
        for key, value in self.to_dict().items():
            if key not in ("name", "schema_version", "rib_count"):
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                    raise ValueError(f"{key} 须为有限正数")
        if not (2 <= self.half_span_m <= 12 and .5 <= self.chord_m <= 3):
            raise ValueError("本模板限半展长 2–12 m、弦长 0.5–3 m")
        if not (.15 <= self.front_spar_fraction <= .35 and .55 <= self.rear_spar_fraction <= .8):
            raise ValueError("前梁限 15%–35% 弦长，后梁限 55%–80% 弦长")
        if not (.01 <= self.min_edge_m < self.max_edge_m <= min(1., self.chord_m)):
            raise ValueError("网格边长须满足 0.01 m ≤ 最小值 < 最大值 ≤ min(1 m,弦长)")
        if self.half_span_m/self.max_edge_m > 100 or self.poisson_ratio >= .5:
            raise ValueError("网格过密或泊松比超出当前各向同性材料范围")
        if max(self.skin_thickness_m, self.spar_thickness_m, self.rib_thickness_m) > .01*self.chord_m:
            raise ValueError("本模板板厚不得超过弦长的 1%")

    @property
    def rib_fractions(self):
        return np.linspace(.1, .9, self.rib_count).tolist()

    @property
    def part_thicknesses(self):
        return {"Skin": self.skin_thickness_m, "FrontSpar": self.spar_thickness_m,
                "RearSpar": self.spar_thickness_m,
                **{f"Rib{i}": self.rib_thickness_m for i in range(self.rib_count)}}


def read_inp(path):
    """Read the deliberately restricted, first-order shell export; reject ambiguity."""
    nodes, elements, sets, sections, materials, types = {}, {}, {}, {}, {}, {}
    mode = None; options = {}; current_material = None
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("**"):
            continue
        if line.startswith("*"):
            chunks = [v.strip() for v in line.split(",")]
            mode = chunks[0].upper()
            options = {a.split("=", 1)[0].upper(): a.split("=", 1)[1] for a in chunks[1:] if "=" in a}
            if mode == "*ELEMENT":
                if options.get("TYPE") not in ("S3", "S4"):
                    raise ValueError("当前网格检查器仅支持一阶壳 S3/S4")
                sets.setdefault(options["ELSET"], [])
            if mode == "*MATERIAL":
                current_material = options["NAME"]; materials[current_material] = {}
            if mode in ("*INCLUDE", "*STEP", "*BOUNDARY", "*CLOAD", "*DLOAD"):
                raise ValueError("此入口仅检查单文件前处理网格，不能混入分析步或外部文件")
            continue
        values = [v.strip() for v in line.split(",") if v.strip()]
        if mode == "*NODE":
            node = int(values[0]); xyz = [float(v) for v in values[1:]]
            if node in nodes or len(xyz) != 3 or not np.isfinite(xyz).all():
                raise ValueError("节点重复或坐标无效")
            nodes[node] = xyz
        elif mode == "*ELEMENT":
            eid, *conn = map(int, values)
            expected = int(options["TYPE"][1])
            if eid in elements or len(conn) != expected or len(set(conn)) != expected:
                raise ValueError("单元重复、退化或连接格式无效")
            elements[eid] = conn; types[eid] = options["TYPE"]; sets[options["ELSET"]].append(eid)
        elif mode == "*SHELL SECTION":
            key = options["ELSET"]
            if key in sections or len(values) != 1:
                raise ValueError("壳截面重复或格式无效")
            sections[key] = {"thickness_m": float(values[0]), "material": options["MATERIAL"]}
        elif mode == "*DENSITY":
            materials[current_material]["density_kg_m3"] = float(values[0])
        elif mode == "*ELASTIC":
            if options.get("TYPE", "ISO") != "ISO" or len(values) != 2:
                raise ValueError("仅支持各向同性弹性材料")
            materials[current_material].update(elastic_modulus_pa=float(values[0]), poisson_ratio=float(values[1]))
    if not nodes or not elements:
        raise ValueError("未找到节点或壳单元")
    if any(n not in nodes for conn in elements.values() for n in conn):
        raise ValueError("单元引用了不存在的节点")
    return {"nodes": nodes, "elements": elements, "sets": sets, "sections": sections, "materials": materials, "types": types}


def audit_mesh(mesh, case):
    case.validate()
    nodes, elements = mesh["nodes"], mesh["elements"]
    used = set(n for conn in elements.values() for n in conn)
    unused = set(nodes)-used
    areas, qualities, seen, adjacency = {}, [], set(), {n: set() for n in used}
    for eid, conn in elements.items():
        canonical = tuple(sorted(conn))
        if canonical in seen:
            raise ValueError("存在重复覆盖的三角单元")
        seen.add(canonical)
        pts = np.array([nodes[n] for n in conn])
        crosses = [np.cross(pts[i]-pts[0], pts[i+1]-pts[0]) for i in range(1,len(conn)-1)]
        area = float(sum(np.linalg.norm(c) for c in crosses)/2)
        if not math.isfinite(area) or area <= 1e-12:
            raise ValueError("存在零面积或退化单元")
        areas[eid] = area
        if len(conn) == 4:
            normal = sum(crosses); norm = np.linalg.norm(normal)
            if norm <= 1e-12:
                raise ValueError("存在自交或退化四边形")
            jac = [np.dot(np.cross(pts[(i+1)%4]-pts[i], pts[(i-1)%4]-pts[i]), normal)/norm for i in range(4)]
            if min(jac) <= 1e-12:
                raise ValueError("存在翻转、凹陷或退化四边形")
        edge_sq = sum(float(np.dot(pts[(i+1)%len(conn)]-pts[i], pts[(i+1)%len(conn)]-pts[i])) for i in range(len(conn)))
        qualities.append((4*np.sqrt(3) if len(conn)==3 else 4)*area/edge_sq)
        for n in conn:
            adjacency[n].update(set(conn)-{n})
    remaining = set(used); components = 0
    while remaining:
        components += 1; todo = [remaining.pop()]
        while todo:
            reachable = adjacency[todo.pop()] & remaining
            remaining -= reachable; todo.extend(reachable)
    if unused or components != 1:
        raise ValueError(f"结构网格未连通或存在孤立节点：连通块={components}，孤立节点={len(unused)}")
    points = np.array(list(nodes.values()))
    extent = np.ptp(points, axis=0)
    if not np.allclose(extent[:2], [case.chord_m, case.half_span_m], atol=2e-5, rtol=1e-5):
        raise ValueError("网格几何尺寸与输入不一致")
    if not np.allclose(points.min(axis=0)[:2],[0.,0.],atol=2e-5):
        raise ValueError("半翼坐标原点或侧别不一致")
    if not (.1*case.chord_m < extent[2] < .13*case.chord_m):
        raise ValueError("网格翼型厚度异常")
    parts = {}; mass = 0.
    for part, expected_t in case.part_thicknesses.items():
        keys = [key for key in mesh["sets"] if key.startswith(f"E{part}_")]
        if len(keys) != 1 or not mesh["sets"][keys[0]]:
            raise ValueError(f"结构部件缺失或为空：{part}")
        key = keys[0]; sec = mesh["sections"].get(key, {})
        part_nodes = set(n for eid in mesh["sets"][key] for n in elements[eid])
        if part in ("FrontSpar","RearSpar"):
            x = getattr(case,"front_spar_fraction" if part=="FrontSpar" else "rear_spar_fraction")*case.chord_m
            if any(abs(nodes[n][0]-x)>2e-5 for n in part_nodes):
                raise ValueError(f"梁位置与输入不一致：{part}")
        if part.startswith("Rib"):
            y = case.rib_fractions[int(part[3:])]*case.half_span_m
            if any(abs(nodes[n][1]-y)>2e-5 for n in part_nodes):
                raise ValueError(f"翼肋位置与输入不一致：{part}")
        material = mesh["materials"].get(sec.get("material"), {})
        if not math.isclose(sec.get("thickness_m", 0.), expected_t, rel_tol=1e-6):
            raise ValueError(f"板厚或单位不一致：{part}")
        for field in ("density_kg_m3", "elastic_modulus_pa", "poisson_ratio"):
            if not math.isclose(material.get(field, 0.), getattr(case, field), rel_tol=1e-6):
                raise ValueError(f"材料参数或单位不一致：{field}")
        area = sum(areas[eid] for eid in mesh["sets"][key])
        part_mass = area*expected_t*case.density_kg_m3
        parts[part] = {"elements": len(mesh["sets"][key]), "area_m2": area, "mass_kg": part_mass}
        mass += part_mass
    if sum(p["elements"] for p in parts.values()) != len(elements):
        raise ValueError("存在未纳入结构部件台账的单元")
    quality_min = float(min(qualities))
    # This is a mesh screening threshold, not proof of stress accuracy.
    if quality_min < .05:
        raise ValueError("存在极瘦单元（归一化形状质量 < 0.05）")
    return {"nodes": len(nodes), "elements": len(elements), "element_types": sorted(set(mesh["types"].values())),
            "connected_components": components, "orphan_nodes": len(unused),
            "extent_m": extent.tolist(), "minimum_area_m2": min(areas.values()),
            "quality_min": quality_min, "quality_p05": float(np.quantile(qualities,.05)),
            "parts": parts, "shell_material_mass_kg": mass, "area_m2": sum(areas.values())}


def write_preview(mesh, path):
    """Portable planform SVG; the file visualizes edges, not stress or deformation."""
    points = np.array(list(mesh["nodes"].values())); low = points.min(axis=0); ext = np.ptp(points, axis=0)
    scale = min(900/ext[1], 320/ext[0])
    def xy(n):
        p = mesh["nodes"][n]; return (30+(p[1]-low[1])*scale, 30+(p[0]-low[0])*scale)
    edges = set()
    for conn in mesh["elements"].values():
        edges.update(tuple(sorted((conn[i],conn[(i+1)%len(conn)]))) for i in range(len(conn)))
    lines = []
    for a,b in sorted(edges):
        x1,y1=xy(a);x2,y2=xy(b)
        lines.append(f'<path d="M{x1:.2f},{y1:.2f} L{x2:.2f},{y2:.2f}"/>')
    svg=f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {ext[1]*scale+60:.0f} {ext[0]*scale+60:.0f}"><rect width="100%" height="100%" fill="white"/><g stroke="#2563a8" stroke-width="0.4" fill="none">'+''.join(lines)+'</g></svg>'
    Path(path).write_text(svg,encoding="utf-8")
