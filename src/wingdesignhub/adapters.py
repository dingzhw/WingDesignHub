"""File-based external workers. Never execute a command supplied by an AI/user text."""
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

NUMBER = r"[-+]?(?:\d*\.\d+|\d+\.?)(?:[EeDd][-+]?\d+)?"


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def tool_paths(root):
    defaults = {"avl": "C:/apps/avl/avl.exe", "xfoil": "C:/apps/XFOIL6.99/xfoil.exe",
                "openvsp": "C:/apps/OpenVSP-3.56.0-win64", "calculix": ""}
    config = Path(root)/"local/tools.json"
    if config.exists():
        custom = json.loads(config.read_text(encoding="utf-8"))
        defaults.update({k: v for k, v in custom.items() if k in defaults})
    return defaults


def inventory(root):
    result = {}
    for name, value in tool_paths(root).items():
        p = Path(value) if value else None
        result[name] = {"path": value, "found": bool(p and p.exists()), "status": "未运行验证"}
    import importlib.metadata as meta
    for name in ("fast-oad-cs23", "openmdao", "openaerostruct", "streamlit", "control"):
        try:
            result[name] = {"version": meta.version(name), "found": True, "status": "已安装，查看验证记录"}
        except meta.PackageNotFoundError:
            result[name] = {"found": False, "status": "尚未安装"}
    return result


def execute(args, cwd, stdin="", timeout=60):
    cwd = Path(cwd)
    manifest = {"argv": [str(x) for x in args], "timeout_seconds": timeout,
                "executable_sha256": sha256(args[0])}
    (cwd/"command.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (cwd/"stdin.txt").write_text(stdin, encoding="ascii")
    process = subprocess.Popen(args, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    try:
        data, _ = process.communicate(stdin.encode("ascii"), timeout=timeout)
    except subprocess.TimeoutExpired:
        import psutil
        try:
            for child in psutil.Process(process.pid).children(recursive=True):
                try:
                    child.kill()
                except psutil.NoSuchProcess:
                    pass
        except psutil.NoSuchProcess:
            pass
        process.kill()
        data, _ = process.communicate()
        (cwd/"stdout.log").write_bytes(data)
        raise RuntimeError(f"计算超过 {timeout} 秒，已停止；请查看运行日志") from None
    (cwd/"stdout.log").write_bytes(data)
    output = data.decode("utf-8", errors="replace")
    if process.returncode:
        raise RuntimeError(f"求解器退出码 {process.returncode}；请查看运行日志")
    return output


def avl_geometry(case):
    return (f"WingDesignHub synthetic wing\n0.0\n0 0 0\n"
            f"{case.area_m2} {case.chord_m} {case.span_m}\n0 0 0\n0.0\n"
            f"SURFACE\nWing\n12 1.0 {case.aero_panels} -1.0\nYDUPLICATE\n0\n"
            f"SECTION\n0 0 0 {case.chord_m} 0\nNACA\n0012\n"
            f"SECTION\n0 {case.span_m/2} 0 {case.chord_m} 0\nNACA\n0012\n")


def parse_avl(output, strips):
    if re.search(r"\b(?:NaN|Infinity)\b|forrtl:|not recognized", output, re.I):
        raise ValueError("AVL 输出包含错误或非有限值")
    if "Vortex Lattice Output -- Total Forces" not in output:
        raise ValueError("缺少 AVL 总力输出")
    coefficients = {}
    for key in ("CLtot", "CDff", "Cmtot", "Sref", "Cref", "Bref"):
        match = re.search(r"\b" + key + r"\s*=\s*(" + NUMBER + ")", output)
        if not match:
            raise ValueError(f"缺少 AVL 输出：{key}")
        coefficients[key] = float(match[1].replace("D", "E"))
    rows = []
    # Read column names: AVL builds differ in whether Xle/Zle are included.
    headers = next((line.split() for line in strips.splitlines()
                    if line.split()[:1] == ["j"] and "Yle" in line and "Area" in line), None)
    if not headers or not all(k in headers for k in ("Yle", "Area", "cl")):
        raise ValueError("无法识别 AVL 条带表格式")
    for line in strips.splitlines():
        t = line.split()
        if len(t) >= 13 and t[0].isdigit():
            try:
                vals = [float(x.replace("D", "E")) for x in t]
            except ValueError:
                continue
            if not all(math.isfinite(v) for v in vals):
                raise ValueError("条带载荷包含非有限值")
            y, area, cl = (vals[headers.index(k)] for k in ("Yle", "Area", "cl"))
            if area <= 0:
                raise ValueError("条带面积非正")
            if y > 0:
                rows.append({"y_m": y, "area_m2": area, "cl": cl})
    if not rows:
        raise ValueError("未找到右半翼载荷")
    return coefficients, sorted(rows, key=lambda x: x["y_m"])


def run_avl(case, executable, directory):
    directory = Path(directory); directory.mkdir()
    if not Path(executable).is_file():
        raise FileNotFoundError("未找到 AVL，请在工具设置中指定 avl.exe")
    (directory/"model.avl").write_text(avl_geometry(case), encoding="ascii")
    commands = f"LOAD model.avl\nOPER\nA A {case.alpha_deg}\nX\nFS\nstrips.txt\n\nQUIT\n"
    output = execute([executable], directory, commands)
    coefs, rows = parse_avl(output, (directory/"strips.txt").read_text())
    for key, value in (("Sref", case.area_m2), ("Cref", case.chord_m), ("Bref", case.span_m)):
        if not math.isclose(coefs[key], value, rel_tol=1e-4):
            raise ValueError(f"AVL 参考量不一致：{key}")
    return {"coefficients": coefs, "right_wing_strips": rows, "drag_scope": "仅诱导阻力；未接入黏性与机身阻力"}


def run_openvsp(case, directory):
    directory = Path(directory); directory.mkdir()
    (directory/"input.json").write_text(json.dumps(case.to_dict()), encoding="utf-8")
    execute([sys.executable, "-m", "wingdesignhub.vsp_worker"], directory, timeout=90)
    result = json.loads((directory/"geometry.json").read_text(encoding="utf-8"))
    for key, expected in (("span_m", case.span_m), ("area_m2", case.area_m2)):
        if not math.isclose(result[key], expected, rel_tol=1e-6):
            raise ValueError(f"OpenVSP 几何与配置不一致：{key}")
    return result
