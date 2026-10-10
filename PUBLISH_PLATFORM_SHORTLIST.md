# Publisher Adapter 候选短名单

研究日期：**2026-10-05（Asia/Shanghai）**。完整证据、26项筛选、评分及API映射见 [研究报告](PUBLISH_PLATFORM_RESEARCH_2026.md)。本文件仅保留值得继续推进的 **3 个**，没有开始接入。

## 明确推荐

**技术接口第一推荐蚁小二；严格遵守素材不进第三方云时，获得权限后的抖音官方直连是生产优先方向。**目前没有任何候选经过本项目真实账号/发布测试。不存在“今天直接切换生产”的推荐。

| 优先级 | 候选 | 档 / 分数 | 下一步 | 当前阻塞 |
|---|---|---|---|---|
| 1 | [蚁小二官方CLI/API](https://www.yixiaoer.cn/cli) | A* / 85 | 首个最小POC候选；先做接口契约和部署链路核验 | 标准上传使用供应商存储；local≠零出网。终态、作品ID/URL、权限来源未实测 |
| 2 | [抖音官方开放平台](https://developer.open-douyin.com/) | B / 58 | 确认video.create.bind能否获批，核实作品结果查询权限 | 上传/创建真实；原生定时NOT_SUPPORTED；通用审核终态和作品指标UNKNOWN |
| 3 | [云略Pro](https://www.yunluepro.com/) | B / 22 | 仅做私有化/API资料和商业可行性验证 | 官网声明API/私有化；尚无可调用路径、schema、认证及状态契约 |

A*仅表示已经有真实程序接口、值得做技术验证；不是许可上传素材到第三方，也不是正式生产准入。第三名分数较低仍保留，是因私有化方向有战略价值；在拿到实际API证据前不能编码Adapter。

## 1. 蚁小二：最接近现有 PublishJob

公开源码实际实现：
- GET /v2/platform/accounts：账号列表。
- GET /storages/{bucket}/upload-url＋PUT：上传本地文件。
- POST /taskSets/v2：创建任务；返回taskSetId；逐账号platformAccountId。
- scheduledTime：13位Unix毫秒时间戳。
- GET /v2/taskSets/{taskSetID}/tasks：任务查询。
- /contents/overviews、/platform-accounts/overviews-v2、/overview/incremental：作品/账号/增量数据接口。

证据：[固定commit源码](https://github.com/yixiaoer888/yixiaoer-skill/tree/a2722c6095f57abf2e345dca637bdded44fa34df/internal/api)、[Douyin表单](https://github.com/yixiaoer888/yixiaoer-skill/blob/a2722c6095f57abf2e345dca637bdded44fa34df/skills/yixiaoer/references/platforms/video/douyin.md)、[渠道规则](https://github.com/yixiaoer888/yixiaoer-skill/blob/a2722c6095f57abf2e345dca637bdded44fa34df/skills/yixiaoer/references/cli/publish-channels.md)。

适合8502→PublishJob→Adapter的理由：可以把账号、素材、排期和供应商任务映射到现有模型。最大待证项是**底层抖音授权、零第三方素材出网、任务终态及作品回收**。数据接口存在不等于Douyin每项指标都有值。Webhook/账号自动续期为UNKNOWN；API/私有化价格CONTACT_SALES。风险MEDIUM、难度MEDIUM。

## 2. 抖音官方：权限成立后的长期方向

真实接口：
- POST /api/douyin/v1/video/upload_video/
- POST /api/douyin/v1/video/create_video/
- OAuth2逐账号授权，scope video.create.bind需申请。

原生scheduled_at为NOT_SUPPORTED，应由自有排期器到点创建作品；返回item_id/video_id不等于审核通过。SDK分享create_video事件不能冒充直接REST创建审核回调。旧列表正文不可用及video_status字段变更，必须向平台核实现行查询能力。[上传](https://developer.open-douyin.com/docs/resource/zh-CN/dop/develop/openapi/video-management/douyin/create-video/upload-video)、[创建](https://developer.open-douyin.com/docs/resource/zh-CN/dop/develop/openapi/video-management/douyin/create-video/video-create)、[状态字段公告](https://developer.open-douyin.com/forum/bulletin/post/6736c38048f043667b75f70a)

企业号、MCN、服务商身份都不自动授予发布scope。风险LOW指获准范围内官方调用；权限与实现难度HIGH。此次能力商业条件CONTACT_SALES/官方确认，不能承诺免费无限。Douyin与TikTok是独立接口体系。

## 3. 云略Pro：私有化备选，先补证据

官网有企业矩阵、API、私有化描述，但本轮未找到可调用的发布接口文档。优先索取账号列表、二进制上传、指定时间发布、任务状态、作品ID/URL、数据分析、Webhook、认证/续期、限流与报价。**全部API字段当前UNKNOWN**，不能伪造 /publish 或计划中的实现。风险MEDIUM、难度HIGH、价格CONTACT_SALES。[官网证据](https://www.yunluepro.com/)

## 下次最小POC与停止条件

选 **蚁小二**，先只核验固定版本schema、脱敏响应样本、权限来源与素材传输架构。供应商必须证明本地/私有化方案符合“不把素材上传第三方服务器”；否则不做真实上传，转向官方权限核验。

资料通过且未来获得测试授权后，再用两个非正式账号、三条合成短MP4验证立即/定时/失败三种情况。验收目标：
1. 正确选账号，无串号；title/description/topics及毫秒时区正确。
2. taskSet→每账号task可关联；排期受理不提前写PUBLISHED。
3. 到点无需桌面人工提交；可查询成功、失败、审核状态。
4. 成功可核对原生video_id与公开video_url；指标缺失明确UNKNOWN。
5. 网络超时、重启和撤销授权不会盲重试导致重复发布。
6. 素材、凭证、权限和限流满足已有项目约束。

缺任一核心证据（尤其零出网、终态、作品ID/URL），停止进入生产。云略只做文档验证；官方先确认scope。未来若需要数据库字段，单独设计兼容迁移。

## 本轮结果与未做事项

26个候选，12个有真实网络API/SDK，6个有Douyin发布相关程序接口；**3个优先推进，1个技术POC首选，0个已证明生产替代**。MatrixMedia/SAU/Prism等浏览器或Cookie路线、AiToEarn的手机人工提交、UI_ONLY产品均不进入短名单。

只完成选型与两份文档；未注册、购买、签约、绑定账号、上传素材、提交视频、修改发布系统、运行集成或继续Xiaovcat UIA开发。现有运行进程未被擅自停止。

