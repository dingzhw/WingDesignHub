# WingDesignHub

面向固定翼飞机概念设计的本地工程工作台。当前版本 **V0.1.5**：总体主线规划调整、代表板线性屈曲与结构敏感性验证版。

目标是让用户给出有效载荷、航程/航时及可选起飞重量等少量需求，一键开展正向总体设计，形成初步技术参数、可行性诊断和方案比较。FAST-GA/OpenMDAO、OpenVSP、AVL/XFOIL、CCBlade、OpenAeroStruct、CalculiX 等工具支撑这一主流程，并逐步覆盖 AAA 十模块。

当前已接通部分气动—载荷—结构分析链，**尚未实现从少量需求到整机方案的完整正向设计**。本次明确了两种重量模式及任务/假设约定：V0.1.6 起建设需求入口，V0.1.7 接通定尺寸和总体迭代，V0.1.8 做方案比较，V0.2.0 验收正向设计最小闭环。详见 [产品主流程](docs/FORWARD_DESIGN.md)与[路线图](docs/ROADMAP.md)。

## 普通用户

在已配置的电脑上，双击 **启动 WingDesignHub.cmd**。浏览器会自动打开本地界面。

1. 默认选择“梁解析解验证”，保留示例参数。
2. 点击“一键运行”，查看翼尖挠度、根部反力矩与解析误差。
3. 工具接好后可选择“OpenVSP 几何 → AVL → 载荷 → 梁变形”。
4. 使用“保存方案”和“下载计算摘要”保存结果。

“公开基准算例”可一键运行 CalculiX 2.23 梁网格加密检查，或 FAST-GA 总体参考案例。FAST-GA 的三项经验范围限制会直接显示在结果页；参考复现通过与工程适用性分别记录。

V0.1.2 新增两项结构入口：

- “公开基准算例”→“OpenAeroStruct 官方结构优化与管梁验证”：运行官方 CRM 管梁回归及独立解析检查。
- “结构网格”：默认生成带蒙皮、两梁、四道内肋的矩形半翼，显示网格投影、节点/单元数和半翼壳体材料量，下载 `.vsp3` 模型与 `.inp` 网格。输入与结果各自保存；生成文件尚无载荷、边界条件或分析步。

网格加密及翼展变化可在“公开基准算例”中一键复算。部分中心肋交线组合会产生退化单元，程序拒绝通过并显示诊断。详见 [V0.1.2 验证与适用范围](docs/VALIDATION_V0.1.2.md)。

V0.1.3 新增“机翼静力”：保留默认方案，点击“一键生成并校核”，自动生成半翼网格、传递规定载荷并调用 CalculiX。默认半翼限制升力 5000 N、极限系数 1.5、根部全固支；最大网格边长 0.2 m。页面显示位移、积分点应力和规定限值下的屈服筛查裕度，可下载完整输入、三维结果和载荷记录。

“公开基准算例”新增 OAS 官方翼盒与燃油卸载检查，以及代表半翼三档网格、正负/双倍载荷和 S6 解析梁验证。当前静力工况为独立合成输入，尚未覆盖全机载荷包线、屈曲、真实材料许用值或结构重量回写。详见 [V0.1.3 验证与适用范围](docs/VALIDATION_V0.1.3.md)。

CalculiX 基准要求 2.23。其他电脑可从 [CalculiX Windows 项目](https://github.com/calculix/CalculiX-Windows)获取对应便携包，在“工具设置”填写 `bin/ccx.exe`，无需修改系统 PATH。完整数值及来源见 [V0.1.1 验证记录](docs/VALIDATION_V0.1.1.md)。

首次在其他电脑部署：安装 Python 3 后双击 `Setup WingDesignHub.cmd`。脚本创建项目专用环境，不修改系统 PATH。OpenVSP、AVL 等外部软件需要单独配置；当前示范机的几何模板仅支持矩形 NACA0012 机翼。

关闭浏览器后本地服务仍可供再次打开使用。双击 **关闭 WingDesignHub.cmd** 可关闭本项目服务。服务仅监听 127.0.0.1。

## 开发与验证

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
