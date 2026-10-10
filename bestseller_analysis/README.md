# 带货爆款视频分析模块

这是一个与生产寻帧完全隔离的本地分析模块。它不连接 `video_index_fixed.db`，不读取或修改生产 FAISS 索引，也不加载或改变 MobileNetV2/ORB 检索逻辑。

## 能力边界

- 已自动化：视频元数据、faster-whisper base INT8 ASR、镜头边界、镜头时长、人脸抽样、字幕 OCR、业务级 Content Segment、钩子/产品衔接/信任/CTA 机器初标、阶段节奏、重复模块、真实结构聚类、Gold候选和复刻候选。
- 需要人工复核：产品是否真实出现、人物身份、医疗/夸张表达、特殊二创、字幕颜色、BGM/音效、最终成交话术。
- 所有自动标签都保留时间、原文、来源和置信度；状态使用 `machine_labeled_needs_review`，不会伪装成人工真值。

## 运行

```powershell
$py = (Get-Content -Raw config.json | ConvertFrom-Json).paths.python_executable
& $py -X utf8 -B -m bestseller_analysis "D:\Users\Desktop\爆款视频" `
  --output "D:\video_search_tool\bestseller_analysis\results\batch_20_v1"
```

同一命令可断点复用已经生成的 ASR、视觉扫描和 OCR。只重建最终分析用 `--force`；只重做某阶段可用 `--force-asr`、`--force-visual` 或 `--force-ocr`。

## 输出

```text
results/<batch>/
├── REPORT.md                  # 横向统计、共同结构、模板与复刻候选
├── BUSINESS_REPORT.md         # 本轮主要报告：内容/销售/产品/信任/CTA/节奏关系
├── aggregate.json             # 可机读汇总
├── business_aggregate.json    # 业务语义层汇总
├── gold_examples.json         # HOOK/PRODUCT/PROOF/CTA候选（待人工批准）
├── replication_candidates.json # 下一步自动复刻测试候选
├── dataset.sqlite             # 可继续增量扩展的数据仓库
├── review.csv                 # 人工修订销售阶段和风险的工作表
├── review.html                # Review服务使用的本地HTML
└── videos/<video_id>/
    ├── analysis.json          # 单条完整分析
    ├── asr.json               # ASR原文和时间戳
    ├── visual_scan.json       # 镜头、采样、人脸证据
    ├── ocr.json               # 字幕OCR与位置/大小
    ├── contact_sheet.jpg      # 人工画面复核总览
    ├── content_segments.json  # 业务片段：主角色+多标签+证据+节奏
    ├── business_analysis.json # 单条业务结构、CTA上下文与重复模块
    ├── business_report.md     # 单条业务报告
    └── report.md              # 单条可读报告
```

SQLite 使用模块自己的表：`videos`、`asr_segments`、`shots`、`sales_segments`、`labels`、`business_videos`、`content_segments`。加入新视频后重新运行即可重算横向统计；生产数据库 Schema 不受影响。

## 人工复核闭环

### 第一轮人工审核 V0.1（当前推荐入口）

双击根目录 `打开带货第一轮人工审核.bat`，或运行：

```powershell
$py = (Get-Content -Raw config.json | ConvertFrom-Json).paths.python_executable
& $py -X utf8 -B -m bestseller_analysis.human_review_server `
  "D:\video_search_tool\bestseller_analysis\results\batch_20_v1" --port 8505
```

三个独立入口：

- Gold候选：`http://127.0.0.1:8505/gold`，只审核现有25条候选，支持审核组A/B/C筛选。
- CTA专项：`http://127.0.0.1:8505/cta`，只审核机器未识别CTA的7条视频，展示完整业务时间线。
- 复刻候选：`http://127.0.0.1:8505/replication`，只审核9、7、8、3、19，不自动替人工选最佳视频。

人工数据只写入 `results/batch_20_v1/human_review/`：`human_gold_data.json`、`cta_review.json`、`replication_review.json`、`review_progress.json`。机器原始JSON保持只读。25+7+5项全部完成后，页面才允许生成 `ROUND1_REVIEW_REPORT.md` 和 `round1_review_statistics.json`。

### 全量Content Segment旧入口

1. 双击根目录 `打开带货分析审核.bat`，或运行：

```powershell
$py = (Get-Content -Raw config.json | ConvertFrom-Json).paths.python_executable
& $py -X utf8 -B -m bestseller_analysis.review_server `
  "D:\video_search_tool\bestseller_analysis\results\batch_20_v1" --port 8504
```

2. 页面可播放原视频并跳到片段，修改起止时间、`primary_role`、多标签、产品可见性、展示类型、信任机制、错误原因和备注。
3. 勾选“批准为Gold Data”并保存后，反馈进入 `review_feedback.json`；页面同时自动导出 `reviewed_segments.json` 和只含人工批准项的 `human_gold_data.json`。
4. 机器候选与人工修订分开保存，原始证据不会被覆盖。

## 业务角色

支持：`HOOK`、`PROBLEM`、`CONSULT`、`EXPLANATION`、`DEMO`、`PRODUCT_BRIDGE`、`PRODUCT_INTRO`、`PRODUCT_VALUE`、`PRODUCT_DEMO`、`PROOF`、`TESTIMONIAL`、`CALL_RESULT`、`AUTHORITY`、`TRUST`、`CTA_SOFT`、`CTA_DIRECT`、`CTA_URGENCY`、`CTA_END`、`OTHER`。

每段只有一个 `primary_role`，但可有多个 `function_tags`、`trust_mechanism` 和 `sales_mechanism`。结构允许任意角色重复，不使用固定8槽。

## 数据质量

- ASR 使用项目已验证的本地 `faster-whisper base`，中文、INT8、CPU；不访问网络。
- 镜头边界为低频像素变化初标，渐变、推拉和快速闪切需人工复核。
- OCR 只抽样钩子帧和固定间隔审阅帧，不代表逐帧字幕全文；完整口播以 ASR 为主。
- 长视频内可能有多轮成交循环，报告保留重复阶段，避免误压成一条短链。

## 自主研究 V0.1

现有20条机器分析可在不重跑ASR/视觉分析、不写生产环境的情况下复现实验：

```powershell
$py = (Get-Content -Raw config.json | ConvertFrom-Json).paths.python_executable
& $py -X utf8 -B -m bestseller_analysis.autonomous_research `
  "D:\video_search_tool\bestseller_analysis\results\batch_20_v1" `
  --output "D:\video_search_tool\bestseller_analysis\results\batch_20_v1\autonomous_research_v01" `
  --pool "D:\video_search_tool\content_pool\results\consult_conversion_v1_v01\segments.jsonl"
```

研究将“小妙招/小灵招”优先解释为课程商品，明确动作且无商品语境才解释为普通技巧。输出包含 `AUTONOMOUS_RESEARCH_REPORT.md`、`NEXT_STEP.md`、序列模式、候选选材模拟和5条复刻规划；只生成计划，不生成视频或剪映草稿。

### 3.mp4 DEMO / CTA 缺口补全

唯一下一步可单独复现：

```powershell
$py = ".\.venv-cuda-test\Scripts\python.exe"
$env:JULY_SEARCH_DEVICE = "cuda"
& $py -B -m bestseller_analysis.demo_cta_gapfill_3
& $py -B -m bestseller_analysis.gapfill_review_server --port 8506
```

打开 `http://127.0.0.1:8506/` 可按 `HOOK → CONTENT → PROOF → DEMO → PRODUCT → CTA → PROOF` 左右对照播放参考片段和候选。输出只写入 `autonomous_research_v01/demo_cta_gapfill_3_v01/`；DINO、CLIP、Speech和字幕库均只读。状态为machine-derived candidate plan，不生成正式视频或剪映草稿。
