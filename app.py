"""Chinese local UI; service layer remains usable without Streamlit."""
import json
from pathlib import Path
import pandas as pd
import streamlit as st
from wingdesignhub import __version__
from wingdesignhub.model import WingCase
from wingdesignhub.service import run_analysis, generate_report, run_reference
from wingdesignhub.adapters import inventory, tool_paths

ROOT = Path(__file__).resolve().parent
st.set_page_config(page_title="WingDesignHub", page_icon="✈", layout="wide")
st.title("✈ WingDesignHub")
st.caption(f"V{__version__} · 固定翼概念设计工作台 · P0 计算与接口验证")
st.info("当前可以运行合成机翼/梁验证。整机总体闭环与十模块完整功能按路线图接入。")
page = st.sidebar.radio("工作区", ["开始计算", "公开基准算例", "工具设置", "验证与路线图"])

if page == "开始计算":
    base = WingCase()
    uploaded = st.file_uploader("打开已保存的方案（可选）", type="json")
    if uploaded:
        try:
            base = WingCase.from_dict(json.loads(uploaded.getvalue()))
        except (ValueError, TypeError) as exc:
            st.error(f"方案无法读取：{exc}")
            st.stop()
    st.subheader("1. 设置方案")
    names = {"梁解析解验证": "beam", "AVL 气动 → 载荷 → 梁变形": "avl",
             "OpenVSP 几何 → AVL → 载荷 → 梁变形": "openvsp_avl"}
    selection = st.selectbox("计算任务", list(names), help="先运行默认验证，再尝试调用实际软件。")
    with st.form("case"):
        name = st.text_input("方案名称", base.name)
        a, b, c = st.columns(3)
        span = a.number_input("全翼展（m）", min_value=.1, value=float(base.span_m), step=.5)
        chord = b.number_input("弦长（m）", min_value=.05, value=float(base.chord_m), step=.1)
        speed = c.number_input("飞行速度（m/s）", min_value=1., max_value=100., value=float(base.speed_m_s))
        alpha = a.number_input("迎角（°）", min_value=-8., max_value=8., value=float(base.alpha_deg))
        load = b.number_input("均布载荷（N/m，仅解析验证）", value=float(base.uniform_load_n_m))
        with st.expander("高级参数：等效梁和空气条件"):
            st.caption("梁参数是合成算例输入，尚未由真实结构定尺寸得到。")
            modulus = st.number_input("弹性模量（GPa）", min_value=.01, value=base.elastic_modulus_pa/1e9)
            inertia = st.number_input("截面惯性矩（m⁴）", min_value=1e-12, value=base.second_moment_m4, format="%.8f")
            density = st.number_input("空气密度（kg/m³）", min_value=.001, value=base.density_kg_m3)
            count = st.number_input("梁单元数", min_value=2, max_value=200, value=base.beam_elements)
        clicked = st.form_submit_button("一键运行", type="primary")
    data = base.to_dict()
    data.update(name=name, span_m=span, chord_m=chord, speed_m_s=speed, alpha_deg=alpha,
                uniform_load_n_m=load, elastic_modulus_pa=modulus*1e9, second_moment_m4=inertia,
                density_kg_m3=density, beam_elements=int(count))
    st.download_button("保存方案", json.dumps(data, ensure_ascii=False, indent=2), "wing-case.json", "application/json")
    if clicked:
        try:
            with st.spinner("正在计算并保存记录……"):
                st.session_state["last_result"] = run_analysis(data, ROOT, names[selection])
        except (ValueError, TypeError) as exc:
            st.error(str(exc))
    if "last_result" in st.session_state:
        r = st.session_state["last_result"]
        st.subheader("2. 最近一次计算结果")
        st.caption(f"任务：{r['mode']} · 运行编号：{r['run_id']}。修改参数后需重新运行。")
        if r["status"] != "success":
            st.error(r["error"])
        else:
            st.success("计算完成，运行记录已保存")
            beam = r["outputs"]["beam"]
            a, b = st.columns(2)
            a.metric("翼尖挠度", f"{beam['tip_displacement_m']*1000:.3f} mm")
            b.metric("翼根反力矩", f"{beam['root_moment_nm']:.2f} N·m")
            st.line_chart(pd.DataFrame({"展向位置（m）": beam["y_m"], "挠度（mm）": [v*1000 for v in beam["displacement_m"]]}).set_index("展向位置（m）"))
            if "tip_relative_error" in beam:
                st.write(f"与均布载荷悬臂梁解析解的相对误差：{beam['tip_relative_error']:.3e}")
            if "aerodynamics" in r["outputs"]:
                st.write("气动结果（CDff 为诱导阻力系数）", r["outputs"]["aerodynamics"]["coefficients"])
        st.caption("这些结果属于接口与数值验证；尚无整机独立物理验证。")
        st.download_button("下载计算摘要", generate_report(r), "calculation-report.md")
        st.download_button("下载完整结果", json.dumps(r, ensure_ascii=False, indent=2), "result.json")
elif page == "公开基准算例":
    st.subheader("复现公开软件案例")
    st.write("算例保留上游默认条件，在独立目录运行。它们用来检查软件和方法，尚未与本工作台的飞机模型联算。")
    ref = st.selectbox("选择案例", ["FAST-GA 总体案例", "CalculiX 悬臂梁基准"])
    st.caption("FAST-GA 可能需要数分钟，会显示经验方法范围检查。CalculiX 2.23 自动执行三档网格与手册尺寸梁验证。")
    if st.button("运行公开案例", type="primary"):
        with st.spinner("正在执行基准并保存日志……"):
            st.session_state["reference_result"] = run_reference(ROOT, "fastga" if ref.startswith("FAST") else "calculix")
    if "reference_result" in st.session_state:
        r = st.session_state["reference_result"]
        if r["status"] == "failed":
            st.error(r["error"])
        elif r["status"] == "executed_with_limits":
            st.warning("参考案例复现完成，但部分经验方法超出范围，须复核后再用于工程方案。")
        else:
            st.success("案例运行结束。请结合日志与验证记录评估结果。")
        summary = r.get("summary", {})
        if "mesh_study" in summary:
            st.metric("20 单元梁挠度误差", f"{summary['relative_error']:.3%}")
            st.caption(f"验收门槛 {summary['threshold']:.0%}；求解器版本 {summary['solver_version']}")
            st.dataframe(pd.DataFrame([{"单元数": row["elements"], "挠度（mm）": row["tip_displacement_m"]*1000,
                                        "相对误差（%）": row["relative_error"]*100} for row in summary["mesh_study"]]), hide_index=True)
        if "outputs_kg" in summary:
            a, b, c = st.columns(3)
            for column, key, title in ((a, "data:weight:aircraft:MTOW", "起飞重量"),
                                       (b, "data:weight:aircraft:OWE", "使用空重"),
                                       (c, "data:mission:sizing:fuel", "任务燃油")):
                column.metric(title, f"{summary['outputs_kg'][key]:.2f} kg")
            labels = {"elevator_chord_ratio": "升降舵弦长比", "horizontal_to_vertical_tail_area": "平尾/垂尾面积比",
                      "takeoff_elevator_angle_deg": "起飞升降舵偏角（°，铰链力矩关系）"}
            for check in summary.get("final_domain_checks", []):
                if not check["within_range"]:
                    st.warning(f"{labels.get(check['parameter'], check['parameter'])}：{check['value']:.4f}，"
                               f"经验表范围 {check['lower']:.4f}–{check['upper']:.4f}；上游采用边界值计算。")
        st.caption("数值基准通过与独立物理验证分别记录。")
        with st.expander("运行详情与完整诊断"):
            st.json(r)
        st.download_button("下载基准记录", json.dumps(r, ensure_ascii=False, indent=2), "benchmark.json")
elif page == "工具设置":
    st.subheader("本机计算工具")
    st.caption("路径只保存在本地；检测到文件或安装包不等于已经完成工程验证。")
    st.caption("OpenVSP 的 Python 接口须与安装目录版本一致。CalculiX 基准要求 2.23，可选择项目内便携版或填写路径。")
    st.dataframe(pd.DataFrame.from_dict(inventory(ROOT), orient="index").fillna(""), width="stretch")
    with st.form("tools"):
        labels = {"avl": "AVL 程序路径", "xfoil": "XFOIL 程序路径", "openvsp": "OpenVSP 安装目录", "calculix": "CalculiX 2.23 程序路径"}
        config = {k: st.text_input(labels[k], v) for k, v in tool_paths(ROOT).items()}
        if st.form_submit_button("保存本机路径"):
            (ROOT/"local").mkdir(exist_ok=True)
            (ROOT/"local/tools.json").write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
            st.success("已保存。计算时会再次检查实际文件。")
else:
    for name in ("COVERAGE.md", "VALIDATION.md", "ROADMAP.md"):
        st.markdown((ROOT/"docs"/name).read_text(encoding="utf-8"))
