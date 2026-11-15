# 软件来源与复用边界

本项目原创代码采用 GPL-3.0-only，与首期 FAST-GA 集成路线保持一致。第三方程序不重新授权、不作为本仓库二进制分发。

V0.2.1 依据 [OpenVSP 3.56 Python API](https://openvsp.org/pyapi_docs/3.56.0/)和随包 API 测试，独立实现常规单发几何模板与接口；选定随包算例原样运行并记录实际哈希，原生库和测试源码保持只读、不进入本仓库。三维预览使用已锁定的 Plotly 6.9.0（MIT），新增直接依赖声明，环境已有包不升级。输出飞机与外形模板为本项目公开合成算例。

V0.2.0 耗油参考依据 Piper VB-760 的 Fig.5-13（打印页 5-17，PDF 80）经济混合比表值，来源为[原厂手册公开镜像](https://www.summitaviationspokane.com/wp-content/uploads/2025/08/pa-28-181-archer-ii-poh.pdf)。另核对 [Lycoming 官方 60297-12 手册](https://www.lycoming.com/sites/default/files/file/2025-11/60297-12%20-%20O-360%2C%20HO-360%2C%20IO-360%2C%20AIO-360%2C%20HIO-360%2C%20and%20TIO-360%20Series.pdf) 3-7、3-12 页的混合比示意和发动机族表值。仅发布少量事实、原文件哈希、来源和独立实现的换算；不分发原手册或图页，不将原厂文字作为本项目许可内容。数据角色和条件差异见 [FUEL_MODEL](FUEL_MODEL.md)。本版没有新增第三方运行依赖。

V0.1.8 对照 Piper Aircraft 原厂《PA-28-181 Cherokee Archer II POH》VB-760（1975-08-15），读取 [公开镜像](https://www.summitaviationspokane.com/wp-content/uploads/2025/08/pa-28-181-archer-ii-poh.pdf) 的 1-2/1-3、5-4/5-5、5-19 页；PDF SHA-256 `0a51a23b0db5d4d1bbb063484a56d7ed12a0a1935da96e5c90e88dd13e1bd43c`。只发布对照所需少量事实数值、来源与模型偏差；原 PDF 和页面图在本地保存，未重新分发手册或图表。比较/卡片服务为独立实现，无新增求解器和第三方依赖。

V0.1.7 新单发流程调用 FAST-GA 1.4.0 原生 `MassBreakdown(payload_from_npax=False)` 及 `BasicICEngine.compute_weight`。质量关系以该版本 [质量组源代码](https://github.com/supaero-aircraft-design/FAST-GA/tree/v1.4.0/src/fastga/models/weight/mass_breakdown) 为依据；仅在本地读取随包 SR22 桨图以满足发动机对象构造接口，当前新机任务性能不使用该桨图。新方案采用独立模板和可见气动/推进假设，固定公开双发参考仍单独回归。

`fastga_plugins/reserve.py` 继承 [FAST-GA 储备组件](https://github.com/supaero-aircraft-design/FAST-GA/blob/v1.4.0/src/fastga/models/performances/mission/mission_components/reserve.py)，原始版权 (C) 2022 ONERA & ISAE-SUPAERO、GPL-3.0-or-later；保留原函数，项目修正解析导数。新不可用燃油插件与总体任务积分独立实现。升阻力方程与诱导阻力形式见 NASA Glenn 的 [升力方程](https://www1.grc.nasa.gov/beginners-guide-to-aeronautics/lift-equation/)、[阻力方程](https://www1.grc.nasa.gov/beginners-guide-to-aeronautics/drag-equation/)及[诱导阻力](https://www1.grc.nasa.gov/beginners-guide-to-aeronautics/induced-drag-coefficient/)。这些来源支撑方程形式，默认系数仍是项目假设，尚未用飞机试验数据校准。

| 软件 | 来源 | 当前用途 |
|---|---|---|
| FAST-GA 1.4.0 | https://github.com/supaero-aircraft-design/FAST-GA | 隔离安装、随包教程；项目插件替换家具质量求和，工作进程内适配任务 CSV |
| OpenMDAO | https://github.com/OpenMDAO/OpenMDAO | FAST-GA/OAS 依赖 |
| OpenVSP 3.56.0 | https://openvsp.org/ | 本机既有程序；主体 NOSA 1.3；Python 包中的 MIT 标记不替代主体许可 |
| AVL | https://web.mit.edu/drela/Public/web/avl/ | 本机程序，GPL；独立运行与解析 |
| OpenAeroStruct 2.12.1 | https://github.com/mdolab/OpenAeroStruct | Apache-2.0；复现官方结构独立优化、调用 SpatialBeamAlone 并以解析管梁检查 |
| CalculiX 2.23 | https://github.com/calculix/CalculiX-Windows | GPL；项目内 Windows x64 便携包；实际版本/二进制哈希随运行保存；旧 GE 2.10 仅保留用于失败对照 |
| Python runtime | https://github.com/astral-sh/python-build-standalone | uv 管理的项目内 CPython 3.13.18；运行时及安装缓存不发布 |

依赖精确版本见 requirements-lock.txt。OpenVSP 的四个本机接口包单独安装，禁止把本机路径写入公开锁文件。FAST-GA 随包公开数据仅在本地运行目录展开，发布其来源和核验摘要。

`fastga_compat.py` 的 CSV 写入方法与 `fastga_plugins/furniture.py` 的分组来自 FAST-GA 1.4.0 的 `models/performances/mission/dynamic_equilibrium.py`、`models/weight/mass_breakdown/d_furniture/sum.py`，原文件声明 Copyright (C) 2025 ONERA & ISAE-SUPAERO、GPL-3.0-or-later。保留署名与许可，项目修改为 `DataFrame.map` 和单输入质量/正确导数。局部适配由上下文管理器恢复，不修改安装包；依赖升级需要复验。

CalculiX 包来源：`https://raw.githubusercontent.com/calculix/CalculiX-Windows/master/releases/CalculiX-2.23.0-win-x64.zip`；SHA-256：`79a674fdee735a22720bbd12bb9ccbadad1e8c8ad5b1de74e1c62f8808b2d395`。仅本地解压，仓库不分发二进制。

V0.1.2 的 `oas_benchmark.py` 中 CRM 设置改编自 OpenAeroStruct **v2.12.1** 的 `tests/integration_tests/test_struct.py`，保留该版本参考质量与物理输入，新增结果记录、输入快照、失败判断和独立解析测试。原始源文件 SHA-256 为 `a4553c51f17df50f037d7bde6913c9a9d6761d6a26fa4d2926f9597852c9f40d`，原许可副本在 `third_party/OpenAeroStruct-LICENSE.txt`。改编文件明确标注来源与修改。

OpenVSP 结构接口依据安装包 3.56.0 自带 API 测试及 [FEA API 文档](https://openvsp.org/pyapi_docs/3.56.0/groups/FEAMesh.html)。本项目调用 API 生成独立合成模型，未复制 OpenVSP 原生库或其他项目飞机数据。

V0.1.3 的 `oas_wingbox.py` 改编自 [OpenAeroStruct v2.12.1 官方翼盒测试](https://github.com/mdolab/OpenAeroStruct/blob/v2.12.1/tests/integration_tests/test_wingbox_analysis.py)，原测试本地文件 SHA-256 为 `4ffb25a6be8df73cd383db146dbbcc0ba3f5041fb9aa19275c7c63e1920d791b`，沿用 Apache-2.0 许可副本。保留翼型坐标、几何、载荷、燃油、材料和优化参考值；显式给出 num_x=3，将虚部为零的物理坐标转为实数，记录并显式执行优化器原本的初值裁剪，补充燃油合力检查。上游完整测试也在本地原样执行；本轮未将其导数测试替代独立梯度精度验收。

CalculiX 壳单元、输出和边界依据随包 2.23 手册（6.2.13–6.2.14、7.4、7.53、7.97、7.99、7.123；[官网](https://www.dhondt.de/)）。数值字段截断通过本机构型实际复现，并核对上游 [nodes.f](https://github.com/Dhondtguido/CalculiX/blob/master/src/nodes.f) 和 [cloads.f](https://github.com/Dhondtguido/CalculiX/blob/master/src/cloads.f) 中的 `f20.0` 读取规则。本项目未修改求解器二进制或上游源码。

V0.1.4 局部板屈曲依据 Gerard/Becker 的 [NACA TN 3781（1957）](https://ntrs.nasa.gov/citations/19930084505)，正文 p.15 式 (20)、p.38 式 (53)/(55)、p.39 有限长压剪相互作用讨论及表 3。采用经典解析式独立实现，不复制第三方程序；原报告仅在 local 保存核查，不入仓库。简支剪切长板系数取 5.34，是对表 3 中 5.35 的向下取值，不使用有限长度增强。板边支承、膜应力包络和曲面等效属于项目工程假设。

AVL 条带定义和轴系依据 [AVL 3.40 User Primer](https://web.mit.edu/drela/Public/web/avl/avl_doc.txt) 的 Force and moment output / Trefftz Plane Plotting 章节。V0.1.4 仅以孤立无后掠翼条带升力近似竖向载荷；轴向力、剖面俯仰矩和全机配平另行扩展。新增翼盒、卸载和板筛查代码为项目独立实现，第三方依赖版本未变。

V0.1.5 代表板采用 CalculiX 2.23 S8R、`*BUCKLE` 与原生 DAT/FRD，依据 [官方 2.23 手册](https://www.dhondt.de/ccx_2.23.pdf) §6.2.14、§6.9.4、§7.5、§10.7；经典板解析关系沿用 NACA TN 3781。手册描述了从偏移 1 开始的特征值搜索；高参考载荷遗漏较低模态的现象由本地实际文件复现，项目采用低参考载荷并验证缩放一致性，未修改求解器。新增代码均为独立输入/解析/诊断实现，依赖版本与许可无变更。

V0.1.6 沿用 FAST-GA 1.4.0（GPL-3.0）公开 [Beechcraft XML](https://github.com/supaero-aircraft-design/FAST-GA/blob/v1.4.0/src/fastga/notebooks/tutorial/data/beechcraft_76.xml) 和 fastga.yml，标签提交 `8092ced91226a3583138ecf0a42d80909aaee346`。本地源码核查范围为 `performances/mission/mission.py`、`mission_components/cruise.py` / `reserve.py`、`weight/mass_breakdown/payload.py` / `update_mtow.py` 及 FAST-OAD 1.11.0 的 `evaluate_problem`。需求模型、服务封装和运行时接口审计独立实现；原始参考 XML、求解文件和第三方源码不新增至公开仓库。既有兼容层继续保留版权和许可说明，上游源文件未修改。
