# 蚁小二8502正式Adapter

最新状态：**YIXIAOER_8502_PRODUCTION_CANARY_PASS / YIXIAOER_PRODUCTION_BATCH_28_READY**。用户已本人Confirm3条灰度，均一次提交、SCHEDULED_QUEUED，且确认抖音真实待发布。主Provider已切换蚁小二LOCAL，原28条仅新生产Preview，未Confirm、未上传或发布；下文READY记录属于上一阶段。

正式入口：8502正常登录苏政超/suzhengchao → 工作区“发布管理” → **蚁小二正式生产** → 28行Preview、每日分布及首尾时间下方蓝色“确认发布计划”。仅点击一次才创建1Plan/28Job。Preview ID `YIXIAOER-PRODUCTION-320f095f-a5c4-45b7-a8e2-1e5515407c86`，2026-10-06 09:00～10-09 18:00，5/8/8/7，原顺序/3h/每日上限，素材只排一次。

`production.py`准备并冻结本地生产Preview、既有DEFAULT帧封面和媒体SHA；002迁移增加生产Preview表、不可变Confirm授权及封面SHA列。只有`confirm_scope`校验的原员工完整选择/相同payload能创建授权。`deployment.py`在用户Confirm后才通知Worker；`worker.py`CONFIRMED_PRODUCTION模式仅消费新授权且显式allowlist内的Plan。当前worker_enabled=false、allowlist=[]，不采用旧CONFIRMED任务。

旧未提交28条占用已按事务核验及首条真实归档submit=false/0证据撤下，原Job/claim/排期/事件保留；额外旧第29条留在禁用队列中。未知结果先只读对账，未明确则暂停后续提交，不再次POST。空标题/简介按官方schema省略字段，不伪造文案。418项隔离覆盖及详细限制/当前证据见`publisher_poc/yixiaoer/production_batch_28/REPORT.md`。

当前验收：`YIXIAOER_8502_INTEGRATION_READY`。3条真实灰度尚未提交，不能写成`YIXIAOER_8502_PRODUCTION_CANARY_PASS`。

## 用户入口与授权边界

8502正常登录`苏政超 / suzhengchao`，顶部“工作区”选择“发布管理”，打开“蚁小二灰度验收”标签页。三行Preview表格和任务/去重/冲突计数下方的蓝色**确认发布计划**按钮是本次唯一Confirm入口。测试素材和排期已经准备，不需要重新选片或创建计划。其它“发布计划”页面的历史业务选择不是此灰度入口。

Preview只读取本地数据、账号缓存和媒体；不会上传或发布。单独的“刷新蚁小二账号状态（只读API）”按钮仅执行官方账号查询。账号缓存最多有效30分钟；过期则Confirm拒绝，不伪造在线状态。每次Confirm和每次claim均重新检查2h15m～14d排期、安全权限、绑定与媒体。首次排期为2026-10-06 02:25，所以该固定计划最晚须在00:10前确认；不允许自动移动既有时间绕过Gate。

用户Confirm后，现有`StartupPipeline/PlanBoundary`事务创建1个CONFIRMED Plan和3个PublishJob，原子加入provider绑定和READY_TO_DISPATCH记录；随后启动服务器唯一发布Worker。Worker只接受配置中显式列出的已确认灰度Plan，不扫描/迁移旧业务队列。重复Confirm保持同一Plan，按钮禁用。

## 正式执行与状态

`publisher.py`提供list_accounts、validate_publish_job、upload_video、create_publish_job、get_publish_status、reconcile_publish_result、get_provider_video_id/url。全部供应商操作使用已安装官方CLI；真实提交明确传`--publish-channel local --client-id`。

每Job流程：atomic claim → 本地/账号检查 → 上传指定视频和封面 → 官方validate → 同一payload dry-run → 独立计算并核验requestHash → 持久化SUBMIT_INTENT和count=1 → 正式publish最多一次 → 只读task对账。payload SHA、clientId和CLI SHA写入intent。超时或未知结果进入SUBMIT_RESULT_UNCERTAIN；只能查询对账，不能重新POST。

状态：READY_TO_DISPATCH、UPLOADING、PROVIDER_VALIDATED、SUBMIT_INTENT、SUBMITTED、SCHEDULED_QUEUED、PUBLISHED、FAILED、SUBMIT_RESULT_UNCERTAIN、CANCELLED。只有`stageStatus=success + stages=scheduled + publishId`映射SCHEDULED_QUEUED；success/push不提前满足灰度。真实公开证据关联相同作品ID后才能PUBLISHED。

`storage.py`和`migrations/001_provider.sql`保留原business account_id、content_id、Plan/Job ID。新增映射、provider证据、submit latch、append-only审计和独立canary准备表，迁移前备份。taskSet/task/video标识一旦写入不可改，submit count不能回退，审计和provider任务记录不可删除。

## 部署

服务器节点：YIXIAOER-PUBLISH-WORKER-SERVER-01。`worker.config.json`默认worker_enabled=false、allowed_plan_ids=[]、CANARY_ONLY。只有上述用户Confirm能通过`deployment.notify_confirmed`启用此Plan。3条全部SCHEDULED_QUEUED后关闭开关并退出，不消费后续业务队列。

`install_tasks.ps1`注册客户端与Worker的Administrator Interactive登录任务，不使用SYSTEM。客户端按正常登录机制启动；Windows整机重启、Windows自动登录和长期免扫码未验证，状态UNKNOWN。`health.py`分开显示ACCOUNT_API_OK与LOCAL_EXECUTOR_LAST_CONFIRMED，不虚构实时executor ONLINE。

服务器与2060S旧Xiaovcat发布Worker为LEGACY/DISABLED；2060S继续只负责Render/Jianying。Render任务、原业务任务和模型/素材库未改。

## 当前范围和限制

- 灰度账号业务ID1621131832863931；蚁小二ID6ac389eb46f95bf847d47da1，昵称只展示。
- 仅3条新生成纯测试MP4及各自独立封面，2026-10-06 02:25/02:40/02:55北京时间，无购物、位置、业务素材或话题。
- 必须提供封面；当前抖音官方schema只接一个challenge，超过1个话题明确拒绝，不静默截断。原业务模板需在后续正式开放前单独验证；本次没有授权开放原28条。
- 接入READY不等于真实灰度PASS。没有新Job/provider作品ID，submit=0。

## 隔离回归

使用8502实际Python：`.venv-cuda-test/Scripts/python.exe -X utf8 yixiaoer_adapter/tests/run_regression.py`。测试使用临时DB、模拟CLI和隔离Streamlit AppTest，不能访问真实供应商发布接口。当前399项覆盖Adapter21、Planner76、Startup248、Render54；日志及历史失败修正说明在`publisher_poc/yixiaoer/adapter_integration/REPORT.md`。
