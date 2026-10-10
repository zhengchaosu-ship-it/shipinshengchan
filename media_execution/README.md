# 2060S Render / Publish 单通道

### 2026-10-07：剪映健康语义

`workstation_health.py`健康采样只读UI，无点击、聚焦、关闭或截图写入。`JIANYING_NOT_RUNNING`和`JIANYING_IDLE_WORKER_OWNED`为READY；RENDERING/EXPORTING/VERIFYING为BUSY；MANUAL_USE为WAITING_FOR_WORKSTATION；已归属且无租约的ORPHAN_IDLE首页可安全收尾；UNKNOWN_BLOCKED为NEEDS_ATTENTION。窗口存在本身不是故障。

`startup_render.agent`专用启动后持久记录ownership，包含PID+创建时间、启动token/时间、任务和草稿身份。无归属窗口不进入关闭路径；已有归属但无租约的编辑窗口也按人工使用等待。Coordinator持有全局锁后及领取前复查，两类队列统一等待。人工退出后自动恢复，不改授权；过期slot按现有策略跳过。原`executor_quiescent`保留为恢复/故障释放时的严格进程停止证据，不再作为健康分类器。

验收命令见 `tests/test_workstation_health.py`（隔离A–H）；执行证据和部署哈希位于 `runtime/health_semantics_20261007/`。不需要另做真实渲染或真实发布验证。

### 2026-10-07 17:49：2060独立真实发布追加验收PASS

`REAL_PROVIDER_PUBLISH_ON_2060_PASS`。用户新增最多1条正式任务授权后，实时核验夏禾OPEN/ONLINE，选择尚无PublishJob的READY成片 `STARTUP-94affa8d-6268-4e22-adaf-58f81f8d4929`。2060全片复验通过，新Export=0；新PublishJob `4026d43a-b45d-4ec2-9bae-b1564d3d350f` 由2060本地视频直接上传，视频/封面各1次、正式POST=1。官方scheduled/success，Task `6ac613e9799bed4c0357c33b`、Video ID `7693858927401848099`；Server已回写SCHEDULED_QUEUED，排期2026-10-08 09:08 +08，尚非公开PUBLISHED。

Server上传0且保持DISABLED；活动48次Mutex采样全持锁、最大执行并发1、无Render重叠；本轮没有同期Render，WAIT未重测。历史296条PublishJob/58条ProviderJob及6授权逐行未改，长期托管仍全部关闭；旧夏竹花开风险失败任务未重发。一次完成后停止真实测试，Worker READY、租约释放。详情及16项报告 `media_execution/runtime/real_provider_validation_20261007_additional/REPORT.md`，本条为最新状态，下方此前FAILED_ACCOUNT_RISK记录保留为上一次验收历史。


状态（2026-10-07）：**RENDER_PUBLISH_2060S_EXECUTION_HANDOFF_READY**。

| 阶段 | 结果 | 已核验范围 |
|---|---|---|
| IMPLEMENTED | PASS | 单槽、非阻塞调度、门隔离、持久化恢复、异步归档 |
| WIRED | PASS | 原Planner/Composition/RenderQueue/Plan Confirm/ProviderStore、8502及常驻服务 |
| DEPLOYED | PASS | Server正式控制链 + 2060原计划任务，LOCAL_BOOTSTRAP_AND_REMOTE_FINALIZE |
| VALIDATED | PASS | 真机10 Render + 10 Mock Publish、进程中断恢复、归档及生产面板 |
| REAL_PROVIDER_VALIDATED | PASS | 新独立授权的夏禾任务由2060真实LOCAL提交一次，已SCHEDULED_QUEUED；此前夏竹花开失败记录保留 |

## 正式运行链

Server保留原Content/RenderJob/PublishJob及稳定business_account_id/provider_account_id。`ProductionControlPlane`附加执行表只维护原Job关联、租约、账号门、输出回执和提交证据，不创建第二套业务Job。DailyPlanner/Composition产生原RenderJob；2060完成后原Content READY，已有或新确认发布计划进入原ProviderStore执行链。Prepare/Preview/Confirm可读取2060冻结MP4及封面校验回执，不要求Server先取得成片。

Server控制服务和原Planner由原启动任务常驻。2060的XUNZHEN_RENDER_WORKER登录任务运行`media_execution.worker`，主动访问Server控制API，不依赖Codex或人工点击。执行节点固定WORKER-2060S-01，Server Provider Upload现为DISABLED；旧代码保留作人工审查后的回退，新Scheduler不会选Server上传。发布路径为2060 local MP4 → 本机蚁小二 → Provider。

单槽由Server SQLite事务租约、Windows `Global\WORKSTATION_MEDIA_EXECUTION_LOCK`和进程内线程闩锁共同约束。P0临近安全提交截止的Publish、P1其余Publish、P2 Render；先过滤可执行集合再排序，不抢占、不因队首账号风险阻塞其它任务。账号风险仅阻止自身发布，Render默认继续；READY积压默认15。账号恢复先WAITING_REPLAN，过期任务STALE_SCHEDULE；原Planner重新校验每日最多5条及去重，不能直接恢复旧排期。

原ProviderStore的SUBMIT_INTENT/count与执行提交闩锁同事务保存。已有intent或不确定结果不再次POST，仅通过正式Adapter查询记录/详情；无意图时可恢复原Job领取。Render已有有效MP4则normalize/ffprobe/full decode后完成原Job；无Export闩锁可恢复原任务；已有闩锁但无有效输出则待检查。恢复必须先持有本机锁，证明旧执行器静止。只正常关闭有完整归属及首页证据的剪映窗口；不强杀未知编辑/导出进程。

归档沿用2060→Server共享，单路、默认4MiB/s、256KiB块；重任务忙时暂停，两端SHA一致才ARCHIVED。ARCHIVE_FAILED不影响成功Render/Publish。只有PUBLISHED、有明确Video ID且ARCHIVED才标记可清理，未实现自动删除。

## 部署与运行

- 安装包：`deploy/2060_handoff_release/`；共享副本：`\\PC-20260617GEOP\RenderOutput\2060_handoff_release`。
- 2060代码：`D:\JianyingRenderWorker\Releases\2060-HANDOFF-20261007\code`；既有Python 3.11、剪映5.9.0.11632不升级。
- 配置/记录：`D:\JianyingRenderWorker\Resident\media_execution.config.json` / `media_execution.install.json`。
- 原任务：XUNZHEN_RENDER_WORKER；健康/日志/Dry Run：`Resident\media_execution\`。
- Server：192.168.1.126:8766，IP白名单及本机DPAPI Bearer；8502高级状态面板读取正式数据库。
- 2060→Server主动API及共享可用即可；Server→2060 SMB/WinRM不是前提。

本轮部署已经完成，无需再次运行安装器。下次安装/升级在2060管理员PowerShell运行`INSTALL_2060_RENDER_PUBLISH_WORKER.ps1`，只将最后完整`PASS: DEPLOYED; HEARTBEAT; DRY_RUN.`视为安装成功。RUNTIME_PASS和IMPORT_PASS只是中间步骤。安装脚本验证包SHA、剪映签名/Hash/runtime，持有本机锁后备份原任务/配置/代码，停止旧常驻，再更新原任务；发现重任务或未知残留进程时拒绝继续。`health_check.ps1`和`--dry-run`不真实发布。安装成功与真机混合验收分别留证。

`rollback.ps1`使用安装记录中的备份恢复该任务/配置/代码，不改数据库；Server统一模式仍会隔离旧领取入口。回退执行能力之前需审查租约、SUBMIT_INTENT与现有进程，绝不能双开新旧Worker或整体恢复旧operations.db。旧任务历史成片及闩锁均保留。

本机蚁小二CLI 3.2.26、客户端进程、自身clientId、doctor/schema及只读accounts已核验；凭据在用户明确授权后经RSA/DPAPI迁移，仅写2060用户配置并限制权限，安装包不含凭据。运行时重新检查网络代理/路由，现场ONLINE/DIRECT_CONFIRMED。必须保持Windows交互登录与本机蚁小二运行。API可读/客户端存在不等同于真实Provider端发布验收完成。

## 已完成的验收

2060真机使用10份独立3秒1080×1920合成草稿，经原剪映导出路径真实Export10次，每个任务闩锁1次，ffprobe+全片decode10/10通过。测试使用隔离数据库中的原正式业务模型，通过已认证Server测试路由及实际2060 Coordinator，测试后关闭该临时API。正式业务接线另用生产库健康/8502只读面板及原模型集成回归核验。

10 Mock Publish中5个可执行任务各POST1次，5个Account A BLOCKED_RISK保持等待。10 Render及5 Publish全部推进，最大重任务并发1，重任务期间越界领取0，Head-of-Line Blocking=0。A自身5个Render继续，B的5个Render/5个Publish继续。

在首个MP4已验证但尚未回执时中断Worker进程并重启Server服务，复验原文件完成原Job，无重复Export。在Mock POST已记录但尚未回执时再次中断/重启，恢复为SUBMIT_RESULT_UNCERTAIN并只读对账；总POST仍为5，全部唯一。10份归档实际拷贝/SHA通过、忙时暂停、模拟归档失败不改变Job、本机MP4保留。初始20任务验收未做真实Provider写操作；之后追加的1次真实发布结果见下。Windows整机重启未做。

2060最终代码68项回归通过；本机核心35项、焦点/恢复54项、桥接20项、发布确认20项等独立命令通过（存在重复加载，不累加为唯一测试数）。正式8502读取实际生产库的AppTest与HTTP健康通过；本项不是新的人工浏览器视觉验收。手动Prepare/Preview/Confirm在Server无MP4时通过，重复确认幂等，冻结媒体Hash变更被拒绝。

测试命令示例（现有环境，无新增依赖）：

```powershell
.\.venv-cuda-test\Scripts\python.exe -X utf8 -m media_execution.run_tests media_execution.tests.test_execution media_execution.tests.test_adapter media_execution.tests.test_verification
```

`run_tests.py`仅对测试目录处理Python3.14临时目录ACL兼容性，不修改业务逻辑或生产文件权限。原搜索模块不在本次修改范围，未启动新8501/全库扫描。

## 一次真实Provider验收与最终边界

本轮追加真实发布验收：用户指定“夏竹花开”并确认已完成官方验证。实时CLI核验稳定账号 `6ac4b574faa99a4ec8670bb3` 后，选用其尚未创建PublishJob或提交的既有成片 `STARTUP-3d90a6f4-5783-468f-80c3-d1d55c86b7af`（122.033秒），2060复验SHA/全片decode通过、与已有归档相同，新增Export=0。按原额度和时段创建唯一新PublishJob `f69e3602-e088-47ec-b9a5-6a27f92dd062`，计划10月8日09:18，未重新开启长期托管。

2060本机真实上传视频1次、封面1次，validate与LOCAL dry-run通过，正式POST恰好1次。Provider TaskSet `0ee25a0c-775a-4dc0-87d1-a6e3251ee82f`、Task `6ac607c1e888b10a7efba166` 返回新的官方账号风险失败：仍要求到创作者中心单独发布并完成验证。Job为FAILED、无Video ID、没有成功进入平台定时队列；不能将预定10月8日09:18描述为已经安排成功。收到失败回执时账号重新BLOCKED_RISK，原任务不重发；用户随后再次确认验证后的账号状态见下。**REAL_PROVIDER_PUBLISH_VALIDATION = FAILED_ACCOUNT_RISK**，执行交接状态仍为READY。

实测补齐客户端异步执行保护：CLI返回任务ID后，2060继续持有执行槽/Mutex/busy直到只读回执确认定时队列或失败；Worker中断后，Server对未确认结束的Provider执行保留重任务门，禁止另一个Render/Publish或Archive进入。只读终态确认后才释放；账号失败只封该账号。另修复单独手工确认的新计划不被旧托管暂停错误阻断，以及LocalOperator预览和已核验恢复门的保持。60项最终本机回归通过；最终代码部署到2060并重新校验297个代码文件SHA，节点专项结果见node-provider-final.stderr.txt。

真实验收前后逐行对比：原295条PublishJob、57条ProviderJob及6份长期授权完全相同；仅新增上述1个PublishJob/ProviderJob。最终计数PublishJob296、ProviderJob58、submit_attempt总51（新增1）；长期托管enabled=0。切换主体阶段旧后台曾更新21条Provider遥测/对账行，独立记录。最终证据 `media_execution/runtime/finalization_20261007/FINAL_AUDIT.json`；官方CLI证据 `outputs/lan_render/2060_acceptance_20261007_v2/real-provider-evidence/`。

普通账号风险不影响其它Render/Publish。提交结果未知且不能证明异步客户端已停止时，工作站重任务槽保守等待只读对账；这与已确认失败的账号门隔离不同。未实现自动删除MP4；未做Windows整机重启。未知剪映弹窗仍需人工处理，现有已核实的环境检测成功弹窗可有限自动确认。

完整23项交付：`runtime/finalization_20261007/REPORT.md`。20任务真机证据 `outputs/lan_render/2060_acceptance_20261007_v2/worker-evidence/`；真实Provider证据 `outputs/lan_render/2060_acceptance_20261007_v2/real-provider-evidence/`。初次夹具/焦点失败记录保留，未重置生产历史Job。安装/回滚脚本静态解析通过，本轮未实际回滚生产节点。

用户随后再次明确“夏竹花开和夏禾，完成了验证”。2026-10-07 17:28（Asia/Shanghai），2060官方CLI doctor及账号查询通过：两者稳定ID匹配、ONLINE、未冻结/锁定。原后台只读恢复请求均CHECKED，账号门恢复OPEN；6份长期托管授权保持enabled=0、旧失败Job和POST=1保留。此次复查新增PublishJob/Upload/Submit均0，不把账号门OPEN描述为真实发布已成功。本轮最多1个新正式PublishJob的额度已使用；若另做真实验收，须有追加范围授权。证据 `two_accounts_recovery.json` 与 `FINAL_AUDIT.json`。
