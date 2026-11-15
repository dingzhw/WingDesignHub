# 验证方法与适用边界

最新结果见 [V0.1.4 梁/壳、质量卸载与屈曲筛查报告](VALIDATION_V0.1.4.md)及 `validation/v0.1.4.json`。前序记录见 [V0.1.3](VALIDATION_V0.1.3.md)、[V0.1.2](VALIDATION_V0.1.2.md)和 [V0.1.1](VALIDATION_V0.1.1.md)。历史失败摘要保持原状，便于前后比较。

## V0.1.0 验证对象

1. 等截面悬臂梁：均布载荷解析式 `w(y)=q*y²*(6L²−4Ly+y²)/(24EI)`；端点集中力 `PL³/(3EI)`；端点力偶 `ML²/(2EI)`。检查全场位移和根部反力，避免只测试同一函数的中间输出。
2. 六分量载荷映射：独立计算映射前后的合力和任意参考点合力矩，包含偏心载荷、正负载荷和集中力偶；超出结构展向范围拒绝计算。
3. 实际 AVL：孤立矩形 NACA0012 机翼，小迎角、低速；检查参考量与半翼条带升力积分，不提供失速、黏性或全机阻力。
4. OpenVSP：单独进程生成机翼，读回面积和翼展与配置核对。几何和 AVL 均由统一配置生成；当前不是任意 .vsp3 模型自动转换器。
5. 用户流程：Streamlit AppTest 执行默认方案、点击运行、检查结果显示和文档页。

梁仅适用于线弹性、小变形、细长等效梁；挠度超过半展长 10% 拒绝作为成功结果。材料模量和截面惯性矩是合成输入，未计算材料许用值、局部屈曲或真实翼盒强度。载荷映射工具支持六分量，而当前气动演示只传递竖向升力。

## 公开依据与下一步独立验证

- [TU Delft Euler–Bernoulli 梁有限元教材](https://interactivetextbooks.citg.tudelft.nl/computational-modelling/structural_linear/euler_bernouilli.html)：Hermite 梁单元、刚度和载荷方法；配合上述经典边值问题解析解。
- [AVL 官方文档](https://web.mit.edu/drela/Public/web/avl/)：条带输出、参考量、适用范围。下一阶段用网格加密和公开机翼案例评估。
- [OpenVSP 3.56 API](https://openvsp.org/pyapi_docs/3.56.0/)：几何及 FEA 接口。
- [FAST-GA 官方案例和模型](https://github.com/supaero-aircraft-design/FAST-GA)：首先复现同版本随包案例，保留输入与基准差异；后接全机模型。
- [OpenAeroStruct 结构独立算例](https://mdolab-openaerostruct.readthedocs-hosted.com/en/latest/struct_example.html)：结构组和外载荷验证。
- [CalculiX 官方案例](https://www.dhondt.de/)：静力/模态/屈曲基准；代表翼盒按分层验证接入。
- [CCBlade 官方教程](https://flow.byu.edu/CCBlade.jl/stable/tutorial/)：公开螺旋桨性能数据和前进比范围。

## 证据分级

V0.1.3 接入代表半翼 S6 静力和 OAS 官方翼盒。详细载荷、边界、数值字段修复、网格敏感性、失败证据和使用范围见 [本轮验证报告](VALIDATION_V0.1.3.md)。静力计算通过与屈服限值筛查、局部屈曲及实际飞机强度验收分别记录。

数值一致性、上游案例复现、独立试验数据验证分别报告。首次运行结果保存在本地 runs，公开验证摘要放 validation。当前不声称已获整机物理验证或适航认可。单位测试通过不代替专业评审。
