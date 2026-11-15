# 软件来源与复用边界

本项目原创代码采用 GPL-3.0-only，与首期 FAST-GA 集成路线保持一致。第三方程序不重新授权、不作为本仓库二进制分发。

| 软件 | 来源 | 当前用途 |
|---|---|---|
| FAST-GA 1.4.0 | https://github.com/supaero-aircraft-design/FAST-GA | 隔离安装、随包教程；项目插件替换家具质量求和，工作进程内适配任务 CSV |
| OpenMDAO | https://github.com/OpenMDAO/OpenMDAO | FAST-GA/OAS 依赖 |
| OpenVSP 3.56.0 | https://openvsp.org/ | 本机既有程序；主体 NOSA 1.3；Python 包中的 MIT 标记不替代主体许可 |
| AVL | https://web.mit.edu/drela/Public/web/avl/ | 本机程序，GPL；独立运行与解析 |
| OpenAeroStruct | https://github.com/mdolab/OpenAeroStruct | 已隔离安装，结构接入继续开发 |
| CalculiX 2.23 | https://github.com/calculix/CalculiX-Windows | GPL；项目内 Windows x64 便携包；实际版本/二进制哈希随运行保存；旧 GE 2.10 仅保留用于失败对照 |
| Python runtime | https://github.com/astral-sh/python-build-standalone | uv 管理的项目内 CPython 3.13.18；运行时及安装缓存不发布 |

依赖精确版本见 requirements-lock.txt。OpenVSP 的四个本机接口包单独安装，禁止把本机路径写入公开锁文件。FAST-GA 随包公开数据仅在本地运行目录展开，发布其来源和核验摘要。

`fastga_compat.py` 的 CSV 写入方法与 `fastga_plugins/furniture.py` 的分组来自 FAST-GA 1.4.0 的 `models/performances/mission/dynamic_equilibrium.py`、`models/weight/mass_breakdown/d_furniture/sum.py`，原文件声明 Copyright (C) 2025 ONERA & ISAE-SUPAERO、GPL-3.0-or-later。保留署名与许可，项目修改为 `DataFrame.map` 和单输入质量/正确导数。局部适配由上下文管理器恢复，不修改安装包；依赖升级需要复验。

CalculiX 包来源：`https://raw.githubusercontent.com/calculix/CalculiX-Windows/master/releases/CalculiX-2.23.0-win-x64.zip`；SHA-256：`79a674fdee735a22720bbd12bb9ccbadad1e8c8ad5b1de74e1c62f8808b2d395`。仅本地解压，仓库不分发二进制。
