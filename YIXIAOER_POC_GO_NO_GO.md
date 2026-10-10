# YIXIAOER_TECHNICAL_POC_PHASE0：Go / No-Go

日期：2026-10-05（Asia/Shanghai）。固定官方commit：`a2722c6095f57abf2e345dca637bdded44fa34df`，源码CLI标记3.2.26。

**YIXIAOER_PHASE0_NO_GO**

离线接口壳、HTTP文本样例与mock验证已完成。蚁小二具有可见程序调用控制面；目前不足以证明可以完整实现现有PublisherAdapter的无人值守、可追踪、可防重复的抖音生产闭环。

## 八项硬门

| Gate | 结果 | 已确认 | 尚需证据 |
|---|---|---|---|
| A 抖音账号授权机制明确 | **FAIL / PARTIAL** | 客户端账号管理添加抖音，内置浏览器扫码有官方教程；API Key和账号登录status分离 | OAuth还是Cookie、实际scope/授权主体、凭证维护方、过期恢复、是否底层GUI/RPA；扫码≠OAuth |
| B 上传API契约明确 | **PASS_SOURCE_CONTRACT** | GET签名query、serviceUrl/key、PUT bytes/Content-Type、UploadResult本地生成已核对实现 | 实际最大文件、签名有效期、存储完整错误码/限流UNKNOWN；未经运行验证，但足以生成标准链离线请求 |
| C scheduledTime明确 | **PASS_SOURCE_REPRESENTATION** | 13位Unix毫秒，逐账号form字段，显式UTC+8转换等价UTC；省略代表普通立即请求 | 服务端显示/执行时区、最小提前量、定时等待客户端要求和恢复UNKNOWN；不声称准点执行已验收 |
| D 任务终态明确 | **FAIL / PARTIAL** | stageStatus有pending/doing/success/fail/failed和taskStatus=deleted消费逻辑 | 完整状态枚举、审核态、success与抖音公开成功关系、失败终态定义/回调 |
| E 作品ID/URL回收方式明确 | **FAIL / PARTIAL** | 候选openUrl；任务ID与账号ID可识别 | 抖音作品ID字段、openUrl必返性/发布时间、task→作品→metrics稳定join；不能把task.id当作品ID |
| F 防重复方案成立 | **FAIL / PARTIAL** | 设计独立意图台账＋不确定即停，mock证明同进程重复调用不再POST | client幂等公开契约无；未知ID后的可靠对账/证明未受理缺失；持久化/并发/重启恢复尚未实现验证；不保证自动exactly-once |
| G 素材路线用户可接受 | **FAIL** | 标准链明确将MP4 PUT到供应商分配对象存储；local仅选择执行器 | 完整控制/留存/删除/后续链路MATERIAL_DATA_PATH_UNKNOWN；用户未接受第三方素材出网，现有本地约束仍有效 |
| H API/CLI使用权限来源明确 | **FAIL / PARTIAL** | [官方CLI入口](https://www.yixiaoer.cn/cli)给出获取API Key和客户端初始化；确有官方源码 | 直接调用网关HTTP是否受支持/许可、企业API使用条件、当前用户角色/套餐/scope、抖音发布合作权限和许可主体UNKNOWN；公开源码不赋予服务器权限 |

H的细分：CLI来源和蚁小二API Key取得路径有证据，未索取/配置key。学院有“CLI向用户开放”等声明，但不足以保证独立Python raw HTTP Adapter的支持范围与企业合同，更不证明抖音开放平台发布scope。没有发现可用于本项目的完整许可约定/抖音授权材料；本轮不做法律定性或以宣传代替权限确认。[官方CLI介绍](https://www.yixiaoer.cn/cli)、[API Key与发布流程说明](https://xueyuan.yixiaoer.cn/article/46560)、[客户端扫码教程](https://xueyuan.yixiaoer.cn/article/45606)。

即使B/C源码契约通过，其余任一硬门未过都不能进入真实POC；本轮多项未过，结论确定为NO_GO。不是要求用户现在绑定账号、购买套餐或给出真实素材。

## 关键未知与下一次所需材料

1. **授权与执行底层**：抖音授权页面/主体/scope、Token或Cookie归属、刷新与重新授权、Windows客户端在线要求、云/local执行器是否使用浏览器/RPA。内置浏览器扫码证据不能回答所有这些问题。
2. **平台成功闭环**：脱敏的真实task详情、全状态枚举、审核字段、明确抖音作品ID/URL及稳定关联；success是任务受理、上传完成、提交成功还是审核成功必须分别定义。
3. **超时与防重复**：厂商幂等支持或完整可对账taskSet记录；无ID超时不能凭空列表自动重试。我们设计的提交闩锁需要持久化/重启测试后才可生产使用。
4. **素材与权限**：标准对象存储上传已确认；需完整素材/凭证每跳及留存协议，并在路线明确后由用户接受。raw API接入许可、抖音发布权限来源也需厂商明确。

本轮未联系供应商、发邮件或代发任何消息。上述是证据缺口清单，不是已取得承诺。未继续研究其他平台，不恢复Xiaovcat UIA。

## 交付和验证记录

- [YIXIAOER_API_CONTRACT.md](YIXIAOER_API_CONTRACT.md)：逐接口method/path/auth/schema/error/pagination/rate limit；抖音字段与schema/preflight差异。
- [YIXIAOER_DATA_FLOW.md](YIXIAOER_DATA_FLOW.md)：本机→签名API→对象存储→cloud/local执行器→抖音图，授权Gate和MATERIAL_DATA_PATH_UNKNOWN。
- [YIXIAOER_ADAPTER_MAPPING.md](YIXIAOER_ADAPTER_MAPPING.md)：七态映射、接口壳、不能映射的NOT_SUPPORTED、四个provider字段及防重复设计。
- `publisher_poc/yixiaoer/`：独立adapter.py、合成fixtures、14项unittest、样例生成器、JSON与HTTP文本、固定官方源码ZIP/源码、证据页和provenance。
- 离线14项PASS；固定官方schema验证PASS；Python语法检查和保护文件核验记录在 `publisher_poc/yixiaoer/evidence/validation.json`，日志在同目录test_results.txt。mock未被写成实测。

所有变更为新增Phase0文件；保护基线覆盖8502相关Python/配置/发布实现/HANDOFF/检索入口，核验没有改变。未操作生产数据库/FAISS/模型/素材；未注册付费、购买、绑定正式账号、上传任何素材、提交真实发布、执行厂商CLI、运行UIA、改变服务进程或修改8502/PublishPlan/PublishJob/Worker/Render。生产功能未变化，因此没有改HANDOFF；本报告记录独立Phase0进度。

最终决策：**YIXIAOER_PHASE0_NO_GO**。离线壳完成不等于YIXIAOER_REAL_POC_READY。
