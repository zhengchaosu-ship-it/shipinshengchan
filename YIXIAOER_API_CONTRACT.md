# YIXIAOER_TECHNICAL_POC_PHASE0：API 契约核验

日期：2026-10-05（Asia/Shanghai）。结论：**YIXIAOER_PHASE0_NO_GO**。本报告核对官方客户端源码和 JSON Schema，不是授权接口实测。

## 固定版本和证据范围

- 官方仓库：[yixiaoer888/yixiaoer-skill 固定版本](https://github.com/yixiaoer888/yixiaoer-skill/tree/a2722c6095f57abf2e345dca637bdded44fa34df)。commit：`a2722c6095f57abf2e345dca637bdded44fa34df`。
- `internal/domain/response.go` 的 `SkillVersion` 为 **3.2.26**；以 commit 为准，不安装 npm latest，不执行厂商 CLI。
- 已从 GitHub codeload 获取固定 commit 源码，并用 GitHub commit API 核对 SHA；留存 ZIP、解压源码和 SHA256。记录：[provenance.json](publisher_poc/yixiaoer/evidence/provenance.json)。该仓库不包含蚁小二服务端、Windows 客户端完整发布实现或抖音权限凭据。
- 默认 base URL：`https://www.yixiaoer.cn/api`，来源 `internal/config/config.go:17`。下文 path 均相对此 URL，不能遗漏 `/api`。
- 官方参考文档有落后于代码的内容：账号文档称默认 size=20，实际 CLI/Go 默认 **50**；作品/账号 overview 文档称无独立子命令，但 `cmd/query.go` 已实现。表单 schema、preflight、wire builder、API client 优先于说明文字。README 未被当作完整契约。
- UNKNOWN 表示证据不足；NOT_SUPPORTED 表示固定公开接口层没有可用字段/状态/入口，不代表供应商内部永久不支持。所有 mock 都为 `SYNTHETIC_NOT_VENDOR_CAPTURE`。

## 公共认证、返回和错误

**认证**：网关请求为 `Authorization: <apiKey>`，**没有 Bearer 前缀**；GET 也设置 `Content-Type: application/json`。来源：[client.go](https://github.com/yixiaoer888/yixiaoer-skill/blob/a2722c6095f57abf2e345dca637bdded44fa34df/internal/api/client.go#L72)。API Key 是蚁小二凭证，不是抖音 OAuth access_token。有效期、scope、刷新协议、角色到接口权限对应关系：UNKNOWN。

成功常见 envelope：`{"statusCode":0,"data":...}`。Go 客户端兼容缺少数字 statusCode 的裸对象/数组；HTTP 2xx 中数字 statusCode 非零仍报业务错误。`message/code` 可为字符串、数字或数组。正式服务端的严格 OpenAPI response schema：UNKNOWN。

网关非 2xx 为错误；源码明确识别 401，提示 API Key 缺失/无效/过期，保留 `httpStatus/code/body`。HTTP 200 非零业务状态码亦报错。**供应商逐接口错误码全集、429/Retry-After 契约、每日额度/QPS/并发/批量上限：UNKNOWN**。CLI 的 `remote_response/remote_upload/remote_error` 等属于客户端错误，不冒充服务端错误码。网关客户端 timeout=60秒；PUT 使用另一个没有显式 Timeout 的 `http.Client{}`；都不能据此推断 SLA 或限流。

下表“公共错误”指上述已核对的解析行为；每个接口的具体错误枚举仍为 UNKNOWN。

## 核心接口

| method / path | 认证 | request schema；必要字段 | 可选字段 | response schema | 错误码 | 分页 | 限流 |
|---|---|---|---|---|---|---|---|
| GET `/v2/platform/accounts` | 原始 API Key | query `page:int>=1,size:int>0`，CLI 必定发出；HTTP 服务端必填性 UNKNOWN | `platform:string`，抖音用中文 `抖音`。CLI 的 name/status 是取回后过滤；其他文档筛选参数未在该 API 方法实现 | `data` 可为数组或分页对象；列表兼容 `data/list/records/items/rows`。账号 `platformAccountId` 或 `id` 是 vendor ID；其他字段见下文 | 公共错误；接口专属 UNKNOWN | CLI 默认 page=1,size=50；`totalPage`，或 `totalSize+page+size` 判下一页；缺少元信息就停止，不凭页条数推断 | UNKNOWN；文档 size 最大1000是页容量声明，非 QPS，代码未硬限制1000 |
| GET `/storages/{bucket}/upload-url` | 原始 API Key | path `bucket:string`，默认 `cloud-publish`；query `fileKey:string,contentType:string`，MP4为`video/mp4` | `size` 十进制字节数，文件非空时发送；其他 bucket 名/配额 UNKNOWN | `{"statusCode":0,"data":{"serviceUrl":string,"key":string,...}}`；两字段缺失视为错误；其他字段 UNKNOWN | 公共错误；无serviceUrl/key：客户端 remote_response；业务枚举 UNKNOWN | NOT_SUPPORTED/不适用 | UNKNOWN |
| PUT `{serviceUrl}`（动态绝对 URL） | URL 内签名；代码不转发 API Key | 原始文件 bytes，`Content-Type` 必须与获取签名时一致；URL 来自上一接口，不拼接 | SDK/服务端要求的额外头、校验和、分片、续传：UNKNOWN；Go只设置Content-Type | 2xx算PUT成功；响应体不解析；随后本地生成 UploadResult，**不是PUT返回JSON** | 非2xx为客户端 remote_upload；存储服务错误码全集 UNKNOWN | NOT_SUPPORTED/不适用 | UNKNOWN；远程URL下载5GiB上限是CLI下载防护，不是上传API最大文件限制 |
| POST `/taskSets/v2` | 原始 API Key | JSON wire body：`publishType:"video",platforms:["抖音"],publishArgs:{accountForms:[...]},coverKey:string`；每项要求 `platformAccountId,video,cover,coverKey,contentPublishForm.formType:"task"`。详细见下文 | `publishChannel` 默认cloud；local必须`clientId`；`desc,isDraft,taskSetId,isAppContent`及平台表单可选字段；HTTP 服务端额外必填项 UNKNOWN | `data:string(taskSetID)`；也兼容 data对象/顶层 `taskSetId/taskSetID/task_set_id/taskIdentityId/id`；CLI规范化为`taskSetId`；返回ID不代表作品成功 | 公共错误；HTTP成功但无ID→不明确受理结果，必须对账；专属错误码 UNKNOWN | NOT_SUPPORTED/不适用；多账号用accountForms数组；批量上限 UNKNOWN | UNKNOWN |
| GET `/v2/taskSets/{taskSetID}/tasks` | 原始 API Key | path `taskSetID:string` | Go不发查询参数；其他字段 UNKNOWN | Go queryData解包data后透传；测试有数组 `[{id,status:"success"}]`；删除预览消费者要求对象`{tasks:[{id,stageStatus,taskStatus,openUrl,...}]}`。严格DTO及必返字段 UNKNOWN | 公共错误；不存在ID/权限不足语义 UNKNOWN | Go没有分页；服务端完整性/分页 UNKNOWN | UNKNOWN |
| GET `/v2/taskSets` | 原始 API Key | CLI要求`--limit`，wire query映射为`size:string`，不是limit；HTTP必填性 UNKNOWN | `platform:string(中文),status:string`；代码没有client_request_id筛选 | data透传；完整字段、稳定排序、时间窗口、保留期限 UNKNOWN | 公共错误；专属 UNKNOWN | CLI只传size；没有page/cursor参数，历史全量可遍历性 UNKNOWN | UNKNOWN |

依据：[accounts.go](https://github.com/yixiaoer888/yixiaoer-skill/blob/a2722c6095f57abf2e345dca637bdded44fa34df/internal/api/accounts.go)、[upload.go](https://github.com/yixiaoer888/yixiaoer-skill/blob/a2722c6095f57abf2e345dca637bdded44fa34df/internal/api/upload.go#L59)、[publish.go](https://github.com/yixiaoer888/yixiaoer-skill/blob/a2722c6095f57abf2e345dca637bdded44fa34df/internal/api/publish.go#L28)、[query.go](https://github.com/yixiaoer888/yixiaoer-skill/blob/a2722c6095f57abf2e345dca637bdded44fa34df/internal/api/query.go#L380)。

账号文档 DTO 字段：`id,platformAccountName,platformName,platformAvatar,platformAuthorId,status,platformType,parentId,groups,proxyId,kuaidailiArea,favorites,isOperate,isFreeze,createdAt`。稳定 ID 生命周期、解绑重绑是否保留：UNKNOWN。`platformAuthorId` 是作者UID，不是发布任务ID或作品ID。登录枚举文档为 0未登录、1成功、2过期、3失败、4取消授权；代码从`status/loginStatus`取数字，只允许1进入发布。API Key有效不代表抖音账号在线。

## 发布 body、抖音字段与源码矛盾

仓库 `schemas/publish.schema.json` 仅是内部表单根 schema（要求formType），**不是 POST 全 envelope 的 OpenAPI schema**。应组合 `schemas/platforms/douyin.video.schema.json`、`internal/modules/publish/preflight.go`、`internal/workflows/publish/service.go`：

1. CLI输入允许 `action:"publish"`，实际 `BuildPublishBodyWithInferred` **剔除 action**；不能把说明文档完整输入直接当最终HTTP body。
2. 共享 `publishArgs.video/cover/coverKey` 会补齐到每个accountForm。样例显式放在每项，避免依赖服务端自动补齐。
3. schema 的accountForm required仅列`platformAccountId,contentPublishForm,video`，但 **preflight还强制cover及coverKey一致**；不能据schema最低要求省略封面。
4. Video为对象`{key:string,size:int>0,width:int>0,height:int>0}`。传已上传key，不能将 `D:\...mp4` 或原始视频URL当key；duration可由UploadResult探测但不是该核心对象必填字段，单位秒。
5. `mediaId/platformName/publishContentId` 在文档称扩展透传，但严格accountForm schema不列出且additionalProperties=false；本轮不依赖这些字段，更不能把publishContentId当幂等键或抖音作品ID。

| 需求 | 核验结果 | 限制 |
|---|---|---|
| platformAccountId | CONFIRMED_SOURCE：accountForms[].platformAccountId，string | 是蚁小二账号ID，不是抖音open_id；稳定性UNKNOWN |
| 视频文件 | CONFIRMED_SOURCE：先签名PUT，再传accountForm.video.key与元数据 | 全链素材出网见数据流报告 |
| title | 支持字段，若出现为string，1–30字符；非必填 | 平台展示效果尚未实测 |
| description | 支持字段，若出现为string，1–1000字符；非必填 | CLI可能归一化#话题，不等于HTTP自动处理 |
| tags | schema允许string数组，1–10项 | 平台视频说明未列tags；CLI不会从tags拼description；实际抖音话题生效UNKNOWN |
| topics / hashtags | 独立字段 **NOT_SUPPORTED**：严格抖音视频schema无topics/hashtags，additionalProperties=false | 不把抖音文章topics能力泛化到视频；视频提供`challenge`单对象 |
| challenge | schema允许`{yixiaoerId,yixiaoerName,raw}` | 必须来源账号对应的challenge查询完整对象；不是多个名称字符串 |
| description中的#标签 | 代码存在归一化到topic HTML，文档又建议视频优先challenge，存在语义分歧 | 最终抖音行为UNKNOWN；样例不嵌入未确认HTML |
| scheduledTime | `accountForms[].contentPublishForm.scheduledTime`，数值；preflight要求13位整数Unix毫秒 | 不能传秒值、无时区字符串、0表示立即；schema最低0与preflight要求13位有差异 |
| scheduledTime时区 | Unix epoch是UTC绝对时刻；输入先带明确offset转换，不重复+8小时 | wire没有timezone字段；服务端显示时区、到点执行机制、最小提前量/最大提前天数UNKNOWN |
| 立即发布 | 不提供scheduledTime的普通非草稿publish流程存在 | “立即”是请求语义，不保证即时成功；不传0 |
| 定时发布 | 字段、13位校验与毫秒保持测试CONFIRMED_SOURCE | 平台原生定时还是供应商计时、客户端离线后行为UNKNOWN |
| 多账号 | 同平台accountForms[]可多项 | 数量/并发上限UNKNOWN；CLI一次命令仅一个平台 |
| 任务状态查询 | 两个taskSet查询接口明确 | 详细状态机见映射报告 |
| 审核状态 | UNKNOWN；未找到可用抖音audit字段/枚举/回调契约 | 不能把stageStatus=success当审核通过 |
| 失败状态 | stageStatus=fail/failed；errorMessage候选字段 | 完整原因码、可重试性、平台最终拒审与提交失败区别UNKNOWN |
| 作品ID | UNKNOWN | task.id是供应商taskId；绝不写入external_work_id |
| 作品URL | task.openUrl有消费者源码证据 | 文档/测试未证明抖音必返、何时可用、公开访问性与ID关联 |

其他可选表单键（以固定 schema 为准）：`horizontalCover,visibleType,declaration,allow_save,location,music,shopping_cart,collection,sub_collection,sync_apps,hot_event,mini_app,film,cooperation_info,game,group_shopping,tagType`。复杂对象的内层required和enum完整保留在固定源码schema中；本原型未实现这些增强功能。

scheduledTime实例：`2026-10-06T09:00:00+08:00` → **1791248400000** → `2026-10-06T01:00:00Z`。源码没有要求再次按Windows本地时区偏移；我们拒绝无offset输入。`query.go` 的ShanghaiDateRange仅用于账号增量日期，不拿它冒充发布服务端时区契约。

依据：[抖音schema](https://github.com/yixiaoer888/yixiaoer-skill/blob/a2722c6095f57abf2e345dca637bdded44fa34df/schemas/platforms/douyin.video.schema.json)、[preflight](https://github.com/yixiaoer888/yixiaoer-skill/blob/a2722c6095f57abf2e345dca637bdded44fa34df/internal/modules/publish/preflight.go#L1815)、[wire builder](https://github.com/yixiaoer888/yixiaoer-skill/blob/a2722c6095f57abf2e345dca637bdded44fa34df/internal/workflows/publish/service.go#L492)、[话题规则](https://github.com/yixiaoer888/yixiaoer-skill/blob/a2722c6095f57abf2e345dca637bdded44fa34df/skills/yixiaoer/references/topic-tags.md)。

## 作品和账号数据接口

| method / path | 认证 | request schema；必要字段 | 可选字段 | response schema | 错误码 | 分页 | 限流 |
|---|---|---|---|---|---|---|---|
| GET `/contents/overviews` | 原始API Key | 无body；代码无必填query；HTTP必填性UNKNOWN | `platform,platformAccountId,publishUserId,type,title,publishStartTime,publishEndTime,page,size`；时间为Unix毫秒，GET字符串；CLI默认page1,size10 | data分页对象，文档作品行含`platformAccountId,accountName,publishUserName,contentData,updatedAt`；contentData候选`reCommand/play/read/great/comment/share/collect`；严格DTO、作品ID与任务join字段UNKNOWN | 公共错误；专属UNKNOWN | page/size已实现，返回total字段与遍历保证UNKNOWN | UNKNOWN |
| GET `/platform-accounts/overviews-v2` | 原始API Key | `platform:string`，CLI要求非空 | `name,group,loginStatus,memberIds`（重复query键）,page,size；CLI默认1/10 | 文档行含`platformAccountId,platformAvatar,platformAccountName,principalName,overviewData`；总计候选fansTotal/playTotal/commentsTotal/likesTotal；精确DTO UNKNOWN | 公共错误；专属UNKNOWN | page/size；返回分页元信息UNKNOWN | UNKNOWN |
| GET `/overview/incremental` | 原始API Key，额外头`x-client:web,x-platform:windows,x-version:2.7.3` | `startTime,endTime`，Unix毫秒字符串 | `group`（不是groupId）,platform,name | data含accounts/summary/trends；原字段透传；字段全集、抖音是否可用UNKNOWN | 公共错误；专属UNKNOWN | Go未传分页；分页UNKNOWN | UNKNOWN |
| GET `/social/dm-stats` | 同上三个额外头与API Key | `startTime,endTime`，Unix毫秒字符串 | `platformAccountIds`逗号连接,platform | data含summary/trend，收发inCount/outCount等；这是私信数据，不是作品评论指标 | 公共错误；专属UNKNOWN | Go未传分页；分页UNKNOWN | UNKNOWN |
| GET `/platform-accounts/{accountID}/account-info` | 原始API Key | path accountID | 无query；其他UNKNOWN | 平台特定账号权利信息，Go透传；抖音字段UNKNOWN | 公共错误；专属UNKNOWN | UNKNOWN/Go无分页 | UNKNOWN |
| GET `/platform-accounts/{accountID}/entitlements` | 原始API Key | path accountID | 无query；其他UNKNOWN | 权益数据透传，严格DTO和抖音scope对应UNKNOWN | 公共错误；专属UNKNOWN | UNKNOWN/Go无分页 | UNKNOWN |
| GET `/platform-accounts/{accountID}/challenges` | 原始API Key | path accountID；代码无必填query | `publishType,keyWord,nextPage`，用于合法challenge对象来源 | 结果透传，候选结构yixiaoerId/yixiaoerName/raw；精确分页容器UNKNOWN | 公共错误；专属UNKNOWN | nextPage请求存在；返回游标字段UNKNOWN | UNKNOWN |

增量命令还会调用`GET /v2/platform/accounts?page=1&size=1000`并带上述额外头获取管理详情；不是另一个账号授权入口。账户净增粉丝不能归因到某条视频；缺指标写UNKNOWN/None，不能填0。作品精确ID筛选参数未在源码实现，按标题模糊查询不能形成可靠作品对账。

依据：[query.go 数据方法](https://github.com/yixiaoer888/yixiaoer-skill/blob/a2722c6095f57abf2e345dca637bdded44fa34df/internal/api/query.go#L392)、[实际CLI命令](https://github.com/yixiaoer888/yixiaoer-skill/blob/a2722c6095f57abf2e345dca637bdded44fa34df/cmd/query.go#L507)、[作品字段说明](https://github.com/yixiaoer888/yixiaoer-skill/blob/a2722c6095f57abf2e345dca637bdded44fa34df/skills/yixiaoer/references/get-content-overviews.md)。

## 完整请求样例和离线验证

- [requests.http.txt](publisher_poc/yixiaoer/examples/requests.http.txt)：账号GET、视频签名GET、视频PUT、必需封面链、定时任务POST、任务GET和作品数据GET；只有文本，无执行入口。
- [publish_request.json](publisher_poc/yixiaoer/examples/publish_request.json)：一个虚构抖音账号、视频key、封面key、scheduledTime。另有local变体；API Key无效、存储主机为`.invalid`。24字节VirtualVideo仅为MP4 ftyp占位签名，不是可播放视频；没有从业务盘读取素材，也没有发送。
- fixture并非供应商真实响应。14项单元测试通过，并对样例账号表单运行固定官方JSON Schema验证；这只证明离线壳和样例符合可见契约，不证明服务端接受或抖音发布成功。
- HTTP/CLI实际使用权限见Go/No-Go报告；即使schema通过，也不进入真实上传或提交。
