# WingDesignHub

面向固定翼飞机概念设计的本地工程工作台。当前版本 **V0.2.3**：在需求→总体→OpenVSP→AVL 链上接通纵向升力面配平，统一工况质量/重心/燃油来源，提供实际残差、尾翼载荷、舵量余量、超限诊断、保存重开和报告。

目标是让用户给出有效载荷、航程/航时及可选起飞重量等少量需求，一键开展正向总体设计，形成初步技术参数、可行性诊断和方案比较。FAST-GA/OpenMDAO、OpenVSP、AVL/XFOIL、CCBlade、OpenAeroStruct、CalculiX 等工具支撑这一主流程，并逐步覆盖 AAA 十模块。

默认首页“新建飞机方案”已能从少量需求生成初步构型、翼面积、重量、燃油和安装功率，并一键比较三个方案。计算采用 FAST-GA 原生部件重量、明确的概念极曲线与任务积分；输入、结果、报告可以一起保存，重开后复算。V0.2.0 交付软件阶段验证及专业评审材料，专业签署仍待完成。完整气动力/推进平衡、起降距离与结构质量回写按后续路线接入。详见 [产品主流程](docs/FORWARD_DESIGN.md)、[阶段验证](docs/VALIDATION_V0.2.0.md)与[评审材料](docs/REVIEW_V0.2.0.md)。

V0.2.1 已生成并核验 12 部件全机外形；V0.2.2 的固定迎角分析保留。V0.2.3 对机翼、平尾和垂尾求水平飞行 CL/Cm 平衡；机身、黏性与推进贡献仍待接入，轴向力尚未闭合，总体任务保持原概念极曲线。见[几何接口](docs/GEOMETRY_INTERFACE.md)、[气动接口](docs/AERODYNAMICS_INTERFACE.md)、[配平与状态接口](docs/TRIM_INTERFACE.md)和[本版验证](docs/VALIDATION_V0.2.3.md)。

## 普通用户

在已配置的电脑上，双击 **启动 WingDesignHub.cmd**。浏览器会自动打开本地界面。

1. 在“新建飞机方案”填写载荷合计（含机组），选择起飞重量为规定值、上限或待求量。
2. 选择航程、航时、同一任务同时约束两者，或往返转场加额外留空；储备独立填写。
3. 核对巡航速度、高度、储备和初始构型假设，勾选确认，点击“运行初步总体设计”。页面给出初步参数、约束表、构型图及可下载的报告；通常可保留高级假设默认值。
   在结果下点击“生成全机几何”，可旋转查看外形。再点击“运行全机气动”，可查看升力、诱导阻力、力矩及条带载荷，导出气动报告和配平接口。默认工况即可运行，展开设置可修改迎角/舵偏等。之后保存方案会同时保存总体、几何和最后一次气动结果；修改需求后重新计算。
4. 展开“三方案比较与需求变化”，选择展弦比或巡航速度比较设计，或选择载荷、航程、航时研究需求变化。填入三个取值，核对共同假设后点击“一键计算并比较三个方案”。支持保存/导入三方案配置、下载可打印方案卡及 ZIP 包。
5. 点击“保存方案到本机”或“保存三方案到本机”。下次从顶部“打开本机方案”恢复输入和历史结果；重新运行产生新记录。也可以导出 `.wdh` 完整方案包，在另一台已配置电脑导入。
6. 点击“导出可打印总体报告”或“导出可打印比较报告”，用浏览器打开 HTML，可打印或另存 PDF。报告包含需求、参数、约束、任务燃油账目、来源及诊断。

耗油默认仍为原有统一假设。高级输入可选择“经济巡航参考”：65% 功率点用于校准，55%/75% 点为同源留出检查，独立试验资料仍缺；范围外继续使用基础耗油率。原约 26.5% 偏差及处理依据见 [耗油模型说明](docs/FUEL_MODEL.md)。完整操作和文件恢复规则见 [使用流程](docs/WORKFLOW.md)。

“检查并保存需求”只保存定义；“运行初步总体设计”才执行总体计算。已检查约束满足时仍明确显示模型边界，未收敛、超出适用域和约束超限分别显示。需求或假设改变后重新确认、计算；旧版需求导入后会补充定尺寸假设。单模块工具仍可从侧栏进入。

“公开基准算例”可一键运行 CalculiX 2.23 梁网格加密检查，或 FAST-GA 总体参考案例。FAST-GA 的三项经验范围限制会直接显示在结果页；参考复现通过与工程适用性分别记录。

V0.1.2 新增两项结构入口：

- “公开基准算例”→“OpenAeroStruct 官方结构优化与管梁验证”：运行官方 CRM 管梁回归及独立解析检查。
- “结构网格”：默认生成带蒙皮、两梁、四道内肋的矩形半翼，显示网格投影、节点/单元数和半翼壳体材料量，下载 `.vsp3` 模型与 `.inp` 网格。输入与结果各自保存；生成文件尚无载荷、边界条件或分析步。

网格加密及翼展变化可在“公开基准算例”中一键复算。部分中心肋交线组合会产生退化单元，程序拒绝通过并显示诊断。详见 [V0.1.2 验证与适用范围](docs/VALIDATION_V0.1.2.md)。

V0.1.3 新增“机翼静力”：保留默认方案，点击“一键生成并校核”，自动生成半翼网格、传递规定载荷并调用 CalculiX。默认半翼限制升力 5000 N、极限系数 1.5、根部全固支；最大网格边长 0.2 m。页面显示位移、积分点应力和规定限值下的屈服筛查裕度，可下载完整输入、三维结果和载荷记录。

“公开基准算例”新增 OAS 官方翼盒与燃油卸载检查，以及代表半翼三档网格、正负/双倍载荷和 S6 解析梁验证。当前静力工况为独立合成输入，尚未覆盖全机载荷包线、屈曲、真实材料许用值或结构重量回写。详见 [V0.1.3 验证与适用范围](docs/VALIDATION_V0.1.3.md)。

CalculiX 基准要求 2.23。其他电脑可从 [CalculiX Windows 项目](https://github.com/calculix/CalculiX-Windows)获取对应便携包，在“工具设置”填写 `bin/ccx.exe`，无需修改系统 PATH。完整数值及来源见 [V0.1.1 验证记录](docs/VALIDATION_V0.1.1.md)。

首次在其他电脑部署：安装 Python 3 后双击 `Setup WingDesignHub.cmd`。脚本创建项目专用环境，不修改系统 PATH。OpenVSP、AVL 等外部软件需要单独配置；本版全机几何使用 OpenVSP 3.56.0 的 Python 3.13 API，安装说明见官方发行包。侧栏独立 OpenVSP/AVL 演示仍为矩形 NACA0012 机翼，全机外形从主入口进入。

关闭浏览器后本地服务仍可供再次打开使用。双击 **关闭 WingDesignHub.cmd** 可关闭本项目服务。服务仅监听 127.0.0.1。

## 开发与验证

V0.2.3：Python `trim_service.run_aircraft_trim(project, root, geometry_run_id, options)`；CLI `trim --geometry-run-id ID [--trim-options options.json]`。归档通过 `--trim-run-id ID` 保存完整配平记录。主界面“纵向配平”使用同一服务，无需先运行固定迎角分析。`scripts/validate_aircraft_trim.py local/new-trim-validation` 验证质量/CG/速度、三档网格、失败状态、原生配平对照与 MIT Vanilla 公开输入；已有原始文件按固定哈希读取，不自动改动第三方安装。方案包维持 50 MB 总大小限制，文件数上限 1024 以容纳迭代原始记录。

V0.2.2：Python 服务 `aero_service.run_aircraft_aero(project, root, geometry_run_id, options)`；CLI `aero --geometry-run-id ID [--aero-options options.json]`。归档增加 `--aero-run-id ID`，与来源总体和几何一起保存。`scripts/validate_aircraft_aero.py local/new-aero-validation` 执行五组需求、三档气动离散、对称/参考点/导数及官方算例验证；首次获取公开输入需要网络，已有官方文件可按固定哈希复用。要求已验证的 AVL 3.40 MRF 输出。

V0.2.1：Python 服务 `geometry_service.run_aircraft_geometry(project, root, sizing_run_id)`，CLI `geometry --run-id ID`；归档可用 `archive-save --run-id 总体ID --geometry-run-id 几何ID --output aircraft.wdh`。几何与父总体独立记录，检查源版本、输入、原生文件与气动参考量一致性。`scripts/validate_aircraft_geometry.py local/new-geometry-validation` 运行需求变化、两档几何离散、保存重开和随包 API 算例。

V0.2.0：`project_archive.build_bundle/read_bundle/save_bundle/load_saved` 共享保存重开逻辑，方案包校验 SHA-256、输入定义与运行产物，导入时不执行文件、不覆盖原记录。需求 schema 3 增加耗油模型选择；schema 1/2 迁移保持统一耗油语义并清除旧确认。报告由实际计算记录生成，校准、同源留出及异条件外部参考分开标记。

CLI 新增 `fuel-check`、`archive-save --run-id ID --output design.wdh`、`archive-open --input design.wdh`、`report --run-id ID --output report.html`。草案可用 `archive-save --input examples/economy_design.json`。正式阶段脚本为 `python scripts/validate_stage.py local/new-stage-validation`；输出目录必须新建，旧证据保留。普通用户无需运行这些命令。

V0.1.8：`run_comparison(request, root)` 从三个配置计算；`compare_sizing_runs(root, ids, purpose)` 从三个已有总体记录重新生成比较。不同软件、求解器或上游模型/数据证据拒绝混比；超限/失败方案保留，未收敛输出不填零。一次只变化一个参数，同任务比较与不同需求的敏感性分别标识，默认不做综合最优排名。

CLI：`compare --input examples/three_designs.json`、`compare-runs --run-ids ID1 ID2 ID3`、`cruise-check`；示例配置待确认。正式验收脚本 `python scripts/validate_comparison.py local/new-validation`，方法和证据见 [V0.1.8 报告](docs/VALIDATION_V0.1.8.md)。每次版本更新先核对路线与产品缺口，再开展有界实现和验证，约定已写入 AGENTS。

V0.1.7：`wingdesignhub.sizing_service.run_sizing(project, root)` 和 CLI `size --input ...` 与界面共用。需求 schema 2 增加定尺寸假设，schema 1 自动迁移并清除旧确认。后台独立进程调用 FAST-GA `MassBreakdown(payload_from_npax=False)`，总载荷直接输入；首次使用无需先逐个运行专业工具。

`python scripts/validate_sizing.py local/your-validation-directory` 验证十二种重量/任务组合、参数变化、积分步长、失败诊断和公开参考任务。数值和边界见 [V0.1.7 报告](docs/VALIDATION_V0.1.7.md)。储备导数已用插件修复并独立核验，完整模型梯度优化仍待验证。

V0.1.6：Python 服务 `prepare_design_project` 保存需求、任务和确认哈希；`run_fastga_reference` 通过隔离进程执行固定公开总体任务，核对 20 项变量的真实输入/输出角色及质量、燃油、航程账目。CLI 提供 `prepare --input examples/aircraft_requirements.json`、`fastga-contract`、`fastga-reference`。示例配置待用户确认；CLI 的待确认/冲突状态返回非零退出码。

`python scripts/validate_design_entry.py` 复算 12 组需求组合及公开任务。接口映射、储备与载荷口径、上游导数限制和数值记录见 [FAST-GA 接口](docs/FASTGA_INTERFACE.md)与 [V0.1.6 验证报告](docs/VALIDATION_V0.1.6.md)。

V0.1.5 新增“代表板屈曲”一键页，可输入尺寸、膜应力与简支/固支条件，查看首阶实际工况载荷系数和归一化模态。“公开基准算例”增加代表板解析/网格/参考载荷验证、载荷作用区与支承敏感性。默认半翼的局部稳定性风险仍未关闭；代表板结果与整翼极限承载能力分别记录。详见 [V0.1.5 验证报告](docs/VALIDATION_V0.1.5.md)。

自动化接口：`python -m wingdesignhub.cli plate --input examples/plate_buckling.json`；基准名称为 `plate_buckling`、`structural_sensitivity`。程序自动归一化求解参考载荷并换算回用户应力状态，避免在高应力参考工况下遗漏较低屈曲模态。

V0.1.4 使用方法：双击启动后进入“载荷与屈曲”，保留默认参数，点击“一键计算载荷与结构”。可修改质量、速度、载荷因数、燃油、设备位置和板厚。结果同时显示升力、各项卸载及板屈曲指标；**默认合成方案屈服筛查通过、局部屈曲筛查未满足**，界面保留该诊断。此页使用竖向 `-m*n_z*g` 有效质量载荷，未包含转动惯性和全机配平。

“公开基准算例”→“同构型翼盒梁与壳对照”可一键复算独立矩形翼盒的弯曲/扭转与网格检查。该基准与 NACA 半翼分别定义；适用范围、量化误差及原始失败过程见 [V0.1.4 验证报告](docs/VALIDATION_V0.1.4.md)。

开发者可使用 `python -m wingdesignhub.cli flight --input examples/flight_loads.json`、`python -m wingdesignhub.cli reference --benchmark box_comparison`；`python scripts/validate_flight_loads.py` 复算四组载荷/网格案例及 AVL 条带加密。普通用户使用界面即可。

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m wingdesignhub.cli doctor
.venv\Scripts\python.exe -m wingdesignhub.cli run --input examples/wing.json --mode beam
.venv\Scripts\python.exe scripts/validate_fastga.py
.venv\Scripts\python.exe scripts/validate_calculix.py
.venv\Scripts\python.exe -m wingdesignhub.cli reference --benchmark oas
.venv\Scripts\python.exe -m wingdesignhub.cli reference --benchmark vsp_structure
.venv\Scripts\python.exe -m wingdesignhub.cli mesh --input examples/structure_mesh.json
.venv\Scripts\python.exe -m wingdesignhub.cli static --input examples/wing_static.json
.venv\Scripts\python.exe -m wingdesignhub.cli reference --benchmark oas_wingbox
.venv\Scripts\python.exe -m wingdesignhub.cli reference --benchmark shell_static
```

计算快照、日志和输入/代码/输出哈希保存在 `runs`；本机路径保存在 `local`，都不进入版本管理。当前不复用计算缓存，每次运行独立保存；后续缓存必须验证完整输入与软件版本。

## 进展与方法

- [版本路线图](docs/ROADMAP.md)
- [十模块覆盖表](docs/COVERAGE.md)
- [验证方法和适用范围](docs/VALIDATION.md)
- [实际开发记录](docs/PROGRESS.md)
- [第三方软件与许可](docs/THIRD_PARTY.md)

本仓库不包含 AAA 手册、院所工程资料、其他项目数据、第三方二进制和凭据。公开示例为独立合成算例。源代码按 GPL-3.0-only 发布；第三方组件遵循各自许可。
