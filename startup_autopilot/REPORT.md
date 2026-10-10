# STARTUP_AUTOPILOT_FOUNDATION_READY

2026-10-06，Asia/Shanghai。完成本轮指定的架构设计、migration设计、UI原型、状态机、DailyPlanner领域实现、Metrics schema、Affinity模型和隔离Shadow Mode。

**真实Autopilot未开启。** 没有在8502部署新按钮，没有注册每日执行服务，没有真实生成/渲染/上传/发布，也没有新增正式授权、Plan或Job。本轮新增生产publish=0；既有生产服务持续运行。

## 交付

| 内容 | 文件 | 本轮状态 |
|---|---|---|
| 完整架构、状态图、权限与生产接线方案 | ARCHITECTURE.md | 设计完成 |
| StartupProfile、二次确认、状态机、管理覆盖 | models.py | 隔离可执行 |
| 每日固定槽、双预算、疲劳/组合去重、Shadow | planner.py | 隔离可执行 |
| 2/24/72h契约、NULL能力标记、官方证据字段decoder | metrics.py | 隔离可执行，无真实collector |
| 账号归一化、Bayesian收缩、24h/72h版本修正 | affinity.py | 合成数据验证 |
| 15张新增表、索引、不可变证据保护 | migrations/001_foundation.sql | 仅隔离库迁移通过 |
| 隔离迁移、Profile/Shadow存储及并发幂等 | storage.py | 拒绝生产库路径 |
| 员工设置/二次确认/暂停结束/管理员偏好预览 | prototype.html、UI_DESIGN.md | 离线交互原型 |
| 显式单次演示与只读生产核验 | demo.py、audit_readonly.py | 无watcher/循环任务 |

目录独立新增，不覆盖正在进行的8502员工UI简化工作。原有Render/Publish/检索模块未修改；HANDOFF追加本轮交接。修改前已保留备份。

## 员工第一次开启

下一阶段接线后的入口设计：正常员工登录8502 → 工作区“账号” → 可操作的STARTUP账号 → “自动起号” → 账号设置。业务账号沿用既有account_id及员工权限，不创建新用户系统。

一次设置每天最多5条、等量固定时间槽、账号拼接模板/允许素材池/时长/固定及禁止素材、目标粉丝、20条学习阈值。点“开启自动起号”，二次确认明确说明长期每天自动安排、直到暂停/结束，冻结完整配置和模板/policy内容哈希，记录确认员工和时间。配置变更须重新确认。

当前prototype.html中的“确认演示”只改演示页面状态，不是生产授权；上述8502真实入口尚未上线，不需要员工现在操作8502。

## 每日系统如何运行

未来由正式服务器每日北京时间21:30规划翌日。首先重验账号权限/在线状态、Render/Provider健康、长期授权与提交预算，再读取所有生成保留、RenderJob、READY内容、正式Job和已入平台作品，按unique content计占位，只补空缺固定槽。

每账号北京自然日最多5条。已入平台、实际公开、渲染中、READY、intent及提交不确定都保守占位。未来真正自动链继续调用现有Content→2060S RenderJob→媒体验证→PublishPlan/PublishJob→Yixiaoer LOCAL。任何count>=1不自动再次POST；超时先对账。Foundation现在只返回“如果运行会选什么”，不执行该链。

排期必须>=执行时now+2h15m且<=14天；AI不改固定发布时间。配额拒绝、离线、池不足或冲突进入需要处理，不无限重试。实际提交日预算包含POC及人工任务；它与作品排期日5条额度分开。供应商官方limit/重置口径仍UNKNOWN。

## 前20条怎么选

有效样本只计有真实公开证据的作品，待发布作品不计。<20条采用固定业务规则与低使用次数优先的受控轮换，保持Slot顺序及业务含义，只在允许池选择。尊重BLOCK/LOCK/PREFERRED；固定素材不能绕过24h疲劳。

同时保护同素材24h不重复、7天次数上限、相邻核心素材不重复、有序完整组合30天不重复。未来已保留素材也参与检查；固定素材与每天5条冲突时提示配置问题，不偷偷放宽。

## 20条后怎么学习

>=20条进入LEARNING；有足够可靠评分数据时进入AUTOPILOT。按同账号、同反馈窗口的历史baseline归一化，不用不同账号绝对播放量比较。默认权重在JSON配置：涨粉35%、播放20%、完播20%、分享10%、评论10%、点赞5%。

24h主学习，72h追加修正；同作品不会因三个窗口被当作三个独立样本。prior=20、中性偏好1、单作品剪裁保护低样本。素材偏好、样本数、coverage、全部score字段和算法版本可解释；历史评分与原始指标不可改写。

成熟选择每Slot按70%高评分、20%中等/潜力、10%探索分配，并降低近期高频素材权重。数据不足时仍受控轮换，不能把“达到20条”误写成“数据已足够”。

## 数据来自哪里

优先接Yixiaoer真实只读统计。当前decoder根据已有官方响应样本映射播放、点赞、评论、分享、收藏字段；明确返回0保留0，缺失保存NULL/NOT_RETURNED。涨粉归因、完播/停留未实现映射，为NULL/NOT_SUPPORTED，不猜值。

这不等于验证了供应商所有指标接口。真实collector及新鲜度验收尚未上线。接口契约允许未来DouyinOfficialMetrics。账号粉丝总数单独用于进度；账号总涨粉不能直接伪装成每作品涨粉。

默认完整权重下，当前这几种统计最多贡献45%覆盖，低于60%学习门，因此维持LEARNING。后续需验证更多数据或人工确认新policy，不能静默把剩余权重重分配。

2h/24h/72h基于真实公开时间；scheduledTime、provider提交时间和CSV创建时间都不能替代。只有用户首次可见的近似时刻则明确标APPROXIMATE，暂不自动学习精确窗口。

## 达标后如何结束

有可信粉丝数据才显示进度。达到目标提示“已达到起号目标”，不自动FINISHED。员工点击“结束起号”，选择“已排期继续发布”或“取消尚未进入平台的任务”，确认后停止新增。默认保留平台待发布作品。第二项未来须在事务再次证明count0/无intent/无供应商标识才能取消，Foundation没有真实取消功能。

暂停仅停止新增，已SCHEDULED_QUEUED继续保留。恢复按当前样本/数据重算阶段并重新检查权限和硬门。

## 验证证据

`runtime/foundation_20261006/FOUNDATION_TESTS.log`：**57/57**通过，含权限/二次确认/配置篡改拒绝、日额度及多阶段同content去重、实际重复Job拒绝、UTC/北京时间等价碰撞、失败未知占位、双预算、固定素材冲突、前后素材疲劳、邻接核心保护、原组合去重、跨账号拒绝、NULL与真实0、窗口到期、baseline隔离、单次高播放收缩、72h不重复计样本、并发同快照唯一、不可变证据。

`regression.log`：**424/424**既有Yixiaoer/PublishPlanner/StartupPipeline/Render相关隔离测试通过，237.552秒。日志中的模拟导出失败、TRANSFER_HASH_MISMATCH为失败路径测试，不是生产新失败。没有启动真实渲染或发布。

10个Python文件语法通过。`UI_LOGIC.json`：18项离线DOM替身事件断言通过，网络调用0；**不构成浏览器视觉验收**。浏览器工具安全策略拒绝file:本地HTML协议，停止该浏览器路径，未使用替代浏览器/服务绕过。请后续本地查看原型并验视觉，再接8502。

完整现有operations.db只读复制到TEMP fixture，新增迁移后所有原表行指纹保持一致、quick_check=ok、profile新增0。原生产库未执行迁移。

`SHADOW_DEMO.json`明确synthetic_fixture=true：翌日5个唯一组合，duplicate0，各素材来自对应允许池，render0/publish0/submit0。该演示不冒充丙曜真实AI偏好。

## 现有28条与服务保护

生产Plan：YIXIAOER-PRODUCTION-320f095f-a5c4-45b7-a8e2-1e5515407c86；丙曜business account_id=1621131832863931。

| 北京日期 | 真实已入队 | 保守占位 | Shadow新增 | 原因 |
|---|---:|---:|---:|---|
| 10/06 | 5 | 5 | 0 | 当日已满 |
| 10/07 | 8 | 8 | 0 | 既有历史任务超过新5条上限 |
| 10/08 | 8 | 8 | 0 | 既有历史任务超过新5条上限 |
| 10/09 | 1 | 7 | 0 | 6条FAILED未获本轮释放授权，继续保守占位 |

没有把新上限追溯成取消旧任务；6条FAILED不重试、不补发。22条SCHEDULED_QUEUED未标PUBLISHED。

`BEFORE.json/AFTER.json`：生产schema SHA不变、sap_表0、Plan7/Job269/providerJob31/Content41均不变；28条hash、ID、排期、intent、count、requestHash不变，submit count合计28、publish_once工件28均未增加。authorization count仍1。完整性比较全部true。

`SERVICES.json`及AFTER健康证据：8502原PID30784/29992、HTTP200；Publisher原47988/48008、正式计划任务Running；蚁小二原6进程、Session1；Render服务22276/20608不变，实际LAN绑定192.168.1.126:8766认证GET/health返回200，2060S心跳新鲜/IDLE。最初仅loopback探测被拒连接，改读既有bind地址后只读健康正常，未重启服务。没有新增后台监控/Task Scheduler/心跳。

## 尚需真实验证与下一步

待验证：实际允许素材池稳定登记、媒体时长/剪辑语义、真实公开时刻和各指标新鲜度/口径、每作品涨粉与完播数据、完整投稿预算可观测性、素材Affinity效果与因果混淆、真实UI视觉和权限接线、长期授权撤销、自动保留事务/跨进程崩溃恢复。当前不承诺“AI能提高涨粉”，不宣称已经无人值守自动生产。

最小安全上线：先一个账号、daily_limit=1、小样本允许池、只接8502账号配置与Shadow页面，关闭真实dispatch，多个每日快照对比现有规则。旧>5占位日不补量。再接真实只读公开/指标证据；单独授权一次真实Content→2060S→LOCAL验收。通过后才逐步放开长期业务授权和最多5条，最后启用指标充分的自适应选择。

本轮完成后停止，无需用户现在开启或确认生产计划。
