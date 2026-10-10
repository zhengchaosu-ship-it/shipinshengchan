# XUNZHEN_SERVER_AUTONOMOUS_MAINTENANCE_V2

本聊天角色为 SERVER_ENGINEER。生产不依赖 Codex 保持运行。所有时间戳以 UTC 持久化，本地查看使用 Asia/Shanghai。AUTO_FIX_PERMISSION_LEVEL = HIGH，只在已经授权且证据充分的范围自主处置。

## 已安装的两层守护

- Codex 当前聊天心跳 `SERVER_MAINTENANCE_CHECK`，每30分钟完整巡检；无变化保持安静。应用离线/额度不足不暂停生产。
- Windows `XUNZHEN_SERVER_LOCAL_GUARD_V2`，SYSTEM、每分钟运行；负责Server单实例检测、有限恢复、Backup Guard、Storage水位、坏记录隔离。采集器失败1分钟重试，最多3次。
- Windows `XUNZHEN_SERVER_MAINTENANCE_SNAPSHOT_V2`，SYSTEM、每30分钟完整目录元数据/健康快照；Codex缺席仍留报告。
- 原正式 Planner/API Task 保留名称、用户及原触发器。入口增加 `server_maintenance.service` 保存traceback与有界日志；RestartCount=3、RestartInterval=1分钟、IgnoreNew、StartWhenAvailable、无限正常运行时间。
- 单实例按venv启动器父子进程链去重，另有服务入口锁、原Planner文件锁/API端口绑定；不会把4个Python父子PID解释成4个业务实例。
- 新入口使用Windows Job的KILL_ON_JOB_CLOSE；实际解释器在业务模块加载前加入Job，入口被Task Scheduler结束时收口其Server子树。旧入口遗留API进程已凭child.json/PID创建时间/父进程消失核验后收口，API正式任务已加载新入口。新PID、Task Running及协调GET成功共同决定Self Check，旧端口响应不能冒充重启成功。
- 维护快照采用独立临时文件和最多6次原子替换，Windows短暂共享占用最多等待1.5秒；持续失败保留错误，不改ACL或安全策略。

## CROSS_NODE_COORDINATION_POLICY

双方必须知道另一角色存在。Server维护角色负责Control Plane、Planner、API、DB、Storage、Backup、Account、Queue、Reconciliation；EXECUTOR_2060_ENGINEER负责Worker、Session、Jianying、Export、Verify、Yixiaoer、Heavy Slot、Journal、Server REJOIN。各自只修改自己的节点和组件。

先归因 LOCAL / PEER / CROSS_NODE。每个incident明确incident_owner。Server不得释放2060 Heavy Slot、清理其Journal、重启其Worker或修改其生产代码；观察到这些故障时发 `EXECUTOR_ACTION_REQUIRED`。执行节点自身健康而Server失联时，应 `WAITING_FOR_SERVER_RECOVERY`，Server恢复后正常REJOIN；宽限180秒后才请求执行节点调查本地故障。非Owner保留现场并安全contain，不同时修同一根因，不直接改对方DB传话。

共享状态在 `runtime/maintenance_watchdog/coordination/policy.json` 与 `server_state.json`。认证只读GET接口：原LAN API的 `/maintenance/coordination`，沿用原token与客户端白名单。每条请求携带timestamp、incident_id、incident_owner、reason_code、evidence、local_state、requested_action、urgency。Owner修复并验证后发 `PEER_RECOVERY_AVAILABLE`。两端机器READY/DEGRADED才允许完整生产；工程师聊天绑定/收到确认单独记录，不把观察到Worker心跳冒充聊天已确认。

当前正式执行节点WORKER-2060S-01；SERVER_ENGINEER为当前服务器电脑Codex（本地聊天 `自动检测维护`），EXECUTOR_2060_ENGINEER为2060电脑正在负责AUTOPILOT_UNATTENDED_LEVEL1的Codex聊天。用户明确选择暂不发聊天通知，绝不能把 `发布计划交接流程` 绑定成执行节点工程师。正式绑定等待用户在2060聊天加入同一策略；角色存在已经登记，不冒充对方已收到/确认。Account Sync事件归SERVER_ENGINEER。

## 正常操作命令

在项目根目录执行（无需安装依赖）：

```powershell
& .\.venv-cuda-test\Scripts\python.exe -X utf8 -B -m server_maintenance.watchdog --repair --codex
& .\.venv-cuda-test\Scripts\python.exe -X utf8 -B -m server_maintenance.rollback
```

每分钟本地任务只写 `minute.json`，完整采集才更新latest与history。`repairs.jsonl`永久保存自主修改审计，包含timestamp、actor、reason、evidence、before、action、after、result、rollback_available；INTENT先于动作。服务日志/API日志最多6×10MiB，采集日志最多4×5MiB。

SYSTEM无法解密用户DPAPI凭据，因此本地任务用403认证门响应判断HTTP存活，并同时核验进程及只读DB的Worker心跳；不改token、ACL或Windows安全策略。Codex正常用户上下文使用认证 `/health`。状态报告标明authenticated=false，HTTP存活不冒充认证的业务健康。

## Server自主恢复白名单

1. Planner/API instance_count=0、正式任务未Disabled、DB可读且Schema齐全、预检通过后启动原Task；启动前重复核验。Windows重试用1分钟×3；超出后本地监督至多每天3次补充恢复、至少间隔1小时。START_REQUESTED必须后续采样验证，不能直接写ONLINE。
2. 失败服务保留原heartbeat/Task返回码/源码与Task XML基线。新服务入口持续保存stderr/traceback与退出码。历史旧退出若无日志，只能UNKNOWN，不能把磁盘事故推断为CONFIRMED。
3. Backup连续失败且30分钟内至少3批完整副本目录，暂停独立Backup Scheduler；不暂停Planner/API或正在执行的任务。
4. 已暂停备份只能在明确属于Storage保护、NORMAL水位、最近备份COMPLETE、SHA/Integrity/Profile验证及当前空间检查通过后解除；同一失败持续时只VERIFY_EXISTING_ONLY。禁止force绕过空间保护。
5. 坏JSON保存证据到quarantine并继续扫描，生产者原文件保留。坏Job只有WAITING/WAITING_FOR_RENDER/READY_TO_PUBLISH、submit_attempt_count=0、intent=NULL、无重槽租约，才在再次事务校验后隔离为FAILED_JOB_LEVEL；不重建、不重新Submit。
6. 账号风险由已存在的正式Account Runtime/Control Plane逻辑局部暂停，用户授权保留；巡检不执行Manual Ack/恢复托管按钮，不修改日额度和时间表。
7. 低风险局部Hotfix必须根因明确、隔离回归通过、源码备份、无业务规则变化、无需Migration、有一键rollback及Self Check。当前周期任务不自动升级代码；如需Hotfix，单独记录证据、变更和回滚，不能把HIGH权限当无条件部署。

## Disk Guard与清理

>=100GiB NORMAL；50–100 WARNING；20–50 DEGRADED_STORAGE；<20 STORAGE_CRITICAL。Backup创建前统计DB及JSON证据source_size；required=source_size+expected_temp_space+20GiB，其中expected_temp_space保守取source_size。空间不足或DEGRADED/CRITICAL拒绝复制，不先创建大副本目录。

CRITICAL时Planner停止新生成/派发，Server API拒绝新Heavy Slot领取；既有租约、API、8502、heartbeat、轻量对账继续。该门直接读shutil.disk_usage，不读取Codex状态或巡检报告。测试Snapshot、Migration rehearsal、大临时副本在DEGRADED/CRITICAL禁止启动，维护操作必须调用 `require_copy_space`，定期任务本身永远不启动这些工作。

`approved_cleanup.json`只登记明确SAFE_TEMP/CACHE的单文件，须有approved、TTL、size、SHA256；过期且未变更才删除；拒绝越界、junction/symlink、正式DB/索引/素材、未发布成片、1GiB以上文件。默认清单为空，未证明用途的文件不自动登记。已停止下载的incomplete、失败备份或重复rehearsal副本等V2权限仍需保存审计和有效替代/恢复基线证据后明确登记专门方案；不能仅凭扩展名删除。

已完成旧DINO实验清理和formal_v1归档由独立磁盘事故报告 `disk_recovery/20261009_v1/REPORT.md` 提供证据，本轮不重复处理，也不把其它聊天的删除计为本轮自主动作。

目录大小仅扫描元数据，不读素材内容。30分钟增量必须有20–45分钟内的完整基线；首轮/部分扫描/中断显示UNKNOWN，绝不伪造0。按实际间隔折算30分钟，>5GiB警告，>15GiB严重，并报告增长最大的目录。

## 回滚

```powershell
& .\.venv-cuda-test\Scripts\python.exe -X utf8 -B -m server_maintenance.rollback --apply
```

只在重槽空闲、2060在线且确认执行器quiescent时停止本次Server任务，恢复4个源码局部撤销副本及原Task XML，再恢复原正式任务。从不覆盖业务数据库、Submit闩锁或历史任务。正在Export/未知副作用时保留现场、请求Owner，禁止强行回滚。更改运行文件若由另一个工程师后续修复，必须先核对哈希，不用旧备份覆盖其新修复。回滚期间暂停两项本地守护任务，恢复完成后重新启用；失败停在现场，禁止自动无限重试。

回滚源码为重新基于当前文件生成并通过隔离测试的局部撤销副本，保留其它Server恢复修复及只读Schema预检。旧Planner入口仍运行既有修复版本，新Job入口在下一次正式启动生效；回滚如遇旧入口遗留子进程，必须同时核验child.json、PID创建时间、父入口消失及2060空闲，才能收口已知Server子树。任何证据不完整则拒绝。API热加载自检失败会保存SERVER_ACTION_REQUIRED，回滚入口仅在上述安全条件满足时执行，未实际执行回滚不报成功。

## 永久禁止

DESTRUCTIVE_UNKNOWN_DATA_DELETE = FORBIDDEN；REAL_TEST_PUBLISH = FORBIDDEN；MANUAL_ACCOUNT_ACK = FORBIDDEN；WINDOWS_REBOOT = FORBIDDEN。还禁止删除生产DB/正式DINO repaired/CLIP/Speech/未发布成片/用途未知video_index.db，重复Export/Submit、历史补发、变更用户托管意图/额度/时刻表、Schema Migration、大库VACUUM、未知GUI强杀及Windows安全策略降低。

## 验证

隔离测试：`python -X utf8 -m unittest server_maintenance.test_watchdog media_execution.tests.test_production_bridge production_autopilot.test_backup_safety startup_autopilot.tests.test_production -v`，全部Provider/Executor为fixture。Windows沙箱临时目录ACL报错时按真实本机权限重跑；失败日志保留。

手动核验：查看两个本地任务LastTaskResult=0、1分钟/30分钟下一运行时间；Planner heartbeat持续且单实例；认证API/8502 HTTP200；2060自然ONLINE/READY、重槽IDLE；授权哈希/受保护索引stat不变；Submit次数不增加。只用mock验证低磁盘，绝不真实填满D盘或杀生产服务测试恢复。8501已在运行，不另外启动重复服务。本次没有改搜索模型/预处理/索引/字幕Schema。

## 2026-10-09 监控时间戳竞态修复
Planner心跳计龄改用读取完成后的时间，避免host_probe期间更新心跳产生负龄误报；真实未来心跳/过期心跳仍不标ONLINE。隔离复现旧竞态、7项边界回归及20项watchdog测试通过；完整巡检自检通过，生产服务未重启、业务DB未写入。源码备份、哈希、回滚命令和Self Check位于runtime/maintenance_watchdog/planner_clock_hotfix/。历史误报/恢复信号保留作为监控缺陷证据，不算真实Planner故障或生产自动恢复。


## 2026-10-09 SERVER_DRAFT_MKL_MEMORY_RECOVERY_V1

草稿Whisper/CT2初始化在Commit余量不足时触发mkl_malloc，8502经用户确认无未保存内容后按原参数单独重载。新增子进程单线程、Commit预算和完整日志，50次隔离完整草稿通过；原6个未来slot经本次显式授权沿用身份恢复并生成6个RenderJob，无重复或补发。恢复器runtime/server_draft_memory_recovery/recover_original_slots.py不得由巡检自动重放，只适用于已批准的原6个ID且最多2次。Planner未重启，父模块新增FAILED_RETRYABLE/gc/恢复接线须下一次正常授权启动才生效，不能当成已经热加载。昭暄正常生产另遇平台登录失效，已留Server账号认证事件；禁止重提历史Submit或改变托管意图。完整证据、限制及源码哈希回滚见runtime/server_draft_memory_recovery/REPORT.md。
