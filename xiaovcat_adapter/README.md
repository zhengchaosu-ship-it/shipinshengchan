# 小V猫发布与数据回流适配器 V0.1

## 起号成片接线 V0.1（2026-10-02）

独立 `startup_pipeline/` 已实现员工归属的内容记录/READY发布池、单条或批次携带MP4进入原Planner、模板、确认生成原PublishJob和稳定ID sidecar、防重复与文件保护。只模拟、不派发，详见 [../startup_pipeline/README.md](../startup_pipeline/README.md) 和 [results/startup_pipeline_v01/REPORT.md](results/startup_pipeline_v01/REPORT.md)。158/158项测试通过，Worker及受保护核心文件哈希未变。

最终 `STARTUP_AUTO_PUBLISH_PIPELINE_PARTIAL`：现有合成输出剪映草稿，没有自动MP4导出/路径映射；尚缺至少3条真实起号导出成片及批次对应，未创建生产测试任务。苏政超仍绑定真实STARTUP账号，但现有同步快照过期，必须走已有只读同步刷新，不能伪造在线。隔离三视频09:00/10:00/11:00验收不是生产苏政超验收。V0.4现有submit脚本只接受先前固定一条任务，不能当通用Worker消费者；本轮未改/未调用。新PublishJob只保存在NEEDS_MANUAL模拟状态，不消费队列，real_publish_enabled=false。

## 最新桌面验证（2026-10-01）

V0.3 独立本机 Worker 已真实完成提交前 dry-run，结论 `XIAOVCAT_DESKTOP_WORKER_PASS`。UIA 主通道 + KEYBOARD_ASSISTED 唯一 fallback，`real_publish_enabled=false`，无真实发布。详情见 [desktop_worker/README.md](desktop_worker/README.md) 与 [results/desktop_worker_v03/REPORT.md](results/desktop_worker_v03/REPORT.md)。根目录 `小V猫自动化测试.bat` 可运行；当前 POC 表单保留，复跑前需自行保存/清理。

以下 V0.1 原 `ui_driver.py` 的空选择器/未验证描述是历史状态：V0.3 使用独立、已验证的直接 UIA 实现，尚未把它接入 V0.1 队列或服务；不能据此声称旧队列自动发布已可用。

这是一个与寻帧、FAISS、DINO、Speech、CLIP、合成与分析代码隔离的发布层。它只使用自己的 `operations.db`，不会连接或修改 `video_index_fixed.db`。

## 当前安全边界

- `real_publish_enabled` 默认为 `false`。状态机在 `VALIDATE_FORM` 成功后返回 `DRY_RUN_READY`，不点击最终发布。
- 每个步骤有独立超时值，默认自动重试 1 次，再失败会写入 `NEEDS_MANUAL`。
- 失败时保存当前步骤、错误和可用截图；不死循环。
- 队列数据结构支持 1～50 条入队，但 V0.1 实机任务硬限制为最多 3 条。
- 不读取密码、Cookie 或 token，不解密凭证，不修改小V猫安装目录。

## 已实现

- `PublishJob` 统一数据结构，含 NOW/SCHEDULED、外部作品映射、错误信息、`composition_id` 和 8 模块素材 ID 预留。
- SQLite 表：`publish_jobs`、`published_content`、`performance_snapshots`、`accounts`、`state_events`。
- 完整发布状态机、超时/重试/错误落库、dry-run 最后闸门。
- Windows UIA 驱动边界（可选 `pywinauto`），选择器未实机验证时明确失败，不猜坐标。
- CSV/XLSX/XLS 回流，支持中英文列名和播放/点赞/评论/分享/收藏快照。
- 优先用作品 ID 映射；取不到时才用账号+标题+视频文件名的唯一匹配。
- `XiaovcatService` 作为 Streamlit 或未来本地 HTTP Worker 的统一调用边界。

## 独立分组规划器 V0.1（2026-10-01）

寻帧8502“工作区 → 发布管理”已接入独立 `publish_planner/`。支持本地管理员/员工登录、多业务分组绑定、真实只读UIA同步、按日计划预览、确认生成本地测试PublishJob和幂等防重复。我的账号分起号/带货；员工管理分别选择STARTUP/COMMERCE组，每类可多个，角色明确保存，不按组名推断。管理员可看全部启用账号；业务计划只允许已明确分类的对应组账号，后端越权返回 `ACCOUNT_PERMISSION_DENIED`。

权限链为employee_id → employee_group_bindings(group_role) → 稳定group_id → 稳定account_id。employees旧单组列保留但不用于授权。PublishPlan新增business_type；起号自动合成提供锁定STARTUP的已有MP4计划入口，带货COMMERCE有统一计划UI与production.py接口；既有带货/8模块代码无发布步骤页面，尚未接线，不冒充已集成。

最新收尾已通过原生 DevTools Elements 公开无障碍DOM读取十组真实 `data-row-key`，精确名称/数量回读后两次重新进入页面，ID完全一致；不执行Console脚本/CDP/IPC/网络接口，不读凭据，不改Worker。独立 `group_identity.py`处理DevTools平铺aria level及零宽文本，避免原探测器40层深度截断。十组真实ID已落库：苏政超起号339642/带货339644、黄明贵起号339648/带货339652、何华俊起号339653/带货339655、凌荟璇起号339658/带货339659、黄小慧起号339660/带货339661。

当前真实UI同步10个自定义组/2个在线抖音号（丙曜1621131832863931与62288252897的3031801633454512），均关联group_id339642，其余9组0账号；此前3个离线ID及历史记录保留不删除。用户显式选择新增苏政超/login suzhengchao，已绑定339642/STARTUP和339644/COMMERCE，管理员表单及真实员工登录回读通过。起号生产入口只返回两号，COMMERCE通用计划页返回0且不能创建；越权/跨类型后端返回ACCOUNT_PERMISSION_DENIED。无真实带货账号，不以隔离夹具冒充现场验收。最终仍为 `XIAOVCAT_GROUP_PLANNER_PARTIAL`，仅剩既有带货/8模块生产页入口未定位，已请求具体网址/文件/启动方式；不得把统一service/计划页验证当作该生产页接线完成。

operations.db已一致性备份并执行001/002增量迁移，原始E2E记录保留。4条先前本地测试任务保留且重复新增0，NEEDS_MANUAL+PLANNER_TEST_ONLY，未进入真实队列；real_publish_enabled始终false，Worker所有非缓存文件SHA256未变。验收、两份迁移结果、测试记录、源/页面截图在results/group_planner_v01/。本轮不运行真实发布或恢复任何监控。

最新118项回归全部通过（规划器/多分组/组件62、适配器9、原Worker31、原寻帧UI16），新增10项源DOM身份解析测试，原算法未改。收尾证据在results/group_planner_finish_v02/，含两次LIVE_SYNC、GROUP_ID_STABILITY、RECONCILE、REAL_PERMISSION_CHECK、ACCEPTANCE/REPORT与真实网页截图；写入前备份operations.db.finish-v02-20261001_204823_371393.bak，原任务/作品/回流/员工/计划明细逐行保留，新PublishJob数0。新员工本地初始密码仅在ACL受限LOCAL_EMPLOYEE_LOGIN.private.json中。隔离回归 `python -X utf8 -m publish_planner.verify`；本轮真实绑定/预览验收 `python -X utf8 -m publish_planner.finish_acceptance`，不派发Worker、不发布。先前V0.1结果和四条测试任务作为历史保留。

同步需要已登录、管理抽屉关闭、无未知弹窗、账号表无筛选/不分页且账号标签完整。已有用户DevTools、焦点/布局变化、组匹配不唯一或数量不一致即停止人工处理。同步器仅打开并关闭自己的原生Elements读取通道，不关闭小V猫；不允许最终业务按钮。

## 分组接入身份约束

- 优先同步小V猫稳定 `group_id`，使用该源ID作为 `xiaovcat_group_id`；`group_name` 仅作为展示字段。
- 员工绑定必须引用 `xiaovcat_group_id`，不得引用 `group_name`；账号成员及权限关系通过稳定ID关联。
- “员工A组”改名为“张三运营组”只更新展示名称，保留分组ID、员工绑定及账号权限关系，禁止按新名称新建或重绑。
- 仅在确认小V猫不存在稳定 `group_id` 时，允许生成并持久化本地稳定ID，并维护本地ID到source group的映射；改名不得重新生成ID，映射不得仅以名称为身份依据。
- “未取得ID”不能直接判定为“没有稳定ID”；源组映射有歧义时转人工核对，不自动猜测或迁移权限。

历史Account.group_name仍仅展示；独立规划器多组关联表的group_id保存真实源稳定身份，不保存名称。真实十组source group映射已建立，权限查询不按名称/后缀判断。本约束不改变既有发布控制链路或单任务验收结论。

## 本机命令

请使用项目 `config.json` 里配置的 Python：

```powershell
& "<python_executable>" -m xiaovcat_adapter init-db
& "<python_executable>" -m xiaovcat_adapter discover --output xiaovcat_adapter/results/discovery.json
& "<python_executable>" -m unittest discover -s xiaovcat_adapter/tests -v
```

## 未验证的真实 UI

本轮 Windows UI Automation 通道没有暴露原生应用窗口，因此 `config.json` 中的控件选择器故意保持为空。需在可读取 UIA 控件树的环境中，对发布页、选视频、账号、标题、文案、提交和成功状态逐一采集并验证 `automation_id` / `control_type` / `title`。在此之前，真实 dry-run 会安全进入 `NEEDS_MANUAL`，不会误点。
