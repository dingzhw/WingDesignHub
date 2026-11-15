# 软件来源与复用边界

本项目原创代码采用 GPL-3.0-only，与首期 FAST-GA 集成路线保持一致。第三方程序不重新授权、不作为本仓库二进制分发。

| 软件 | 来源 | 当前用途 |
|---|---|---|
| FAST-GA 1.4.0 | https://github.com/supaero-aircraft-design/FAST-GA | GPL-3.0-only；隔离安装，运行随包教程；尚未替换其总体模型 |
| OpenMDAO | https://github.com/OpenMDAO/OpenMDAO | FAST-GA/OAS 依赖 |
| OpenVSP 3.56.0 | https://openvsp.org/ | 本机既有程序；主体 NOSA 1.3；Python 包中的 MIT 标记不替代主体许可 |
| AVL | https://web.mit.edu/drela/Public/web/avl/ | 本机程序，GPL；独立运行与解析 |
| OpenAeroStruct | https://github.com/mdolab/OpenAeroStruct | 已隔离安装，结构接入继续开发 |
| CalculiX | https://www.dhondt.de/ | 基准试运行使用官网指向 GeneralElectric/CalculiX 的 Windows 2.10 便携包；GPL；代表件阶段升级当前版并重验 |
| Python runtime | https://github.com/astral-sh/python-build-standalone | uv 管理的项目内 CPython 3.13.18；运行时及安装缓存不发布 |

依赖精确版本见 requirements-lock.txt。OpenVSP 的四个本机接口包单独安装，禁止把本机路径写入公开锁文件。FAST-GA 随包公开数据仅在本地运行目录展开，发布其来源和核验摘要。
