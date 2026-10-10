# PRODUCTION_AUTOPILOT_GO_LIVE_RECOVERY

2026-10-07 00:41最终更新：用户已追加夏禾单任务授权，`STARTUP-94affa8d-6268-4e22-adaf-58f81f8d4929` 一次导出、全片校验及一次LAN回传完成。旧RenderJob COMPLETED，业务成片READY且NOT_SCHEDULED；Worker IDLE / RenderCapability READY。该追加轮Provider Upload、PublishJob新增、真实发布、新RenderJob及新Content全部0。按要求完成后停止，未推进Publisher；账号的独立平台验证异常不影响Render READY，也没有在本轮代为解除。最新验收 `../startup_render/runtime/export_recovery_xiahe_20261007/DELIVERY_VERIFICATION.json`。下面00:29与10月6日段落为历史记录。

2026-10-07 00:29更新：原忍冬RenderJob已按单次恢复及单文件回传授权完成，COMPLETED / READY，媒体完整校验通过。00:11曾达到6账号Preflight READY且全部停用。其后用户在8502自行开启4账号并明确要求保留现状，后台增加了12个ProviderJob和5次提交；因此下面10月6日的“无Render/上传/Publish”仅是此前历史记录。

当前新阻塞为后台领取的旧排队任务“夏禾起号10月6日-3”：帧率选择后的Qt鼠标提示被误判未知弹窗，最终导出前HALT。精确tooltip判定已修复、部署并通过实际证据回放，但该任务没有重试；当前无MP4、无最终导出闩锁，仍需用户单独授权该任务一次恢复。当前不返回全系统GO_LIVE_READY。用户开启后的平台验证异常仍由现有异常中心处理，不在本轮Render恢复中代为验证或发布。

最新证据：`../startup_render/runtime/export_recovery_20261006/delivery_check.json`；原任务对账：`reconciliation_result.json`；00:11历史Preflight：`production_acceptance.json`；119项回归和19项最后定向测试通过。详细交接见 `../HANDOFF.md` 顶部。

2026-10-06，验收仍被正式Worker的人工处理状态阻塞。没有开启任何账号，没有 Render、上传或 Publish。

## 已完成的本地恢复

- 七个 Provider 抖音账号重新通过正式只读 CLI 核验；八个业务账号中一个历史账号未绑定，不按昵称合并。丙曜的稳定映射保持原值。
- 完整核验 44 个已提交任务和七个账号的 75 条官方作品记录。原始查询证据及逐任务结果保存在 `runtime/go_live_recovery/reconciliation.json` 和账号作品分页文件。
- 两条已有任务由官方公开作品证据修正本地为 PUBLISHED；三条旧排期由官方任务终态确认本地为 FAILED，原提交和排期参数不变。另有三个丙曜历史 FAILED 的任务详情与公开作品列表矛盾，保持原 FAILED，不重试、不计入有效归因学习。
- Provider作品列表包含缓存：33个已确认任务的作品ID尚不在本轮缓存列表中，不能据此断言作品已删除；70条Provider作品无法确认对应本系统Content/Material IDs，仅用于账号baseline。逐条标记及缓存updated_at已保留，禁止猜测映射或伪造真实Metrics。
- 六个原账号的历史发布/过期排期异常已核对，恢复为 PAUSED，enabled 始终为 0。原确认时间、config_json/hash、模板、背景、稳定映射、历史任务参数保持原值。旧终态 FAILED 不再周期性把关闭账号重新变成异常；当前真实失败和不确定提交仍停止生产。
- 启动弹窗在显示确认按钮前及提交确认时分别执行真实 Preflight：在线唯一绑定、已确认模板、1～5条、发布时间、粉丝目标、有效背景、已校验素材容量、账号阻塞事件、备份恢复保护、Render、Publisher。
- 已校验素材的保守容量足够即可开始，不要求扫描/校验整个大素材库。没有放宽疲劳、去重、每日额度或学习证据标准。
- 账号卡从本地持久记录显示每日计划、生成、渲染、排期、发布、失败和待处理进度；渲染库不可读时显示未知，不伪造零值。
- 现有正式 Render Server、Autopilot、Publisher 计划任务已重新加载修复；Account Sync 继续按原正式任务运行。Planner、Metrics、Backup、Health 继续复用正式 Autopilot 服务，不创建临时替代守护进程。

## 2060S 真实诊断

主机 DESKTOP-9VQ76D3，worker_id WORKER-2060S-01。最初不是无心跳，而是 HALTED_NEEDS_MANUAL。忍冬既有任务 `STARTUP-8fa633ab-a8e3-4653-96dd-02b61aac2e14` 在 EXPORTING 失败：未在编辑窗口中找到导出按钮。原服务器任务仍为 NEEDS_MANUAL，未恢复旧任务。

用户运行共享维护脚本后确认正式任务 XUNZHEN_RENDER_WORKER 已启用、运行，固定剪映 5.9.0.11632 的路径、签名、SHA256 均正确，Worker→StartupAssets/RenderOutput 两个共享可访问。重启后曾短暂没有新心跳，随后15:00和15:01 UTC收到同一Worker连续心跳，但状态仍为 HALTED_NEEDS_MANUAL、current_job_id=null。不能把有心跳当作IDLE。

共享脚本已补充等待旧任务退出、精确停止该配置的残留常驻进程、正式任务退出码、任务用户/登录类型、进程 Session ID、失败本地state和日志诊断。用户后两次回复为“输出”和命令本身，并没有新版JSON结果；共享 `outputs/lan_render/GO_LIVE_RECOVERY/WORKER_CHECK.json` 仍是22:53的初次报告。脚本采用 UTF-8 BOM，并通过 Windows PowerShell 语法解析。

维护期间 CLAIM_CONTROL.enabled=false，暂停新的领取；原配置已保存在 `runtime/go_live_recovery/CLAIM_CONTROL.before.json`。两条原 QUEUED 都归属未开启账号，新加载的账号级领取保护拒绝领取它们。恢复核验后沿用原正式开关，不改已有排期或失败任务。

Worker 的旧失败本地 state 会被原 Agent 保留并阻止下一次领取，单纯重新启动并不代表已清除这一真实阻塞。不得通过删除失败历史、篡改完成回执、重置任务或重新渲染来冒充恢复。

## 当前验收

六个账号（引流+手法+手法+收尾、夏禾、春福轩、忍冬、晚枫、夏竹花开）均 enabled=false、PAUSED。各自模板已确认，背景维持用户原选择，每日5条、原发布时间、目标3000粉丝均保留；完整稳定ID、VisualProfile、背景、Preflight详情在 `runtime/go_live_recovery/accounts.json`。

目前 READY_TO_START=0，NEEDS_USER_CONFIGURATION=0，六个均 INFRA_BLOCKED。配置和已校验素材容量已通过，当前 Render 未就绪。不能输出 PRODUCTION_AUTOPILOT_GO_LIVE_READY。

保护验证文件 `runtime/go_live_recovery/protected.json`：44 个提交闩锁不变；58 个 RenderJob 身份数量不变；六套授权确认配置、模板、背景、原 PublishPlan/Items 不变。本轮真实新增 Render=0、Upload=0、Publish=0。

恢复后的当前三库备份已通过SHA256、SQLite完整性和清单检查：`startup_autopilot/runtime/production_worker/consolidation/backups/20261006T150521115383Z`。未替换生产数据库；前轮隔离恢复/HOLD保护验收仍保留。

58 项初始回归、81 项生产边界回归以及 7 项启动检查测试通过（存在重叠，不相加冒称独立数量）。7 项包含启动弹窗未就绪时确认按钮禁用、只读 Adapter 拒绝写操作、关闭账号不领取 Render 和不被旧 FAILED 反复停止。

真实8502账号卡已查看。自动审批拒绝点击真实账号“恢复托管”，因为可能开启生产且用户禁止本轮开启；没有执行点击。弹窗保护使用隔离账号测试，不宣称已点击真实启动确认。

## 十四项验收结论

| 项目 | 当前结论 |
|---|---|
| 1 Render是否ONLINE/IDLE | 否，HALTED_NEEDS_MANUAL |
| 2 heartbeat | 重启后恢复，稳定Worker ID，当前没有在途任务 |
| 3 作品对账 | 44已提交任务核验、75缓存作品；2条公开状态和3条失败状态由真实证据修正；3条矛盾保留 |
| 4 重复/错误映射 | 未发现重复Provider作品ID或账号/content串号；不能确认的70条Provider作品不强行关联 |
| 5 同步账号总数 | 7个抖音Provider映射；本地8个业务账号，1个历史未绑定 |
| 6 六账号分类 | 引流+手法+手法+收尾、夏禾、春福轩、忍冬、晚枫、夏竹花开全部PAUSED、enabled=false、INFRA_BLOCKED |
| 7 READY_TO_START | 0 |
| 8 NEEDS_USER_CONFIGURATION | 0；六个账号的现有设置及已校验素材容量均通过 |
| 9 真正异常 | 1个共享Render基础设施阻塞；另1个历史未绑定账号、3条历史矛盾记录待核对 |
| 10 页面可以配置并开始 | 可配置；正式开始被Render就绪检查阻止，不能宣称可投入生产 |
| 11 Preflight | 真实账号只读检查和隔离弹窗禁用测试通过；未点击真实确认 |
| 12 技术问题 | 旧导出失败保留在Worker本地state，原Agent会保持停止；需要人工核验，不能删除或重试历史 |
| 13 常驻服务 | Server/AccountSync/Publisher/Autopilot使用原正式计划任务；Planner/Metrics/Backup/Health由正式Autopilot承担。Render任务存在且有心跳，但未就绪 |
| 14 新增真实数量 | Render=0，Upload=0，Publish=0；所有六个账号继续关闭 |

本轮禁止为健康检查生成视频，因此不能把版本/心跳核验当作新的实际导出成功或多日无人值守吞吐验收。
