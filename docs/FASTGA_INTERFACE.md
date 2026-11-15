# FAST-GA 总体服务接口 — V0.1.7

本版提供需求定义、新单发初步定尺寸、固定公开参考任务三类服务。普通用户从“新建飞机方案”进入，开发者可用同一 Python/CLI 服务。需求就绪表示定义已确认，总体结果分别报告数值收敛、已检查约束及模型边界。

| 服务 | 输入 | 输出与状态 |
|---|---|---|
| `validate_design_project` | `DesignProject` 或 JSON 对象 | 字段/单位类型、重量关系、任务冲突、确认与零储备诊断 |
| `prepare_design_project` | 需求方案、项目目录 | 任务编号、需求快照、任务段、来源、摘要、哈希；`requirements_ready` / `needs_confirmation` / `invalid_input` |
| `get_fastga_contract` | 无 | 固定参考任务的变量、单位、角色与使用边界 |
| `reference_binding_preview` | 需求方案 | 单发重量/载荷/任务映射说明；固定参考任务继续拒绝自定义覆盖 |
| `run_sizing` | 已确认 `DesignProject`、项目目录 | 需求驱动的初步参数、几何、重量/燃油/功率及 CG 历史、约束与完整性哈希 |
| `run_fastga_reference` | 项目目录 | 固定公开任务的运行编号、真实参数、账目、收敛、诊断与产物哈希 |
| `get_results` | 项目目录、任务编号 | 完整性核验后的运行记录 |

`python -m wingdesignhub.cli prepare --input ...` 与 `fastga-reference` 对应上述服务；参考任务拒绝 `--input` 覆盖。原有 `reference --benchmark fastga` 使用同一 worker。求解器在独立子进程运行，600 秒超时，输出保存在独立目录；没有把需求文本作为命令执行。

`python -m wingdesignhub.cli size --input ...` 调用 `run_sizing`，隔离进程超时 240 秒。成功状态为 `concept_checked_with_limits`，明确配平等未覆盖项；`constraints_not_met`、`out_of_domain`、`not_converged`、`failed`、待确认或输入冲突均非成功退出。结果含输入与源码哈希、FAST-GA 质量组 59 项真实绑定及上游源文件哈希、完整输入、迭代、日志、构型图和摘要。

需求 schema 2 新增可调定尺寸假设并纳入确认哈希；schema 1 导入后保留原需求、补充默认假设并清除旧确认。`metal_single_v1` 的固定比值由当前版本模型定义，在界面和本报告说明，运行源码哈希锁定其实现。

## 输入语义与确认

- `weight.mode=fixed`：`value_kg` 必填，保持规定满载设计重量；尺寸和任务按此重量检查。计算装载质量不得超过预算，剩余质量为未分配预算；不添加虚拟压舱物。CG 只对应实际计算台账。
- `upper_bound`：值为上限；重量仍需求解，并检查余量。
- `solve`：值须为空；迭代初猜属于求解器状态，不能与用户规定量混用。
- `payload_kg`：所有机组、乘员、行李、任务设备的合计，计入一次。
- `range_only`：规定主航迹距离；`endurance_only`：最低主任务空中时长。
- `same_route`：同一主任务承担距离和最低航时两项要求，不能相加为两段。
- `transit_loiter`：往返总距离与额外留空时长分列，不把总航程当作单程半径。
- 储备时长独立设置；不贡献已完成的主任务航程/航时。当前储备估算基础为巡航平均耗油率，不含另航机场、百分比应急油等扩展策略。

默认速度 60 m/s、高度 2000 m、储备 2700 s 是有标识的项目演示假设，不是适航规定。环境为标准大气、无风。假设来源与配置保存；定义确认 SHA-256 覆盖需求和假设，重新导入未修改配置可复用，变更会失效。确认记录是定义确认，不是设计结果或专业审核通过。

## 已核实的固定参考流程

版本固定 FAST-OAD-CS23 1.4.0，使用 [公开 XML](https://github.com/supaero-aircraft-design/FAST-GA/blob/v1.4.0/src/fastga/notebooks/tutorial/data/beechcraft_76.xml) 与 [公开流程配置](https://github.com/supaero-aircraft-design/FAST-GA/blob/v1.4.0/src/fastga/configurations/fastga.yml)。标签提交 `8092ced91226a3583138ecf0a42d80909aaee346`；运行前检查 XML SHA-256。模型调用 `generate_configuration_file → generate_inputs → evaluate_problem`，不是 `optimize_problem`；YAML 中的优化变量不会因此自动执行。

| 数量 | 参考流程角色 | 接入注意事项 |
|---|---|---|
| `data:TLAR:range` | 输入；生成后 m | 主航线距离；巡航扣除爬升/下降距离 |
| `data:TLAR:v_cruise` | 输入；m/s | 指定巡航真空速，非求出的最优速度 |
| 巡航高度、储备时长 | 输入；m、s | 原任务为 10000 ft、45 min，接口转为 SI |
| NPAX、单人质量、行李 | 输入 | 载荷模型内含额外 2 名驾驶员 |
| `data:weight:aircraft:payload` | 输出；kg | 默认子模型计算 `(NPAX+2)×单人质量+行李` |
| MTOW / OWE / ZFW / 总燃油 | 输出；kg | MTOW=ZFW+总燃油；总燃油已经含储备 |
| 翼面积/翼展/MAC、机身长度、尾翼面积 | 输出；m²/m | 由参考构型、功率等完整输入驱动 |
| 发动机台数、单台功率 | 输入；无量纲、W | 参考机为两台 130 kW，不是自动选型结果 |

实际计算后通过 OpenMDAO 元数据审计 20 项公开变量的来源和角色，并以 `get_val(..., units=...)` 取 SI 值。只修改输入 XML 中同名 MTOW 不会把求解输出变成固定输入。上限不是当前模型的原生约束，需要后续外层定尺寸流程处理。

新方案直接调用 `MassBreakdown(payload_from_npax=False)`，使 `payload` / `max_payload` 都等于用户给出的含机组总载荷。座位数仅参与设备/座椅重量关系，向这些关系传递的 NPAX_max 为总座位数减 2；不重新计算乘员重量。机身长度与截面是显式模板假设，当前未做详细客舱空间布置校核。

新方案的几何、速度、功率、载荷、油箱容量均显式映射到质量组。只为原生发动机对象构造读取随包 SR22 的桨图；实际发动机重量只用功率回归关系。任务效率和 BSFC 来自可见假设，桨图未作为新机推进性能使用；扰动桨图后质量输出不变已测试。原生推进总和未加不可用燃油，新方案用已声明的总油箱容量比例（默认 2%）替代该子项，再单独加入 OWE 一次；原公开参考任务保持历史合计方式以便回归。

## 数值与适用边界

质量、八项燃油、储备公式及载荷公式残差门槛 0.01 kg；主航线距离残差门槛 `max(1 m, 0.1%×规定航程)`。三项历史重量回归门槛 1e-5 kg；上游自身非线性收敛与上述账目分别检查。详细结果见 [V0.1.6 验证报告](VALIDATION_V0.1.6.md)。

公开模型是双发 Beechcraft 教学案例；本项目目标为常规单发，新方案不自动套用该参考机。保留已定位的升降舵弦长比、平垂尾面积比、有符号升降舵偏角三个经验范围问题。该次收敛不是 V0.2.0 的三轮重量/CG/任务约束验收，也不是独立物理精度验证。

在 [上游储备组件](https://github.com/supaero-aircraft-design/FAST-GA/blob/v1.4.0/src/fastga/models/performances/mission/mission_components/reserve.py) 中，原函数值 `m_c/max(t_c, ε)×t_r×k` 正确；四项 `compute_partials` 与独立中心差分不符。V0.1.7 注册 `CorrectReserve` 插件，继承原函数并修正四项导数；正常与分母下限分支、OpenMDAO 总导数均已核验，完整参考任务输出不变。恰在 `t_c=ε=1e-6 s` 处不可微，代码采用左侧导数 0，不作为梯度工作点。安装包源码未修改，退出上下文恢复模型注册。全模型梯度及优化尚未验证。
