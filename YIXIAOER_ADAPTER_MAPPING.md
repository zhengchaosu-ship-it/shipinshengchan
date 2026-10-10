# YIXIAOER_TECHNICAL_POC_PHASE0：Adapter 与状态映射

日期：2026-10-05（Asia/Shanghai）。固定commit：`a2722c6095f57abf2e345dca637bdded44fa34df`。只实现独立离线壳，未注册到8502，未修改PublishPlan/PublishJob/Server Worker/2060 Render。

## 与现有发布层的关系

当前代码是 `xiaovcat_adapter.publisher.Publisher → PublishStateMachine/PublishDriver` 与 `local_ui_publisher`，并有生产dispatcher；本轮检查未找到一个可直接继承的字面`class PublisherAdapter`。因此下面按用户要求的五个能力口构建 **YixiaoerPublisherAdapter**，不能声称已能无修改替换现有driver。既有PublishJob枚举还有PENDING/PREPARING/SUBMITTING/NEEDS_MANUAL等；本轮用户指定的七态只用于POC映射，不扩展生产枚举或Schema。

| 方法 | 离线壳所做操作 | 边界 |
|---|---|---|
| list_accounts() | 构造账号GET，解包兼容列表容器，按显式分页信息读fixture | 不伪造正式账号在线；mock账号标记独立 |
| upload_video() | 使用VirtualVideo内存占位bytes，构造签名GET和PUT并记录到FixtureTransport | 不读取nominal_path；拒绝真实路径输入；24字节不是有效可播放视频 |
| create_publish_job() | 构造官方wire body；消费mock taskSet回执；演示内存意图台账 | 只返回SUBMITTED；scheduledTime存在也不提前标SCHEDULED_QUEUED |
| get_publish_status() | 查询taskSet/tasks fixture，保存每账号taskID/raw stageStatus/errorMessage/openUrl候选 | 不把供应商成功当抖音已公开；作品ID和审核仍None/UNKNOWN |
| get_video_metrics() | 构造contents/overviews GET，保留raw指标 | 作品ID关联UNKNOWN，不凭标题自动归因、不把缺值补0 |

代码：[adapter.py](publisher_poc/yixiaoer/adapter.py)，fixture：[responses.json](publisher_poc/yixiaoer/fixtures/responses.json)，测试：[test_adapter.py](publisher_poc/yixiaoer/test_adapter.py)。没有生产模块import、网络client、真实凭证环境变量、业务素材读取或DB连接。构造函数只接受精确FixtureTransport类型，不能注入真实HTTP transport。

## 真实状态证据与七态映射

关键来源并非README：[cmd/publish_delete.go:240](https://github.com/yixiaoer888/yixiaoer-skill/blob/a2722c6095f57abf2e345dca637bdded44fa34df/cmd/publish_delete.go#L240) 的展示逻辑把 `stageStatus=success` 显示为“发布成功”，`doing/pending`显示“处理中”，`fail/failed`显示“发布失败”；`taskStatus=deleted`覆盖为已删除。这里是客户端解释，不是完整服务端枚举或抖音审核协议。`internal/api/query_test.go`还有仅`status:"success"`的模拟数组响应，不能将测试响应当服务端实值。

| 我们的状态 | 可见供应商状态/事实 | 本轮映射 | 不能推断的事项 |
|---|---|---|---|
| QUEUED | 无独立供应商队列状态契约 | 供应商对应 **NOT_SUPPORTED**；只可由我们本地意图表达，壳不写生产队列 | pending未明确是排队；源码展示为处理中 |
| UPLOADING | GET签名后PUT执行的本地动作 | 供应商任务状态对应 **NOT_SUPPORTED**；未来可用本地上传进度，壳只记录请求 | PUT成功不等于任务创建，更不等于发布 |
| SUBMITTED | POST得到可解析taskSetID | **SUBMITTED**，仅表示供应商受理并有追踪ID | HTTP200无ID是结果不确定，不是确定未创建 |
| SCHEDULED_QUEUED | scheduledTime是请求字段，无明确“已接受定时”状态 | 供应商对应 **NOT_SUPPORTED**（公开契约层）；必须等可靠排期确认后才能映射 | 不能仅凭字段存在或POST成功设置 |
| PROCESSING | stageStatus=doing/pending | **PROCESSING**（供应商阶段处理中；语义局限见上） | 是否上传、平台审核、队列等待无法区分 |
| PUBLISHED | stageStatus=success，可能伴随openUrl | **NOT_SUPPORTED**作为已确认抖音终态；壳暂记PROCESSING＋requires_manual | 不知道是否审核通过、实际公开存在、作品ID及URL有效性 |
| FAILED | stageStatus=fail/failed，errorMessage候选 | **FAILED**，限定供应商阶段失败 | 不能保证这是抖音最终拒审；不能直接自动重发 |

`stageStatus=success`被壳保守暂留PROCESSING，附`provider_stage_status=success,review_status=UNKNOWN,publication_verified=false,requires_manual=true`，这是“待平台证据”的适配策略，不是在宣称供应商仍运行。未知/缺少stageStatus、只给status=success、已删除返回status=None和requires_manual；不能把无法映射的状态硬塞FAILED。将来若服务端明确新增审核和公开终态，再补映射并测试。

`task.id` → provider_task_id；`taskSetId` → provider_task_set_id；`task.openUrl` → **candidate_video_url**；抖音真实作品ID → UNKNOWN。不能把task.id、platformAuthorId、mediaId或publishContentId写成external_work_id。不能从未知格式openUrl字符串截取数字充当已核实作品ID。

多账号逐task保留状态，不能一个成功覆盖全taskSet。task与platformAccountId是否必返对应关系UNKNOWN；缺关联时不靠数组顺序/同名昵称做绑定。作品指标和task之间稳定join字段UNKNOWN；get_video_metrics只作原始数据查询壳。成功有ID/URL且证实抖音公开或其定义的可靠终态，才能进入PUBLISHED，相关凭据本轮不存在。

## 幂等与提交超时

固定源码未找到client idempotency key、Idempotency-Key header、按client_request_id精确查询机制。结论是 **NOT_SUPPORTED_IN_PUBLIC_CLIENT_CONTRACT**；服务端是否另有机制UNKNOWN。`publish --dry-run`返回的`requestHash`只做本地请求一致性检查，Publish调用未发送该hash作为幂等键；`taskSetId`字段是已有草稿发布，不证明“自选ID的新建任务幂等”。不要发一个自造字段期待供应商去重。

已支持查询已有taskSet：知道ID可调用`/v2/taskSets/{id}/tasks`；不知道ID可查`/v2/taskSets?size=...&platform=...&status=...`。但记录列表完整分页、排序、唯一指纹、索引一致性未确认。网络超时后，“列表没看到”不能证明未创建。源码自己的missing-ID错误也建议先query records，而不是盲重试。[Publish回执处理](https://github.com/yixiaoer888/yixiaoer-skill/blob/a2722c6095f57abf2e345dca637bdded44fa34df/internal/api/publish.go#L38)、[requestHash实现](https://github.com/yixiaoer888/yixiaoer-skill/blob/a2722c6095f57abf2e345dca637bdded44fa34df/internal/workflows/publish/dryrun.go#L118)。

设计字段（**不修改正式数据库**）：

| 字段 | 定义及约束 |
|---|---|
| provider_request_id | 我们生成的不可变请求身份；同一个业务任务唯一，恢复时复用；不当成供应商已支持的idempotency key |
| provider_task_set_id | 首次成功回执立即持久化，非空时禁止重POST，只恢复查询 |
| provider_task_id | 详情回收后逐账号保存；多账号应为子记录，不能用一个ID覆盖所有账号 |
| submit_attempt_count | 发送前与提交意图一起原子持久化；超时后不归零、不自动增加再次发送 |
| payload_hash | 固定账号ID、素材SHA256、完整wire body、UTC排期、通道的摘要，防相同request_id换内容 |
| reconciliation_state | INTENT_RECORDED / ACKNOWLEDGED / SUBMIT_RESULT_UNCERTAIN / MANUALLY_RECONCILED；属于控制标记，不新增七态的“已发布”含义 |

未来安全流程：

1. 校验素材唯一规则、账号和时间；对同一request_id/账号加进程锁。将意图、完整body hash、attempt=1先持久化，再发一次POST。落盘失败不能提交。
2. 已知taskSetID只GET；重复调用读取相同回执，不POST。相同request_id不同payload拒绝。
3. HTTP超时、连接中断、HTTP200无ID、无法明确判定是否受理的错误，持久化SUBMIT_RESULT_UNCERTAIN并停止自动POST；进程重启仍阻止。不能把5xx/429一般重试策略直接套到创建任务。
4. 只读query records寻找候选，再详情核对账号、素材key/hash、排期、body指纹等。仅标题/时间相近、列表为空、用户看不到任务均不足。供应商不返回足够关联字段时转人工对账，保留意图；不得自动放行重发。
5. 只有供应商明确证明原请求未受理且新的提交得到授权后，才能增attempt再提交；并保留历次request/receipt。不能保证在无幂等、无可靠对账时做到自动exactly-once。

此策略能以“提交不确定即停”控制自动重复，但无法同时保证不漏发和自动恢复。**可自动对账恢复的防重复闭环尚未成立**，Gate F不能据一个本地hash就判完整通过。

本轮内存ledger只演示同进程防重复，不持久化、不承诺并发安全或重启恢复。未来持久化设计可先用隔离POC journal验证，再按授权做生产迁移；本轮没有新DB、正式Schema或修改PublishJob。测试验证一次受理复用、payload冲突拒绝、超时/无ID/503/业务错误后第二次调用不再POST；这不等于已经具备生产恢复能力。

## 验证步骤

在 `D:\video_search_tool\publisher_poc\yixiaoer` 使用现有Python环境：

```powershell
& D:\video_search_tool\.venv-cuda-test\Scripts\python.exe build_examples.py
& D:\video_search_tool\.venv-cuda-test\Scripts\python.exe -m unittest -v test_adapter
```

14项全部通过，测试期间socket被patch为NETWORK_FORBIDDEN；固定官方schema验证样例、毫秒/时区等价、立即模式省略scheduledTime、local必需clientId、同平台两mock账号、上传PUT不带网关API Key、未知状态保留、success不标PUBLISHED、缺作品join不归因。jsonschema为既有环境依赖，未安装任何包。

手动只读验收：打开requests.http.txt与两个JSON样例，检查时间戳、accountForms逐账号字段、视频/封面key一致、原始Authorization格式、没有action或虚构幂等字段；打开fixture确认SYNTHETIC标记。不要执行厂商CLI validate/dry-run，因为它们可有远程账号/通道检查。本POC不启动8501/8502，也不运行可能触发UIA的生产集成测试；服务路径完全未改，使用隔离tests和源文件hash验证边界。
