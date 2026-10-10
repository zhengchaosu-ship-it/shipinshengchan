# 中国短视频多账号管理／自动发布平台 API 选型研究

研究日期：**2026-10-05，Asia/Shanghai**。适配目标：`8502 → Content → PublishPlan → PublishJob → Publisher Adapter → 中国大陆抖音`。本报告是公开资料与源码调查，**没有完成授权后的接口实测，也没有证明任何候选已可投产**。

## 1. 结论与统计口径

**第一推荐：蚁小二官方 CLI／API，最符合现有 Publisher Adapter 的技术形态。第二推荐：抖音官方开放平台，先申请并核实 video.create.bind 权限。第三推荐：云略 Pro，只进入私有化/API 文档与商务验证阶段。**

找到明显优于 Xiaovcat 桌面 UIA 的控制路线：服务端调用账号、上传、排期、任务查询接口，不再依赖窗口位置或控件树。但“控制接口更好”不等于底层抖音授权合规、完整结果回收和无人值守稳定性已经得到验证。

| 指标 | 结果与含义 |
|---|---|
| 纳入逐项筛选 | **26 个**；不把同一产品的 SaaS、开源仓库、镜像、Fork 重复计数 |
| 国内矩阵管理产品 | **13 个**，编号 04–16；有当前可访问官网/文档，个别资料较旧，不据此保证营业或服务 SLA |
| 有真实网络 API／SDK 证据 | **12 个**：01、02、03、04、17、18、20、21、23、24、25、26 |
| 有中国抖音发布相关程序接口证据 | **6 个**：01、04、17、20、21、23；17 要手机人工提交，20/21/23 依赖浏览器/Cookie |
| 此外有真实发布 CLI | 19 SAU；没有把其历史 Web 后端计入稳定当前网络 API |
| 值得优先推进 | **3 个**：A 档 1 个、优先 B 档 2 个；其中现阶段技术 POC 首选 **1 个**（蚁小二） |
| 已证明完整生产替换 | **0 个**，本轮未授权联调、未真实发布、未验证账号规模或 SLA |

**现有项目约束必须保留：优先本地、素材不上传第三方服务器。**蚁小二公开代码的标准上传路径会取得供应商对象存储的签名地址；“local 发布”不证明素材全程留在本机。因而其 A 档是**技术选型候选**，不是允许违反本地约束的接入许可。下一步应先验证零素材出网的私有化/本地方案；若供应商无法证明，则暂停其真实上传 POC。严格保持素材只在自有系统与目标抖音之间流转时，**获得权限后的官方直连才是优先的生产方向**；本轮不替用户改变这项约束。[蚁小二上传源码](https://github.com/yixiaoer888/yixiaoer-skill/blob/a2722c6095f57abf2e345dca637bdded44fa34df/internal/api/upload.go)

## 2. 方法、证据等级和标记

已组合检索中文的多账号、定时发布、企业号、MCN、矩阵、批量发布、开放接口、SDK、私有化、OEM、Webhook、二次开发，以及英文 Douyin video publish/content posting/multi account management、China social media management、GitHub short video publisher、Gitee 抖音自动发布。优先读平台官网、开发者文档、GitHub 原始代码和实时仓库元数据；搜索摘要用于发现线索，不把宣传“API”当作已经可调用。

- **E1**：实际方法、路径、请求或实现源码可核对；仍不代表有当前账号权限。
- **E2**：官网明确声称相关能力，但无完整接口契约；只能进入商务核验。
- **E3**：GUI/宣传/历史页面，缺少可调用发布接口。
- **YES**：相应文档/代码存在；**CLAIM**：供应商声明，未独立验证；**UNKNOWN / U**：公开证据不足。
- **NOT_SUPPORTED / N**：已核对的接口或产品形态没有该项，或明确要求人工，不能实现所指自动化。含义限定于本轮核对的公开版本，不断言厂商永远不能开发。
- **UI_ONLY**：本轮仅确认网页/桌面人工功能，没有发现面向本系统的程序发布接口；不排除另有未公开企业接口。
- **LOCAL_SCHEDULER**：可由我们自己的排期器实现，不冒充供应商原生 scheduled_at。
- 风险为工程和账号治理判断，**不是封号概率或法律定性**。A/B/C 的硬条件优先于分数：私有接口、人工提交、GUI 产品不会仅因总分高而进入正式生产候选。

所有并发、百账号稳定性、Token 自动刷新、报价和 API 许可，只在有具体证据时写确认；“支持 1000 个账号”的页面是容量宣称，不能当实测。

## 3. 全部候选、分档、评分与主要证据

评分顺序：**API 30 / 抖音 20 / 多账号 15 / 定时 10 / 状态与回调 10 / 数据 API 5 / 成熟度 5 / 成本 5**。未知能力不获分；GUI 多账号/定时可获少量功能分但 API 为 0；CLI 属部分程序能力；广告、数据、浏览器控制 API 若不能服务本任务，API 适配分很低。成熟度依据更新、文档、社区而非压测。成本分考虑公开价格与运维复杂度，开源免费不代表免费维护。分值是本轮证据下的选型判断，不是厂商性能排名。

| ID | 候选 / 类型 | API 真伪与主要缺口 | 档 | 风险 | 难度 | 八项分值 | 总分 | 主要证据 |
|---|---|---|---|---|---|---|---:|---|
| 01 | 抖音开放平台 / 官方 | 真上传、创建；权限申请、定时与结果闭环缺口 | B | LOW | HIGH | 20/20/11/0/2/0/5/0 | 58 | [创建](https://developer.open-douyin.com/docs/resource/zh-CN/dop/develop/openapi/video-management/douyin/create-video/video-create) |
| 02 | 巨量引擎／千川 / 官方商业 API | 真广告/授权 API；未核实普通作品发布 API | B | LOW | HIGH | 3/5/6/0/0/1/5/0 | 20 | [抖音号授权](https://open.oceanengine.com/labels/12/docs/1771376926549067?origin=left_nav) |
| 03 | 快手开放平台 / 官方 | 真视频 API；不支持抖音 | C | LOW | MEDIUM | 15/0/8/0/4/0/5/0 | 32 | [上传发布](https://open.kuaishou.com/platformDocs/openAbility/contentManagement/createAVideo.html) |
| 04 | 蚁小二 / 商用 CLI、API | E1；状态枚举、作品 ID、授权来源待验 | A* | MEDIUM | MEDIUM | 27/18/14/10/7/4/4/1 | 85 | [官方 CLI](https://www.yixiaoer.cn/cli)、[源码](https://github.com/yixiaoer888/yixiaoer-skill) |
| 05 | 易媒助手 / Windows 矩阵 | UI_ONLY | C | MEDIUM | HIGH | 0/8/8/3/0/0/3/2 | 24 | [官网](https://yimeizhushou.com/)、[版本/套餐](https://yimeizhushou.com/vip.html) |
| 06 | 融媒宝 / Windows 矩阵 | UI_ONLY | C | MEDIUM | HIGH | 0/8/8/3/0/0/3/2 | 24 | [官网](https://www.rmeibao.com/hj?channel=zh)、[定时](https://www.rmeibao.com/tutorial/46.html) |
| 07 | 云略 Pro / 企业矩阵 | API、私有化 E2，无路径/schema | B | MEDIUM | HIGH | 0/8/8/3/0/0/3/0 | 22 | [官网](https://www.yunluepro.com/) |
| 08 | 新榜矩阵通 / 企业矩阵 | 定制 API 声明未证明是发布接口 | B | MEDIUM | HIGH | 0/8/8/0/0/0/3/0 | 19 | [新榜 API 入口](https://newrank.cn/account/api)、[矩阵通](https://matrix.newrank.cn/) |
| 09 | 火山引擎矩阵管家 / 企业服务 | 发布/数据 GUI 文档；API 未证实，资料旧 | C | MEDIUM | HIGH | 0/8/8/0/0/0/2/0 | 18 | [官方文档](https://www.volcengine.com/docs/6412/163488?lang=zh) |
| 10 | 发布鸭 / 浏览器矩阵 | GUI；开放接口需联系，暂无契约 | B | HIGH | HIGH | 0/8/8/3/0/0/2/0 | 21 | [官网](https://www.fabuya.com/) |
| 11 | 坤图矩阵管理器 / 桌面 | UI_ONLY，浏览器环境与 Cookie | C | HIGH | HIGH | 0/8/8/3/0/0/2/3 | 24 | [官网](https://www.szkuntu.cn/) |
| 12 | 小V猫 Xiaovcat / 桌面 | UI_ONLY，当前工程已依赖 UIA | C | HIGH | HIGH | 0/8/8/3/0/0/3/0 | 22 | [官方指南](https://baoteyun.com/docs/vcat/intro/) |
| 13 | 创作罐头 / 矩阵 | UI_ONLY | C | MEDIUM | HIGH | 0/8/8/0/0/0/2/0 | 18 | [官网](https://www.czgts.cn/) |
| 14 | 企域新链 NewMatrix / 汽车矩阵 | UI_ONLY，垂直汽车行业 | C | MEDIUM | HIGH | 0/8/8/0/0/0/2/0 | 18 | [官网](https://www.newmatrix.com.cn/) |
| 15 | 微小宝 / 公众号管理 | 微信公众号证据，抖音未验证 | C | MEDIUM | HIGH | 0/0/4/0/0/0/2/0 | 6 | [官方产品](https://www.wxb.com/product) |
| 16 | A5新媒体管家 / 分发产品 | UI_ONLY，抖音细项/API 未验证 | C | MEDIUM | HIGH | 0/0/4/2/0/0/1/0 | 7 | [官方介绍](https://www.a5.cn/xmt_adv_2025/index.html) |
| 17 | AiToEarn / SaaS＋开源 | 真 REST，抖音需用户手机提交 | C | MEDIUM | MEDIUM | 26/7/14/6/9/1/3/0 | 66 | [中国版教程](https://docs.aitoearn.cn/)、[仓库](https://github.com/yikart/AiToEarn) |
| 18 | 出海匠 / 开放 API | 真账号等 API，Douyin 未验证 | C | MEDIUM | HIGH | 8/0/7/0/2/1/2/0 | 20 | [开发文档](https://openapi-doc.chuhaijiang.com/introduction) |
| 19 | social-auto-upload / 开源 | 当前 CLI，历史 Web API 不保证可用 | C | HIGH | HIGH | 14/16/10/8/2/0/3/5 | 58 | [仓库](https://github.com/dreammis/social-auto-upload) |
| 20 | MatrixMedia / 开源本地 HTTP | 真 HTTP；Electron＋浏览器会话 | C | HIGH | MEDIUM | 23/16/10/7/5/0/2/5 | 68 | [HTTP API](https://github.com/hanliang97/MatrixMedia/blob/main/docs/http-api.md) |
| 21 | Prism / 开源 FastAPI | 真 API；浏览器与私有登录接口 | C | HIGH | HIGH | 20/14/12/8/6/1/1/5 | 67 | [仓库](https://github.com/Laihiujin/Prism) |
| 22 | multi-publisher / 开源桌面 | Electron IPC，未见外部 REST | C | HIGH | HIGH | 0/14/8/0/0/0/1/5 | 28 | [仓库](https://github.com/atxinsky/multi-publisher) |
| 23 | multipost / Rust gRPC | 真 gRPC；Douyin Chrome CDP，规模证据弱 | C | HIGH | HIGH | 23/14/9/0/8/0/0/4 | 58 | [仓库](https://github.com/Shuozeli/multipost) |
| 24 | AdsPower / 浏览器控制平台 | 真本地 API，没有内置抖音发布接口 | C | HIGH | HIGH | 4/0/8/0/0/0/4/1 | 17 | [API 文档](https://help.adspower.com/docs/api) |
| 25 | 比特浏览器 / 浏览器控制平台 | 真本地 API，仍需自己写发布自动化 | C | HIGH | HIGH | 4/0/8/0/0/0/3/0 | 15 | [浏览器 API](https://doc.bitbrowser.net/zh/api-jie-kou-wen-dang/liu-lan-qi-jie-kou) |
| 26 | TikHub / 数据 API | 真 REST 数据接口，未见视频发布 API | C | HIGH | HIGH | 3/0/3/0/0/4/2/2 | 14 | [Swagger](https://api.tikhub.io/)、[创作者作品列表](https://docs.tikhub.io/359719871e0) |

A*：可先进行无需授权/上传的接口契约验证；后续真实测试须先解决素材出网和供应商权限来源。B 共 5 个，优先只留 01、07；02 广告场景不匹配，08 尚无发布 API 证据，10 明确浏览器自动化，均不进入短名单。C 共 20 个。

## 4. Top 5 决策比较

这是**决策优先级**，不是按分数降序：前 3 项是推进对象，后 2 项用于说明本地 API 替代路线及其风险。不能把 C 档比较对象误读为生产推荐。Prism、AiToEarn 虽有较高功能分，分别因私有接口与人工提交被排除。

| 平台 | 官网 | 类型 | 支持抖音 | 多账号 | API | 上传 | 定时发布 | 发布状态查询 | Webhook | 数据 API | 账号认证方式 | 价格 | 风险 | 接入难度 | 评分 | 证据链接 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---:|---|
| 蚁小二（A*） | [官网](https://www.yixiaoer.cn/) | 商用云／本地客户端 CLI | YES，源码有专用表单 | 账号列表与逐账号任务 | HTTP＋CLI，E1 | 本地 MP4→签名 PUT；出网须核查 | scheduledTime 毫秒时间戳 | taskSet/tasks 可查；终态枚举 U | U | 作品/账号 overview 与增量，Douyin 字段实值待测 | 客户端绑定＋供应商 APIKey；底层 OAuth/Cookie U | 普通订阅与 API 合同分开；API CONTACT_SALES | MEDIUM | MEDIUM | 85 | [源码 API](https://github.com/yixiaoer888/yixiaoer-skill/tree/a2722c6095f57abf2e345dca637bdded44fa34df/internal/api)、[抖音表单](https://github.com/yixiaoer888/yixiaoer-skill/blob/a2722c6095f57abf2e345dca637bdded44fa34df/skills/yixiaoer/references/platforms/video/douyin.md) |
| 抖音官方（B） | [开放平台](https://developer.open-douyin.com/) | 官方 API | YES，需 video.create.bind | 自行维护每个 open_id 的授权 | REST＋官方 SDK | multipart／分片 | 原生 N；自有排期器 | 创建回执有 ID；通用审核终态 U | 有 Webhook 框架；直接创建审核回调 U | 通用作品全指标 U；特定小程序场景有限 | OAuth2，按 app＋open_id | 本次能力价格/商业条件 CONTACT_SALES | LOW | HIGH | 58 | [上传](https://developer.open-douyin.com/docs/resource/zh-CN/dop/develop/openapi/video-management/douyin/create-video/upload-video)、[创建](https://developer.open-douyin.com/docs/resource/zh-CN/dop/develop/openapi/video-management/douyin/create-video/video-create) |
| 云略 Pro（B） | [官网](https://www.yunluepro.com/) | 企业矩阵、私有化声明 | CLAIM | CLAIM，团队矩阵 | E2：有 API 声明，无契约 | U | GUI/产品宣称；API U | U | U | 看板宣称；API U | U | CONTACT_SALES | MEDIUM | HIGH | 22 | [官网企业集成说明](https://www.yunluepro.com/) |
| MatrixMedia（C） | [仓库](https://github.com/hanliang97/MatrixMedia) | 本地 Electron＋HTTP | YES，dy | phone/partition 会话隔离 | localhost:30088 | 绝对 MP4 路径／URL | publishAt，进程内到点执行 | 历史记录，不是稳定通用状态 REST | U | Douyin 指标 API U | 扫码、浏览器 Cookie | GPL-2.0 源码；运维自担 | HIGH | MEDIUM | 68 | [真实 HTTP 契约](https://github.com/hanliang97/MatrixMedia/blob/main/docs/http-api.md) |
| social-auto-upload（C） | [仓库](https://github.com/dreammis/social-auto-upload) | Python CLI＋浏览器 | YES | account 别名＋Cookie 文件 | 当前 CLI；历史 REST 不保证 | 本地 file、title、desc | --schedule 本地日期时间；浏览器执行 | CLI结果，完整终态 U | U | U | 扫码、Cookie、Patchright | MIT 源码；运维自担 | HIGH | HIGH | 58 | [README](https://github.com/dreammis/social-auto-upload)、[CLI 文档](https://github.com/dreammis/social-auto-upload/blob/main/docs/CLI.md) |

**最适合现有架构的技术候选是蚁小二**：供应商任务 ID、account ID 和定时时间可以映射现有 PublishJob，无需将 8502 改成新的发布后台。官方直连在账号治理和素材链路上更理想，但要自行完成授权、排期和状态补齐；不能把申请中权限写成已支持。云略仅作为私有化的备选商询，当前没有可实现的 Adapter 契约。

## 5. 抖音官方能力专项核验

### 5.1 已确认的真实接口

| 能力 | 当前证据 | 对本系统的影响 |
|---|---|---|
| 上传本地视频 | POST `https://open.douyin.com/api/douyin/v1/video/upload_video/`；multipart，open_id＋access-token，scope video.create.bind | 接口真实；上传返回的加密 video_id 是素材标识，不能直接当已发布作品 |
| 创建作品 | POST `/api/douyin/v1/video/create_video/`，同一 scope；上传 video_id＋text 等 | 返回 item_id 与作品 video_id；创建后仍需审核，回执不等于公开可见 |
| 文案/话题 | text 组合文案与 #话题；公开契约不是独立 title/description/hashtags 三字段 | Adapter 应合并并做长度校验，不能虚构 title 字段 |
| 定时 | 核对的创建请求无 scheduled_at / publishAt | 原生 NOT_SUPPORTED；由自有服务到点调用创建，上传有效期另验证 |
| 用户授权 | OAuth2，code→token；open_id 与应用相关 | 多账号可分别授权，自己保管账号注册表；没有证明存在全局 GET/accounts |
| 单条基础资料 | POST `/api/douyin/v1/video/video_basic_info/`，scope posting.behavior，查自己账号作品 | 能核对作品基础 ID/标题等，不是发布任务终态或全量分析接口 |
| 作品列表 | 旧 account-video-list 页面本轮只有导航，缺少正文；历史公告仍提及 video.list.bind | UNKNOWN，向平台确认当前权限及接口，不把空页判成全面下线 |
| 通用作品数据 | 历史 video.data.bind 等不能据旧示例认定今天可开通 | UNKNOWN；不承诺播放/点赞等全指标闭环 |
| 发布 Webhook | 有官方框架、授权事件及 SDK 分享 create_video 事件 | 不能把 SDK 分享成功事件当 REST 创建作品的审核终态回调 |

证据：[上传](https://developer.open-douyin.com/docs/resource/zh-CN/dop/develop/openapi/video-management/douyin/create-video/upload-video)、[创建](https://developer.open-douyin.com/docs/resource/zh-CN/dop/develop/openapi/video-management/douyin/create-video/video-create)、[基础信息](https://developer.open-douyin.com/docs/resource/zh-CN/dop/develop/openapi/video-management/posting-task/video-basic-info)、[旧列表页](https://developer.open-douyin.com/docs/resource/zh-CN/dop/develop/openapi/video-management/douyin/search-video/account-video-list)、[当前接口目录](https://developer.open-douyin.com/docs/resource/zh-CN/dop/develop/openapi/list)。

创建文档要求从应用能力实验室申请“代替用户发布内容到抖音”，再取得用户授权。可访问文档不等于任意新应用均能获得权限。上传文档建议超过 50MB 分片，超过 300MB 必须分片，总文件不超过 4GB；创建文档含单用户单应用日创建上限 75 条、视频最长 15 分钟的错误说明。这些是**接口所述限制**，不是百账号容量承诺或全部业务的通用配额。

### 5.2 当前文档的重要冲突

官方 2024-11-15 公告称，2024-12-13 起，作品列表/数据中的 is_reviewed、video_status 及 video-basic-info 的 video_status 被移除。基础信息页面旧样例仍出现 video_status，**实现时应以公告为约束，不利用旧样例判断审核成功**。[官方变更公告](https://developer.open-douyin.com/forum/bulletin/post/6736c38048f043667b75f70a)

官方 `/share-id/` 是给 SDK 分享流程生成有效期 1 小时的 share_id；need_callback 配合 SDK 返回作品 ID。它不是 `GET /publish/{task_id}`，也不是服务端直接发布接口的可靠审核回收方案。[分享结果说明](https://developer.open-douyin.com/docs/resource/zh-CN/dop/develop/openapi/video-management/douyin/search-video/video-share-result)、[Webhook 事件](https://developer.open-douyin.com/docs/resource/zh-CN/dop/develop/webhooks/event-list)

Webhook 有签名、超时重试和 Msg-Id，可在获得对应事件权限后做去重；本轮没有证明存在针对直接 REST 创建任务的完整审核/失败回调，故保留 UNKNOWN。[Webhook 总览](https://developer.open-douyin.com/docs/resource/zh-CN/dop/develop/webhooks/summarize)

### 5.3 开发者身份不能替代 scope

| 身份/入口 | 能确定什么 | 不能推断什么 |
|---|---|---|
| 普通自研应用 | 可走开发者申请、用户 OAuth，按获准 scope 调用 | 所有普通应用默认都有服务端发视频 |
| 企业号/企业认证 | 官方有企业开发者专属能力，授权主体与管理能力更明确 | 蓝 V 即自动获得 video.create.bind |
| MCN | 业务上有矩阵账号/创作者协作场景 | MCN 是唯一发视频入口，或 MCN 任意发所有签约号 |
| 系统服务商 | 官方开发者类型，可按需求申请差异化能力 | 自称服务商/合作伙伴即可绕过审批与用户授权 |
| 集团内部、定向伙伴 | 可能有合同/定向能力 | 外部系统可用相同内部接口；本轮没有可复用契约 |
| 巨量/千川 | 广告主、素材、抖音号合作授权等官方 API | 广告素材上传等于普通抖音主页作品发布 |

依据：[现行角色和权限说明](https://partner.open-douyin.com/docs/resource/zh-CN/developer/introduction/type-and-permission)、[能力方案](https://partner.open-douyin.com/docs/resource/zh-CN/dop/ability/common-solution)、[千川授权](https://open.oceanengine.com/labels/12/docs/1771376926549067?origin=left_nav)。千川 SELF 授权说明涉及主页发布权限，但本轮**未找到可供本 Adapter 调用的独立普通视频创建接口**；必须拿到真实方法和申请条件才可改变结论。

### 5.4 OAuth、限流、数据场景

公开授权说明的 access_token 生命周期为 15 天、refresh_token 为 30 天，刷新/续期及最长授权周期有额外规则；撤销授权会失效。需要应用实现自动刷新与串行锁，**不是平台自动替我们维护 token**。账号键建议 `(client_key, open_id)`；不能把 open_id 视为跨应用全局抖音 UID。[授权说明](https://developer.open-douyin.com/docs/resource/zh-CN/dop/develop/sdk/mobile-app/permission/overall-permission)、[官方 SDK](https://developer.open-douyin.com/docs/resource/zh-CN/dop/develop/openapi/sdk-overview)

video-basic-info 的错误说明含 100 QPS 限制，仅对该接口引用；其它接口未确认时为 UNKNOWN。应以获准应用控制台配额为准，分账号和应用限速。企业团队 RBAC、百账号队列公平性由我们实现，OAuth 多账号能力不能当 100 账号压测结果。

小程序有 ma.item.data 授权或挂载自身小程序的分析能力；例如 video-overview-data-v3 是小程序挂载视频场景，不能移植成普通矩阵号全量作品分析。[小程序授权](https://partner.open-douyin.com/docs/resource/zh-CN/mini-app/develop/api/open-interface/authorization/tt-show-douyin-open-auth/)、[挂载视频分析](https://developer.open-douyin.com/docs/resource/zh-CN/mini-app/develop/server/operation/data-analysis/video-analysis/video-overview-data-v3)

### 5.5 Douyin 与 TikTok 严格区分

TikTok Direct Post 使用 `open.tiktokapis.com/v2/post/publish/video/init/`、video.publish scope，返回 publish_id，有 FILE_UPLOAD/PULL_FROM_URL 和独立审核/限额要求。**这是国际 TikTok，不能发布到中国大陆抖音账号。**两者应用注册、token、scope、任务回收模型不同。全球工具宣称支持 TikTok，不给 Douyin 评分。[TikTok 官方 Direct Post](https://developers.tiktok.com/docs/en/content-posting-api-reference-direct-post)

## 6. 蚁小二接口真实性与待验证项

官方 /cli 页面链接官方仓库，公开 Go 客户端确有请求实现；不是仅贴一个 AI Skill 的宣传。核对版本：仓库 commit `a2722c6095f57abf2e345dca637bdded44fa34df`，2026-09-30；npm `@yixiaoermail/cli` 3.2.26，2026-09-30 发布。本轮只读，没有安装/执行 CLI，也没创建 APIKey。[官方入口](https://www.yixiaoer.cn/cli)、[npm 元数据](https://registry.npmjs.org/@yixiaoermail/cli)

默认 base URL 是 `https://www.yixiaoer.cn/api`；客户端 Authorization 使用配置中的 APIKey。企业开放平台另有试用/合同流程，不能把企业专用合同 API 和公开 CLI 路径混成一份承诺。[配置](https://github.com/yixiaoer888/yixiaoer-skill/blob/a2722c6095f57abf2e345dca637bdded44fa34df/internal/config/config.go)、[HTTP 客户端](https://github.com/yixiaoer888/yixiaoer-skill/blob/a2722c6095f57abf2e345dca637bdded44fa34df/internal/api/client.go)、[企业入口](https://open.yxiaoer.cn/)

| 系统需求 | 实际接口/字段证据 | 验证边界 |
|---|---|---|
| 账号列表 | GET /v2/platform/accounts；分页、供应商 account id、status | platformAccountId 稳定性/解绑重绑语义 U；不是天然抖音 UID |
| 上传 MP4 | GET /storages/{bucket}/upload-url → serviceUrl/key → PUT 文件 | 标准 bucket 为 cloud-publish；元数据 duration/尺寸；对象存储归属/删除策略须证明 |
| 创建/排期 | POST /taskSets/v2 → taskSetId | scheduledTime 为 13 位 Unix 毫秒；不是秒，不直接把 ISO 字符串传进去 |
| 选择账号/文案 | publishArgs.accountForms[].platformAccountId；Douyin title、description、topics | title 1–30、description 1–1000；话题字段须按供应商查询结果/表单格式填，不虚构统一 hashtag 参数 |
| 查询任务 | GET /v2/taskSets；GET /v2/taskSets/{taskSetID}/tasks | 容器 ID 要分解到每个账号 task；所有真实状态与失败码、video_id/video_url 仍 U |
| 单作品数据 | GET /contents/overviews，platformAccountId 等筛选 | schema 有 play/great/comment/share/collect；是否对抖音全部有值/时延/作品关联 U |
| 账号数据/涨粉 | GET /platform-accounts/overviews-v2；GET /overview/incremental | cmd/query.go 有 account-overviews、account-increments；涨粉字段口径/净增粒度待样本确认 |
| 发布渠道 | publishChannel=cloud 或 local；local 必须 clientId 在线 | 没有自动回退；local 不能据名字判断零出网或不依赖桌面 |
| Webhook、刷新 | 未确认回调文档或公开 refresh-account 接口 | UNKNOWN；不承诺 APIKey 调用就解决抖音重新授权 |

证据：[accounts.go](https://github.com/yixiaoer888/yixiaoer-skill/blob/a2722c6095f57abf2e345dca637bdded44fa34df/internal/api/accounts.go)、[upload.go](https://github.com/yixiaoer888/yixiaoer-skill/blob/a2722c6095f57abf2e345dca637bdded44fa34df/internal/api/upload.go)、[publish.go](https://github.com/yixiaoer888/yixiaoer-skill/blob/a2722c6095f57abf2e345dca637bdded44fa34df/internal/api/publish.go)、[query.go](https://github.com/yixiaoer888/yixiaoer-skill/blob/a2722c6095f57abf2e345dca637bdded44fa34df/internal/api/query.go)、[CLI 查询命令](https://github.com/yixiaoer888/yixiaoer-skill/blob/a2722c6095f57abf2e345dca637bdded44fa34df/cmd/query.go)、[渠道说明](https://github.com/yixiaoer888/yixiaoer-skill/blob/a2722c6095f57abf2e345dca637bdded44fa34df/skills/yixiaoer/references/cli/publish-channels.md)。

HTTP 200 仍可能是业务失败；源码检查 statusCode。taskSetId 缺失/网络响应不明时不能盲目重发，应先查记录。部分参考文档与 CLI 实现不同步，接入前必须以固定版本 schema 和响应样本核对。

厂商 FAQ 宣称使用官方 API、非 RPA；这是**厂商声明**，本轮不能独立证明抖音具体 scope、合作资格和云/本地两种渠道的实现。请供应商给可核对的官方授权入口/能力名称、Cookie 是否托管、授权撤销和导出机制。[官方 FAQ](https://xueyuan.yixiaoer.cn/article/46634)、[API 文档迭代说明](https://xueyuan.yixiaoer.cn/article/46560)、[定制/私有化](https://www.yixiaoer.cn/customized)

## 7. 逐项能力核验：全部 26 项

以下两个矩阵合计覆盖用户的 25 个检查点。API 栏讨论“程序可用”，不会把 GUI 的上传、定时、数据看板当 API。未知是调查结论，不能替换成肯定。ID 对应上表；每行证据沿用上表及专项章节。

字段说明：T/D/H 分别标题/简介/话题；定时列明确时间字段；结果列是原生作品 ID 与链接，不是供应商任务 ID。数据序列为**播放/点赞/评论/分享/收藏/涨粉**，V=有相关接口/字段证据但本轮未实测，U=未知，N=明确未实现本平台，GUI=仅看板。作品/账号列分别指单作品 API 与按账号分开查询。

| ID | 抖音/多账号 | 稳定 ID / API 列账号 | 本地 MP4 API | T/D/H | 定时 API / 时间字段 | 状态查询 / ID＋URL | 发布回调 | 数据六项 | 单作品/分账号数据 |
|---|---|---|---|---|---|---|---|---|---|
| 01 | YES / 逐账号授权 | app作用域 open_id / N全局列表，自有注册表 | YES | 合并text | N原生；LOCAL_SCHEDULER | 终态U / ID YES，URL U | 直接创建U | U/U/U/U/U/U | 通用U / 按open_id |
| 02 | 相关授权 / 多广告主 | advertiser_id等 / 有广告资源列表，不是普通账号发布列表 | 广告素材YES，普通发布U | 普通作品U | 普通作品U | 普通作品U/U | 普通作品U | 普通作品全U | 广告数据非目标 |
| 03 | N抖音 / 快手OAuth | 快手授权ID / 自有注册表 | YES快手 | caption等 | U | 快手查询链路 / photo_id，公开URL U | U | 抖音全N | 抖音N |
| 04 | YES / YES | vendor account id / YES | YES，签名PUT | YES/YES/YES表单 | YES / scheduledTime ms | YES查询，枚举U / U＋U | U | V/V/V/V/V/V* | V / YES |
| 05 | CLAIM / CLAIM | 账号ID U / UI_ONLY | UI_ONLY | GUI / 细项U | GUI / API U | API U / U＋U | U | GUI，API全U | API全U |
| 06 | CLAIM / CLAIM | 账号ID U / UI_ONLY | UI_ONLY | GUI / 细项U | GUI / API U | API U / U＋U | U | GUI，API全U | API全U |
| 07 | CLAIM / CLAIM | U / API契约U | U | U | 产品CLAIM / API U | U / U＋U | U | GUI，API全U | API全U |
| 08 | CLAIM / CLAIM | U / 发布账号API U | U | U | U | U / U＋U | U | 看板CLAIM，API全U | API全U |
| 09 | 文档YES / 企业组织 | U / UI_ONLY | UI_ONLY | GUI / 细项U | U | API U / U＋U | U | GUI，API全U | API全U |
| 10 | CLAIM / CLAIM | profile / API U | UI_ONLY | GUI / 细项U | GUI / API U | API U / U＋U | U | API全U | API全U |
| 11 | CLAIM / CLAIM | profile / UI_ONLY | UI_ONLY | GUI / 细项U | GUI / API U | API U / U＋U | U | API全U | API全U |
| 12 | YES现有流程 / YES | 现有UI账号 / API U | UI_ONLY | GUI | GUI / API U | API U / U＋U | U | GUI，API全U | API全U |
| 13 | CLAIM / CLAIM | U / UI_ONLY | UI_ONLY | GUI / 细项U | U | API U / U＋U | U | GUI，API全U | API全U |
| 14 | CLAIM / CLAIM | U / UI_ONLY | 产品CLAIM / API U | U | U | API U / U＋U | U | 看板CLAIM，API全U | API全U |
| 15 | U抖音 / 微信多号 | U抖音 / U | 抖音U | 抖音U | 抖音U | 抖音U / U＋U | U | 抖音全U | 抖音全U |
| 16 | U抖音 / 分发CLAIM | U / UI_ONLY | 抖音U | U | GUI声明 / API U | API U / U＋U | U | API全U | API全U |
| 17 | YES但需人工 / YES | vendor accountId / 列表文档YES | 签名上传YES | 通用title/body，Douyin话题U | publishAt ISO8601；不能自动完成抖音发布 | Flow/record YES / platformWorkId＋workLink字段 | U | 有数据接口目录，Douyin六项全U | 文档存在 / accountId |
| 18 | Douyin U / 多平台YES | vendor账号ID / YES | 普通发布接口文档；Douyin U | Douyin U | Douyin U | 平台通用接口 / Douyin U | U | Douyin全U | Douyin U |
| 19 | YES / YES | account别名非平台ID / CLI | YES CLI | title/desc；话题需浏览器验证 | --schedule "YYYY-MM-DD HH:mm" | CLI结果 / U＋U | U | 全U | U |
| 20 | YES dy / YES | phone/partition非平台ID / changeData会话列表 | YES本地file/URL | title/description/tags | publishAt本地时间，进程内计时 | changeData历史 / 原生ID＋URL U | U | 全U | U |
| 21 | YES / YES | 本地账号ID / 真accounts路由 | YES源码 | 代码表单，细项待测 | 队列/定时源码 / 精确契约待测 | publish路由 / 原生ID＋URL U | U | Douyin全U | analytics路由≠证明全部指标 |
| 22 | YES / YES | 本地会话ID / N外部API | N外部API，GUI上传 | GUI | U | 外部API N / U＋U | U | 全U | U |
| 23 | YES / YES | account_id映射profile / gRPC YES | Media.Upload流 | Posts.Submit内容，Douyin细项待测 | N原生；调用方排期 | GetJob/Watch YES / 原生ID＋URL U | N Webhook；gRPC Watch可用 | Douyin N/N/N/N/N/N | Douyin N |
| 24 | 无内置抖音 / 多profile | profile id非平台ID / YES | N内置发布 | N内置 | N内置 | N内置发布 / N＋N | N内置发布 | 抖音全N | 抖音N |
| 25 | 无内置抖音 / 多profile | browser id非平台ID / YES | N内置发布 | N内置 | N内置 | N内置发布 / N＋N | N内置发布 | 抖音全N | 抖音N |
| 26 | 抖音读取 / 可传Cookie | 数据用户ID / 无绑定账号列表证据 | N发布 | N发布 | N发布 | N发布任务 / 可读已有作品，非提交结果 | U | V/V/V/V/V/U | V / 依Cookie与用户 |

04 的涨粉 V* 表示账号增量查询代码存在，**具体涨粉字段定义与有效值 UNKNOWN**。绝不把未填字段写成 0，亦不把净增粉丝当某条作品归因涨粉。

| ID | 认证/Cookie/扫码 | Token 自动刷新 | Windows桌面需在线 / 发布需GUI | 团队权限 / 数十至百账号 | 并发与 API rate limit | 实现类别 |
|---|---|---|---|---|---|---|
| 01 | OAuth；无需Cookie；授权可扫码 | 应用自行实现；非默认自动 | N / 授权有人操作，正常API N | 自建RBAC / 可多授权，100号U | 创建75/用户/应用/日；基础信息100QPS，其它U | 官方API |
| 02 | 广告主token＋抖音号授权，前置协议 | U，按广告API规则 | 正常API N / 初始授权流程 | 商业组织权限 / 普通发片规模U | 当前目标接口U | 官方API（广告场景） |
| 03 | 快手OAuth，无需抖音Cookie | 自实现，精确规则U | API N / 初始授权 | 自建 / 100号U | U | 官方API（非Douyin） |
| 04 | APIKey；账号客户端绑定；是否托管Cookie U；扫码方式待确认 | 底层账号自动续期U | cloud N；local client须在线 / 提交CLI N | master/admin/member代码 / 大规模CLAIM，实测U | U；分页size=50不是限流 | 第三方API；官方来源CLAIM未独立证实 |
| 05 | 客户端绑定；Cookie/扫码细项U | U | Windows客户端在线 / YES | 团队版 / 1000+CLAIM | U | UI_ONLY，底层U |
| 06 | 客户端绑定；Cookie/扫码细项U | U | Windows客户端在线 / YES | 团队版 / 1000+CLAIM | U | UI_ONLY，底层U |
| 07 | U | U | SaaS/私有化CLAIM；桌面依赖U / API发布U | 企业组织CLAIM / 案例规模CLAIM | U | 企业集成声明，底层U |
| 08 | U | U | 云产品；发布执行器U / API发布U | 企业组织CLAIM / 大规模CLAIM | U | 企业集成声明，底层U |
| 09 | 企业账号授权；Cookie U | U | 云管理文档，执行器U / GUI已确认 | 企业组织YES文档 / 实测U | U | UI_ONLY，官方品牌≠开放发布API |
| 10 | 浏览器profile、Cookie；扫码/登录 | U，会话可能失效 | 本地执行器需在线 / 现有产品GUI | 团队/矩阵CLAIM / 100号U | U | Browser Automation＋Cookie |
| 11 | 浏览器Cookie、扫码 | U，会话可能失效 | Windows在线 / YES | 团队U / 100账号CLAIM | U | Browser/Cookie Automation |
| 12 | 桌面账号绑定；底层Cookie U | U | Windows在线 / 当前UIA需GUI | 产品多账号 / 百账号实测U | U | UI_ONLY；现有UIA |
| 13 | 绑定方法U；不据第三方猜Cookie | U | 桌面/执行器依赖U / GUI产品 | 企业协同CLAIM / 1000+CLAIM | U | UI_ONLY，底层U |
| 14 | U | U | U / 当前程序接口U | 汽车企业矩阵CLAIM / 万级为案例宣称 | U | UI_ONLY，底层U |
| 15 | 微信公众号授权；Douyin U | U | 云产品 / Douyin U | 多公众号 / Douyin规模U | Douyin U | 非目标产品 |
| 16 | U | U | 客户端介绍 / GUI | 团队U / Douyin规模U | U | UI_ONLY |
| 17 | APIKey＋平台授权；Douyin手机唤起 | 平台托管细节U | 服务器N；Douyin需手机人工GUI | key共享账户绑定集合 / RBAC与100号U | U；教程5秒轮询建议不是rate limit | 第三方API＋用户分享 |
| 18 | Bearer或X-API-Key；Douyin认证U | U | HTTP N；Douyin发布U | U / Douyin百号U | U | 第三方开放API；Douyin未证实 |
| 19 | 扫码、Cookie文件、account别名 | 没有证明OAuth自动刷新 | 浏览器执行器在线；可headless / 初始登录GUI | 文件隔离，团队RBAC U / 百号U | 自控；平台配额U | Browser/Cookie Automation |
| 20 | 扫码、Electron隔离session/Cookie | 未证实OAuth续期 | Electron/tray进程在线 / 初始GUI，HTTP执行可不操作窗口 | profile隔离；RBAC U / 百号U | 本地队列；平台配额U | Browser/Cookie Automation |
| 21 | 扫码/Cookie；私有passport登录HTTP | U | 浏览器/服务在线；Windows非必需 / 初始登录 | 矩阵模块声明 / 百号U | 高并发声明非压测；配额U | Browser＋Cookie＋Reverse Engineering（登录） |
| 22 | Playwright扫码/Cookie | U | Electron桌面在线 / YES | 本地多号 / 百号U | U | Browser/Cookie Automation |
| 23 | Chrome CDP持久profile/Cookie | U | browser runner在线；Windows非必需 / 初始登录 | APIKey多租户机制 / 百号U | 自控；Douyin配额U | Browser/Cookie Automation |
| 24 | 本地APIKey；抖音登录需自己实现 | 不能替抖音刷新OAuth | 可headless平台模式；runner在线 / 初始登录自行处理 | 团队权限/多profile / 不等于百抖音号验证 | 套餐有控制API限额；Douyin限制U | 官方浏览器产品API＋自写自动化 |
| 25 | 本地控制API；抖音Cookie/profile自行处理 | 不能替抖音刷新OAuth | 浏览器runner在线 / 初始登录自行处理 | 团队/profile功能 / 百抖音号U | U | 官方浏览器产品API＋自写自动化 |
| 26 | APIKey；creator_v2明确传Cookie | 不替用户刷新抖音登录 | SaaS N / Cookie取得需要用户授权/登录 | U / 数据查询不代表矩阵发布规模 | Swagger标10QPS；具体合同以服务商为准 | 第三方数据API；Cookie/非官方接口风险 |

05–16 的网页说明证明产品功能或定位，不证明稳定账号 ID、底层发布授权、接口续期。UI_ONLY 的发布 Adapter 操作应拒绝为 NOT_SUPPORTED；“私有企业接口是否存在”保留 UNKNOWN，商务给出文档后才重评。

## 8. 国内产品运营迹象、价格与采购边界

本轮 13 家国内产品均查看其自有网站；页面仍可访问、下载/套餐/联系方式仍在，仅作为公开运营迹象。**不等于已核验工商、客服响应、退款或长期服务。**火山矩阵管家文档更新停在 2023 年，A5 使用 2025 年专题；应明确标旧资料。新榜矩阵通入口存在，独立子站抓取超时，本轮不声称已读到完整企业 API 文档。

| 产品 | 免费/普通套餐公开情况 | API／企业／私有化价格与收费方式 | 本轮结论 |
|---|---|---|---|
| 蚁小二 | FAQ普通订阅示例59元/月、590元/年 | API、100账号、私有化 CONTACT_SALES；需分开核价 | 普通订阅不能当API报价，[FAQ](https://xueyuan.yixiaoer.cn/article/46634) |
| 易媒助手 | 官网免费5账号/1设备/每日2次；有50/200账号、2/10设备档，当前金额未确证 | API CONTACT_SALES（存在性亦待确认） | [官方套餐](https://yimeizhushou.com/vip.html) |
| 融媒宝 | 免费档；普通中级56元/月、388元/年，高级188元/月、1298元/年 | 团队有不同档；API CONTACT_SALES | 只引述展示价，不混用团队额度，[官方购买页](https://www.rmeibao.com/buy) |
| 云略 Pro | 未找到公开可核价套餐 | 企业定制/私有化 CONTACT_SALES | 接口交付应纳入合同与验收 |
| 新榜矩阵通 | 本轮未确认公开价格 | 定制 CONTACT_SALES | “定制API”须具体到发视频 |
| 火山矩阵管家 | 未确认当前售卖与价格 | CONTACT_SALES | 先确认产品仍对外提供 |
| 发布鸭 | 官网联系/下载，当前套餐金额未核实 | 开放接口 CONTACT_SALES | 明确模拟浏览器，风险不因合同消失 |
| 坤图 | 官网有免费软件声明 | 商业API/团队完整报价 CONTACT_SALES | 免费GUI≠可接入API |
| 小V猫 | 本轮未确认对应有效套餐价 | API CONTACT_SALES；暂无文档证据 | 不继续扩展UIA |
| 创作罐头 | 本轮未确认价格 | CONTACT_SALES | 大账号数只是声明 |
| 企域新链 | 垂直企业解决方案 | CONTACT_SALES | 汽车场景，不泛化成通用API |
| 微小宝 | 公众号管理套餐存在，未核抖音相关价 | 抖音服务/API CONTACT_SALES | 不是已确认的抖音工具 |
| A5新媒体管家 | 专题介绍，有效价格未知 | CONTACT_SALES | 服务当前可用性待确认 |

其他候选：官方抖音/巨量/快手本次目标能力未找到可直接套用的商业计价，记 CONTACT_SALES/官方控制台确认，**不写免费无限**。AiToEarn、出海匠发布 API 为 CONTACT_SALES；不把视频生成模型价当发布价。开源 19/20/21/22 源码按各自许可证使用，托管机器/浏览器/维护另计；23 许可证正式文件待核。AdsPower 有免费2浏览器配置，付费控制API套餐金额当前未核实；比特浏览器有效企业/API价未核实，均 CONTACT_SALES。[AdsPower 价格页](https://www.adspower.com/pricing)

TikHub 官网展示数据请求起价0.001美元/次、免费额度0.05美元；这是数据服务展示价，不是发视频价，账户数据与大批量查询合同另核。[官方抖音数据页](https://tikhub.io/douyin-api)

## 9. 开源项目实证：代码、更新、许可、部署

GitHub 统计为本轮实时 API 查询快照，时间统一 **UTC**；Stars/Issue 会变。下表 open_issues_count **含 Issue＋PR**，不能当纯 Issue 数。检查代码不等于运行验证，未下载登录凭证或执行外部脚本。

| 项目 | 最后 commit / SHA（缩写） | Stars / 未关闭Issue＋PR | 最新 release | License | 真实实现/部署与关键限制 |
|---|---|---|---|---|---|
| [蚁小二CLI](https://github.com/yixiaoer888/yixiaoer-skill) | 2026-09-30 06:33:34 / a2722c6 | 14 / 10 | 本轮核npm 3.2.26；GitHub release 未核 | GitHub license=null；npm UNLICENSED | 商用客户端源码可读，不按某个Skill文件的MIT-0推断整个产品可自由商用 |
| [AiToEarn](https://github.com/yikart/AiToEarn) | 2026-09-18 07:18:17 / 3581f51 | 26307 / 20 | v2.5.0，2026-06-24 | MIT | Docker/自托管；国内SaaS接口与开源部署功能可能不同；自托管不自动获抖音代发布scope |
| [SAU](https://github.com/dreammis/social-auto-upload) | 2026-09-02 16:56:11 / 0012d2c | 15301 / 70 | baijiahao，2025-04-12 | MIT | 当前CLI＋Patchright浏览器；有Docker文件。README明确历史Web端不保证同步或可用 |
| [MatrixMedia](https://github.com/hanliang97/MatrixMedia) | 2026-10-03 18:05:56 / 6b43185 | 907 / 1 | v0.11.7，2026-10-03 | GPL-2.0 | Electron GUI进程提供HTTP；另有CLI。无已核实Docker一键稳定方案 |
| [Prism](https://github.com/Laihiujin/Prism) | 2026-09-09 02:01:21 / 9227ea1 | 94 / 0 | v1.1.0，2026-09-09 | Apache-2.0 | FastAPI、队列/矩阵调度、浏览器；部署脚本存在，Docker成熟运行未验证 |
| [multi-publisher](https://github.com/atxinsky/multi-publisher) | 2026-03-01 11:45:43 / 819e688 | 29 / 2 | v0.1.0，2026-03-01 | MIT | Electron IPC＋Playwright；不是稳定对外HTTP服务，无Docker服务证据 |
| [multipost](https://github.com/Shuozeli/multipost) | 2026-08-20 22:26:20 / 5a76a0e | 0 / 0 | 无 release | README声称Apache-2.0 OR MIT；GitHub license=null、未见正式LICENSE | Rust gRPC，多租户与流式任务；有Dockerfile但依赖外部Chrome/CDP环境，社区/成熟度弱 |

SAU 的 account 别名只是文件隔离，不是抖音永久账号 ID；当前 README 将 Web 后端作为历史保留。不能照旧教程启动 Flask 就声称有今天支持的生产 REST 契约。当前 CLI 文档有真实示例：sau douyin upload-video --account <name> --file <mp4> --title <title> --desc <desc> --schedule "YYYY-MM-DD HH:mm"；它仍通过浏览器完成抖音定时策略，不是官方 scheduled_at API。[CLI 文档](https://github.com/dreammis/social-auto-upload/blob/main/docs/CLI.md)

MatrixMedia 的实际接口包括 GET /platforms、GET /creative-statements、POST /changeData、POST /publish。账号以 phone 或 `persist:phone抖音` partition 选择；publishAt 是本地日期时间，由进程到点执行。多平台发布立即返回 submitted 只代表提交队列，不是所有账号作品成功。pushData 可读历史，但没有核实一个具有完整审计语义的 `GET /publish/{id}`。它减少UIA控件依赖，却没有消除浏览器DOM/扫码/Cookie风险。[HTTP 文档](https://github.com/hanliang97/MatrixMedia/blob/main/docs/http-api.md)、[server源码](https://github.com/hanliang97/MatrixMedia/blob/main/src/main/server/index.js)

Prism 有 accounts/publish/campaigns 等 FastAPI 路由和调度源码，不能把部署 `/api/status` 当发布状态。Douyin 登录源码直接操作 creator.douyin.com 私有 passport 接口和 sessionid，因此标 HIGH；并未声称每一步上传均由逆向接口完成。[publish路由](https://github.com/Laihiujin/Prism/blob/main/prism_backend/fastapi_app/api/v1/publish/router.py)、[Douyin私有登录源码](https://github.com/Laihiujin/Prism/blob/main/prism_backend/app_new/platforms/douyin_http.py)

multipost 的 protobuf 确有 Accounts.List/Get/CheckAuth、Media.Upload、Posts.Submit/GetJob/Watch/ListJobs。Watch 是 gRPC 流，不是 HTTP Webhook。排期/重试由调用方负责；Douyin 使用 Chrome CDP、DOM 文件输入与创作者管理页确认。当前 Stats 支持其他平台，未实现 Douyin 指标，故此项 NOT_SUPPORTED。[proto目录](https://github.com/Shuozeli/multipost/tree/main/crates/multipost-proto/proto)

Gitee 已检索并查看 [SAU镜像](https://gitee.com/hijoseph/social-auto-upload/blob/main/README.MD)（摘要仍为旧流程）及 MatrixMedia 指向的 [pubtw项目](https://gitee.com/gzlingyi_0/pubtw)。后者访问未能取得完整元数据，所以 **Gitee最后commit、Stars、License未核实**；使用GitHub主仓数据，不编造、不重复计数。只在搜索出现但未完成源码核验的 A2Data/auto_douyin、media-publisher 等不纳入本轮26项，不称为推荐。

## 10. 有 API 但不能替换发布核心的典型反例

**AiToEarn**：中国版真实 POST /api/v2/channels/publish/flows，publishAt 为 ISO8601；GET /api/v2/channels/publish/flows/{flowId} 与 GET /api/v2/channels/publish/records/{recordId} 返回任务/结果。记录字段有 platformWorkId、workLink，但文档明确抖音 status=8 时必须拿 schemeUrl/shortLink，由用户手机打开抖音并提交。符合“可编排”，不符合“员工仅在8502确认后完全自动发布”。不能用其国际平台或自托管宣传覆盖这一限制。[创建Flow](https://docs.aitoearn.cn/477782797e0)、[Flow详情](https://docs.aitoearn.cn/477782798e0)、[记录结果](https://docs.aitoearn.cn/477782809e0)、[人工操作接口](https://docs.aitoearn.cn/477782811e0)、[抖音教程提示](https://docs.aitoearn.cn/)

**出海匠**：有 HTTPS 开放平台、Bearer/X-API-Key、POST /open/v1/social/accounts/list 等真实通用账号接口；当前公开证据不足以证明支持中国Douyin。海外TikTok支持不算抖音能力。[开放文档](https://openapi-doc.chuhaijiang.com/introduction)

**AdsPower、比特浏览器**：可程序管理profile/打开浏览器/获得CDP；比特有 POST /browser/list、/browser/open。它们交付浏览器控制面，未交付本任务的抖音上传/排期/状态/分析 API，接入后仍要我们维护网页自动化。[AdsPower](https://localapi-doc-zh.adspower.net/docs/Udx0pH)、[比特API](https://doc.bitbrowser.net/zh/api-jie-kou-wen-dang/liu-lan-qi-jie-kou)

**TikHub**：有 Swagger 与 POST /api/v1/douyin/creator_v2/fetch_item_list，需creator Cookie，可读作品及互动数据；不是视频发布服务。只能作为数据路线研究对象，不能以它补上最后一步并宣布完成。[创作者列表](https://docs.tikhub.io/359719871e0)

学生版“简易抖音”里的 /douyin/publish/action/、/douyin/feed/ 是自建仿抖音服务；抖音短链、续火花聊天工具和普通音视频SDK也不是大陆抖音发布接口，本轮排除。

## 11. 风险与正式生产准入

| 类别 | 典型候选 | 判断与主要风险 |
|---|---|---|
| 官方API，LOW | 抖音、巨量、快手 | 限于获准scope和用途；可被撤销/限流/审核拒绝，LOW不是不会封号 |
| 官方合作伙伴 | 本轮未独立证实可交付本需求的伙伴 | 厂商说“官方合作”需可核对资质、能力、合同，不能直接授予LOW |
| 第三方API，MEDIUM待证 | 蚁小二；云略尚仅E2 | 第三方存储/账号托管、API变更、停服、ID导出、权限制约；合规性未获独立证实 |
| 第三方用户分享 | AiToEarn | 抖音需手机人工，无法无人值守；APIKey与素材云存储治理 |
| Browser/Cookie，HIGH | SAU、MatrixMedia、multi-publisher、multipost、发布鸭、坤图 | DOM改版、登录过期、人机验证、会话泄露；HTTP包装不消除底层账号风控 |
| Reverse Engineering，HIGH | Prism私有登录；TikHub部分Cookie数据路线 | 私有协议变更/授权边界不清，不推荐作为正式发布核心 |
| UI_ONLY，MEDIUM或HIGH | 国内GUI产品、小V猫 | 脆弱UI状态、窗口/在线桌面依赖；供应商底层授权未证实，不能一律说其违法 |

抖音当前协议页面标示更新2026-02-13、生效2026-02-20，包含对影响平台运行的自动化/第三方工具的限制。不能用“自己账号”“付费软件”推导所有自动化都获许可，也不能把合同违约和刑事违法混为一谈。扫码时用户应能辨识服务主体、scope、账号、撤销入口；Cookie等同登录凭证，不能发到日志、提交仓库或交给来源不明服务。[抖音用户协议](https://www.douyin.com/draft/douyin_agreement/douyin_agreement_user.html?id=6773906068725565448&ug_source=kljd_dy_js1)

本轮不对任何产品给“不会封号”的保证，不提供绕过验证码/风控的方法。供应商跑路风险采用版本固定、账号/任务/作品ID可导出、可撤销凭证、可迁移存储以及已有停机回退策略管理；不能靠高Stars替代服务合同和实际稳定性验收。

## 12. 未来 PublisherAdapter 契约建议（仅设计）

保留现有 Content / PublishPlan / PublishJob、员工确认与幂等提交语义；**没有实现下面接口，也没有改现有代码/数据库**。不统一伪造供应商端点；统一的是本系统契约。

```python
class PublisherAdapter:
    def list_accounts(self): ...
    def refresh_account(self, account_id): ...
    def upload_video(self, account_id, local_mp4): ...
    def create_publish_job(self, account_id, asset, content, request_key): ...
    def schedule_publish(self, account_id, asset, content, scheduled_at, request_key): ...
    def get_publish_status(self, provider_job_id, account_id): ...
    def list_published_videos(self, account_id, cursor=None): ...
    def get_video_metrics(self, account_id, platform_video_id): ...
```

这里只是建议签名，不把既有函数更名。建议 capability 返回 YES / NOT_SUPPORTED / UNKNOWN / LOCAL_SCHEDULER，并区分授权不足与能力不存在。结果保留 provider_account_id、platform_account_id（可能未知）、provider_job_id、provider_task_id、asset_id、platform_video_id、video_url、raw_status、last_checked_at、error/retryable。这些是未来内存/响应设计；如以后需要持久化新增列，另写兼容迁移，不能本轮修改Schema。

| 方法 | 蚁小二 | 抖音官方 | 云略Pro | MatrixMedia比较 | SAU比较 |
|---|---|---|---|---|---|
| list_accounts | GET /v2/platform/accounts | 自有OAuth注册表；原生全局列表NOT_SUPPORTED | UNKNOWN | POST/changeData读取账号会话 | CLI/config账号别名；非永久平台ID |
| refresh_account | UNKNOWN，需重新授权/刷新契约 | OAuth刷新由应用实施；撤销后重新授权 | UNKNOWN | Cookie重新扫码；OAuth自动刷新UNKNOWN | Cookie重新扫码；OAuth自动刷新UNKNOWN |
| upload_video | upload-url＋PUT | upload_video，必要时分片 | UNKNOWN | POST/publish整合上传；独立素材上传句柄NOT_SUPPORTED | CLI整合上传；独立句柄NOT_SUPPORTED |
| create_publish_job | POST/taskSets/v2；取得taskSetId，再拆task | create_video；只返回作品回执，原生异步task_id NOT_SUPPORTED | UNKNOWN | POST/publish，队列/响应需再查 | 启动CLI执行；自有job_id |
| schedule_publish | scheduledTime毫秒 | 原生NOT_SUPPORTED；LOCAL_SCHEDULER | UNKNOWN，GUI不能代替 | publishAt本地时间；进程在线 | CLI --schedule "YYYY-MM-DD HH:mm"；浏览器策略 |
| get_publish_status | GET/v2/taskSets/{id}/tasks；枚举待核 | 通用task状态NOT_SUPPORTED；作品审核终态查询UNKNOWN | UNKNOWN | /changeData历史记录；完整终态语义UNKNOWN | 通用task查询NOT_SUPPORTED；流程结果待核 |
| list_published_videos | 发布records是本供应商任务记录，不等于账号全部作品；全量UNKNOWN | 当前video.list.bind接口/许可UNKNOWN | UNKNOWN | pushData是本工具历史；全量作品UNKNOWN | 全量UNKNOWN |
| get_video_metrics | /contents/overviews；按account与作品关联待核 | 通用六项UNKNOWN；特定场景不能通用化 | UNKNOWN | UNKNOWN | UNKNOWN |

关键规则：

1. 内部 job_id 不等于 taskSetId，更不等于作品 video_id；供应商批量任务应拆分到每个账号的 PublishJob。
2. scheduled_at 内部建议带时区，保存UTC瞬间并保留Asia/Shanghai显示；蚁小二转换毫秒，MatrixMedia转换本地文本。默认定时可接受范围/秒级精度都要从获准schema确认。
3. 没有确认响应或供应商缺少幂等键时，状态进入 UNKNOWN/人工核对，不盲重试上传后的发布。request_key仅为我们内部键，**不虚构厂商已支持Idempotency-Key**。
4. 厂商“受理”映射为 SUBMITTED/PENDING 或已证实的 SCHEDULED_QUEUED，上传成功不能映射PUBLISHED。只有终态与对应作品证据到齐才回写PUBLISHED。
5. 视频审核失败、删除、仅自己可见、任务取消需分开保留原始信息；链接不能依据未核格式拼出来。缺失video_url/metric用UNKNOWN，不填0或伪造链接。
6. 没有Webhook时可以轮询；即便有回调也需要签名、去重与补偿查询。特定SDK分享回调不绑定到普通服务端任务。
7. 不增加“生成同一内容到所有账号”的默认行为；沿用现有确认、唯一内容和停机/不确定状态处理约束。

## 13. 理想流程逐阶段可达性

阶段共8个：①API可选账号 ②传本地MP4 ③程序文案/话题 ④按指定时间自动执行 ⑤返回可关联任务/作品回执 ⑥程序查询可靠终态 ⑦回收作品ID＋公开URL ⑧作品指标＋按账号分析。“确证数”只统计本任务整阶段有证据的项，不把营销宣传或未知算完整。

| 候选 | ① | ② | ③ | ④ | ⑤ | ⑥ | ⑦ | ⑧ | 判断 |
|---|---|---|---|---|---|---|---|---|---|
| 蚁小二 | YES | YES | YES表单 | YES字段 | YES taskSetId | 部分：查询YES、终态U | U | 部分：接口YES、字段实值/关联U | **5/8确证、2项部分、1项未知**；当前最接近，需要受控POC |
| 抖音官方 | 自有注册表 | YES | YES合并text | 原生N，自有排期可补 | YES作品回执，非task_id | U | 只有作品ID，URL U | U | **3/8原生整项确证**；账号/定时自建后可补，但不是已完成闭环 |
| 云略Pro | U | U | U | U | U | U | U | U | **0/8 API确证**；不允许开始Adapter编码 |
| MatrixMedia | YES本地会话 | YES | YES参数 | YES本地runner | 有队列/响应 | 部分历史记录 | U | U | **5/8接口/本地行为证据**；仍为HIGH，不作生产首选 |
| SAU | 部分本地别名 | YES | 部分话题细项 | YES定时流程 | 自有job，原生task U | U | U | U | **2/8整项确证**；CLI＋浏览器比较对象 |
| AiToEarn | YES | YES | 部分Douyin话题 | **N全自动** | YES Flow/tasks | YES记录状态 | YES字段，实际产生需人工 | U | **5/8接口整项证据**，但④硬失败；不是无人值守替代 |

上表的终态与链接“YES”仅指API契约，仍不代表做过一次真实发布。官方的3个原生整项是②③⑤；MatrixMedia的5个为①②③④⑤；AiToEarn的5个为①②⑤⑥⑦。受理与公开作品存在是不同证据。

其余候选：02仅官方广告相关能力，普通主页发片8阶段均未核实；03有快手上传/发布，但抖音8阶段全部不满足；05/06/09/11/12/13/14/15/16缺少抖音发布API，程序链路**0/8确证**；08、10只有商询或GUI证据，同为0/8。18的Douyin仍UNKNOWN，0/8。21可确认账号/上传/任务路由与调度组件，严格8阶段契约/真实结果尚不能逐项确定，**不报告完整数**；22仅GUI/IPC，不满足对外Adapter，0/8；23有账号/媒体/任务/Watch接口，但文案、作品回收与Douyin指标不完整，至少①②⑤有明确程序契约，④原生N、⑧N；24/25提供浏览器控制，发布8阶段均需另写，0/8；26只有数据查询⑧部分，发布①–⑦不成立。

## 14. 下一步最小 POC：蚁小二，分两个门槛

**本轮到选型结束，没有开始POC。**以下是下次任务的验收设计；不注册、不购买、不索取token、不绑定账号、不提交真实视频。

第一步可不触碰素材：固定 CLI 版本，核对 upload/publish/query 的请求/响应 schema，使用静态脱敏 fixture 做 Adapter 契约样例。向供应商索取：
- 中国Douyin发布能力授权依据、官方scope/合作主体、是否依赖Cookie/浏览器；
- 私有化或本地流程架构，MP4每一跳地址/存储方/删除策略，证明“local”能否真正不进第三方云；
- 两个测试账号的可用权限、ID稳定性、taskSet→task字段、全状态枚举、失败/审核定义、作品ID/URL示例；
- refresh/重新授权、Webhook、幂等/重试/取消/重复提交策略；
- 账号数/并发/QPS/日额度、团队角色与完整API/私有化报价。

**只有资料通过、且明确满足现有素材约束，才进入第二步的隔离发布测试**：未来用户另行授权使用两个非正式测试账号与三条合成短MP4，立即发布/定时发布/故意不合法参数各一次；不扫生产素材、不开生产worker，不修改8502/生产库。本轮并未要求用户提供这些账号或授权。

验收必须同时满足：账号不会串号；毫秒/时区正确；返回非空taskSet/task映射；排期回执能对应SCHEDULED_QUEUED；到点后服务无需桌面人工操作；终态可区分失败/审核/成功；成功有可核对video_id/video_url；播放/点赞/评论/分享/收藏有值或明确不支持；网络超时不产生重复发布；重新启动后能恢复追踪；绑定撤销有清晰失败；MP4出网满足约束。缺终态/ID/零出网任一核心条件即不进入生产。

若蚁小二不能满足这些条件，下一步是**官方video.create.bind权限验证**，不是继续叠加小V猫UIA，也不是把Prism私有接口当替代；若官方权限不可得，暂保留已有流程并记录阻塞，不伪造“无人值守已实现”。

## 15. 本轮边界与交付

仅新增本研究文件和短名单。未改HANDOFF、生产数据库、模型、抽帧、FAISS、发布代码、配置或worker；未启动Streamlit/执行发布集成，文档任务不需要这些服务测试。未注册、购买、签约、绑定正式账号、提交视频或上传素材。当前Xiaovcat开发暂停，不代表擅自终止任何现有运行进程。

所有候选的事实均以2026-10-05公开证据为界。未完成的客服/权限/实测环节明确留为UNKNOWN，官网价格为展示价格而非报价单。未来视频号/小红书/快手扩展需逐平台重审scope、人工要求与指标，不把“多平台支持”直接等同8阶段全自动。
