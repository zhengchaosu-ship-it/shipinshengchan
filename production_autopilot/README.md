# Production Autopilot Consolidation

增量收敛既有 `startup_autopilot`、`startup_pipeline`、`startup_render`、`yixiaoer_adapter`，不另建生成/渲染/发布实现。不改变搜索模型、索引、生产素材或历史排期。

## 用户使用

一级入口仍为索引模块、视频生成模块、AI托管模块；本机单工作室不需要登录。

新增蚁小二抖音账号后，Account Sync每5分钟把稳定Provider ID同步进本地列表。账号默认未配置、未托管、无背景，不根据昵称合并。用户设置模板、账号背景、每天1～5条、时段、目标粉丝后，明确点击最终确认按钮，才创建长期授权。

AI托管的账号卡显示今日已公开进度、下一条、累计发布、有效样本、真实粉丝与目标、学习状态和异常原因。进度观察每15秒只读本地数据库；普通页面不启动CLI。

认证问题：在蚁小二/抖音完成短信、扫码、登录或重新授权，点击异常中心的“我已完成验证，重新检查”。后台只读同步账号并对账任务；该检查周期禁止生成、Render和Publish。验证通过且不存在其它阻塞时恢复原授权；原认证失败任务保留且永不重发。作品缺失、无法确定提交结果、Render中断仍需核验；不能仅靠账号ONLINE清除这些异常。

恢复非认证异常时，修复原因后重新确认开始托管。已经错过安全提前量且可证明从未提交的本地分配标记为MISSED_NOT_SUBMITTED，保留原草稿、内容与任务。确认恢复后只规划新的未来时段。终态失败父任务可以关联未来正常额度中的新分配，记录独立补位谱系，不重置父任务闩锁、不修改其原发布参数。未确认提交结果的任务禁止补位自动重发。

达到目标粉丝只提醒；用户点击结束起号后不再产生新视频。平台已接受的定时任务保留，按既有结束对话框的选择处理未提交任务。

## 生产不变量

### 2026-10-07 正式闭环接入

生产媒体路径冻结为 `WORKER-2060S-01 → 本机成片验证 → 本机视频/封面上传 → Yixiaoer → Provider`。Server只承担控制、状态、公开对账、指标和学习；`server_provider_upload=DISABLED`，不改变已通过验收的2060发布实现。

`final_integration.sql`增量添加既有Job的观察记录、指标窗口和员工建议，不创建第二套PublishJob。自动备份小型业务库；`production_publications`保存稳定账号/作品/content/composition/template/全部slot，`production_metric_trace`可直接联查窗口及素材。Composition ID沿用原allocation_id，手工确认Job可按同content的生成批次和有序素材关联，不改旧allocation的排期或job_id。

现有生产Worker每60秒调度独立只读队列，即使账号长期托管关闭也继续处理已接受作品。只通过官方`yxer query content-overviews`取得作品证据；账号ID、作品ID、过去的实际公开时间匹配，且没有明确非公开标记，才同事务推进原ProviderJob/PublishJob/媒体执行记录至PUBLISHED，并保存published_at。与2060活动租约互斥，不能把定时成功当公开。原明确排除托管的账号不由此模块接管。

PUBLISHED事务创建2h/24h/72h持久窗口，时间以实际公开时间起算。每账号最多一个在途查询、失败也至少间隔5分钟；重启恢复。每个窗口需Provider的updatedAt达到窗口，缺失字段NULL；迟到数据LATE_CAPTURE、不参与学习，旧精确窗口不被迟到数据覆盖。持续7天仍缺失的窗口记录UNAVAILABLE，保留证据，不造0。

只有VERIFIED组合、PUBLISHED作品及有效EXACT指标可参与学习。AccountMaterialAffinity沿用`startup_autopilot.affinity.build_affinities`，SlotAttributionEngine沿用`slot_affinity.build_slot_affinities`；生产Planner调用`BanditSelector`，保留原epsilon探索、低样本门槛、Slot独立身份和疲劳限制。2h供观察，24h/72h供学习，同一作品不重复计样本。

MaterialDemandEngine每30分钟读取已确认模板、有限目录元数据与既有SHA缓存、近期使用、未来计划和账号Slot偏好，更新`视频生成模块 → 素材任务`。显示今日建议数量、slot/模块、推荐原因；产品仅取素材库明确关联，未绑定保存NULL并显示“起号通用”。固定片段不消耗轮换疲劳额度。建议不是生产授权，入库继续走既有生产素材库及消费者缓存更新。

8502首页区分生成、待渲染、成片READY、待发布、平台定时队列、已公开与账号异常。所有账号仍须用户点击“确认并开始托管”后才可长期生产，账号每日最多5条、Replacement lineage、单执行槽和Exactly Once闩锁保持原实现。

本轮目标作品`7693858927401848099`登记为北京时间2026-10-08 09:08之后首次只读公开对账；这是未来待办，不代表已经公开或已经采到未来窗口数据。部署证据与回滚范围见`runtime/final_integration_20261007/REPORT.md`。

- 身份与所有资产按business_account_id/provider_account_id隔离；昵称和备注仅展示。
- 所有新计划的北京时间每日额度统一最多5；FAILED和不确定提交保守占用当日额度，历史超额排期不变。
- Render沿用稳定Content ID、唯一队列、Worker归属/租约、幂等回执。GUI中断停在明确核验状态，不自动重复导出。
- Publish沿用持久submit_attempt_count=1闩锁和请求hash；重启先只读对账。平台TASK ID、Provider账号ID、标题与时间均需一致。历史details返回账号ID为NULL时，必须用原payload、原dry-run完整请求hash、原intent和TaskSet ID证明稳定身份；非NULL错ID直接拒绝，绝不使用昵称兜底。
- 组合30天去重由既有Planner负责；增量迁移仅移除永久组合唯一约束，保留账号/时段和Content/Plan/Job唯一身份，原行逐字段不变。
- 每周期每账号最多生成1条，账号轮转；共享Render队列。Metrics独立有限线程查询，每账号最多1个在途采集，采集Adapter只允许content-overviews。
- 真实公开证据来自官方作品列表；Provider排期成功不当作已公开。
- 有效学习门槛要求公开作品、真实24h/72h指标、可确认本账号Composition/Material ID；缺指标或不明关联只能作为baseline。缺失指标NULL。
- 窗口2h/24h/72h；旧数据不占用有效窗口，NULL/未知快照允许后续补齐。迟到采集标记LATE_CAPTURE，不能冒充原窗口精确数据。默认窗口容差30/120/240分钟，可配置。
- AccountVisualProfile独立于TemplateVersion；已实现背景共用，字幕/字体/Logo/贴纸/主体位置/缩放/抠像字段预留NULL，继续沿用现有生成器参数，不宣称新样式编辑已实现。

## 后台健康与备份

现有生产Worker每60秒循环；健康每5分钟采集8502、托管Worker、Publisher、Render、Yixiaoer Client、Account Sync、数据库、磁盘、素材、输出目录。所有CLI继续run_hidden / shell=False / CREATE_NO_WINDOW / SW_HIDE。数据库失效时独立健康JSON仍保留。

每6小时本地备份三个小型业务库：operations.db、shadow账号资产库、render_jobs.db。**不备份/修改32GB搜索数据库或FAISS**。备份含账号映射、Profile、模板版本、视觉绑定、Affinity、Metrics、Composition、预算、授权与Publish审计；另复制相关小型JSON证据。通过SQLite只读快照导出，逐库integrity_check与SHA256验证；活跃授权与账号资产hash必须一致。不启动Render或Publish。

默认目录：`startup_autopilot/runtime/production_worker/consolidation/backups/`。

可配置参数沿用production_worker.config.json：

| 配置 | 默认值 |
|---|---|
| poll_seconds | 60 |
| max_generations_per_account_cycle | 1 |
| async_metrics | true（正式main默认） |
| metrics_parallel_accounts | 2，上限4 |
| metrics_max_pages | 20；目标作品找到即提前停止 |
| backup_interval_seconds | 21600 |
| minimum_free_bytes | 5GiB |
| consolidation_runtime | production_worker/consolidation |

备份保留以便审计，不自动物理删除；磁盘低空间进入异常中心。CLI凭证、客户端重新登录、素材/导出目录及Windows任务配置在机器迁移时单独核验，备份不代替平台授权。

## 恢复 / 机器迁移

1. 停止业务Worker和页面写入，保留损坏库及当前Runtime，不要删除生产数据或重置任何提交闩锁。
2. 从最新已验证备份恢复到**新的隔离目录**：

   `.venv-cuda-test\Scripts\python.exe -X utf8 -m production_autopilot.restore --backup <备份绝对目录> --destination <尚不存在的恢复目录>`

3. 工具验证清单hash、数据库完整性、外键、唯一Provider映射、授权和submit_attempt_count；输出restore.report.json，不启动Worker，不触发外部操作。损坏/缺失备份拒绝恢复；已有目标目录拒绝覆盖。
4. 对照报告确认原business/provider ID、授权hash、模板/背景、历史Task IDs和submit_attempt_count保持原值。operations.db替换业务库、account_assets.db替换配置的shadow库、render_jobs.db替换既有Render队列；保留备份文件本身。
5. 新机器恢复素材路径、Render输出目录和既有配置；核对背景hash，素材目录迁移后需要重新选择同一背景资产以更新路径。配置路径必须对应新机器，不更换稳定账号ID。CLI凭证和客户端验证在本机完成，不上传素材。
6. 页面/后台先只读检查账号并对账已提交任务；SCHEDULED_QUEUED继续沿用平台排期，不重发。GENERATING、失联Render租约、SUBMIT_INTENT/UNCERTAIN保留并进入人工核验。错过时段的旧任务不得滚动改期重发。
7. 恢复后的业务库和Render库自动设置同一恢复保护标识，生成、渲染领取和Publish提交全部冻结。旧备份可能缺少备份之后发生的提交，不能仅凭旧submit_attempt_count=0判断从未发布。核对平台历史、原任务和输出后，在“高级管理 → 备份恢复核对”明确确认。工具保留原授权与历史身份，将旧未提交任务留在人工处理状态，不重试；保护解除后才启动现有计划任务。账号或健康检查失败仍停在异常中心。

## 增加Render Worker

目前保持单Render并行度1。未来在既有LAN配置登记独立worker_id、独立桌面节点和本地目录，并配置max_parallel_jobs=2（或更大）及托管允许Worker列表即可；上层仍使用原RenderQueue。并发领取以事务和lease隔离，原Worker可重复领取自己的同一token，其它Worker不能接管未知在途导出。租约过期需要对账，不自动重Render。

50账号fixture验证的是250条持久规划额度和账号隔离，以及原队列多Worker领取行为；不是250条真实视频的吞吐验收。实际产能仍受素材供给、GUI会话和渲染硬件约束。
