# 服务器原Job3一次性入口

> 用户已取消原Job3的全部真实授权。本文件下方均为历史设计。
> 两端Job3 cmd/PS/Python一次入口现已安全拒绝：JOB_CANCELLED / exit20，不要尝试恢复或重试。
> 2026-10-05 13:28正式业务取消已完成：Job3=CANCELLED、attempt0、无SUBMIT_INTENT；依据用户本人真实只读无任务确认。Content READY/NOT_SCHEDULED，Plan PARTIALLY_COMPLETED。禁止重新激活或补发。

## 当前用户真实一次性入口（2026-10-05 10:38准备完成，Codex未运行）

在服务器Administrator本人PowerShell中执行：

```powershell
& "D:\video_search_tool\START_SERVER_XIAOVCAT_JOB3_REAL_ONCE.cmd"
```

只允许原Plan52e11ba8、原Job3 af6c16d3、丙曜/1621131832863931、原-6.mp4及SHA、固定15:00、空标题/陶老师小妙招/健康+健康科普+养生。没有可传入其它Job的参数，不消费Job1/2或第4条。入口内自行完成硬检查，不需另外先运行预检。账号快照过期在原互斥内由原正式单组机制自动刷新一次；失败不放宽在线/授权/稳定ID校验。

先只读PRECHECK→原一次执行互斥→再次PRECHECK/必要同步→原Worker/UIA/fresh readback→原持久化reserve→唯一Invoke→原finally撤销→只读任务核验。共享磁盘配置全程false，真实许可仍为既有单Job内存最小窗口，不把常驻队列整体武装。记录过提交意图，即使Invoke未返回或进程崩溃，也拒绝重新运行提交；只能核验旧结果。已claim而未submit也拒绝盲目重新prepare。

**固定15:00排期仍沿用既有大于2小时检查，必须在13:00以前完成最终提交检查；过时拒绝，不改排期。**

最新结果（仅真实运行后生成）：`D:\video_search_tool\xiaovcat_adapter\runtime\server_publish_worker\JOB3_REAL_ONCE_RESULT.json`。原worker.log、jobs/af6c16d3.../PRE_SUBMIT_CHECK.json、SUBMIT_RESULT.json、LOCAL_RECONCILIATION.json保留。只有唯一“已同步”才SUBMITTED/SCHEDULED_QUEUED，不标PUBLISHED。

旧`START_SERVER_XIAOVCAT_JOB3_ACCEPTANCE.cmd`保持只读NO-SUBMIT原样，不用它真实提交。下面是历史说明，不是当前真实入口。

> 2026-10-05启动器修复后：当前.cmd只执行NO-SUBMIT预检，不执行下方历史真实流程。
> `-NoSubmitPreflight`已硬编码，PS缺少该参数也拒绝运行。用户现在不要再次运行入口；真实执行需未来另一次明确授权。
> 本轮Codex只运行了一次只读launcher preflight，Job3 attempt仍0，globalfalse。

## 历史真实入口设计（当前包装器不启用）

由服务器Administrator本人运行：

`D:\video_search_tool\START_SERVER_XIAOVCAT_JOB3_ACCEPTANCE.cmd`

Codex准备/维护阶段不得调用此入口触发桌面操作。本轮没有运行它。

只允许原Plan `52e11ba8-fe9b-47f4-ae1f-74ed593712a9` 和原Job3
`af6c16d3-2912-4390-88c7-4584b3e4feea`，丙曜/抖音/1621131832863931，
原-6.mp4及SHA，固定2026-10-05 15:00 +08:00，空标题，简介“陶老师小妙招”，
健康/健康科普/养生。不创建或修改Plan/Job、排期、账号、MP4。

请保持服务器小V猫在Administrator同一交互Session运行。入口取得原互斥，拒绝已领取或已attempt的Job；
快照过期由原正式单组同步刷新，读取到错误ID/离线/未知弹窗则安全停止。
只调用既有PublishWorker/Publisher/UIA/fresh readback/reserve-once/任务核验，不调用Codex或远程截图。

只有严格预检和fresh readback通过才允许提交；原reserve先提交数据库，再一次Invoke。
scope的撤销回调和finally关掉进程内武装，磁盘dry=true/armed=false/global=false不变。
结果无法确定时只保留未知状态，不再次提交。即使只在UI动作前崩溃而attempt已经保留，也不重试。

文件：

- `xiaovcat_adapter/runtime/server_publish_worker/worker.log`
- `xiaovcat_adapter/runtime/server_publish_worker/LAST_CYCLE.json`
- `xiaovcat_adapter/runtime/server_publish_worker/jobs/<job_id>/PRE_SUBMIT_CHECK.json`
- `xiaovcat_adapter/runtime/server_publish_worker/jobs/<job_id>/SUBMIT_RESULT.json`
- `xiaovcat_adapter/runtime/server_publish_worker/jobs/<job_id>/LOCAL_RECONCILIATION.json`

只有原结果服务核验唯一“已同步”才登记SUBMITTED/SCHEDULED_QUEUED，不标PUBLISHED。
本入口只run_once，结束不消费第4条，不启动常驻Task。

固定排期距离提交仍须大于2小时；2026-10-05 13:00以后原15:00排期会被拒绝，不自动重算。

## 常驻部署边界

服务器Task `XUNZHEN_XIAOVCAT_PUBLISH_WORKER_SERVER`已经准备，Administrator/Interactive/AtLogOn，当前Disabled。
新config的worker_enabled=false，只有用户Job3一次性入口给予本次进程内授权。
旧服务器入口仍退役；2060S发布Task/进程及8776发布桥已停，Render保持运行。

Job3真实成功以前不得启用全量常驻生产。未来全量模式须原3个Job的成功+各一次reserve记录通过，
设置带时区的production_authorized_after以排除所有历史队列，再启用allow_all_confirmed_plans。
scope配置变更必须重启独立Publish进程；8502原服务也需正常加载新代码。本轮未重载8502。
当前不能宣称SERVER_XIAOVCAT_RESIDENT_PUBLISH_WORKER_READY。
