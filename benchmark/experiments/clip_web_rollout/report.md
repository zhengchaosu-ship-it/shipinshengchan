# 正式CLIP文字搜索接入验收

**TEXT_SEARCH_PRODUCTION_READY**。服务地址 http://127.0.0.1:8502 。启动方式保持根目录启动寻帧.bat。

## 接入与保护

- 图片：原search_adapter.py逐字节未改变。DINO formal_v1_repaired → Top500 → 每asset最多5帧、至少10秒 → 原similarity顺序Top10。ORB关闭。
- 文字：新增独立text_adapter.py → 既有clip_index.query.TextSearch（CPU）→ CLIP formal_v1 Top20；页面前10。未实现新模型、翻译、去重或rerank。
- 缩略图：CLIP index_id/frame_id → metadata frame_number/source_shard → 原DINO JPEG。路径限于正式repaired目录，仅只读打开源SQLite。
- 三个正式目录dino_index/formal_v1、dino_index/formal_v1_repaired、clip_index/formal_v1共987个文件集合、大小和mtime_ns前后相同；无索引改写或重建。
- 页面分别显示DINO/CLIP版本、319素材、约507小时；文字额外显示362,752画面和5秒采样。结果展示asset_id、video_id、文件名、timestamp、similarity、缩略图、路径和原短预览入口。

## 安全门槛和关闭开关

CLIP adapter在创建引擎前检查report存在且complete、严格验收READY且检查项均通过、必要索引文件非空、源目录和report/validation/metadata数量一致。原TextSearch加载FAISS后，在模型加载前再次校验512维、真实ntotal=metadata=report。失败只影响文字模式。

配置：benchmark/experiments/dino_july_web/search_config.json，字段text_search_enabled。false后重启寻帧，文字提示暂不可用；true后重启恢复。当前true。已验证false不改变DINO版本、candidate_dedup或图片目录加载；最终恢复原配置字节。UI用独立缓存，修改配置需要重启。

## 回归与Web验收

40项轻量测试通过，包括缺文件/NOT_READY拒绝、真实ntotal不匹配在模型前拒绝、文字关闭不影响图片、线程安全、缩略图映射、原图片去重、UI和反馈、CLIP原有测试。初次测试夹具未关闭SQLite造成Windows临时目录清理失败，已修正并全部重跑通过。

真实索引轻量回归：地狱素材1、4、7三张图片Top10 frame_id/顺序/分数匹配原冻结结果；实际候选500，candidate_dedup=true，ORB=false。5条中文Top20逐项匹配建库验收快照，全部字段和JPEG可读。未知中文及否定句拒绝。

真实8502浏览器验收：

| 输入 | 查询/缩略图/预览/反馈 |
|---|---|
| 患者趴着接受治疗 | 全部通过；正确时间及备注成功写入 |
| 按摩腰部 | 全部通过 |
| 肩颈治疗 | 全部通过 |
| 患者坐着，老师站在旁边 | 全部通过 |
| 老师给患者按摩背部 | 全部通过 |
| 地狱素材1.png | 全部通过，DINO结果不变 |
| 地狱素材4.png | 全部通过，DINO结果不变 |
| 地狱素材7.png | 全部通过，DINO结果不变 |

每次均检查页面结果和首项预览，video readyState=4、无播放错误，预览从命中点前1秒附近开始。前序已生成的预览缓存长度约5.45–6.7秒，沿用既有预览缓存逻辑，无改动。文字后端保存20项，页面显示10项；图片仍保存10项。

反馈复用现有数据库和schema。已从真实数据库核对5条text和3条image记录：原query、index_version、英文prompt、完整TopK frame_id及分数、选择rank/asset、时间/备注均一致。8条标记CLIP_WEB_ACCEPTANCE的测试记录已逐ID归档到browser_feedback_verified.json后清理；已有搜索/反馈记录行哈希无变化。未清理用户其它记录。

文字仍有原先的姿势、部位或角色偏差；部分Top10来自同一asset相邻画面。本轮只观察，没有新增文字去重参数。功能通过不等于语义准确率达标。

## 性能

正式CPU后端预热后，5条文本各3次，共15次。单位ms：

| 阶段 | median | P95 |
|---|---:|---:|
| text embedding | 10.73 | 12.23 |
| FAISS Top20 | 33.97 | 34.53 |
| metadata组装 | 0.50 | 0.70 |
| thumbnail组装 | 4.52 | 6.36 |
| 查询总计算（不含缩略图） | 45.16 | 46.79 |
| adapter总计算（含缩略图） | 49.50 | 52.56 |

计时随调用返回，不共享last_timing。网页首次搜索含模型/索引加载约3.29秒，暖查询计算时间不包含Streamlit渲染和视频预览生成。

## 文件改动

生产代码/配置共5个：新增text_adapter.py；修改app.py（独立文字入口/库标识/反馈版本/Top20）、ui.py（显示asset_id）、search_config.json（文字开关）、clip_index/query.py（只增加分项计时API，原接口及结果保持不变）。

测试与文档：新增test_text_adapter.py，修改test_ui.py、Web README.md和根HANDOFF.md；本目录新增verify.py、finalize.py、各项验收JSON/日志/截图及本报告。修改前备份保留。search_adapter.py、反馈store/schema、CLIP common模型/翻译代码、原预览生成函数、启动器均未修改。

本任务完成后停止，无后续模型、排序或自动剪辑开发。
