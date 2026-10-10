# 话术搜索 V1 独立验证版

复用 `video_index_fixed.db` 的现有字幕，不转写音视频，不修改原字幕、DINO、CLIP、图片排序或Web。当前**全库词法检索已构建，语义仅覆盖8个asset的pilot**，不是全库语义搜索上线。

从项目根目录运行（使用现有独立CUDA Python；文字查询默认CPU）：

```powershell
.\.venv-cuda-test\Scripts\python.exe -X utf8 -B speech_search/query.py "腰疼不一定是腰的问题"
.\.venv-cuda-test\Scripts\python.exe -X utf8 -B speech_search/query.py "这是两边肌肉受力不平横引起的" --mode fuzzy --json
.\.venv-cuda-test\Scripts\python.exe -X utf8 -B speech_search/query.py "身体各个部位都是互相连通的" --mode semantic
```

示例输入只是查询，不代表库中一定存在正确原句。尤其注意“是/不是”等否定关系：模型或模糊匹配仍可能返回含义不符的候选，需对照匹配原文及上下文。

## Python API

```python
from speech_search.query import search_speech, SpeechSearch
results = search_speech("两边肌肉受力不平衡", top_k=10)

# 多次交互应复用实例，避免每次加载模型/向量文件。
engine = SpeechSearch()
response = engine.search("左右两侧肌肉用力不均", top_k=10)
print(response["results"])
print(response["timings"], response["semantic_scope"])
```

结果包含asset_id、主文件video_id/path/name、source_video_id、first/last_segment_id、start/end、matched_text/original_text、前后句、match_type、lexical/fuzzy/semantic/final_score和timestamp_warning。时间全部来自旧Whisper段边界；上下文不改变起止时间；score不是概率。

## 构建与数据规则

- `build.py --execute`只读事实库及现有SHA资产映射，输出此目录的database.sqlite。按asset事务checkpoint续跑；不调用Whisper，不打开原视频。
- `segments`按(asset_id,start,end,normalized_text)归并，`segment_sources`保留全部原字幕ID、原文、source_video_id及转写run。倒序开始新的run，不跨run拼接。
- 规范化：NFKC、转简体、小写、移除标点空白及“嗯/呃/唉”；保留数字和“不/没/吗”等有意义字。所有原文保留，不回写事实库。
- 1–3个连续段窗口；跨段最大间隙3秒、多段最长60秒/240字符。单条长字幕保留词法能力。相同asset/start/end/规范文本的窗口归并，window_sources保留全部来源。
- FTS5独立contentless全文索引保留完整位置记录，以支持有效BM25。索引字符二元组和无声调单字拼音二元组；后者仅容忍部分同音字，多音字不保证正确。
- 精确层：二元组AND召回后验证完整规范化子串，保留原LIKE的连续文字匹配能力；不把用户的`%/_`当通配符。优先较短完整命中窗口。
- 模糊层：BM25字符候选最多300条＋拼音最多100条，最多400条做RapidFuzz。字符分=0.75×partial_ratio+0.25×ratio；拼音同式；最终fuzzy=max(字符分,0.85×拼音分+0.15×字符分)，阈值65。没有逐106万条暴力fuzzy。
- 融合：精确结果独立优先级，其余对fuzzy与semantic排名做等权RRF，k=60，不相加不同量纲原分数。各路及最终输出均归并同asset的重叠话术片段（重叠达到较短窗口一半，或起点相差≤2秒），防止重复副本霸屏。
- 新索引保留非完全相同的历史重复转写版本，避免未经核实丢掉文本；窗口不把两次转写混成连续话术，展示端会折叠同asset重叠时间。

冻结规则在common.RULES、validation/cases.json与pilot_plan.json中，评测没有调权重或搜索参数。

## 中文语义模型及明确范围

本机原来没有合适中文句向量缓存。使用[BAAI/bge-small-zh-v1.5官方模型](https://huggingface.co/BAAI/bge-small-zh-v1.5)，revision `7999e1d3359715c523056ef9478215996d62a620`。模型下载在models子目录，新增RapidFuzz/pypinyin仅安装到deps，OpenCC、PyTorch/FAISS与vendor Transformers复用现有环境。没有使用CLIP文本模型或外部推理API。

按官方方式CLS pooling、512维、FP32 L2归一化，查询加“为这个句子生成表示以用于检索相关文章：”，文档不加；最长256 token，超过部分仅语义编码截断，原文和词法索引不截断。全库仅2个窗口超过256个规范化字符。

`semantic.py`只允许不超过20个asset、150,000个窗口；当前冻结8个asset、143,391窗口的IndexFlatIP。它没有全量构建开关。模型文件hash及语义文件hash、READY、规则、范围、维数、ntotal和ID数量均检查。`--mode semantic`未就绪时拒绝运行；hybrid无语义库时可保留词法能力，返回semantic_scope=null。

## 时间异常

time_anomalies.json按原ID记录1,060条/44个asset：2–10秒为minor_tail（137条），>10秒为out_of_range（923条）。搜索命中这些记录所在窗口返回timestamp_warning=true，原start/end不缩放、不截断。这里只做筛查，未判断每条差异是否属于媒体容器或实际口播错位。

## 测试与报告

```powershell
.\.venv-cuda-test\Scripts\python.exe -X utf8 -B -m unittest discover -s speech_search/tests -v
.\.venv-cuda-test\Scripts\python.exe -X utf8 -B speech_search/evaluate.py
```

32例由现有转写文本人工选句/改写，四类各8例；不是用户独立提交的业务holdout，也没有重新听审。四层同范围主比较使用8个asset全部143,391个窗口，另记录全库词法＋pilot语义的CLI实际范围，不能把两者混成全库语义准确率。素材命中、原时间附近命中与时间偏差分开报告。

详细结果在report.md和validation/results.json。正式Web未接入；全库语义建库未开始。
