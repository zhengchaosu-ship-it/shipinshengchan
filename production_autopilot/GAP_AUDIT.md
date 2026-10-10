# PRODUCTION_AUTOPILOT_GAP_AUDIT

审计时间：2026-10-06。此表记录实施前状态；代码存在不等于长期运行验收通过。

实施后的逐项DONE/PARTIAL/RISK、真实服务状态、回归与备份恢复证据见[ACCEPTANCE.md](ACCEPTANCE.md)。初始缺口已按P0 → P1 → P2收敛；Render工作站离线、真实连续运行及20条有效样本验收仍待完成。

| 优先级 | 能力 | 状态 | 代码证据 / 缺口 |
|---|---|---|---|
| P0 | Account Sync、稳定账号主键 | DONE | account_registry / account_sync_worker；只读同步、本地快照、缺失TTL、无昵称合并 |
| P0 | 用户首次明确确认、多账号授权 | DONE | ProductionStore.start / verify；独立授权hash、账号权限、暂停/结束检查 |
| P0 | 每日预算、StartupDailyPlanner | PARTIAL | reserve_daily持久分配、额度去重、最多5；人工计划入口需要统一额度，已有超额历史必须保留 |
| P0 | Render exactly-once | PARTIAL | RenderQueue唯一业务身份、LAN lease、回执幂等；外部GUI无法承诺数学上的恰好一次，中断停机核验而非盲重渲染 |
| P0 | Publish exactly-once | DONE | submit_attempt_count持久闩锁、intent/hash、重启只读对账；不确定结果禁止重发 |
| P0 | Failed / Uncertain reconciliation | PARTIAL | Adapter已有只读对账；失败和账号注意状态缺乏统一分类、节流和恢复流程 |
| P0 | Replacement Job lineage | MISSING | 未发现稳定父子链；不能靠重置旧任务实现补位 |
| P0 | Service restart recovery | PARTIAL | 已有单实例、持久状态、GENERATING中断保护；缺统一恢复清单和多账号公平调度 |
| P0 | Provider Auth Recovery | MISSING | 尚无“我已完成验证，重新检查”后台请求；不能以恢复账号为由重发失败任务 |
| P0 | AttentionRequired异常中心 | PARTIAL | 已有账号级停机、原始原因；缺行动提示、去重、恢复审计和统一入口 |
| P0 | 独立账号资产 | PARTIAL | Profile/Template/Background/History/Metrics/Affinity/预算/状态均按ID；VisualProfile未形成统一契约 |
| P0 | 固定3模块、SINGLE_STUDIO | DONE | studio_navigation / single_studio；工程功能位于高级管理 |
| P1 | 2h/24h/72h真实Metrics | PARTIAL | production_metrics已取官方作品证据、缺值NULL；缺失/旧数据可能永久占用窗口，轮询故障影响整账号循环 |
| P1 | 20条有效样本再学习 | RISK | builder.context目前计数公开作品，未同时验证指标与素材关联；必须统一生产有效样本口径 |
| P1 | Affinity与人工覆盖 | DONE | affinity / slot_affinity / composition_planner：归一化、收缩、exploit/explore、疲劳、LOCK/PREFERRED/BLOCK |
| P1 | 账号视觉身份 | PARTIAL | account_visuals背景已共用；字幕/字体/Logo等需独立保留契约，不改变已确认模板 |
| P1 | 运行驾驶舱 | PARTIAL | 已有账号卡、时间轴、学习页；今日计数是分配数，缺累计发布、真实粉丝/目标与统一异常处理 |
| P1 | 后台健康 | PARTIAL | 各Worker已有heartbeat、Render health；缺持久汇总、磁盘/路径/数据库诊断 |
| P1 | 自动备份/恢复演练 | MISSING | 现有备份主要是迁移时备份；未见周期快照、跨库恢复验证和恢复手册 |
| P2 | 10/20/50账号 | PARTIAL | 账号隔离和共享渲染队列已具备；长串行Provider查询和生成可能阻塞其它账号，需限额/公平轮转与fixture压力验证 |

## 当前运行证据（只读）

- Registry：7个抖音账号均为ONLINE；6个账号已有背景绑定。
- 6个托管授权均为ATTENTION_REQUIRED；5个发布失败，1个DOUYIN_SCHEDULE_TOO_SOON。
- 分配：FAILED 7、RENDER_PENDING 15、SCHEDULED_QUEUED 2、SUBMITTED 4；真实Metrics 0。
- Provider任务：FAILED 16、SCHEDULED_QUEUED 21、SUBMITTED 7；累计提交闩锁44。以上是已有业务，不能视作本次新增提交。
- Worker heartbeat持续更新，但无活跃授权；服务在线不等于业务健康。

## RISK

1. 素材量/疲劳规则不足时无法无限供给每天5条；停止并明确提示，不能自动放宽已确认模板。
2. 真实平台失败、验证和GUI会话需要人工；代码补齐不能宣称已经完成连续多日无人值守验收。
3. 旧FAILED禁止重试；已进入平台的SCHEDULED_QUEUED只能只读对账，不改排期/重复提交。
4. 当前沙箱读取Windows计划任务受限，需通过授权的系统只读检查核验部署；不影响源码和fixture工作。
5. 当前粉丝若Provider没有返回必须显示未知；达到目标只提醒，不能自动结束。

## 实施顺序

P0：统一异常/恢复请求 → 每日预算入口 → 安全补位谱系 → 重启与公平调度。

P1：有效样本门槛与可恢复窗口采集 → 账号VisualProfile契约 → 驾驶舱 → 健康/周期备份/恢复演练。

P2：50账号fixture，验证隔离、每天5条、共享队列与公平调度。最后报告实际通过项与仍需人工/持续运行验证项。
