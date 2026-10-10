# 话术搜索正式全库语义索引

正式目录：`speech_search/index/formal_v1/`。原试验`semantic_pilot/`与32例验证数据保留，原`query.py`行为不变；正式查询使用新的`formal_query.py`。

## 查询（不接Web、不融合）

在项目根目录使用当前CUDA Python；文字查询默认CPU：

```powershell
.\.venv-cuda-test\Scripts\python.exe -X utf8 -B speech_search/formal_query.py "腰疼不一定是腰的问题"
.\.venv-cuda-test\Scripts\python.exe -X utf8 -B speech_search/formal_query.py "两边肌肉受力不平衡" --mode exact
.\.venv-cuda-test\Scripts\python.exe -X utf8 -B speech_search/formal_query.py "两边肌肉受力不平横" --mode fuzzy --json
```

API：`FormalSearch().search(query, top_k=10, mode='semantic')`，重复查询复用实例。只允许exact/fuzzy/semantic，三种能力独立返回分数，不使用旧融合排序。Semantic保持Top200候选与原有同asset重叠窗口折叠规则，保留原始相似度，未重新调参。

每条返回window_id/window_size、asset_id、主文件video_id/path/name、source_video_id、first/last_segment_id、起止时间、原文与前后句、分数和timestamp_warning。标记为warning的时间不得静默截断或缩放。库内的相似句可能不是同一次口播，必须核对原文与时间。

## 正式构建和续跑

```powershell
.\.venv-cuda-test\Scripts\python.exe -X utf8 -B speech_search/build_formal.py --execute
```

同一命令用于续跑；不要删除结果。默认batch=64，可显式降低`--batch-size`，编码器、模型、tokenizer、CLS pooling、256 token上限、FP32/L2全部复用pilot的Encoder。精简pilot构建上限保持原样，正式建库单独实现。

- manifest记录固定模型revision、Encoder源码hash、模型文件hash、源库和原记录/去重/窗口计数、受保护文件状态。
- build_plan.sqlite为稳定row_id/window_id的只读输入快照与逐batchcheckpoint。每个batch先写vectors.f32并fsync，再以SQLite FULL事务提交状态；只复用已提交的batch。
- vectors.f32按plan row_id固定偏移保存512维float32。单条文本错误记录failures；系统性CUDA/模型异常停止并保留已提交结果，修复环境后续跑，不把整个库误标为坏文本。
- metadata.sqlite用连续faiss_row绑定所有字段和embedding_row。只有成功编码的记录进入FAISS，不混入失败占位数据。
- 原始视频、Whisper、DINO与CLIP均不参与此构建。
- 崩溃发生在向量写入但checkpoint提交之前时，该未提交batch可重新编码；已提交batch不会重跑。当前记录包含一次停止后复用前128向量的真实续跑验证。

## 验收与复测

```powershell
.\.venv-cuda-test\Scripts\python.exe -X utf8 -B speech_search/validate_formal.py
.\.venv-cuda-test\Scripts\python.exe -X utf8 -B speech_search/evaluate_formal.py
```

严格验收检查全部metadata与原窗口逐行一致，向量数量、维度、归一化、逐row FAISS内容、window_id、318个asset、文件路径、时间基本范围、warning、失败和续跑保护。已有时长警告只标记，不作为重新转写的理由。READY只表示索引完整性；查询质量单独报告，不能把数量一致当准确率通过。

原32例来自转写文本选句/改写，是冻结开发验证集，未独立听审。新增20例来自另外20个asset，评测前冻结；不据测试结果调模型或融合。附近命中沿用GT起点在返回窗口内±2秒，误差基准是原Whisper时间，不能视为口播真实对齐误差。

运行结果、性能、例外和接入判断以正式目录的report.json、query_tests.json、final_report.md为准。当前任务不修改寻帧Web。
