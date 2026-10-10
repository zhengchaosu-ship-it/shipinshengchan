# Job3一次性实机验收：用户执行说明

本入口准备状态：`XIAOVCAT_JOB3_FIRST_REAL_ACCEPTANCE_ARMED_READY`。
这里的READY表示入口及安全机制已准备，并不表示当前已经武装或实机提交成功。
Codex没有运行本入口，也没有操作小V猫。

## 用户运行

在服务器小V猫所在电脑 **PC-20260617GEOP**，以原Windows生产用户 **Administrator** 登录，保持小V猫在同一未锁屏交互Session。不要使用2060S运行此入口。

当前只读检查发现丙曜账号快照已过期（最近同步2026-10-05 01:24北京时间）。请先通过8502现有Planner的“刷新发布账号”更新当前账号快照；不要重新创建Plan/Job或点击小V猫一键分发。

然后双击：

`D:\video_search_tool\START_XIAOVCAT_JOB3_ACCEPTANCE.cmd`

**运行此文件是用户亲自启动真实Job3验收，最多一次真实提交。** 不需要编辑任何配置，不要手工把常驻Worker武装。运行期间不要关闭终端、切换账号、改表单、锁屏或同时操作小V猫。

若预检报`PUBLISH_ACCOUNT_SNAPSHOT_EXPIRED`，没有claim/表单操作/提交，也没有武装；先更新现有快照。若报`SCHEDULE_NO_LONGER_SAFE_NO_RECALCULATION`，停止，绝不自动改15:00排期。现有安全窗口要求提交时距15:00严格超过2小时，因此不要拖到13:00以后运行。

## 唯一范围

- Plan：52e11ba8-fe9b-47f4-ae1f-74ed593712a9。
- Job：af6c16d3-2912-4390-88c7-4584b3e4feea。
- Content：STARTUP-a16c1f3b-2dbc-41ca-9c9d-8eb157a3e73e。
- 账号：丙曜 / 抖音 / 1621131832863931；STARTUP。
- 原视频：`D:\video_search_tool\outputs\startup_exports\STARTUP_b681bc5228bb43018cdfb6d4556a7af4\丙曜起号10月4日-6.mp4`。
- 原文件SHA256：8e6d565018aca1d2770ad8c38e4efdd27db2aac4e4a84b36cd5a6fa0fbefc256。
- 固定定时：2026-10-05 15:00 Asia/Shanghai。
- 标题空；简介陶老师小妙招；话题健康、健康科普、养生。

配置和代码双重限定，仅原Job3，不能扩展到Job1/2或其它历史任务。使用原正式队列、claim和PublishJob，不生成验收scope、不INSERT任务、不创建任何Plan/Job/视频。

## 执行机制

先只读核对固定配置、exe文件、Windows SID/活动Session、小V猫进程身份、唯一常驻Worker新鲜空闲心跳、原Task动作及解析后的真实SID；再读取原Job的持久化reserve（必须0）和正式_context，严格核验绑定/授权/当前在线新鲜快照/原媒体ffprobe与SHA/原排期。

全部通过之后才正常停止**空闲且未武装**的原常驻Worker（自己的STOP_WORKER标记，最多等待40秒，无kill、不关小V猫）。拿到原文件锁和原桌面Worker互斥后，再次严格预检；此时进程内才设dry_run_mode=false、real_submit_armed=true。**常驻配置文件始终dry_run_mode=true、real_submit_armed=false，全局real_publish_enabled始终false。**

复用现有本地Publisher：只run_once，CLAIM→PREPARING→FORM_READY→FORM_VERIFIED→SUBMITTING。表单fresh readback使用原校验，不绕过控件或绑定规则。最终单Job内存提交许可由原execute_once最小窗口启用；原数据库先commit提交意图，再唯一Invoke。一旦reserve≥1，入口再次运行也拒绝武装，绝不补点击。

原execute_once的finally在Invoke返回或抛错后，先撤销单Job许可及本次Worker内存武装，**再**保存/观察结果。Worker和入口finally另外兜底撤销。进程崩溃时内存许可消失，磁盘配置仍未武装；后续启动不能继承权限。

撤销武装后，本地Worker只读进入任务记录，按稳定账号/昵称/平台/完整文件名/固定15:00/本次创建时间唯一关联，最多轮询180秒。明确已同步才content SUBMITTED、PublishJob SCHEDULED_QUEUED；不能标PUBLISHED。无法确认则SUBMIT_RESULT_UNCERTAIN，不重新提交。最后仅恢复原未武装Task，不改Task配置；异常恢复不代表结果成功。

## 证据路径

- 入口日志：`D:\video_search_tool\xiaovcat_adapter\runtime\job3_first_real_acceptance\acceptance.log`。
- 入口结果：同目录`RESULT.json`。
- 用户实际运行才产生：`PREFLIGHT.json`、`ARMED.json`、`DISARMED.json`。
- 本轮只读准备证据：同目录`PREPARATION_READ_ONLY_EVIDENCE.json`、`REPORT.md`。
- 原Job表单/提交/任务记录证据：`D:\video_search_tool\xiaovcat_adapter\runtime\local_ui_worker\jobs\af6c16d3-2912-4390-88c7-4584b3e4feea\`。
- 回归日志：`D:\video_search_tool\xiaovcat_adapter\runtime\local_ui_worker\JOB3_ENTRY_REGRESSION.log`。

如果有任何真实提交意图/结果不确定，**不要再次运行入口尝试提交**；保留日志，只做后续只读核验。Job1/2永久保持各1次，不在本入口执行范围。
