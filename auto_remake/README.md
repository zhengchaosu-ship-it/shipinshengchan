# 自动复刻 V0.2 — 参考视频解析与 DINO 素材候选

已实现：单条本地 MP4 → OpenCV CPU 切镜 → 质量过滤及代表帧 → 显式调用既有正式 DINO 查询 → 多帧 asset 聚合 → 每镜头最多5个候选 → JSON 与离线双栏 HTML。所有新增代码、测试、文档、输出均在 `auto_remake/`；没有安装新依赖，不启动或重启任何服务。

本轮只实现 DINO 视觉候选，不接 Speech、CLIP、ORB、LLM、自动剪辑或剪映草稿。单独执行原 `analyze` 仍保留 V0.1 的解析行为，只有显式执行 `match` 才加载正式 DINO，并更新 `matches`。检索分数和时间共识都不是 GT。

## V0.2 两阶段使用

先解析，检查 `report.html` 中镜头和代表帧，再执行匹配。复用寻帧的现有解释器（不运行 Web 启动器）：

```powershell
& .\.venv-cuda-test\Scripts\python.exe -X utf8 -B -m auto_remake.analyze 'D:\参考视频\真实二创.mp4' --task-id real_demo
& .\.venv-cuda-test\Scripts\python.exe -X utf8 -B -m auto_remake.match auto_remake/results/real_demo/analysis.json --device cpu --candidate-pool 100
```

本轮真实验收唯一输入：`D:\Users\Desktop\BJ\88888888 (1)(1).mp4`。实际27.433333秒，823帧。主结果位于 `results/real_88888888_v02_cpu/`。最初沙箱进程不能读取既有 transformers 目录，保留错误记录于 `results/real_88888888_v02/`；随后使用有读取权限的原解释器进程完成 CPU 检索，没有更换、安装或修改任何依赖。两次使用同一解析结果，未用 GT，也未为此片调切镜或融合阈值。

匹配前保存 `analysis_only.json`、`report_analysis_only.html`。已有匹配尝试的目录拒绝重跑，避免覆盖证据；新运行用新 task-id。更新已有 JSON/HTML 前留唯一 `.bak`，JSON 原子替换。匹配失败保留解析 JSON 并写 `matching_error.json`。低置信度并不意味着程序失败。

### 正式查询复用与隔离

`dino_adapter.py` 仅通过文件导入既有 `search.py` 和 `search_adapter.py`，构造 `FormalV1RepairedAdapter`，调用 `search_with_timings(image, k=100)`。没有另写 encoder/FAISS 逻辑或复制 Web 检索代码。沿用正式 READY 门槛、DINO预处理和模型、metadata与shard只读连接，以及冻结 Top500 → 每asset最多5帧、至少10秒间隔 → 前100条规则。100是去重后的**frame候选上限，不保证100个asset**；实际数量写入逐帧诊断。只将返回的已有 JPEG 写到本任务，绝不为候选解码原素材。

加载前后对正式索引目录和既有查询代码/配置记录文件集合、大小、mtime；变化则拒绝标记匹配完成。动态导入关闭字节码写入，不向生产目录生成 pycache。默认 `--device cpu`；可显式指定 `cuda` 复用同一编码器，本次只跑 CPU。没有修改生产配置。

### 聚合、时间与置信度

同一 query 对同一 asset 至多支持一次，保留该 query 的最好rank、最好similarity及全部返回时间候选；逐帧原始排名和计时在 shot 的 `frame_results`。asset 跨帧支持数严格优先，辅助项上界小于一票：

`aggregated_score = (support + 0.45×mean(1/rank) + 0.25×mean(clamp((similarity+1)/2)) + 0.20×temporal_bonus)/(query_count+1)`

temporal_bonus 为 high=1、medium=0.5、low=0。不直接累加相似度。分数越高只表示本策略排序靠前，不能解释成正确概率或跨视频准确率。

时间规则：用 `source_time - (query_time - shot_start)` 作偏移锚点，每query选一个偏移相差不超过2秒的候选；优先更多query共识，再残差，再rank。无动态规划。参考跨度至少1秒、来源严格递增、观察速度比0.5–2，才视为可用连续证据；3票以上且覆盖>=60%为 high，2票为 medium，其他 low。起止估计用1倍速偏移中位数外推；low 输出 null。它不验证真实剪辑速度，也没有来源总时长约束，不可直接当剪辑点。

`source_timestamps` 在 high/medium 时是共识轨迹的来源点，low 时是逐帧最好命中；`best_hit_source_timestamps` 始终保存逐帧最好命中，`temporal_track` 解释共识用了哪些query与候选。缩略图显示该asset在所有query里的最佳排名命中，可能与估计区间不同；报告分别标注缩略图时间和来源估计，并展开时间共识证据。

置信度阈值固定，未用此片GT调参：无候选/支持比例<60%/平均similarity<0.65 → `LOW_CONFIDENCE`；至少3张query全支持、时间high、平均similarity>=0.75、与Top2聚合分差>=0.05 → `HIGH_CONFIDENCE`；其他 → `NEEDS_REVIEW`。高置信也只是规则证据，需人工确认。

### 人工 GT（不参与检索）

`gt_template.json` 初始全部 `unjudged`，命中率为 null。检索时不读取任何 GT。以后可复制模板、填写 reviewer、每shot judgement（top1_correct/top5_correct/not_found/unable_to_judge）、正确候选rank、切镜合理性和时间正确性，再汇总：

```powershell
& .\.venv-cuda-test\Scripts\python.exe -X utf8 -B -m auto_remake.evaluate auto_remake/results/real_demo/analysis.json --labels auto_remake/results/real_demo/my_gt.json
```

A=切镜合理但检索失败；B=切镜错误；C=正确asset但时间不准；D=等价素材/重复片段。模板以参考路径、切镜、query和候选指纹绑定结果，防止错用旧标注。Top1/Top5定义为人工确认asset命中率，分母仅含可判断且已标注镜头，C类另外统计。未知不能自动视为失败或成功。

### 本轮真实验收结果

| shot | 参考区间（秒） | query数 | Top1 video_id | score | 支持 | 时间共识 | 标记 |
|---|---|---:|---:|---:|---:|---|---|
| 1 | 0–9.500 | 5 | 185 | 0.92840 | 5/5 | high（3帧轨迹） | NEEDS_REVIEW |
| 2 | 9.500–20.566667 | 5 | 18 | 0.93655 | 5/5 | medium（2帧轨迹） | NEEDS_REVIEW |
| 3 | 20.566667–23.233333 | 3 | 185 | 0.91804 | 3/3 | low | NEEDS_REVIEW |
| 4 | 23.233333–27.433333 | 3 | 18 | 0.91798 | 3/3 | low | NEEDS_REVIEW |

4个镜头，共16张代表帧、20条asset候选及20张候选缩略图。video_id 18 和185同名 `2026年06月15日16时46分12秒.ts`，路径与asset_id不同，不自动合并成同一asset。

CPU解析4.823266秒，成功匹配阶段8.748325秒（含模型/索引加载4.067184秒），其中embedding1.258912秒、FAISS2.423535秒、聚合0.010118秒。总处理13.571591秒，每分钟参考视频29.682702秒。计时不含首次权限失败、人工查看等待、CLI启动、最终JSON/HTML写出；是单条冷加载实测，不是50条吞吐基准。

全部16张参考帧和20张候选缩略图已可视检查。1秒网格及切点前后图检查显示：9.5秒有明显跳转；20.566667秒为同场景小跳变，有待人工确认是否剪接；23.233333秒有短暂推近，可能是缩放特效触发切镜。同场景不等于同一连续原片，未据此手改边界。没有发现大量字幕导致的碎切，但未逐帧播放验收，不能排除漏切。

所有shot目前都需人工确认，HIGH_CONFIDENCE为0。展示的Top1来源帧与参考中服装或人物组合存在差异；有较低排名候选更接近参考构图，但本轮不调整排序、不据缩略图冒充GT。参考画面的大面积背景、叠加字幕和缩放特效可能干扰全图特征，原因尚未通过对照实验确认。无GT，Top1/Top5真实命中率、正确asset但时间错误数量、完全召回失败数量均不能据此计算。

25项单测覆盖原解析层和新增聚合/时间共识/低置信标记/逐帧查询/诊断/备份/失败/GT绑定及统计。真实检索确认319个asset、1,843,351帧，保护清单前后相同。HTML的内容、36个图片引用、转义和离线资源经过静态检查；浏览器工具禁止本地file协议，未绕过限制，因此不宣称完成浏览器布局渲染验收。详情见实际任务的 `validation.json` 和 `validation.md`。

## V0.1 解析层基础说明（以下仍适用于 analyze）

## 运行

从项目根目录运行（PowerShell，复用现有解释器，不加载项目配置模块）：

```powershell
$taskPython = (Get-Content config.json -Raw | ConvertFrom-Json).paths.python_executable
$env:PYTHONIOENCODING = 'utf-8'
& $taskPython -B -m auto_remake.analyze 'D:\参考视频\中文 名称.mp4' --task-id reference_demo
```

输出固定为 `auto_remake/results/<task_id>/`。省略 task-id 自动生成时间和随机后缀；已有任务目录拒绝覆盖。task-id 禁止路径分隔符、Windows 保留名等。输入仅接受一个本地 MP4，不递归扫描任何目录。建议先用 30 秒至 2 分钟短片验证。

- `analysis.json`：完整结果的最终标记，UTF-8、标准 JSON，无 NaN。
- `frames/*.jpg`：最大宽度 640（不放大小图），保持比例，JPEG 90。
- `report.html`：双击浏览器离线查看，包含总时长、每镜头时间区间和所有代表帧，图片可点击查看。
- `error.json`：失败原因；失败时不生成 `analysis.json`，可能保留部分图片用于排查。

JSON 的 `image_path` 相对于 `analysis.json` 所在目录。HTML 使用同一相对路径，转义文本和 URL；没有外部资源、脚本或网络请求。移动结果时复制整个任务目录，不能单独移动 HTML。

退出码 0 表示解析产物生成完成，不代表镜头切分准确或每镜头都有图片。`status=needs_review`、`warnings` 和每镜头的 `selection_status` 必须一并检查；输入/解码/写文件失败退出 1。

## 算法与阈值

第一遍顺序读取视频，每帧缩小到宽度最多 320 后计算相邻 BGR 图像的平均绝对差、灰度黑像素比例、Laplacian 方差。只保存每帧少量统计信息，不缓存整段像素。切镜在新镜头的第一帧发生，区间为 `[start, end)`，覆盖整段解码视频，包括黑场；不自动删除黑场或将它拼到相邻镜头。

第二遍顺序解码至最后一张选中帧，仅保存代表帧，不逐帧 seek。解码通过 OpenCV FFmpeg 后端，显式关闭硬件解码，不调用 Torch/CUDA。

| 参数 | 默认值 | 含义 |
|---|---:|---|
| cut_threshold | 28 | 相邻 BGR 平均绝对差达到此值，触发候选切镜（0–255） |
| min_shot_seconds | 0.35 | 距上次切镜不足此秒数时抑制候选切镜；最后一段可以更短 |
| boundary_guard_seconds | 0.12 | 已检测镜头边界两侧保护范围内不选代表帧 |
| transition_threshold | 12 | 与前一帧或后一帧的差达到此值，不选该帧，作为轻量转场/剧烈变化过滤 |
| black_level / black_ratio | 18 / 0.95 | 至少 95% 灰度像素不高于 18，认定黑帧 |
| blur_threshold | 35 | 缩小后的灰度 Laplacian 方差低于此值，认定严重模糊/低纹理帧 |
| short_seconds / long_seconds | 2 / 8 | `<2秒` 目标1张；`2–8秒` 目标3张；`>8秒` 最多5张 |
| analysis_width / image_width | 320 / 640 | 统计图和导出图最大宽度，保持比例 |

所有参数通过 `--settings auto_remake/settings.json` 覆盖（JSON 键即表内字段；例如 `{"cut_threshold": 32, "blur_threshold": 25}`）。参数类型和范围经过校验，未知键报错；实际参数写入结果便于复现。生产建库的 1 秒抽帧间隔没有修改，本模块自身检测采用参考视频逐帧统计。

代表帧优先目标为镜头 10%/50%/90%，长镜头增加 30%/70%，短镜头取 50%。从整个镜头的合格帧中选最近的未使用帧，时间相同时优先清晰度；目标位置恰好模糊时尝试邻近合格帧。保证帧号不重复、时间位于镜头内，但没有承诺内容语义去重，合格片段很窄时可能相邻。

拒绝原因按黑帧、模糊、转场顺序计数，每帧只计一个首要原因。不降低阈值兜底：全无合格帧输出 `query_frames=[]` 和 `no_usable_frames`；不够目标张数输出 `insufficient_usable_frames`。这些情况保留镜头并将总体状态标记 `needs_review`。

时间优先采用解码器单调 PTS，减去首帧 PTS 使视频从 0 开始；缺失/非单调时回退 `frame_index/fps` 并警告。末帧显示时长用尾部最多30个间隔的中位数估计。容器声明帧数和实际解码数相差超过1帧时拒绝生成成功结果；无法保证发现所有解码器静默丢帧。末帧时长是估计值，VFR 的回退时间也不应作为精确剪辑依据。

局限：简单差分可能把闪光、快速运动判成切镜；可能漏掉相似画面切换、慢叠化和不足0.35秒的连续快切。转场过滤只是边界保护和相邻变化启发式，不能保证排除所有叠化帧。低纹理的正常画面也可能被模糊阈值过滤。未验证自然二创片的切镜准确率。

## 稳定数据与未来接口

核心 JSON 示例（附加诊断字段允许扩展）：

```json
{
  "schema_version": "1.0",
  "reference_video": "D:/参考视频/示例.mp4",
  "duration": 4.5,
  "shots": [{
    "shot_id": 1,
    "start": 0.0,
    "end": 4.5,
    "duration": 4.5,
    "query_frames": [{"timestamp": 1.2, "image_path": "frames/example.jpg", "frame_index": 36}],
    "matches": []
  }]
}
```

`models.py` 定义 `Shot`、`QueryFrame`；`matcher.py` 保留 `ShotMatcher` Protocol 的 `match_shot(shot: Shot) -> list[dict]`。通用占位函数仍明确抛出 `NotImplementedError`，避免隐式全局模型加载；V0.2 显式使用 `dino_matcher.DinoMatcher`，解析器自身不调用检索。

V0.2 已由 `match.py` 显式协调 DINO matcher。`SpeechMatcher` 和 `ClipMatcher` 仍未实现；未来可在实例构造时绑定所需上下文，核心 Shot/JSON 无需依赖特定模型。语音转写、剪辑与草稿不在当前模块实现范围。

## 小规模验证（2026-09-28）

没有在常规 `test_videos/` 发现现成短片，本轮使用确定性合成视频 `tests/test_videos/合成 参考视频.mp4`（320×180、24 FPS、36秒、864帧）。颜色背景、棋盘纹理、小圆点运动；6–7秒全黑，10–12秒局部模糊片段，15–17秒整镜头模糊。真值保存在同名 `.truth.json`。这是合成测试，不能代表真实二创效果。

| 镜头 | 区间（秒） | 时长（秒） | 代表帧数 | 结果 |
|---|---|---:|---:|---|
| 1 | 0–6 | 6 | 3 | 前/中/后 |
| 2 | 6–7 | 1 | 0 | 24帧全黑，明确留空 |
| 3 | 7–15 | 8 | 3 | 避开10–12秒模糊片段 |
| 4 | 15–17 | 2 | 0 | 48帧严重模糊，明确留空 |
| 5 | 17–23 | 6 | 3 | 前/中/后 |
| 6 | 23–36 | 13 | 5 | 分布于整个镜头 |

识别6个镜头，5个内部边界与预设一致，未发现误切或漏切（仅限此合成片）。输出14张代表帧；源视频864帧（JSON `decoded_frame_count` 是第一遍的源帧数量，不是两遍读取次数之和）。此次 CLI 的 CPU 分析及抽帧计时为 **0.571188秒**，不含解释器启动和随后 JSON/HTML 写入时间，不是多次性能基准。

10项 unittest 通过，覆盖切镜和全时长覆盖、时间戳/图像/质量、JSON/离线HTML及转义、抽帧档位/过渡过滤、缺帧状态、参数验证、目录越界/重跑保护、写出失败不伪报、解码中断和 PTS 回退、matcher未实现行为。已完成模块 Python 文件语法检查。未运行旧 Streamlit/图搜/文字检索集成测试，本模块无这些依赖，且任务要求不启动共享服务。

可视检查：逐行查看 `results/synthetic_36s_v01/contact_sheet.jpg` 中全部14张代表帧，均清晰，镜头颜色/标签正确，黑场和全模糊镜头无图片，时间顺序正确。已检查 HTML 文本、6个镜头区块、14个本地图片引用及无网络资源。浏览器工具安全策略拒绝 `file://`，因此**未完成 HTML 在浏览器中的实际布局渲染验收**；未换用其他浏览器或服务绕过该策略。

初次单测遇到本机 Python 3.14 `TemporaryDirectory` 权限问题，测试改用模块内普通临时目录并检查绝对路径后清理，后续10项测试全部通过。编辑既有文件前保留了 `.bak` 备份。

## 复测与人工步骤

```powershell
& $taskPython -B -m unittest discover -s auto_remake/tests -v
& $taskPython -B -c "import pathlib, py_compile; [py_compile.compile(str(p), doraise=True) for p in pathlib.Path('auto_remake').rglob('*.py')]"
# 已附带合成片；只有文件不存在时才执行生成器（拒绝覆盖）。
& $taskPython -B -m auto_remake.tests.make_sample
# 使用新的 task-id，保留已有证据。
& $taskPython -B -m auto_remake.analyze 'auto_remake/tests/test_videos/合成 参考视频.mp4' --task-id synthetic_recheck --input-description '36秒合成测试'
```

人工打开新任务的 `report.html`，检查总时长36秒、6个镜头、数量3/0/3/0/3/5，图片无破损和网络依赖；点击代表帧确认清晰、标签对应镜头。对照真值检查6/7/15/17/23秒五个边界，以及镜头3的图片避开10–12秒。真实参考片验收仍待另行提供并逐镜头人工标注。

上述合成验证为 V0.1 历史记录；V0.2 的主验收仅使用前文指定真实视频，完成候选报告后停止，不继续自动剪辑。

## V0.3：DINO + Speech 独立证据验证（2026-09-28）

新增 `speech_matcher.py`（只转写参考片、薄适配正式纯Semantic Top20）、`multimodal_evidence.py`（按参考时间重叠关联、独立语音锚点和跨模态时间证据）、`multimodal.py`（可续跑的独立编排）、`multimodal_report.py` 和 `protection.py`。旧 V0.1/V0.2 入口、模型、正式索引和 Web 不变。

固定规则在 `multimodal_rules.json`，每个任务另存 `frozen_rules.json`。不相加 DINO 和 Speech score；重叠的1/2/3段话术不算多份独立证据；同一asset的远距离时间区域作为不同假设；时间连续性允许0.5–2倍速度及有限剪切，只给同源识别标签，不输出剪辑timeline。信息量等级是长度启发式，HIGH不是ASR准确度或匹配概率。

```powershell
$env:PYTHONPATH='D:\video_search_tool\benchmark\experiments\embedding_comparison\deps;D:\video_search_tool'
$env:HF_HUB_OFFLINE='1'
# 新任务使用新task-id；不要覆盖本次实测。失败续跑同一命令加 --resume。
.\.venv-cuda-test\Scripts\python.exe -X utf8 -B -m auto_remake.multimodal 'D:\Users\Desktop\BJ\88888888 (1)(1).mp4' --task-id another_v03
.\.venv-cuda-test\Scripts\python.exe -X utf8 -B -m unittest discover -s auto_remake/tests -v
```

本次实测在 `results/real_88888888_v03/`：`analysis.json`、`reference_speech.json`、`report.html`、`report.md`、`validation.json`。27.433秒参考片产生4个shot/16帧、ASR15段、42个话术窗口，其中39条有效，正式Speech返回780条结果。DINO逐帧查询和V0.2相同配置；没有复制正式向量或新建索引。

最可能候选均为 `AST-30BDD9631F51D4865F01` / video65 / `2026年05月10日18时07分31秒.ts`。证据级别为 **0 HIGH / 3 MEDIUM / 1 NEEDS_REVIEW**，首选模态一致0/4，两路候选池共同支持4/4。shot2–3有暂定同源链，但不是双方强证实；全片时间存在倒序和大跳跃。`MULTIMODAL_NOT_READY`，不自动剪辑。成功阶段累计27.721秒，约60.629秒/分钟参考片，含冷加载，不含开发和人工查看。详细边界和每shot原因见报告。

原始base INT8 ASR文本保留，未因本片结果改写或调整证据门槛。额外只读提取4张DINO现成JPEG查看话术时间区域；未解码原素材。1051个正式文件size/mtime_ns及小文件SHA256前后相同。HTML做结构与本地图片读取验收，未宣称浏览器布局渲染已验收。

## V0.4：候选原素材内部时序对齐（2026-09-28）

新增 `asset_local.py`、`sequence_alignment.py`、`alignment_report.py`、`align.py`、`alignment_rules.json` 及12项测试。只读取V0.3既有证据选Top5 asset；分别读取这些asset的正式DINO shard向量、Speech指定embedding_row，不加载/搜索全库FAISS。只重新编码参考query，未重建源embedding或索引。当前代码是独立实验，没有修改Web或生产检索。

```powershell
# 使用前文相同PYTHONPATH及本地离线环境；新任务名避免覆盖已有结果。
.\.venv-cuda-test\Scripts\python.exe -X utf8 -B -m auto_remake.align auto_remake/results/real_88888888_v03 --task-id another_v04
# 中断续跑：同一命令加 --resume；已完成任务拒绝再次覆盖。
```

每asset执行16张视觉/39条话术局部检索，各保存Top20峰值。话术1/2/3段共享segment不能重复当独立锚点，参考时间构造6个非重叠高信息窗口。先语音粗路径，再时间带视觉复核，最后联合有序DAG路径；不同模态用独立证据等级归一化，不直接相加cosine。允许前跳/少量重复，大幅回退高罚；遗漏、语义分数损失和coverage显式记录。该粗到细方法不保证全部可能路径全局最优。

固定参数先写 `alignment_rules.json`，任务内保留 `frozen_rules.json`，没有按本片结果搜索参数。累计小回退还做全局2秒容差验收，不能串联小倒退规避限制；此验收不改路径或分数。Sequence形状HIGH不是HIGH_CONFIDENCE_SOURCE，质量、coverage、候选差距均需单独过门槛。

实测产物 `results/real_88888888_v04/`：Top5选择video65/18/185/16/205，最终序列排名65/205/18/185/16，对齐分0.4984/0.4011/0.3551/0.3407/0.2953。video65路径收拢至01:58:26–01:58:43，但有效coverage仅56.4%，视觉coverage27.9%，39条片内Top1仅13条处于该路径时间带；中段部分台词换成弱相似句，末段强锚点被跳过。第一、第二分差0.0973仍不足以弥补证据缺失，结论 **ALIGNMENT_NOT_READY**，不能进入正式source timeline/自动剪辑。

总计算10.091秒，含参考query编码与模型加载；asset-local Speech1.418秒、DINO4.580秒、sequence alignment0.169秒。读取40,983条DINO/85,985条Speech向量，没有再次扫描整个向量库。48项回归通过；286个共享DINO命中和101个共享Speech命中分数差均<1e-6。1141文件保护清单一致（含V0.3、正式索引、模型、字幕、Web）；报告5个SVG/50个图片引用可读，浏览器布局未验收。HTML、完整局部结果、参考统一时间轴、置信门槛和人工观察均在独立结果目录。

## V0.5：整段话术序列 + 局部音频验证（2026-09-28）

新增 `transcript_alignment.py`、`audio_alignment.py`、`localize.py`、`localization_report.py`、`localization_rules.json` 和7项单测。此入口仅针对已授权的88888888参考片及V0.3/V0.4既有证据，不是通用剪辑工具。使用现有15条ASR，DINO与单段Semantic仅产生19个候选asset；读取这些asset的原字幕，副本/转写run分开做Smith–Waterman局部对齐。支持1↔1、1↔2、2↔1、1↔3、3↔1，不用Semantic分数定位，不改原字幕或GT。

```powershell
# 使用前文相同PYTHONPATH；新输出使用新的task-id。
.\.venv-cuda-test\Scripts\python.exe -X utf8 -B -m auto_remake.localize --task-id another_v05 --stage text
.\.venv-cuda-test\Scripts\python.exe -X utf8 -B -m auto_remake.localize --task-id another_v05 --stage audio
.\.venv-cuda-test\Scripts\python.exe -X utf8 -B -m auto_remake.localization_report auto_remake/results/another_v05
```

两阶段顺序执行；同task-id续跑复用已有asset文本/音频checkpoint和有限PCM缓存，校验规则与保护清单。音频只处理文本Top3不同asset的最佳时间带，各自±30秒，最多180秒；实际合计192秒原素材音频，不扫描整场直播。使用PyAV真实音频PTS、16k mono、MFCC+delta、subsequence DTW，8个互不重叠音频块，未下载模型、安装依赖或重新ASR。最后读取候选带已有DINO向量复核16张参考帧，没有新建任何embedding/FAISS。

结果 `results/real_88888888_v05/`：第一video65 / `AST-30BDD9631F51D4865F01`，01:58:25.820–01:58:34.820的原字幕路径匹配ref1–4，4/15可靠、coverage28.29%。01:49和01:54各2/15，不能接在开头之后当正向连续轨迹。音频仅2/8块可靠且一致：ref0–4.44→source7105.8325–7110.2325，ref4.92–8.24→source7110.7525–7114.0325。这是开头的局部声音证据，不是整片裁切边界；声学时间为20ms特征网格帧中心。DINO WEAK（4/16支持）。第二video183仅1/15文本、0/8音频，第三video73同样0/8音频。

结论 **SOURCE_LOCALIZATION_NOT_READY**。整片trusted source start/end均null，未自动剪辑。报告明确区分可靠开头和未验证后段；01:49/01:54本轮只比较字幕，未继续追加音频扫描。成功计时阶段累计12.532秒（不含参考MFCC预计算、保护检查、报告和人工等待，不是完整端到端墙钟）。55项测试通过，1220个正式/历史文件大小和mtime_ns、小文件SHA256前后相同。`analysis.json`、`results.csv`、`audio_anchors.csv`、每asset路径、report.md/html、validation.json均已保存。HTML结构/图片可读性已检查，浏览器布局未验收。

## V0.6：多来源候选与Source Segment Graph（2026-09-28）

新增 `source_switching.py`、`source_switching_rules.json`、`source_graph.py`、`source_switching_report.py` 和6项测试，旧V0.3/V0.4/V0.5文件与代码不改。只处理本次88888888案例：开头0–8.24秒原样保留ANCHORED及三路证据，明确不是绝对GT。后段7个5秒窗、2.5秒步进；24条原ASR组合query重新全库Semantic召回，12张既有DINO query向量重新全库Top500，再原生产去重，未重新编码源素材。

```powershell
# 仍用前文CUDA测试venv及PYTHONPATH；HF_HUB_OFFLINE=1；新任务名避免覆盖历史。
.\.venv-cuda-test\Scripts\python.exe -X utf8 -B -m auto_remake.source_switching --task-id another_v06 --stage recall
.\.venv-cuda-test\Scripts\python.exe -X utf8 -B -m auto_remake.source_switching --task-id another_v06 --stage audio
.\.venv-cuda-test\Scripts\python.exe -X utf8 -B -m auto_remake.source_graph auto_remake/results/another_v06
.\.venv-cuda-test\Scripts\python.exe -X utf8 -B -m auto_remake.source_switching_report auto_remake/results/another_v06
```

同task-id复用已完成checkpoint。全库召回仅选候选；原字幕片内对齐读取14个asset，每窗最多3个asset、各最多2个文本时间带进入音频。实际9个请求合并成5个有限带，3个asset共374.90秒源音频。使用V0.5原MFCC/DTW阈值；对已测试音频块做两个不重叠半段的一致性复核，仅用PCM缓存，半段不重复当额外锚点。DINO最后只在声音候选附近读取已有向量。

产物 `results/real_88888888_v06/`：`source_segment_graph.json`、召回/片内/声音详细JSON、`candidate_results.csv`、`report.md/html`、`validation.json`。新可靠节点ref11.40–14.12→video65的01:49:25.713–01:49:28.413，声音0.9739、两半0.9753/0.9726，字幕0.7833、DINO WEAK。它相对开头约01:58是同asset向前取片后跳回早段的证据，允许跨节点倒序，未把它当错误或接成连续原片。

直接声学覆盖7.76→10.48秒（28.29%→38.20%）。图中来源已分配10.96秒，额外0.48秒为用户要求保留的开头锚点间隙；UNRESOLVED16.473333秒。后段5个来源候选小段只有1个严格通过；14.12–17.04和末尾25.22–27.42半段失败，17.04–20.78声音通过但“好不好”触发旧否定启发式、DINO仅WEAK，保守辅助门槛未通过。报告明确这是潜在漏接受，不是声学召回失败；未据本片改阈值。未知节点source为空，候选嵌套保存，不供自动裁片。

结论 **MULTISOURCE_LOCALIZATION_NOT_READY**（新增严格覆盖2.72秒未到事前设定的5秒提升门槛）。没有证明跨asset拼接；已有证据指向同asset不同时间段，其余未知。61项回归通过，1279个生产/历史文件轻量清单一致。没有新ASR/模型/embedding/索引，没有ORB/reranker/CLIP实验、Web改动或裁片。HTML只检查结构与图片可读性，未验收浏览器布局。
