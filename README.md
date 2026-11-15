# WingDesignHub

面向固定翼飞机概念设计的本地工程工作台。当前版本 **V0.1.0**：计算基础与关键路径开发版。

目标是整合 FAST-GA/OpenMDAO、OpenVSP、AVL/XFOIL、CCBlade、OpenAeroStruct、CalculiX 等工具，逐步覆盖 AAA 的十个核心模块。当前提供合成机翼/梁案例、真实 OpenVSP/AVL 调用、载荷映射、计算记录和中文界面。完整整机设计与 AI 功能仍按路线图开发。

## 普通用户

在已配置的电脑上，双击 **启动 WingDesignHub.cmd**。浏览器会自动打开本地界面。

1. 默认选择“梁解析解验证”，保留示例参数。
2. 点击“一键运行”，查看翼尖挠度、根部反力矩与解析误差。
3. 工具接好后可选择“OpenVSP 几何 → AVL → 载荷 → 梁变形”。
4. 使用“保存方案”和“下载计算摘要”保存结果。

首次在其他电脑部署：安装 Python 3 后双击 `Setup WingDesignHub.cmd`。脚本创建项目专用环境，不修改系统 PATH。OpenVSP、AVL 等外部软件需要单独配置；当前示范机的几何模板仅支持矩形 NACA0012 机翼。

关闭浏览器后本地服务仍可供再次打开使用。双击 **关闭 WingDesignHub.cmd** 可关闭本项目服务。服务仅监听 127.0.0.1。

## 开发与验证

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m wingdesignhub.cli doctor
.venv\Scripts\python.exe -m wingdesignhub.cli run --input examples/wing.json --mode beam
.venv\Scripts\python.exe scripts/validate_fastga.py
.venv\Scripts\python.exe scripts/validate_calculix.py
```

计算快照、日志和输入/代码/输出哈希保存在 `runs`；本机路径保存在 `local`，都不进入版本管理。当前不复用计算缓存，每次运行独立保存；后续缓存必须验证完整输入与软件版本。

## 进展与方法

- [版本路线图](docs/ROADMAP.md)
- [十模块覆盖表](docs/COVERAGE.md)
- [验证方法和适用范围](docs/VALIDATION.md)
- [实际开发记录](docs/PROGRESS.md)
- [第三方软件与许可](docs/THIRD_PARTY.md)

本仓库不包含 AAA 手册、院所工程资料、其他项目数据、第三方二进制和凭据。公开示例为独立合成算例。源代码按 GPL-3.0-only 发布；第三方组件遵循各自许可。
