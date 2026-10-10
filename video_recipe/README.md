# Video Recipe V0.1（3.mp4 旁路 POC）

本模块只把现有 `3.mp4` 分析和本地内容池转换为：

```text
Reference Evidence → Reference Timeline → Video Recipe → Build Result
```

它不安装或依赖 Hypit，不复制 Hypit 源码，不使用 SVML Runtime、HyperFrames、Studio 或 WhisperX；不生成 MP4、剪映草稿或 Variant，也不写生产数据库/索引。

## 生成结果

在项目根目录运行：

```powershell
.\.venv-cuda-test\Scripts\python.exe -B -m video_recipe.build_v01
```

固定只读取 `bestseller_analysis/results/batch_20_v1/videos/3/`、`autonomous_research_v01`、现有 `content_pool` 和已存在的 Template Editing 预览。输出到 `video_recipe/results/3_v01/`：

- `reference_evidence_3_v01.json`
- `reference_timeline_3_v01.json`
- `video_recipe_3_v01.json`
- `build_result_3_v01.json`
- `recipe_review_3_v01.html`

## Review 页面

```powershell
.\.venv-cuda-test\Scripts\python.exe -B -m video_recipe.review_server --port 8506
```

打开 `http://127.0.0.1:8506/`。页面只读，按参考顺序显示 Reference Node、Anchor、Business Role、候选和 Satisfy 状态；候选优先复用已存在的 Template Editing MP4 预览，否则读取原本地素材的指定时间段。本轮不会生成新预览。

## 边界

- Recipe 是现有复刻规划的 7 节点业务骨架，不是 21 分钟原片的逐帧剪辑时间线。
- Anchor 使用已有 ASR Content Segment 时间做近似定位，没有逐词强制对齐。
- DEMO 没有已验证视觉证据时只能是 `PARTIAL`。
- CTA 必须同时满足行动动词、小妙招课程指向、购买/报名/下单语境，否则不允许成为最终选中素材。
- `variant_id` 与 `candidate_selection` 仅保留接口，没有生成 Variant A/B/C。

## 3.mp4 单条可播放复刻预览 V0.1

该步骤只读取已经冻结的 `video_recipe_3_v01.json` 与 `build_result_3_v01.json`。5个 `SATISFIED` 节点固定使用 Build Result 已选候选；DEMO Top1 完成解码和抽样画面检查后可用 `PARTIAL_DEMO` 临时进入；CTA 永远保持 `UNRESOLVED` 并从预览中省略。

```powershell
.\.venv-cuda-test\Scripts\python.exe -B -m video_recipe.preview_v01 --include-partial-demo
```

只使用已有 `bin/ffmpeg.exe` 做统一规格转码与硬切拼接，保留原声，不添加字幕、特效、BGM、AI画面或正式包装。输出：

- `preview_timeline_3_v01.json`
- `preview_3_v01.mp4`
- `preview_quality_3_v01.json`
- `preview_review_3_v01.html`

左右对照页：

```powershell
.\.venv-cuda-test\Scripts\python.exe -B -m video_recipe.preview_review_server --port 8507
```

打开 `http://127.0.0.1:8507/`。页面左侧播放原始 `3.mp4`，右侧播放硬切预览，下方显示7个Recipe节点、替换素材和保留状态。
