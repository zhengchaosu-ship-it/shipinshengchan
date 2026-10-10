# 2060S 起号草稿导出交接 V0.1

## 2026-10-04登录后真实正式单条结果（最新）

`LOCAL_JIANYING_RENDER_PASS`及新正式content `STARTUP-a212b58e-12de-4dd7-a586-779257e02792`的RenderJob COMPLETED/READY已取得真实MP4与自动回传证据。草稿/成片均为`丙曜起号10月4日-3`，丙曜stableID1621131832863931，专用5.9入口/登录检查/自动打开/导出通过。主机文件见`outputs/startup_exports/STARTUP_2bcc2960072d47e085af42a96a54a62a/`；H.264/AAC、1080×1920、30fps、141.133333秒、78,302,376字节，SHA6801b1894fdaf6aab6f220257ce3796321f4fd8a269644a8c9db84d964b52abc。

新增登录阻塞明确分类，不自动操作认证。配置`normalize_h264_output`默认false，本轮2060S开启；实际HEVC输出保留原文件，再通过本机FFmpeg H.264规范化，严格最终media_probe不放宽。当前任务首次VALIDATING失败保留；`resume_validation`只能在Broker本轮精确审批/原失败指纹/原成片SHA/导出已正常结束/GENERATION_RESULT单条一致时恢复验证及原自动回传，绝不再导出、领取或改旧失败。缺少审批的旧回执仍RESULT_IMMUTABLE。

一次人工登录解除隔离阻塞，其后正式生成/领取/交接/打开/导出/回传无需人工。真实发布尚未发生：单条新Job被文案参数权限审核阻止，须确认当前空默认模板是否用于本次发布，不能宣称完整闭环PASS。完整证据与限制见HANDOFF和runtime/closed_loop_20261004_post_login_01/。

## 实际DraftRoot/内部身份与失败传播差分修复（2026-10-04）

Worker曾把-2安装到`D:/JianyingRenderWorker/Drafts`，但2060S真实globalSetting.currentCustomDraftPath为`D:/JianyingPro Drafts`；-1是全局root_meta_info中的外部既有注册记录，-2没有注册。因此不能把“Worker文件目录存在”当作“已安装到剪映扫描目录”。配置新增jianying_settings/jianying_index，生产复制和启动前必须核对实际root；不修改应用设置，不手工注册全局索引。

`draft_install.install_check`核对必需JSON、正式名称、独立UUID、画布/时长、全部草稿JSON资源引用和已知重复身份。新增STAGING_COMPLETE/DRAFT_INSTALLED/DRAFT_FILES_VALIDATED，保留旧兼容阶段，不用加长sleep绕过失败。旧普通草稿的非JSON/空文件不解密，索引metadata ID仍检查，内容ID审计范围及不可读旧草稿列表明确写入证据；新生产主id/metadraft_id在生成阶段独立生成。

失败回执到Broker后，统一业务服务保存RENDER_FAILED及failure_code/message/failed_at/job_id；幂等指纹阻止重复变更和失败转成功。需005_render_failure.sql安全迁移，备份/旧行保留/外键检查与回滚已测试。权限、待发布池和真实发布规则不放宽。

本次只有隔离副本安装文件校验通过，未验证2060S真实UI出现/发现，不是可见性PASS。原失败任务、GOOD/BAD源草稿不改；无新生产草稿/PublishJob/发布。主机源码已修复但既有运行进程未重启，下次单条监听恢复前正常加载新版本。本轮到此停止，详见runtime/differential_20261004/REPORT.md及HANDOFF。

## 专用5.9启动入口硬约束（2026-10-04）

生产Agent只调用2060S已经部署的`D:/JianyingRenderWorker/Scripts/START_JIANYING59_WORKER.ps1`。真实桌面`剪映5.9 Render Worker.lnk`指向该脚本；日志统一使用`launcher_name=剪映5.9RENDER WORKER`。没有新造launcher、没有修改原脚本/EXE/更新组件；普通剪映快捷方式、协议、PATH及EXE直接启动均不可作为回退。

`agent.example.json`新增兼容配置`jianying_launcher_name`、`jianying_launcher`、`jianying_launcher_sha256`。Worker先核验既有脚本SHA，再通过同一入口的`-CheckOnly`验证实际EXE路径、5.9.0.11632、SHA256及Valid签名。启动须返回`JIANYING59_STARTED`且发现全新实例；`ALREADY_RUNNING`不算专用来源证明。启动后再次CheckOnly核验，版本漂移立即记录VERSION_DRIFT并停止，不继续适配新版。

保留正常关闭安全首页→全进程退出→专用入口重启→UI/真实名称ready→原pyJianYingDraft自动导出→正常关闭的生命周期；不会强杀正在编辑/导出或未知窗口。启动后按PID及创建时间跟踪Worker实例，正常关闭拒绝接管另开的未归属实例。每个任务`JIANYING_LAUNCH_SOURCE`记录launcher_name、launcher_path、jianying_exe_path、jianying_version、jianying_sha256、process_id、started_at及进程列表。

新增13项入口隔离测试，连同原生命周期/Render回归：主机59/59、2060S57/57通过，语法检查通过。专用脚本真实CheckOnly为VERSION_OK；本轮没有实际启动/导出生产草稿，实际启动来源须在用户下一条新任务中验收，不能将预检当端到端PASS。专用监听按新run的max_jobs=1、stop_after_one=true恢复，历史失败证据保留；real_publish_enabled=false。证据在`runtime/acceptance_20261004_050123_production/`。

## 剪映命名/刷新生命周期修复（2026-10-04）

`JIANYING_DRAFT_NAMING_PASS` / `JIANYING_DRAFT_REFRESH_PASS`：2060S隔离复用原失败任务已接收素材，真实列表发现“丙曜起号10月4日-1”，pyJianYingDraft自动打开并导出同名MP4，74.53秒，H.264/AAC/1080×1920/30fps/67.233333秒。正常关闭→进程全退→锁定5.9重启→真实UI名称核验→导出→正常关闭均已实际完成；原失败任务未重入队/未改COMPLETED，旧内容未改READY。不是新生产批次端到端PASS。

主机生成器已通过`XUNZHEN_RESERVED_DRAFT_NAME`向`DraftFolder.create_draft`传入业务名称，无需重构。修复Worker安装时覆盖为XZ-content_id的问题；5.9首页名称来自`draft_meta_info.json.draft_name`，通过UIA `HomePageDraftTitle:<name>`实际回读。`draft_content.json.name`为空并不代表列表名为空，5.9样本没有draft_info.json，不凭空生成字段。文件夹、正式metadata名称、UI查找名称及账号绑定任务MP4名称必须一致，content_id仍为独立稳定主键。

`draft_lifecycle.py`区分FILESYSTEM_DRAFT_READY、JIANYING_CLOSING、CLOSE_REQUESTED、PROCESS_EXITED、JIANYING_RESTARTING、JIANYING_UI_READY、JIANYING_DRAFT_VISIBLE及CLOSE_JIANYING。每次重新取得UI根，按真实首页/列表状态有界等待；名称不一致报DRAFT_NAME_MISMATCH，不可见报JIANYING_DRAFT_NOT_VISIBLE。编辑/保存/导出/未知弹窗或关闭超时停止NEEDS_MANUAL；只对核验过的5.9首页发送正常WM_CLOSE，不强杀。版本/SHA/签名/进程路径在重启前后核验。沿用既有导出库，不更改素材传输和业务完成入库接口。

隔离入口`isolate_draft_lifecycle`不调用Agent.tick/Broker/业务数据库，仅显式读取旧失败接收包、校验31文件、复制4个JSON到同名研究副本，素材仍引用原接收包；持久化单次尝试闩锁，不自动重复导出。研究产物不自动回传入READY。两端导出监听继续Disabled，发布开关false，等待用户后续指令。

注意：用户报告重启后旧草稿可见；但上一轮没有进程启动时间证据，本轮新副本重启前已可见，不能把历史DraftNotFound唯一确认为JIANYING_DRAFT_LIST_STALE。

## 生成完成事件入队修复（2026-10-04）

当前主机配置event_only=true。RenderJob由起号生成完成回调经StartupContentRegistration直接创建为PENDING，Broker只消费已创建任务，不再扫描文件夹生成任务或猜员工。登记附表保留DRAFT_READY/RENDER_PENDING，旧内容表仍GENERATING直到真实MP4验收。

生成前必须通过现有发布管理登录，employee_id随generation_id传递到业务登记与队列。无登录不启动合成；登记/入队失败分别显示CONTENT_REGISTRATION_FAILED / RENDER_JOB_CREATE_FAILED，不能冒充全部完成。失败批次20261004_003025禁止新入口补录。旧扫描分支仅为历史测试/兼容保留，当前配置不使用。以下旧HTTP文件传输说明仅保留作历史部署参考；正式LAN部署见本节。

## LAN RESIDENT RENDER WORKER V1（2026-10-04）

当前生产/发布权限分离：生成选择器及账号名称预留使用`get_generation_accounts`，要求员工/稳定组授权、账户启用和历史稳定身份核验，不要求当下online或30分钟发布快照。`get_publishable_accounts`及发布计划仍严格要求新鲜在线快照；过期返回`PUBLISH_ACCOUNT_SNAPSHOT_EXPIRED`，READY不会被删除或重绑。

新增层仅包含`lan_server.py`、`lan_protocol.py`、`lan_transport.py`、`render_worker.py`、Windows秘密保存及计划任务部署。`Agent`只增加可选通信适配器、本地Jobs目录和输出路径钩子；原草稿安装/专用入口/登录检测/生命周期/pyJianYingDraft/编码规范及ffprobe仍复用。`completion.py`/Generation/READY业务逻辑未重写；RenderQueue仍指向同一个render_jobs.db。附加LAN身份/租约/回执表的幂等迁移见`migrations/001_lan_resident.sql`，不更改jobs旧字段。

正式配置：服务器`startup_render/runtime/lan_resident_v1/server.private.json`，2060S `D:/JianyingRenderWorker/Resident/worker.private.json`。密钥仅引用当前固定用户DPAPI文件，SMB密码在Windows凭据管理器；无明文前端密钥。API固定LAN IPv4:8766，仅允许配置客户端且所有GET/POST均要求Bearer token，PUT/旧文件下载被拒绝。支持`/health`、`/worker/config`、`/worker/register`、`/worker/heartbeat`及`/render-jobs/{claim,id/status,id/complete,id/failed}`。

Worker `WORKER-2060S-01`，交互登录用户`sdaffwS`，计划任务`XUNZHEN_RENDER_WORKER`（AtLogOn、Interactive、Hidden、IgnoreNew、失败重启3次/1分钟）。旧`XunZhen-Startup-Render-agent`禁用以防双进程；共享原桌面/Agent互斥锁。服务器原专用Render计划任务改为`startup_render.lan_server`；8501/8502不因此重启。Windows需保持用户登录/桌面可用；检测锁定后`INTERACTIVE_SESSION_REQUIRED`，不解锁。登录/版本/未知错误停止领取并保持心跳，人工恢复后按保留state回执恢复，不重导出。

心跳独立线程20秒，不被单条剪映长调用阻塞。服务器90秒离线阈值、120秒租约。领取原子事务并记录固定Worker所有者；相同Worker重复请求返回原claim，不交给其它Worker。租约过期标记`LEASE_EXPIRED_NEEDS_RECONCILIATION`，不因网络超时重新Render；原Worker恢复后重发保存的回执，崩溃前无终态则原Agent明确失败并解除在途占用。机器永久丢失时需管理员核实现场后处理，**不自动猜测任务没导出就重领**。这是防重复安全边界，不是无人判断GUI未知结果的承诺。

共享（专用`PC-20260617GEOP/XunZhenRender`账户，均SMB加密，无Everyone Full Control）：

- `\\PC-20260617GEOP\StartupAssets` → 现有`E:/备份/起号手法`，Read；不复制第二套素材库。
- `\\PC-20260617GEOP\StartupTaskFiles` → 同队列原`server/packages`，Read；只含已有打包流程冻结的本任务JSON/模板依赖，覆盖其它源盘的小范围资源。
- `\\PC-20260617GEOP\RenderOutput` → `D:/video_search_tool/outputs/lan_render`，Change。

专用账号对原Users共享显式Deny，不能利用原Everyone共享读用户目录。服务器家庭LAN标记Private；API/SMB入站只在Private，API固定Worker IPv4，未关闭防火墙。原Guest映射策略已改为认证共享，原值备份`SMB_AUTH_BEFORE.json`；没有启用不安全Guest。hostname/IP在配置中，不修改路由器/IP/DNS；建议管理员以后设置DHCP固定租约。

任务本地`D:/JianyingRenderWorker/Jobs/<content_id>`，附`source/assets/manifest/output/logs`及既有package/events/state；实际媒体映射到package/assets本地SSD。缓存`D:/JianyingRenderWorker/AssetCache/<asset_id>/<sha>.<ext>`，SHA核验后可硬链接到本任务，避免同素材重复网络复制。每条保留`path_mapping_manifest.json`及回执`lan_path_mapping`。源UNC不直接进入剪映媒体路径，安装仍使用原映射函数。本地成片`Jobs/<content_id>/output/<draft_name>.mp4`，SMB原子返回`RenderOutput/<content_id>/<draft_name>.mp4`；已存在同SHA幂等复用、不同SHA停止，不能覆盖其它成片。HTTP只传JSON；主机原完成服务再次SHA/ffprobe后READY。

网络遥测临时失败不重新Render；HTTP指数退避，SMB`WAITING_STORAGE`最多4次，重传输出不调用renderer。最终回执保存在state后再发；断网时下一轮只重发回执。完整失败停止后续领取，日志不输出密码/token。`CLAIM_CONTROL.json`可限定验收batch或暂停新增领取，不中断已领取子进程。旧HTTP路径兼容测试仍保留，但正式计划任务不再使用。

验收证据`startup_render/runtime/lan_resident_v1/`。Remote Desktop Commander只用于部署/维护，不导出、不参与生产领取/文件传输/结果回传。API/文件Smoke及单条已实测通过；LAN Batch10为10/10 READY，最终状态在`batch10/FINAL_ACCEPTANCE.json`，不能拿切换前旧Batch10冒认LAN结果。最终26项报告FINAL_REPORT.json及机器时间线/身份审计保留；状态LAN_RESIDENT_RENDER_WORKER_PRODUCTION_READY。OS重启及真实网络断线注入未执行；新LAN内存仅终态/峰值快照，旧Batch10全阶段资源采样另列，不伪造缺失观测。

本轮只修复前置登记，监听保持禁用，等待用户生成一条全新草稿。测试结果见startup_pipeline/runtime/registration_fix/RESULT.json；此结果不是新一轮真实导出验收结果。

## 本轮单条验收模式（2026-10-04）

部署存在runtime/single_run.json时，以其started_at和max_jobs=1进一步限制新批次，仅允许单视频manifest。此模式补充PENDING/STAGING_FILES/DRAFT_READY/JIANYING_STARTING/EXPORTING/VALIDATING/VALIDATED/COMPLETED时间记录。任务机在素材全量哈希通过后调用已验证的版本检查脚本及pyJianYingDraft；错误保留证据并停机，禁止人工救场。

return_mp4模式自动把验证过的MP4上传到主机result_root/<batch_id>/<index>.mp4，主机再次检查哈希、ffprobe及签发时的完整内容身份，更新原startup_contents.production_status=READY、保持NOT_SCHEDULED，回执标识READY_TO_PUBLISH / STARTUP_READY_TO_PUBLISH。不会创建PublishJob；这只是导出验收，不连接小V猫。本模式成功回执为COMPLETED，替代下面旧版EXPORTED_AWAITING_PUBLISH_PARAMETERS边界。生产库原字段约束不改。

这是独立的增量交接模块，不替换起号合成器、权限服务或已验证的小V猫 Worker。

## 已实现边界

服务器首次启动记录所有已有批次为排除基线，仅领取激活后新生成、完成且在原 operations.db 有员工归属/content_id 的 STARTUP 草稿。只读业务库，任务状态保存在自己的 runtime/server/render_jobs.db。

经局域网 8766 端口传送草稿 JSON、封面和它明确引用的媒体，每文件 SHA256 验证；不扫描或同步整个素材库，不传账号库、密码、Cookie、token。接口只允许配置的服务器/2060S IP；这是受限可信局域网 HTTP，非面向互联网的认证/加密服务。

任务机按业务正式draft_name安装草稿副本，修改副本本地路径和5.9列表metadata，不改变时间线或服务器草稿。使用现有固定版本剪映5.9导出库，和小V猫共用桌面互斥锁。账号绑定任务输出到D:/JianyingRenderWorker/Exports/startup/<batch_id>/<draft_name>.mp4；旧非账号绑定任务保留索引MP4路径，已有文件不覆盖。ffprobe验证H.264、AAC（有音轨时）、MP4、分辨率、帧率、时长及非零文件，生成带员工/内容/批次/序号/组合签名的回执。

成功状态是 EXPORTED_AWAITING_PUBLISH_PARAMETERS，不是 PUBLISHED，也不冒充旧待发布池的 READY。生产库尚不写入远程路径；当前不创建真实 PublishJob、不启动发布轮询、不开启真实发布开关。下一阶段必须通过现有员工→稳定分组→稳定账号权限服务校验用户确认的发布参数，再实现待发布成片与既有 Worker 的正式入队桥接，不能绕过权限直接写队列。

## 启动与诊断

server.example.json 和 agent.example.json 是本局域网的无凭据部署模板。安装时使用当前用户交互式计划任务；不保存密码、不以 SYSTEM 操作桌面，不启动/重启线上寻帧。

服务器（项目根目录）：

```powershell
.\.venv-cuda-test\Scripts\python.exe -X utf8 -B -m startup_render.server --config startup_render/server.example.json --scan-once
.\startup_render\install-task.ps1 -Role server -Python D:\video_search_tool\.venv-cuda-test\Scripts\pythonw.exe -Config D:\video_search_tool\startup_render\server.example.json
```

2060S（项目根目录）：

```powershell
D:\JianyingRenderWorker\venv\Scripts\python.exe -X utf8 -B -m startup_render.agent --config startup_render/agent.example.json --once
.\startup_render\install-task.ps1 -Role agent -Python D:\JianyingRenderWorker\venv\Scripts\pythonw.exe -Config D:\Projects\XunZhen\startup_render\agent.example.json
```

`--once` 有领取任务语义，不是只读检查。只读状态用服务器 http://192.168.1.126:8766/health，以及任务机 startup_render/runtime/agent/health.json。详细错误在两端 runtime 中的日志和回执。停止新增监听可用 Stop-ScheduledTask -TaskName XunZhen-Startup-Render-server / XunZhen-Startup-Render-agent；不会停止线上寻帧或小V猫服务。不要在正在导出时强制停止，除非需要中止操作。

## 保守失败规则和未验收项

- 领取/处理状态持久化；断线重传回执，不重导出。中途崩溃、超时、已有输出、未知窗口停止为 NEEDS_MANUAL，任务机停止消费后续任务。服务端准备中崩溃的任务不会自动重做。
- 既有失败草稿的隔离自动导出已实测通过；修复后仍须由用户生成全新单条，重新验收主机→任务机→回传→READY完整链路。隔离通过不是生产端到端PASS。必须保持2060S当前用户登录且桌面解锁，不要同时手工编辑剪映。
- 剪映只接受指定5.9 EXE/SHA256/签名/进程路径。仅在确认安全首页、无未知弹窗时正常关闭并重启刷新；不关闭用户正在编辑/保存/导出的窗口，不强杀。真实草稿名未发现时停止，不盲点。
- 外部目录型特效/贴纸包暂不递归复制，报告 EXTERNAL_RESOURCE_DIRECTORY_REQUIRES_MAPPING；须在实际新草稿上确定最小资源迁移范围。旧版剪映与服务器草稿兼容性仍需实片核验。
- 现有目标机发布Worker的真实登录/账号权限数据、独立话题、定时策略等尚需结合本次参数验证，不能据此宣称“无人值守真实发布已打通”。

## 隔离测试

`python -X utf8 -B -m unittest startup_render.test_handoff -v`

测试使用本模块runtime/tests下独立夹具和模拟导出器，覆盖新旧批次、归属、路径防逃逸、SHA256、只读业务库、不可覆盖、回执身份、断线/中断不重做及错误停机。没有任何真实桌面或发布操作。
