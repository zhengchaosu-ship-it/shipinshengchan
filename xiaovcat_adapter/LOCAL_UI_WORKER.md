# Xiaovcat Local UI Publish Worker V1

独立入口：`python -X utf8 -m xiaovcat_publish_worker --config xiaovcat_adapter/local_ui_worker.config.json`，工作目录项目根。正常启动由Task Scheduler `XUNZHEN_XIAOVCAT_PUBLISH_WORKER`执行项目配置runtime的pythonw.exe。没有Codex、Remote Desktop Commander、computer-use、OCR、屏幕坐标或截图运行依赖。

## 默认部署与本轮界限

配置`worker_enabled=true`、`dry_run_mode=true`、`real_submit_armed=false`。此模式只检查本机进程身份/Session、发现已确认队列、构造正式表单字段、写心跳和Dry Run报告。**不会claim、实例化PrepareUI、操作表单、刷新小V猫账号或提交**。Mock/历史Fixture通过不等于Job3真实UI已FORM_VERIFIED。

初始只允许Plan `52e11ba8-fe9b-47f4-ae1f-74ed593712a9`、Job `af6c16d3-2912-4390-88c7-4584b3e4feea`。不创建Plan/Job/content/Render，不消费其它历史任务，不操作Job1/2，不重算原15:00。

## 身份与权限

- Worker与小V猫必须同一活动交互Session、同一Windows SID；锁屏/安全桌面/进程不存在时HALTED_NEEDS_MANUAL。
- 本机执行授权来自固定Windows生产用户及本地配置的明确Plan/Job范围。不是员工登录token，不创建planner_sessions、不伪造员工身份/acceptance scope、不提供远程未认证执行API。配置及operations.db必须仅允许可信本机维护用户修改；本轮未调整ACL或建立新安全架构。
- 复用`ProductionDispatcher._claim_in_transaction`。该函数只有在员工鉴权或本机授权成功后调用；BEGIN IMMEDIATE + QUEUED条件UPDATE，共用原严格_context（CONFIRMED、有效员工、STARTUP授权、稳定绑定、新鲜在线快照、未提交记录、媒体、固定未来排期）。原员工token接口保持兼容。
- 如仅快照过期，武装后的正式Worker最多调用1次既有单组同步，核验稳定ID，保存真实在线状态，再重新执行严格claim。默认Dry Run绝不刷新或放宽快照。

## UI与提交安全

`XiaovcatLocalUiPublisher`分离observe、prepare_job、verify_form、submit_once、reconcile_result；每动作取得新UIA树/控件，fresh_read只重读最多2次，不重放写动作。既有账号、文件选择、话题、同步及最终回读代码复用。初期能力仍限定已验证的丙曜/抖音，不宣称已泛化其它平台/模板。

本地scope禁用截图证据（旧默认保留），`uia_only=true`使旧日期字段沿用ValuePattern但通过SetValue写入，不使用原键盘输入分支。新日期UIA写入和任务记录导航只有Mock验收，首次实机仍须按现有回读条件验证；失败禁止偷偷切回键盘/坐标/OCR。

每Job结果/表单/回读在`runtime/local_ui_worker/jobs/<job_id>/`；状态阶段写原state_events。原持久化`V04_FINAL_SUBMIT_RESERVED`在Invoke前commit，作为submit_attempt_count=1的保守单次身份（reserve成功但Invoke未到也不得重试）。submit_started_at来自该事件；Invoke返回立即记时间，并通过LOCAL_SUBMIT_RETURNED保存数据库。返回字段为空不证明没提交。

复用原execute_once的最小**单Job内存许可**true→finally false；全局xiaovcat_adapter/config.json始终false，不以全局开关允许整个队列。real_submit_armed是Worker额外授权闩锁，两者不可混同。

只读任务记录导航使用同一UIA SelectionItem/Invoke模式，遇未知弹窗停止。结果按同一checkbox任务块的完整文件basename、稳定账号ID、昵称、平台、固定定时与“创建:”时间±120秒唯一匹配。不使用最新一条；多匹配/缺字段=SUBMIT_RESULT_UNCERTAIN。后台状态不等于已同步。已同步才登记content SUBMITTED、Job SCHEDULED_QUEUED，绝不提前PUBLISHED。

重启时：同Worker已有reserve只POST_SUBMIT_RECONCILIATION，不prepare/claim/submit；原nonce保留，可将SUBMIT_RESULT_UNCERTAIN通过严格关联证据收口。无reserve但已CLAIMED的中断任务转BLOCKED，不重放部分表单动作。未知/失败停止后续消费。其它Worker的claim绝不接管。

## 运维

- Task固定Windows生产用户AtLogOn，Interactive/Limited，不用SYSTEM；IgnoreNew、异常退出恢复3次/1分钟。本轮不做注销/重启验收。
- 单实例：executor.lock + 与既有桌面Worker共用Local mutex。第二实例WORKER_ALREADY_RUNNING退出，不覆盖主心跳。
- 心跳25秒：worker_id、hostname、pid、session_id、status、current_job_id、last_heartbeat、进程存在、dry_run_mode、real_submit_armed。读时必须结合PID和时效，不能仅看旧JSON。
- 原resident_monitor.py及日志保留，旧只读进程已正常退出；新Worker整合心跳。没有两个executor同时claim。
- 正常停止：建立runtime/local_ui_worker/STOP_WORKER标记，循环完成当前动作链后退出，不强杀正在提交的进程。重新启动前移除维护者自己创建的标记。
- 未来启用是另一个明确授权步骤：核验范围、时间仍合法、账号/文件/绑定后，停止Worker，配置dry_run_mode=false及real_submit_armed=true，再从专用计划任务启动。只改一个开关导致矛盾配置会拒绝启动；不需要改代码。配置身份/范围变更需重启，不能热切到其它Plan。

本轮不执行上述启用步骤。首次真实本机prepare/readback、唯一提交及任务记录UIA核验尚未执行，不以离线测试代替真实发布证据。
# Job3一次性用户验收入口（2026-10-05）

新增`D:\video_search_tool\START_XIAOVCAT_JOB3_ACCEPTANCE.cmd`，只由用户亲自运行；Codex本轮未执行。详细说明见`JOB3_FIRST_REAL_ACCEPTANCE.md`。入口代码硬锁原Plan/Job3、账号/原文件SHA/固定15:00/文案，先严格只读预检；只正常交接唯一空闲未武装Worker，原配置不改。全部通过后仅本次进程内授权，最终Invoke结束立即撤销，再只读核验。断线/重启不继承内存权限，原reserve≥1永不再次提交；finally恢复原未武装Task。当前账号快照过期，需要先用现有“刷新发布账号”更新；本轮不替用户执行刷新或UI动作。
