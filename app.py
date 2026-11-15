"""Chinese local UI; service layer remains usable without Streamlit."""
import json
from pathlib import Path
import pandas as pd
import streamlit as st
from wingdesignhub import __version__
from wingdesignhub.model import WingCase
from wingdesignhub.service import run_analysis, generate_report, run_reference
from wingdesignhub.adapters import inventory, tool_paths
from wingdesignhub.fea_mesh import StructureMeshCase
from wingdesignhub.structure_service import run_structure_mesh

ROOT = Path(__file__).resolve().parent
st.set_page_config(page_title="WingDesignHub", page_icon="✈", layout="wide")
st.title("✈ WingDesignHub")
st.caption(f"V{__version__} · 固定翼概念设计工作台 · P0 计算与接口验证")
st.info("当前可以运行合成机翼/梁验证。整机总体闭环与十模块完整功能按路线图接入。")
page = st.sidebar.radio("工作区", ["开始计算", "结构网格", "公开基准算例", "工具设置", "验证与路线图"])

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
elif page == "结构网格":
    st.subheader("生成金属半翼结构网格")
    st.write("NACA0012 矩形半翼，包含蒙皮、前后梁和内翼肋。生成后检查实际单元、连通性、尺寸和材料单位。")
    st.caption("此页交付几何与网格文件；边界条件、载荷和强度分析在后续版本接入。")
    base = StructureMeshCase()
    uploaded = st.file_uploader("打开结构网格方案（可选）",type="json")
    if uploaded:
        try:
            base = StructureMeshCase.from_dict(json.loads(uploaded.getvalue()))
        except (ValueError,TypeError) as exc:
            st.error(f"方案无法读取：{exc}"); st.stop()
    with st.form("structure_mesh"):
        name = st.text_input("方案名称",base.name)
        a,b,c = st.columns(3)
        span = a.number_input("半翼展（m）",min_value=2.,max_value=12.,value=float(base.half_span_m),step=.5)
        chord = b.number_input("弦长（m）",min_value=.5,max_value=3.,value=float(base.chord_m),step=.1)
        edge = c.number_input("目标最大网格边长（m）",min_value=.01,max_value=1.,value=float(base.max_edge_m),step=.01)
        with st.expander("结构布局和板厚"):
            st.caption(f"当前材料 E={base.elastic_modulus_pa/1e9:g} GPa、ν={base.poisson_ratio:g}、ρ={base.density_kg_m3:g} kg/m³，属于合成各向同性材料输入。翼肋均布于 10%–90% 半展长。")
            front = st.number_input("前梁弦向位置（%）",min_value=15.,max_value=35.,value=base.front_spar_fraction*100)
            rear = st.number_input("后梁弦向位置（%）",min_value=55.,max_value=80.,value=base.rear_spar_fraction*100)
            ribs = st.number_input("内翼肋数量",min_value=2,max_value=11,value=base.rib_count,step=1,
                                   help="默认四肋已验证；带中心肋等部分交线组合可能生成退化单元，程序会拒绝通过并保留日志。")
            skin = st.number_input("蒙皮厚度（mm）",min_value=0.,max_value=30.,value=base.skin_thickness_m*1000)
            spar = st.number_input("梁腹板厚度（mm）",min_value=0.,max_value=30.,value=base.spar_thickness_m*1000)
            rib = st.number_input("肋板厚度（mm）",min_value=0.,max_value=30.,value=base.rib_thickness_m*1000)
            min_edge = st.number_input("最小网格边长（m）",min_value=.01,max_value=1.,value=float(base.min_edge_m),step=.01)
        clicked = st.form_submit_button("一键生成并检查网格",type="primary")
    data = base.to_dict()
    data.update(name=name,half_span_m=span,chord_m=chord,max_edge_m=edge,min_edge_m=min_edge,
                front_spar_fraction=front/100,rear_spar_fraction=rear/100,rib_count=int(ribs),
                skin_thickness_m=skin/1000,spar_thickness_m=spar/1000,rib_thickness_m=rib/1000)
    st.download_button("保存网格方案",json.dumps(data,ensure_ascii=False,indent=2),"structure-mesh.json")
    if clicked:
        try:
            with st.spinner("正在生成结构、划分网格并检查……"):
                st.session_state["mesh_result"] = run_structure_mesh(data,ROOT)
        except (ValueError,TypeError) as exc:
            st.error(str(exc))
    if "mesh_result" in st.session_state:
        r = st.session_state["mesh_result"]
        st.caption(f"最近运行编号：{r['run_id']}。修改参数后需重新运行。")
        if r["status"] == "failed":
            st.error(r["error"])
            if r.get("diagnostic"):
                st.code(r["diagnostic"],language=None)
        else:
            st.success("网格生成与检查通过")
            summary = r["summary"]; metrics=summary["metrics"]
            a,b,c = st.columns(3)
            a.metric("节点数",metrics["nodes"]);b.metric("壳单元数",metrics["elements"])
            c.metric("壳体材料量（半翼）",f"{metrics['shell_material_mass_kg']:.2f} kg")
            work = ROOT/"runs"/r["run_id"]/"mesh"
            st.image((work/"mesh_preview.svg").read_text(encoding="utf-8"),caption="网格俯视投影；不是应力或变形图")
            for label,filename in (("下载 OpenVSP 结构模型","structure.vsp3"),("下载 CalculiX 网格","wing.inp")):
                st.download_button(label,(work/filename).read_bytes(),filename)
            for limit in summary["limits"]:
                st.caption(limit)
        with st.expander("完整检查记录"):
            st.json(r)
        st.download_button("下载网格检查记录",json.dumps(r,ensure_ascii=False,indent=2),"mesh-result.json")
elif page == "公开基准算例":
    st.subheader("复现公开软件案例")
    st.write("算例保留上游默认条件，在独立目录运行。它们用来检查软件和方法，尚未与本工作台的飞机模型联算。")
    references = {"FAST-GA 总体案例":"fastga","CalculiX 悬臂梁基准":"calculix",
                  "OpenAeroStruct 官方结构优化与管梁验证":"oas","OpenVSP 结构网格加密与翼展变化":"vsp_structure"}
    ref = st.selectbox("选择案例", list(references))
    st.caption("各案例保留独立计算记录。FAST-GA 可能需要数分钟；结构网格基准比较两档网格和翼展变化。")
    if st.button("运行公开案例", type="primary"):
        with st.spinner("正在执行基准并保存日志……"):
            st.session_state["reference_result"] = run_reference(ROOT, references[ref])
    if "reference_result" in st.session_state:
        r = st.session_state["reference_result"]
        if r["status"] == "failed":
            st.error(r["error"])
        elif r["status"] == "executed_with_limits":
            st.warning("参考案例复现完成，但部分经验方法超出范围，须复核后再用于工程方案。")
        else:
            st.success("案例运行结束。请结合日志与验证记录评估结果。")
        summary = r.get("summary", {})
        if "official" in summary:
            st.metric("官方 CRM 管梁回归质量",f"{summary['official']['mass_kg']:.6f} kg")
            st.caption(f"相对官方回归值误差：{summary['official']['mass_relative_error']:.3e}；该合成案例不作为目标飞机重量。")
            st.dataframe(pd.DataFrame([{"单元数":v["elements"],"端位移（mm）":v["tip_displacement_m"]*1000,
                                        "位移相对误差":v["relative_errors"]["tip"],"应力相对误差":v["relative_errors"]["stress_midpoint"]}
                                       for v in summary["straight_tube"]]),hide_index=True)
        if "coarse" in summary:
            st.dataframe(pd.DataFrame([{"方案":name,"节点数":summary[key]["metrics"]["nodes"],
                                        "单元数":summary[key]["metrics"]["elements"],
                                        "壳体材料量 kg":summary[key]["metrics"]["shell_material_mass_kg"]}
                                       for name,key in (("基准网格","coarse"),("加密网格","fine"),("半翼展增加","longer"))]),hide_index=True)
            if summary.get("passed"):
                st.caption("网格材料量与表面积差异检查通过，结构应力和变形收敛尚待后续求解验证。")
            else:
                st.warning("网格材料量或表面积差异未通过验收，请查看完整记录中的差异与阈值。")
        for limit in summary.get("limits",[]):
            st.caption(limit)
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
