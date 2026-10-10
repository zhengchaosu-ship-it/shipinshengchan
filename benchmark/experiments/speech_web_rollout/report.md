# 话术搜索 Beta Web 接入验收

SPEECH_SEARCH_BETA_READY

- 正式话术库：318 asset，3,099,048 vectors；READY 门槛生效。
- 直接调用 FormalSearch.search(mode="semantic", top_k=10)。BGE 模型、归一化、候选数和原有窗口折叠完全沿用已验收实现；没有新增时间去重或修改分数。
- reranker、fuzzy 最终排序均未启用。Exact/Fuzzy/旧实验代码保留但不参与本入口。
- 首页面渲染全部 Top10，双列按序阅读；原文、前后句、字幕 start/end、asset/video ID、路径和 similarity 均展示。
- timestamp_warning 只提示“该时间点可能存在原字幕时间偏差”，不修改字幕时间，仍可预览。合成 UI 测试覆盖此分支。
- 话术预览从命中前 1 秒开始，保留声音，8～60 秒；浏览器加载正常，六个短预览经 PyAV 确认都有视频和音频流。

## 真实网页验证

| 测试 | 结果 |
|---|---|
| 原句、删字、错字、同义表达、长话术、跨 segment，共 6 例 | Top10/原文/前后文/时间/路径/预览通过；逐行与冻结正式 Semantic 结果一致 |
| 图片 1.png、4.png、7.png | Top10 与冻结 DINO + candidate dedup 完全一致；缩略图和预览正常 |
| CLIP 患者趴着接受治疗、按摩腰部、肩颈治疗 | 后端 Top20 与历史结果一致；页面 Top10、缩略图、预览正常 |
| 反馈 | 正确话术、正确时间 614.310 秒及备注、Top10没有找到均写入临时库成功 |
| 回滚 | false 时话术禁用，实际 DINO/CLIP 搜索仍成功；true 后话术恢复；正式配置已恢复 true |

功能验收不等于准确率重新评测。删字和错字例 GT 位于第 2 条，没有人为提升到 Top1。原字幕识别错误和原时间误差仍保留。

## 性能

最终页面 6 次热查询，小样本 P95。Web 总耗时来自页面，精度约 10ms，包含反馈持久化；不含网络传输、浏览器绘制或点击后短预览生成。

| 阶段 | median ms | P95 ms |
|---|---:|---:|
| 文本 embedding | 6.711 | 8.060 |
| FAISS | 286.867 | 301.782 |
| metadata / 上下文 | 31.146 | 38.183 |
| 页面结果字段适配 | 0.011 | 0.013 |
| 搜索计算总计 | 326.041 | 341.485 |
| Web 服务端总计（含反馈） | 380.000 | 397.500 |

首次加载观测为 2.70～6.98 秒，受模型/FAISS 缓存状态影响，不纳入热查询统计。

## 数据保护与迁移

- DINO、CLIP、Speech 正式目录全部文件 size/mtime 未变；小文件 SHA256 未变。正式话术 FAISS/metadata 的验收 size/mtime 与 READY 报告一致。
- 原字幕库、话术源库、GT、现有 Semantic/图片/CLIP 查询代码保持未修改。
- 原反馈库仅迁移 CHECK 约束允许 speech，自动备份 search_feedback.db.before-speech.bak；所有既有 searches/feedback 记录逐条内容摘要一致，外键检查通过。
- 测试使用 XUNFRAME_TEST_FEEDBACK_DB 指定临时库；正式服务已清除该变量并恢复原反馈库，没有开发反馈污染。
- speech 原查询、Top10、matched_text、semantic_rank/score、window/source segment ID 保存于不可改写快照；selected_rank 与反馈中 asset/time/note 关联到该快照。
- 52 项 Web 回归通过；独立话术适配/反馈测试 9 项通过（其中 3 项也包含在 Web 回归中）。语法检查通过。

## 启动和独立关闭

启动：项目根目录“启动寻帧.bat”，实际使用 .venv-cuda-test/Scripts/python.exe -m streamlit；地址 http://127.0.0.1:8502。
在 benchmark/experiments/dino_july_web/search_config.json 将 speech_search_enabled 改为 false 并刷新网页，只关闭话术；恢复 true 即重新启用。必要时重新运行启动脚本。

## 文件

修改：
- benchmark/experiments/dino_july_web/app.py
- benchmark/experiments/dino_july_web/ui.py
- benchmark/experiments/dino_july_web/ui.css
- benchmark/experiments/dino_july_web/feedback_ui.py
- benchmark/experiments/dino_july_web/search_config.json
- benchmark/feedback/store.py
- HANDOFF.md

新增：
- benchmark/experiments/dino_july_web/speech_adapter.py
- benchmark/experiments/dino_july_web/test_speech_adapter.py
- benchmark/experiments/dino_july_web/test_speech_ui.py
- benchmark/feedback/migrate_speech.py
- benchmark/experiments/speech_web_rollout/：验收代码、临时反馈库、日志和报告。

生产配置最终为 candidate_dedup=true、text_search_enabled=true、speech_search_enabled=true；DINO/CLIP 索引与排序未变。
