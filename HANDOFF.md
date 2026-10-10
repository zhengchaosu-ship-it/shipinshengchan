# 视频素材检索工具 - 工程交接文档 (HANDOFF.md)

### 2026-10-09：Level1轻负载收口与自然生产观察

用户主动结束全系统AUTOPILOT_UNATTENDED_LEVEL1_FINAL_OBSERVATION，实际04:23:05–09:56:57（5小时33分52秒），不延长。签发AUTOPILOT_UNATTENDED_LEVEL1_OPERATIONAL_READY；OBSERVATION_LOAD=LIGHT、MULTI_ACCOUNT_CONTINUOUS_LOAD=NOT_FULLY_VERIFIED、FULL_6H_TIMEBOX=NOT_COMPLETED。339样本/324扩展全局样本；5次正常Render完成及5次一次Submit接收排期，实际新负载集中夏竹花开，Gate已OPEN。首作品仍等待公开对账，不冒称PUBLISHED。当前共享基础设施正常，2060 ONLINE/READY、SessionGuard READY、Heavy Slot IDLE，D盘141.783GiB、Backup COMPLETE，无SYSTEM未恢复阻塞；四个历史隔离Job形成DEGRADED/YES。账本及导出收据重复0、采样slot leak0、实际轻负载观测HOL0；未经历压力/故障恢复场景不称已充分验证。原Account Sync负龄告警保留并分类为采样时钟竞态误报。专用Windows观察任务Disabled、level1聊天心跳PAUSED；正常Autopilot和常规维护继续，未写生产DB/造测试Job/Submit/改授权/重启Peer。独立Session认证和2060工程师聊天绑定仍待证据，不以生产心跳代替。

后续REAL_PRODUCTION_STABILITY_OBSERVATION已建立小型只读基线与每6小时聊天跟进，今日余下时间为基线，2026-10-10至10-14五个完整自然日只使用真实正常生产；保留原分钟守护及30分钟维护证据。无负载日、未经历的隔离/恢复场景、不可回溯连续区间明确标注，不凑任务、不要求重新人工六小时盯盘。结论及范围见runtime/xiazhu_recovery_20261009/FINAL_OPERATIONAL_REPORT.md；后续计划见runtime/real_production_stability_20261009/PLAN.md。以下原Level1计划仅作历史记录，以本节最终收口为准。

### 2026-10-09：夏竹花开单账号恢复与六小时观察

最新Probe UNKNOWN，用户明确重新认证和恢复托管构成本次Manual Ack；只恢复夏竹花开，Gate CONDITIONAL_OPEN、Runtime ACTIVE。最小Manual Ack接线及006/007迁移已部署（151项隔离验证、备份实际还原、自检通过），未部署通用Outbox Receiver。首次配置模式不匹配自动回滚后，通过正式sync_profile恢复该账号原确认PRODUCTION/启用标记，原授权配置哈希、额度、时间表、模板不变。非目标账号冻结窗口内行哈希一致，无历史补发、重复账本或测试Publish。下一条正常生产提交成功自动确认OPEN，风险复现仅暂停本账号且不重试Submit。六小时观察北京时间04:23:05–10:23:05，当前RUNNING；本机每分钟只读采样与Codex30分钟监督，2060工程师确认仍待正式绑定，不操作Peer。证据及12项验收见runtime/xiazhu_recovery_20261009/REPORT.md。一般维护仍禁止自主Manual Ack和迁移，本次仅为用户明确授权的单账号例外。

### 2026-10-09：Server自治维护V2与跨节点职责边界

新增 `server_maintenance/`，Codex当前聊天心跳 `SERVER_MAINTENANCE_CHECK` 每30分钟监督；Windows `XUNZHEN_SERVER_LOCAL_GUARD_V2` 每分钟恢复/保护，`XUNZHEN_SERVER_MAINTENANCE_SNAPSHOT_V2` 每30分钟留完整快照。两项SYSTEM任务已真实返回0。原Planner/API正式Task保留有限1分钟×3重试、IgnoreNew、StartWhenAvailable；新增日志入口、旋转日志。Planner曾EXITED_RESULT_1，在只读Schema/DB预检、instance_count=0后恢复并验证心跳；历史原退出原因若缺traceback仍UNKNOWN，不能推定已证明。API重槽空闲且无候选任务时加载本地水位派发门禁及认证只读 `/maintenance/coordination`，自检通过；2060不重启、不操作GUI。

Backup启动前核验source_size、free_space、expected_temp_space及20GiB余量；50GiB以下拒绝大副本，force不绕过。沿用已修复失败退避/只验证已有副本，Backup异常熔断不阻塞生产。20GiB以下只拒绝新Heavy领取/Planner生成，heartbeat、API、8502和轻量核对保留。坏Job只在未执行/未Submit/intent空/无租约且事务再次验证后隔离，不重建、不重提；默认清理清单为空，已证明SAFE_TEMP/CACHE按TTL+SHA+size清理，UNKNOWN不动。无Schema Migration、无真实测试Publish、无历史补发；搜索模型/索引受保护stat及6份授权校验不变。

最新CROSS_NODE_COORDINATION_POLICY：SERVER_ENGINEER为当前服务器电脑Codex，拥有Planner/API/DB/Storage/Backup/Account Sync/Account/Queue/Reconciliation；EXECUTOR_2060_ENGINEER为2060电脑负责AUTOPILOT_UNATTENDED_LEVEL1的Codex聊天，拥有Worker/SessionGuard/Jianying/Render/Export/Verify/Yixiaoer/Heavy Slot/Journal/REJOIN。每事件LOCAL/PEER/CROSS_NODE归因、稳定incident_id及明确incident_owner。Server失联造成Peer心跳缺失不能触发Worker恢复；Server只发请求，不能释放Peer Slot、改Peer Journal或操控GUI。用户明确暂不发聊天通知，**不得把“发布计划交接流程”绑定为执行节点工程师**；正式绑定等待用户在2060聊天加入同一策略。共享状态及PEER_RECOVERY_AVAILABLE位于 `runtime/maintenance_watchdog/coordination/`；无Peer DB传话，不同时修同一根因。

报告 `runtime/maintenance_watchdog/latest.json/latest.md/history/`，分钟快照 `minute.json`；永久自主动作审计 `repairs.jsonl`。已记录完整目录大小基线，首轮30分钟增长为待采集，不写成0。Codex额度/网络/未启动只记录MAINTENANCE_WATCHDOG_UNAVAILABLE，不构成Production Blocker。回滚保留其它Server修复与只读Schema门禁，不还原业务DB；执行前检查源码未被后来修复覆盖且回滚隔离回归通过。操作、白名单、禁止项及验证见 `server_maintenance/RUNBOOK.md`。

### 2026-10-08：正式 JOB / ACCOUNT / SYSTEM 故障隔离与账号运行态

新增 `production_autopilot/account_runtime.py` 和增量迁移004。账号用户授权与运行态分开：当前账号风险只设 `PAUSED_NEEDS_ATTENTION`，保留原授权；未来尚未开始的自动分配取消，已执行/已提交/历史终态保持。Coordinator、Planner及生产写入口都检查运行态。用户在8502“重新开启托管”通过本地账号同步、Provider映射/认证、当前发布门轻量检查后，恢复未来有效时段，不创建测试任务、不补过期slot、不跨天追债。正式LOCAL通道现有8100秒安全提前量继续适用，daily_publish_limit仍由用户配置决定。

平台已接收后的公开等待改用独立轻量核对租约，不持媒体Mutex、重任务槽或busy，不允许使用核对令牌执行stage/submit。每次查询有界，失败只安排下一次只读核对；提交闩锁不复位，SCHEDULED_QUEUED不会因暂时SUBMITTED观察倒退。原重槽中晚枫 `1df99efb-7acd-4e65-9a30-b7205a6a077d` 的旧核对租约已在正式Worker停止且本机Mutex/无执行器证据成立后释放，历史任务行逐字段未变。此前Control Tower记录的长时间核对红色规则由本节替代：单Job及账号问题为黄色，只有共享基础设施故障为红色。

8502账号总览统一采用运行态，不再把保留enabled授权的暂停账号写成自动托管中；显示原因、用户动作、最近公开时间及恢复按钮。页面刷新纯读。夏竹花开当前ACCOUNT_RISK单独暂停，其他5份生产授权继续。新取消状态不占有效slot唯一索引或预算；迁移先备份，保留全部原行/外键，外键完整性检查通过。历史FAILED不复活；本次维护也没有改历史SCHEDULED_QUEUED/PUBLISHED事实。

用户明确批准短暂停止、更新并恢复原调度。2060仅更新api/coordinator/publisher/worker四文件，版本 `FAULT_ISOLATION_V1_20261008`；未重启Windows/剪映/蚁小二，未开启Server Upload。09:13:46维护审计通过：新增Render/Publish/Allocation=0、Submit增量=0、六份授权逐字段不变；只取消风险账号3个未来预留。09:14:06恢复唯一正式任务 `XUNZHEN_RENDER_WORKER`（PID22376），随后恢复Server原托管任务。恢复后正常生产另计，保持过期slot不补。后台已核对多个历史排期，重槽IDLE。

六账号A–F隔离场景、六小时平台等待模拟、提交令牌隔离、恢复失败不创建任务、用户OFF优先、总览运行态等通过。回归日志：主125次、补充99次、最终UI20次，去重173项。09:20正式8502已显示DEGRADED/YES、“系统空闲，正常等待下一任务”，19个已提交作品的轻量查询记录可见，重槽IDLE；5个账号托管中、夏竹花开单独暂停。正式DB审计和日志在 `production_autopilot/runtime/fault_isolation_20261008/REPORT.json`，四文件哈希/本机验收在 `outputs/lan_render/fault_isolation_20261008/`。不要重跑一次性安装脚本或用备份覆盖生产提交账本；源码备份为 `.fault-isolation-20261008.bak`，2060原文件保留于Resident/fault_isolation_backup_20261008。无人值守Session认证仍PENDING。

### 2026-10-08：8502 Production Control Tower V1

首页顶部统一展示生产总状态、现在是否可以投入生产、当前账号/内容/阶段/持续时间/最后进度、五项队列摘要、下一计划任务、最近结果及1h/24h统计。每15秒只刷新只读fragment。普通首页不展示PID、UIA/COM、租约或原始表；原执行诊断移至高级管理→系统诊断，旧独立Publisher明确LEGACY/已迁移。采用ProductionReadinessEvaluator输出READY/DEGRADED/BLOCKED及reason_codes/human_messages；统一Worker在线与业务能力分别判定，账号风险及已隔离Job为黄色，真实节点离线、数据库不可用、执行位置冲突等全局阻塞为红色。旧Render/Publisher健康源在读取时排除，Server Upload DISABLED不构成异常。

纯读模型使用SQLite mode=ro及query_only，不实例化生产Worker/Planner/Publisher、不调用claim/recover/submit。新增UI不迁移Schema、不调整托管授权、不启动或重启2060。无Runnable任务时明确显示“系统空闲，正常等待下一任务”；SCHEDULED_QUEUED只计平台定时队列，成功提交/排期不冒充PUBLISHED。无人值守认证默认PENDING，不能因进程已运行六小时或前次Console测试而自动升级；该认证提示本身不阻止生产。

当前数据暴露真实长期占用：晚枫起号10月7日-2，Job 1df99efb-7acd-4e65-9a30-b7205a6a077d，PUBLISH_RECONCILING租约自04:23:06持续，节点心跳新鲜但没有阶段推进。总状态按30分钟发布阶段只读告警预算显示BLOCKED/NO，保持Worker ONLINE，不把重复SUBMITTED journal写入或租约续期显示成任务进度。本轮未处理该原Job、未重试提交、未取消租约或关闭托管。红色为就绪判定，不代表页面执行了暂停动作。

统计来自统一执行账本：完成按任务去重，恢复完成须有后续成功证据。完整历史JOB_STALLED/Worker crash缺少持续采样，显示未采集/NULL；导出收据未全部回传时完整duplicate export为NULL，另保留已观测收据统计。不得把这些未知值改成0。进程uptime使用同PID、owner_alive的既有启动时间；连续在线只累计页面真实观测到的心跳，超过90秒间隔、PID或启动时间改变后重置，不把uptime冒充连续心跳证据。

40项回归通过（含A–G、纯读SQL拒写、数据库不可用、短时正常对账与长时间占槽、时间窗去重、后台刷新及原三模块路由）；真实8502页面/高级诊断已核验。源码备份.control-tower-20261008.bak，交付及正式库8次只读刷新审计位于production_autopilot/runtime/control_tower_20261008/REPORT.json。本轮功能新增RenderJob/PublishJob/真实提交均0；既有后台正常生产与此页面读取行为分开计账。

### 2026-10-08：无人值守验收基线已保存，真实Session矩阵及六小时验收待补

本轮状态为ACCEPTANCE_PENDING_SESSION_VALIDATION，不能报告2060_UNATTENDED_PRODUCTION_ACCEPTED或ACCEPTED_WITH_SESSION_REQUIREMENT。用户明确当前只能使用ToDesk；2060实测为sdaffwS / Console / Session1 / WTS协议0 / Default输入桌面，不能用其替代RDP连接或断开测试。锁屏与用户切换尚未执行，等待用户确认能够恢复登录；没有自动解锁。按请求顺序，Session测试未完成前不启动六小时验收计时，也不将此前生产运行时长补算进去。

开始时发现既有晚枫Job STARTUP-872a5aef-32a5-428b-85a1-b126e8a4b9b9已在导出后的close_home失败：UNOWNED_JIANYING_INSTANCE_NEEDS_MANUAL。环境检测换了主PID，持久ownership已正确更新，但render_child局部owned缓存未同步。仅修改agent.py及workstation_health.py：关闭前核对同worker/job/launch_token及PID创建时间，合并已经证明归属的PID，不放宽人工进程或PID复用保护。187项唯一回归通过。原成片通过原恢复入口重新校验后COMPLETED，export latch未变、没有重导出、没有Publish调用，旧租约已释放。

另做Console补充批次：3/3不同测试草稿打开、连续3次READY及安全关闭通过，分别37.90/55.55/36.64秒；UIA/COM错误0、child非零退出0、重复Export/Submit0、slot已释放。正式Worker在媒体互斥锁阻止生产领取时继续心跳，14个存活采样、13个不同心跳、最大心跳年龄12.14秒。隔离测试草稿使用独立ownership状态，正式健康观察曾短暂UNKNOWN_MODAL/NEEDS_ATTENTION，始终没有心跳离线；该事实保留，不能将此批次描述为全程READY。0x80040201为NOT_REPRODUCED_DURING_ACCEPTANCE，仅限已执行Console补充批次。

仓库未初始化Git，因此status/diff/commit不可用；不创建假commit。初始及修复后代码均归档并逐文件SHA256：2060修复后集合哈希5b9e40531fba10c599bb30a1bcc0dab8b911877932951fc6f9d96d3d3aa8ce3c，Server集合哈希813f26b443b61a9c3615093e1869ccc470d34c8b3b6764033dbda029042f1f3a。版本JIANYING_MTA_PROBE_V1_20261008。源码备份后缀.unattended-acceptance-20261008.bak；2060两文件部署有独立原版本备份。当前仅冻结验收候选基线，最终核心冻结仍待完整验收。

维护期审计新增业务RenderJob=0、PublishJob=0、Provider submit增量=0；六份托管授权逐字段未变、Server Upload DISABLED。春福轩STARTUP-138bf05b-3a96-43be-97d8-f02873638198仍FAILED_JOB_LEVEL且recovery_count=1，未重试。Session条件等待期间按用户此前明确授权结束维护并恢复正常生产：02:00:48启动唯一2060正式Worker，实际PID24892；02:01:29恢复Server原托管任务。生产恢复之后的正常业务须与维护期零发布审计分开，过期slot跳过规则未改。详细基线、187项日志、console_summary.json、maintenance_audit.json及待验收报告位于outputs/lan_render/unattended_acceptance_20261008；完整UI证据留在2060的D:\JianyingRenderWorker\UnattendedAcceptance20261008。

### 2026-10-08：剪映公共UIA执行链批量验证，跨会话验收待补

修复范围为公共Jianying 5.9执行器及8502健康映射。旧执行器将Qt切页期间Win32/UIA非原子快照当成最终状态，并跨窗口生命周期保留COM控件；晚枫的0x80040201发生于UIA属性读取，春福轩为旧加载窗口消失期间UNKNOWN_MODAL误判。没有证据证明两者具有同一个剪映内部COM缺陷，也不能将该HRESULT直接解释为RPC/线程apartment错误。

每次关键读/输入现在由独立短生命MTA helper完成，父Render只接收JSON；目标HWND、PID/创建时间、控件语义和命中区域均重新验证。草稿需精确身份、时间线时长、关键编辑器控件及连续3次稳定观察。补齐虚拟首页滚动、环境检测后的归属延续、透明导出面板和严格校验的设置菜单；未知窗口仍拒绝输入。导出闩锁保留，可能已点击的输入不重放；仅明确尚未派发输入的COM错误允许有界重建探测器。

新增细分阶段、Render领取前MTA/交互会话自检、30分钟内两个不同Job同类失败的Render熔断；成功打开不能掩盖之后的导出阶段失败。Publish独立于Render自动化熔断。8502使用统一2060心跳区分节点在线、渲染/发布能力和执行槽，并显示Automation Health、最近10次打开、30分钟异常数和最后异常时间；旧Server Publisher心跳不再作为普通页面故障。

185项唯一回归通过；2060最终批次open_v13为10/10不同草稿、export_v3为5/5完整导出+ffprobe+full decode，均1080×1920/30fps/H.264。最终批次COM/UIA异常和child非零退出均0，每条export latch=1。前期调试有14次测试child非零退出（其中1次日志明确COMError），全部保留，不能将整轮描述为零失败。生产任务新增0、Publish新增0、真实Publish=0；六份托管授权逐字段未变，Server Upload保持DISABLED。

春福轩原Job STARTUP-138bf05b-3a96-43be-97d8-f02873638198仅恢复一次，但本次维护脚本未设置代码工作目录，导致模块子进程在启动剪映前ModuleNotFoundError；这是维护入口错误，不是另一次草稿UIA失败。Job已FAILED_JOB_LEVEL隔离、租约已释放、recovery_count=1，没有第二次尝试或新Job。公共子进程已固定代码cwd，并通过异目录真实子进程回归及2060模块入口检查；不得因此清除原Job恢复闩锁。

SESSION_REQUIREMENT：当前登录用户的活动console session、未锁定Default输入桌面。当前Session1/MTA真机通过，会话不可用的领取防护回归通过；RDP连接/断开、锁屏/解锁和切换用户尚未实机测试，已请求用户配合，因此不报告全量JIANYING_DRAFT_OPEN_EXECUTOR_STABLE。详情：`outputs/lan_render/draft_executor_stability_20261007/REPORT.json`、`validation_summary.json`及`media_execution/runtime/draft_executor_stability_20261007/maintenance_audit.json`。原源码备份后缀`.draft-executor-20261007.bak`；不回滚业务数据库、发布闩锁或恢复计数。

按此前明确授权，维护边界结束后01:10:35恢复唯一2060计划任务（实际PID28524），01:11:03恢复原Server托管调度；未启动旧Render/Publisher服务，未改六份账号授权。随后既有忍冬Job STARTUP-80085457-01be-4366-85d5-b78e456addca通过公共正式入口COMPLETED，后续队列继续单槽运行。正常生产与维护期零任务/零发布审计分开记录；过期slot不补、无跨天欠账。春福轩原失败计数及隔离保持，夏竹花开当前ACCOUNT_RISK门保持阻塞。普通8502已实际显示统一2060在线、Automation READY；不会把迁移前Publisher心跳过期当成生产故障。

### 2026-10-07：剪映占用与Worker故障分开

`media_execution/workstation_health.py`按进程PID/创建时间/账号/路径、持久ownership、当前租约、journal、近期心跳和只读UI证据区分八种剪映状态。Worker自己首页空闲为READY；渲染、导出、成片校验为BUSY；人工使用为WAITING_FOR_WORKSTATION，Render和Publish均不领取执行槽。人工退出后下次心跳自动READY；健康检查不修改托管授权。仅真正版本、未知窗口、导出超时或执行身份不明等风险进入NEEDS_ATTENTION。

专用启动器完成核验后写入2060 `Resident/media_execution/jianying_owner.json`，含PID、创建时间、launch_token、launch_time、render_job_id、draft_id及父Worker身份。PID复用不继承归属。无租约且证实为Worker旧首页的实例可沿用原安全收尾；人工编辑/无归属窗口不关闭。领取前在全局媒体锁内重新观察。BUSY只覆盖实际执行，不覆盖空队列轮询。8502显示中文占用状态，旧协议将人工占用兼容为BUSY而非故障。

保留既有daily_publish_limit及过期slot不补发策略。回归覆盖A–H、单槽、Exactly Once、草稿/导出流程和slot策略，详情见 `media_execution/runtime/health_semantics_20261007/REPORT.json`。本轮不创建真实Render/Publish任务，不提交作品，不更改历史失败，不开启托管。

### 2026-10-07：用户每日额度固定，错过时段不追补

每日数量由用户设置的`daily_publish_limit`（保留现有1～5上限）、剩余合法发布时间和实际执行条件共同决定。AI素材评分仅影响素材排序、组合、探索与补素材建议，不修改用户额度。既有评分实现未设置按分数减量的门槛，回归已验证极低评分仍保留5条额度。

已取消`media_execution/replanning.py`把过期任务挪至未来14天的行为；恢复后仅继续原来仍满足安全提前量的slot，过期未提交分配记`MISSED_NOT_SUBMITTED`，对应从未提交且无租约的Job取消，原时间及READY成片保留。Submit Intent、已提交、FAILED和平台队列不改不重试。控制层也拒绝改时追补。过期/跨天父任务不再绑定为新一天的补欠账；正常次日仍按用户自己的时段和额度规划。

`reserve_daily`保留各slot可用的合法组合，不因部分slot无合法素材而整批拒绝，不改变daily_publish_limit。启动检查有合法组合即可通过素材项；缺失slot记录原因，自然少发，不集中补发。用户暂停/结束、账号风险与Worker条件保持原限制；未开启任何账号托管。

84项唯一隔离回归通过。两个空闲Server控制服务已完整重启加载代码，原Server上传任务仍Disabled。生产审计：新增RenderJob/PublishJob/真实提交均0，6份授权、分配、lineage、历史FAILED及Submit闩锁不变；已有SCHEDULED_QUEUED作品仅后台只读对账时间戳自然刷新。当前2060因19:03:58已启动剪映进程而报告NEEDS_ATTENTION（早于19:12:15 Server重启），未代用户关闭程序。源文件备份后缀`.slot-policy-20261007.bak`，无Schema变更。证据：`production_autopilot/runtime/slot_policy_20261007/REPORT.json`。

### 2026-10-07：8502正式托管启动门禁修复

`AUTOPILOT_START_GATE_RECONCILED`。仅修改`production_autopilot/preflight.py`及启动弹窗成功文案，未改Publisher、Planner、Metrics或学习流程。正式门禁读取WORKER-2060S-01新鲜READY心跳、本机蚁小二及PublisherInfrastructure，不再依赖已停用的Server Publisher心跳；Server Upload及旧上传计划任务保持DISABLED。

旧“已有作品或账号异常”由历史FAILED和OPEN风险事件触发；原检查只认可`resumed=true`，不认可新架构`gate_recovered=true,resumed=false`。现按当前OPEN/ONLINE发布门与较新成功恢复证据，将旧风险归类RESOLVED；FAILED归类HISTORICAL，当前风险仍ACTIVE并阻塞。只读分类，不修改历史任务、事件或授权。SCHEDULED_QUEUED不阻塞，并复用既有每日occupancy计算余下素材需求，不创建计划。

夏禾、夏竹花开eligibility均true、blocking_reasons均[]。真实8502夏禾弹窗已显示“可以开始正式托管”，每天最多5条：09:08、12:23、15:26、18:18、21:06；最终按钮未点击。夏竹花开仅检查，有限素材校验缓存位于检查副本。33项唯一隔离回归通过（11项新增门禁测试、7项既有门禁测试、15项正式托管回归）。审计：RenderJob新增0（总61）、PublishJob新增0（总297）、ProviderJob新增0（总59）、FAILED修改0、Submit闩锁增量0、6条授权逐字段未变且均关闭。证据：`production_autopilot/runtime/start_gate_20261007/REPORT.json`，对应`.start-gate-20261007.bak`为源码备份；无Schema迁移。


### 2026-10-07 18:29：正式托管闭环接入完成

`PRODUCTION_AUTOPILOT_FINAL_INTEGRATION_READY`。冻结2060本地成片→本机直接上传→Yixiaoer→Provider架构，Server上传仍DISABLED，未改已验收上传/Submit实现。本轮新增真实发布0、历史FAILED修改0、全部Submit闩锁不变；6条长期授权逐字段未变、enabled仍全部0。

既有Server控制Worker已部署持久公开观察与2h/24h/72h窗口，托管关闭也能继续已提交作品的只读生命周期。官方公开证据后才PUBLISHED/published_at和建指标任务；目标夏禾作品`7693858927401848099`仍SCHEDULED_QUEUED，首次公开检查2026-10-08 09:08 +08，目标尚无Metrics。按content找回原composition `ffc495df-c247-4f53-8583-71d0f1cbf20d`、模板1及3个slot/material身份，不改旧分配排期。

Metrics缺失NULL、陈旧RETRY、迟到LATE_CAPTURE，旧精确窗口不被覆盖。VERIFIED组合+PUBLISHED+有效EXACT数据才进入既有账号/Slot偏好，Planner已接BanditSelector。MaterialDemandEngine每30分钟生成建议，8502“视频生成模块→素材任务”可见20条建议，产品未绑定NULL；首页区分生成、待渲染、READY、待发布、平台定时队列、已公开、账号异常。当前真实有效学习样本仍为0，不宣称已完成未来采集或训练。

103项唯一隔离测试通过（12新增、91既有），AppTest、真实浏览器、服务新心跳、业务库完整性及基线审计通过。所有未来长期生产仍等8502用户“确认并开始托管”。报告与备份：`production_autopilot/runtime/final_integration_20261007/REPORT.md`；增量迁移`production_autopilot/final_integration.sql`，不另建PublishJob，不全库回滚。

### 2026-10-07 17:49：2060独立真实发布追加验收PASS

`REAL_PROVIDER_PUBLISH_ON_2060_PASS`。用户新增最多1条正式任务授权后，实时核验夏禾OPEN/ONLINE，选择尚无PublishJob的READY成片 `STARTUP-94affa8d-6268-4e22-adaf-58f81f8d4929`。2060全片复验通过，新Export=0；新PublishJob `4026d43a-b45d-4ec2-9bae-b1564d3d350f` 由2060本地视频直接上传，视频/封面各1次、正式POST=1。官方scheduled/success，Task `6ac613e9799bed4c0357c33b`、Video ID `7693858927401848099`；Server已回写SCHEDULED_QUEUED，排期2026-10-08 09:08 +08，尚非公开PUBLISHED。

Server上传0且保持DISABLED；活动48次Mutex采样全持锁、最大执行并发1、无Render重叠；本轮没有同期Render，WAIT未重测。历史296条PublishJob/58条ProviderJob及6授权逐行未改，长期托管仍全部关闭；旧夏竹花开风险失败任务未重发。一次完成后停止真实测试，Worker READY、租约释放。详情及16项报告 `media_execution/runtime/real_provider_validation_20261007_additional/REPORT.md`，本条为最新状态，下方此前FAILED_ACCOUNT_RISK记录保留为上一次验收历史。


### 2026-10-07：正式生产素材库迁移到 E 盘完成

`PRODUCTION_MATERIAL_E_DRIVE_LIBRARY_READY`。正式根目录 `E:\寻帧生产素材库`；创建30个目录（15个规定目录及15个保留来源子目录）。249文件逐项SHA256迁移并复验：起号125个/7,479,027,997字节，背景6个/14,772,175字节，待确认118个/6,703,881,193字节；带货0个，Duplicate=0、Failed=0。旧目录保留为LEGACY_EMPTY。4.20素材和求赞求关注素材未猜分类，保留来源层级进入待确认区；8.13手法按明确目录分类归入手法子目录。特效、教程、半成品和成品保留原位。

8502实际浏览器已核对五个Commerce接收目录自动绑定；10类Registry均READY，Commerce目前为空池。上传依然只提交pool_id/产品，服务器解析真实路径。正式pool_id为STARTUP_LEAD/STARTUP_CLOSE，旧module_type STARTUP_HOOK/STARTUP_ENDING保留兼容。ProductionMaterial持久表原为0条，更新0条，没有创建重复material_id；legacy_inventory当前131条可用路径全部有效。6账号的24个既有起号池ID、模板及背景ID保持；更新750条SHA缓存、6条背景编目及6条绑定路径。原先1条缺文件的历史缓存不参与现行编目，保留记录。

完整SHA复验、起号四类及6账号hash_budget=0读取、背景snapshot、10池HTTP查询、8501/8502/8510健康检查通过。62项隔离回归通过（迁移/上传23、背景/模板39）。Commerce只验收既有查询接口，项目仍无完整CommerceCompositionPlanner。原后台自行刷新16条偏好证据时间/version_hash，业务值相同，未回滚其记录。Raw Index移动=0、Render/Jianying移动=0，索引文件属性不变；没有生成、渲染、上传发布任务。

正式报告及5个要求文件位于 `E:\寻帧生产素材库\_管理`；工作副本、三库一致性备份、测试记录在 `production_materials/runtime/e_drive_migration_20261007/`。迁移脚本 `production_materials/migration.py`，验收脚本 `production_materials/verify_migration.py`。恢复只按manifest和备份恢复本轮路径字段，不得整体回滚operations.db覆盖并行发布记录。下方“Commerce尚未配置/旧目录”的2026-10-07早期上传入口记录为迁移前状态。

### 2026-10-07：2060S Render/Publish执行交接完成

`RENDER_PUBLISH_2060S_EXECUTION_HANDOFF_READY`。IMPLEMENTED / WIRED / DEPLOYED / VALIDATED均PASS；`REAL_PROVIDER_PUBLISH_VALIDATION = FAILED_ACCOUNT_RISK`。正式Server已接入原DailyPlanner/Composition/RenderQueue/Plan Confirm/ProviderStore、8502、Worker Health、AccountPublishGate、Recovery与后台Archive；沿用原Content/RenderJob/PublishJob及稳定账号ID，附加执行表只维护租约/执行关联，不建立第二套业务Job。新成片在2060本机验证并可直接进入原发布计划，Server不必先持有MP4。

2060（DESKTOP-9VQ76D3 / WORKER-2060S-01）已部署2060-HANDOFF-20261007，原XUNZHEN_RENDER_WORKER计划任务常驻运行并恢复READY。部署方式LOCAL_BOOTSTRAP_AND_REMOTE_FINALIZE：用户本机管理员启动后，修复UNC ProviderPath、PowerShell退出码及旧venv子进程残留，使用已授权远程维护通道完成切换、校验及真机验收。正式运行由2060主动访问Server 8766控制API；不依赖Server→2060 SMB/WinRM。原Server Planner和控制服务持续运行；验收通过后Server Provider Upload切为DISABLED，旧Publisher计划任务停用，fallback代码保留。新发布节点固定WORKER-2060S-01。

20任务真机混合验收：10次剪映5.9真实导出，10个原模型Mock Publish中5个完成提交、5个BLOCKED_RISK等待；15个可执行任务全部推进，实际重任务最大并发1、越界领取0、队首阻塞0。10份输出ffprobe及全片解码通过，每个Export闩锁恰好1次。Worker进程在MP4已验证/回执前及Mock POST后分别中断，并重启Server服务；原Job恢复，无重复Export，5个Mock POST各1次，不确定提交仅只读对账。10份后台归档SHA两端一致，忙时暂停及归档失败隔离通过。20任务初验未做真实Provider提交；随后追加1次真实发布，结果如下。Windows整机重启未做。

旧夏禾成片复验通过，未再导出；单Job历史异常不再永久HALT Worker。剪映前台焦点及环境检测已成功弹窗的有限重观察修复已部署；未知弹窗仍保守停止该次执行。2060本机蚁小二CLI/客户端/自身clientId及直连检查通过；迁移凭据经用户明确授权，未在安装包存放凭据。6份长期托管授权保持停用；初验时4个账号有风险门、真实Upload/Submit=0。随后追加真实发布及两账号验证恢复，结果如下。

本任务修改历史PublishJob=0。主体切换检查点新增执行Job=0、ProviderJob57、PublishJob295、submit_attempt总50；追加单次验收后分别为58、296、51。旧后台对账期间21条Provider行发生遥测/对账更新，不能声称所有历史表hash未变。2060最终代码68项回归通过；本机核心、桥接、确认、恢复回归及正式8502面板读取通过。完整23项交付与证据见 `media_execution/runtime/finalization_20261007/REPORT.md`；真机证据 `outputs/lan_render/2060_acceptance_20261007_v2/worker-evidence/`；本机安装包 `deploy/2060_handoff_release/`。下方此前HALTED/第一阶段记录是历史状态。

本轮追加真实发布验收：用户指定“夏竹花开”并确认已完成官方验证。实时CLI核验稳定账号 `6ac4b574faa99a4ec8670bb3` 后，选用其尚未创建PublishJob或提交的既有成片 `STARTUP-3d90a6f4-5783-468f-80c3-d1d55c86b7af`（122.033秒），2060复验SHA/全片decode通过、与已有归档相同，新增Export=0。按原额度和时段创建唯一新PublishJob `f69e3602-e088-47ec-b9a5-6a27f92dd062`，计划10月8日09:18，未重新开启长期托管。

2060本机真实上传视频1次、封面1次，validate与LOCAL dry-run通过，正式POST恰好1次。Provider TaskSet `0ee25a0c-775a-4dc0-87d1-a6e3251ee82f`、Task `6ac607c1e888b10a7efba166` 返回新的官方账号风险失败：仍要求到创作者中心单独发布并完成验证。Job为FAILED、无Video ID、没有成功进入平台定时队列；不能将预定10月8日09:18描述为已经安排成功。收到失败回执时账号重新BLOCKED_RISK，原任务不重发；用户随后再次确认验证后的账号状态见下。**REAL_PROVIDER_PUBLISH_VALIDATION = FAILED_ACCOUNT_RISK**，执行交接状态仍为READY。

实测补齐客户端异步执行保护：CLI返回任务ID后，2060继续持有执行槽/Mutex/busy直到只读回执确认定时队列或失败；Worker中断后，Server对未确认结束的Provider执行保留重任务门，禁止另一个Render/Publish或Archive进入。只读终态确认后才释放；账号失败只封该账号。另修复单独手工确认的新计划不被旧托管暂停错误阻断，以及LocalOperator预览和已核验恢复门的保持。60项最终本机回归通过；最终代码部署到2060并重新校验297个代码文件SHA，节点专项结果见node-provider-final.stderr.txt。

真实验收前后逐行对比：原295条PublishJob、57条ProviderJob及6份长期授权完全相同；仅新增上述1个PublishJob/ProviderJob。最终计数PublishJob296、ProviderJob58、submit_attempt总51（新增1）；长期托管enabled=0。切换主体阶段旧后台曾更新21条Provider遥测/对账行，独立记录。最终证据 `media_execution/runtime/finalization_20261007/FINAL_AUDIT.json`；官方CLI证据 `outputs/lan_render/2060_acceptance_20261007_v2/real-provider-evidence/`。

用户随后再次明确“夏竹花开和夏禾，完成了验证”。2026-10-07 17:28（Asia/Shanghai），2060官方CLI doctor及账号查询通过：两者稳定ID匹配、ONLINE、未冻结/锁定。原后台只读恢复请求均CHECKED，账号门恢复OPEN；6份长期托管授权保持enabled=0、旧失败Job和POST=1保留。此次复查新增PublishJob/Upload/Submit均0，不把账号门OPEN描述为真实发布已成功。本轮最多1个新正式PublishJob的额度已使用；若另做真实验收，须有追加范围授权。证据 `two_accounts_recovery.json` 与 `FINAL_AUDIT.json`。

### 2026-10-07：RAW_VIDEO_RUNTIME_DECOUPLING，10条物理隔离通过

`RAW_VIDEO_RUNTIME_DECOUPLED_DELETE_READY`仅针对新候选清单293条TS/394.461486GB，预计扣除新增侧库、备份和验收占用后净释放约393.909GB；原片实际删除=0。10条有历史图搜/Speech/描述依据的TS已完整SHA校验后同盘隔离，ONLINE/OFFLINE图搜、Speech Semantic、描述各10case的Top1/5/10、时间、分数、JPEG指纹完全一致，ORB缓存匹配10case相同，正常查询Raw open=0。实际8502搜索渲染函数及共用卡片/对话框无异常，无生产后台启动/重启。全部源已恢复，SHA前后相同，388条源状态ONLINE。

新增`raw_assets`独立侧库迁移、CachedFrameProvider/PersistentThumbnailStore；旧ORB/展示缩略图无VideoCapture回退，Speech segment映射复用正式DINO非空JPEG1,843,351帧（缺失0）。新补帧6,092张/150.76MB，话术映射1,053,910条/99.8312%；仍缺1,782个segment涉及59资产/66条TS，全部KEEP；缺图只显示占位，不读原片。OFFLINE_SOURCE/MISSING合法独立状态，离线禁止服务器预览、保留员工文件名/时间及复制控件。唯一索引MP4来源仍未证实，KEEP。主生产schema/模型/权重/索引格式未改，72,076原受保护文件属性未变；根目录26项测试（GPU skip1）及28项定向测试通过。

候选、KEEP、完整元数据备份、物理隔离恢复日志及限制说明：`raw_runtime_decoupling/20261007/REPORT.md`。验收使用已有CPU环境及测试专用全量分块精确FAISS读取器，未回放旧MobileNet整库，未点击真实浏览器剪贴板。常驻8502在现有页面rerun热载ui.py，旧Speech对象的空thumbnail由展示层读持久存储。待用户另行确认`RAW_VIDEO_CONFIRMED_DELETE`，本轮不清理原片；下一次操作必须先永久标记OFFLINE_SOURCE并保留全部身份/索引/缓存。下方“删除阻止”是改造前历史审计记录。

### 2026-10-07：原始直播存储只读审计，删除阻止

状态 `RAW_VIDEO_DELETE_BLOCKED_BY_RUNTIME_DEPENDENCY`。两个既有根目录共388个视频文件/472.826GB：359个非空TS直播原片/472.035GB、28个空文件、1个已索引MP4“引导9.14新”（原始直播身份未证实，UNKNOWN）。相邻目录与录制工具另有6个未登记测试/教程MP4，全部保留；最终KEEP清单394条，DELETE清单0条。当前DINO/CLIP查询核心从索引及独立JPEG读取；319资产/1,843,351帧非空JPEG记录覆盖完整。CLIP→DINO 362,752条映射、Speech 3,099,048条资产身份映射不一致均0，Speech保留3,147条时间warning。

旧video_search.py的ORB与展示缩略图在缺旧缓存时仍VideoCapture原片，正式ui.build_preview_clip仍检查/FFmpeg读取原路径（已有预览缓存也先要求源在线）；Speech返回thumbnail=None，OFFLINE_SOURCE与指定复制按钮未实现。本轮仅代码/存储审计及小样本补充验证，没有改生产schema、UI、模型、向量、权重或索引。无10条合格MP4，物理脱机实验未执行；实际DINO/CLIP/Speech索引另行加载均内存分配失败（CLIP独立进程也失败），不能声称正式Top1/5/10验收通过。10条TS进程内原片访问拒绝实验确认7个历史ORB命中点有源依赖；8条Speech Exact结果一致，不能替代Semantic。

元数据轻量备份约98.41MB、清单、容量及完整结论位于 `raw_storage_audit/20261007/`，详见 `AUDIT_REPORT.md`。28空文件、邻目录测试/教程与身份不明MP4仍保留；生产素材仅统计且全部排除删除。已有受保护文件大小/mtime未变、无移除；并发服务另增2个旧预览缓存已单独记录。原片移动=0、删除=0，素材上传=0，本轮停止，未进入实际清理。

### 2026-10-07 00:41：追加授权夏禾单任务恢复完成，随后停止

用户明确追加仅恢复“夏禾起号10月6日-3” `STARTUP-94affa8d-6268-4e22-adaf-58f81f8d4929`，允许最终导出最多1次、ffprobe+全片解码、仅局域网回传原目录、READY对账，禁止任何Provider/Publisher推进。保持该旧任务冻结的稳定账号ID `YXER-DY-6ac4a551e49305f1ab81d5ae`；历史草稿名不用于按当前昵称重新绑定。

一次最终导出成功，复用既有HEVC→H.264兼容处理并保留原HEVC；成片62.9秒、1080×1920、30fps、H.264/AAC、46,117,442字节，全片解码通过。SHA256 `9dd76d99bf3936c1882042e8467c4c8651a146eb4c9b604a4a902f3e66e7fed0`。原RenderJob内部状态COMPLETED，原Content production_status READY / publish_status NOT_SCHEDULED；旧失败回执及state保留。正式Worker重新上线IDLE，三项健康与RenderCapability READY、无当前任务。全局领取设置恢复前确认仅余旧排队任务仍受停用账号保护，没有触发其它Render。

本次追加恢复统计：RENDER_EXPORT=1、LAN_OUTPUT_TRANSFER=1、PROVIDER_UPLOAD=0、PUBLISH_JOB_CREATED=0、REAL_PUBLISH=0、新Content/RenderJob=0。原ProviderJob计数56、提交闩锁49均不变；独立后台于00:37因官方对账提示“系统未找到此作品”把最后1个运行账号停用，未改动这些账号状态，不能将独立发布侧异常当作Render阻塞。按用户“完成后停止”结束，未进入Publisher。验收 `startup_render/runtime/export_recovery_xiahe_20261007/DELIVERY_VERIFICATION.json`，媒体 `outputs/lan_render/EXPORT_RECOVERY_XIAHE_20261007/validated_output.json`。以下00:29待授权描述保留为历史过程。

### 2026-10-07：原忍冬任务恢复完成；后续夏禾任务仍待单独恢复授权

本轮锁定 `STARTUP-8fa633ab-a8e3-4653-96dd-02b61aac2e14`，根因是首页草稿卡位于窗口外，旧UIA将其误判为可见并未真正进入编辑器。增加有限滚动、实时可见区域检查、导出状态识别及UIA/已核实窗口结构/唯一位图三级定位；未知弹窗停机。限定剪映5.9.0.11632及原EXE SHA256，保持既有Render队列、媒体校验及Yixiaoer/Publisher链。

原忍冬草稿仅做一次恢复导出；47.066667秒、1080×1920、30fps、H.264/AAC、60,397,904字节，ffprobe和全片解码通过。用户追加明确授权后仅回传这一个MP4，原RenderJob COMPLETED、原Content production_status READY；旧失败receipt和本地state均备份保留。SHA256为 `7d5b9e32301c3fd4e0847f99d69f2a75b435d46bcdd6042f6180b85efd9a40cb`。未创建新Content/RenderJob。恢复过程直接Publish调用0。

00:11验收时Worker IDLE、PROCESS/DRAFT/EXPORT_AUTOMATION及RenderCapability READY，6账号Preflight全部通过且enabled=0；证据 `startup_render/runtime/export_recovery_20261006/production_acceptance.json`。这是时间点快照，不能代表最终状态。00:13–00:14用户另行在8502确认开启4个账号，并在聊天明确要求保留现状。随后原后台增加12个ProviderJob、5次提交（44→49），原忍冬Content被排期；不能声称本轮全系统Publish零增量。没有撤销用户授权或改动平台排期。

随后旧QUEUED任务 `STARTUP-94affa8d-6268-4e22-adaf-58f81f8d4929`（夏禾起号10月6日-3）被原Worker领取，在最终导出前因鼠标“展开”提示被误判未知弹窗而HALT。已针对实测Qt tooltip类/样式/尺寸/非遮挡条件修复并部署，远端历史快照回放恢复为EXPORT_DIALOG；无成片、无最终导出闩锁。119项回归通过；最后视觉匹配和tooltip修正后的19项定向测试通过。后续夏禾任务未重试、Worker仍HALTED_NEEDS_MANUAL，追加的一次任务恢复请求等待用户确认；当前不能标记GO_LIVE_READY。详细实际状态 `startup_render/runtime/export_recovery_20261006/delivery_check.json`，原文件对账 `reconciliation_result.json`，测试 `final-tests.txt` / `final-focused-tests.txt`。

### 2026-10-06：PRODUCTION_AUTOPILOT_GO_LIVE_RECOVERY（进行中）

只读完整核对44个Provider任务及75条官方作品记录，修正2条已有公开作品状态，3条历史Provider矛盾保留原失败、不重发。六个账号修正历史异常为PAUSED/enabled=false；旧终态FAILED不再反复覆盖暂停。新增正式启动Preflight、账号卡每日七项本地进度及停止账号不领取渲染的保护。现有正式服务计划任务已加载修复；44提交闩锁、58Render身份、模板/背景/账号稳定映射保持原值。

2060S原停止原因是导出按钮未找到。用户已验证剪映5.9路径/签名/hash及两个共享；重启后同一Worker心跳已恢复，但仍HALTED_NEEDS_MANUAL，旧失败本地state会阻止领取。新版退出码/进程/失败state诊断输出尚未收到，维护领取仍暂停。没有启用账号，Render/Upload/Publish=0，六账号配置/已校验容量均通过但INFRA_BLOCKED，不能宣称GO_LIVE_READY。详情和下一步见`production_autopilot/GO_LIVE_RECOVERY.md`。

### 2026-10-06：PRODUCTION_AUTOPILOT_CONSOLIDATION

先输出Gap Audit，再增量收敛既有生产链；详细状态与恢复说明见`production_autopilot/GAP_AUDIT.md`及`production_autopilot/README.md`。新增统一异常中心、后台只读验证请求、严格Provider任务账号核验、统一新计划每日最多5条、未来补位谱系、错过时段的本地未提交任务保护、账号轮转与独立只读Metrics采集队列。原FAILED不重试，原SCHEDULED_QUEUED只读对账，不改参数；暂停/结束优先于恢复请求。

生产有效样本必须同时有公开作品、真实可用24h/72h指标和本账号Composition/Material IDs。未知/NULL快照允许补齐，迟到采集不当作精确窗口；SUBMITTED作品可由官方公开列表确认后进入Metrics。AccountVisualProfile与模板分开，背景共用，其余视觉样式字段预留NULL，继续沿用原生成器。

后台5分钟健康快照、6小时跨库本地备份及隔离恢复验证已接入原生产Worker；不会备份或修改32GB搜索数据库。队列支持配置未来多个独立Render Worker，上层仍沿用RenderQueue；当前正式并行度保持1。50账号fixture通过独立250条持久额度和重复规划幂等；此为架构测试，实际产能/多日连续运行须继续观察，不能宣称已完成真实250视频吞吐验收。

本轮初始实际状态：7个Registry抖音账号、6个正式背景绑定、6个托管账号因平台验证/作品查询/错过提前量进入ATTENTION_REQUIRED。用户后续已自行选择背景，保留这些选择；下方背景任务的NONE描述仅代表前次验收时的快照。

交付验收见`production_autopilot/ACCEPTANCE.md`：生产链部署回归及15项最终收敛专项通过，真实备份/隔离恢复6份授权与HOLD保护通过。8502热加载已修复，普通三模块浏览器可用；恢复旧备份后必须在高级管理核对平台历史才能解冻。真实只读复核仅补齐4个原NULL作品ID，原排期/身份/配置及44次提交闩锁不变，本轮新增Render/Publish均0。当前6个账号仍停用待处理，Render Worker OFFLINE；不能宣称多日无人值守与20条真实有效样本验收已完成。

### 2026-10-06：ACCOUNT_BACKGROUND_BINDING_READY

`account_visuals`新增独立AccountBackgroundBinding/BackgroundMaterialCatalog，按稳定business_account_id绑定、SHA256去重，SQLite迁移新增6张表并先备份。背景目录沿用`jianying_auto/config.json:bg_dir`，本机6个独立图片背景。用户明确要求正式账号保持未绑定，当前8个业务账号均NONE，没有按名字自动分配。

8502 AI托管的“账号设置 · 账号背景”提供缩略图、背景选择、铺满/完整显示/拉伸、必需背景开关；关闭弹窗取消未保存选择。人工自动起号默认继承，可本次覆盖；AI固定继承。普通页面/下拉只读本地编目，刷新按钮才扫描背景小目录。设置不改模板版本、StartupProfile、授权或Affinity。

原Adapter与ProductionWorker传递按业务ID冻结的视觉层；原剪映main在建新草稿前校验账号/hash，index0插入背景轨，0到全片。图片拉满，视频静音循环、最后段截断；只缩放背景，主体绿幕/裁切/位置及1080×1920保持。无绑定不随机使用别的背景；必需背景缺失阻止新生成。新草稿独立视觉层审计不携带UI缩略图/停用旧路径；原Render素材打包可承接图片和视频，无发布链改写。

87相关测试通过。两个隔离业务账号真实草稿分别使用9月20日.png/夏禾.png，5秒整片覆盖，未串号；视频7秒2+2+2+1循环和3种fit均通过。属草稿结构验收，没有剪映GUI实渲染。18项正式业务保护通过，新增真实Render/Publish=0。最新代码已载入8502和托管Worker，账号同步/发布Worker继续运行。报告和截图：`jianying_auto/runtime/account_background_20261006/REPORT.md`、`background_picker.png`；使用/迁移说明：`account_visuals/README.md`。

### 2026-10-06：8502_PRODUCTION_UIUX_V2_READY

8502现使用统一深蓝/青色Design System及真实三张模块导航卡。索引三个入口保留原查询模型和排名，结果卡、原片预览、状态与高级详情统一；竖图预览限高。自动起号约30/70配置与任务布局，目标账号先选、连续1～5段，1920×1080主按钮首屏可见，原登记/渲染/发布链不改。AI账号概览、时间轴、有效学习进度与四步设置向导接原ProductionStore；Slot复制/删/排序、跨日期未来5条预览、显式保存和最终开始确认均有真实交互。正式运行账号仍只读，丙曜保护保持。

普通模块/下拉使用原fragment，生成配置、上传图、各模式结果与模板Draft保持。普通目录快照hash_budget=0，不扫描/yxer；显式预览/保存保留完整校验。全量gc仅实际释放大模型后执行，保留RLock及非活跃索引释放。工程状态在齿轮高级管理，免登录不变，没有新增模型/Schema或重启正式服务。

109相关回归、37最终UI/编辑测试、14展示文件语法通过；17项业务保护检查通过。真实浏览器图/话术/描述分别2.53/9.43/1.19秒返回10条，并打开话术原片预览。TEMP夹具实际保存每日3条/目标2000、模板和3个时段，未写正式模板。三模块20切换中位307ms/最大418ms，索引二级20次299ms/最大318ms；没有逐渐变卡，但不能宣称全部<300ms。1920×1080、2560×1440及760宽适配实测；未做8小时人工疲劳或新的LAN视觉验收。

Plan12/Job274/provider36/Content46及Shadow、托管授权、分配、原提交锁保持，RenderQueue35个任务指纹不变，真实新增Render/Publish=0。后台正常账号核验/对账/心跳仍更新，原Worker26896 RUNNING/active1。完整14项交付及三张截图：startup_autopilot/runtime/uiux_v2_20261006/REPORT.md；保护证据DELIVERY_VERIFICATION.json。主脚本无file watcher时既有标签可能需刷新两次；新会话已验收最新版。

### 2026-10-06：8502_THREE_MODULE_UI_READY

最新正式UI为索引模块 / 视频生成模块 / AI托管模块，默认索引→图搜。免登录保持；原图搜DINO、话术Speech formal_v1、描述CLIP formal_v1与手动自动起号均恢复接线。手动生成使用原本地操作身份、ContentRegistration/2060S RenderQueue/READY池；AI托管继续原ProductionStore与用户确认模板，当前已运行账号设置只读。右上角齿轮→高级管理收纳账号、发布计划、Plan/Job/Provider/Worker心跳与POC记录，旧后端保留。普通路由fragment更新，未观察明显整页白屏。

真实浏览器三类查询分别4.04/13.03/1.50秒返回定位结果，账号切换、手动生成配置、托管设置/模板/运行/学习及高级管理均点击验证，未点击生成或最终开始/发布。8专项、55既有链路、42搜索生成回归、8语法通过，15数据保护检查通过。原Plan12/Job274/provider36/Content46及所有任务映射、排期、intent/count不变，丙曜22queued/6failed不动，真实新增Render/Publish=0。

连续加载正式大索引曾造成Windows提交内存不足1455，原托管于06:17:58进入ATTENTION_REQUIRED。增加模式切换释放非活跃搜索缓存、查询/释放RLock后工作集约11.3→1.17GB，按严格基线06:22:19恢复已有授权状态，原确认时间/config/模板/任务不改，保留故障与恢复审计。Worker原PID26896恢复RUNNING/active1，所有服务未重启。不是“全程服务无影响”。新的LAN标签DOM观察超时，LAN HTTP200；真实UI验证在localhost原用户页完成，不能冒称本轮新LAN视觉验收完成。详细报告startup_autopilot/runtime/three_module_20261006/REPORT.md。

### 2026-10-06：8502_SINGLE_STUDIO_AUTOPILOT_UI_READY

用户明确取消现阶段8502员工登录。startup_autopilot/single_studio.config.json开启SINGLE_STUDIO_MODE=true/AUTH_MODE=DISABLED；app主入口在任何登录逻辑之前直接进入起号托管。普通导航仅起号托管/历史记录/异常，无员工选择、登录名、密码、切换/退出登录。新的局域网浏览器会话http://192.168.1.126:8502已实测，首次缓存旧脚本需刷新一次后完全进入新主页面，脚本缓存已更新；截图runtime/single_studio_20261006/NO_LOGIN_STUDIO.png。

StudioPlannerStore使用进程内LocalOperator与固定LOCAL_OPERATOR/STUDIO_CONSOLE审计身份，不制造登录Session，不借用旧员工或Admin登录。004迁移仅增加studio_operator_identity以及employees中disabled、不可登录的STUDIO_CONSOLE兼容外键锚点，所有历史员工/Session/绑定行未改。旧绑定的STARTUP group_role只作为业务分类，不依赖员工是否启用/拥有权限；有效账号仍要求稳定身份、active账号/group。丙曜在下拉可读但禁止托管，不创建其Profile。ID只放高级详情；账号之间模板、Metrics、Affinity及composition历史保持独立。恢复认证可关闭显式开关，旧登录代码和数据仍在。

本轮开始前用户已于北京时间04:59:12开启新账号托管，模板Version2，今天09/12/15/18/21五条已经SCHEDULED_QUEUED/count1。保留原长期授权和旧confirmed_by真实历史，不自动暂停、不重新开始、不重POST；之后用户操作审计使用STUDIO_CONSOLE。正式Worker受控重载为PID26896（旧48996/48252退出），当前RUNNING/active1；8502、客户端、原Publisher、Render未重启。现有2060S Render/READY/Yixiaoer LOCAL仍复用；增加内容owner与provider claim可用性小钩子，普通登录路径保持原启用校验，托管领取在事务内重新验证长期授权。无登录不等于自动开托管。

12免登录专项（含隔离真实登记/RenderQueue/Plan/Job/MockCLI一次提交）、15既有托管、122模板/发布及80旧链回归通过，12文件语法通过。全部已有业务数Plan12/Job274/provider36/Content46不变；新账号5个原任务ID、排期、count/intent/hash不变，仅正常对账updated_at更新。丙曜旧28仍22queued/6failed/count28/映射hash不变；全Shadow/Profile/模板/Affinity/Metrics行不变。新增真实Render/Publish=0；DELIVERY_VERIFICATION.pass=true，quick_check ok/foreign_key_check空。当前收尾池1独立素材、ROTATING/7天上限7次仍有连续5/天容量限制，保留用户规则，需要用户自己调整，不静默放宽。完整报告runtime/single_studio_20261006/REPORT.md。

### 2026-10-06：STARTUP_AUTOPILOT_PRODUCTION_UI_READY（等待本人最终确认）

8502普通员工导航现为首页/起号托管/历史记录，Admin原功能保留。真实苏政超会话已验证账号下拉、开始托管向导、每日1～5条与北京时间、用户Slot模板编辑、目标与开始和最终确认按钮。最新账号YXER-DY-6ac3d908a54616c8efe04a46已有用户本人保存的四段Version1：引流→手法→手法→收尾。模板收尾目前1个独立素材、7天最多复用7次，连续5/天容量不足，UI明确提示；不自动修改用户模板。

新增production.py/production_worker.py/production_metrics.py/employee_ui.py和003增量迁移。正式pythonw任务STARTUP_AUTOPILOT_PRODUCTION_SERVER_01已部署，04:48只重载该新空闲服务以加载最终代码，PID48252；现有8502/蚁小二/Publisher/Render进程保留。真实长期授权0/分配0，Worker IDLE_AWAITING_USER_CONFIRM；未替用户点击确认，新账号仍SHADOW/COLD_START/enabled=false。最终用户点击后才会写长期授权，持久额度最多5/北京时间自然日，Composition→现有ContentRegistration→2060S Render→READY→原Plan/Job→原Yixiaoer LOCAL Adapter，保留隐藏CLI、hash/intent/count1与只读对账。

官方content-overviews连接器已接线：仅本账号匹配作品ID与真实非未来日期可计公开样本；2h/24h/72h记录观察时间及供应商数据新鲜度，不支持字段NULL。生产独立评分版本startup-production-policy-v1使用可得播放/互动指标，本账号baseline和slot/material独立权重，20样本前均衡探索，20后仅LEARNABLE消费权重。暂停/结束停止新生成与提交，不取消抖音已有排期。每日不足提前8100秒或14天以外拒绝，错误停派、不盲目重试。

156项回归、21项最后增量、14文件语法通过；真实浏览器确认页截图留存。原28仍22SCHEDULED_QUEUED/6FAILED/count28且映射hash、排期、业务记录数量不变，本轮真实Render/上传/publish0。审计总schema hash变化来自授权的新4表/2触发器；所有原schema对象逐项一致，DELIVERY_VERIFICATION.ready_without_user_enable=true。报告startup_autopilot/runtime/production_enable_20261006/REPORT.md。

### 2026-10-06：8502_STARTUP_UI_INTERACTION_PASS

真实苏政超8502会话复现“设置账号”仅展开已存在st.tabs而没有切tab；改为startup_autopilot_page稳定路由，紧凑账号卡右侧直接显示完整账号设置表单，下方视频模板/明日计划导航。外层导航fragment+内层编辑fragment避免8502其它tabs重跑；原两个Health折叠区域每轮仍各启动PowerShell，实测单次1.46～1.48s、合计约2.95s，为主要阻塞。素材元数据实际8.4ms，原10次下拉10次扫描；现在会话catalog TTL300s/Profile60s、Draft字段不扫描/不CLI/不Planner/不写版本，刷新/预览/保存才校验。无watcher/run_every。

账号观察设置保存在独立Shadow库并保持disabled，原Account/provider映射不动；每日数量/固定时段/学习阈值对Shadow生效。真实浏览器设置出现99.9～110.3ms；四段10次改动1696帧空白0/工作区root替换0，Draft跨页保留；另点1次未确认预览，版本0/receipt1，不冒充用户模板确认。107项回归与7语法通过；正式28仍22queued/6failed/count28和hash/排期/ID不变，Render/Upload/Publish新增0，原常驻进程保持。临时探针UI接线/启用文件已移除。报告startup_autopilot/runtime/ui_interaction_fix_20261006/REPORT.md。

### 2026-10-06：STARTUP_TEMPLATE_BUILDER_READY（用户定结构；当前未确认）

8502起号托管→设置账号→视频模板新增首次空白Slot向导，可增删、拖动/键盘/上下移，同类型HAND_1/HAND_2独立。每段显式类型/池/固定/轮换/AI/优先策略及独立疲劳；FIXED可以长期复用，完整有序媒体SHA组合默认30天去重，未把片段重复等同整视频重复。预览未来5条后保存不可变Version1，修改Version2；保存凭证绑定账号/actor/结构/所选池/30min/基准版本，始终Shadow、enabled=false。

新账号YXER-DY-6ac3d908a54616c8efe04a46旧自动默认被标UNCONFIRMED_DEFAULT，确认版本0/预览凭证0；没有替用户选择正式模板。真实catalog已登记：引流10/手法44/坐诊30/收尾1独立SHA素材。实际账号模板未选，真实容量UNKNOWN；仅隔离配置轮换+AI手法+轮换手法+固定尾验证5/天、35/7天、duplicate0，不能当用户模板。此前“单收尾只能1条”是旧统一疲劳示例，现被逐Slot策略替代。

62基础+39模板/界面案例、77既有相关回归通过；27模板复核/13UI增量/10JS断言/11语法通过。真实指标采集尚未接线，AI只在本账号LEARNABLE内选择，20前不消费强学习权重。101案例均隔离；本轮生产Render/Plan/Job/上传/publish0，原28条22queued/6failed/count及排期/ID/hash不变，所有常驻服务保持，无watcher或重启。生产浏览器视觉未验收，没有代用户保存。报告startup_autopilot/runtime/template_builder_20261006/REPORT.md。

### 2026-10-06：NEW_ACCOUNT_STARTUP_AUTOPILOT_SHADOW_READY（容量受限，真实托管禁用）

用户明确选择独立新建业务账号：`YXER-DY-6ac3d908a54616c8efe04a46`，昵称「引流+手法+手法+收尾」，官方provider `6ac3d908a54616c8efe04a46` ONLINE；分配苏政超已有STARTUP组339642，未关联旧3031801633454512。独立Profile SHADOW/COLD_START/enabled=false、daily5、sample0/20、目标NULL；8502发布管理新增「起号托管」观察页，复用稳定会话权限，只有查看建议/观察设置，没有真实派发。独立shadow_8502.db记录Profile与追加决策，operations.db只增加用户授权的新Account/binding/audit，原schema/任务不变。

固定引流→手法→坐诊→收尾、09/12/15/18/21；真实素材有限样本SHA验证。两个收尾文件同SHA仅1独立收尾，默认核心素材邻接禁止复用等疲劳规则不放宽：10/07～10/13七天合计1/35，明日09:00一条，其余缺口明确显示，不宣称5条/天可上线。丙曜及旧账号不加入Autopilot，不继承其它账号权重，真实Render/Plan/Job/蚁小二submit/上传0；原28仍22queued/6failed/count28及排期/ID/intent不变。正式常驻Worker正常只读核验时间/审计更新保留，不声称整库字节冻结。

专项69/69、入口AppTest、8语法通过；扩大回归528通过+14旧导入错误经补测198通过，1个旧小V猫历史AST断言仍失败且保留日志，未改旧Publisher或弱化测试。8502/客户端/Publisher/Render原进程及健康保持，无watcher/重启。浏览器视觉未验收；真实托管与指标采集仍未开放。连续1条/天Canary须先补独立素材/目标/真实接线与单独验收；不可自动发布。完整报告`startup_autopilot/runtime/new_account_shadow_20261006/REPORT.md`。


### 2026-10-06：STARTUP_AUTOPILOT_FOUNDATION_READY（仅Shadow，未生产接线）

独立新增`startup_autopilot/`：账号Profile/状态机/二次配置哈希授权、固定Slot模板、每天<=5条unique content的Shadow DailyPlanner、实际提交日预算（含POC/人工，官方额度UNKNOWN）、24h/7d/邻接核心/30d组合保护、账号内Metrics归一化与Bayesian Affinity、15张sap_新增表migration设计、离线交互UI原型。存储层只允许TEMP/isolated的*.fixture.db，生产路径拒绝；真实dispatch恒拒绝。沒有修改8502页面、自动Plan/Job事务、2060S、正式Publisher或注册每日调度；真实metrics collector和长期授权生产接线尚未实现。

57项基础隔离测试、424项既有回归、10Python语法通过；UI事件18项离线断言通过，浏览器file协议被安全策略拒绝，视觉验收未完成。合成Shadow5组合duplicate0/render0/publish0/submit0；实际生产库只读副本migration保持全部原表行不变。生产schema无sap_表，Plan7/Job269/providerJob31/Content41不变；原28条22queued/6failed、ID/排期/count/intent/hash/publish_once28均不变。10/07和10/08已有8条，新5条上限仅阻止新增不取消；6failed仍保守占位，不补发。

8502 HTTP200、Publisher原PID47988/48008及客户端6进程保持，Render LAN认证health200/2060S新鲜IDLE。下一步仅单账号daily_limit1、小素材池、8502账号配置与Shadow接线；再真实只读指标与独立单条验收，未授权现在开LIVE。完整交付/未实现边界/上线门：`startup_autopilot/REPORT.md`、`startup_autopilot/ARCHITECTURE.md`；原型`startup_autopilot/prototype.html`。本轮结束，不创建watcher。

### 2026-10-06：YIXIAOER_CLI_NO_WINDOW_FIX_PASS

正式Worker旧executor28736反复直接启动yxer.exe，pythonw无控制台但子CLI未配置隐藏；统一为`yixiaoer_adapter/cli_runner.py`的YixiaoerCliRunner：Windows CREATE_NO_WINDOW + STARTUPINFO/SW_HIDE、shell=false，管道/returncode/timeout/JSON解析不变，无重试。正式CLI1个低层入口覆盖11个业务调用，旧POC/诊断3个入口也统一；health/deployment两处PowerShell辅助进程经run_hidden。旧POC=0，Stage3心跳PAUSED，未改Task Scheduler的正式Action。

用户明确授权一次受控重载，00:35:26～00:35:29仅正式Worker旧29188/28736→新47988/48008；8502 30784/29992、蚁小二6进程、Render22276/20608不变。46项隔离回归、8语法检查通过；官方accounts5次、doctor及应用health各5次、独立纯测试validate/dry-run夹具通过，真实publish/upload=0。125.595秒WinEventHook+1997次窗口枚举，可见yxer窗口0；新Worker实际status日志证明无窗口策略生效。

正式28条仍22 SCHEDULED_QUEUED/6 FAILED，排期/ID/count/intent与POC闩锁SHA均不变；正式publish_once仍28份，本轮增加0。未重试失败、未改provider任务。证据与完整报告：`publisher_poc/yixiaoer/cli_no_window_fix_20261006/REPORT.md`。观察脚本已退出，完成后停止；后续正式服务继续按原逻辑运行。

### 2026-10-05 23:20：YIXIAOER_8502_PRODUCTION_CANARY_PASS / YIXIAOER_PRODUCTION_BATCH_28_READY

用户已本人8502 Confirm3条灰度，正式Adapter执行一次/条；三个原Job均success/scheduled、SCHEDULED_QUEUED/count1，唯一taskSet/task/workID。用户确认三条均在抖音待发布区域，追加人工外部证据，不标PUBLISHED。作品ID7693195300579724590 / 7693195363921972514 / 7693195462240750883，完整Job/task映射在`publisher_poc/yixiaoer/production_batch_28/CANARY_FINAL.json`。

主Publisher=yixiaoer LOCAL，服务器YIXIAOER-PUBLISH-WORKER-SERVER-01；Xiaovcat LEGACY/DISABLED，2060S继续Render。增量生产Preview/不可变Confirm授权表，worker模式CONFIRMED_PRODUCTION，但当前worker_enabled=false/allowlist空。只能消费真实新Confirm生成的授权，不能采用历史CONFIRMED Job。未知submit只读对账，结果未明确暂停后续POST；每Job永久count≤1。公开证据才PUBLISHED。

恢复原28条发现旧Plan740d22f4-5eb0-455e-b5fb-e14e4c0a5180实际29Job仍占用。首条归档PRE_SUBMIT_CHECK确认submit_attemptedfalse/final_submit_invocations0并在提交前BLOCKED；所选其它均未claim。经旧TaskDisabled/进程0、事务内无intent/提交事件/作品验证，仅原28条Job撤占用为CANCELLED，ID/claim/排期/旧事件保留并追加审计；旧PlanPARTIALLY_CANCELLED，额外第29条继续留在禁用旧队列，不纳入新28。没有清除消耗过的闩锁或重试旧任务。

新生产Preview ID`YIXIAOER-PRODUCTION-320f095f-a5c4-45b7-a8e2-1e5515407c86`，仅准备表/本地文件，没有正式Plan/28Job。28原content顺序、3h、09:00首发、daily20上限、跨日逻辑保留，5/8/8/7，最早2026-10-06 09:00，最晚10-09 18:00，unique28/duplicate0/collision0。当前仍合法未顺延；过期准备会整体顺延，Confirm/claim再检2h15m～14d。既有DEFAULT封面在本地准备并SHA冻结，原空标题/简介依官方schema省略可选字段，无话题，未上传业务素材。

准确入口：正常登录**苏政超/suzhengchao → 工作区：发布管理 → 蚁小二正式生产 → 28行Preview、每日分布、首尾时间下方蓝色“确认发布计划”**。点击一次才创建新1Plan/28Job并启动服务器Worker。“发布计划”也支持原28条同ID恢复；旧29条浏览器选择请用专用正式生产标签。未操作用户浏览器/代Confirm。

418项隔离覆盖通过（415完整+2正常Planner接线+1未知结果保护），26恢复专项也通过，19Python语法通过。全库仍Plan6/Job241/providerJob3，provider submit总3均来自用户已确认灰度，本轮新增publish/upload0；DB完整性ok。服务器旧发布Disabled/新TaskReady，2060S23:16旧PublishDisabled/RenderRunning，Render/Jianying/SMB不变。完整报告`publisher_poc/yixiaoer/production_batch_28/REPORT.md`。停止等待本人Confirm。

### 2026-10-05 22:35：YIXIAOER_8502_INTEGRATION_READY（3条仅Preview；提交0）

正式`yixiaoer_adapter/`已增量接入8502 StartupPipeline/PlanBoundary/PublishPlan/PublishJob，官方CLI LOCAL、稳定账号映射、追加审计、先持久化intent/count=1再publish最多一次、未知结果只读对账。success/scheduled有作品ID仅为SCHEDULED_QUEUED，公开证据才PUBLISHED。新provider表迁移前备份，原37表历史行完整字段一致；实际本轮基线Plan5/Job238保持，新增正式Plan/Job/providerJob/submit全0。没有消费原28条或既有业务Job。

用户最新要求停在READY，等本人8502 Confirm。3条新生成8秒纯测试视频和封面已准备，业务丙曜1621131832863931→蚁小二6ac389eb46f95bf847d47da1。Preview ID `YIXIAOER-CANARY-cbcadaf7-cafe-40fe-8599-dddd68379227`，2026-10-06北京时间02:25/02:40/02:55，unique3/重复0/碰撞0。仅独立准备记录，不是正式Plan；当前无Job/task/作品ID。最早安全Confirm截止00:10，不自动改时间绕过2h15m Gate。

准确入口：正常登录**苏政超/suzhengchao → 工作区：发布管理 → 蚁小二灰度验收 → 三行Preview及计数下方蓝色“确认发布计划”**。无需重新选素材。该按钮Confirm后原子创建1Plan/3Job，启动新服务器Worker，只允许此灰度ID；重复Confirm禁用。账号缓存有效30分钟，过期须专用只读刷新，绝不伪造在线。入口通过源码和隔离AppTest验证，没有操作用户生产浏览器。

YIXIAOER-PUBLISH-WORKER-SERVER-01当前worker_enabled=false/allowlist空；Administrator Interactive登录任务已注册，客户端6进程Session1。8502加载新模块后PID29992/health200。旧Server/2060S Xiaovcat发布Task Disabled/代码历史保留，Render/Jianying/SMB不变。Windows整机启动恢复、自动登录、长期扫码频率UNKNOWN，未重启整机。账号API成功与LOCAL_EXECUTOR_LAST_CONFIRMED历史证明分开展示，实时executor UNKNOWN。

399项覆盖通过：Adapter21/Planner76/Startup248/Render54；聚合382通过+修正导入路径后16补测+新增状态分类1，原失败日志保留；20Python语法通过。真实官方归档B2 dry-run经正式Adapter requestHash核验通过，未再调用CLI。当前仅单challenge且必须提供封面；原业务模板需后续另验。报告`publisher_poc/yixiaoer/adapter_integration/REPORT.md`与FINAL_VERIFICATION.json；**READY不是真实灰度PASS，原28条仍不开放**。

### 2026-10-05 17:10：8502_CONFIRM_PLAN_READY（原28条仅Preview；只读预检通过）

实际8502 PID13360于10/04 21:43启动，使用`.venv-cuda-test/Scripts/pythonw.exe`，`--server.fileWatcherType none`；晚于启动的Planner修复不能自动替换已导入模块。已证实当前源码/真实数据库所有后端硬门通过，但旧常驻进程存在发布模块加载断点。用户浏览器访问被通道策略拒绝后停止浏览器操作，未绕过读取浏览器或Session内存；**没有直接取得原浏览器唯一错误码/隐藏flag，不把推断当目视结果**。

仅8502入口增加定向发布模块版本检查：后续rerun按依赖顺序加载已变更发布模块，不碰搜索模型、Render或发布Worker。进一步检查已安装Streamlit ScriptCache真实源码确认其主入口字节码缓存也不会因普通刷新清除，因此17:09:30只重载8502原服务（旧launcher24252/listener13360→新launcher20656/listener19092），同解释器/参数/端口，health200。不停止/重启发布Worker。登录后按原员工身份自动恢复既有28条Preview选择，无需重选；不发新登录授权，若浏览器会话已失效仍须正常登录。恢复原Preview始终固定原plan_id，修复旧恢复标记已存在但ID仍指向cancelled Plan的残留问题；原28条参数锁定，账号刷新只重算资格，不改变选择、排期或签名。按钮显示`不能确认：具体原因`并可展开只读硬门；快照过期仍禁止确认，复用原刷新入口，安全不放宽。

新增`startup_pipeline.confirm_preflight`只读检查，复用原权限/排期/媒体规则，无新会话/迁移/claim/Confirm/UI调用。17:09:50在实际8502 Python环境执行原保存Preview：eligible=true，blocking_reason=null，28 READY/NOT_SCHEDULED，无活跃占用/提交历史/submit intent，snapshot 16:41:56真实同步、丙曜在线，30分钟有效至17:11:56。Worker ONLINE/IDLE、heartbeat新鲜；旧Job3 CANCELLED、不影响当前28条。账号以后过期仍须原“刷新发布账号”，不伪造时间或在线状态。

原Preview ID15f28b9d-cd44-4ff1-bd6c-e5091e07a430/文件SHA c8ccf0d2e0271c31e926ef20186271488d7ade1a86fc10fe29876b90fb948d3b不变，28 unique/重复0/碰撞0，10/06=5、10/07=8、10/08=8、10/09=7。预计用户Confirm仅1正式Plan/28Job；本轮实际新增0/0、提交0，全库仍Plan4/Job209、错误200Job仍CANCELLED、旧Job1/2/3完整哈希不变。

服务器Task Enabled/Running、Administrator Interactive Session1、PID27908单实例，XIAOVCAT-WORKER-SERVER-01 ONLINE/IDLE/current=null/globalfalse/armedfalse；2060S维护只读核验发布Task Disabled/进程0。共12个新增隔离测试，263/263相关回归通过（146.311秒），随后部署恢复修改28/28专项通过（18.748秒），另有先行37项通过；7Python语法通过。真实Streamlit AppTest验证“旧标记+取消ID+过期快照→明确拒绝→刷新后Confirm enabled”，隔离测试验证部署后只能给已登录原员工恢复既有选择；没有点击生产Confirm。**实际浏览器视觉状态未验收，用户刷新8502，必要时正常登录；不需重选28条**。证据与完整硬门在`startup_pipeline/runtime/confirm_eligibility_20261005/REPORT.md`、FINAL_PREFLIGHT.json、FINAL_INTEGRITY.json、REGRESSION.log、DEPLOYMENT_RECOVERY_TESTS.log。未重建28条Preview、未创建Plan/Job、未操作小V猫、未修改Render/Worker链。完成后停止。

### 2026-10-05：SERVER_AUTO_PUBLISH_PRODUCTION_READY（用户Confirm授权，28条仍仅Preview）

服务器常驻发布改为CONFIRMED_PRODUCTION；8502确认事务即正式授权并原子入队，取消额外派发checkbox/CMD/手工武装依赖。只接受CONFIRMED且真实confirm审计时间>=2026-10-05T07:47:00+00:00的计划；旧acceptance gate不再约束正式生产，历史任务不自动扫入。整Plan唯一内容/账号时间硬门在claim事务再验证；原账号授权/在线新鲜snapshot/永久绑定/媒体SHA/固定排期检查不放宽。

空闲磁盘dry=true/armed=false/globalfalse；原UIA准备和fresh readback后，原reserve持久化提交意图，再由当前Job回调短暂开启内存提交权限，唯一Invoke后finally立即关闭；保留原控件逻辑。reserve事务同时拒绝SUBMIT_INTENT，进程重启不重复提交；未知/失败持久化HALTED_NEEDS_MANUAL后安全停止真实动作，仅心跳，不自动继续其它Job。成功只能SUBMITTED/SCHEDULED_QUEUED，不提前PUBLISHED。现有UI能力仍限已验证丙曜/抖音账号。

Task XUNZHEN_XIAOVCAT_PUBLISH_WORKER_SERVER Enabled/Running，Administrator Interactive Session1，唯一executor XIAOVCAT-WORKER-SERVER-01，PID27908仅1实例；连续heartbeat ONLINE/IDLE/current_job_id=null/两开关false。2060S发布Task仍Disabled、发布进程0；Render/剪映/SMB不变。8502原服务0.0.0.0:8502、health200、PID13360，不停服。

正确Preview ID15f28b9d-cd44-4ff1-bd6c-e5091e07a430仍28/unique28/重复0/碰撞0，10/06=5、10/07=8、10/08=8、10/09=7，文件SHA不变；无对应正式Plan。全库Plan4/Job209仍不变，错误200Job仍CANCELLED，28Content READY/NOT_SCHEDULED；旧Job1/2/3完整记录哈希不变。**本轮不确认28Plan、不创建正式任务、不操作小V猫、不真实发布。**用户在8502刷新发布账号（如过期）后确认一次，Resident自动发现串行执行，不再需要Codex逐条参与。

新增14个正式生产fixture测试；252/252相关回归PASS，最终reserve硬门64/64专项PASS；11文件语法检查PASS。第一次回归1条旧UI文案断言失败已修正，历史日志保留。完整机器/fixture证据与报告：xiaovcat_adapter/runtime/server_publish_worker/production_ready_20261005/REPORT.md、BEFORE.json、PRE_ENABLE.json、AFTER.json、REGRESSION.log、SUBMIT_GUARD_REGRESSION.log。此结论是生产接线READY，**不是28条已经发布成功**。


### 2026-10-05 15:26：PUBLISH_PLANNER_UNIQUE_CONTENT_FIX_READY（错误200任务已取消；28条仅Preview）

用户明确“同一个视频绝对不得重复发布”，并授权整体取消错误Plan99b93466-4223-4417-8d36-8ab69a2378e8。先通过6项整Plan取消隔离测试，再只读复核worker_enabled=false/globalfalse/armedfalse及全体未claim/attempt0。15:07:26北京时间调用ProductionDispatcher.cancel_unsubmitted_plan，同一BEGIN IMMEDIATE事务校验expected200个Job全部范围/状态/无claim及执行事件/无SUBMIT_INTENT或reserve/无作品映射后，Plan及200个Job全部CANCELLED；reason=INVALID_DUPLICATE_SCHEDULE_GENERATION、by=USER、原payload/排期/metadata/items均保留。审计以现有error_code/error_message JSON及每Job PLAN_CANCELLED事件保存，不增Schema、不删除记录。dispatch合法终态BLOCKED/JOB_CANCELLED。原库备份operations.db.duplicate-plan-cancel-20261005_150726.bak，quick_check=ok。

28条Content全数production READY/publish NOT_SCHEDULED，原错误reservation已释放；全库仍Plan4/Job209，没有替代正式任务。旧Job1/2仍SCHEDULED_QUEUED各attempt1，旧Job3仍CANCELLED/attempt0；三者完整Job/content/events哈希前后一致。Server/2060S原claim入口对错误Plan首末样本均JOB_CANCELLED，discover亦因Plan取消排除全200条。没有UI动作或真实提交。

仅STARTUP排期增量修复：独立消费去重素材，不再video_paths取模循环；daily_count是上限，耗尽即停，end_date是最晚日期。自然合法槽限制有效数量，跨天维护每账号最早下一时刻/实际日期计数/已占用槽；已存在有效排期占用时跳过并寻找后续合法槽。容量不足明确SCHEDULE_CAPACITY_TOO_SMALL_FOR_SELECTED_CONTENT，不静默漏素材。ALLOW_REPEAT_CONTENT固定false。Preview映射、写入前、存储模拟Promote、幂等Confirm均硬验素材唯一与时间唯一，DUPLICATE_CONTENT_SCHEDULE_BLOCKED / ACCOUNT_TIME_COLLISION_BLOCKED。COMMERCE旧排期行为保留。

取消历史不再阻塞content重新选择/确认或生产_context，但其它有效Job/作品/submit-once检查仍保留。新合法schedule_signature加入plan_id，避免旧取消索引挡住相同时间的合法新Preview，不删除旧签名或审计。账号快照/授权/绑定等正式Confirm安全条件未放宽。

原28条选择与原日期10/06～10/15、09:00首发、3h、daily_count20、allow_cross_day=true构建新纯Preview ID15f28b9d-cd44-4ff1-bd6c-e5091e07a430。28 unique、预计28、重复0、时间冲突0；按实际日分布10/06=5、10/07=8、10/08=8、10/09=7，预计10/09 18:00完成后立即停止。保留09:00所以首日只有5个自然槽；没有改成00:00来凑示例。00:00首发daily8的夹具确实8/8/8/4。

Preview只存startup_pipeline/runtime/recovery_previews/99b93466-4223-4417-8d36-8ab69a2378e8.json，数据库无新Preview Plan、无新Job。8502在同员工/同28条选择下可自动加载原参数与新Preview身份，避免session里旧Cancelled Plan复活；显示选择数/预计数/重复数/冲突数/结束日/每日分布。快照过期允许经现有generation资格及内容归属/绑定/媒体检查计算只读排期，但不发确认receipt且Confirm disabled；正式Confirm仍在线严格验证。真实Streamlit AppTest已覆盖恢复旧cancelled session、显示新Preview、未确认/未写任务；不冒称用户当前浏览器已目视验收。8502 health200，无服务重启。

最终191/191相关隔离回归实际PASS（105.422秒），含新增10个纯唯一排期测试+12个整Plan取消/历史释放/只读恢复/确认硬门测试；16个Python py_compile PASS。首轮126项因2个旧语义错误码断言失败，中间175项因测试路径导入及旧重复数量/UI文案断言失败；修复运行路径和与新规则一致的明确断言后最终通过，不伪造失败轮结果。没有新测试框架，没有生产发布测试。

Server Task Running、Administrator Session1/PID28080单实例，heartbeat连续/current=null；仍为未武装观察，业务heartbeat DISABLED、worker_enabled=false/dry=true/armedfalse/globalfalse，不能称正式executor已放开。2060S Publish Task仍Disabled/进程0。未修改Render/Jianying/SMB/小V猫控件或Worker核心。详细28行排期表、取消审计及最终证明在xiaovcat_adapter/runtime/server_publish_worker/unique_content_fix_20261005/REPORT.md、CANCELLATION.json、FINAL_VERIFICATION.json。等待用户查看正确28条Preview后再确认，本轮停止。

### 2026-10-05 14:05：服务器Publish恢复诊断，常驻观察进程已恢复；正式消费仍阻塞

用户的新正式Plan `99b93466-4223-4417-8d36-8ab69a2378e8` 已在13:48:50北京时间创建并CONFIRMED，200个既有Job全部NEEDS_MANUAL/STARTUP_CONFIRMED_NOT_DISPATCHED、dispatch QUEUED、attempt0、无claim/提交事件。28个不同content各被轮转安排7～8次，另有76组相同account_id/scheduled_at重叠。只读原ProductionDispatcher._context核验首Job `c5e22bee-2af3-42dd-a3a8-90a86a14667e` 实际返回ALREADY_SUBMITTED_OR_RESERVED_NO_RETRY，非8502未创建任务；不得把此状态伪造成已领取。

真实无反应原因有三层：服务器Task原Disabled且从未运行；server_ui_worker.config.json仍worker_enabled=false、仅允许已取消旧Job3；旧全量开关要求原Batch3全部提交成功，与Job3正式取消冲突。新Plan还不符合现有content防重复执行约束。源排期preview以video_paths取模轮转，参数每天20条/180分钟/跨日/10月6～15日形成200条，单日序列跨到后天与下一日首发重叠。未改排期算法、原计划、Job、安全闩锁或验收条件，未自行删除/取消多余Job，需先明确重复发布规则/计划处置授权。

核验server配置worker_enabled=false/dry=true/armed=false、globalfalse、进程0且无STOP_WORKER后，Enable+Start既有XUNZHEN_XIAOVCAT_PUBLISH_WORKER_SERVER，仅启动原禁用执行配置的观察分支，不运行UI/claim/同步/提交。14:03:01 PID28080，Administrator/Session1，Task Running/Enabled、单实例；heartbeat14:03:26/14:03:51/14:04:41连续，status DISABLED/current=null。**观察进程在线不等于正式executor ONLINE，不返回SERVER_PUBLISH_QUEUE_RESUMED。** 2060S Publish仍Disabled/进程0；Render未动。

8502 STARTUP Planner增加只读Publish Worker ONLINE/OFFLINE、worker_id、last_heartbeat提示；检查配置启用、新鲜心跳、PID存活、身份和会话，未启用观察进程仍显示执行OFFLINE。Confirm前明确“发布Worker离线，计划可以保存，但暂不会执行”；移除旧“等待Job3验收”用户提示，不改账号/Planner事务。原Streamlit无需重启，8502 health200；隔离页面测试通过，未冒称在用户当前浏览器实测刷新。电脑使用技能仅受支持sky只读观察当前小V猫账号页/丙曜创作者中心，未点击、填表或调用UIA Worker旁路；可见稳定账号tab ID1621131832863931，无登录挑战，不据此伪造数据库在线快照刷新。

61/61必要隔离回归通过（39.097秒）：健康5、READY页面10、取消10、production dispatch23、server resident13；4个修改/新增Python AST语法检查PASS。业务库BEFORE/AFTER所有200个Job字段、旧Job1/2/3的Job/content/events哈希及全库Plan4/Job209均完全一致；本轮新增Plan/Job/claim/submit=0，旧三条仍提交1/1/0、Job3 CANCELLED。globalfalse/armedfalse保持。证据和每个Job的实际状态在`xiaovcat_adapter/runtime/server_publish_worker/queue_recovery_20261005/BEFORE.json`、`AFTER.json`及REPORT.md。已询问200条是否确实重复发布，未取得新语义授权前保留现场停止正式消费；未放开历史队列。

### 2026-10-05 13:28：JOB3_CANCELLED_CLEANLY（正式取消收口完成）

用户本人已明确只读核验小V猫任务记录无“丙曜/丙曜起号10月4日-6.mp4/抖音/15:00”对应任务。证据来源USER_MANUAL_XIAOVCAT_CONFIRMATION，记录时间不是虚构机器UI观察时间。本轮不打开/操作小V猫，不提交或重新生成。两端Publish Task仍Disabled、发布进程0、globalfalse/armedfalse；2060S Render Task仍Running，未改Render、8502或其它生产链。

取得既有single_instance文件锁+原Windows GUI互斥后，先再次核对attempt0/无SUBMIT_INTENT/Job1及Job2各attempt1且SCHEDULED_QUEUED。原operations.db通过SQLite backup备份为`D:\video_search_tool\operations.db.job3-user-cancel-20261005_132856_552558.bak`，quick_check=ok，然后调用既有ProductionDispatcher.cancel_unsubmitted_job正式服务，BEGIN IMMEDIATE同事务收口。没有裸SQL手工改状态、没有新Schema/Plan/Job。

原Job3 af6c16d3→CANCELLED，cancel_reason=SCHEDULE_WINDOW_EXPIRED_USER_CANCELLED、cancelled_by=USER、cancelled_at=2026-10-05T05:28:56+00:00（北京时间13:28:56），原2026-10-05T15:00:00+08:00未改。submit_attempt_count仍0、SUBMIT_INTENT仍0；原12:31 claim/PREPARING两条审计和话题失败原因均保留在历史与取消审计，claim/context身份前后相等。dispatch既有CHECK不含CANCELLED，使用BLOCKED/error_code=JOB_CANCELLED合法终态，不删除或伪造旧领取历史。

content STARTUP-a16c1f3b...保持生产READY，publish_status SCHEDULED→NOT_SCHEDULED，无其它有效Job占用；原ready_candidates真实只读验证可重新进入选择列表（文件/已登记ffprobe/大小mtime均符合），未建替代计划。原Plan52e11ba8→PARTIALLY_COMPLETED，表示两条已提交、一条取消，不取消Job1/2整个计划。Job1/2完整Job、content与state_events前后逐字段完全一致，仍各SCHEDULED_QUEUED/提交1次；不提前标PUBLISHED。

真实业务库反例验证：共同_claim_in_transaction分别以Server/2060S Worker身份调用，均JOB_CANCELLED，事务回滚无写入；服务器正式discover无Job3；实际LAN Repository.handle('/publish/claim')亦在context检查时JOB_CANCELLED、未创建能力/claim。这是拒绝调用验证，不是发布动作。两端原Job3 cmd实际误运行测试均JOB_CANCELLED/exit20，原PS/Python用户一次入口仍永久拒绝，不恢复武装或Task。全库Plan3/PublishJob9保持、新任务/提交0。

本轮相关108/108回归实际通过（40.048秒），含取消/正式派发/服务器/旧NO-SUBMIT/LAN/旧Job3入口；5个相关Python语法PASS。首次直接运行隔离审计脚本因sys.path不含项目根报ModuleNotFoundError，发生在任何备份/数据库动作之前；从项目根runpy调用正式服务成功，不伪造首轮成功。没有更改核心逻辑。本轮最终报告与审计在`xiaovcat_adapter/runtime/server_publish_worker/job3_cancellation/`：USER_NO_TASK_CONFIRMATION.json、CANCELLATION_AUDIT.json、RESULT.json、FINAL_VERIFICATION.json。server REPORT与入口说明已更新。完成后停止，禁止补发或恢复Job3。

### 2026-10-05：Job3用户取消安全停机完成，正式取消待唯一任务记录负证据

用户明确撤销原Job3 af6c16d3全部提交授权，不补发/重排/创建替代Job。只读发现用户已于12:31运行原真实入口：PRODUCTION_ATOMIC_CLAIM及PREPARING各一条，12:31:14因EXISTING_TOPIC_PROFILE_MISMATCH_NO_UNVERIFIED_OVERWRITE失败；不是之前10:38仍未claim状态。submit_attempt_count=0、无SUBMIT_INTENT/RESERVE/LOCAL_SUBMIT_RETURNED、PRE_SUBMIT_CHECK submit_attempted=false/final_invocations0；保留失败文件和两条审计。当前Job3 NEEDS_MANUAL/BLOCKED、dispatch BLOCKED、content production READY/publish SCHEDULED，原15:00不变。没有把这些证明冒称已检查小V猫任务不存在。

按computer-use技能，仅受支持sky打开现有小V猫并读首页；导航一键发布tab（不是分发按钮）失败coordinate input geometry is unavailable，重新选窗口/激活/观察一次报FrameArrived timed out，随后停止桌面输入。未进入任务记录，因此缺少小V猫对应任务不存在的负证据。已通过异步问题请求用户只读确认丙曜/-6.mp4/15:00/抖音没有对应任务。本轮没有执行正式取消事务、没有伪造CANCELLED/Content释放/Plan部分完成。不能返回JOB3_CANCELLED_CLEANLY，当前唯一阻塞是该项负证据。

立即禁用服务器REAL_ONCE.cmd、ACCEPTANCE.cmd、旧START_XIAOVCAT_JOB3_ACCEPTANCE.cmd及两个PS/固定Pythonmain；入口直接JOB_CANCELLED/exit20（旧文件.backup保留）。2060S两个Job3 cmd、根Python显式用户一次模式、lan_publish_worker CLI显式用户一次模式已备份并安全拒绝；未来误运行不进入UI/claim。两端实际cmd/root拒绝测试均JOB_CANCELLED/exit20。服务器两个Publish Task及2060S Publish Task Disabled，发布进程两端0，磁盘globalfalse/armedfalse；2060S Render Task仍Running，未改Render。现有Job3 dispatch BLOCKED已拒绝claim，本轮未重置历史claim/context。

最小正式服务ProductionDispatcher.cancel_unsubmitted_job已增加，仅在经确认的唯一无任务证据+count0+无intent/成功/活跃执行时同一事务取消。取消reason/time/by存原state_events和Job error_message JSON，不新增schema；cancelled_by USER、reason SCHEDULE_WINDOW_EXPIRED_USER_CANCELLED、scheduled_at不变。job CANCELLED、既有dispatch CHECK用BLOCKED+JOB_CANCELLED等价终态、无其它占用时content READY/NOT_SCHEDULED、保留两条成功时plan PARTIALLY_COMPLETED。共同_context/claim/block拒绝已取消Job，新增PublishStatus.CANCELLED可正常读取。不删除旧元数据/审计，不新增任务。该服务目前仅在隔离夹具验证，未应用生产。

108/108相关隔离回归通过：取消/正式派发/服务器/原NO-SUBMIT65项（31.928秒）+LAN/旧Job3入口43项（8.097秒）；7Python语法PASS。原cmd字节保留测试已按本轮用户撤销改为拒绝stub测试，原备份仍留存。Job1/2仍SCHEDULED_QUEUED、各提交1次；Job3提交0，全库Plan3/Job9未变化，本轮新提交0。待用户确认无对应小V猫任务后，取得既有互斥、SQLite备份、调用正式cancel服务，再做生产只读最终核验；不得重启或提交。

### 2026-10-05 10:38：SERVER_JOB3_REAL_ONCE_LAUNCHER_READY，仅准备，未执行真实入口

按本次明确授权保留`START_SERVER_XIAOVCAT_JOB3_ACCEPTANCE.cmd`及其NO-SUBMIT用途，SHA256仍EF7CBDC0E165974467F15B563B456B08E8C59BC8D87AA1028FD34FDCD1EF20D7。另建ASCII-only/无BOM/CRLF的`START_SERVER_XIAOVCAT_JOB3_REAL_ONCE.cmd`→绝对PS包装器→固定`xiaovcat_adapter.server_job3_real_once`；没有通用Job/Plan/排期参数。PS为UTF8 BOM/CRLF以支持PS5.1中的中文绝对路径，Python解释器固定绝对路径并与原config核验。

新增入口层只读precheck：次数0优先检查、原Plan/Job/content/account/完整路径/原SHA/空标题/简介/3话题全部锁定，确认未claim、正式CONFIRMED/非成功状态、SID末尾500且Administrator、同一交互Session、exe存在、原15:00距执行>2小时。先PRECHECK再原single_instance互斥；互斥内复核、仅快照过期时复用原单组refresh_snapshot一次，然后严格_context必须通过才交给原PublishWorker。配置和代码均排除Job1/2，不写acceptance scope，不新建Plan/Job。attempt>=1明确POST_SUBMIT_RECONCILIATION_REQUIRED_NO_RETRY；重开入口不能重提。

UI、fresh readback、原reserve_once先提交数据库再唯一Invoke、finally撤销和只读任务唯一核验均未改写。保持既有安全合同：磁盘real_publish_enabled=false和real_submit_armed=false始终不变；不是把共享配置置true而放开整个队列。准备动作使用原单Job进程内执行授权，真正提交许可enabled_for_this_job仅在持久化reserve之后的最小窗口内true，原finally立即false。成功须唯一已同步后SUBMITTED/SCHEDULED_QUEUED，不提前PUBLISHED。

31/31隔离回归通过（12新入口保护+13Server+6NO-SUBMIT，9.527秒），PS仅Parse通过、新cmd格式和旧cmd字节不变通过。10:38只读实际核验7路径全True，新cmd Test-Path=True；原视频SHA一致、Administrator/小V猫Session1存在，Job3 QUEUED/未claim/attempt0，快照过期已明确留待用户运行时自动刷新，没有现在调用同步/UI/Worker。Job1/2 SCHEDULED_QUEUED/各attempt1保持，全库3Plan/9Job保持；新Plan/Job/提交0，globalfalse/armedfalse。Codex没有执行新cmd或真实main、没有启动Task/小V猫、没有生产提交。用户可在服务器PowerShell运行新REAL_ONCE.cmd；固定排期不重算，13:00及之后拒绝15:00。日志仍server_publish_worker/worker.log及jobs/af6c16d3...，新入口结果JOB3_REAL_ONCE_RESULT.json仅用户实际执行后产生，当前不伪造该结果。

### 2026-10-05：Job3启动器ASCII修复完成，仅NO-SUBMIT预检，不再授权真实运行

用户报告.cmd乱码`'紝2026-10-05' 不是内部或外部命令`及路径错误，明确禁止再次真实执行。开始前只读确认原Job3 af6c16d3的V04_FINAL_SUBMIT_RESERVED计数0/globalfalse；进一步确认仍NEEDS_MANUAL/STARTUP_CONFIRMED_NOT_DISPATCHED、dispatchQUEUED、claimed_at=null、Job3 state_events0。没有把count0误称真实Worker已执行。

原cmd实测UTF8无BOM、LF、中文echo；目标项目/Python/PS/script/DB/MP4均真实存在。替换为ASCII-only无BOM/CRLF包装器，移除中文/chcp/相对路径/暂停，固定D:\video_search_tool工作目录与绝对powershell.exe/脚本路径。PS包装器改为UTF8 BOM/CRLF（兼容真实Windows PowerShell5.1），逐项Test-Path，Python路径仍读原config的绝对路径并核验。**当前cmd硬编码-NoSubmitPreflight，PS漏参数拒绝；不会运行真实Job3。此前让用户运行该cmd提交的说明已失效，等待未来另一次明确授权。**

仅在server_resident的CLI启动层增加互斥--launcher-preflight-only，进入专用纯文件/SQLite只读探针后立即return，位于Worker创建/会话UI观察/快照刷新/claim/真实执行之前；不改Worker/Publisher/闩锁/Planner/Render/配置/排期。模式与--user-job3-once不能同时使用。只读库mode=ro/query_only，before/after Job3与开关配置一致，显式closing关闭连接。

从C:\Windows工作目录实际执行修复后的cmd，10:15:59目标Python真实进入server_resident.main:NO_SUBMIT，cwd正确D:\video_search_tool，退出码0，NO_SUBMIT_LAUNCHER_PREFLIGHT_PASS。7项PowerShell Test-Path全True：项目目录、powershell.exe、PS包装器、实际Python、server_resident.py、operations.db、原-6 MP4；非假设路径。提交前后0→0，Job3审计0→0，SQLite total_changes0，未创建Worker/调用UI/同步/claim/reserve/submit。仅写独立诊断证据，不覆盖LAST_CYCLE/旧提交记录。最终globalfalse/armedfalse；没有执行真实入口、启动Task、小V猫或用户第二次真实运行。

新增6项启动器隔离测试+原Server专项13项，最终19/19（9.207秒）通过；3个Python语法PASS、PS语法PASS、cmd ASCII/无BOM/CRLF字节复核PASS。首轮6项在清理临时SQLite时WinError32（连接上下文不自动close），改为显式closing后全通过；生产预检并无业务写入。本轮未重新跑539项，不冒称新增全量。原文件.backup `.launcher-repair-*`保留。证据与REPORT：`xiaovcat_adapter/runtime/server_publish_worker/launcher_preflight/`。修复完成后停止，不要求用户现在运行入口。

### 2026-10-05 05:04：EMERGENCY SERVER PUBLISH接线已准备，Job3未提交（PARTIAL）

本次700cee90附件明确取代下面的2060S发布执行方案：服务器PC-20260617GEOP/192.168.1.126负责发布，2060S只Render。2060S发布Task XUNZHEN_XIAOVCAT_PUBLISH_WORKER先确认IDLE/current=null/dry=true/armed=false，再Disable及写自己的STOP_WORKER正常退出；05:00:56补证Disabled/enabled=false/发布进程0。Render Task仍Running/enabled=true，没有修改/重启Render、Jianying、SMB或视频。服务器8776发布桥Task亦Disabled并停止，监听/进程0；保留代码/旧记录，避免远端再次claim。旧服务器同名Task和退役入口仍Disabled，不重新启用第二执行器。

新增服务器接线`xiaovcat_adapter/server_resident.py`和`server_ui_worker.config.json`，入口仍复用根`xiaovcat_publish_worker.py`，身份XIAOVCAT-WORKER-SERVER-01。UI动作/控件实现、原fresh readback、reserve-once、ProductionDispatcher、结果核验均未改写。8502的start_confirmed_dispatch在SERVER_ONLY模式只读鉴权并通知已确认队列，不再Popen逐计划桌面子进程；Preview不能通知，当前允许范围固定原Plan52e11ba8/原Job3 af6c16d3。界面明确提示执行器尚未启用，避免显示PID None已成功。**本轮未重载线上8502，不能宣称新接线已在其现有进程生效。**

服务器新Task XUNZHEN_XIAOVCAT_PUBLISH_WORKER_SERVER已注册，Administrator/Interactive/AtLogOn/IgnoreNew/非SYSTEM，当前Disabled、worker_enabled=false。新模块由原PublishWorker一次执行一条，磁盘dry=true/armed=false/global=false；只有正式启用或用户原Job3一次性入口才有进程内许可，原submit先持久化再Invoke、撤销回调及finally不变。全量模式必须原3个Job均SCHEDULED_QUEUED/各reserve1，并设带时区production_authorized_after排除历史队列，scope变化要求重启Publish独立进程。目前未开启全量或常驻真实消费。

本机受支持sky通道正常启动服务器现有D:\小V猫\小V猫.exe并读到主页/登录态。账号管理输入报`coordinate input geometry is unavailable`；按技能重新选唯一窗口/恢复一次，截图报`FrameArrived timed out: timed out waiting on channel`，随后停止所有桌面输入，没有以CLI调用UIA Worker绕过。该限制是Codex执行通道，不是原本机Worker代码失败。未完成实机Dry/回读/Job3提交，不能给STARTUP_BATCH_3_AUTO_PUBLISH_PASS或SERVER_XIAOVCAT_RESIDENT_PUBLISH_WORKER_READY。

05:04:14只读预检：Administrator同一Session1/console1及小V猫进程SID检查通过；原-6本地视频49,597,710字节，SHA8e6d565018aca1d2770ad8c38e4efdd27db2aac4e4a84b36cd5a6fa0fbefc256不变。严格账号预检仍PUBLISH_ACCOUNT_SNAPSHOT_EXPIRED；未伪造同步/ONLINE。原Job1/2各attempt1、SCHEDULED_QUEUED和SUBMITTED保持；Job3attempt0、NEEDS_MANUAL/dispatchQUEUED、contentREADY/SCHEDULED，未claim。本计划3个Job、全库Plan3/Job9不变；新增Plan/Job/视频/Render/提交均0，globalfalse/armedfalse，8502 health200。

用户本人在服务器可运行`START_SERVER_XIAOVCAT_JOB3_ACCEPTANCE.cmd`，本轮未运行。入口只允许原Job3且拒绝已claim/attempt；原正式机制自动刷新339642快照，再原UIA准备/完整回读/最多一次提交/只读核验。固定15:00仍须距执行>2小时，不自动重排，13:00以后拒绝。结束不启用常驻Task、不消费第4条。说明`xiaovcat_adapter/SERVER_JOB3_ACCEPTANCE.md`；日志/机器预检/结果位于`xiaovcat_adapter/runtime/server_publish_worker`。

新增服务器专项13/13通过；本轮相关全量539/539（218.598秒）通过，包含既有发布安全/Planner/Render回归，均为Mock/隔离夹具，不是实机发布PASS。最终6个Python语法PASS，用户入口PowerShell仅Parse通过未执行。预检证据脚本首轮因新runtime目录不存在报FileNotFoundError，补mkdir后真实重跑通过；未改业务状态。源文件/文档备份.emergency-server-*保留。最终报告`xiaovcat_adapter/runtime/server_publish_worker/REPORT.md`。

### 2026-10-05 04:30：继续授权后的通道范围核验与未武装observer真实重启补证；正式UI/生产验收未完成

本轮读取c04fd80f完整请求，用户授权Job3一次真实提交与后续常驻生产验收，但禁止Job1/2重放、第四条、新Plan/Job。没有把最高文件系统权限当作桌面通道授权。完整读取computer-use技能/guidance/confirmations/api，按受支持`node_repl + @oai/sky`初始化并只读list_apps/list_windows：真实控制主机`PC-20260617GEOP`，文档API没有远端device选择参数，不能选择2060S；没有启动服务器小V猫，没有尝试截图或ToDesk。2060S维护连接Online但CLI不能替代Computer Use触发UIA Worker桌面动作。明确代码`SUPPORTED_DESKTOP_CHANNEL_NOT_TARGETING_2060S`，不是Worker故障或截图失败，也未猜测小V猫登录失败。实机UIA Dry和Job3真实提交均未执行，不宣称两项最终PASS。

完成可独立补证的安全重启：新增维护脚本`xiaovcat_adapter/deployment/restart_observer_check.py`部署2060S同名根目录，仅复用正常STOP标记/instance_lock/原Task恢复；不调用UI、账号同步、claim、submit。04:29:47→04:29:57正常交接，旧PID18720→新PID25436，父23476为venv包装，同一Windows用户/Session1、唯一实例进程链，Task/heartbeat恢复IDLE/current=null；队列前中后完全一致，Job3 QUEUED/attempt0。这只是`UNARMED_OBSERVER_RESTART_PASS`，不冒充真实生产executor重启验收，更不证明开机启动。

04:30:49服务器只读业务快照：原Plan3条、全库3 Plan/9 PublishJob保持；Job1/2 SCHEDULED_QUEUED/各attempt1，Job2人工确认及不确定历史未动；Job3 NEEDS_MANUAL/STARTUP_CONFIRMED_NOT_DISPATCHED、dispatchQUEUED、claimed_at=null、READY/SCHEDULED、attempt0、LOCAL事件0。原15:00/账号/文案/视频SHA未动，新提交/Plan/Job均0，globalfalse/armedfalse。服务器同名Task Disabled、enabled=false、正式发布进程0。2060S小V猫未运行，登录未核验。Render仍IDLE未重启，未碰剪映/素材/导出。

本轮专项24/24通过（8.596秒），现有LAN Render/专用入口39/39通过（1.384秒），维护脚本语法PASS；此前523/523全量结果仅作为上一轮基线，不冒称本轮重跑全部。证据`SUPPORTED_CHANNEL_CHECK.json`、`OBSERVER_RESTART_ACCEPTANCE.json`、最新`FINAL_READ_ONLY_EVIDENCE.json`和REPORT均在`xiaovcat_adapter/runtime/lan_publish_2060s`。

下游实机Dry、原Job3唯一提交/结果核验、正式自动执行模式与8502 Confirm授权队列泛化仍未完成。当前常驻代码仍限定原Job3且只观察/心跳，不称PRODUCTION_READY。按用户指定顺序不在Job3成功前放开其它队列。要推进UI步骤需能直接访问2060S的受支持桌面通道，或用户本人本机运行已准备入口；维护CLI执行UIA发布不能作为旁路。本轮在该技能边界停止，没有伪造生产失败或成功。

### 2026-10-05 04:18：小V猫执行Worker迁移2060S完成；真实UIA Dry Run仍待本机用户运行（PARTIAL）

本次以084285a5附件纠正部署位置，取代下方历史服务器执行方案。服务器Task `XUNZHEN_XIAOVCAT_PUBLISH_WORKER`已Disabled、worker_enabled=false、STOP_WORKER保留，正式发布进程0。根`START_XIAOVCAT_JOB3_ACCEPTANCE.cmd`只提示入口退役；旧首次验收及production_worker真实默认执行在服务器主机拒绝。代码、Task导出备份及历史报告保留。

2060S `DESKTOP-9VQ76D3/192.168.1.89`、`sdaffwS`、Session1部署`D:\XunZhenPublishWorker`；Worker ID `XIAOVCAT-WORKER-2060S-01`。Task同名，Interactive/AtLogOn/IgnoreNew/非SYSTEM，04:07:48启动，PID18720（venv wrapper父22000是一条进程链而非第二Worker）。常驻默认仅NO_UI_NO_CLAIM队列数据观察与20秒心跳，ONLINE/IDLE/current=null，Render亦IDLE；没有自动实例化UIA/PrepareUI或领取任务。最终配置dry=true/armed=false/global=false。

最小LAN API`192.168.1.126:8776`/Task`XUNZHEN_PUBLISH_DISPATCH_API`仅业务仓库，不含桌面执行；Private防火墙仅本机IP→2060S IP允许。复用既有Render两端DPAPI凭据引用，没有复制明文token/DPAPI文件，也不造第二operations.db。server/worker模块复用ProductionDispatcher原严格_context/claim、原reserve先commit→HTTP确认→唯一Invoke，以及原结果服务；2060S仓库DI只替换存储调用，UI控件动作/回读不重写。网络不自动重试claim/reserve；server重启/ACK丢失不能重新取提交能力。server全局保持false，许可仍为单Job最小内存窗口，Invoke结束原finally立即撤销。

当前部署范围双重限制原Plan52e11ba8及原Job3 af6c16d3，未泛化消费其它队列。原计划仍3个Job，全库3个Plan/9个Job，新增0；Job1/2成功状态与各attempt1未操作，Job3仍QUEUED/claimed_at=null、READY/SCHEDULED、attempt0、LOCAL事件0，15:00原排期未改。本轮真实提交0。

小V猫真实安装`D:\小V猫\小V猫.exe`，文件ProductVersion`2,0,0`、卸载登记DisplayVersion`3.0.0`；尚未检查UI版本/登录，当前进程不存在，不能宣称丙曜在2060S已登录。原Job3 MP4经已有RenderOutput共享→2060S本地`Jobs\af6c16d3-2912-4390-88c7-4584b3e4feea\video\丙曜起号10月4日-6.mp4`，49,597,710字节，SHA8e6d565018aca1d2770ad8c38e4efdd27db2aac4e4a84b36cd5a6fa0fbefc256与原文件一致，不Render、不改源文件、不用UNC上传。

共享GUI lane沿用原Render同名Windows mutex `Local\XiaovcatDesktopWorkerV03`；Publish检查Render新鲜IDLE再取锁，Render仅GUI阶段增加WAITING_UI_LANE等待包装。其它生成/导出/ffprobe/回传逻辑未改，Render常驻未重启。两端旧agent源码只末尾空行/换行不同已逐行比对，远端原SHA24AA2412…作漂移保护+备份后机械部署；新源码SHA82C41411…两端一致。121/121既有Render隔离回归PASS；没有声称本轮新增实机Render测试。

最小运行包54源码、61条目、155360字节，SHAe7dc43b0eaf26bac0dc46b5ba59a29f6b804e8acf2c2905ba59d698f2e576f0d；必要模块在2060S Python3.11既有venv真实import通过。runtime无*.db或凭据副本。不依赖Remote Desktop Commander运行生产，维护连接仅部署/读取结果。

`START_JOB3_UI_DRY_RUN.cmd`与`START_JOB3_FIRST_REAL_ACCEPTANCE.cmd`及README已在2060S准备，均未执行。真实入口缺少LOCAL_UIA_DRY_RUN_PASS/2060S_LOCAL_WORKER_UIA证据时在任何桌面动作前拒绝。**真实UIA Dry验收尚未完成，不能返回XIAOVCAT_2060S_PUBLISH_WORKER_ARMED_READY。** computer-use技能不允许Codex把维护CLI调用UIA Worker作为桌面旁路；本轮不研究捕获，也不把远程截图作为Worker PASS条件。下一步请用户在2060S正常打开小V猫/如需则登录，只运行`START_JOB3_UI_DRY_RUN.cmd`，收到本机UIA证据后再只读核验。当前不要运行真实入口。原排期15:00距真实执行仍须>2小时，不自动重算；旧01:24账号快照已过期，用户Dry入口通过既有单组339642真实读取刷新，未伪造online。

全量相关523/523（203.109秒）与最终LAN专项24/24（8.164秒）通过，专项与全量有重叠不相加；10文件语法PASS。初次发现test import路径/默认GBK问题，按正确包名+UTF8运行修正，失败日志保留，未借此改生产逻辑。远端脚本执行策略限制及Task Action空值均保留现场，最终用明确prefix变量注册成功；仅该进程ExecutionPolicy，不改机器全局策略。证据和报告：`xiaovcat_adapter/runtime/lan_publish_2060s/REPORT.md`、`FINAL_READ_ONLY_EVIDENCE.json`、`2060S_READ_ONLY_EVIDENCE.json`、`FULL_REGRESSION.log`、`LAN_REGRESSION_FINAL.log`。

### 2026-10-05：Job3首次实机验收入口准备完成，未运行、未武装、未提交

用户明确本轮Codex只准备，一次性真实武装由用户本人执行。新增根目录`START_XIAOVCAT_JOB3_ACCEPTANCE.cmd`与`xiaovcat_adapter/job3_first_acceptance.py`，固定原Plan52e11ba8、原Job3 af6c16d3、原content/account/完整视频路径+SHA、原15:00/空标题/简介/3话题；配置与代码双重锁定，不创建Plan/PublishJob/验收scope，不操作Job1/2。用户说明`xiaovcat_adapter/JOB3_FIRST_REAL_ACCEPTANCE.md`。

用户执行时先验唯一已部署空闲未武装实例、Windows SID/Session、exe、Task动作/解析SID、原Job attempt0、严格正式_context（授权/新鲜在线快照/绑定/ffprobe/SHA/固定合法排期）。全部通过才用自己的正常停止标记交接原空闲Worker；原互斥取得后二次预检。仅本次进程内dry=false/armed=true，常驻配置文件一直dry=true/armed=false，global一直false；仅run_once原Job3。原reserve先commit再唯一Invoke不变。execute_once finally新增可选撤销回调，Invoke返回/抛错后先关许可和内存武装，再保存/观察结果；Worker/入口finally兜底。崩溃不能保存武装，reserve≥1拒绝再次运行提交。任务记录原严格唯一核验，已同步才SUBMITTED/SCHEDULED_QUEUED，不标PUBLISHED。最后仅恢复原未武装Task，不改Task配置。

本轮没有运行cmd/真实入口，也未停止/重启Worker、刷新小V猫或触发任何桌面动作。03:22:50只读证据：常驻唯一PID6228/Session1/同SID，Task身份与动作通过，Job3 QUEUED/attempt0、READY/SCHEDULED、账号绑定与原字段正确；Job1/2 SCHEDULED_QUEUED/attempt1各自历史保持。本计划3个Job、全库Plan3/Job9、Job3 LOCAL事件0。原MP4 SHA8e6d565018aca1d2770ad8c38e4efdd27db2aac4e4a84b36cd5a6fa0fbefc256一致。本轮唯一当前实机预检阻塞PUBLISH_ACCOUNT_SNAPSHOT_EXPIRED，最近同步01:24北京时间；不把旧ONLINE字段当新鲜在线证明。用户运行前需用现有刷新发布账号更新，固定排期距执行须>2小时，不重算。准备状态不等于当前武装或生产提交PASS。

本轮新增23项隔离测试（入口19、一次性Worker4），最终相关回归416/416（180.837秒）通过，6个Python文件语法检查通过。初次普通沙箱77项因临时目录权限失败，受控授权Mock/夹具重跑通过；全量日志JOB3_ENTRY_REGRESSION.log，未使用真实UI。只读Task检查发现UserId以Administrator短名存储，改为NTAccount解析SID后严格比较，不放宽身份验证；当前真实Task检查通过。

证据`xiaovcat_adapter/runtime/job3_first_real_acceptance/PREPARATION_READ_ONLY_EVIDENCE.json`；报告同目录REPORT.md。当前仍DRY_RUN_MODE=true、REAL_SUBMIT_ARMED=false、real_publish_enabled=false；准备后停止，不触碰Render/Planner/原视频。

### 2026-10-05 02:59：XIAOVCAT_LOCAL_UI_PUBLISH_WORKER_DRY_RUN_READY（软件/Fixture验收，不是真实提交）

本轮按914bd564附件只开发、部署和离线Dry Run；不把新Worker作为Codex实时桌面旁路。独立入口`xiaovcat_publish_worker.py`、适配器`xiaovcat_adapter/local_ui_publisher.py`、限定队列仓库`local_worker_queue.py`、只读身份检查`local_session.py`。正式代码无Codex/computer-use/Remote Desktop Commander/OCR/坐标/截图运行依赖。Render/Jianying/SMB/ffprobe/READY/Planner确认逻辑未改，不创建Plan/Job/content/Render。

原production_dispatch只抽出共用原子claim事务（旧员工token接口仍鉴权）；本机入口由固定生产Windows SID及配置中显式Plan/Job范围授权，不发员工token、不伪造登录或acceptance scope。原_context继续严格验证有效员工、STARTUP组、稳定账号绑定、新鲜在线快照、固定未来排期与视频。唯一附加结果入口允许同原nonce、reserve1的SUBMIT_RESULT_UNCERTAIN经严格任务证据收口；不重置claim、不清闩锁、不提前PUBLISHED。未新增数据库schema或第二套库。

Publisher将准备、回读、单次提交、只读核验分离；既有控件动作复用，stale只重观察最多2次。scope.capture_screenshots=false让旧截图证据不成为运行条件，旧调用默认保持截图。旧日期输入含SendInput，本地scope增加uia_only=true，沿既有ValuePattern.SetValue纯UIA写入并原样回读，旧默认分支不变；这一分支只有Mock验证，未宣称本轮真实UI写入成功。任务记录反向导航与已创建提示的去查看进度使用已有控件类型/层级和UIA模式；未知弹窗停止，不调用提交/重发/详情等未授权动作。

恢复机制：原V04_FINAL_SUBMIT_RESERVED为数据库持久化保守attempt，先commit后唯一Invoke；>=1即禁止再prepare/claim/submit，只根据同一任务块的稳定账号ID、昵称、平台、完整文件名、固定定时、创建标签时间±120秒唯一核验。后台执行中不等于成功，多匹配/缺字段转SUBMIT_RESULT_UNCERTAIN。Invoke立即记录submit_returned_at，并追加LOCAL_SUBMIT_RETURNED；进程崩溃可能返回时间为空，但闩锁仍有效。原execute_once单Job内存许可最小窗口true/finally false，全局配置始终false。准备阶段崩溃（已claim但attempt0）不重放写操作，安全BLOCKED。身份/范围热改需停机重启，失效快照最多用现有单组机制刷新一次再严格claim。

Task `XUNZHEN_XIAOVCAT_PUBLISH_WORKER`已从本轮只读monitor任务迁移，固定Administrator/Interactive/AtLogOn/IgnoreNew，异常恢复3次/1分钟。旧monitor源文件/日志保留，PID1752正常退出；新的executor整合25秒心跳。默认worker_enabled=true、dry_run_mode=true、real_submit_armed=false；此分支只查进程身份/正式队列并构造数据，**不claim、不实例化PrepareUI、不触发任何UI动作**。实际干净停止/重启已验证，最终PID6228、Session1，与小V猫同用户同活动Session，02:58:36心跳ARMED_REQUIRED/current_job_id=null。第二实例启动在进入队列/UI前WORKER_ALREADY_RUNNING退出，未覆盖正式心跳。只验证部署/当前进程，未作OS重启/注销验收。Task LastTaskResult267009=运行中。

原Job3正式字段Dry Run：af6c16d3、STARTUP-a16c1f3b-2dbc-41ca-9c9d-8eb157a3e73e、丙曜/抖音1621131832863931、原-6文件、原10月5日15:00、标题空、简介陶老师小妙招、3话题全部从数据库构造；不是UI fresh readback，不标FORM_VERIFIED。最终Job3 QUEUED/claimed_at=null/attempt0，原文件SHA8e6d565018aca1d2770ad8c38e4efdd27db2aac4e4a84b36cd5a6fa0fbefc256一致。Job1/2未操作，SCHEDULED_QUEUED/各1次，Job2人工确认来源与未知历史保留。原Plan52e11ba8/current plan3条，全库Plan3/Job9，LOCAL_事件0，新增Plan/Job/真实提交0，real_publish_enabled=false。Batch3仍PARTIAL，不能标真实发布PASS。

最终相关回归393/393（173.943秒），新增43项（Publisher20+Worker23），13文件语法PASS。首轮发现结果目录缺失已修，377项首次运行的旧测试导入路径错误及AST证据开关误差日志保留；新AST仅允许截图开关/返回时间，原reserve/唯一Invoke/try-finally逐句保护仍在。Fixture明确区分旧原始表单树与从历史sky文本规范化的任务记录，不伪造新的UIA实机证据。证据`xiaovcat_adapter/runtime/local_ui_worker/FINAL_READ_ONLY_EVIDENCE.json`、DRY_RUN.json、FULL_REGRESSION_FINAL.log；报告原batch3 REPORT及local_ui_worker/REPORT。配置/运维见LOCAL_UI_WORKER.md，文档/被改原文件有.local-ui-worker-v1.bak。

本轮首次真实本机prepare/fresh readback/唯一提交/任务记录UIA核验均未执行。未来必须另有明确启用授权、严格核验固定排期仍合法，然后将dry_run_mode=false、real_submit_armed=true并限定原范围；不需改代码。本轮不武装、不发布，未武装Worker留驻，停止开发。

### 2026-10-05 02:15：常驻发布监督层部署，仅MONITOR_ONLY，未完成正式Publish Worker

本轮用户要求停止Codex desktop capture重试并建设独立常驻Xiaovcat Publish Worker。没有再调用computer-use捕获、桌面输入或现有UIA执行器。当前交付范围仅只读监督基础设施，状态`XIAOVCAT_RESIDENT_PUBLISH_WORKER_PARTIAL`；不能标`XIAOVCAT_RESIDENT_PUBLISH_WORKER_READY`或`STARTUP_BATCH_3_AUTO_PUBLISH_PASS`。

新增`xiaovcat_adapter/desktop_worker/resident_monitor.py`、配置、启动/安装脚本及15项隔离测试。监控使用SQLite mode=ro观察正式production_dispatch，只允许观察原Job3 af6c16d3；无数据库迁移、claim、控件读取/输入、表单准备或提交调用。配置硬拒绝MONITOR_ONLY以外模式。队列eligible仅表示未领取、未占用提交闩锁的已确认候选，不等于账号/媒体/排期严格预检或Job3 dry run PASS。

服务器PC-20260617GEOP/192.168.1.126，Task Scheduler `XUNZHEN_XIAOVCAT_PUBLISH_WORKER`已部署为**只读监控**：Administrator、Interactive、AtLogOn、IgnoreNew、异常重启3次/1分钟。最初PowerShell -File入口退出1；改为项目已配置Python的pythonw.exe直接启动，不修改Windows ExecutionPolicy，不覆盖其它任务。实际监控PID1752、启动02:12:02、Session1，和小V猫同一活动console Session；02:12:02至02:14:22持续5秒心跳、单实例、IDLE/current_job_id=null。Task LastTaskResult267009表示正在运行，不是退出成功码。登录自动触发/重启恢复配置已存在，但本轮未进行注销或重启验收，也未验证锁屏/登录弹窗状态。仅监控运行不依赖Codex，正式发布独立运行尚未证明。

仍缺：现有ProductionDispatcher.claim依赖有效员工会话，尚无合规独立Worker认证/授权接线；现有production_worker.prepare_and_submit将准备和提交连在一起，提交后只轮询当前树，没有独立自导航任务记录核验闭环。均未修改安全模型或既有UIA控件逻辑。依据computer-use技能的Windows自动化通道限制，不能通过新常驻进程替代失败的受支持桌面通道由Codex执行本轮真实控件动作；当前不执行这种旁路。停止截图重试不等于证明软件生产能力失败，也不等于生产执行验收通过。

只读复核原Plan52e11ba8未改，当前计划原3个Job，全库Plan3/PublishJob9不增。Job1/2 SCHEDULED_QUEUED、content.publish_status SUBMITTED，历史提交闩锁各1；Job2人工确认来源与SUBMIT_RESULT_UNCERTAIN历史保留。Job3 QUEUED/claimed_at=null，Job NEEDS_MANUAL/STARTUP_CONFIRMED_NOT_DISPATCHED，原15:00未改，累计提交0；未做FORM_VERIFIED/本地dry run。累计1/1/0，本轮新增Plan/Job/content/Render/提交均0，real_publish_enabled=false。没有操作Job1/2、Render链或视频。

最终相关隔离回归56/56（既有41+新增15，0.711秒）、2个Python文件语法PASS。首次fixture连接未关闭导致WinError32已修；最后普通沙箱重跑因临时目录权限报错，保留REGRESSION_FINAL.log，授权非沙箱运行最终通过REGRESSION_ELEVATED_FINAL.log；未冒称重跑历史321项。报告`xiaovcat_adapter/runtime/resident_monitor/REPORT.md`及原批次REPORT.md。文档修改前备份`.resident-monitor-20261005.bak`。监控保留只读运行，生产执行关闭，本轮停止。

### 2026-10-05 01:53：维护连接恢复后原Job3观察重试，Codex捕获仍超时

用户报告桌面维护通道已恢复，授权仅原Job3，不处理Job1/2。重新通过受支持sky枚举小V猫真实唯一窗口133098，截图第一次FrameArrived timed out；重新枚举/选择/激活并一次有界恢复仍window capture timed out。依据computer-use技能停止输入，不以其它UIA/Worker/维护控制替代失败的观察通道，没有执行导航/上传/表单准备/最终提交。

只读正式库确认原af6c16d3仍QUEUED、claimed_at=null、历史reserve0，Job.current_step仍STARTUP_CONFIRMED_NOT_DISPATCHED，原15:00及-6路径不变；Job3未有ORIGINAL_FILE_SELECTION证据，不冒称已载入或fresh readback PASS。real_publish_enabled=false，新Plan/Job/视频/Render/重传/真实提交均0，Job1/Job2没有再次操作。维护连接恢复不等于Codex支持的捕获通道恢复；当前HARD_EXTERNAL_BLOCKER仍SUPPORTED_COMPUTER_USE_CAPTURE_UNAVAILABLE。

本轮仅补证/更新文档，没有生产逻辑修改或后台Worker启动。证据JOB3_CHANNEL_RECHECK_20261005_0153.json；旧失败现场/Job2人工成功来源保留。未标整批PASS，已停止，须恢复受支持桌面观察后才准备原Job3；不得重新提交前两条。

### 2026-10-05 01:44：Job2人工确认收口；Job3准备前观察通道阻断，零领取/零提交

用户明确人工在小V猫确认Job2成功，原c671a186/content STARTUP-1e4ca507-7cc6-46dc-9ce9-6361110a8418按该确认收口为SCHEDULED_QUEUED/content SUBMITTED。submission_confirmation_source=USER_MANUAL_XIAOVCAT_CONFIRMATION持久化于同名state_events审计及job2_20261005/USER_MANUAL_CONFIRMATION_RESULT.json；不冒称机器重新核验已同步。正式仓库单事务仅更新原结果，核验原上下文/排期12:00/绑定/文件SHA/Invoke1/reserve1，保留旧状态/错误字段到审计，未清闩锁或重新派发。原FINAL_RESULT.json/READ_ONLY_OUTCOME.json及SUBMIT_RESULT_UNCERTAIN历史全文保持；数据库修改前已backup为job2_20261005/operations.before-manual-confirm-20261005_014130.db.bak。Job1/Job3记录未改，计数不增，未标PUBLISHED。

本轮同时授权原Job3，但尚未准备或提交。支持的sky新枚举/文本观察仍发现原发布创建提示对话框，未自动关闭旧Job提示或操作Job1/2；在准备导航前截图FrameArrived超时。重新枚举唯一小V猫窗口、激活、一次恢复截图仍window capture timed out；按computer-use安全恢复规则停止全部输入，不通过CLI/UIA替代该已失败的控制观察通道。本轮新增job3_prepare_only.py只是未执行的已有Worker准备包装，不含最终提交；未运行它、未领取Job3、不改其QUEUED或15:00。

最终Job1/Job2均SCHEDULED_QUEUED、各1次，Job2为人工确认来源；Job3QUEUED/0次，累计1/1/0，新Plan/Job/content/Render0，全局及许可false。当前HARD_EXTERNAL_BLOCKER=SUPPORTED_COMPUTER_USE_CAPTURE_UNAVAILABLE，整批仍PARTIAL，不冒称Batch3 PASS。证据JOB3_PREPARE_BLOCKED.json、Job2人工确认审计/报告；两个runtime脚本py_compile通过，本轮未重跑全量回归。已停止，恢复受支持观察通道后才可准备Job3；仍须最终字段回读PASS及动作时确认，不允许再次提交前两条。

### 2026-10-05 01:37：原Job2唯一提交已创建后台任务，结果待只读核验；停止，不操作Job1/3

用户即时确认仅原Job2 c671a186-21e4-44a9-8529-28138eee49e5；通过正常员工登录及正式ProductionScope检查原CLAIMED/nonce、历史reserve0/无成功发布记录，绑定丙曜/抖音1621131832863931、原-5文件路径/SHA与固定12:00/空标题/简介“陶老师小妙招”/健康健康科普养生一致。01:35:22只读重新检查在线唯一选中账号，01:35:24完整fresh回读PASS，不重新上传/重选账号/改排期/视频/Plan/Job；既有ready_actions仅validate和submit。

01:35:26.580510 +08:00唯一Invoke返回，持久化reserve1，单任务许可01:35:26.583386关闭，全局一直false。computer-use sky真实读取“发布任务已创建，已在后台执行中。”，不等于已同步。只读点击“去查看进度”遇coordinate input geometry is unavailable；随后截图FrameArrived超时，按skill重新定位唯一窗口并激活后一次恢复仍window capture timed out。按computer-use安全恢复规则停止输入，不绕过通道，不再点击最终按钮。

通过现有ProductionDispatcher.block保存Job2=NEEDS_MANUAL/SUBMIT_RESULT_UNCERTAIN、dispatch=SUBMIT_RESULT_UNCERTAIN；content.production_status=READY/publish_status=SCHEDULED，未伪记SUBMITTED/SCHEDULED_QUEUED/PUBLISHED。Job1/Job3整行与开始快照不变，Job1已同步且reserve1永久保留，Job3仍QUEUED未领取，累计1/1/0、重复0。原plan保持，本计划仍原3个Job，全库Plan3/Job9/content34/run10/acceptance1均不增。real_publish_enabled最终false，执行器已退出。

新增runtime/job2_confirmed_submit.py只编排既有单次Worker，job2_readonly_uncertain.py只登记未知结果，无新控件逻辑/生产模块改动。两个脚本语法通过；本轮未重跑全量回归，上一轮41/41和先前321/321保留为历史。机器证据startup_pipeline/runtime/batch3_publish_final/job2_20261005/CONFIRMED_SUBMIT_RESULT.json、SUBMIT_RESULT.json、READ_ONLY_OUTCOME.json、FINAL_RESULT.json及REPORT.md。后续只能只读核验唯一-5/丙曜/12:00/创建01:35:26的任务；禁止重新提交Job2，当前停止，不执行Job3。

### 2026-10-05 01:26：原Job2表单完整准备PASS，等待最终即时确认；Job1状态保持

当前整批STARTUP_BATCH_3_AUTO_PUBLISH_PARTIAL。用户授权Job2/3串行；原Job2 c671a186于01:24原子领取，原-5 MP4文件对话框路径回读及SHA核验通过，丙曜/抖音账号在线唯一选中，稳定ID1621131832863931与永久content绑定一致。初次recent-topic入口未找到唯一健康选项，零提交停止保留历史；通过原PlannerStore事务一次审计恢复同claim，复用既有topic-search/topic-commit逐个建立真实chip，不重传/重选，不改Worker控件逻辑。

01:26:16完整新树回读左右标题空、简介“陶老师小妙招”、健康/健康科普/养生实际3chip、左右定时10月5日12:00，账号及超时转即时关闭均通过。Job2=DRY_RUN_READY/PRE_SUBMIT_VERIFIED，队列CLAIMED，最终Invoke/reserve=0。原Job1及派发整行与本轮开始比对不变，SCHEDULED_QUEUED/content SUBMITTED，唯一reserve1；Job3仍QUEUED未领取，不提前填写或提交。累计1/0/0，新增Plan/Job0、全库Plan3/Job9/content34/run10/acceptance1不变，global与真实许可均false，无后台提交执行器。

按computer-use规则，在实际最终点击边界必须再请求即时确认，即使已预授权；当前暂停等待Job2最终一次提交确认，不标Batch3 PASS。收到后仅最终重读/一次Invoke/只读任务关联，不重做准备；Job2明确成功才继续Job3，未知停止。runtime prepare_remaining_job.py只编排现有动作，生产Worker/Planner/Dispatcher/Render源码未改。本轮41/41既有相关回归与新脚本语法通过，原321/321为先前基线。证据及报告`startup_pipeline/runtime/batch3_publish_final/job2_20261005/`、同父REPORT.md，原最近使用话题失败证据保留不伪造。

### 2026-10-05 01:17：原Job1唯一提交已同步，只读结果登记成功；不执行Job2/3

用户即时确认只提交原ce40b544 Job1，不执行后两条。最终回读00:52:52丙曜/抖音1621131832863931、-4原视频、空标题/简介“陶老师小妙招”/健康健康科普养生/原10月5日09:00全部一致。00:52:54.294837唯一Invoke返回，原单Job内存许可00:52:54.297261关闭，全局一直false。原持久化reserve=1，累计一键分发1次，不重新上传或选账号、不改排期或MP4。

00:55:55初始结果轮询因任务创建提示窗未进入任务行，安全保留SUBMIT_RESULT_UNCERTAIN，没有再次提交。用户随后明确允许只读任务记录核验。01:15:45经computer-use sky读取真实当前任务记录，唯一-4条目=已同步、账号稳定ID匹配、创建及执行时间00:52:54、定时09:00、简介精确、用时1分6秒，与旧-3/组合1任务严格区分。01:17通过原PlannerStore单事务登记PRODUCTION_SCHEDULED_RESULT_VERIFIED审计，原Job与队列=SCHEDULED_QUEUED，content.publish_status=SUBMITTED（production_status仍READY），未标PUBLISHED，work_id/URL暂未取得。

只读后验登记没有UI输入/提交/创建/领取代码，不将未知状态重置CLAIMED，不清闩锁，不重新派发。原ProductionDispatcher/Worker/Planner/Render源码未改。两条后续仍QUEUED、未领取/提交；本计划原3条、全库Plan3/Job9/content34/run10/acceptance1保持，新Plan/Job/视频0、重复提交0、real_publish_enabled最终false。整批仍PARTIAL，仅Job1本轮PASS，禁止继续后两条。

00:42首页/播放器进度条滚动offscreen的前置误停、00:51快照过期停止均保留历史；本轮编排严格原已安装播放器结构、路径/SHA/账号panel校验，通过原仓库一次审计恢复误停同claim，正式339642单组刷新后提交，未放宽发布安全。当前机器证据`startup_pipeline/runtime/batch3_publish_final/JOB1_READ_ONLY_FINAL_RESULT.json`、JOB1_CURRENT_TASK_SKY.txt、stale_resume_20261005/SUBMIT_RESULT.json及REPORT.md。原JOB1_CONFIRMED_SUBMIT_RESULT.json保留不确定历史，最新以后验结果为准。本轮两个脚本语法通过；321/321是上一轮回归基线，未冒称本轮重跑全量。停止，不追加自动化或发布监控。

### 2026-10-05：UIA stale只读重观察修复；原Job1完整回读PASS，尚未真实提交

当前`STARTUP_BATCH_3_AUTO_PUBLISH_PARTIAL`，技术准备`JOB1_FRESH_PRE_SUBMIT_PASS`。用户5827d041附件允许仅修账号等动作后stale回读及恢复原Job1；新增fresh_readback只包裹读操作，初读+最多2次重观察，总预算不重置；每次从当前窗口新树重定位，错误快照整体丢弃，不重做Invoke/Toggle/SetValue。正确值SKIP WRITE；超限UI_STATE_UNSTABLE，其它异常立即停止。未重写控件策略或Production Dispatch/Planner。

一次性恢复沿原PlannerStore写事务，有PRE_SUBMIT_STALE_READBACK_RESUMED旧→新审计1条；原ce40b544 Job/claim/context/claim时间保持，原子claim仍1次，无submit reserve才允许恢复。Job1视频和账号已正确，所以本轮未重新上传/重选。00:24:23新树回读丙曜/抖音在线且选中、左右标题空/简介“陶老师小妙招”、右侧实际3个话题健康/健康科普/养生、左右定时2026-10-05 09:00，超时改即时关闭。视频依据原标准文件路径回读+同一载入表单+SHA一致；UI无完整文件名，不冒称重新从UI取得文件路径。

当前停止在computer-use规定的最终对外提交即时确认边界（即使预授权也需要），不是技术阻塞。Job1=DRY_RUN_READY/PRE_SUBMIT_VERIFIED、队列CLAIMED；Job2/3仍QUEUED未领取，未回读其真实表单。三条一键分发0/0/0、重复0、真实发布0，全程false，无后台最终提交执行器。Plan52e11ba8原3条仍固定10月5日09/12/15+08；三条content READY/SCHEDULED。全库Plan3/Job9/content34/run10/acceptance1保持，新增Plan/Job0，三个MP4 SHA一致，未重启8502或改Render/2060S/Jianying/SMB/账号绑定。

收到即时确认后沿原nonce只继续最终回读和原单次提交，不重新prepare视频/账号，不清除ledger或重算排期；Job1明确已同步才可继续下一条，未知即停止。reserve_once/execute_once/validate_and_prepare AST原样，live_snapshot只新增有界只读包装。最终回归321/321：STARTUP214（143.520秒）、V0.4 21、Planner66、导航10、回读10；新增测试18项（回读10+恢复8），10文件py_compile通过。首轮namespace导入/新增测试调用笔误及第二轮discover目录不可导入日志保留，最后按现有namespace模块名完整运行通过，不改框架或生产条件。证据`startup_pipeline/runtime/batch3_publish_final/stale_resume_20261005/`、`STALE_FINAL_RESULT.json`，报告同目录REPORT.md，文档修改前备份后缀`.stale-readback-20261005.bak`。

### 2026-10-04 23:53：发单条视频导航真实PASS；原Job1在账号步骤证据回读阻塞，真实提交0

本轮仍为`STARTUP_BATCH_3_AUTO_PUBLISH_PARTIAL`，不得标发布PASS。用户附件bb79f017仅允许补“任务记录→发单条视频”子页导航。正式Worker仅修改`v04_prepare.py`新增`ensure_single_video_page`/就绪判定、`ready_actions.py`的page入口调用；24个既有PrepareUI方法AST逐一保持不变。Production Dispatch、Planner、V0.4最终回读/闩锁/提交逻辑未改，8502未重载。

真实UI层级为外层`*-panel-publish`下面`ant-tabs-nav`（50018），各Tab各自位于独立`ant-tabs-tab`包装节点（50026），按钮`*-tab-post`、Name=`play-square 发单条视频`、ControlType=50019，按同一nav和相同动态ID前缀的history/post成对验证。初次诊断误要求Tab直接同父而在点击前安全停止，证据保留attempt1；据真实树修正后23:43:46仅选择post一次，状态TASK_RECORD→SINGLE_VIDEO_PUBLISH→PUBLISH_FORM_READY，最终按钮0。已在表单时不重复导航；不使用坐标/OCR/图像。超时明确XIAOVCAT_SINGLE_VIDEO_PAGE_NOT_REACHED。

原Job1 ce40b544的零提交WAIT_FOR_STATE_TIMEOUT在本轮授权下通过一次性维修入口、原PlannerStore事务审计恢复原claim；claim_token/context/claimed_at/worker_id不变，原子claim仍仅1次，新增PRE_SUBMIT_NAVIGATION_RESUMED审计1条，不创建acceptance scope/计划/任务。维修入口仅在本轮runtime目录，不修改正式dispatcher，不是新的生产重试机制；已有最终提交预留即拒绝恢复。

23:47:53复用正式单组刷新339642，2个稳定账号重新核验并更新快照；23:47:57原-4 MP4标准文件对话框路径回读成功、不修改或复制源视频；23:48:00账号回读丙曜/抖音在线、selected=true，其它账号未选。随后`ready_actions.main(account)→PrepareUI.observe→checkbox element resolve`抛“控件已消失，必须重新观察”，在文案/话题/排期/validate/submit之前停止。Job1由原dispatcher.block保留为BLOCKED/NEEDS_MANUAL；后两条QUEUED、未领取。只读重新观察已成功，当前title/desc/item_title/text均空；证明账号动作完成但紧随其后的证据快照遇瞬时失效句柄，不能把后来只读成功冒称正式链继续成功。

本轮没有修账号/observe/状态检测，未扩大授权范围；不再次恢复这个新失败，不执行后两条。唯一下一步需用户授权处理账号动作后observe失效句柄的有界重新观察/安全恢复，再沿原Job继续；不得重建Plan/Job、清除提交闩锁或重算时刻。原计划52e11ba8仍CONFIRMED，3个原Job固定2026-10-05 09:00/12:00/15:00 +08；三条content均READY/SCHEDULED，未标SUBMITTED/PUBLISHED。全库Plan3/Job9（本计划3、历史6）/content34/run10/acceptance1不变，MP4 SHA均与原dry一致。提交0、重复0、新Plan/Job0、人工介入0，real_publish_enabled全程false，准备执行器已退出。

证据：`startup_pipeline/runtime/batch3_publish_final/single_navigation_20261004/RESULT.json`、`navigation_resume_job1/ACCOUNT_RECHECK_FINAL.json`、`ORIGINAL_FILE_SELECTION.json`、`RUN_ERROR.json`及只读重观察；最终`SINGLE_NAV_FINAL_RESULT.json`与REPORT.md。9文件py_compile、24个原方法AST、导航10/10、完整STARTUP206/206（包含维修保护6项及正式派发23项）、V0.4 21/21、Planner66/66，共303/303通过；完整STARTUP以UTF-8复跑耗时133.037秒（首轮206项有1项旧测试默认GBK读取UTF-8报错，失败日志保留）。不再修改或启动任务。

### 2026-10-04 23:29：正式PublishJob派发接线通过dry dispatch，真实执行发布子页阻塞（提交0）

`STARTUP_BATCH_3_AUTO_PUBLISH_PARTIAL`。只处理原正式plan `52e11ba8-fe9b-47f4-ae1f-74ed593712a9`与原ce40b544/c671a186/af6c16d3三条Job；Plan/Job/内容/排期/MP4均未重建。新`startup_pipeline/production_dispatch.py`/迁移008增加独立正式队列与配置old→new审计，Confirm原事务自动enqueue；ProductionScope来自原子claim后的正式数据库上下文，不读写startup_real_acceptance_jobs。迁移前一致性备份`operations.db.production-dispatch-20261004_230736_151016.bak`，外键通过。通过正式仓库仅将原3个Job简介改为“陶老师小妙招”、话题#健康/#健康科普/#养生、标题保持空；共享模板与原固定2026-10-05 09/12/15排期不变。

既有PrepareUI仅增加execution_scope入口，旧动作搬入正式ready_actions.py、历史CLI保留wrapper；控件方法/动作AST比对通过，V0.4提交闩锁模块未改。新production_worker整轮Windows互斥、job_id唯一原子claim、原最终Invoke最多一次、严格回读/状态关联，未知停后续；成功只登记SUBMITTED/SCHEDULED_QUEUED。正式service可从正常登录用户启动当前计划Worker，token走stdin；8502源码增加正式派发按钮/可选Confirm后自动执行，非验收脚本依赖。新UI源码尚未重载到8502（fileWatcher none，本轮未重启线上服务），不得宣称当前浏览器已部署新控件。

真实339642刷新和3/3 dry dispatch通过，执行范围/文案/媒体SHA/未来固定时间均正确、最终按钮0。23:08:49第一条原子领取，23:09:02旧page动作WAIT_FOR_STATE_TIMEOUT，队列BLOCKED、Job NEEDS_MANUAL；后两条QUEUED且未领取。只读UI179节点、read_errors0、无截断，外层publish已选、内层`rc-tabs-8-panel-history`仍“任务记录”；现有Worker缺“发单条视频”子页导航。归类EXISTING_WORKER_PUBLISH_SUBTAB_NOT_READY，不是视觉/快照/scope失败。按用户禁止改控件逻辑停止，不重派、不清claim/闩锁、不手动切页。

当前3条content仍READY/SCHEDULED，三条Job未提交；全库Plan3/Job9（历史6+当前3）/content34/run10/acceptance1均保持，新Plan/Job/acceptance均0，真实提交0、重复0、人工0，real_publish_enabled始终false，执行器已退出。MP4 SHA一致；Render/2060S/Jianying/SMB/权限核心未改。7文件py_compile通过；STARTUP199/199完整回归、收尾Confirm+Dispatch37/37、Planner66/66、原Worker21/21通过，早期import/fixture失败日志保留。REPORT与FINAL_RESULT及dry/真实失败/只读页面证据：`startup_pipeline/runtime/batch3_publish_final/`。下一步仅在用户允许补现有Worker发布子页导航后处理本条零提交BLOCKED的审计化恢复；本轮已停止，不标PASS。

### 2026-10-04 21:49：STARTUP_BATCH_3_PLAN_CONFIRM_READY（同一模拟计划原子升级，派发0）

真实计划`52e11ba8-fe9b-47f4-ae1f-74ed593712a9`在21:08由旧页面确认入口保存为TEST_ONLY，含3个NEEDS_MANUAL模拟任务，并把content.publish_status改为SCHEDULED。原Preview只读，不会创建记录；旧Confirm只支持simulation，后续_slots又不区分当前simulation与正式占用，导致CONTENT_ALREADY_SCHEDULED。并非Render/成片故障。

采用Promote，未取消重建。`startup_pipeline/plan_confirmation.py`读取原存储item直接校验（不调用排期器），仅允许同一员工、同一plan payload、content/account/path/profile/时刻完整一致且无其它任务/提交记录的模拟计划。确认前严格复核账号快照/在线/STARTUP授权/永久绑定、ffprobe与文件size/mtime、未来时间。`confirm_plan`在原BEGIN IMMEDIATE事务内把publish_plans.status升级CONFIRMED、items.test_only=0、metadata.dispatch_mode=CONFIRMED_NOT_DISPATCHED，原3个job保留NEEDS_MANUAL/current_step=STARTUP_CONFIRMED_NOT_DISPATCHED；不进入PENDING消费队列。startup_plan_confirmations记录确认人、时间、receipt及原状态；同一计划重复确认返回existing=3/created=0，无第二份计划。旧confirm模拟API保留兼容，页面Confirm已切换正式未派发入口；新Preview仍不写任何计划/任务。

迁移007保留原metadata全部行/索引/触发器、外键复核，扩展dispatch_mode并增加确认审计表；先复用现有迁移006的正式item能力，不改变单条已通过Worker。真实迁移前备份`operations.db.plan-confirmation-20261004_213046_613026.bak`，独立验收前快照在`startup_pipeline/runtime/confirm_promote_20261004/operations.before-confirm-20261004_213045.bak`，只留工作区内、不外传。

21:30:46账号快照仍在30分钟有效期内，用8502原app.py/正常员工登录/现有AppTest执行一次真实页面Confirm；不是伪造数据库，也不冒称浏览器视觉验收。当前-4/-5/-6原content ID、job ID、schedule_signature、原MP4与2026-10-05 09:00/12:00/15:00 +08全部保持。再次调用正式确认接口返回幂等existing=3，创建0。全库计划3→3、PublishJob9→9（当前3条由模拟激活为正式，新增行0），仅当前plan正式升级，其它历史数据不变。当前模板startup-default的空标题/空简介/无话题保持原值，本轮未套用其它历史发布模板。

页面恢复同一simulation/confirmed计划，显示“预览/未确认”或“已确认，3个发布任务已创建”，锁定原排期/账号/模板，正式后Confirm禁用。重新登录可从待发布池“已保存起号计划”查看同一计划；不重新选已安排内容、不新建第二份。最终STARTUP177/177、Planner66/66、Workbench19/19，共262/262通过（新增14项后端+2项页面测试）。首轮两个负向fixture因不可变触发器/签名保护提前拦截而报错，修正测试输入后重跑完整回归通过，未放宽生产保护，失败日志保留。

确认空闲生成锁后21:43:05仅重载原8502加载页面，wrapper24252/listener13360/0.0.0.0；21:49本机及LAN页面/health均200。Worker继续IDLE/current_job_id=null/正常心跳，content34/生成run10均未增加。未操作小V猫、Worker、Render/Jianying/SMB或成片；worker_dispatches=0、真实发布0、real_publish_enabled=false。本轮停止在正式任务未派发。REPORT、FINAL_RESULT.json、原确认及回归日志位于`startup_pipeline/runtime/confirm_promote_20261004/`。

### 2026-10-04 21:02：STARTUP Planner永久账号锁定与页内刷新验收通过，仅Preview

`STARTUP_BOUND_PLANNER_PREVIEW_PASS`。根因：原`publish_planner/ui.py::_plan_ui`将content绑定账号再与严格在线候选求交，30分钟快照过期使账号数组为空，继而INVALID_ACCOUNTS。现STARTUP READY入口从授权content的target_account_id/name快照提供只读身份，实际Plan账号强制取content绑定值；与当前在线快照分离。不同绑定账号在待发布池/Planner明确MULTIPLE_BOUND_ACCOUNTS，禁止改投。手动通用Planner未改变。

`startup_pipeline/ui.py::render_plan`新增“刷新发布账号”，复用原selector_refresh.refresh_startup_accounts，仅同步当前员工授权STARTUP组（suzhengchao为339642）；刷新不清除3个content_id/MP4选择。过期明确PUBLISH_ACCOUNT_SNAPSHOT_EXPIRED，不放宽Preview/Confirm/backend绑定、授权、在线、媒体和防重复规则。绑定入口默认daily_count等于所选视频数，本次3；原调度器不变。

20:54真实刷新遇ACCOUNT_PAGE_NOT_READY: UNKNOWN_DIALOG_NEEDS_MANUAL，保留原STAGES/reader.log并停止，不盲目关闭；用户明确回复“已关闭”后仅重试一次正式同步。21:01:15同步成功，稳定账号1621131832863931仍属339642，丙曜ONLINE/is_available=1。现有真实AppTest通过8502原app.py正常员工登录验证，而非宣称浏览器视觉验收；-4/-5/-6全部保留且账号控件disabled/稳定ID锁定，真实严格Preview返回2026-10-05 09:00、12:00、15:00 +08:00。未点击确认、未创建正式计划/PublishJob，历史PublishJob前后均6。

STARTUP161/161、Planner66/66、Workbench19/19，共246/246隔离回归通过；4项新增页面测试覆盖过期绑定、原入口刷新、失败保留选择、混账号拒绝。首轮沙箱临时目录WinError5后改用正常Windows权限运行同一测试，未更改测试条件/生产权限。8502 fileWatcher none，仅在持有空闲生成锁后21:00:42重载原实例，新listener13584/wrapper16692；localhost/LAN均200，LAN Worker继续IDLE/current_job_id=null/连续心跳。

本轮未生成视频/RenderJob、未重新Render/修改MP4、未改Render Worker/Jianying/SMB/Render API/READY核心/Planner后端/小V猫Worker/账号绑定约束。真实发布0，real_publish_enabled=false。备份`.bound-planner-20261004.bak`保留；REPORT、真实Preview及246项日志在`benchmark/experiments/dino_july_web/runtime/bound_planner_20261004/`。已停在Preview，不继续确认或提交。

### 2026-10-04 20:36：起号待发布池UI修复，三选进入原Planner，发布0

`STARTUP_READY_POOL_UI_FIXED`。只改`startup_pipeline/ui.py`页面接线与相关隔离测试；未改LAN Worker/2060S/Jianying/SMB/Render API/ffprobe/READY登记核心或发布安全。8502因fileWatcher none，在确认生成锁可独占后于20:34:41仅重载原8502服务，localhost/LAN health200；Worker继续IDLE/current_job_id=null/正常心跳。

用户截图批次`STARTUP_b8d97cf4e4aa4fefa1ba453a9c850f80`，content/RenderJob `STARTUP-9ddb9731-22f5-4a8d-91b0-562b1d858324`、丙曜-28：19:54:43生成，19:57:17.443已自动COMPLETED/VALIDATED并回传；当前业务READY/NOT_SCHEDULED、主机`outputs/lan_render/STARTUP-9ddb9731-22f5-4a8d-91b0-562b1d858324/丙曜起号10月4日-28.mp4`真实存在。H.264/AAC1080x1920/30fps/117.366667秒/64,174,044字节，主机重新ffprobe通过、SHA与回执均`e8d29ac62145d95250bda67c6361b04cb8b2aaf0c0018de036745d509e0bddc3`。截图None是成片登记前/尚未刷新的页面值，不是当前数据库；没有证据需要改READY核心。

原表格本来展示当前批次的所有生产状态，但多选候选也只限该批次，因此非READY最新批次会把历史Batch3/Batch10隐藏；原“加入发布”len!=1禁用，多选3条不能用该按钮；原空候选按钮实际已有disabled，缺明确等待提示。另“本批次全部”在工作区radio创建后改workspace_mode，存在Streamlit控件状态变更异常；现统一在on_click回调阶段切换并显示已带入数量。状态表展示production_status/render_status/publish_status/error，新增“刷新待发布池状态”。

现多选汇总当前员工全部批次，且限定授权STARTUP稳定账号、READY、NOT_SCHEDULED、主机MP4存在/非零、存档ffprobe视频流/时长有效、文件size/mtime与验收一致；不重跑Render、不为UI重新ffprobe所有文件。“本批次全部”仍只限当前批次；两个选择按钮均支持同账号多条，无READY禁用并说明等待导出，混账号拒绝、点击时重新验权限与文件。快照过期仍可查看READY/带入Planner，但明确PUBLISH_ACCOUNT_SNAPSHOT_EXPIRED且严格禁止确认任务，未刷新小V猫/伪造在线。

20:36真实库共有丙曜29条READY（29主机文件存在），其中-3历史SUBMITTED排除，28条未安排可选（-4到-31）。调查期间既有链路继续完成-31，不是本轮主动生成。真实现有AppTest以suzhengchao登录，选历史Batch3 -4/-5/-6，3个稳定content_id/MP4准确带入原Planner；快照最后同步14:32:51，过期警告可见且确认按钮disabled。PublishJob前后仍6，新增0、真实发布0、real_publish_enabled=false；不冒称远程浏览器视觉验收。

10项新增页面测试随STARTUP全回归157/157（96.678秒）、Planner66/66、Workbench19/19，共242/242通过，语法PASS。首次回归的相对import加载问题与旧fixture缺ffprobe媒体证据已在测试侧修正，未放宽生产成片规则。现有测试可在隔离库创建模拟任务，但没有写正式PublishJob。代码/旧测试/HANDOFF的`.ready-pool-20261004.bak`备份保留；机器证据及REPORT在`benchmark/experiments/dino_july_web/runtime/ready_pool_20261004/`。此轮已停止，不真实提交小V猫。

### 2026-10-04 19:44：员工LAN访问服务器侧完成，实际员工浏览器确认待补

`EMPLOYEE_LAN_WORKBENCH_PARTIAL`。PC-20260617GEOP / 192.168.1.126 的8502原本已监听0.0.0.0，未创建第二服务；最终只有1个监听、PID23716（venv父壳8636）。本机127.0.0.1与LAN地址页面/health均200；2060S DESKTOP-9VQ76D3在最终配置下跨机访问8502/health均200。入口为`http://192.168.1.126:8502`。

预检发现三个Windows防火墙Profile均关闭、旧8502规则Profile Any且python.exe路径不匹配实际pythonw；经用户明确批准，启用当前Private Profile，并收紧原`XunFrame-LAN-TCP-8502`为Private/TCP8502/LocalSubnet/EdgeTraversal Block。Program Any是为兼容venv底层pythonw，端口和子网限制仍保留。6条宽端口应用规则均有Windows应用包SID，不适用于该pythonw。没有修改Render8766/SMB445规则；2060S复核两共享可访问、Worker持续心跳IDLE/current_job_id=null。Domain/Public仍保持原先关闭，**本次网络限制只在当前Private网络生效；不宣称整机所有Profile已保护**，不要切换至Public后继续暴露该监听。

原app.py虽显示员工登录，却未使用render_session返回值阻断未登录素材搜索。本轮仅增加既有会话入口门槛并修正文案，未认证时st.stop，不加载工作区/素材；本机与LAN统一，未新增登录系统或更改角色/账号权限。仅8502因fileWatcher none进行重载加载代码，Render/Publish服务、Worker、Jianying及生产逻辑未改。

现有AppTest真实登录suzhengchao/EMPLOYEE成功；真实CLIP文字搜索“治疗肩颈的视频”返回20条，显示10条且10张JPEG可解析（3.275秒）。反馈仅写隔离测试库；EMPLOYEE无员工管理/同步账号Admin页签。现有UI19/19、Planner登录/权限66/66、LAN启动配置3/3通过，语法检查通过。ADMIN行为由隔离回归证明，不冒称真实管理员浏览器登录。首次Smoke脚本错取image而非thumbnail字段失败，修正诊断脚本后完整通过，不是生产搜索故障。

支持的浏览器通道DOM/截图持续超时，跨机HTTP和AppTest不能冒充员工浏览器端到端操作已完成。唯一验收待补：一台员工电脑浏览器打开LAN URL，用既有账号登录并完成一次普通搜索，确认结果/缩略图出现；不生成视频，不发布。补证前不标记EMPLOYEE_LAN_WORKBENCH_READY。报告与机器证据在`benchmark/experiments/dino_july_web/runtime/employee_lan_20261004/REPORT.md`及`EVIDENCE.json`，原文件均有`.employee-lan-20261004.bak`备份。

前后业务总数仍30 contents/8 generation runs/6历史PublishJobs，Render队列仍22条，新增均0；未生成草稿/Render/PublishJob，真实发布0，real_publish_enabled=false。素材库/FAISS及模型未改，未增加HTTPS/公网/代理/新安全架构。此轮停止，不继续生产。

### 2026-10-04 19:10：LAN_WORKER_REBOOT_AUTOSTART_PASS（只读补证完成）

维护连接恢复后只读核验真实boot为18:35:04.500；sdaffwS Session 1登录事件21为18:35:14.027，XUNZHEN_RENDER_WORKER LastRun=18:35:14、Running、Result=267009/0x41301（运行中）。AtLogOn固定sdaffwS/Interactive、IgnoreNew及原启动参数/工作目录不变。Worker父壳9312启动18:35:14.146，实际解释器11728启动18:35:15.944；父壳父PID2856实证由Schedule服务持有，只有1条正式进程链，无旧agent或独立重复Worker。Server首次恢复ONLINE为18:35:22.463，boot→Session/Task→Worker→ONLINE时间一致，57条连续注册/心跳历史及19:10:09.605新心跳验证持续恢复，最终IDLE/current_job_id=null。

2060S实际IPv4仍192.168.1.89；只读Test-Path确认StartupAssets及RenderOutput两共享均可访问，无JianyingPro/ffmpeg活动进程。TaskScheduler Operational日志未启用，未改配置启用；自动触发由登录事件、LastRun、原AtLogOn配置、Schedule服务进程父链与时间线确认，不编造不存在的触发日志。全程未人工启动Worker；Remote Desktop Commander只做设备重启/维护观察，不参与生产启动。22条队列身份状态与基线一致、未完成0，RenderJob/PublishJob新增0、真实发布0，real_publish_enabled=false（主机及Worker health）。没有再重启、生成视频、启动剪映或修改生产配置。

最终REPORT及完整机器证据：startup_render/runtime/reboot_acceptance_20261004/REPORT.md、FINAL_RESULT.json；此前PARTIAL、连接失败证据及原报告备份保留为历史，不回滚已通过LAN生产与Batch10。HANDOFF修改前备份HANDOFF.md.reboot-pass-20261004_1910.bak。收口后停止，不继续其它开发。

### 2026-10-04 19:03：重启只读补证仍被维护连接Offline阻断

用户报告2060S维护连接已恢复后，实际Remote Desktop Commander命令返回无Online设备；设备列表DESKTOP-9VQ76D3为Offline，20秒后重查仍Offline/Last seen 34分钟前。boot/Task/PID/SMB查询未执行，不伪写PASS。主机真实读取Worker 19:03:08.372心跳、IDLE、current_job_id=null；未完成任务0、队列仍22条、PublishJob历史6/新增0、real_publish_enabled=false。没有启动Worker/剪映/任务、生成视频、修改生产配置或再次重启。REBOOT_ACCEPTANCE_PARTIAL保持，只需修复维护客户端到正确账户的Online连接再补只读证据。报告及原始返回：startup_render/runtime/reboot_acceptance_20261004/REPORT.md、SUPPLEMENT_CHECK_1903.json。HANDOFF修改前备份HANDOFF.md.reboot-evidence-20261004_1903.bak。既有生产就绪与Batch10结果完整保留。

### 2026-10-04：LAN Worker重启验收部分完成（自动心跳已恢复，维护证据待补）

本轮仅允许2060S正常重启，不生成内容/RenderJob/PublishJob，不启动剪映/小V猫，不改核心代码和数据库结构。重启前主机无未完成任务；Worker IDLE、current_job_id=null。真实计划任务XUNZHEN_RENDER_WORKER为sdaffwS/Interactive/AtLogOn、IgnoreNew、失败重启3次/1分钟，解释器/工作目录/配置存在且server_url、worker_id正确。原两PID为venv父启动壳22612及子解释器24408，一条Worker进程链，不认定双实例。

18:33:45首次shutdown命令返回203，确认旧boot未改变后，18:34:17仅对DESKTOP-9VQ76D3发出Restart-Computer正常重启，无Force。服务器未重启。主机收到恢复后首次ONLINE注册/心跳记录18:35:22.463，约65.462秒；截至18:41:34.320有57条连续注册/心跳记录，超过3个20秒周期，最终IDLE且无current_job_id。全程没有手动运行/修复Worker进程，正式API恢复已实证。

尚不能宣称LAN_WORKER_REBOOT_AUTOSTART_PASS：重启后Remote Desktop Commander维护命令两次无响应，已停止等待；其设备列表缓存Online/Last seen不能作为真实连接证据。尚缺重启后boot、Session与Task触发/PID单实例、2060S本机SMB访问实证。不能把观察通道故障判为Worker故障或WINDOWS_INTERACTIVE_LOGIN_REQUIRED；已恢复IDLE与该猜测不符。只请求用户恢复Remote Desktop Commander维护连接，不手工启动Worker。本轮REBOOT_ACCEPTANCE_PARTIAL，既有LAN生产与Batch10 PASS保持，不回滚。RenderJob集合22条未变、未完成0、PublishJob总数6/新增0、真实发布0，real_publish_enabled=false。

证据及20项报告：`startup_render/runtime/reboot_acceptance_20261004/REPORT.md`、REMOTE_BEFORE.json、SERVER_BEFORE.json、SERVER_AFTER.json、RECOVERY_HISTORY.json。下一步仅补只读核验，不再次重启、不运行生产任务。HANDOFF修改前备份HANDOFF.md.reboot-acceptance-20261004.bak。

### 2026-10-04：LAN常驻Worker最终收口（停止扩展）

按用户最新指令，仅只读复核和更新文档，未修改核心逻辑、重新Render、生成新草稿或发布。`CLOSURE_CHECK.json`确认未完成RenderJob为0，当前LAN Batch10仍为10/10 READY；Worker `WORKER-2060S-01`为IDLE、current_job_id=null，最近核验心跳为2026-10-04 18:24:13 +08:00。2060S真实计划任务`XUNZHEN_RENDER_WORKER`仍Running，用户sdaffwS、Interactive；服务器专用任务仍Running。未发现仍运行的验收/回归测试命令，不终止常驻Worker或线上工作台。

正式任务使用LAN HTTP JSON与SMB，不依赖Remote Desktop Commander；本次远程命令仅用于只读核验计划任务。既有359/359回归结果采用已完成记录，不新增或继续扩展DPAPI/security测试。PublishJob历史总数6、本轮新增0，真实发布0，real_publish_enabled=false。最终结论`LAN_RESIDENT_RENDER_WORKER_PRODUCTION_READY`，完整收口报告为`startup_render/runtime/lan_resident_v1/REPORT.md`。OS重启/注销触发实测、真实网络故障注入、连续资源采样及额外安全测试列为非阻塞FOLLOW-UP，不继续实施。修改前备份`HANDOFF.md.lan-closure-20261004.bak`。

### 2026-10-04 18:01：LAN_RESIDENT_RENDER_WORKER_PRODUCTION_READY（真实单条+LAN Batch10通过）

最新用户要求优先LAN常驻化。此前后台旧Batch10已经实际开始，未中断导出、未伪认成新LAN证据：原batch `STARTUP_0619bf21a1eb4fe8bcd7eeb8134ab6eb`的-7至-16全部COMPLETED/READY/NOT_SCHEDULED，主机10条文件SHA及ffprobe再次通过，生成至最后回传1470.203秒（平均147.020）。原沙箱草稿写权限错误仅在零成功/零content/零Render时同batch以正常权限有界恢复，失败清单归档保留；没有重Render、第二批补结果或发布。旧Batch10结果在`startup_render/runtime/batch10_20261004_1630/FINAL_ACCEPTANCE.json`，transport明确LEGACY_HTTP_NOT_LAN_RESIDENT_V1。

本轮增量层：LAN JSON API/Worker注册/独立20秒心跳/原子固定所有者租约/幂等回执、SMB本地staging/SHA缓存及返回、交互用户登录计划任务。原Generation、账号绑定、RenderJob内容规则、草稿安装函数、专用Launcher检查和render_child逻辑保持；Agent仅增加可选transport/jobs_root/output钩子。两端4个关键函数跨Python版本规范化AST一致。`completion.py`/Planner/小V猫Worker未改，不创建发布任务。

真实Server `PC-20260617GEOP / 192.168.1.126`、2060S `DESKTOP-9VQ76D3 / 192.168.1.89`，均IPv4 /24、网关192.168.1.1、以太网，双向ping通过。LAN地址`http://192.168.1.126:8766`只绑定当前LAN地址，固定客户端+所有API Bearer token。host/IP配置可换（含127.0.0.1），未改IP/DNS/路由器；建议后续DHCP reservation。附加LAN表通过`startup_render/migrations/001_lan_resident.sql`，同一原RenderQueue数据库，没有第二个生产队列。

共享`\\PC-20260617GEOP\StartupAssets`指向现有`E:/备份/起号手法`只读；`StartupTaskFiles`是原同队列packages，只读冻结任务JSON和不在主素材目录的模板依赖；`RenderOutput`指向`D:/video_search_tool/outputs/lan_render`可写。新专用XunZhenRender账户，无Everyone Full Control；三共享SMB加密，专用账户对原Users共享显式拒绝。原ForceGuest=1导致SMB1272已实证定位并改为认证共享，原值SMB_AUTH_BEFORE.json保留；没启用不安全Guest。服务器LAN标记Private，Render API与SMB入站改Private，防火墙未关闭。密码/token仅DPAPI或Credential Manager，部署交付用RSA加密，不放前端/明文配置/日志。

2060S常驻`XUNZHEN_RENDER_WORKER`已真实Running：sdaffwS、Interactive/AtLogOn、隐藏pythonw、忽略重复实例、失败重启3次/1分钟；旧agent任务Disabled避免双实例，服务器原专用任务改为lan_server，8501/8502未停。用户必须保持登录和可用交互桌面；锁定INTERACTIVE_SESSION_REQUIRED不解锁，登录/版本错误保持心跳但停止领取。原专用5.9入口及EXE/SHA/签名检查继续原样使用；不增加UI控制栈。

真实API/SMB非生产Smoke PASS：本机register/heartbeat/claim及重复回执、tiny.txt往返SHA一致，无剪映调用。新LAN单条`STARTUP_b54e253c653b42bba9c95cf0a89de752`，content/RenderJob `STARTUP-b1f09875-0db4-4515-9bdd-fcce8d5ec6fa`、丙曜1621131832863931、真实名称-17；LAN_SINGLE_RENDER_PASS，129.811秒，H.264/AAC1080x1920/30fps/79.033秒/42,044,411字节，SHA14bd6005b69993255d6891f63c45a54385a02214cd1a0aba5282247602597c33。Worker本地Jobs/content/output同名MP4，SMB自动回主机lan_render/content/同名MP4，原完成服务READY且NOT_SCHEDULED。生产操作未用Remote Desktop Commander，只用其部署/维护。

随后严格按新授权生成新LAN Batch10 `STARTUP_1d175c3e9fef4524b5ead7d62bd5a077`，10个独立content/job，丙曜-18至-27，不复用旧Batch10。10/10全部自动成片/回传/主机SHA及ffprobe/READY且NOT_SCHEDULED；1436.214秒（23分56.214秒）、平均143.621秒、吞吐25.066条/小时。10个正式草稿名/metadata ID/必要internal UUID/组合签名独立且正确，领取/EXPORTING严格无重叠，所有剪映实例正常退出。20秒独立心跳导出中真实持续，每条5–9个样本、最大间隔20.150秒；合计缓存命中151次。后3条处理均值122.885秒、前3条107.916秒（1.139倍，不同视频时长影响，未自动改架构）。常驻主Worker终态RSS约20.3MiB、峰值约30.8MiB（另有venv父启动壳），系统可用内存约7.24GiB、D盘剩余114.17GiB。新LAN批次没有首/第五条全过程内存快照，只有终态/峰值；旧Batch10的边界样本单独保留，**不拿旧资源样本冒认新LAN批次指标**。

`LAN_RESIDENT_RENDER_WORKER_PRODUCTION_READY`按新LAN功能验收标准成立。20项新增LAN测试+原Render101、Startup147、Planner66、小V猫25，共359/359隔离回归通过；完整日志REGRESSION.log/JSON（负向测试的预期错误不是生产失败）。real_publish_enabled=false，历史PublishJob仍6，本轮新增0、真实发布0。最新26项机器报告FINAL_REPORT.json、单条及Batch10 FINAL_ACCEPTANCE.json、BATCH10_DETAILED_AUDIT.json、HEARTBEAT_AND_CACHE.json、SMOKE_RESULT.json及真实主机MP4均保留。Remote Desktop Commander只有部署/终态只读维修核验，没有参与真实任务领取、备料、导出、成片传输或READY写入。未进行OS重启/注销自启动实测或真实网络断线注入；AtLogOn配置及实际Task启动已核验，HTTP/SMB有界断线恢复隔离测试通过。登录保持、用户交互桌面需持续可用。

验收完成时无在途/PENDING/QUEUED生产任务，常驻两端服务保持Running/Worker IDLE，旧agent仍Disabled。CLAIM_CONTROL切为RESIDENT_PRODUCTION（不限制特定验收batch），以后正式Generation事件产生的新STARTUP任务可以自动领取；没有自行生成第12条LAN视频或更大批量。所有历史失败/本次隔离Smoke明确终态保留，不自动重Render。完成后不继续发布链。

前一请求的生产/发布资格最小解耦也已保留：generation选择器/名称预留用`get_generation_accounts`，要求有效员工、稳定授权组、启用账号和历史真实身份，不要求当前在线/30分钟TTL；现有严格发布接口/计划器仍校验新鲜在线快照，过期PUBLISH_ACCOUNT_SNAPSHOT_EXPIRED。测试包含过期生成/Render/READY可行及发布拒绝，未调用小V猫刷新、未伪造同步状态。不要回退这项解耦。

### 2026-10-04 16:16：10条稳定性验收在生成前被账号快照过期阻断

`STARTUP_BATCH_10_STABILITY_PARTIAL`，尚未生成batch或预留序号，新增content/RenderJob/草稿/MP4/READY/PublishJob均0，真实发布0。真实suzhengchao会话的STARTUP候选接口返回空；339642/STARTUP稳定绑定仍enabled=1，丙曜1621131832863931身份未变。快照最后同步14:32:51，30分钟有效期于15:02:51到期，16:16:49检查时已过期；缓存ONLINE不代表当前在线。

本轮用户禁止调用小V猫，因此未调用单组同步、未放宽TTL、未伪造同步时间，未修改任何核心生产逻辑或运行配置。需要用户在8502起号自动合成点击一次“刷新账号”后确认，再从正式Generation count=10继续。2060S在线，专用agent仍Ready，无剪映/FFmpeg活跃进程；本轮两端监听均未启动。原Render回归101/101通过（5.583秒），业务总数仍9 contents/4 generation bindings/6 PublishJobs，两端real_publish_enabled=false。前轮3条READY与历史失败保持完整，不能把旧批次当本轮10条验收结果。

29项未执行/已检查状态和证据：`startup_render/runtime/batch10_preflight_20261004_1616/REPORT.md`、PRECHECK.json、REGRESSION_TESTS.txt。HANDOFF修改前备份HANDOFF.md.batch10-preflight-20261004_1616.bak。当前停止等待快照刷新。

### 2026-10-04 15:11：STARTUP三条批量Render真实验收PASS，发布0

`STARTUP_BATCH_3_RENDER_PASS`。一次8502同一正式Generation count=3（begin→generate_batch→complete），batch `STARTUP_b681bc5228bb43018cdfb6d4556a7af4`；丙曜1621131832863931，真实序号草稿-4/-5/-6。三个content/RenderJob分别`STARTUP-848418c8-295f-4776-9eaa-caf83a93b5f1`、`STARTUP-1e4ca507-7cc6-46dc-9ce9-6361110a8418`、`STARTUP-a16c1f3b-2dbc-41ca-9c9d-8eb157a3e73e`。三组composition_signature/draft_id/main/internal IDs独立；Worker领取、剪映导出、严格ffprobe、回传、主机READY全部串行，前条主机成功回执保存早于下条领取。三条媒体资源31/29/33个自动迁移并逐SHA复核，未手工补文件或点击导出。

三次均使用原专用`D:/JianyingRenderWorker/Scripts/START_JIANYING59_WORKER.ps1`、5.9.0.11632固定EXE/SHA；已有HEVC→H.264规范流程自动执行，不重Render。最终三条H.264/AAC、1080×1920、30fps、2流，时长83.900000/69.101995/86.133333秒，大小53,271,201/39,856,117/49,597,710字节；两端文件SHA一致。主机输出`outputs/startup_exports/STARTUP_b681bc5228bb43018cdfb6d4556a7af4/丙曜起号10月4日-{4,5,6}.mp4`，原内容3/3 READY且NOT_SCHEDULED，原待发布池新增3条。

正式生成15:04:51.097939至最终主机成功回执15:11:04.772309总373.674秒，平均124.558秒/条；剪映导出60.203/54.891/62.454秒。人工干预0，PublishJob新增0（6→6），真实发布0，没有调用小V猫，两端real_publish_enabled始终false。单条生产核心两端SHA未变；既有Render回归101/101通过，另一次沙箱测试夹具权限错误保留说明。未进行真实失败注入；原Worker失败后暂停继续领取的fail-closed行为未改，不能宣称验证失败后自动继续。

确认导出/转码均退出后停止本轮两端专用Render监听（scheduled task Ready、无残留进程），8501/8502仍运行；未继续5/10条任务。完整22项报告和机器证据在`startup_render/runtime/batch3_20261004_1500/REPORT.md`、FINAL_ACCEPTANCE.json及自动receipts。HANDOFF修改前备份HANDOFF.md.batch3-20261004_1500.bak。等待用户确认下一轮。

### 2026-10-04 14:48：用户明确方案2，原READY单条已真实定时提交成功

按本次用户“真实提交成功且取得现有系统成功证据”的验收边界，`STARTUP_FULL_CLOSED_LOOP_PASS`：原content `STARTUP-a212b58e-12de-4dd7-a586-779257e02792`、唯一PublishJob `0716cc5f-1cb5-48a1-aada-b29297a91a04`，沿用已READY的`丙曜起号10月4日-3.mp4`。本次新增content/RenderJob/PublishJob均0，不重渲染、不修改视频，SHA保持6801b1894fdaf6aab6f220257ce3796321f4fd8a269644a8c9db84d964b52abc。用户明确历史测试模板后只更新原任务的授权载荷，未修改全局默认模板；此前参数权限拒绝证据完整保留。

账号丙曜/抖音1621131832863931与内容target_account_id相等；STARTUP339642实时同步后在线。提交前无历史提交预留/成功记录；两侧UI空标题、简介“陶老师小妙招”、实际话题健康/健康科普/养生、默认视频封面未另选图片，回读全部通过。既有Planner重新验证今天16:42合法未来定时，14:41:01.098仅调用一次“一键分发”，持久化唯一V04_FINAL_SUBMIT_RESERVED在调用前完成；单任务内存真实许可14:41:01.110已关闭，全局real_publish_enabled始终false。

小V猫提示“发布任务已创建，已在后台执行中”，唯一匹配本MP4/丙曜/本次创建时间/16:42的任务状态“已同步”，耗时1分13秒；只读保存后任务详情再次验证空标题、精确简介及3个话题。operations.db的Job为SCHEDULED_QUEUED，内容production_status仍READY、publish_status为SUBMITTED，已登记内部content→Job映射；不写PUBLISHED、不编造work_id/URL。**本轮PASS指官方定时提交闭环，不宣称16:42尚未到达时作品已经公开。** 到时平台公开结果未核验，work_id/URL/外部task_id目前未取得。没有重试提交、消费其它任务或继续生产。

证据：`startup_render/runtime/closed_loop_20261004_post_login_01/publish/POST_SUBMIT_CHECK.json`、SUBMIT_RESULT、TASK_PROGRESS_VERIFIED_UI、TASK_DETAIL_READBACK及真实截图。当前RESULT.json与REPORT.md更新；此前失败RESULT保存为RESULT_BEFORE_CONFIRMED_SUBMISSION.json。登记前备份operations.db.submission-audit-20261004_144832.bak。现有防重复/提交前测试本轮21/21通过；产品Worker/Planner核心本轮未修改。完成后停止，不自动发第二条。

### 2026-10-04：登录后正式单条Render已READY；真实发布被参数权限审核阻止

最新真实状态：`LOCAL_JIANYING_RENDER_PASS`，新正式RenderJob真实`COMPLETED`、业务内容`READY`。**不是STARTUP_FULL_CLOSED_LOOP_PASS**：最终提交命令在进程创建前被权限审核拒绝，没有点击“一键分发”、没有持久化提交预留，真实提交0次。需要用户明确选择本次发布文案；不能绕过审核、换间接命令提交或自动改用旧测试文案。

用户在2060S完成一次登录后，原隔离导出自然继续；没有重新导出/人工点击导出。隔离MP4为`D:/Users/视频/丙曜起号10月4日-2-ISOLATED_INSTALL_POC.mp4`，13:21:18创建、13:21:47写完，89,140,497字节、H.264/AAC、1080×1920、30fps、71.266667秒、2流，SHA256 `40a4b5120c65770e2dcb9bf81fd4f108826d3ef0affe956325b83147afb0ea40`。原登录失败attempt保留，隔离成功没有提升历史生产内容。原Worker增加登录窗口前置/等待中检查，明确JIANYING_LOGIN_REQUIRED并停止；未操作登录凭证，没有新增UI控制栈。

本轮严格只生成1条：8502同一后台入口`StartupContentRegistration.begin → jianying_adapter.generate_batch → complete`，员工上下文和真实随机选料贯穿。generation `2bcc2960-072d-47e0-85af-42a96a54a62a`；batch `STARTUP_2bcc2960072d47e085af42a96a54a62a`；content/RenderJob `STARTUP-a212b58e-12de-4dd7-a586-779257e02792`；正式草稿`丙曜起号10月4日-3`，序号来自数据库，目标丙曜1621131832863931。4个主素材加模板依赖，共46个媒体文件/4个JSON自动交接；48个资源引用已验证，逐源路径→Worker路径及SHA见回执。

2060S 13:36:31自动领取、13:36:37安装到实际`D:/JianyingPro Drafts`，独立metadata ID `5D28E89F-9C94-4E65-A098-1BF74852F2AC`和content内部ID `5275754A-167D-4C11-A685-7FFFAC46553F`。13:36:43仅通过`D:/JianyingRenderWorker/Scripts/START_JIANYING59_WORKER.ps1`启动专用5.9 PID12164；EXE `D:/JianyingRenderWorker/JianyingPro/5.9.0.11632/JianyingPro.exe`，SHA `BA941A875E7E4C4BBD3200733C10836C21E07DF726195F7102B3107874EF07D9`，签名Valid。登录检查无阻塞窗口；真实列表精确发现完整名称，13:37:12自动打开，13:38:23自动导出，耗时85.406秒，13:38:29正常关闭/全进程退出。无人工生成/传料/打开/导出。

真实首次成片是HEVC/AAC，被既有严格H.264验收拒绝；没有假报成功或另生成/重导出。保留原HEVC MP4/SHA及首次失败回执；新增可配置`normalize_h264_output`复用本机FFmpeg/libx264，只把已导出的HEVC规范成H.264（52.781秒，AAC不重编码）。默认关闭以兼容原Worker，仅本轮2060S配置启用。严格ffprobe不放宽。本轮唯一job经GENERATION_RESULT、run、原失败指纹、原MP4 SHA、已导出/已正常关闭事件和账号绑定限定的validation-only恢复，**不调用renderer/tick/claim/桌面**；历史失败默认仍不可变。恢复通过原自动upload/post_receipt/主机SHA+ffprobe+完成服务，在13:49:52回传完成并进入原READY池。

最终两端MP4同名：2060S `D:/JianyingRenderWorker/Exports/startup/STARTUP_2bcc2960072d47e085af42a96a54a62a/丙曜起号10月4日-3.mp4`；主机 `D:/video_search_tool/outputs/startup_exports/STARTUP_2bcc2960072d47e085af42a96a54a62a/丙曜起号10月4日-3.mp4`。78,302,376字节、H.264/AAC、1080×1920、30fps、141.133333秒，SHA256 `6801b1894fdaf6aab6f220257ce3796321f4fd8a269644a8c9db84d964b52abc`。2060S health.json保留首轮NEEDS_MANUAL停机快照；当前COMPLETED证据来自恢复回执和主机RenderDB，不能用陈旧health声称再次领取或重导出。

正式发布桥接只限定当前READY池内容，不消费通用队列：migration006备份/保留旧行/FK核验，旧Planner默认SIMULATION_ONLY仍不变；新`startup_real_acceptance_jobs`以content/run唯一约束绑定一个Job。仅将原V0.4 Prepare/Precheck/Submit参数化复用同一套已验证UI动作/最终唯一Invoke；没有新UIA、坐标、远控或视觉绕过。现有起号默认模板实际是空标题/空简介/空话题、DEFAULT封面；最新用户要求复用默认模板，但历史V0.4曾指定“陶老师小妙招”+三个健康话题。审核认为参数有歧义，最终外部提交被拒绝；当前不能自行选择另一套文案。

PublishJob仅新增1个 `0716cc5f-1cb5-48a1-aada-b29297a91a04`，已用现有Worker加载真实MP4、选唯一在线丙曜、回读空模板/0话题/默认封面，两侧计划16:17通过PRE_SUBMIT_CHECK，但**未进入小V猫定时队列**。Job现为NEEDS_MANUAL / AWAITING_PUBLISH_PROFILE_CONFIRMATION；内容production_status仍READY，本地publish_status=SCHEDULED仅表示计划预留，不是平台发布。等待用户文案确认后只能继续这个Job，先重新校验/调整将过期的计划和账号快照；禁止创建第二个content/Job或盲重提。所有全局发布开关始终false，单任务最终许可没有启用。历史PublishJob5→6，新发布记录0，旧失败content/RenderJob未提升。

证据：`startup_render/runtime/closed_loop_20261004_post_login_01/{RESULT.json,REPORT.md,ISOLATED_AFTER_LOGIN.json,GENERATION_RESULT.json,VALIDATION_RECOVERY_APPROVAL.json,server/receipts/}`及`publish/{JOB_CREATED.json,PRE_SUBMIT_CHECK.json,FINAL_LIVE_UI.json,PERMISSION_REVIEW_BLOCK.json}`。最终Render101/101（6.209秒）、完整起号/权限/计划/既有Worker171/171（86.025秒），合计272项通过，包含本轮36项新增测试；首轮62/62、最终话题16/16是其中子集不重复加总。首次unittest discover相对导入失败是命令错误，已改用模块列表171项通过，不隐瞒失败。HANDOFF与模块README修改前均已备份；未停止8501/8502、未改模型/索引/素材源文件。

### 2026-10-04：2060S LOCAL FUNCTIONAL ACCEPTANCE，真实剪映登录阻塞

用户明确改用已有本机Worker功能输出作为验收，不再要求Codex远程视觉通道。本轮未研究ToDesk/截图，不新增UIA控制层或坐标脚本；实际从2060S原环境调用现有`startup_render.agent.render_child`，复用原pyJianYingDraft、专用Launcher与正常关闭/发现/打开/导出流程。上一条REMOTE_UI_CHANNEL_UNAVAILABLE不再作为本轮停止理由。

先定位并最小修复安装检查器：GOOD和已打开TEST的根目录`draft_biz_config.json`均为剪映生成的零字节辅助占位文件，原rglob全部JSON严格解析因此先报JSONDecodeError。仅此根目录文件允许空并在证据中显式记录；非空损坏该文件、其它空JSON、subdraft内同名空文件仍失败，核心与资源检查没有放宽。修改仅`draft_install.py`和4项测试；2060S已部署这个检查器。20/20安装检查测试通过，相关生命周期/专用入口/安装/失败传播68/68通过（11.507秒），无真实桌面操作的Mock/临时库测试。现有agent.py、5.9Launcher/EXE、小V猫Worker未修改。

隔离执行attempt_01：12:59:42 +08:00开始，精确核验TEST名称`丙曜起号10月4日-2-ISOLATED_INSTALL_POC`、draft_id 7EDC61A2-B9DA-4e10-B671-FA42CD144C91、internal content id 3E0D8888-86A2-4041-9760-4676B448FECF、实际路径D:/JianyingPro Drafts/完整名称；97个资源引用全部存在。12:59:44通过唯一专用入口启动PID27424，版本5.9.0.11632、SHA BA941A875E7E4C4BBD3200733C10836C21E07DF726195F7102B3107874EF07D9、签名Valid。12:59:52原Worker机器回读完整名称JIANYING_DRAFT_VISIBLE，12:59:54调用原自动导出，13:00:07自动打开记录JIANYING_DRAFT_OPENED。这是实际本机自动发现/打开证据，不再仅文件has_draft。

随后未产生MP4。复用现有只读窗口清单核验到同PID真实`登录`窗口：visible=true、enabled=true，HWND0x10007b8；导出窗口visible=true、enabled=false，HWND0x2630a22，主编辑窗口同样禁用。当前会话为console Session1/Default，不是未解锁或错Session；未读取登录表单/凭证、未操作认证、没有声称需要购买VIP。真实failure_code为`JIANYING_LOGIN_REQUIRED`，结论HARD_EXTERNAL_BLOCKER。仅在命令行/父PID核验后停止本轮隔离Python PID25800，确认其进程退出；没有停止剪映、没有终止实际编码进程，保留登录和导出现场。13:12:05保存终态，并备份停止前RUNNING结果；这不是原库正常返回或超时报错，明确记录`execution_stop`，未伪造导出完成。

指定隔离目标MP4及原库默认D:/Users/视频/同名MP4均不存在，ffprobe未执行；不标记LOCAL_JIANYING_RENDER_PASS。未重载服务/武装新生产run、未生成新content/RenderJob/PublishJob；业务库SHA仍87e3df53fb9910a63d35160c17d1b555588fe53fffe45578545b832b5207e7b7，content5/generation3/PublishJob历史5新增0，真实发布0，两端real_publish_enabled=false，原失败业务/渲染终态保留。

当前唯一必要人工动作：在2060S当前剪映5.9登录窗口完成登录，不要手工导出；完成后再继续原本机功能验收。隔离成功以前不可开始正式新content或发布。证据`startup_render/runtime/local_functional_20261004/attempt_01/{RESULT.json,events.json,version_check_before_restart.json}`、`REPORT.md`；2060S原证据同相对目录。HANDOFF备份`HANDOFF.md.local-functional-20261004_1312.bak`，安装检查器及测试备份后缀`.local-functional-v01.bak`。本轮按真实认证外部阻塞停止。

### 2026-10-04：STARTUP FULL CLOSED-LOOP 前置核验，HARD_EXTERNAL_BLOCKER

用户最新授权最多6轮隔离验证、3个全新正式content，只有Render/READY/账号绑定/PublishJob全通过后才允许丙曜1621131832863931一次真实提交。本轮没有把该授权误当已有闭环成功：实际停在2060S桌面通道边界，验收层failure_code为`REMOTE_UI_CHANNEL_UNAVAILABLE`，不是新RenderJob失败。computer-use支持窗口清单仅服务器Codex/Quark/小V猫/VPN，没有2060S剪映；Remote Desktop Commander可读远端文件、进程及终端，但无原生桌面控制接口。遵循computer-use技能，不另写远程UIA或自制桌面协议绕过，不重复研究此前两次ToDesk捕获超时，不请求中间人工点导出。

12:39 +08:00真实核验：2060S剪映指定5.9路径进程21404及子进程正在运行；这不是本轮Launcher启动、签名检查或UI状态通过的证据。既有Worker计划任务Ready，health最后07:20:27为HALTED_NEEDS_MANUAL，当前未返回startup_render Python进程；8502健康ok、8766健康LISTENING_FOR_NEW_OWNED_BATCHES，原run单条限额已由旧失败占用。没有重启服务、重新领取或解除旧终态；未来新验收需要独立run/attempt，不可覆写旧失败。

上一只读查找证据已归档本机：pyJianYingDraft文件枚举35个目录，其中32个带索引/metadata身份、3个缓存/回收站非草稿目录；完整TEST名称`丙曜起号10月4日-2-ISOLATED_INSTALL_POC`与metadata/index/路径9项严格核验通过，真实draft_id为7EDC61A2-B9DA-4e10-B671-FA42CD144C91。31个旧草稿仅索引ID可读、metadata不可解析，未猜测/解密。文件has_draft通过不等于UI lookup通过；UI枚举/自动发现/打开/导出仍未执行，人工长名可见确认仅保留为历史证据。

本轮正常本机权限下重新运行生命周期/专用入口/安装/失败传播四组Mock与临时库测试，64/64通过，11.336秒；首次受限环境夹具因临时目录PermissionError失败，重试并非修改产品安全条件。未改业务源码、草稿、索引或生产数据库；operations.db SHA前后均87e3df53fb9910a63d35160c17d1b555588fe53fffe45578545b832b5207e7b7。旧content RENDER_FAILED、旧RenderJob NEEDS_MANUAL保留；本轮新content/RenderJob/PublishJob/真实发布均0，PublishJob历史总5；两端real_publish_enabled=false。没有导出/回传/READY/发布成功的新证据，不标记STARTUP_FULL_CLOSED_LOOP_PASS。

证据：`startup_render/runtime/closed_loop_preflight_20261004/RESULT.json`、`REPORT.md`及`startup_render/runtime/exact_lookup_20261004/RESULT.json`。HANDOFF备份`HANDOFF.md.closed-loop-preflight-20261004_1243.bak`。当前仅需恢复可由支持工具访问的2060S桌面通道；本轮按真实外部阻塞停止，不继续生成生产内容。

### 2026-10-04：JY59_DRAFT_VISIBILITY_ROOT_CAUSE_NARROWED，用户回读确认TEST已可见

本轮只读差分，无草稿/索引/业务修改，无应用启动/关闭/输入/导出。用户最初报告TEST不可见，提供第三可见草稿名“丙曜起号10月4日-2”；只读索引没有该短名独立条目，仅存在TEST长名条目。进一步询问完整标题后用户明确回答“是的，是你发出来这条长名”，因此更新为`TEST_VISIBLE_HUMAN_CONFIRMED`：此轮首要问题是长标题显示/识别歧义，不是已证实的剪映拒绝登记。不能把GOOD_B与TEST当两个独立样本，不伪造第三个普通可见草稿。此结论不是Worker自动发现/打开/导出通过，不升级FIX_READY或生产E2EPASS。

root_meta与073210备份字节完全一致、结构完全一致、36条，GOOD/TEST字段无变化，SHA37F9C8BF17A7542BF291340F8CCA0760ADE00E50BD6B0CBDDD7C9987D4A2C063。不存在JY_REJECTED_ROOT_META_ENTRY证据。22字段逐项值/类型/相同与否/推断含义见RESULT，12字段相同、10不同：身份/名称/4种路径、素材大小、两时间、时长。hidden=false、removed=0、云字段与draft_type相同；不存在未知status/workspace字段而被忽略。metadata/index draft_new_version=164.0.0；main content new_version=110.0.0/version=360000/platform.app_version=5.9.0，两者一致。TEST目前14文件（非4），封面/extra/settings/attachment/agency/bak/tmp等均具备；GOOD16文件主要多两轮load.bak，subdraft UUID差异不是结构缺失；cover是索引直接引用文件，不再概括全部12辅助文件均可选，首次列表前必要性没有删除对照实验。

原生日志draft_acion_watch.json记录07:27:34 copy_draft_external、errno=0/suc=true，TEST当前7EDC61A2身份和目录来自正式导入事件；这比猜注册字段更强，主content3E0D8888仍独立。有限User Data检索：24923文件名清单、约45.7MB内容，命中root_meta、该日志、draftLayoutConfig.ini；另有回收站索引1条，不含GOOD/TEST，两者layout值同为0（含义未知不猜）。共13个.db：11普通SQLite schema、2 Tracking非普通格式不解密；7应用缓存库可查询未发现草稿身份，2媒体搜索库schema可读但数据检索缺simple tokenizer，2浏览器库只读schema无草稿表，未读Cookies/会话/登录存储。没有GOOD有而TEST缺失的第二草稿DB证据，不能声称未知二进制/受限库已全排除。当前JianyingPro明文日志无draft/project/TEST条目；部分alog为非明文、1个Parfait日志锁定，未解密/强行读取，未发现TEST拒绝原因。

原GOOD/旧BAD研究对象保持，业务库SHA仍87E3DF53FB9910A63D35160C17D1B555588FE53FFFE45578545B832B5207E7B7；旧content RENDER_FAILED、RenderJob NEEDS_MANUAL，content5/generation3/PublishJob历史5新增0，新生产草稿/RenderJob/真实发布0，两端real_publish_enabled=false。诊断脚本第一次遇到日志PermissionError后只增量加只读跳过与明确限制，未改生产代码。下一步最小验证仅建议另行授权Worker按完整正式名称只读查找现有TEST，不生成任务或导出；本轮完成后停止。

证据`startup_render/runtime/jy59_visibility_diagnosis_20261004/RESULT.json`（逐字段表、目录SHA、数据库schema、日志、人工回读），只读采集器diagnose.py；HANDOFF备份`HANDOFF.md.jy59-diagnosis-20261004.bak`。

### 2026-10-04：SAFE ROOT META REGISTER，发现索引/身份现场变化，未覆盖

用户要求只增量登记隔离副本并交由人工目视，不再研究computer-use/ToDesk。本轮完全没有桌面操作、启动/关闭剪映或导出。只读检查发现指定`D:/JianyingPro Drafts/root_meta_info.json`不存在；真实索引仍为`C:/Users/sdaffwS/AppData/Local/JianyingPro/User Data/Projects/com.lveditor.draft/root_meta_info.json`（现有Worker配置一致）。索引已从上一轮35条变为本轮读取时36条，GOOD -1仍在，TEST隔离名称/路径已有且仅一条记录，但其真实index及draft_meta_info中的draft_id均已变为`7EDC61A2-B9DA-4e10-B671-FA42CD144C91`，不同于用户锁定的`79911B3E-9DE7-42B3-86C7-262B13724AD8`；不能据此断言变更原因，更不能把旧ID只写索引造成元数据不一致。content主id仍为`3E0D8888-86A2-4041-9760-4676B448FECF`。当前剪映5.9进程已运行，非本Agent启动，不关闭/覆盖现场。

已安全备份真实索引：`root_meta_info.json.backup_20261004_073210_626`同目录；原/备份SHA均`37F9C8BF17A7542BF291340F8CCA0760ADE00E50BD6B0CBDDD7C9987D4A2C063`，原文件备份前后及本轮末尾SHA不变，备份JSON可解析。观察GOOD真实结构22字段，完整记录及类型语义见RESULT，不从单一样本猜字段必需性。本轮不追加、不修改任何索引/草稿JSON：已有36条完整，GOOD与TEST路径保持；原BAD的28个资源引用全部存在，当前TEST主内容及subdraft JSON共97个引用无缺失，均只读验证。

状态`ROOT_META_REGISTER_PARTIAL`，不是按指定79911身份完成ROOT_META_REGISTERED_OK。需用户正常退出剪映，并确认使用实际C盘索引及当前真实身份，才能继续；人工可以观察当前TEST名称，但目视结果尚未取得，不能升级FIX_READY或隔离导出PASS。旧content RENDER_FAILED、旧RenderJob NEEDS_MANUAL不变，业务content5/generation3、PublishJob历史5新增0；无新增RenderJob/第三条草稿/真实发布，两端real_publish_enabled=false。

证据`startup_render/runtime/root_meta_register_20261004/RESULT.json`；HANDOFF修改前备份`HANDOFF.md.root-meta-register-20261004.bak`。

### 2026-10-04：DRAFT_INSTALL_REAL_UI_ACCEPTANCE，代码已重载，UI通道仍阻塞

本轮结论仍为DRAFT_INSTALL_VISIBILITY_FIX_PARTIAL，不是FIX_READY/ISOLATED_RENDER_PASS/PRODUCTION_RETEST_READY。按用户明确授权，仅重载本次修复涉及的主机专用Render server和8502工作台：新server实际子进程PID20188，07:22:41 +08:00启动，8766健康；8502子进程PID18692同刻启动，原参数不变，健康ok，8501及其它服务未重启。2060S既有专用Worker计划任务07:20:26启动并读取当前源码，07:20:27返回HALTED_NEEDS_MANUAL、LastTaskResult=0，无持续Worker/导出进程；原回执receipt_sent=true，终态保护在claim之前阻断，未重试或领取第二条。源文件SHA及启动记录在本轮RESULT.json，未获取短生命周期Worker PID，不冒称取得内存源码哈希。

按computer-use技能重新核验Windows通道，仍只有服务器窗口、无2060S剪映窗口；服务器既有ToDesk恢复目标后两次捕获分别FrameArrived/window capture timeout，遵循恢复次数限制停止输入。不通过自制UIA/桌面脚本绕过，不登录远控、不输入密码。本轮未启动/关闭剪映、未执行安装副本/索引登记/自动发现/打开/导出。既有隔离副本`D:/JianyingPro Drafts/丙曜起号10月4日-2-ISOLATED_INSTALL_POC`重新通过install_check，28个资源引用可用，两个独立UUID未复用GOOD/BAD；身份审计仍只覆盖索引metadata与可解析内容ID，31个历史不可解析目录未改。全局索引35条且未包含隔离副本，SHA未变，因未修改无需本轮备份；文件级通过不能满足本轮DRAFT_INSTALLED_OK全部要求。

只调用原专用入口START_JIANYING59_WORKER.ps1的CheckOnly：07:24:12确认VERSION_OK 5.9.0.11632，指定EXE路径、SHA BA941A875E7E4C4BBD3200733C10836C21E07DF726195F7102B3107874EF07D9、签名Valid；不是实际启动来源或UI通过证据。旧RenderJob/回执NEEDS_MANUAL、业务content RENDER_FAILED保持不变；主机operations.db、RenderDB、原回执以及远端state/index SHA前后相同。没有新生产草稿/content/RenderJob，PublishJob历史5新增0、真实发布0，两端real_publish_enabled=false，无运行中导出子进程。完成只读与重载工作后停止；需要可捕获2060S真实桌面通道才能继续正式隔离安装和UI验收，不能自行生成第三条。

证据：`startup_render/runtime/real_ui_acceptance_20261004/RESULT.json`；HANDOFF修改前备份`HANDOFF.md.real-ui-acceptance-20261004.bak`。

### 2026-10-04：VISIBLE -1 / INVISIBLE -2差分修复，真实UI复验仍待完成

当前失败content/job `STARTUP-d49177d3-31bb-4ad1-a370-9b328371119e`、batch `STARTUP_3001a61ce1d7489393a4271101881389`已真实生成/登记/领取/自动传输；05:38:06失败于JIANYING_DRAFT_NOT_VISIBLE，原RenderJob/回执保持NEEDS_MANUAL，不重试、不改COMPLETED/READY。

2060S GOOD为`D:/JianyingRenderWorker/Drafts/丙曜起号10月4日-1`，BAD为同父目录的`丙曜起号10月4日-2`。两者都在Worker配置目录，但**不是剪映实际扫描目录**：真实`User Data/Config/globalSetting`的`currentCustomDraftPath=D:\\JianyingPro Drafts`；扫描根目录为`D:/JianyingPro Drafts`。C盘默认Projects/com.lveditor.draft/root_meta_info.json有35条列表记录，已注册外部GOOD路径，无BAD条目。GOOD的既有注册可见性不能证明Worker任意复制到外部目录即可被识别；本轮不手工写全局索引或改剪映设置。

GOOD有16文件（含打开/编辑后自动生成的backup/cover/tmp等），BAD仅4个非零且有效的草稿JSON，结构没有多套一层目录，28个绝对资源引用都存在。两者ACL/所有者相同且可读，未改权限。metadata draft_id分别103BC2B4-1004-477a-B874-6B7CDE4C4343、BC69C7CD-7C5E-4185-B284-AF3E1047A664，不重复；主draft_content.id却同为91E08AC5-22FB-47e2-9AA0-7DC300FAEA2B。pyJianYingDraft ScriptFile.__init__直接读取固定content模板，原生成器没有替换顶层id；这是另一个明确身份缺陷，不能未经隔离UI实验把它称为唯一可见性原因。

最小修复：新账号绑定STARTUP在原create_draft阶段独立生成主content.id及metadata draft_id（旧源草稿不改）；2060S配置改为核验后的真实扫描根目录。新增draft_install.py，安装前读取既有设置核对root，安装后检查4类JSON/名称/路径/UUID/画布/时长/资源和已知重复身份；STAGING_COMPLETE、DRAFT_INSTALLED、DRAFT_FILES_VALIDATED与JIANYING_DRAFT_VISIBLE分开。历史普通草稿有31个非JSON/空元数据，未解密/修改；metadata身份通过全局索引核验，content身份审计只声明可解析内容范围，完整warning保留，不能冒称全部历史身份可读取。

用户授权的隔离副本为`D:/JianyingPro Drafts/丙曜起号10月4日-2-ISOLATED_INSTALL_POC`，仅复制4个JSON、0素材，改独立UUID与自身路径后DRAFT_INSTALL_CHECK通过。原GOOD/BAD全部SHA不变。当前computer-use只返回服务器窗口，不能访问2060S真实UI；按技能停止UI控制，没有用自制桌面输入绕过。没有启动/关闭/点击剪映、没有导出、没有生成第三条生产任务；隔离副本真实列表出现及Worker发现**未验证**，仅ISOLATED_FILES_VALIDATED_UI_PENDING，不是DRAFT_INSTALL_VISIBILITY_FIX_READY。

失败传播使用005_render_failure.sql受控迁移：SQLite旧CHECK不允许RENDER_FAILED，备份后按重建流程保留所有旧字段/外键/唯一约束/触发器；新增failure_code/failure_message/failed_at/render_job_id及不可变回执指纹附表，原字段记录不变，foreign_key_check为空。通过统一register_failed处理本轮已经收到且身份匹配的原失败回执，真实content.production_status已为RENDER_FAILED，failure_code=JIANYING_DRAFT_NOT_VISIBLE，failed_at=05:38:06 +08:00；重复应用幂等，发布状态NOT_SCHEDULED、video_path NULL。其它业务表SHA不变，原RenderJob DB/原失败回执SHA不变。备份operations.db.render-failure-20261004_060453_741102.bak。新Broker失败回调及页面失败说明已写入源码；本轮未重启线上服务，下轮ARMED前需按正常部署加载新的主机代码，不能声称旧运行进程已热更新。

新增安装16项、失败状态17项（含真实Broker隔离集成）通过；相关Render90/90、业务/Planner152/152通过（有重叠），2060S73/73，8个生产改动文件语法通过。最初夹具准备为READY导致安全拒绝，已改成隔离未导出夹具；前次3项测试导入路径错误按原tests PYTHONPATH重跑通过，未放宽产品检查。

本轮PublishJob新增0（历史5）、真实发布0、两端real_publish_enabled=false。素材下载/上传、锁定5.9 Launcher/签名EXE/更新组件、权限/Planner/小V猫Worker未改，Worker仍任务终态退出，无导出子进程；不自动恢复或消费下一条。证据在`startup_render/runtime/differential_20261004/{REPORT.md,DIFFERENTIAL_RAW.json,ISOLATED_INSTALL_VALIDATED.json,FAILURE_STATE_APPLIED.json}`。真实可见性复验是剩余阻塞，下一步须在可用2060S UI通道下仅验证既有隔离副本，不启动下一条生产任务。

### 2026-10-04：本轮单条监听补充专用剪映入口约束（尚未生成生产任务）

用户补充普通剪映启动/更新曾把5.9升级为8.9。2060S真实桌面`C:/Users/sdaffwS/OneDrive/Desktop/剪映5.9 Render Worker.lnk`的Target为既有pwsh、Arguments为`-NoProfile -File "D:\JianyingRenderWorker\Scripts\START_JIANYING59_WORKER.ps1"`，已核验复用此入口，不创建另一launcher。

仅增量改`startup_render/agent.py`的入口调用/启动来源/进程归属校验、`draft_lifecycle.py`立即传播VERSION_DRIFT，以及Agent模板3个launcher配置字段，新增13项隔离测试。生产EXE直启已移除；每次通过专用入口CheckOnly验证版本/路径/SHA/签名，再正常关闭安全首页、确认全退出、调用同一入口启动全新实例、再次版本检查、等待UI及正式草稿名、沿用原自动导出。ALREADY_RUNNING不当来源验证；未知编辑/保存/导出不强杀，启动后只正常关闭归属本次Worker的PID/创建时间实例。原launcher/checker/签名EXE/更新组件均未改；任务日志包含用户要求的7个启动来源字段。

锁定EXE=`D:/JianyingRenderWorker/JianyingPro/5.9.0.11632/JianyingPro.exe`，版本5.9.0.11632，SHA256=`BA941A875E7E4C4BBD3200733C10836C21E07DF726195F7102B3107874EF07D9`，签名Valid。真实专用入口CheckOnly通过VERSION_OK；本轮没有真实启动剪映或导出。新测试及回归主机59/59、2060S57/57；两端规范化换行后的代码SHA一致（远端agent.py为CRLF、本机为LF，逐行diff为空；原始SHA均留存），素材传输/RenderJob/READY/权限/Planner/小V猫Worker未改。

补充期间仅在确认无任务/导出子进程后暂停本轮两端专用监听，8502及其它服务未停；完成后仍按原新run `acceptance_20261004_050123_production`恢复单条监听。原05:07的ARMED.json及BASELINE保留为历史快照，不冒称补充期间保护代码全未变；最终补充核验使用ARMED_DEDICATED_ENTRY.json，明确授权只改上述两处生产Python文件。历史失败DB/回执保持原SHA，旧content未改READY，未生成生产草稿或PublishJob，real_publish_enabled=false。实际专用入口启动来源还需下一条用户生成任务的JIANYING_LAUNCH_SOURCE证明，当前仅STARTUP_SINGLE_ACCEPTANCE_ARMED，等待用户手工生成1条。

### 2026-10-04：新的单条生产链路验收已武装，等待用户手动生成

run_id=`acceptance_20261004_050123_production`，acceptance_started_at=`2026-10-04T05:01:23.2113795+08:00`。仅配置切换到本轮新的运行状态目录：主机`startup_render/runtime/acceptance_20261004_050123_production/server/render_jobs.db`，2060S `D:/Projects/XunZhen/startup_render/runtime/acceptance_20261004_050123_production/agent`。旧主机runtime/server及旧任务机runtime/agent原地保留，不删除/清理/改状态，旧失败content `STARTUP-71402f01-9880-4bab-8909-c7706120779f`仍历史NEEDS_MANUAL，未写READY/COMPLETED。

主机既有生成完成事件每次新建Registration/RenderQueue时读取server.example.json，已核验当前enqueue数据库与本轮Broker相同，无需改业务代码或重启登记上下文。新Broker队列空、按新的started_at过滤完成事件、max_jobs=1，Worker新状态目录无旧任务、stop_after_one=true；恢复既有两端专用计划任务，主机真实/health LISTENING，2060S WAITING_NEW_DRAFT，局域网GET成功，5.9.0.11632版本/SHA/签名/实际进程路径预检VERSION_OK，real_publish_enabled两端false。旧DB/回执SHA、全部业务/Worker保护代码SHA未变。

8502原本未监听，已按原已验证局域网启动参数在正常本机权限下隐身启动现有工作台，没有停止任何现有服务、没有修改业务/模型/索引/防火墙。未生成新草稿、content或生产RenderJob，新增PublishJob=0（历史5），真实发布=0。用户下一步应在8502选择丙曜稳定account_id=`1621131832863931`、生成1条STARTUP；正式名称取真实原子预留计数，不硬编码序号。若账号快照过期，使用既有“刷新账号”按钮；不放宽权限。

本轮只到STARTUP_SINGLE_ACCEPTANCE_ARMED后停止动作，等待用户手动生成后再验收真实自动交接/MP4回传/READY/待发布池与锁定账号预览；不能把武装或隔离通过当完整生产链路PASS。证据`startup_render/runtime/acceptance_20261004_050123_production/{single_run.json,BASELINE.json,ARMING_REMOTE.json,ARMED.json}`。配置备份为对应`.arming-acceptance_20261004_050123_production.bak`，不覆盖生产凭据。

### 2026-10-04：JIANYING_DRAFT_NAMING_PASS / JIANYING_DRAFT_REFRESH_PASS（隔离验证，不是新生产链路PASS）

用户补充2060S重开剪映后旧草稿可见，但实际名称错误。本轮UIA真实回读旧首页`HomePageDraftTitle:XZ-STARTUP-71402f01-9880-4bab-8909-c7706120779f`，文件夹及`draft_meta_info.json.draft_name`均为该XZ名称；`draft_content.json.name`为空，5.9样本没有draft_info.json。主机生成器已用`XUNZHEN_RESERVED_DRAFT_NAME`把正式名称传入`DraftFolder.create_draft`并补全meta；具体缺陷是2060S的`install_draft`覆盖名称为XZ-content_id，`render_child`再按该文件夹名查找。此前业务/Manifest中的“丙曜起号10月4日-1”不代表剪映UI名称已通过。

增量修复Worker安装/导出边界：按正式draft_name创建副本并回读5.9meta，content_id仍独立稳定；导出前核对业务名/文件夹/meta/账号绑定MP4名，重新取得UI根并确认真实`HomePageDraftTitle`名称，错名DRAFT_NAME_MISMATCH，不可见JIANYING_DRAFT_NOT_VISIBLE。新增draft_lifecycle正常关闭首页→所有锁定进程退出→锁定5.9重启→首页/列表ready→正式名称visible，再调用原pyJianYingDraft导出；导出完成后正常关闭。编辑/保存/导出/未知弹窗或关闭超时不强杀，转NEEDS_MANUAL。前后均验证版本/SHA/签名/进程路径；逐阶段记录时间及明确子进程错误，增加close_requested_at/process_exited_at/restart_at/ui_ready_at字段。

隔离研究仅复用旧接收包，31文件SHA通过，27媒体未重新传输，仅复制4个草稿JSON到正式名称研究副本，未重命名/覆盖原XZ失败目录。04:37:51正常关闭、04:37:52全部退出/重启、04:37:59首页ready、04:38:01真实名称visible；自动按该名称打开/导出，04:38:03～04:39:17耗时74.53秒，04:39:21正常关闭全退出并验证完成。2060S研究MP4为`D:/Projects/XunZhen/startup_render/runtime/naming_refresh_20261004/exports/丙曜起号10月4日-1.mp4`，H.264/AAC、1080×1920、30fps、67.233333秒、83515997字节，SHA256=`8f06ac5d916eb59f8b6ea74dc2d31ba3c3826a46e0e74c45f496088c0c69019f`。无人代点、无人补素材，仅明确授权的自动研究导出一次。

历史刷新原因仍需准确区分：用户确认重启后旧草稿出现，但上轮未记录原进程启动时间，不能独立证明“素材到达晚于启动”；本次新副本重启前也已可见，不能把旧DraftNotFound唯一归因JIANYING_DRAFT_LIST_STALE。本轮验证的是已修复命名和安全刷新生命周期可用，不篡改原失败结论。

新增18项隔离测试；主机18+原Render28=46/46，既有账号绑定/序号36/36，2060S18+原Render26=44/44，语法检查通过。原素材下载/哈希传输函数未改；server/queue/completion/common、STARTUP权限/绑定/selector/READY/Planner/小V猫Worker哈希未变。账号绑定新任务不依赖“组合X-自动合成”；独立旧非绑定生成器保留兼容命名，不作为该链路的查找回退。

旧content/render_job `STARTUP-71402f01-9880-4bab-8909-c7706120779f`仍NEEDS_MANUAL，业务内容仍GENERATING/NOT_SCHEDULED、登记仍RENDER_PENDING；未写READY/COMPLETED，未把研究MP4通过生产回执回传。原主机草稿、2060S旧失败文件、旧失败20261004_003025证据均未变。新增PublishJob=0（历史总数5）、真实发布=0、两端real_publish_enabled=false；两端专用导出计划任务仍Disabled，剪映正常退出，无导出子进程。本轮停止，等待用户以后生成全新单条再验收完整主机→2060S→回传→READY；不得复用旧失败任务冒充成功。

证据与完整16+6项报告：`startup_render/runtime/naming_refresh_20261004/{REPORT.md,FINAL_ACCEPTANCE.json,REMOTE_EVIDENCE.json,HOST_SAFETY.json}`；2060S同名runtime目录保留原始阶段/版本/素材校验及研究产物。备份：agent.py/README.md/HANDOFF.md的`.naming-refresh-v01.bak`及2060S原agent备份。

### 2026-10-04：账号绑定最终单条真实交接验收FAIL，已保留现场并停止

本轮run_id=`acceptance_20261004_031357_account_bound`，边界取用户正常点击生成时已写入的真实03:13:57 +08:00。唯一新batch为`STARTUP_0920778945844235b452f9863867923d`，content_id/render_job_id均为`STARTUP-71402f01-9880-4bab-8909-c7706120779f`。员工`c160d384-c285-4a41-824e-dd7f93c8aff7`，STARTUP，丙曜稳定account_id=`1621131832863931`全链路不变。原Manifest记录草稿`丙曜起号10月4日-1`于03:14:02自动生成成功，content和唯一PENDING RenderJob均由生成完成事件自动创建；没有手工补登记/入队。

恢复前已确认主机只有此一任务、无其它QUEUED/CLAIMED，2060S无既有任务/导出进程；单轮max_jobs=1、Worker stop_after_one=true，发布与最终提交授权均false。主机自动打包，2060S于03:59:53.704记录领取后首个PENDING事件；实际27个媒体（主选材3个）+4个草稿JSON共31文件，自动传输及SHA256全部通过，03:59:56进入DRAFT_READY。源→任务机路径映射及逐文件校验保存在本轮报告，不复制整个素材库。

剪映预检真实VERSION_OK：5.9.0.11632、SHA256=`BA941A875E7E4C4BBD3200733C10836C21E07DF726195F7102B3107874EF07D9`、签名Valid，实际进程路径均为锁定EXE。既有Worker自动启动剪映，04:00:11进入EXPORTING调用，但04:00:16.963失败：`pyJianYingDraft.exceptions.DraftNotFound`，列表中找不到安装好的`XZ-STARTUP-71402f01-9880-4bab-8909-c7706120779f`副本。副本draft_content.json真实存在，不是素材缺失；草稿目录注册/列表可见性的更深原因本轮未验证，不能猜为刷新问题或擅自修复。

整体结论`STARTUP_RENDER_HANDOFF_FAIL`。导出调用尝试约5.95秒，未取得成功导出耗时。期望MP4为`丙曜起号10月4日-1.mp4`，但任务机与主机均不存在，ffprobe未执行、无自动MP4回传。主机收到失败回执并保存NEEDS_MANUAL，content仍GENERATING，未进入READY/待发布池，READY计划预览未执行；当前content、Manifest及RenderJob中的账号绑定仍正确，不能将其记为READY阶段已验收。

两端专用任务均已Disabled；确认无仍在导出的子进程后才停用，本轮未关闭剪映应用、未重导/人工打开/点击/补素材/改READY。人工救场0次，用户按计划生成1次；本轮新增PublishJob0、历史总数5、真实发布0，real_publish_enabled两端均false。原失败批次20261004_003025的报告SHA不变，仍无业务补录。主机受保护代码及原草稿SHA不变，2060S agent/common实测前后SHA不变，未部署或改Worker。

完整27项及素材映射：`startup_render/runtime/acceptance_20261004_031357_account_bound/{FINAL_ACCEPTANCE.json,BASELINE.json,OBSERVATION.json,REMOTE_EVIDENCE.json}`；原Worker日志/版本检查/events保留在2060S对应job目录，主机原receipts保留失败回执。仅新增只读取证脚本和证据，备份原single_run配置及HANDOFF，未改生产逻辑。本轮结束，不自行修复或重新生成。

附带只读检查：04:04～04:06发现8502无监听、健康请求拒绝连接，8501仍监听。当前验收没有执行8502停止/重启动作，也没有该端口的本轮起始基线，原因未定，不把它误归为此次DraftNotFound；未扩展任务去重启工作台。

### 2026-10-04：STARTUP_ACCOUNT_SELECTOR_READY（仅账号快照刷新与候选加载）

真实空列表原因是旧快照过期及起号页只有读取、没有同步入口。02:27核验：`suzhengchao`的employee_id及339642/STARTUP绑定有效，两个既有稳定账号仍标ONLINE，但最近同步为01:29:44，已超过原30分钟有效期；同一`D:\video_search_tool\operations.db`，业务类型STARTUP正确，严格权限服务返回空，未放宽规则。

仅改`startup_pipeline/workbench_session.py`的目标账号选择器，新增`selector_refresh.py`及`selector_sync_reader.py`。起号页提供“刷新账号”；缺失/过期快照在每个工作台登录会话首次进入时自动尝试一次，调用前设置闩锁，失败不循环；手动按钮可以重试。同步后立即重新读取原`get_publishable_accounts(..., business_type='STARTUP')`并显示在线数量/同步时间。selectbox实际值仍是稳定account_id，GenerationContext与ACCOUNT-BOUND CONTENT规则未改。

刷新只查当前登录员工已启用的STARTUP绑定组，本轮仅339642，不扫10组。内部限定快照写入器复用原`persist_group_snapshot`的实时采集、scope、组/账号稳定ID、数量/在线状态校验；事务内重新鉴权及检查绑定/既有账号集合，只更新该组既有账号的展示/在线/快照字段与同步审计。不能创建身份、变更归属或赋权，原Planner管理员同步入口及数据库约束未修改。没有浏览器上传快照接口。

真实网页自动尝试曾在后台窗口激活处失败，尚未读取分组，失败页面正确保留手动按钮。起号调用层临时连接后台调用线程与当前前台/已定位小V猫窗口的输入队列，再调用原读取器，finally断开；原前台校验、分组DOM读取、重试与发布Worker完全未改。只连接前台队列的初版仍失败，补充目标窗口队列后，真实起号页“刷新账号”于03:03:24完成单组同步，两账号当前均ONLINE：丙曜/1621131832863931、62288252897/3031801633454512，与历史ID一致。真实下拉展开并选择丙曜成功，未点击生成按钮。后续若窗口锁定、焦点/读取校验失败仍停止，不伪造在线状态。

新增15项隔离测试通过；相关回归218/218（startup109、planner66、adapter25、web_ui18），最终窗口队列修正后15项定向再测通过，语法通过。自动一次成功/失败重试、立即重读、离线/越权过滤、稳定option值/GenerationContext、绑定撤销、ID不一致拒绝及无生成/发布副作用均覆盖；测试不是生产草稿验收。

证据位于`startup_pipeline/runtime/selector_refresh/acceptance/{BASELINE.json,FINAL.json,TESTS.json,selector_selected.jpg}`，成功现场在`startup_pipeline/runtime/selector_refresh/2fdd111b50fe4bac8db3550995185d88/339642/{STAGES.json,LIVE_SYNC.json,reader.log}`；失败阶段日志亦保留。备份`operations.db.selector-refresh-20261004_023353.bak`及修改文件`.selector-refresh-v01.bak`。受保护代码/业务表、员工绑定及非目标组账号哈希均不变，生产内容新增0、PublishJob新增0（历史总数5），真实发布0，real_publish_enabled=false。仅8502通过原启动器重新加载，8501未改；两端Render专用监听与原心跳保持停用。没有修改2060S Worker、剪映、RenderJob/READY核心、计划器或发布链路。到此停止，等待用户另行启动真实生成。

### 2026-10-04：WORKBENCH_ACCOUNT_BOUND_STARTUP_READY（业务修正完成，未做真实导出验收）

寻帧8502顶部复用原 `planner_session` 提供共享WorkBench Session（employee_id/login_name/role），不再要求先进入发布管理登录。起号自动合成按钮前增加目标STARTUP账号，沿用原授权/在线/30分钟快照规则；未登录或未选稳定ID不能生成。生成不需要MP4，保留的手工入口明确标为MANUAL_EXISTING_VIDEO。

`StartupContentRegistration.begin` 在数据库事务中预留GenerationContext、batch_id及账号/业务/本地日期序号；`account_binding.draft_name` 生成安全昵称+起号M月D日-N，通用函数支持COMMERCE带货命名但未接其生产页。不扫描目录计数；同名冲突安全拒绝，不覆盖。生成器仅接收预留名字，Manifest保留账号上下文。成功登记的content通过migration004附表永久关联稳定target_account_id、昵称快照、draft_name及预留source_content_id。更新/删除绑定被SQLite触发器拒绝；历史内容不猜账号、不补录。

RenderJob payload继承账号，2060S `agent.py`仅修改输出相对路径和回执账号字段，`common.py`增加兼容命名函数。输出为 `<batch_id>/<draft_name>.mp4`，旧无绑定任务仍保留数字文件名；`render_child`、素材下载/安装、上传、剪映5.9版本检查及控制函数AST不变。主机回传身份核验增加稳定账号与名字一致性；继续由原SHA/ffprobe校验进入READY，不能手工登记新绑定MP4补成功。READY池展示账号快照/ID、内容、文件、时长与真实队列状态，读取失败不会冒充成功。

STARTUP_READY_POOL直接带入原计划器，账号只读；服务端拒绝混合账号计划及任何改投，手工已有MP4入口也不能绕过已有内容路径绑定。生成PublishJob的metadata增加账号约束；小V猫通用提交点与旧v04_submit仅增加最终稳定ID守卫，不匹配抛ACCOUNT_BINDING_MISMATCH且不碰最终按钮。没有重写小V猫自动化/主状态机或分组权限。原计划确认仍仅生成本地模拟状态，不自动消费；旧V0.4脚本仍是固定历史单任务，不等于通用真实发布已实现。

隔离回归：新增38项（startup36+render1+生成适配1），全套355/355通过：startup94、render28、planner66、adapter25、publish_worker31、web83、generator2、core26。2060S已部署最小适配，其原26/26渲染测试通过。首次生成器测试在CUDA测试环境缺pyJianYingDraft，改用项目config已配置解释器后2/2通过，未安装依赖。新绑定模式草稿目录缺失时立即失败，不走旧目录扫描兜底。详见 `startup_pipeline/runtime/account_bound_v01/RESULT.json`、各测试日志及REMOTE_DEPLOYMENT.json。Mock测试不代表真实桌面导出或端到端PASS。

迁移一致性备份：`operations.db.account-binding-20261004_021315_561134.bak`。旧业务表逐行散列不变，新增三附表均0行，外键检查通过；生产PublishJob历史总数5、本轮新增0。失败批次20261004_003025仍无业务登记/队列，不复用。real_publish_enabled=false，真实生成/导出/发布均0。8502用原启动器重新加载，8501未动。两端专用Render监听仍禁用、原心跳仍暂停，未开始本轮真实验收。

下一步等用户从新入口生成1条全新草稿后，再另行恢复限定单条的跨机验收。届时若账号快照过期，必须通过既有UI同步刷新真实在线状态；本轮未刷新、更未放宽快照期限。

### 2026-10-04：XIAOVCAT GROUP SYNC TIMEOUT V0.1

本轮仅修改独立同步器 `xiaovcat_adapter/group_sync.py` / `group_identity.py`，新增 `sync_trace.py` 和16项隔离测试。未修改Planner、员工绑定、2060S Worker、剪映或发布Worker。真实阶段日志复现：339642 的 DOM 节点及 data-row-key 已找到，展开后选中项变成子 td，旧逻辑持续等 selected tr，超时位于 `GROUP_SWITCH_FAILED / EXPAND_AND_READ_GROUP_ROW`，不是权限丢失。修复为按源ID精确XPath查询单组、逐阶段状态确认、每次重新取根与页面/搜索框、最多两次重试；真实重试一次恢复。未知页面/焦点改变不盲操作。

入口 `GroupSyncUI(results).sync_group('339642', expected_account_ids)`；CLI支持 `--group-id 339642 --expected-account-id 1621131832863931 --expected-account-id 3031801633454512 --results <本轮目录>`。单组快照scope为 `SINGLE_GROUP_VERIFIED_UI`，不冒充全量同步，不停用其他组。`persist_group_snapshot`核验源group_id、当前两个稳定account_id与历史完全一致、状态/数量一致及采集时间不超过120秒，再调用原 `PlannerStore.sync_snapshot` 管理员鉴权入口。原发布权限30分钟快照规则未放宽。

2026-10-04 01:29:44 +08:00已刷新 operations.db 339642 快照。现场多次读回丙曜1621131832863931和62288252897/3031801633454512均为ONLINE，第二个账号已不同于上一轮离线现场，未人为伪造OFFLINE。原 `get_publishable_accounts(..., business_type='STARTUP')` 实际返回2个；账号前置条件已恢复，但不满足用户指定的“一在线一离线、仅返回丙曜”验收，因此严格记录 `XIAOVCAT_STARTUP_ACCOUNT_SYNC_PARTIAL`，不是同步仍超时。仍需用户自行生成新的单条草稿，本轮没有生成草稿或继续渲染/发布。

证据：`xiaovcat_adapter/results/group_sync_timeout_v01/final/{STAGES.json,LIVE_SYNC.json,ACCEPTANCE.json}`；原始复现日志在 `recheck/STAGES.json`。SQLite一致性备份 `operations.db.group-sync-20261004_012925.bak`。员工/绑定/发布计划等受保护业务表及非目标组账号逐行不变，PublishJob前后均5条、新增0，`real_publish_enabled=false`；32个受保护代码/配置哈希一致。Planner66、Adapter25（含新增16）、原Worker31，共122项回归通过，4个新改Python文件语法通过。首次沙箱测试因Windows临时目录ACL失败；在获准本机测试环境重跑通过，未当作产品失败或伪报通过。

### 2026-10-04：用户批准本地密码最小长度调整及单账号重置

用户明确批准将寻帧本地密码最小长度由12改为6。publish_planner/storage.py使用统一MIN_PASSWORD_LENGTH=6进行设置/登录校验，初始化页面提示同步更新；PBKDF2-SHA256加盐及310000轮、登录限速、权限体系均不变，旧长密码兼容。新增4项密码策略测试，Planner完整66/66通过，语法通过。

仅重置本地账号suzhengchao密码为用户指定值（不在文档/源码保存明文），业务服务登录验证通过并退出验证会话，撤销其旧会话3个；员工身份、角色、启用状态、分组绑定均校验未变，其他账号密码未改。本机SQLite一致性备份：operations.db.local-password-20261004_010020_438081.bak。没有修改小V猫密码、2060S、渲染/发布开关；用户需刷新页面重新登录。

### 2026-10-04：起号完成事件登记断点已修复（等待新的真实批次验收）

已实现并通过隔离回归，**不等于真实跨机导出PASS**。旧断点为startup_pipeline.ui.begin_generation鉴权失败返回None、页面仍继续合成，随后finish_generation因缺generation_id直接返回；员工任务上下文从未写startup_generation_runs，因此后续没有业务内容/RenderJob。当时浏览器session未保留，具体是未登录、过期还是其它鉴权问题不能断言。

现在生成前通过原PlannerStore鉴权，缺失planner_session时在合成前显式STARTUP_LOGIN_OR_CONTEXT_REQUIRED阻断。begin创建原generation_run并返回generation_id/employee_id/started_at，页面将同一上下文直接传给生成成功回调，不从文件名/分组名猜身份。新StartupContentRegistration.register_startup_content复用原_ingest的稳定UUID内容ID及UNIQUE(batch_id,video_index)，写新登记附表的员工、草稿、组合签名、业务类型与DRAFT_READY事件。旧startup_contents.production_status保留GENERATING约束，不冒充已导出READY。

登记事务提交后同一个完成回调调用RenderQueue.enqueue，在原render_jobs.db中同步创建唯一PENDING任务，render_job_id沿用content_id，payload保留employee_id/batch_id/video_index/draft_path/created_at/business_type。重复回调及并发enqueue不重复内容或有效RenderJob，身份变化拒绝。附表进入RENDER_PENDING；登记失败CONTENT_REGISTRATION_FAILED且不入队，入队失败RENDER_JOB_CREATE_FAILED并保留已登记身份。页面不会在这些失败后显示全部成功。兼容字符串单条入口从生成返回值与任务ID建立Manifest，未扫描目录/回填旧草稿。

主机Broker配置event_only=true，改为消费完成事件已创建的PENDING记录，再调用**未改动**的素材打包/传输实现；不再通过扫描批次推断创建RenderJob。2060S agent、剪映导出、素材传输common、原StartupPipeline服务、PublishPlanner与发布Worker均未修改，目标机无部署操作。两端验收监听仍Disabled、自动跟进仍Paused；没有开启真实导出或发布。

迁移003只新增startup_content_registrations/startup_registration_events；生产备份`operations.db.registration-20261004_005117_443633.bak`。既有业务行校验不变，生产新登记0、PublishJob仍5、新增0。失败证据批次20261004_003025在新登记入口明确拒绝自动补录，原manifest哈希未变，其最终FAIL证据保留。

新增20项（服务18+页面2）测试；主机完整回归205/205通过，语法检查通过。报告`startup_pipeline/runtime/registration_fix/RESULT.json`，包含保护文件哈希、迁移结果和日志。真实新草稿未生成，真实发布0，real_publish_enabled=false。用户下一步应刷新寻帧、在**发布管理**完成本地登录，再生成1条全新起号草稿；本轮到此停止，不能复用旧失败批次或自行恢复渲染/发布验收。

### 2026-10-04：单条真实交接验收失败，已停止（不修补本轮结果）

最终结论 **STARTUP_RENDER_HANDOFF_FAIL**。用户正常生成新批次`20261004_003025`（00:30:25创建，00:30:30完成），video_index=1，草稿`组合1-自动合成`，composition_signature=`ccc48e019f7cbbdcf4b63ad818086bc8dd155a1bf817921f690e2eaececd0578`，时长53.067秒（草稿元数据，非MP4探测结果）。这不是此前已发布的同名旧MP4，本轮依据新manifest和组合签名识别，未导出旧视频。

明确阻塞在RenderJob之前：operations.db没有本批次startup_batches / startup_contents / startup_generation_runs记录，因此没有员工归属、content_id或RenderJob。独立render_jobs.db共0条，2060S自动领取0条、传输0、导出0、回传0、READY新增0。草稿JSON引用24个去重媒体文件，其中manifest主选材3个；24个源媒体在主机存在。不能将本次失败归因为任务机缺素材或剪映导出失败，它们尚未执行。

代码证据：startup_pipeline/ui.py的begin_generation在principal登录校验PermissionError时直接返回None，finish_generation在generation_id缺失时直接返回，原草稿仍可成功生成。这解释可能的跳过路径；未捕获生成时浏览器session，不能断言具体为未登录、会话过期或其它登记前错误。本轮不手工认领、不补content_id、不改草稿、不补素材、不点击导出、不重试或领取第二条。

本轮专用server/agent计划任务停止并禁用（未来登录也不自动继续本轮），automation-2已PAUSED；无运行中导出子进程被中断，线上工作台及原小V猫Worker未动。两端real_publish_enabled=false，目标final_submit_authorized=false，生产PublishJob总数保持5，新增0，真实发布0，人工救场0。停止主机后任务机短暂URLError是停机结果，不是本轮根因。

完整16项验收、源素材清单和身份散列见`startup_render/runtime/FINAL_ACCEPTANCE_20261004_003025.json`。后续如用户批准修复，应先修“生成入口的员工归属/内容登记可见性与前置检查”，不能把本轮改成PASS，也不要启动自动发布。

### 2026-10-04：STARTUP_RENDER 单条无人干预验收已布防，等待新草稿

本轮run_id=`acceptance_20261004_001039`，仅接受2026-10-04 00:10:39 +08:00以后完成且有原员工归属的单视频批次，最多1个RenderJob；10个历史批次不变。两端任务已恢复运行，2060S当前WAITING_NEW_DRAFT，未收到本轮content_id，不能报告真实导出PASS。现有生产PublishJob计数5、startup_contents计数3作为本轮观测基线；未新增真实发布任务，real_publish_enabled=false。

本轮仅增量完善startup_render验收：单任务窗口、阶段时间、源→本地映射、缺素材停止、调用既有5.9版本检查脚本、上传最终MP4至主机确定路径、主机哈希和ffprobe再校验、限签发身份登记原startup_contents.READY（用户语义READY_TO_PUBLISH）。不修改Schema或发布Worker；这替代前一节“尚不回写READY”的旧实现描述。只有真实自动验收通过才允许更新READY，原UI池使用READY+NOT_SCHEDULED+本机文件存在，无需修改旧UI。写入前为operations.db做仅本机备份，不复制凭据到2060S。

主机接收路径`D:\video_search_tool\outputs\startup_exports\<batch_id>\001.mp4`，2060S保留原导出路径；自动HTTP回传不是人工救场。回执在`startup_render/runtime/server/receipts/`，任务机每任务目录有events.json、source_to_worker.json、version_check.json、render.log。本轮失败时禁止手工补文件/点击导出/重试任务。成功或失败后不接第二条，不进入发布。

主机隔离测试27/27、2060S已部署版本26/26通过（新增第27项为主机READY幂等及权限测试）；语法通过。预检5.9.0.11632/SHA256/签名Valid/进程路径为VERSION_OK，但不替代未来执行时的再检查。模块运行代码快照301a55079522a5fa429a49c0a2ef8400984cdaf3，目标其它未提交开发仍保留。

聊天自动跟进automation-2每5分钟仅观察本轮结果，未变化不通知；终态给16项验收并暂停自身及专用监听。不得把尚未出现的新草稿当作失败或伪造已完成。单任务范围见`startup_render/runtime/single_run.json`，准备记录见`SINGLE_RUN_ACCEPTANCE.json`。

### 2026-10-04：2060S 新起号草稿导出交接（PARTIAL，真实发布保持关闭）

用户明确只处理“接入以后新生成的起号草稿”，需要自动真实发布但账号、文案、发布时间稍后确认。本轮新增独立 `startup_render/`，未改线上合成业务、生产Schema、权限服务、小V猫Worker或其配置；安全源码导出器仅增加新模块白名单，修改前已有 `.startup-render.bak` 备份。

服务器 `D:\video_search_tool` 的 `XunZhen-Startup-Render-server` 与2060S `D:\Projects\XunZhen` 的 `XunZhen-Startup-Render-agent` 当前用户交互式计划任务已启动。独立 TCP8766 只对192.168.1.89放行，不关闭/重启线上工作台。首次激活为2026-10-04 00:03:08 +08:00，排除10个既有批次，仅接收激活后完成且原业务库已有员工归属/content_id的新批次。服务器只读operations.db，独立保存任务状态；2060S已通过真实局域网领取空队列，状态WAITING_NEW_DRAFT，当前真实导出、上传、发布均0。

实现引用文件清单、SHA256传输、任务机副本路径迁移、固定剪映5.9导出调用、ffprobe/帧率/分辨率/时长校验和content_id/batch_id/video_index/employee_id回执；不复制整个素材库或凭据，不覆盖已有草稿/MP4，故障或中断不自动重导。输出目录 `D:\JianyingRenderWorker\Exports\startup\<batch_id>\001.mp4` 等。成功回执为EXPORTED_AWAITING_PUBLISH_PARAMETERS，**尚不回写原待发布池READY，也不创建真实PublishJob**。

2060S已有未提交的Worker开发，未被覆盖；同步仅提取新模块（快照03ce973c1a03e453ff04a60e33c69ed50121ded4），已有修改文件同步前后SHA256一致。新增21项隔离测试服务器/2060S均通过，2060S原301项模拟回归全部通过，合计目标机322项；语法检查通过。不能将模拟测试视为真实桌面验收。

剩余：第一条新起号草稿跨机实片导出待验收，目录型特效资源迁移和5.9兼容性未知时停NEEDS_MANUAL；用户确认发布参数后，仍需正式接通成片→既有权限服务/Worker入队桥接并验收账号/独立话题/定时发布。当前不宣称无人值守真实发布已打通。两端real_publish_enabled=false，目标final_submit_authorized=false。详见 `startup_render/README.md` 与 `startup_render/runtime/ACCEPTANCE.json`。

### 2026-10-02：寻帧局域网入口

用户选择最新版寻帧8502供局域网伙伴使用。原 `benchmark/experiments/dino_july_web/launch.ps1` 增加可选 `-Lan` 和只检查参数的 `-CheckOnly`；默认仍为127.0.0.1，局域网模式监听0.0.0.0。新增根目录 `启动寻帧-局域网.bat`、同目录 `setup_lan.ps1` 和 `LAN_ACCESS.md`。修改前已备份启动器/README/HANDOFF，Windows PowerShell脚本为UTF-8 BOM、CRLF，批处理为UTF-8、CRLF。

现场主机IPv4为192.168.1.126，办公网类别Public；已配置独立规则 `XunFrame-LAN-TCP-8502`，仅现有CUDA环境Python程序/TCP8502/LocalSubnet入站，EdgeTraversal=Block。没有关闭防火墙或改变网卡类别。8502原先未运行，现以正常本机权限在后台启动；局域网首页与 `/_stcore/health` 返回HTTP200/ok，监听0.0.0.0:8502。证据 `benchmark/experiments/dino_july_web/runtime/lan_verification.json`，启动日志 `lan.stdout.log`/`lan.stderr.log`。当前运行进程和网卡状态以实时检查为准。

新增启动参数/防火墙范围测试3项、现有UI测试16项、根目录基础测试26项全部通过。未修改搜索、模型、抽帧、索引、数据库Schema、业务权限或Worker；没有启动索引构建或草稿生成。保留旧8501进程，本轮仅开放最新版8502。主机网络检查已通过，**伙伴电脑端到端连接及双用户实测仍待用户反馈，不据此承诺并发容量**。

伙伴入口 `http://192.168.1.126:8502`，无需安装依赖；浏览器短片沿用已有预览，页面D/E盘路径仍属于主机。起号只生成主机剪映草稿，不提供伙伴本机剪映或原视频下载；发布管理沿用已有员工权限和模拟/真实发布边界。搜索及反馈导出目前没有登录门槛，同子网可访问。停止/重启、IP保留、规则撤销和排查见LAN_ACCESS.md。原本机启动入口会恢复127.0.0.1监听。

### 2026-10-02：STARTUP AUTO PUBLISH PIPELINE V0.1（接线实现，真实三成片模拟验收待输入）

当前结论 **STARTUP_AUTO_PUBLISH_PIPELINE_PARTIAL**。新增独立 `startup_pipeline/`（增量SQL迁移、服务、薄UI接线、40项隔离测试），仅修改原寻帧 `benchmark/experiments/dino_july_web/app.py` 和原Planner `ui.py` 的页面接线；没有修改合成核心、Planner算法/权限服务、稳定身份同步或整个 `xiaovcat_adapter/desktop_worker/`。全部受保护文件SHA256与基线一致，既有业务表逐行不变（本地登录验证产生会话记录除外），完整性ok、外键错误0。

先核实生产现实：起号模块当前输出**剪映草稿，不直接导出MP4**。既有7个批次Manifest在 `D:\video_search_tool\jianying_auto\runtime\batches\<batch_id>\batch_manifest.json`，含真实batch_id、生成时间、视频序号、composition_signature、选材、draft_path，但没有最终MP4路径。实际草稿根目录 `C:\Users\Administrator\AppData\Local\JianyingPro\User Data\Projects\com.lveditor.draft`；没有可确认的统一成片导出目录。此前指定目录 `D:\Users\Desktop\地狱素材` 仅识别到已发布过的 `组合1-自动合成.mp4`，不重新提交、不复制、不按文件名猜批次。已向用户请求至少3条现有起号导出MP4与batch_id/video_index映射，尚未收到。

已实现：登录后新批次在生成前记录服务端员工归属，原generate_batch完成后复用原Manifest登记稳定content_id；成功草稿先GENERATING，明确绑定现有导出MP4且本地ffprobe通过才READY。历史批次只能管理员明确指定所属员工；普通员工不能认领他人或旧批次。起号页面及发布管理增加待发布池，支持单条/多条/本批次全部、时长与本地预览、状态和删除保护。选择后自动携带content_id/MP4，复用原计划参数和完整时间槽，不重新选择文件；固定模板保存空标题、固定简介、独立topics_json、DEFAULT封面，并预留account_id/profile关联。

后端调用原get_publishable_accounts(employee_id,business_type=STARTUP)，再次校验稳定账号ID、内容归属、READY、媒体存在/非零/探测结果及文件变化、未来时间/跨天、模板与预览回执。确认才事务写原PublishPlan/items/PublishJob，新sidecar保存employee/account/source_plan/item/batch/signature/topics/cover；内容+账号+时间唯一签名防跨计划重复；失败全事务回滚。已排期/有任务的MP4禁止页面删除（本版不提供删除功能）。新任务NEEDS_MANUAL/STARTUP_SIMULATION_NOT_DISPATCHED，dispatch_mode=SIMULATION_ONLY，绝不进入PENDING队列、绝不调用Worker；外部开关被置true也拒绝模拟确认。

生产operations.db只新增接线表及默认模板，**新批次/内容/计划任务为0**；迁移前backup为 `operations.db.startup-pipeline-20261002_011450_896197.bak`。真实苏政超本地登录和起号页/待发布池已验证；稳定STARTUP组339642仍对应两个账号，COMMERCE当前0账号。既有账号UI快照已超30分钟，原可发布服务返回0，未伪造在线时间；使用真实素材模拟前须通过已有管理员同步入口刷新。隔离夹具3视频预览09:00/10:00/11:00、确认3条PublishJob及全部关联、防重、权限、按钮直达均通过，**不冒充苏政超真实成片验收**。

完整回归158/158（新接线40、原Planner62、适配器9、Worker31、原寻帧UI16）。证据 `xiaovcat_adapter/results/startup_pipeline_v01/` 的TEST_RESULTS、SIMULATION_PLAN（明确隔离夹具）、SOURCE_DISCOVERY、REAL_PERMISSION_CHECK、MIGRATION、PROTECTED_BASELINE、REPORT及页面截图。运行 `python -X utf8 -m startup_pipeline.verify` / `...startup_pipeline.acceptance`。ffprobe优先config.paths.ffprobe_executable或ffmpeg旁，否则复用adapter配置EXE目录已有resources/app/ffprobe.exe，不安装/下载。

另一明确边界：现有V0.3 Worker是固定测试视频dry-run，V0.4 submit是既有单JOB_ID/VIDEO授权脚本，**不是任意新PublishJob消费者**。本轮不改、不复跑它，也不宣称新任务已具备自动真实派发。后续真实一条验收需另行授权和确认兼容契约，不能仅把全局开关改true。既有XIAOVCAT_E2E_PASS及XIAOVCAT_GROUP_PLANNER_PARTIAL原结论保留，COMMERCE生产页阻塞不扩展。本轮real_publish_enabled=false，真实提交0，停止在当前范围。

### 2026-10-01：XIAOVCAT_GROUP_PLANNER 收尾 V0.2（真实分组ID已解决，PARTIAL）

当前最新结论以本节为准；下节V0.1的“group_id未取得/真实绑定阻塞”是历史现场，已解除。仅增量修改独立分组同步器，新增 `xiaovcat_adapter/group_identity.py`，通过原生 DevTools **Elements** 的公开UIA树读取分组 `tr[data-row-key]`，逐组精确XPath搜索后核对同一行名称/账号数；未执行Console脚本、CDP、IPC或网络接口，未读取小V猫凭据。常规UIA属性只有展示名，DevTools DOM树需去掉零宽/不换行空格并按公开aria level解析平铺结构；原Worker探测器40层限制会截断此树，新读取器独立实现，Worker不改。源渲染使用真实分组id为行键，两次关闭并重新进入管理页后十组ID完全相同；未擅自改名生产分组，改名不改权限由隔离回归覆盖。

真实映射：苏政超起号339642、苏政超带货339644、黄明贵起号339648、黄明贵带货339652、何华俊起号339653、何华俊带货339655、凌荟璇起号339658、凌荟璇带货339659、黄小慧起号339660、黄小慧带货339661。十组均存 `xiaovcat_groups.group_id/source_group_id`、`identity_status=SOURCE_ID`。两个在线抖音号丙曜（account_id1621131832863931）及62288252897（account_id3031801633454512）均关联339642；其余九组当前0账号。同步边界仅把完整可见账号归属与唯一源组行关联并校验数量；运行时权限仅查询持久化group_id/account_id，不查名称或后缀。

用户显式选择“新增员工苏政超，登录名suzhengchao”，已创建员工c160d384-c285-4a41-824e-dd7f93c8aff7并绑定339642/STARTUP和339644/COMMERCE，未自动按员工姓名推断授权。真实员工登录、管理员表单回读、起号生产入口/计划预览已验证：STARTUP返回两号，COMMERCE返回0并阻止创建；其他既有未绑定测试员工看不到这两号，手工传入返回ACCOUNT_PERMISSION_DENIED。COMMERCE传STARTUP账号同样被拒绝。现场没有任何真实COMMERCE账号，反向跨类型/其他员工已有账号隔离测试通过，但不能声称完整真实带货成片计划通过。

写入前SQLite backup：`operations.db.finish-v02-20261001_204823_371393.bak`。没有临时组记录需重绑，源组从0增至10；RECONCILE报告含old_group_key/new_source_group_id/group_name/affected_accounts/affected_bindings，并另记录新增显式绑定。既有员工、PublishJob、published_content、performance_snapshots、state_events、四条测试计划明细逐行保持。完整性ok、外键错误0，未新增任何PublishJob或派发任务。

证据在 `xiaovcat_adapter/results/group_planner_finish_v02/`：sync1/sync2/LIVE_SYNC.json、GROUP_ID_STABILITY.json、RECONCILE.json、REAL_PERMISSION_CHECK.json、ACCEPTANCE.json/REPORT.md及03～08网页截图。118项回归全部通过（规划器62、适配器9、Worker31、原寻帧UI16），新增10项DOM身份解析安全测试。`publish_planner.verify.run(results=...)`仅增加结果目录参数，不改算法；`python -X utf8 -m publish_planner.finish_acceptance`用于明确本轮指定员工绑定/预览验收，不创建任务。新本地员工初始密码仅在同目录 `LOCAL_EMPLOYEE_LOGIN.private.json`，Windows ACL限定Administrator、gitignore排除；不在报告打印。

唯一开发阻塞B：现有仓库只定位到带货分析/审核服务器，没有找到“带货/8模块生产页面”的发布账号控件，已向用户询问具体网址/文件/启动入口，尚未获得。统一COMMERCE service与计划页已验证，不等于该生产页面已接线；不要新造生产模块或声称PASS。已验证起号入口维持STARTUP。Worker全目录非缓存文件SHA256与V0.1基线完全相同，real_publish_enabled=false，提交0，既有XIAOVCAT_E2E_PASS/PERFORMANCE_SYNC_PARTIAL_VIP保持原结论。最终 **XIAOVCAT_GROUP_PLANNER_PARTIAL**，等待入口后只接B，不重新设计已通过调度/权限功能。

同步使用前提：小V猫已登录、管理面板关闭、没有未知弹窗、账号无筛选/不分页且已打开的账号选项卡与完整清单一致。遇用户已打开DevTools、焦点变化、DOM布局变化/组ID不唯一/名称数量不匹配即停止转人工；只关闭同步器自己打开的DevTools，不关闭用户应用，不点击业务写入/分发按钮。

### 2026-10-01：XIAOVCAT_GROUP_PLANNER V0.1（多业务分组，PARTIAL）

本轮已真正实现 `publish_planner/`、两次增量迁移及寻帧8502页面“工作区 → 发布管理”，不是仅文档规划。入口提供我的账号、发布计划、发布任务，管理员另有员工管理/只读同步。独立本地会话鉴权；真实 Worker 全目录非缓存文件SHA256与本轮基线一致，未修改、未调度，既有 `XIAOVCAT_E2E_PASS` 和 `PERFORMANCE_SYNC_PARTIAL_VIP` 保持原结论。全局 `real_publish_enabled=false`，本轮提交调用0。

员工权限已按最新业务修正为 `employee_id → employee_group_bindings → group_id → account_id`。关联表含employee_id/group_id/group_role/enabled/created_at，每类允许多个组；`STARTUP`起号、`COMMERCE`带货由管理员明确绑定，不从名称推断。employees旧xiaovcat_group_id列仅保留兼容，任何权限查询均不使用它。旧单组字段不自动迁移授权；管理员保存绑定后旧员工会话失效。账号页面分“我的起号账号/我的带货账号”，管理员额外可查看全部启用账号；`PublishPlan.business_type`与生产边界再次校验，越权或跨类型返回 `ACCOUNT_PERMISSION_DENIED`。

真实UIA同步和网页同步按钮均已运行：当前10个自定义组，苏政超起号2账号；苏政超带货、黄明贵起号/带货、何华俊起号/带货、凌荟璇起号/带货、黄小慧起号/带货均0。当前无筛选/不分页表实际2个在线抖音号：丙曜 `1621131832863931`、62288252897 `3031801633454512`，稳定账号ID已存入operations.db。此前3个离线账号保留历史ID和记录，完整当前清单确认后仅停用，不删除；局部快照不自动停用遗漏账号。10组名称/数量/UIA证据已记录在group_sync_runs，但UIA未暴露稳定group_id，稳定身份组表仍0；不能把“未取得ID”解释成“源不存在ID”，未造名称型本地映射。因此真实员工多分组绑定仍阻塞，测试员工存在但真实授权账号0；不得声称已完成真实绑定验收。

计划器已支持分钟级首发时间、数量1～20默认5、8档间隔与自定义1～1440分钟、逐日重置、默认跨天拒绝/显式允许、PER_ACCOUNT/PER_PLAN_TOTAL及SEQUENTIAL/ROUND_ROBIN_ACCOUNT。预览不落库，确认才事务写入；schedule_signature唯一、重复确认新增0。业务修正前创建的4条本地测试任务保留（11:15/12:30/13:45/15:00，75分钟）；状态NEEDS_MANUAL、PLANNER_TEST_ONLY，不在PENDING队列，新业务规则下没有稳定组和明确role绑定不能创建新计划。起号自动合成已增加锁定STARTUP的已有MP4计划入口，不把剪映草稿当成片；统一计划页支持COMMERCE，`production.py`提供带货/8模块类型限定边界，但现有带货代码未找到发布步骤页面，不能声称那一页面已接入。

迁移用SQLite backup一致性备份，未启用WAL；原始PublishJob/published_content/performance_snapshots/state_events/E2E记录保留，v2迁移另逐行保护已有员工及4条计划明细。证据：`xiaovcat_adapter/results/group_planner_v01/{ACCEPTANCE,MIGRATION,MIGRATION_MULTI_GROUP,TEST_RESULTS,LIVE_SYNC,WORKER_BASELINE}.json`与页面截图。运行 `python -X utf8 -m publish_planner.verify` 为隔离测试，`python -X utf8 -m publish_planner.acceptance`为本轮固定plan_id幂等验收，不启动Worker。以最新TEST_RESULTS.json为最终测试数；ACCEPTANCE.json包含21项验收，不以隔离夹具代替真实数据。生成的本地测试登录资料在同目录LOCAL_TEST_LOGIN.private.json，已限制Windows ACL并加入gitignore，不在报告打印密码。

最终108项回归全部通过（规划器/多分组/组件52、适配器9、原Worker31、原寻帧UI16），16个Python文件语法通过。最终 `XIAOVCAT_GROUP_PLANNER_PARTIAL`：主要剩余阻塞为稳定源group_id及账号到组ID的映射；另一未完成项是现有带货/8模块发布页面接线。本轮完成后停止，不进入真实批量发布、手机端或数据分析。

### 小V猫分组身份约束（后续接入继续遵守）

分组与账号采用相同的稳定身份原则：如果小V猫提供稳定 `group_id`，必须同步并以该源ID作为 `xiaovcat_group_id`，不能另造ID替代；`group_name` 仅用于展示，不得作为主键、员工绑定外键或权限关联键。员工绑定必须引用 `xiaovcat_group_id`，账号与分组的成员关系也通过稳定ID关联。

例如“员工A组”改名为“张三运营组”，只更新展示名称，分组ID、员工绑定与账号权限关系保持不变；不得按新名称创建新组或重绑员工。只有确认小V猫没有稳定 `group_id` 时，才允许建立并持久化本地稳定分组ID，作为 `xiaovcat_group_id` 使用，并维护本地ID到source group的映射。该映射不能仅靠 `group_name` 识别；改名后沿用同一ID。源组无法唯一对应时要求人工核对，禁止按名称猜测、自动新建或迁移权限。“尚未取得ID”不等于“小V猫不存在稳定ID”。

历史V0.1适配器的 `Account.group_name` 仍仅为展示字段；独立规划器稳定ID表和多组绑定见最新收尾节，源group_id获取与十组真实落库已完成。员工绑定使用employee_group_bindings.group_id（即稳定xiaovcat_group_id语义），不再使用employees单组列；本条不恢复发布/定时跟进。

### 2026-10-01：Xiaovcat V0.4 最终验收（XIAOVCAT_E2E_PASS，数据回流单独PARTIAL）

最终发布结论：`XIAOVCAT_E2E_PASS`。用户在本线程明确确认“本次测试作品已在抖音端实际可见”，作为平台真实发布完成的人工确认依据；本轮未再次操作UI自动核验。验收依据为只提交1条、丙曜/抖音、定时任务成功、抖音端真实作品出现、没有重复提交、`real_publish_enabled=false`。该结论仅覆盖本次指定单任务，不代表批量发布已验收。

数据回流单独记录为 `PERFORMANCE_SYNC_PARTIAL_VIP`：作品管理在线/本地数据页提示VIP限制，未绕过；平台作品ID/URL、首次播放/点赞/评论、精确实际发布时间仍未取得，保留null，不能补造或记0。`POST_SUBMIT_CHECK.json` 为本轮最终验收报告，已注明发布确认来源为用户，不再将发布状态写为待定。

用户操作时明确确认后，仅对 `D:\Users\Desktop\地狱素材\组合1-自动合成.mp4` 的丙曜/抖音任务在本机17:08:53调用“一键分发”1次。定时2026-10-01 19:18（UI仅分钟精度，提交所在分钟17:08加130分钟；实际相差129分6秒）。原文件HEVC Main10、720×1280、30fps、52.78秒、AAC LC，未转码/创建素材副本；标题空白，简介“陶老师小妙招”，实际话题健康/健康科普/养生，无另选封面。提交前及提交后只读任务详情均回读正确。

新增隔离 `desktop_worker/v04_submit.py`：固定唯一job_id，PRE_SUBMIT_CHECK完整实时核验，SQLite BEGIN IMMEDIATE事务在UI调用前持久化一次性闩锁，任何异常/未知/已预留均禁止再次提交。全局config始终false，仅本任务内存许可临时启用，finally立即关闭；没有消费通用队列。空标题仅显式单任务allow_empty_title可用，旧模型/队列默认仍拒绝。40项隔离测试通过（31 Worker+9适配器）；语法通过，未修改搜索、合成、生产索引库或模型。

提交当时小V猫提示“发布任务已创建，已在后台执行中”；唯一任务记录显示“已同步”、指定账号/文件名、19:18定时。新增SCHEDULED_QUEUED与独立v04_audit证据登记，内部content_id与唯一PublishJob建立映射。历史operations.db记录保留提交当时的SCHEDULED_QUEUED，本轮依用户要求仅更新文档和验收报告，没有改数据库/控制代码/配置；最终平台发布结论以上方用户确认和报告为准。证据在 `xiaovcat_adapter/results/real_publish_v04/` 的PRE_SUBMIT_CHECK、SUBMIT_RESULT、POST_SUBMIT_CHECK和58/60/62/64截图，原始提交/核验证据不改写。

本线程只读heartbeat“丙曜单条定时发布只读验收”（id=automation）已停用（PAUSED），落实用户“更新后停止”。本轮没有修改发布控制链路、没有新提交、没有消费其它任务。以后任何接手者不得再次运行submit-once或消费其它任务；如需继续数据回流，必须等待用户另行授权。

### 2026-10-01：Xiaovcat V0.4 单任务准备（等待操作时确认，未提交）

独立新增 `desktop_worker/v04_prepare.py` 与 `v04_precheck.py`，继续本机 UIA + 受控键盘、标准文件对话框及逐步截图回读，不使用 RPC/私有接口。用户指定唯一原素材 `D:\Users\Desktop\地狱素材\组合1-自动合成.mp4`，ffprobe 为 HEVC Main10、720×1280、30fps、52.78秒、AAC LC；用户已明确要求原文件、不转码、不生成副本。已加载并显示52秒视频预览。

实时确认仅丙曜抖音号在线且选中；通用和右侧标题均为空、简介均为“陶老师小妙招”，三个实际话题芯片健康/健康科普/养生一致。同步弹窗有独立字段勾选，封面2和追评不勾选；右侧残留 V0.3 测试封面已替换为当前视频自动默认帧，没有另选自定义图片。发现抖音右侧要求至少提前2小时，与原1小时要求冲突而停止；用户随后明确改为提交前本机当前时间加130分钟。现表单暂定2026-10-01 18:49，两侧定时模式/值已回读，真正提交前必须重新计算130分钟并重新验证，不能沿用这个预览时间。

证据在 `xiaovcat_adapter/results/real_publish_v04/`，`PRE_SUBMIT_CHECK.json` 当前为 `AWAITING_ACTION_TIME_CONFIRMATION`；`form_fields_verified=true`，但 `all_checks_passed=false`，因为尚未完成操作时确认/最终实时核验。全局 `real_publish_enabled=false`、最终调用次数0、submit_attempted=false；未写入实际 V0.4 PublishJob，未消费队列、未进入定时任务、未生成作品ID/指标，不能称真实发布成功。准备工具没有提交实现；下一轮获确认后仍需单任务 durable at-most-once guard、限定任务启用/finally关闭、提交后未知结果转人工且绝不重试，禁止套用有默认重试的旧发布状态机。空标题与既有模型必填约束也须用明确兼容的单任务路径处理。

12项新纯核验测试 +14项既有 Worker 安全测试 +9项适配器回归通过；测试只使用模拟/临时数据，不操作桌面。首次沙箱临时目录权限失败，隔离重跑通过。未修改生产索引库、检索、合成或模型。

### 2026-10-01：本机交互式 Xiaovcat Worker V0.3（PASS，仅提交前）

新增独立 `xiaovcat_adapter/desktop_worker/`：不依赖 Codex computer-use RPC，从当前登录桌面 Session 1/Default 直接调用 UIA COM。首次仅见容器，激活真实窗口再探测后 UIA2/UIA3 可见 Chromium 页面按钮/输入/账号树。主通道改为已真机验证的 UIA，唯一 fallback 为焦点校验 + Unicode SendInput + UIA 回读的 KEYBOARD_ASSISTED；不启用视觉点击/CDP控制，不再沿用 V0.2 尚未验证的 HYBRID/视觉方案。`--force-renderer-accessibility` 本轮未启用验证（保留原进程），CDP9223无监听；测试启动器供正常手工退出后单独验证，Worker 绝不杀/重启已有进程。

最终版本通过实际 `run_worker.ps1` 完整完成：单视频发布页 → 标准文件选择器、安全测试 MP4 → 读取5个可见账号（2在线/3离线）并选1个在线抖音账号 → 通用/账号标题与简介共4字段精确回读、最终再次确认 → 识别“一键分发” → STOP。最终结论 `XIAOVCAT_DESKTOP_WORKER_PASS`；`real_publish_enabled=false`，最终提交调用次数0。测试 mp4v 文件已载入并显示测试封面，但不支持播放器预览，不代表真实上传已验证。未知弹窗/已有草稿/读取不完整等均停止到 NEEDS_MANUAL，已知选择面板关闭动画有明确状态等待。普通窗口/移动/最大化后定位与值验证通过，DPI96/100%，未测试其它系统缩放。14项新安全测试、9项既有回归通过。

运行：根目录 `小V猫自动化测试.bat` 或 `xiaovcat_adapter/desktop_worker/run_worker.bat`。当前 POC 表单仍保留；复跑前用户自行保存/清空，正常 Runner 不自动覆盖/清空。证据：`xiaovcat_adapter/results/desktop_worker_v03/REPORT.md`，最终成功 run 为 `run_20261001_145847_361298`，六阶段截图及机器报告齐全。3101固定只读根/健康/upgrade探测均404，无公开本地UI服务契约证据，放弃。未接队列或修改 operations.db/生产数据/检索/合成/分析链，未进入真实发布。

### 2026-10-01：XIAOVCAT UI CONTROL CHANNEL POC V0.2（PARTIAL）

本轮只处理小V猫 UI 控制通道，未开发发布中心、数据看板、批量发布、手机端或真实发布。新增只读 `xiaovcat_adapter.ui_channel_probe`，使用 Windows 进程/窗口 API 枚举进程模块和 HWND/Class，并探测 UIA host provider 与 MSAA `IAccessible`；不发送键鼠输入，不读取凭证。已确认小V猫 3.0.0 是 Electron 40.2.1 + Chromium 嵌入式 Web UI：主窗口 `Chrome_WidgetWin_1`，渲染窗口 `Chrome_RenderWidgetHostHWND`，无标准 Win32 `Edit/Button/List/ComboBox` 业务控件。18个相关 HWND 的 `UiaHostProviderFromHwnd` 和 `AccessibleObjectFromWindow` 均成功，说明小V猫 HWND 层存在 UIA/MSAA provider。

之前 UIA 树为空的主要原因不是小V猫完全无 provider，而是当前 Codex Windows 原生控制传输层不可用：`sky.list_apps()` 报 `Trusted RPC service is not configured`，重置后 `cua.getState()` 仍为空 app 列表，`listWindows`/native launch 均不可用；小V猫进程和可见主窗口实际已存在。因此本轮无法安全执行 UIA ControlView/RawView 枚举、键盘导航、截图、账号读取、MP4选择或文字填写，也未识别/点击最终发布按钮。安全测试 MP4 已只读验证为 `auto_remake/tests/test_videos/合成 参考视频.mp4`（36秒，542,204字节），但未送入小V猫。

控制方案决定为 `HYBRID`：UIA/MSAA 做状态校验，键盘做文本与文件对话框操作，只有 Chromium 节点不暴露时才用窗口相对位置+特征校验；单一 fallback 为 `VISION_ASSISTED`，禁止绝对桌面坐标。此方案为基于技术栈的决策，尚未真机验证。状态机新增回归测试，确认 `UNKNOWN_DIALOG` 会停止并转 `NEEDS_MANUAL`；适配器共9项测试通过。最终结论 `XIAOVCAT_UI_POC_PARTIAL`。证据见 `xiaovcat_adapter/results/ui_poc_v02/channel_probe.json`、`evidence_manifest.json` 和 `REPORT.md`。

### 2026-10-01：小V猫发布与数据回流适配器 V0.1（PARTIAL）

新增完全独立的 `xiaovcat_adapter/`，不接入检索、合成或分析生产链。已实现 `PublishJob`、1～50 条入队接口（V0.1 真机限制最多3条）、完整发布状态机、每步超时与默认重试1次、失败截图/日志接口、CSV/XLSX/XLS 作品数据回流和统一服务边界。项目根目录已建独立 `operations.db`，含 `publish_jobs`、`published_content`、`performance_snapshots`、`accounts`、`state_events`；未开 WAL，未连接生产索引库。`real_publish_enabled=false` 是默认且已用单元测试确认：状态机到 `VALIDATE_FORM` 后返回 `DRY_RUN_READY`，不执行 `SUBMIT`。8项适配器测试全部通过。

本机只读发现已定位 `D:\小V猫\小V猫.exe`、`小V猫.exe` 进程、主窗口标题“小V猫”、配置目录 `C:\Users\Administrator\AppData\Roaming\小V猫`、空的 `_download/_upload` 目录与 `127.0.0.1:3101` 监听。注册及 package 版本为3.0.0，EXE文件版本为2.0.0；本机端口对 `/`、`/health`、`/version` 均返404，未发现可直接合法调用的稳定接口。本轮 Windows UIA 通道未暴露原生应用窗口，项目 Python 也没有 `pywinauto`，所以未采集真实控件选择器，未读取账号，未上传视频，未进行真实 dry-run 或数据导出。结论为 `XIAOVCAT_ADAPTER_PARTIAL`，因前置 UI 验证未通过，没有修改 `video_search.py` 或新增“发布中心”。完整证据见 `xiaovcat_adapter/results/discovery_20261001.json` 和 `xiaovcat_adapter/results/ACCEPTANCE_20261001.md`。

### 2026-09-30：3.mp4 DEMO / CTA 缺口补全旁路实验

按 `autonomous_research_v01/NEXT_STEP.md` 只处理3.mp4，新增 `bestseller_analysis.demo_cta_gapfill_3`。DEMO以3.mp4的148.59–155.58秒真人手法实操为参考，使用正式DINO四帧近邻和CLIP三组强视觉查询，Speech只补上下文；去除同直播备份副本后保留2个可播放候选（1个STRONG、1个WEAK），补全1/1 DEMO槽。CTA使用Speech exact+semantic两阶段召回，结合即时前后各2句及40秒内最近商品指代句，只保留指向小妙招/视频课程的购买行动；已硬排除课程介绍、价格无行动、既往销量和“不要/不用去拍”等否定句，找到可靠CTA候选。

结果在 `bestseller_analysis/results/batch_20_v1/autonomous_research_v01/demo_cta_gapfill_3_v01/`：`REPORT.md`、`demo_candidates.json`、`cta_candidates.json`、`replication_plan_3_v02.json`、`review.html`及19个短预览。只读审核服务为 `python -B -m bestseller_analysis.gapfill_review_server --port 8506`，页面和参考/候选视频Range分别实测HTTP 200/206。最终7个结构槽全部有候选（6 STRONG、1 WEAK、0 UNRESOLVED），machine-derived覆盖率100%，结论`READY_FOR_SINGLE_PREVIEW`；这只表示值得进入单条预览验证，不等同人工Gold或精准复刻。本轮27项模块测试通过、19/19预览完整解码；未生成视频/剪映草稿，未修改生产数据库、FAISS、DINO/Speech/CLIP索引、寻帧、Template Editing或剪映模块。

### 2026-09-30：带货视频自主研究模式 V0.1

新增只读旁路脚本 `bestseller_analysis/autonomous_research.py`，复用 `batch_20_v1` 的20条/7.06小时/2768个机器Content Segment，以及现有独立内容池2457段，不重跑ASR、OCR或视觉分析。研究包含两轮：业务序列/位置/节奏统计，以及置信度≥0.70稳健性、本地素材覆盖、候选选材模拟和9/7/8/3/19复刻规划。Top12转移关系在高置信重算中保留10个（Jaccard 0.714）；最稳定规律是CONTENT、DEMO、PROOF多轮循环，DEMO先于PRODUCT 17/18、PROOF先于PRODUCT 16/18。HOOK覆盖20/20、平均8.77秒、3.15切镜/10秒，明显快于中后段。

业务先验明确为“小妙招/小灵招=课程教学商品”；只有明确动作且无商品语境时才判普通技巧。脚本将强商品词与“买/学习/教学”等弱词分开，避免把上下文词错误提前到当前片段。CTA专项质量审计发现原29个机器CTA候选中仅2个满足较严格商品/购买语境，27个是弱候选或可能误报，因此没有把CTA次数和顺序固化为规则。

结果在 `bestseller_analysis/results/batch_20_v1/autonomous_research_v01/`：`AUTONOMOUS_RESEARCH_REPORT.md`、`NEXT_STEP.md`、`research_data.json`、`sequence_patterns.json`、`candidate_selection_simulation.json`、`replication_plans.json`。本地质量候选覆盖HOOK 89、CONTENT 944、PRODUCT_BRIDGE 32、PRODUCT 101、PROOF 38；DEMO仅6段/4个asset，严格商品CTA在本次模拟中保留UNRESOLVED。只生成候选计划，未生成视频或剪映草稿。18项模块测试通过；未修改生产数据库/FAISS、DINO/Speech/CLIP索引、寻帧、Template Editing、剪映生成或机器原始分析。

### 2026-09-30：带货爆款第一轮人工审核 V0.1

在已完成的 `bestseller_analysis/results/batch_20_v1/` 上新增人工审核工作流，不重跑20条分析，也不要求审核全部2768个Content Segment。新服务 `bestseller_analysis.human_review_server` 仅建立三条队列：25个Gold Example候选、7条机器未识别可靠CTA的视频（5/6/12/16/17/18/20）、5条复刻候选（9/7/8/3/19）。入口分别为本机8505端口的 `/gold`、`/cta`、`/replication`；双击根目录 `打开带货第一轮人工审核.bat` 可启动。

Gold审核显示视频、片段边界、原话、前后文、机器角色/标签/产品衔接/信任/销售机制/置信度/证据，人工可填写GOLD/USABLE/REJECT、边界结论与时间、角色、多标签、错误原因、备注及“实际会用于剪辑吗”。按审核组A（HOOK/CONSULT/PRODUCT）、B（PROOF/TRUST）、C（CTA）筛选，无账号系统。CTA专项显示整条业务时间线，可确认确实无CTA或补录跨Segment的软/直接/紧迫/结尾CTA及前置角色。复刻队列显示完整视频、结构、Gold匹配和商品/PROOF/CTA节点，只保存人工评分与是否适合，不自动选最佳。

人工层独立保存到 `bestseller_analysis/results/batch_20_v1/human_review/`，包含 `human_gold_data.json`、`cta_review.json`、`replication_review.json`、`review_progress.json`。同时将产品首次提及、首次画面出现、首次承担销售功能拆成三个可选人工时间字段；不覆盖旧的机器统计。顶部显示25/7/5进度和GOLD/USABLE/REJECT/未审核数；只有三队全部完成才允许生成 `ROUND1_REVIEW_REPORT.md` 与结构化统计JSON。14项模块测试通过，三个页面HTTP 200、视频Range 206、未完成报告409、跨源POST 403。未修改模型、生产数据库/FAISS、寻帧、Template Editing、DINO/Speech/CLIP或剪映生成。

### 2026-09-30：独立带货爆款视频分析 V1（20条，待人工审核）

新增独立目录 `bestseller_analysis/`，对桌面“爆款视频”20条真实带货成片完成本地离线分析，共7.06小时。已保留ASR、OCR、抽样视觉分析、镜头边界和联系人脸等底层缓存；镜头边界仅作为Content Segment的边界、节奏和转场辅助信号。业务层生成2768个Content Segment，支持1个`primary_role`和多个`function_tags`，覆盖HOOK、问题/咨询/解释/演示、产品衔接/介绍/价值/演示、证明/反馈/权威/信任及多种CTA，并记录产品进入方式、信任机制、销售机制、阶段节奏、上下文证据与置信度。

完整结果保存在 `bestseller_analysis/results/batch_20_v1/`：逐视频时间轴和报告、`BUSINESS_REPORT.md`、`business_aggregate.json`、`gold_examples.json`、`replication_candidates.json`、`dataset.sqlite`及人工审核页。双击根目录 `打开带货分析审核.bat` 可在本机审核视频片段，修改边界、角色、标签、产品可见性、信任机制、错误原因和备注；保存后生成`reviewed_segments.json`，只有人工勾选通过的片段才进入`human_gold_data.json`。当前25条Gold Example均为机器候选，不得当作人工真值；产品画面是否真正可见也默认留空等待人工确认。

该模块没有读取或修改生产数据库、FAISS生产索引、MobileNetV2/预处理/检索逻辑、Template Editing生产代码或剪映生产模块；本轮也没有训练/微调模型或进入自动生成阶段。11项独立单元测试通过。主报告中的结构、模板、CTA和节奏结论属于第一版机器分析，需结合审核页修正后再作为Gold Data使用。

### 2026-09-30：起号自动合成支持1～10条批量草稿

起号页面在有效Slot组合后新增“生成数量”1～10下拉框，默认1；数量大于1时按钮显示“批量生成剪映草稿”。每条草稿沿用同一Slot类型顺序，但都会重新选材；单条内部同类素材继续优先无放回，批次内用Slot类型和规范化源路径生成SHA-256 `composition_signature`，最多重试50次避免完整组合重复，素材组合空间不足时允许重复并明确提示。批次逐条调用原 `generate_draft()`，单条失败会记录后继续后续任务，页面显示逐条进度、成功/失败汇总、每条实际素材和草稿目录。

批次记录保存在 `jianying_auto/runtime/batches/<batch_id>/`，包含 `batch_manifest.json` 和每条 `video_XX.json`；剪映草稿仍直接写入剪映要求的草稿根目录，不做不兼容嵌套。Manifest记录批次时间、请求/成功/失败数、Slot顺序、素材、签名、草稿路径和错误。12项adapter与16项直接UI测试、共75项相关回归全部通过。5组真实批量验收全部成功：`20260930_160536` 引流→手法1条，`20260930_160607` 引流→手法→收尾3条，`20260930_160701` 引流→手法→手法→收尾5条，`20260930_160824` 坐诊→手法→收尾10条，`20260930_161131` 引流→坐诊→手法→手法→收尾10条。共29个草稿逐一核对主轨段数、路径和顺序均与Manifest一致，5条和10条含双手法的15个草稿全部使用两个不同手法文件；各批签名唯一数等于草稿数，均无失败、无重复组合警告，每条清单齐全。本轮未修改Template Editing、图片/话术/文字搜索、DINO、Speech、CLIP、索引或数据库。

### 2026-09-30：剪映草稿目录权限诊断

用户在Web生成 `组合17-自动合成` 时遇到 `PermissionError [WinError 5]`。核对确认目标目录不存在、剪映草稿根目录ACL给当前Administrator完全控制；根因是8502服务由受限沙箱启动，剪辑子进程继承限制，非素材、重名或Windows ACL问题。将8502重新启动到正常本机权限后，通过网页原按钮真实重试成功：`组合17-自动合成`，引流1段，12.8秒，页面正确显示草稿路径和实际素材。

`jianying_adapter.py` 新增真实写权限探针，生成前在草稿根目录创建并立即删除临时文件；受限时直接提示关闭8502并双击根目录 `启动寻帧.bat`，不再把pyJianYingDraft长堆栈暴露给用户。8项adapter和15项直接UI测试通过。加载探针后的8502再次通过网页生成 `组合18-自动合成`（引流1段，9.6秒），证明正常权限不会被误拦截。未修改剪映合成核心、搜索模块、索引、数据库或素材。

### 2026-09-29：起号自动合成支持连续1～5段

起号页面仍固定显示5个Slot，但实际生成段数改为1～5：片段1必须为引流/手法/坐诊/收尾；片段2～5增加“无”且默认“无”。遇到第一个“无”后，后续Slot自动重置为“无”并禁用；adapter的 `parse_slots()` 同时拒绝任何中间断层，提示“第N段为空时，后续片段不能再选择”。预览只显示实际组合和“共N段”，“无”不会选素材、不会进入时间线。原目录配置、同类无放回选择、素材不足提示、生成结果明细及高级字符串模式均保留。

7项adapter和15项直接UI测试通过；连同话术UI、Speech/Text adapter共48项相关回归全部通过。5组真实生成验收：`组合23-自动合成` 手法1段（37.300秒）、`组合24-自动合成` 引流→手法2段（53.834秒）、`组合25-自动合成` 坐诊→手法→收尾3段（254.135秒）、`组合26-自动合成` 引流→手法→手法→收尾4段（147.367秒）、`组合27-自动合成` 引流→坐诊→手法→手法→收尾5段（180.002秒）。各草稿主轨段数严格为1/2/3/4/5、空素材0；重复手法均为不同文件。5个草稿都保留贴纸复合片段、滤色、外层alpha=0.01及内层6贴纸alpha=1。本轮未修改其它寻帧模块或Template Editing。

### 2026-09-29：起号自动合成5段真实素材接入

寻帧第4个入口已改为“起号自动合成”，固定显示片段1～5五个下拉框，每个选项均为引流/手法/坐诊/收尾，并显示实时数量。真实目录统一配置在 `jianying_auto/jianying_source_folders.json`：引流10、手法44、坐诊30、收尾2，当前均在根目录、无子目录；共享扫描器已支持递归和 `.mp4/.mov/.ts/.mkv/.avi/.flv/.m4v/.webm`，不跟随链接离开4个配置目录。页面严格保留1～5顺序，同类采用无放回随机，只有数量不足才重复并提示；完成后展示每段类型、文件名、完整来源、草稿目录和素材总数。高级入口保留旧组合字符串，“流量”兼容映射为“引流”。

5项adapter、14项直接UI测试通过；连同话术UI、Speech/Text adapter共44项相关回归全部通过。4组真实生成均成功：`组合19-自动合成`（引流→手法→手法→坐诊→收尾，223.002秒）、`组合20-自动合成`（引流→引流→手法→坐诊→收尾，209.834秒）、`组合21-自动合成`（坐诊→坐诊→手法→手法→收尾，423.035秒）、`组合22-自动合成`（5段手法，215.568秒）。每个草稿主轨均为5段、路径顺序正确、任务内5个源文件互不重复；均保留1条贴纸复合片段，内层6贴纸alpha=1，外层滤色、alpha=0.01。8502真实页面已核验5个下拉框、4个固定选项、实时数量、组合预览和高级兼容入口。未修改图片/话术/文字搜索、Template Editing、DINO、Speech、CLIP或生产数据库。

### 2026-09-29：剪映自动合成接入寻帧

寻帧 `benchmark/experiments/dino_july_web/` 已增加第4种模式“剪映自动合成”。页面可选“坐诊 / 手法 / 流量手法”预设，或输入 `流量1+手法2+收尾1` 一类自定义组合；提交后由新增 `jianying_adapter.py` 调用独立 `jianying_auto/jianying_auto.py` 子进程，避免将字幕、剪辑依赖载入DINO/CLIP搜索进程。子进程强制本地离线环境，使用项目配置中的Python解释器，并通过Windows文件锁限制同一时间只生成1个草稿；失败会把本地日志返回页面。该功能只创建剪映草稿，不导出MP4。

`search_config.json` 新增向后兼容开关 `jianying_auto_enabled: true`，关闭后不显示入口。贴纸沿用已验证的复合片段流程：内层贴纸100%不透明，外层统一滤色、不透明度1%。3项adapter测试和14项UI测试通过；8502真实页面已核验入口、预设与生成按钮，未在Web验收时实际提交生成。没有修改生产数据库、DINO/CLIP/FAISS索引、模型或现有三种搜索路径。

### 2026-09-29：剪映自动合成贴纸复合片段

独立目录 `jianying_auto/` 的草稿生成流程已增加贴纸复合片段：6个随机贴纸先以100%不透明度写入内嵌子草稿，父时间线只保留1条“贴纸复合片段”视频轨道，外层统一设置混合模式“滤色”和不透明度1%。修复了旧实现把draft material ID误作video material ID、遗漏外层draft引用的问题；新增剪映11.5格式的虚拟video material，并清理旧的逐贴纸混合引用。`config.json` 的 `sticker_combination` 默认true，可设false回退独立贴纸轨道。

2项独立单元测试通过；实际生成 `坐诊4-自动合成`，结构验收为父时间线0条sticker轨、1条复合轨，子草稿6条sticker轨，外层alpha=0.01、滤色引用唯一，子草稿文件齐全。此结果只证明草稿结构完整，仍需用户在剪映专业版实际打开确认画面渲染；没有修改生产检索库、索引、模型或 `auto_remake`。

### 2026-09-29：Template Editing V0.1 独立候选审核（含首个Gold Set）

新增 `content_pool/` 与 `template_editing/`，不接入寻帧或auto_remake。正式Speech/BGE全库只读召回，回查生产字幕原ID与转写run；在3–20秒内合并连续字幕，保留前后文、来源、透明功能规则、商品小妙招消歧及评分证据。模板为独立ID的有序slot列表，允许同一功能重复；当前仍为坐诊转化型8个位置。Transition接口仅返回None，未做组合、timeline、成片或剪映草稿。

只读提取桌面 `爆款拆解-举例.xlsx` Sheet1的20条案例：15条话术、5条标题/摘要，拆成25个语义原型。苗老师→陶老师、小灵招→小妙招；保留原话，检索时弱化为老师/这套课程。按具体话术映射功能，不照搬“逼单/反馈”标签；原始召回和增量Gold召回分别保存。每个推荐有Gold原话、单元格、功能、相似度和共同功能依据；Gold有效分占最终12%，摘要折减，无共同功能不加分。

最终从覆盖318个字幕asset的正式索引中检索，实际候选涉及281个asset，2770个去重窗口；扩展核对23801条唯一原字幕（seed内5673条），形成2457个Content Segment。8个slot各Top10，共80条、63个独立原声MP4预览全部解码通过。规则有效候选依次49/30/25/62/28/45/28/13；PRODUCT_BRIDGE和CTA_END较薄弱。Top10中15个展示位置来自Gold独有召回（11个不同片段），不代表人工可用率已改善。部分原始字幕存在碎片、转写噪声和否定语义误召回，已在报告注明。

结果 `template_editing/results/consult_conversion_v1_v01/report.html`，双击根目录 `打开模板候选审核.bat`，或运行 `python -B -m template_editing.serve`，只监听127.0.0.1:8503。反馈独立保存至同结果目录 `template_feedback.json`，键为report/slot/segment，已验证实际浏览器保存、刷新恢复及原声预览完整播放。测试评价已单独归档，业务反馈初始为空。首轮含首次预览70.701秒，最后小修正复用召回/预览18.555秒，有效处理累计89.256秒；不含开发、测试及人工等待。

17项新测试、26项原项目测试、13项原Speech测试通过。2018个生产/索引/Web/auto_remake/模型受保护文件状态和集合不变，Excel SHA256不变。状态 `TEMPLATE_V01_REVIEW_READY` 仅指审核包就绪，尚未通过人工素材质量验收；建议先收集80条人工反馈，本阶段停止，不进入V0.2。详见 `template_editing/README.md`、结果目录 `report.md` 与 `validation.json`。

### 2026-09-28：话术搜索正式全库语义索引（完整性READY，未接Web）

`speech_search/index/formal_v1/` 已完成318个有字幕asset的全部3,099,048窗口：1/2/3段分别1,055,692 / 1,031,878 / 1,011,478。复用原BGE-small-zh-v1.5 Encoder与固定revision，512维FP32 CLS/L2；embedding、metadata、FAISS逐行一致，失败0，完整性READY。FAISS为6,346,850,349 bytes，建库16分31.6秒，真实停止/续跑验证复用前128向量。原1,060条字幕时间警告对应3,147窗口，原时间不变。

新增正式构建、验收、查询和评测脚本，原pilot与验证结果保留。CLI使用 `speech_search/formal_query.py`，Exact/Fuzzy/Semantic独立输出，默认Semantic，无融合。全库32例素材Top1/5/10：Exact50/50/50%，Fuzzy68.75/71.875/75%，Semantic78.125/90.625/93.75%，Semantic附近时间Top10为30/32。相较pilot Semantic31/32 Top1、32/32 Top10明显退化；同义通用短句竞争及否定句区分不足已有案例证据。新增另20个asset的20例Semantic19/20 Top1/5/10；不据结果改参数。CPU暖语义查询52例median297.1ms/P95 309.4ms。

当前只可称索引完整性通过，不应宣称32例效果无退化或已通过生产质量验收，暂不建议直接接入Web作为已验收功能。原字幕、DINO/CLIP、图片排序、Web、ORB保持不变，未启动Whisper。13项测试通过。完整证据见 `speech_search/index/formal_v1/final_report.md`，操作见 `speech_search/FORMAL_README.md`。本阶段已停止，未继续Web开发。

### 2026-09-28：话术搜索V1独立验证（未接Web、未全库语义编码）

新增 `speech_search/`，只读复用 `video_index_fixed.db` 1,062,422条字幕与SHA逻辑资产映射。独立库归并为1,058,667条规范化字幕、3,099,048个1–3段窗口，全部原ID/原文/来源保留；FTS5二元组召回后最多400候选RapidFuzz，精确优先，其余排名RRF。异常时间1,060条仅加警告，不改事实库start/end。

中文BGE-small-zh-v1.5固定revision仅对8个asset/143,391窗口做独立语义pilot。32例同范围素材Top1/5/10：精确50/50/50%，fuzzy78.125/87.5/90.625%，semantic96.875/100/100%，融合87.5/100/100%；融合正确时间附近Top10为30/32，不能把素材命中当精准定位。10项新测试及26项原测试通过。CLI已可运行，语义不是全库；未转写、未改DINO/CLIP/Web、未全库embedding。结果与限制见 `speech_search/report.md`，用法见其README。


### 2026-09-28：寻帧正式CLIP文字搜索接入

文字模式通过新增 `benchmark/experiments/dino_july_web/text_adapter.py` 复用 `clip_index.query.TextSearch`，CPU文字编码、CLIP formal_v1 Top20，页面显示前10；按原frame_id/frame_number只读DINO JPEG提供缩略图，复用短预览和反馈。加载前检查report、严格验收READY、文件及数量，真实FAISS ntotal由原TextSearch再核对。文字异常/关闭不会加载或影响DINO图片引擎。

`search_config.json` 增加 `text_search_enabled: true`；设false后双击启动寻帧.bat重启即可单独关闭。图片的formal_v1_repaired、Top500、每asset最多5帧、10秒间隔和ORB关闭保持原样，search_adapter.py本次逐字节未变。文字反馈复用现有schema，index_version为clip_formal_v1、保存中文原query/英文prompt/后端Top20及人工反馈。

40项轻量测试通过；真实Web完成3张图片和5条中文，每条验证缩略图、短预览、反馈。8条验收反馈已核对并定向清理，原业务记录不变。CPU暖文字查询含缩略图组装median49.5ms/P95 52.6ms（15次），DINO及CLIP正式目录987个文件大小/mtime与集合不变。完整证据见 `benchmark/experiments/clip_web_rollout/report.md`。状态TEXT_SEARCH_PRODUCTION_READY；文字仍有姿势/部位语义偏差，没有引入文字去重、ORB或模型调整。

### 2026-09-28：CLIP正式全素材索引完成（未接Web）

`clip_index/formal_v1` 已从只读DINO `formal_v1_repaired` 已有JPEG每5秒分桶构建完成：319个asset、362,752帧；embedding、metadata、FAISS ntotal及逐行映射全部一致，失败0。固定CLIP模型/revision、512维FP32/L2，未解码原视频、未改DINO/Web/ORB。CLIP构建器默认源改为repaired，补齐降低batch续跑、单asset源读取失败隔离、GPU计时和Windows进度文件占用重试。一次真实中断后复用217,476帧断点完成，未从零重跑。

完整性及5条中文Top20功能验收READY；CPU暖查询median47.4ms/P95 52.8ms（15次）。画面抽查有治疗场景相关性，但姿势、部位和角色仍有偏差，不代表准确率验证通过。建库31分34.5秒，FAISS约708.5MiB；详见 `clip_index/validation/formal_v1/report.md`、`validation_report.json` 和 `query_smoke.json`。本轮只完成独立索引，未接入寻帧。

### 2026-09-28：寻帧正式库候选去重

`benchmark/experiments/dino_july_web/search_adapter.py` 已接入冻结的后处理：formal_v1_repaired查询Top500，按原DINO分数顺序，每asset最多5帧，代表帧至少相隔10秒，再返回最多10条。`search_config.json` 默认 `candidate_dedup: true`；false恢复原始Top10路径。ORB不接入，UI结果字段不变，仅为最终候选读取JPEG；两个正式库及模型保持只读。

新增根目录 `关闭寻帧候选去重.bat` / `开启寻帧候选去重.bat`，设置开关并通过现有CUDA解释器启动器重启8502；切库脚本保留该配置。查询计时按本次调用返回，不使用跨线程共享SQLite或计时状态。30张原query开启/关闭结果逐项匹配冻结实验；holdout20去重后55%/80%/85%，hell10为20%/50%/60%。详细上线和Web验证见 `benchmark/experiments/candidate_dedup_rollout/report.md`。

> 最后更新：2026-09-27
> 项目位置：D:\video_search_tool\
> 交接对象：Codex（AI编程Agent）

### 2026-09-27：正式CLIP文字索引准备（未启动正式建库）

新增独立 `clip_index/`：采用已落盘的 `openai/clip-vit-base-patch32` 固定revision `3d74acf...`，512维归一化特征和独立FAISS。模型本身不是中文模型，沿用七月的受控领域中文转英文方案，补齐“患者趴着接受治疗 / 按摩腰部 / 肩颈治疗 / 患者坐着，老师站在旁边”；未知中文与否定句明确拒绝。

未来构建只在DINO `report.json` 完成且无异常后，从DINO shard按frame_number读取已有JPEG，不重新解码原视频。默认每5秒选一帧；319个主素材共506.842小时，按资产时长估计365,102张，精确值待DINO metadata完成后由plan确定。输出设计为 `clip_index/formal_v1/`，含manifest、build plan、逐asset embedding/checkpoint shard、progress、sessions、独立FAISS、metadata、failures、assembly和最终report。batch事务断点可续跑，单图损坏记录后继续。

统一查询API为 `clip_index.query.search_text(text, top_k=20)`，返回frame_id、asset_id、video_id、timestamp、similarity、file_path，并提供当前TextEngineAdapter所需的三元组接口。6项合成轻量测试通过，覆盖中文翻译、JPEG→embedding→CPU FAISS→metadata→query、异常图、断点恢复及安全门槛。本轮未访问真实formal_v1、未启动Torch/GPU或正式CLIP建库，未修改Web配置及任何既有索引/数据库。完整说明见 `clip_index/README.md`。

### 2026-09-27：formal_v1 只读验收工具

新增 `dino_index/validate_formal.py` 与根目录 `验收正式DINO索引.bat`。`formal_v1/report.json` 不存在时立即输出“正式索引尚未完成”，不加载FAISS、metadata或shard，不读取资产库/原视频且不创建验收输出。完成标记存在后，只读核对构建报告、319个逻辑资产、metadata字段/数量/重复、asset_id覆盖、路径存在、时间戳范围、shard与384维特征数量；所有前置项通过后才用已存feature进行CPU FAISS自查询，不加载DINO模型或GPU。

报告写到正式目录外的 `dino_index/validation/formal_v1/validation_report.json` 和 `.md`，最终状态仅READY/NOT_READY；工具不自动切换Web配置。5项合成轻量测试通过，覆盖安全拒绝、完整READY、异常时间戳阻止FAISS加载、报告失败/资产缺失及formal输出保护。当前真实report不存在时仅验证了安全拒绝，没有等待或读取半成品。

### 2026-09-27：寻帧搜索反馈

独立 july_test 网页已增加每次图文搜索快照、结果确认、可选正确时间点/备注、没有正确结果及 CSV 导出。查询原图保存在独立 `benchmark/feedback/search_feedback.db`，不写生产库；每次导出位于 `benchmark/feedback/exports/`。搜索重渲染不重复记录，同次改选更新反馈，未标时间不使用预测时间充当真值。七月 asset_id 缺失如实保留NULL。

`python -m benchmark.feedback.store --cases` 可将已确认素材及时间的图片反馈转成原 benchmark JSON；文字、未命中、缺少时间等记录留待补标/后续runner，详见 `benchmark/feedback/README.md`。本轮64项轻量测试通过，未加载模型、未进行GPU推理、未读原视频或真实formal_v1，未修改任何索引或正在运行的DINO建库。

### 2026-09-27：正式DINO Web接入准备

`benchmark/experiments/dino_july_web/` 新增独立搜索adapter和 `search_config.json`。当前配置保持 `search_index: july_test`；未来正式索引完成后改为 `formal_v1` 并重启网页即可切换图片索引，页面代码无需再次修改。adapter 以 `report.json` 为正式完成硬门槛，在此之前不打开正式FAISS、metadata、特征或shard。

统一图片结果字段为asset_id、video_id、文件名、文件路径、timestamp、similarity和thumbnail。正式metadata已具备全部标识和定位字段；缩略图通过shard+frame_number只读获取。7月实验结果的asset_id为null。正式DINO没有文字特征，切到formal_v1时仅开放图片搜索。轻量测试只使用合成metadata、图片和mock，未加载formal_v1、未运行GPU或读取原视频。

### 2026-09-27：独立正式DINO建库

新增 `dino_index/build.py`、`query.py` 和短视频测试，说明见 `dino_index/README.md`。输入为资产管理输出 `asset_inventory/results/20260927_assets/primary_files.csv` 的319个主文件，使用已验证的本地DINOv2-small和独立CUDA环境。沿用生产每 `int(FPS*1)` 帧抽一帧的规则；保留asset_id、原video_id、路径、时间戳与稳定frame_id。

输出只写 `dino_index/formal_v1/`；不改变旧MobileNet生产索引或检索服务，不保存全尺寸图片。支持逐批次事务断点和逐视频恢复。3个合成短视频的真实GPU测试已通过。全量数据状态以 `progress.json` 为准；只有 `report.json` 存在才表示319个视频处理、FAISS组装、查询速度测试和源文件状态核对全部完成。解码异常会记录在报告中。

---

### 2026-09-27：寻帧切换到 formal_v1_repaired

`benchmark/experiments/dino_july_web/search_config.json` 已切换为 `formal_v1_repaired`。adapter 新增第三个合法版本并直接指向独立修复目录，不复制或重命名 `formal_v1`；加载前要求构建报告完成、严格验收为 READY、验收报告绑定当前目录且 metadata/FAISS 非空。页面明确显示“正式素材库、319个素材、约507小时、DINO formal_v1_repaired”。

3张已有JPEG轻量Smoke Test实际使用CUDA完成query embedding并查询1,843,351帧FAISS，均返回Top10且预期视频在Top10；asset_id、video_id、timestamp、路径与缩略图全部有效。预览入口会按命中点前1秒生成8秒本地MP4，已实际生成并解码。根目录新增 `启动寻帧.bat`、`切换寻帧到7月测试库.bat` 和 `切换寻帧到正式素材库.bat`；服务仍只监听 `127.0.0.1:8502`。未修改两个正式索引目录，未启动CLIP建库。

---

## 一、项目一句话说明

本地运行的"以图搜视频"工具。上传一张直播切片截图，在本地素材库中找到对应的原始视频和精确时间点。同时支持文字搜索口播内容、截图OCR。专为直播切片工作流设计。

---

## 二、当前项目状态（基于真实代码验证）

### 2026-09-27 素材逻辑资产管理完成

- 基于 `asset_inventory/results/20260927_assets/assets.db` 的完整SHA-256结果，在同目录新增独立 `logical_assets.db`；没有修改源扫描库、生产数据库、FAISS、DINO或检索代码。
- 388条文件记录归为320个SHA逻辑组：319个唯一可用视频素材，另有1个包含28条零字节文件的不可用组。生成稳定的 `AST-<SHA前20位>` asset_id；短ID冲突会停止而非覆盖。
- 42个重复组涉及110条文件和68个多余副本：41个非空组各2个文件，空文件组28个文件。所有文件信息完整保留，没有移动或删除文件。
- 已生成319个主文件候选。规则依次为：可用非空、生产库已登记、副本标记更少、路径层级更浅、路径更短、video_id更小；空文件组不指定主文件。
- 独立库逐字段保留源videos表全部字段，并提供asset映射、主文件和重复组视图；JSON/CSV清单及42组明细见 [逻辑资产报告](asset_inventory/results/20260927_assets/逻辑资产报告.md)。
- 10项资产隔离测试和26项原项目测试通过；数据库完整性、388条逐字段一致、主文件规则重算、319条路径存在、源扫描库未变化和生产保护快照检查通过。本阶段完成后停止。

### 2026-09-27 素材资产扫描完成

- 新增独立 `asset_inventory/` 扫描工具；本次只扫描用户确认的E盘直播录制目录与D盘素材目录，不抽帧、不生成DINO特征、不改FAISS或生产检索。
- 独立数据库：`asset_inventory/results/20260927_assets/assets.db`。共388个文件、472,825,668,239字节，360个非空视频的媒体头总时长596小时50分26.104秒（包含重复副本）；28个零字节空文件另行登记，未知媒体字段为NULL。
- 388个文件均完成完整SHA-256。重复42组涉及110个文件，共68个多余副本，其中非空视频41个、空文件27个；没有删除重复文件。损坏/不可用28个均为空文件，未做全片解码，不保证排除中途损坏。
- 6项新测试和26项原测试通过；数据库完整性、3个小文件独立哈希复核、生产与DINO源文件状态保护检查通过。扫描进程已停止。
- 结果详见 [扫描报告](asset_inventory/results/20260927_assets/扫描报告.md)，字段、统计口径和显式运行方式见 [资产扫描说明](asset_inventory/README.md)。本轮不接入检索或网页。

### 2026-09-27 独立7月内部测试网页

- 新增 `benchmark/experiments/dino_july_web/`，双击根目录 `启动7月测试工具.bat`，访问 `http://127.0.0.1:8502`。使用已有独立CUDA环境，运行时离线，不改变生产网页或配置。
- 图搜只读已有DINO实验索引，按原7月目录白名单限制到18个视频、180,408帧，返回Top10及已有缩略图、视频ID、时间戳、相似度和路径；排除合并实验中额外的benchmark视频。
- 文字实验复用已有CLIP权重，在独立目录缓存6,023张已有JPEG的特征（每30秒选一张）；没有重新抽帧或重建DINO。中文仅支持明确领域词表并显示英文转换，英文可直接检索；这不是通用中文语义模型，也未验证业务语义准确率。
- 11项新测试、26项原测试、11项benchmark测试通过；3张真实图搜自匹配及3条示例文字查询、Streamlit页面验证通过。生产代码/配置、库、索引及DINO源文件大小和修改时间未变。
- 启动、限制及验收记录见 [7月测试工具说明](benchmark/experiments/dino_july_web/README.md)。本轮不扩展功能。

### 2026-09-26 查询端 CPU / CUDA 可配置切换

- 新增 `query_device` 配置，默认 `cpu`；旧配置缺省同样使用CPU。`cuda` 使用 `cuda:0` 进行原查询embedding推理，启动页面打印实际device、解释器和PyTorch版本；CUDA不可用时明确报错。
- 当前仍为原生产CPU环境，未切换现网。独立CUDA环境已补齐页面依赖并验证启动；切换时需同时配置该环境的 `paths.python_executable`，见 [QUERY_DEVICE.md](QUERY_DEVICE.md)。
- 查询模型构造、预处理、1280维FP32、L2归一化和FAISS检索逻辑不变；默认CPU结果与原函数逐元素相同，同图CPU/GPU最大绝对差9.24e-7。原有21项测试通过，新增5项设备专项测试在CUDA环境全通过。
- 原生产库、索引、模型与环境包未变。修改前备份后缀为 `.query-device-20260926.bak`，恢复CPU配置和原解释器即可回滚；本轮没有进行其他优化。

### 2026-09-26 P1-1 独立 CUDA 测试完成

- `.venv-cuda-test` 使用 Python 3.14.7 + PyTorch 2.11.0+cu128 / torchvision 0.26.0+cu128，RTX 3060 已实际执行张量运算和原 MobileNetV2 推理。
- 100 张合成图片、单张 FP32、三轮中位数：测试环境 CPU 2.660 秒，GPU 1.126 秒，约 2.36 倍；原生产 CPU 基线 2.243 秒。数值一致性检查通过。
- 生产仍使用原 PyTorch 2.14.0+cpu，代码、配置、模型、索引与数据库均未改写；21 项测试通过。没有把网页或录入任务迁移到 GPU。
- 下文“Python 3.14 无法安装 CUDA 版”等历史判断已过时；此次独立环境验证不代表整个项目依赖均兼容该 CUDA 环境。详情及复测命令见 [CUDA_TEST.md](CUDA_TEST.md)。

### 2026-09-26 P0 路径清理

- 新增 config.py 统一读取原有 config.json。项目内文件默认相对于项目目录，机器相关素材目录和解释器位置集中在 JSON 中，旧 video_folder 配置兼容。
- 主程序、批处理、历史工具、启动脚本中的 C/D/E 盘硬编码路径已清理；SQL 中的素材目录筛选也从配置读取。主库与历史库仍是独立配置项，历史维护工具没有改指向生产主库。
- 模型、FFmpeg、匹配缩略图、展示缓存、索引文件、日志、完成标记、测试素材及运行时库路径已纳入配置。没有修改模型、预处理、检索逻辑或数据格式。
- 21 项单元测试和 3 个合成短视频的隔离流程测试通过；测试覆盖真实视频处理、图搜/文字搜索、缩略图、模型路径和服务启动。生产数据未改写。
- 完整路径规则、修改文件清单、隐藏依赖和验证记录见 [PATHS.md](PATHS.md)。后文第一项修复记录为此前阶段的历史记录。

### 2026-09-26 接管后的第一项修复

- `video_search.py`、`add_new_videos.py`、`build_faiss.py` 通过新增的 `database.py` 统一使用项目目录内的 `video_index_fixed.db`。
- 查询连接默认只读；录入和现有维护按钮显式使用读写连接。两种连接都只打开已有文件，数据库缺失时报错，不创建空库、不回退旧库。
- 生产数据库、现有 FAISS、模型及素材均未改写；没有运行录入或全量重建。
- 其他历史脚本和 `update_paths.py` 尚未统一，`init_database.py` 仍是独立的新库初始化工具，不能用于重置生产库。
- 新增 `tests/test_database.py`，使用临时小数据库验证连接、文字检索和图搜候选与视频 ID 的衔接，共 10 项测试通过；测试命令为 `python -B -m unittest discover -s tests -v`，需要使用已安装依赖的解释器。
- 语法检查通过；Streamlit AppTest 页面测试显示 360 个视频、1,591,127 帧、1,062,422 条字幕，无页面异常；独立本机端口 18501 启动检查返回 HTTP 200，检查后已停止该测试服务。没有进行生产图搜准确率或性能验收。
- 只读审查发现存量特征混有 62,720 维与 1,280 维，部分历史帧间隔为 10 秒。下文的“1280维、1秒/帧”仅适用于当前增量提取实现，不能当作全库存量保证。详见 KNOWN_ISSUES.md 的 ISSUE-018；处理方案验证前不要执行全量索引重建。

### 核心功能

| 功能 | 状态 | 说明 |
|------|------|------|
| 视频递归扫描 | ✅ 已完成 | os.walk扫描config.json指定目录，支持子文件夹 |
| 视频抽帧 | ✅ 已完成 | OpenCV逐帧读取，1秒1帧（add_new_videos.py中FRAME_INTERVAL=1） |
| 画面特征提取 | ✅ 已完成 | MobileNetV2 + AdaptiveAvgPool2d(1)，输出1280维，L2归一化 |
| 特征存储 | ✅ 已完成 | SQLite BLOB存储float32字节 |
| FAISS向量索引 | ✅ 已完成 | IndexFlatIP内积搜索，159万向量 |
| 以图搜视频 | ✅ 已完成 | FAISS粗筛20候选 → ORB精排 → 综合得分排序 |
| 时间戳返回 | ✅ 已完成 | 返回视频路径 + 精确秒数 |
| 文字搜索口播 | ✅ 已完成 | faster-whisper转写字幕，SQL LIKE搜索 |
| 截图OCR | ✅ 已完成 | RapidOCR识别文字后搜索字幕 |
| Web界面 | ✅ 已完成 | Streamlit，6个标签页，http://localhost:8501 |
| 缩略图显示 | ⚠️ 部分实现 | 搜索结果现场抽帧缓存，批量缩略图生成中（10448/1591127） |
| 人脸搜索 | ⚠️ 实验性 | Tab6"找这个人"，YuNet检测+SFace识别，全库遍历极慢，未实际验证可用性 |
| 开机自启 | ⚠️ 已配置 | 计划任务+启动文件夹双保险，刚修复Python路径问题，待下次开机验证 |
| 多素材目录 | ❌ 未实现统一扫描 | video_folder 为主目录；material_folder 配置原专用脚本目录，尚未合并为统一多目录流程 |
| 增量自动检测 | ❌ 未实现 | 加新视频需手动运行add_new_videos.py，不会自动监控 |
| 用户账户/权限 | ❌ 未实现 | 单机工具，无登录系统 |
| GPU加速 | ❌ 未实现 | PyTorch是CPU版(2.14.0+cpu)，Python 3.14太新装不了CUDA版 |

### 数据规模（2026-09-26）

- 视频：360个（E盘285个 + D盘75个）
- 帧特征：1,591,127条
- 字幕片段：1,062,422条
- FAISS索引：7.59GB
- 数据库：32.3GB（video_index_fixed.db）

---

## 三、完整技术栈（实际使用版本）

### 运行时
- **Python**: 3.14.7 (MSC v.1944 64bit)
- **PyTorch**: 2.14.0+cpu（CPU版，CUDA不可用）
- **CUDA**: 未安装/未使用
- **NVIDIA驱动**: 616.92（硬件RTX 3060 12GB存在但未被PyTorch使用）

### 核心库
| 库 | 版本 | 用途 |
|----|------|------|
| torch | 2.14.0+cpu | MobileNetV2特征提取 |
| torchvision | 0.29.0 | 模型和预处理 |
| opencv-python | 5.0.0 | 视频读取、ORB、人脸、抽帧 |
| faiss-cpu | 1.15.1 | 向量检索 |
| streamlit | 1.64.0 | Web界面 |
| faster-whisper | 1.2.1 | 语音转字幕（CTranslate2后端） |
| ctranslate2 | 4.8.2 | faster-whisper的推理引擎 |
| rapidocr-onnxruntime | 1.2.3 | 截图OCR |
| opencc-python-reimplemented | 0.1.7 | 繁体转简体 |
| numpy | 2.5.3 | 数值计算 |
| pillow | 12.3.0 | 图像处理 |
| onnxruntime | 1.30.0 | OCR模型推理 |

### 模型文件（models/目录）
| 文件 | 大小 | 用途 | 加载方式 |
|------|------|------|----------|
| model.bin | 138MB | faster-whisper base模型 | WhisperModel("models", device="cpu", compute_type="int8") |
| base.pt | 138MB | openai-whisper base模型（备用，实际用faster-whisper） | whisper.load_model("base") |
| config.json | 2KB | faster-whisper配置 | 自动加载 |
| tokenizer.json | 2.1MB | faster-whisper分词器 | 自动加载 |
| vocabulary.txt | 449KB | faster-whisper词表 | 自动加载 |
| face_detection_yunet.onnx | 227KB | 人脸检测（YuNet） | cv2.FaceDetectorYN_create |
| face_recognition_sface.onnx | 37MB | 人脸识别（SFace） | cv2.FaceRecognizerSF_create |

### 其他
- **FFmpeg**: bin/ffmpeg.exe（84MB，独立二进制，不依赖系统安装）
- **数据库**: SQLite 3（Python内置）
- **Web框架**: Streamlit（无独立后端，单文件应用）

---

## 四、硬件和运行环境

### 当前开发机
- CPU: 14代i5
- GPU: NVIDIA RTX 3060 12GB（**未被使用**，PyTorch是CPU版）
- 内存: 32GB
- 系统: Windows

### 资源占用
- **抽帧阶段**: CPU满载，内存约500MB，每小时视频约需3分钟
- **字幕转写**: CPU满载，内存约1-2GB，faster-whisper int8模式，速度约20倍实时
- **FAISS搜索**: CPU，内存加载7.59GB索引，搜索约200-500ms
- **Web服务**: 内存约400MB（不含FAISS索引）
- **FAISS索引加载**: 首次加载需读取7.59GB到内存，约10-30秒

### 精度设置
- MobileNetV2: FP32（CPU推理）
- faster-whisper: INT8（compute_type="int8"）
- FAISS: FP32向量

### 已知瓶颈
1. **GPU完全闲置**: PyTorch CPU版，Python 3.14太新导致CUDA版装不上
2. **ORB匹配慢**: 搜索时对20个候选逐个开视频seek抽帧，缩略图生成完后会改善
3. **FAISS IndexFlatIP是暴力搜索**: 159万向量1280维，CPU搜索约200-500ms，未来可换IVF索引
4. **内存峰值**: FAISS索引7.59GB + 系统 + 浏览器，32GB刚好够用

---

## 五、项目目录说明

```
D:\video_search_tool\
├── video_search.py              # 【程序入口】Streamlit主程序，6个标签页，搜索逻辑
├── config.json                  # 【配置文件】素材目录、模型、缓存、解释器等路径
├── config.py                    # 【路径入口】解析旧配置及新的 paths 配置项
├── requirements.txt             # Python依赖清单（22个包）
├── 启动工具.bat                  # 一键启动Web服务，调用launch.ps1
├── 开机启动服务.bat              # 开机自启入口，调用launch.ps1读取解释器配置
│
├── database.py                  # 【数据库入口】日常三个入口共用，只打开已有主库
├── video_index.db               # 【数据库】保留旧库，日常三个入口已不使用
├── video_index_fixed.db         # 【数据库】当前主用库（32.3GB，复制修复版）
├── faiss_index.bin              # 【FAISS索引】7.59GB，159万1280维向量
├── faiss_meta.pkl               # 【索引元数据】270MB，pickle格式，(file_path, file_name, timestamp)列表
│
├── models/                      # 【模型目录】317MB
│   ├── model.bin                # faster-whisper base模型
│   ├── config.json              # faster-whisper配置
│   ├── tokenizer.json           # 分词器
│   ├── vocabulary.txt           # 词表
│   ├── base.pt                  # openai-whisper模型（备用）
│   ├── face_detection_yunet.onnx # 人脸检测
│   └── face_recognition_sface.onnx # 人脸识别
│
├── bin/                         # 【工具目录】84MB
│   └── ffmpeg.exe               # FFmpeg独立二进制
│
├── thumbnails/                  # 【缩略图目录】生成中，10448张/275MB
│   └── {video_id}_{timestamp}.jpg # 命名规则
│
├── add_new_videos.py            # 【建库脚本】增量添加视频（抽帧+特征+字幕）
├── build_faiss.py               # 【建索引脚本】从数据库重建FAISS索引
├── init_database.py             # 初始化空数据库（新电脑用）
├── update_paths.py              # 路径批量替换工具
├── generate_thumbnails.py       # 批量生成缩略图（后台运行中）
├── full_process_and_shutdown.py # 完整处理+自动关机脚本
├── batch_add_d_material.py      # D盘素材批量处理（历史脚本）
├── batch_transcribe_missing.py  # 批量补字幕（历史脚本）
├── check_progress.py            # 进度检查
│
├── process_log.txt              # 处理日志
├── 处理完成.txt                  # 处理完成标记
├── 全新电脑部署指南.md            # 部署文档
└── 迁移部署指南.md               # 迁移文档
```

### 注意：废弃/临时文件
- bug.png, bug2.png, bug3.png：历史截图，可删
- check_status.py, check_v2.py, find_0722.py, find_vid.py, list_videos.py：0字节空文件，可删
- resample_frames.py, fix_0719.py, fix_thumbs.py：历史修复脚本，已完成使命
- scan_d_material.py, test_transcribe.py, gen_thumbnails.py：重复/历史脚本
- auto_shutdown.ps1：历史关机脚本

---

## 六、完整数据流

### 流程A：新视频加入素材库

```
1. 用户把视频放到素材目录（E:\... 或 D:\素材\）
2. 运行 python add_new_videos.py
3. os.walk递归扫描目录，对比数据库已有路径，发现新视频
4. 对每个新视频：
   a. cv2.VideoCapture打开，获取fps和时长
   b. INSERT INTO videos (file_path, file_name, duration)
   c. 逐帧读取，每1秒取1帧（frame_step = fps * 1）
   d. 对每帧：BGR→RGB → Resize(224,224) → ToTensor → Normalize → MobileNetV2 → 1280维 → L2归一化 → float32.tobytes()
   e. 每20帧批量INSERT INTO frames (video_id, timestamp, features)
   f. faster-whisper转写音频，INSERT INTO subtitles (video_id, start, end, text)
5. 运行 python build_faiss.py
   a. 从数据库分批加载所有帧特征（10000条/批）
   b. 构建numpy矩阵 (N, 1280) float32
   c. faiss.IndexFlatIP(1280) → index.add(matrix)
   d. 保存faiss_index.bin + faiss_meta.pkl
6. 重启Streamlit服务加载新索引
```

### 流程B：上传截图搜索视频

```
1. 用户在Web上传截图
2. cv2.imdecode解码为BGR
3. extract_image_features(img_bgr):
   a. MobileNetV2提取1280维特征（L2归一化）
   b. calc_phash: 灰度→resize(32,32)→DCT→取8x8低频→中位值二值化→64位
   c. calc_color_hist: HSV空间，12x8直方图，归一化→96维
   d. 保存原始BGR图到全局变量query_color_frame供ORB使用
4. search_similar_frames(query_feat, query_phash, query_color, top_k=10):
   a. FAISS粗筛: index.search(query_vec, 20) → 20个候选
   b. 批量查询每个候选的video_id
   c. 对每个候选：
      - load_frame_for_matching: 优先读缩略图{vid}_{ts}.jpg，没有则开视频seek抽帧
      - ORB匹配: 同时匹配原图和水平镜像，取较好的匹配点数
      - pHash汉明距离 → 相似度
      - HSV颜色直方图相关系数 → 相似度
      - 综合得分 = min(ORB/30,1)*0.55 + pHash*0.2 + 颜色*0.15 + MobileNet*0.1
   d. 按综合得分排序，取top_k，过滤得分>0.2
5. 返回结果：视频路径、文件名、时间戳、综合得分、各维度明细
6. Web显示：缩略图（现场抽帧缓存）、时间、ffmpeg裁剪命令
```

### 流程C：文字搜索口播

```
1. 用户输入关键词
2. SQL: SELECT v.file_path, v.file_name, s.start, s.end, s.text
       FROM subtitles s JOIN videos v ON s.video_id = v.id
       WHERE s.text LIKE '%关键词%'
       ORDER BY v.file_path, s.start
3. 返回匹配的字幕片段，显示时间和台词
```

---

## 七、索引和数据库结构

### SQLite表结构

**videos表**
| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK AUTOINCREMENT | 视频ID |
| file_path | TEXT UNIQUE | 完整绝对路径 |
| file_name | TEXT | 文件名 |
| duration | REAL | 时长（秒） |
| processed_at | TEXT DEFAULT CURRENT_TIMESTAMP | 处理时间 |

**frames表**
| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK AUTOINCREMENT | 帧ID |
| video_id | INTEGER | 关联videos.id |
| timestamp | REAL | 时间点（秒） |
| features | BLOB | 1280维float32的字节（5120字节） |

**subtitles表**
| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK AUTOINCREMENT | 字幕ID |
| video_id | INTEGER | 关联videos.id |
| start | REAL | 开始时间（秒） |
| end | REAL | 结束时间（秒） |
| text | TEXT | 字幕文本 |

**索引**
- idx_frames_video: frames(video_id)
- idx_sub_text: subtitles(text)
- idx_sub_video: subtitles(video_id)
- sqlite_autoindex_videos_1: videos(file_path) UNIQUE

### FAISS索引结构
- **类型**: faiss.IndexFlatIP（内积暴力搜索）
- **维度**: 1280
- **向量数**: 1,591,127
- **距离**: 内积（特征已L2归一化，内积=余弦相似度）
- **元数据**: faiss_meta.pkl，Python list of tuple (file_path, file_name, timestamp)
- **对应关系**: faiss_meta[i] 对应 index中第i个向量

### 数据示例
```python
# videos
(1, 'E:\\备份\\...\\2026-07-19_145449.ts', '2026-07-19_145449.ts', 0.0, '2026-09-20 04:37:41')

# frames (features是5120字节BLOB)
(1, 9, 0.0, b'\x00\x01\x02...')

# subtitles
(1, 1, 0.0, 8.72, '一分钱,但是你这个也没烧走了路啊。')
```

### 删除/移动视频的影响
- **移动视频**: 数据库和FAISS里的路径会失效，搜索结果打不开视频。需运行update_paths.py批量替换，或用Web界面的"一键修复路径"
- **删除视频**: 数据库和FAISS里会残留无效记录，搜索可能返回已删除的视频。目前没有自动清理机制，需手动删除对应记录并重建FAISS
- **重建索引**: 运行build_faiss.py，从数据库重新加载所有帧构建索引

---

## 八、图像预处理

### 抽帧参数
- **抽帧频率**: 1秒/帧（FRAME_INTERVAL=1，在add_new_videos.py中）
- **注意**: video_search.py顶部写的FRAME_INTERVAL=10，但那是旧值，实际建库用的是add_new_videos.py中的1

### MobileNetV2预处理（建库和查询完全相同）
1. BGR → RGB（cv2.cvtColor）
2. Resize到(224, 224)（torchvision.transforms.Resize）
3. ToTensor（归一化到0-1）
4. Normalize: mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]
5. 输入MobileNetV2（去掉最后分类层，加AdaptiveAvgPool2d(1)）
6. 输出1280维向量 → L2归一化 → float32

### ORB预处理
- 直接用原始BGR图，不做resize
- nfeatures=500, scaleFactor=1.2, nlevels=8
- 同时匹配原图和水平镜像（cv2.flip(frame, 1)）

### pHash预处理
- BGR → 灰度 → resize(32,32) → DCT → 取左上8x8 → 中位值二值化

### 颜色直方图预处理
- BGR → HSV → calcHist([0,1], [12,8], [0,180,0,256]) → 归一化 → 96维

### 不做的处理
- ❌ 不做人物检测后再embedding（直接对整帧提取特征）
- ❌ 不处理字幕遮挡
- ❌ 不做数据增强（建库时不镜像、不调色）
- ❌ 查询图和库图预处理流程相同（都是MobileNetV2标准预处理）

---

## 九、目前检索算法

### 最终相似度公式
```
total = min(orb_score / 30.0, 1.0) * 0.55   # ORB局部特征（权重最高）
      + sim_phash * 0.20                     # 感知哈希
      + sim_color * 0.15                     # HSV颜色直方图
      + sim_mobilenet * 0.10                 # 全局语义特征
```

### 各分数计算
- **orb_score**: ORB好匹配点数量（距离<50），同时匹配原图和镜像取最大值，上限30归一化
- **sim_phash**: 1 - hamming_dist/64，汉明距离越小越相似
- **sim_color**: cv2.compareHist HISTCMP_CORREL相关系数，范围-1到1
- **sim_mobilenet**: FAISS内积（L2归一化后=余弦相似度），范围0到1

### 搜索流程
1. **粗筛**: FAISS IndexFlatIP搜索Top 20
2. **精排**: 对20个候选逐个做ORB+pHash+颜色，计算综合得分
3. **过滤**: 只保留综合得分>0.2的结果
4. **排序**: 按综合得分降序，取Top 10返回

### 没有的机制
- ❌ 没有时间连续性判断（相邻帧不合并）
- ❌ 没有人物ReID（人脸搜索是独立的全库遍历，未融入主搜索）
- ❌ 没有姿态/动作识别
- ❌ 没有多帧融合（单帧独立搜索）

---

## 十、当前准确率和测试结果

**尚未建立标准benchmark。**

历史用户反馈（非量化）：
- 自己从素材里直接截的图：基本能搜到
- 别人剪辑过的切片（加特效、调色）：部分能搜到，ORB匹配有帮助
- 镜像翻转的视频：已支持（搜索时同时匹配镜像）
- 换背景/抠图的视频：效果较差，全局特征受背景影响大
- 人物在不同场景：MobileNetV2全局特征偏场景，人物匹配不是强项
- 绿色衣服等明显颜色：颜色直方图有一定辅助作用

---

## 十一、运行方式（已配置好的Windows电脑）

### 启动Web服务
```cmd
cd /d D:\video_search_tool
启动工具.bat
```
或手动：
```cmd
cd /d D:\video_search_tool
python -m streamlit run video_search.py --server.headless true --server.port 8501
```
浏览器打开：http://localhost:8501

### 添加新视频
以下为日常入口关系说明。当前存在 ISSUE-018 历史特征混用问题，尚不能直接执行生产库的全量索引重建。

```cmd
cd /d D:\video_search_tool
python add_new_videos.py
python build_faiss.py
```
然后重启Web服务。

### 重建FAISS索引
当前先保留现有索引；需先解决 ISSUE-018 并完成小样本验证，再安排生产重建。

```cmd
cd /d D:\video_search_tool
python build_faiss.py
```

### 检查进度
```cmd
python check_progress.py
```

---

## 十二、从零部署（新Windows电脑）

详见 `ENVIRONMENT.md`，简要步骤：
1. 安装Python 3.12（**不要用3.14**，CUDA版PyTorch不支持）
2. 复制video_search_tool文件夹（不含大数据库，新素材从头建库）
3. pip install -r requirements.txt
4. 修改config.json中的素材路径
5. python init_database.py（建新空库）
6. python add_new_videos.py（抽帧+字幕）
7. python build_faiss.py（建索引）
8. 启动服务

---

## 十三、绝对不要随便改的东西

| 内容 | 原因 |
|------|------|
| MobileNetV2 1280维输出 | 改了会导致旧FAISS索引和数据库特征全部失效，需重建全部 |
| 预处理Normalize参数 | 改了特征分布就变了，旧索引全部失效 |
| L2归一化 | FAISS用内积，依赖归一化 |
| FAISS维度1280 | 索引文件硬编码维度 |
| 数据库表结构 | subtitles用start/end（不是start_time/end_time），改了会破坏现有查询 |
| faiss_meta.pkl格式 | (file_path, file_name, timestamp)三元组，搜索代码依赖此结构 |
| 抽帧间隔1秒 | 改了会影响时间戳精度和索引密度 |
| 综合得分权重 | 已调优，改动需重新验证准确率 |
| models/目录模型文件 | 不要替换为其他版本，接口可能不兼容 |

---

## 十四、下一阶段产品目标（仅记录，不要求开发）

最终目标：工作室内部AI视频生产平台

- **A. 用户账户**: 多账号、权限、任务管理
- **B. 素材管理**: 统一素材库、上传自动建库、多模态搜索
- **C. 自动复刻**: 参考视频→切镜→理解镜头→匹配原素材→生成时间线→剪映草稿
- **D. 批量生产**: 每天50条，单条25分钟，需批处理/缓存/多Worker/云GPU
- **E. 算力调度**: 局域网Worker + 云端3090/4090 + 统一调度
- **F. 爆款发现**: 行业视频监控、爆款候选、自动进入复刻任务

---

## 十五、建议的代码模块边界（渐进式拆分）

现有代码集中在video_search.py（650行）和几个脚本中。建议拆分：

| 目标模块 | 可复用的现有代码 | 说明 |
|----------|------------------|------|
| **indexing** | add_new_videos.py, build_faiss.py, init_database.py | 建库、抽帧、特征提取、索引构建 |
| **search** | video_search.py中search_similar_frames, search_by_keyword | 检索逻辑 |
| **vision** | video_search.py中extract_image_features, calc_phash, calc_color_hist, match_orb_features, extract_face_feature | 视觉特征提取 |
| **assets** | config.json, 路径管理, update_paths.py | 素材管理 |
| **reference_parser** | 无（新开发） | 参考视频切镜解析 |
| **replicate** | 无（新开发） | 自动复刻逻辑 |
| **timeline** | 无（新开发） | 时间线生成 |
| **jianying_exporter** | 无（新开发） | 剪映草稿导出 |
| **worker** | full_process_and_shutdown.py的流程思路 | 任务Worker |
| **api** | 无（新开发） | 后端API |
| **web** | video_search.py中Streamlit页面部分 | 前端 |

**拆分原则**: 先把vision和search从video_search.py抽成独立模块，Web层调用它们。indexing保持脚本形式即可。不要大规模推翻重写。

## 2026-09-28：寻帧话术搜索 Beta

8502 工作台新增“话术找原片 Beta”，调用 `speech_search/formal_query.py` 的 `FormalSearch.search(..., mode='semantic', top_k=10)`，索引为 `speech_search/index/formal_v1`（318 asset、3,099,048 向量）。沿用已验收查询中的既有窗口折叠和原始 Semantic 分数顺序，没有新增时间去重、fuzzy 融合或 reranker。

入口适配在 `benchmark/experiments/dino_july_web/speech_adapter.py`：加载前校验 READY、文件状态、实际 metadata 行数、embedding 文件大小及 FAISS ntotal。仅话术失败时禁用该入口。`search_config.json` 的 `speech_search_enabled` 为独立开关；设 false 并刷新页面即可关闭话术，图片和 CLIP 保持可用；true 为正式默认。

Top10 全部展示匹配原话、前后句、asset/video ID、原字幕起止时间、分数、路径。时间异常只提示，不改原字幕。话术短预览保留音轨，从命中前 1 秒开始，按窗口长度生成 8～60 秒片段；图片/CLIP 预览保持原行为。

反馈仍写原 `benchmark/feedback/search_feedback.db`。`benchmark/feedback/migrate_speech.py` 在兼容迁移前生成 `.before-speech.bak`，增加 speech 查询类型；原记录内容不变。不可变 Top10 快照保存 matched_text、semantic_rank/score、start/end、源 segment/window ID；反馈 selected_rank 引用该快照，另保存正确 asset、corrected_timestamp 和 note。测试进程可通过 `XUNFRAME_TEST_FEEDBACK_DB` 使用临时库，正常启动不设置该变量。

本次验收资料：`benchmark/experiments/speech_web_rollout/`。没有修改正式 DINO、CLIP、Speech 索引、原字幕库或生产图片/CLIP 查询适配层。启动仍使用 `启动寻帧.bat`，地址 `http://127.0.0.1:8502`。

## 2026-09-28：auto_remake V0.3 独立多模态验证

独立入口 `python -B -m auto_remake.multimodal <单条参考MP4> --task-id <新任务>`；中断显式加 `--resume`，只复用该任务已完成阶段。新增薄适配复用正式DINO及Speech纯Semantic Top20；参考片使用现有Faster-Whisper base CPU INT8。没有接入或修改寻帧Web，没有转写原素材库。

实测 `D:\Users\Desktop\BJ\88888888 (1)(1).mp4`：27.433秒、4个shot、16张代表帧、15个ASR段、39个有效话术query。按预先固定证据规则得到0 HIGH、3 MEDIUM、1 NEEDS_REVIEW；最可能来源video65（AST-30BDD9631F51D4865F01），但全片时间不连续，只有shot2–3暂定同源链，未达到可靠自动定位。结论 `MULTIMODAL_NOT_READY`，未启动剪辑。

产物：`auto_remake/results/real_88888888_v03/analysis.json`、`reference_speech.json`、`report.html`、`report.md`、`validation.json`。详细启动环境与固定规则见 `auto_remake/README.md`。所有正式索引、模型、原字幕及当前Web保持未修改，轻量保护清单1051文件前后一致。总处理27.721秒（各成功阶段墙钟累计，含冷加载，不含开发/人工等待/报告写出）。

## 2026-09-28：auto_remake V0.4 候选素材片内对齐

独立入口 `python -B -m auto_remake.align auto_remake/results/real_88888888_v03 --task-id <新任务>`。基于原证据选5个asset，以现有DINO/Speech指定行向量重搜16帧/39话术；不调用全库FAISS、不重建索引、不解码原片、不重跑ASR。先独立语音锚点，再时间带视觉与联合顺序路径；规则预先固定，未按结果调参，未接Web。

结果目录 `auto_remake/results/real_88888888_v04/`。video65仍是第一候选，序列分0.4984，第二video205为0.4011，分差0.0973。约01:58:26–01:58:43路径虽顺序合理，证据coverage仅56.4%，中后段画面/话术弱且跳过末段强锚点；原1:49/1:54/1:58冲突没有真正解决。结论 **ALIGNMENT_NOT_READY / NEEDS_REVIEW**，不进入正式source timeline或剪辑。

48项测试通过；1141个受保护文件前后一致，V0.3完整保留，生产Web及正式DINO/CLIP/Speech未改。10.091秒为本轮成功计算阶段累计，含参考query编码；详细候选、节点、模型复用、性能边界及人工观察见HTML和report.md。

## 2026-09-28：auto_remake V0.5 整段原字幕与局部声音验证

独立 `auto_remake.localize --task-id <任务> --stage text/audio`，随后 `auto_remake.localization_report <结果目录>`。只针对当前已授权88888888案例，复用V0.3的15条ASR和V0.4的16张DINO query向量；没有新Semantic查询、没有重新编码或转写。候选扩展19个asset，完整原字幕逐副本/run做有限合并的局部Smith–Waterman；之后仅Top3 asset最佳时间带（合计192秒）解码局部音频，MFCC+DTW，再DINO局部复核。生产与历史V0.3/V0.4未改。

`auto_remake/results/real_88888888_v05/`：video65（AST-30BDD9631F51D4865F01）仍第一，01:58:25.820–01:58:34.820文本4/15可靠、coverage28.29%；01:49/01:54各2/15。8个声学块仅开头2个一致，ref0–4.44和4.92–8.24对应source7105.83–7110.23和7110.75–7114.03。DINO WEAK（4/16）；第二video183文本1/15、音频0/8。第一候选相对胜出但整片覆盖不足，**SOURCE_LOCALIZATION_NOT_READY**，整片trusted start/end为null，不进入自动裁片。

55项测试通过，1220文件轻量保护检查一致；原字幕、DINO/CLIP/Speech正式索引与Web未改。12.532秒是记录到的阶段计时合计，不包括参考MFCC预计算等未计时步骤。详见report.md/html、analysis.json、results.csv、audio_anchors.csv和validation.json。没有继续追加区域声学搜索、模型优化、索引重建或剪辑。

## 2026-09-28：auto_remake V0.6 Source Switching

独立入口 `auto_remake.source_switching --task-id <任务> --stage recall/audio` → `auto_remake.source_graph <结果目录>` → `auto_remake.source_switching_report <结果目录>`。只处理当前88888888案例，保留V0.5开头ANCHORED，不重新优化。后段7个重叠窗，24条Speech全库query及12张DINO既有向量全库Top500召回；14个asset轻量原字幕定位，3个asset的5个有限带合计374.90秒局部音频，无全片扫描/源ASR/新embedding。

`auto_remake/results/real_88888888_v06/source_segment_graph.json`：新确认ref11.40–14.12→video65（AST-30BDD9631F51D4865F01）01:49:25.713–01:49:28.413。与开头约01:58构成同asset不同时间段证据，具体切换边界仍在未知间隙。直接声学覆盖28.29%→38.20%，增加2.72秒；图中分配来源10.96秒（含开头0.48秒间隙），UNRESOLVED16.473333秒。其它音频候选完整保存但未全部通过分半/辅助证据门槛，未强塞source字段。

**MULTISOURCE_LOCALIZATION_NOT_READY**，未自动裁片。17.04–20.78声音证据强但旧字幕否定启发式将“好不好”误计为否定差异，严格门槛可能漏接受；本轮只记录，不修改模型/旧规则。未证明其它asset插入；未知部分仍需人工确认。61项测试通过、1279文件保护清单一致。生产及V0.3/V0.4/V0.5均保留，详见report.md/html、candidate_results.csv、validation.json。
# 2026-10-06：YIXIAOER_ACCOUNT_AUTO_SYNC_READY

8502业务账号现已自动同步蚁小二抖音账号。唯一映射依据为provider_account_id；新Provider ID创建独立YXER-DY-{id}业务账号，绝不按昵称/备注合并。既有丙曜和引流账号的原映射、模板、长期授权与历史保留；未映射历史账号62288252897继续独立。

新增BusinessAccountRegistry及YixiaoerAccountSyncWorker，迁移只新增账号快照/审计/请求表。周期查询由AccountSyncWorker负责，原发布/托管Worker普通周期读取本地快照，正式提交前保持严格账号校验。新账号默认尚未配置，不自动建模板、不自动开启托管、不生成、不发布。Provider异常阻止新正式提交；查询失败保留旧快照，缺失3次或900秒后标记断开，不物理删除。

常驻计划任务YIXIAOER_ACCOUNT_SYNC_SERVER_01已启动；启动同步一次、每300秒同步，登录Windows自动启动。配置位于yixiaoer_adapter/account_sync.config.json。AI托管和视频生成账号区域提供刷新账号，刷新仅投递后台只读同步请求；普通下拉/页面不启动CLI。无窗口执行沿用YixiaoerCliRunner。

真实首次同步3个抖音账号：新增夏禾（YXER-DY-6ac4a551e49305f1ab81d5ae），已有2个保持原映射。当前同步业务账号3个，另有1个未映射历史账号，OFFLINE/MISSING均为0。本轮真实Render=0、Publish=0；133项同步及现有回归验证通过，Worker调整后45项相关回归通过。详细结果、备份、快照比对和日志见yixiaoer_adapter/runtime/account_sync_20261006/REPORT.md。


## 2026-10-07 生产素材上传入口 V1

8502 → 视频生成模块新增「生产素材库」，默认上传。独立LAN服务8510负责分片、续传、校验、SHA256去重、防覆盖与编目。四个起号目录和背景目录复用原位；五个Commerce目录仍待管理员在本机高级管理中配置。产品支持通用与小妙招，新增产品使用稳定ID。详见 [部署、消费端与验收说明](production_materials/README.md)。

本轮只接线页面及生产素材编目；未改原始索引、Startup生成算法、Render Worker、Publisher。未来CommercePlanner只有素材查询接口，未实现带货生成/托管。验收不向正式池加入模拟视频，实际上传已有手法素材改名副本验证重复跳过。


### 2026-10-07 正式 Render 工作站故障诊断与单任务恢复

夏竹花开起号10月7日-1（STARTUP-953306bf-d777-4069-ae09-d648ed996f36）在 DRAFT_OPEN/MEDIA_LOAD 阶段被 LVLoadingDialog 加载遮罩误报 UNKNOWN_MODAL；原收据泛化阶段为 EXPORTING，实际上此前没有点击最终导出，也没有成片。新增严格的已验证加载窗口识别和有界等待，真正未知弹窗仍拦截；DRAFT_LOAD_TIMEOUT 隔离单任务。修复 Qt 下拉选择时重复激活父窗口导致菜单关闭的问题；焦点变化时先重新观察。补充 ExportProgress 百分比文本识别。

仅恢复原任务，最终导出1次、局域网回传1次。ffprobe及全片解码通过：251.533333秒、1080x1920、30fps、H.264/AAC、311641683字节。原 RenderJob=COMPLETED、Content=READY/NOT_SCHEDULED。原失败回执归档，清除当前Content错误字段。正式WORKER-2060S-01进程与计划任务恢复、Session1、IDLE、三个健康项READY。恢复原领取配置；所有账号仍停用，两条原QUEUED任务未领取。仅更新两个受影响账号的渲染提示，不恢复授权。新增RenderJob/Content/PublishJob、Provider Upload、真实Publish均0。

8502及托管进程已重载具体错误提示代码，原Publisher进程未重启。21项渲染回归测试通过；50项生产集成fixture测试通过。完整证据：startup_render/runtime/workstation_diagnosis_20261007/DIAGNOSIS_RESULT.json；原截图与导出完成截图在 outputs/lan_render/WORKSTATION_DIAGNOSIS_20261007。本轮完成后停止，未推进Publisher。

### 2026-10-07 晚枫原任务 UIA 停滞修复与恢复

原 RenderJob `STARTUP-f62a915b-81ff-4763-81e6-77fe6e135914` 在草稿打开后的 UIA `CurrentClassName` 读取发生 COMError -2147220991（事件无法调用任何订户），没有发生导出提交。旧子进程退出，剪映留在编辑页，Server租约过期。原事件 EXPORTING 发生过早，已改为 RENDERING_PRE_EXPORT，最终点击才记录 EXPORT_SUBMITTED。

`startup_render/export_ui.py` 对已识别瞬态 COM 错误最多重探测三次，重建当前线程 COM/UIA 客户端并重新枚举窗口；不重复点击。`media_execution/progress.py` 持久记录 stage、stage_started_at、last_progress_at、stage_timeout、recovery_count；覆盖启动、打开草稿、等待导出、导出配置、导出百分比和成片校验。心跳不计为进度；父进程看门狗只收割本 Job 的 Python 自动化子进程，绝不强杀剪映/原生导出。校验与归一化使用剩余阶段时限。8502卡片显示任务名、阶段、阶段持续时间和最后进度；停滞显示“任务停滞，需要处理”。

原任务经归属、无导出闩锁、无成片、无有效租约和无人工编辑证据检查后正常关闭旧剪映。Qt从编辑器回到首页的过渡窗口只做有界等待，未知弹窗不点击。首次原任务恢复持久闩锁 `render_recovery_once.json` 记录 recovery_count=1；有导出闩锁或已恢复一次均禁止再次导出。可证明剪映退出的失败按 JOB_LEVEL 隔离并释放槽；无法证明停止的原生导出继续保留租约。

2026-10-07 21:17:27（上海）原 RenderJob=COMPLETED、Content=READY/NOT_SCHEDULED、Worker=READY，执行槽释放。成片位于2060 `D:\JianyingRenderWorker\Jobs\STARTUP-f62a915b-81ff-4763-81e6-77fe6e135914\output\晚枫起号10月7日-2.mp4`；ffprobe及完整解码PASS，188.933333秒、1080x1920、30fps、H.264/AAC、234668982字节，SHA256 `e0c11869826020321a2d671748df42d7443bb3e0bc0923a84952a4a5ce8abcf2`。导出提交1次，恢复1次。

恢复阶段暂停生产派发并保留6个已开启授权；新增RenderJob=0、PublishJob=0、Provider写入=0，发布表和历史FAILED记录完全未变。验收后依用户追加授权恢复原2060任务及Server生产调度；之后正常生产可新增发布任务，与本次恢复零发布验收分开计数。继续按当前时间检查原slot，过期跳过，不集中补量、不跨天补欠账。Server Provider Upload保持DISABLED。

证据：`media_execution/runtime/wanfeng_stall_20261007/recovery_audit.json`、`dispatch_resume.json`；2060部署与过程证据在 `outputs/lan_render/wanfeng_stall_20261007/`。本机29项回归通过，最终38项健康/阶段/恢复专项测试通过；更广的执行、生产桥接和剪映生命周期回归记录保存在同一runtime目录。备份后缀 `.wanfeng-stall-20261007.bak`；2060旧文件在 Resident/wanfeng_stall_backup_20261007。

### 2026-10-08 账号验证恢复检查（平台信号尚缺）

新增 AccountRecoveryProbe、恢复证据迁移005与8502「我已完成验证，重新检查 / 重新检查」入口。用户动作直接调用官方CLI读取新鲜账号列表和概览；普通页面刷新纯读，不创建Job、不上传、不Submit。ONLINE不作为验证解除证明，Account Sync与Recovery分开。检查网络阶段不持数据库写锁，单账号去重，用户关闭/换绑/新风险优先；充分证据才清当前门、恢复未来运行态，不追赶过期slot，不改历史Job。

2026-10-08 12:06:25（上海）夏竹花开稳定Provider ID `6ac4b574faa99a4ec8670bb3` 为ONLINE、未冻结/锁定，但官方CLI3.2.26缺少平台授权有效性、风险/验证解除、当前发布能力信号。本次 `UNKNOWN / PROVIDER_VERIFICATION_SIGNAL_UNAVAILABLE`，不宣称账号恢复；保留BLOCKED_RISK和PAUSED_NEEDS_ATTENTION，原长期授权保留。页面显示最新原因、时间和重查入口。夏竹花开历史两类发布行逐行未变，submit总3→3，本次测试Job/上传/Submit均0，其他5账号授权不变，服务未重启。

100项回归通过；证据及当前无发布恢复限制见 `production_autopilot/runtime/account_recovery_20261008/REPORT.md`。2060另有独立的SYSTEM_PROXY_PRESENT发布网络门，本次未修改网络；Control Tower仍DEGRADED/YES，账号风险不是全局RED。不能把已接线的RECOVERED分支替身测试描述为平台已经提供恢复信号或真实账号恢复成功。

### 2026-10-09 紧急磁盘恢复与备份失败退避

按用户明确授权移除旧 `benchmark/experiments/dino_july_test` 的 frames、features、实验FAISS（60.98 GiB逻辑大小）；配置、README、报告和manifest保留。旧 `dino_index/formal_v1` 的329个文件（18.086 GiB）完整归档至 `E:\XunZhenArchives\20261009_disk_recovery\dino_formal_v1`，逐文件SHA256一致后移除D盘源目录。当前8502正式索引仍为 `formal_v1_repaired`，没有自动回退至旧formal_v1；独立旧CLI如需使用应先按 `dino_index/formal_v1_ARCHIVED.json` 恢复归档，不应直接调用已归档路径。

`BACKUP_ACTIVE_PROFILE_MISMATCH` 根因为账号暂停后保留授权，而执行profile关闭并降为SHADOW；旧校验将安全暂停误判为配置漂移，失败又不更新成功时间，每300秒运维tick重复全量复制。新增 `production_autopilot/backup_safety.py`：备份专用互斥、持久BACKUP_FAILED、15分钟至6小时退避、告警文件/日志、重试只验证原副本；仅在持久暂停证据及完整配置哈希核对通过时兼容安全降级，不改账号或历史Job。10项专项测试、2项恢复回归通过。

新有效备份 `startup_autopilot/runtime/production_worker/consolidation/backups/20261008T185734992037Z` 的3个DB均通过SHA256、integrity_check及隔离恢复；恢复副本foreign_key_check为空，七张关键表逐行一致，恢复派发锁保持HOLD_RECONCILIATION_REQUIRED。完成后清理60批失败/中断副本，保留8批更早备份（含最后已验证基线）及新备份；维护用STORAGE_PROTECTION备份专用暂停已解除，普通备份检查未新建重复副本。

D盘空闲23.298→149.943 GiB，净回收126.645 GiB（空闲差值含小文件簇空间，不能与逻辑文件大小直接相加比较）。主/旧视频数据库、正式DINO/CLIP/Speech、MobileNet FAISS和配置保护项大小及mtime全部一致。8502三种正式搜索实际查询通过。无服务停止/重启，无新增Render/PublishJob或真实Submit。2060 PID23116 READY、SessionGuard READY、执行槽空闲。Planner及Account Sync在本轮开始前已退出（任务Ready/result1），AI托管异常中心另有 `production_autopilot/ui.py:40` 的旧reason分隔符解析异常，本轮未扩大范围恢复这些服务或修改该页面；不可把磁盘恢复完成表述为全系统恢复正常。审计与验收证据见 `disk_recovery/20261009_v1/`。

### 2026-10-09 磁盘事故后的Server恢复及用户终止观察

Planner（PID60608）、Account Sync（PID62700）恢复为单业务实例，心跳正常；计划任务异常恢复间隔1分钟、3次上限、IgnoreNew。常驻业务异常和错误证据写入失败不再直接终止进程；Account Sync每20秒更新心跳，300秒同步时间独立保留。8502托管页面旧reason分隔符解析及单记录JSON容错已验证。31项回归、2项低磁盘演练入口验证和语法检查通过；原退出原因因缺少致命traceback仍为UNKNOWN，不将备份失败等同于磁盘满退出证据。

用户明确要求结束本轮观察、不延长。专用只读采样已停止：31样本、964.425秒（16分04秒），**未达到完整30分钟，不签发30分钟观察PASS，也未启动六小时Level1**。最终只读检查未发现SYSTEM Blocker，Control Tower DEGRADED/YES（1账号风险+4隔离Job），正式API鉴权HTTP200、8502正常；2060 PID23116 ONLINE/READY、SessionGuard READY、Heavy Slot IDLE且无泄漏，未重启2060。D盘149.938 GiB；采样期净使用增加1.063 MiB，Backup目录增长0、9批保留、最新COMPLETE。原31作品27排期+4公开，submit_attempt_count全部1，Reconciliation检查推进；4READY保留。重复Composition/RenderJob/PublishJob/Submit、历史slot补发及观测HOL均0。受限环境的LAN探测失败不算正式API离线；正式鉴权最终核对单独留证。详见server_control_plane_recovery/20261009_v1/REPORT.md及FINAL_RESULT.json。


### 2026-10-09 Level1范围正式扩展为全系统

用户最终确认AUTOPILOT_UNATTENDED_LEVEL1_FINAL_OBSERVATION为全系统04:23–10:23正式观察，不重新计时。旧“夏竹花开六小时Level1正式观察”为历史名称；现有automation id=level1已改正式名称与全系统规则，旧Windows只读任务名/目录保留，不重复安装。每分钟global_observation覆盖6个托管账号、Server/API/Planner/Account Sync/2060/Session/所有Render Export Verify与Publish Reconciliation/Heavy Lease/Disk Backup/重复与历史补发，并记录实际自动恢复和跨节点协调。观察器扩展代码只写审计证据；10项隔离规则检查和语法通过，生产DB、授权、Job、Slot、服务均未由本次范围调整修改。扩展前14个旧样本、2个维护历史快照、6个成功sync_runs（含窗口前基线）、不可变阶段/提交/租约事件已回溯保存。未留存的精细heartbeat、逐分钟磁盘、本地mutex/journal、精确HOL时长和被覆盖的checked_at明确EVIDENCE_UNAVAILABLE及替代证据/签发影响；不以缺字段自动重置窗口，也不提前承诺PASS。夏竹花开09:18正常未来任务已一次提交到SCHEDULED_QUEUED并确认OPEN，仅为专项成功。截止后全系统结论必须独立评估连续性/关键缺口；没有实际故障时恢复能力写NOT_EXERCISED，不制造故障。详见runtime/xiazhu_recovery_20261009/OBSERVATION_SCOPE.md及global_scope_evidence.json。


### 2026-10-09 新账号正式素材池绑定修复 V1

新增账号初始化改为读取 ProductionMaterialPoolRegistry，使用 STARTUP_TECHNIQUE / STARTUP_CLOSE 等正式 pool_id；检查登记、有效启用状态（默认登记启用，disabled_pool_ids 可禁用）、正式目录映射和可读取候选。空池返回 POOL_EMPTY 及正式池候选，不保存正常初始化。没有Schema迁移，也不再使用旧备份目录作为新增账号默认池。

CompositionPlanner 对重复手法、收尾位置按 material_id / media_sha256 实施片内不同媒体约束，两个位置继续共享同一物理池；Slot复用次数、冷却、相邻成片和完整组合跨天历史规则保持原配置。修复预览可作为未确认Draft恢复，当前会话只同步指定pool字段，保留其它未保存编辑；不会自动确认模板或开启托管。

只修复昭暄（YXER-DY-6ac7453457e95ebe6027e8f0）的 HAND_1/HAND_2、TAIL_1/TAIL_2。重新计算SHA缓存并用ffprobe验证正式手法44、收尾16个唯一媒体；Day1–7全部5条，总35，片内HAND/TAIL及完整组合重复均0。模板仍Draft，Autopilot OFF。旧目录保留；其它账号旧目录引用0，昭暄未使用的引流/坐诊旧池继续保留在审计中。

88项相关隔离回归通过（初轮87通过；调整旧固定同媒体夹具后6项时段回归全通过，覆盖全部88项）。原Server Planner在2060 READY、重槽IDLE、无可运行队列时重载，PID64760新心跳确认；所有授权逐行不变，PublishJob与Submit计数增量0，没有重启API/2060。Provider、Server API、Planner、2060检查通过；正式开启前仍需用户预览并保存模板，再重新检查并明确开启。

证据：runtime/new_account_pool_binding_v1/RESULT.json、capacity_preview.json、media_validation.json、preflight.json、planner_reload.json及回归日志。源码备份后缀 .new-account-pools-v1.bak；shadow_before.sqlite仅为现场备份，不可整库覆盖正在生产的其它账号。回滚只按before.json对指定账号池/缓存/本轮新增预览做有界恢复，不修改授权、素材文件或其它账号。测试命令：python -X utf8 -B -m unittest startup_autopilot.tests.test_production_pool_binding startup_autopilot.tests.test_template_builder startup_autopilot.tests.test_template_ui startup_autopilot.tests.test_production production_autopilot.test_start_gate production_autopilot.test_slot_policy production_materials.tests.test_portal -q。


### 2026-10-09 8502旧Registry类缓存修复

上一轮初始化代码已加载，但常驻8502的热加载清单遗漏production_materials.store，导致新调用startup_defaults命中旧类并报AttributeError。补齐config/library/store依赖与主入口旧刷新器升级检查，Registry先于CompositionCatalog/TemplateBuilder/账号入口加载；新增账号入口在识别缺方法的旧缓存时仅reload代码，不初始化或迁移生产素材库。19项旧类复现、正式池初始化及真实主入口隔离回归通过，语法检查通过；实际8502只读选择炳谦后未配置页面正常、背景炳谦.png及开始设置按钮存在，未点击开始设置/托管按钮。未重启服务；本轮账号Profile、素材池、模板状态/版本/预览记录前后核对一致。证据runtime/new_account_pool_binding_hotload_v1/RESULT.json及tests.log，源码备份后缀.pool-registry-hotload-v1.bak。


## 2026-10-09 SERVER_DRAFT_MKL_MEMORY_RECOVERY_V1

草稿Whisper/CT2初始化在Commit余量不足时触发mkl_malloc，8502经用户确认无未保存内容后按原参数单独重载。新增子进程单线程、Commit预算和完整日志，50次隔离完整草稿通过；原6个未来slot经本次显式授权沿用身份恢复并生成6个RenderJob，无重复或补发。恢复器runtime/server_draft_memory_recovery/recover_original_slots.py不得由巡检自动重放，只适用于已批准的原6个ID且最多2次。Planner未重启，父模块新增FAILED_RETRYABLE/gc/恢复接线须下一次正常授权启动才生效，不能当成已经热加载。昭暄正常生产另遇平台登录失效，已留Server账号认证事件；禁止重提历史Submit或改变托管意图。完整证据、限制及源码哈希回滚见runtime/server_draft_memory_recovery/REPORT.md。

### 2026-10-09：局域网员工生产素材上传入口修复

原生产素材库iframe依赖192.168.1.126:8510，员工报告连接拒绝。后端实际监听正常，但防火墙绑定venv启动器而非实际基础pythonw进程。已修正规则并把正式入口统一为8502同源/production-materials/；正式launch.ps1使用新的server.py挂载固定回环代理，原app.py业务不变。用户确认无未保存内容、预检零未完成上传后仅重载8502，上传服务与Planner/API/2060未重启。

分钟级素材服务守护只恢复已退出的原单实例Task，尊重人工禁用并持久化退避预算。29项隔离回归通过，正式API256.4MiB样本完成8MiB断点续传、SHA256去重、正式带货池识别及暂存清理；小视频通过正式同源浏览器界面成功入库。测试产品upload_acceptance_20261009与现有起号池隔离，不用于发布。大样本为有效MP4加free atom填充，仅验证大字节传输。员工电脑最终确认及生产保护结论查看runtime/employee_material_upload_repair_20261009最终报告；不得把服务器HTTP200冒充员工实测。详见production_materials/README.md。

### 2026-10-09：8502正式索引模块应急恢复

Speech用户查询“小妙招”多次std::bad_alloc，原一次加载5.91GiB FlatIP超过现场5.53GiB可用提交内存；8502另曾退出，退出机制无日志不得冒称确认OOM杀进程。仅启动已退出8502，未重启Planner/API/2060。正式Speech查询改用speech_search.readonly_flat.ReadOnlyFlatIP，只读原text.faiss向量区并按32768行分块调用同一FAISS内积kernel，保持全库精确TopK、模型和metadata；没有重建/替换正式索引。新增各索引独立启动健康预检，当前搜索只依赖自己的catalog，某个索引失败不阻断其它搜索或自动生产；话术原文深色对比度局部修复。

三种真实8502浏览器查询各10结果、30条Asset ID/时间/缩略图映射通过，原失败“小妙招”亦通过；19项隔离测试（页面项含9子场景）通过。清理保护8项size/mtime全部不变，无正式文件误删或活动归档路径证据。生产数据库只读校验，未全表扫描；不改托管/发布规则，不创建发布测试。证据、回滚bak及退出机制/非阻断浏览器观察器日志限制见runtime/index_module_recovery_20261009_v1/REPORT.md。
