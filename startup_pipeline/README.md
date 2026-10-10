# 起号成片 → PublishPlan → PublishJob V0.1

## 2026-10-04 单条READY验收桥接（当前限定，不是通用发布上线）

原Planner页面默认模拟行为保留。`single_acceptance`仅对本轮GENERATION_RESULT唯一content、真实Render COMPLETED回执/主机成片SHA、STARTUP稳定账号绑定、严格快照及授权校验创建1个SINGLE_ACCEPTANCE Job；附表对run/content唯一约束，migration006有数据库备份、旧行保留及FK检查。不手写伪造content/RenderJob，不自动消费其它发布任务。

现有V0.4 Prepare/Precheck/Submit只做兼容参数化，仍同一套Worker；只有注册scope才能用新READY MP4，旧固定V0.4入口仍不能消费任意Job。最终持久化预留→唯一Invoke→许可关闭，无自动重试。当前新增Job0716cc5f-1cb5-48a1-aada-b29297a91a04的真实表单已回读，但外部提交权限审核拒绝：当前默认空模板与历史陶老师/健康话题文案需用户明确确认。Job NEEDS_MANUAL，无提交预留/点击/真实发布，全局开关false。当前不是STARTUP_FULL_CLOSED_LOOP_PASS，也不是发布模块全面上线。后续只能恢复这个现有Job并重新校验参数/快照/时间，不生成第二条。

## 2026-10-04：WORKBENCH_ACCOUNT_BOUND_STARTUP_READY

以下为最新流程；后文V0.1人工成片登记说明仅适用于历史未绑定内容，不适用于新自动生产内容。

1. 在寻帧8502顶部登录工作台，复用原 `planner_session`。无需先到发布管理登录。
2. 起号自动合成页面先选目标STARTUP账号；只有当前员工授权、在线、快照未过期的稳定ID可用，无须MP4。
3. 生成前事务预留GenerationContext与名字：`{安全昵称}起号{月}月{日}日-{序号}`。序号按稳定账号ID/业务类型/本地日期隔离，数据库事务与唯一约束防并发，不扫描草稿文件夹。账号改名不改变历史名字和归属。
4. 成功草稿经原登记服务关联不可改写的 `startup_content_bindings`，自动PENDING入RenderJob；2060S仅继承账号，在原导出流程中使用 `{draft_name}.mp4`。
5. 原自动回传链路经主机SHA256和ffprobe验收后进入原READY池。新绑定内容禁止手工注册MP4补结果。池显示内容/账号/文件/时长及只读真实渲染队列状态。
6. `STARTUP_READY_POOL`直接带入计划，账号只读；服务端和提交前再次核验稳定ID。不同账号内容禁止混合计划，禁止管理员修改历史归属。`MANUAL_EXISTING_VIDEO`仍保留，但不可用该入口改投已有账号绑定文件。

本轮只增加migration 004附表/触发器，未为历史内容猜账号。失败批次 `20261004_003025` 永久排除。账号快照仍须30分钟内，过期需要通过原同步入口刷新，不以旧状态继续生产。

2060S仅部署输出名与回执账号字段适配；`render_child`、版本检查、传输函数和剪映控制未改。两端专用监听仍禁用，本轮没有生成草稿、启动导出或真实发布。需用户新生成1条后，另行恢复新单任务验收，不能把隔离测试当成真实跨机PASS。

回归/附表迁移证据：`startup_pipeline/runtime/account_bound_v01/RESULT.json` 与分组日志。可复核命令：`.venv-cuda-test\Scripts\python.exe -X utf8 -B -m startup_pipeline.verify_account_bound`；只有显式 `--migrate` 才应用附表迁移，不消费任务。

已知边界：原计划确认仍是本地模拟、不会自动消费；旧V0.4 Worker依旧固定旧单条任务，不是新内容的通用真实发布消费者。本轮仅加防串号最终守卫，未开启自动发布。不同账号同名或往年同名发生物理名字冲突时安全拒绝，不覆盖已有草稿。

## 历史V0.1记录（以上述最新流程为准）

当前 `STARTUP_AUTO_PUBLISH_PIPELINE_PARTIAL`。接线代码和158项回归已通过；苏政超至少三条真实导出MP4模拟验收尚缺素材路径及批次映射。没有真实发布，Worker完全未修改。

## 使用入口

寻帧8502：发布管理登录后，起号自动合成页和“发布管理 → 起号待发布池”均可访问自己的池。登录后正常生成的新批次自动记录归属，并复用原Manifest。原合成模块只生成剪映草稿，成功草稿不等于READY视频。

1. 在剪映正常导出MP4（本模块不控制剪映、不复制或转码文件）。
2. “登记/核验导出MP4”选择准确视频序号，填已有原文件完整路径，通过ffprobe后才READY。历史批次先由管理员明确指定所属员工，不能根据文件名自动匹配。
3. 选择单条、多条或本批次全部，进入原Planner，内容ID与MP4已自动带入；只提供本人STARTUP组稳定账号ID。在线快照仍遵守原30分钟期限，过期需管理员使用已有同步入口刷新。
4. 选择固定发布模板，核对时间、数量模式、间隔、总任务数及完整预览。“确认发布计划”才写本地模拟任务，不能实际发小V猫。

## 实现边界

增量迁移只新增startup表；原PublishJob字段不改，新增关联放startup_job_metadata和startup_plan_items，引用既有job/item主键。账号级模板只预留关联。内容归属、STARTUP权限、文件和预览校验全部在服务端。内容/账号/时间签名不含plan_id，数据库唯一约束和事务防重复；同路径既有非FAILED旧任务转人工，不冒充新视频。

新任务使用原PublishJob但状态NEEDS_MANUAL、current_step=STARTUP_SIMULATION_NOT_DISPATCHED，不进入PENDING队列。只有real_publish_enabled=false才允许确认，没有启用真实发布的分支。池内SCHEDULED只表示本地模拟任务，并非小V猫定时队列或平台已发布。SUBMITTED/PUBLISHED等仅预留状态，本轮没有真实回调实现。页面不提供MP4删除或自动取消任务。

当前V0.4发布Worker固定先前单个JOB_ID/视频，并非通用新任务消费者。不能通过改全局开关或再次运行旧submit脚本来消费这些任务。后续真实单条验收必须另行授权并确认Worker兼容契约，不属于本轮。

默认模板允许空标题、空固定简介与空话题，管理员可创建固定文本模板；topics_json独立，不混入简介。封面DEFAULT，不另选图片。没有AI文案、COMMERCE生产接线、手机端或数据回流扩展。

## 验证与证据

在项目根目录使用config.json已有Python：

```powershell
$startupPython = (Get-Content config.json -Raw -Encoding UTF8 | ConvertFrom-Json).paths.python_executable
& $startupPython -X utf8 -m startup_pipeline.verify
& $startupPython -X utf8 -m startup_pipeline.acceptance
```

verify使用隔离数据库/三个夹具文件及独立0.4秒小型MP4，记录40项新测试+118项原回归；不操作桌面或生产素材。SIMULATION_PLAN明确标为非生产员工/非真实成片；测试结束清除临时夹具。acceptance验证受保护哈希、既有业务数据及苏政超本地权限，只允许既有的增量迁移/短期本地登录会话，不创建生产计划。

结果：xiaovcat_adapter/results/startup_pipeline_v01/。当前生产新内容及新任务均0；需要至少3条已有起号导出MP4的完整路径、batch_id和video_index，方可完成指定真实员工模拟验收。
