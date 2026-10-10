# video_search_tool 开源项目复用审计

> 审计日期：2026-09-30  
> 审计范围：只读调查、代码阅读、架构对比和复用建议  
> 本次变更：仅新增本报告；未修改生产代码，未安装依赖，未读写 `video_index_fixed.db`、FAISS 索引或素材库

## 1. 结论先行

当前项目不应再自行开发以下底层能力：

1. **ASR 解码、VAD、词级时间戳基础能力**：继续直接使用 `faster-whisper`，不要另写 ASR 引擎。
2. **通用镜头边界检测**：优先采用 PySceneDetect；现有简单帧差检测保留为回退和对照，不再继续扩展成完整场景检测框架。
3. **剪映标准草稿对象、轨道、片段、关键帧、字幕等序列化**：继续直接使用 `pyJianYingDraft`。当前项目已经这样做了，不存在“用它替换自研方案”的迁移问题。
4. **静音/停顿/运动驱动的机械裁剪**：需要时调用 auto-editor 独立 CLI，不自行重写同类算法。
5. **ASR 文本选择到时间区间、区间合并、字幕重映射**：不引入完整 FunClip；只移植并修正其少量纯逻辑，接入现有 faster-whisper 数据结构。

真正值得自研的是项目的差异化层：

- 带货视频的“开头钩子—痛点—证明—卖点—CTA”等领域结构定义、标注和识别；
- 爆款参考视频与本地素材之间的跨模态候选召回、证据融合、顺序约束和可解释匹配；
- 结合现有 MobileNetV2/FAISS、DINO、CLIP、BGE、ORB、截图寻帧的多级检索与重排；
- 多素材切换、去重复、时长预算、节奏约束和人工复核工作流；
- 稳定的剪映版本适配层、黄金草稿样本和回归测试；
- 面向本地素材库的资产身份、路径映射、缓存和失败恢复。

四个重点问题的明确答案：

| 问题 | 结论 |
|---|---|
| NarratoAI 能否作为“爆款分析 + 自动剪辑”的基础框架？ | **不建议。** 它是围绕 LLM 文案、定时抽帧、配音、字幕、合成和独立任务流构建的完整应用，与本项目的本地检索、已有索引和证据链重叠不高，整合反而会形成第二套系统。归为 **C：借鉴设计**。 |
| pyJianYingDraft 是否应直接替换自研剪映草稿格式？ | **它已经是现有 `jianying_auto` 的核心依赖。** 应停止新增底层 JSON 序列化，标准能力交给它；仅保留剪映 11.5、复合片段/贴纸等必要适配补丁。归为 **A + B**。 |
| FunClip 的“ASR 文本 → 时间轴 → 自动剪辑”能否复用？ | **能复用数据流和少量纯函数，不能直接把整个项目当依赖。** 其时间戳假设、MoviePy 1.x、FunASR 模型栈和若干已知 bug 不适合直接进入生产环境。归为 **B**。 |
| PySceneDetect 能否直接作为 20 条带货爆款视频的镜头切分器？ | **可以作为首选候选直接调用。** 先对 20 条视频做旁路标注评测，再决定默认用 `AdaptiveDetector` 还是 `ContentDetector`；不改库、不重建索引。归为 **A**。 |

---

## 2. 当前系统基线与审计边界

审计以代码现状而不是旧文档中的规划为准。当前系统已经具备：

- `video_index_fixed.db`、MobileNetV2 1280 维 L2 特征和 FAISS `IndexFlatIP`；
- ORB、pHash、颜色等二次校验，以及截图寻帧；
- 本地 `faster-whisper base` CPU INT8 字幕识别；
- 独立 DINO、CLIP、BGE 语音索引；
- `auto_remake` 中的相邻帧差切镜、镜头代表帧、DINO/语音匹配、顺序对齐、MFCC+DTW、素材切换图；
- `template_editing` 中的 8 槽位口播匹配和人工审核；
- `jianying_auto` 中基于 `pyJianYingDraft 0.3.0` 的剪映草稿生成，以及对剪映 11.5/复合片段的定制补丁。

因此，本报告中的“复用”默认采用以下边界：

- 第三方组件不得直接写生产数据库和 FAISS；
- 第三方输出先保存为独立 JSON/CSV/缓存，再由薄适配层读取；
- 不更改 MobileNetV2、Normalize、L2、FAISS 1280 维和 `faiss_meta.pkl` 三元组；
- 不替换已验证的 faster-whisper、ORB 和截图寻帧；
- 不把素材上传到云服务；
- 不因采用一个项目而引入它的整套 Web UI、账户体系、任务数据库或云 API。

### 2.1 评估等级

- **A：直接复用，不再自行开发**：使用稳定库 API 或独立 CLI；本项目只写薄适配层。
- **B：复用核心代码，再做适配**：选择少量模块或算法，保留许可证声明，修正数据模型和已知问题。
- **C：只借鉴设计，保留现有实现**：不引入其运行时和核心代码。
- **D：没有合适成熟方案，必须自行开发**：通常是本项目的领域差异化能力。

工作量口径：XS 为 0.5–1 人日，S 为 1–3 人日，M 为 3–7 人日，L 为 1–3 周，XL 为 3 周以上。均为实现前估算，不含生产级大规模回归。

### 2.2 调查方法与可重复性

- 读取六个指定仓库默认分支的最新源码快照、README、License、依赖清单和核心模块；
- 通过 GitHub 仓库元数据、最新提交和公开 Issues 核对活跃度与风险；
- 对扩展候选先按本地优先、许可证、活跃度、Windows/GPU 可行性筛选，再读取官方仓库资料；
- 仅做静态阅读，没有执行第三方代码、下载模型或安装依赖；
- 当前配置解释器中确认已有 `pyJianYingDraft 0.3.0` 和 `faster-whisper 1.2.1`，未安装 PySceneDetect、FunClip、WhisperX、FunASR、OpenTimelineIO 或 auto-editor；
- Star/Fork、提交时间和 Issues 状态是 2026-09-30 的快照，不应当作长期固定事实。

---

## 3. 六个指定项目总览

Star/Fork 是 2026-09-30 的 GitHub 快照，会持续变化。

| 项目 | Star / Fork | 最近推送 | License | 直接依赖 | 复用等级 | 总结 |
|---|---:|---|---|---|---|---|
| [NarratoAI](https://github.com/linyqh/NarratoAI) | 11,258 / 1,551 | 2026-09-17 | MIT | 否 | C | 独立 LLM 视频生产应用，不宜成为现有系统底座 |
| [pyJianYingDraft](https://github.com/GuanYixuan/pyJianYingDraft) | 4,468 / 677 | 2026-09-26 | Apache-2.0 | 是，且已使用 | A + B | 标准草稿能力直接复用；版本差异由薄适配层处理 |
| [PySceneDetect](https://github.com/Breakthrough/PySceneDetect) | 5,211 / 523 | 2026-09-21 | BSD-3-Clause | 是 | A | 作为镜头边界检测器，先做 20 条视频旁路评测 |
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper) | 25,632 / 2,101 | 2025-11-19 | MIT | 是，且已使用 | A | 继续作为 ASR 基础设施，不重复造轮子 |
| [FunClip](https://github.com/modelscope/FunClip) | 6,356 / 756 | 2026-09-16 | MIT（模型另计） | 否 | B | 只适配文本选段与字幕时间重映射逻辑 |
| [auto-editor](https://github.com/WyattBlue/auto-editor) | 5,395 / 673 | 2026-09-19 | Unlicense（发布物另核） | 非 Python；CLI | A（限定用途）+ C | 直接用于静音/运动裁剪；不作为语义剪辑框架 |

---

## 4. 指定项目逐项审计

### 4.1 NarratoAI 0.8.7

1. **GitHub 地址**：[linyqh/NarratoAI](https://github.com/linyqh/NarratoAI)
2. **Star/Fork**：11,258 / 1,551。
3. **最近更新时间**：最近推送 2026-09-17；最新提交 `9fa69e0` 是文档更新。近期提交以 README、推广和文档合并为主，不能只用“最近推送”推断核心代码迭代强度。
4. **License**：MIT。
5. **主要功能**：主题/文案驱动的视频生产、定时抽帧、视觉 LLM 分析、配音、字幕、FFmpeg/MoviePy 合成、剪映草稿输出、Web UI 和任务编排。
6. **与现有系统重合**：抽帧、ASR/字幕、片段裁剪、视频生成、剪映草稿和任务编排；与现有 FAISS/DINO/CLIP/BGE 索引、ORB 和截图寻帧没有直接集成。
7. **是否已重复实现**：是，通用媒体处理与草稿编排大多已有；其“文档型视频”视觉分析并不等价于现有爆款复刻证据链。
8. **是否可直接作为 Python 依赖**：不建议。它是应用而非稳定 SDK，依赖 MoviePy、LLM provider、UI、任务配置和自身数据模型。
9. **是否适合部分复用代码**：有限适合。可参考 `app/utils/video_processor.py` 的 FFmpeg 抽帧回退、`app/services/clip_video.py` 的裁剪容错；若复制代码必须保留 MIT 声明并写针对性测试。
10. **是否适合只借鉴架构**：适合。可借鉴任务阶段、缓存、错误降级和服务边界，但不复制其整套应用骨架。
11. **Windows 支持**：可运行，但强依赖 FFmpeg、字体、路径和多媒体依赖配置；其部署形态不是现有 Windows 本地工具的即插即用库。
12. **RTX3060 12GB / RTX3080 10GB 适配**：媒体处理本身可 CPU/FFmpeg；核心视觉分析默认依赖外部或 OpenAI-compatible LLM。若强制本地视觉模型，10–12GB 显存会限制模型大小和吞吐，而且属于新的模型验证工作。
13. **接入工作量**：作为完整底座为 XL；仅借鉴 FFmpeg 容错为 S。
14. **主要风险**：引入第二套任务/配置/媒体模型；云 LLM 与“素材不上传”冲突；自带剪映 JSON 构建器会与现有 pyJianYingDraft 体系重复；定时抽帧可能遗漏短镜头；最近问题仍涉及 LLM 参数、批量生产和 TTS 稳定性，例如 [#287](https://github.com/linyqh/NarratoAI/issues/287)、[#274](https://github.com/linyqh/NarratoAI/issues/274)、[#267](https://github.com/linyqh/NarratoAI/issues/267)。
15. **最终建议**：**C**。不要把 NarratoAI 作为“爆款分析 + 自动剪辑”的基础框架；只借鉴任务编排和媒体处理的容错设计。

核心阅读位置：[`frame_analysis_service.py`](https://github.com/linyqh/NarratoAI/blob/main/app/services/documentary/frame_analysis_service.py)、[`video_processor.py`](https://github.com/linyqh/NarratoAI/blob/main/app/utils/video_processor.py)、[`clip_video.py`](https://github.com/linyqh/NarratoAI/blob/main/app/services/clip_video.py)、[`jianying_draft_builder.py`](https://github.com/linyqh/NarratoAI/blob/main/app/services/jianying_draft_builder.py)、[`task.py`](https://github.com/linyqh/NarratoAI/blob/main/app/services/task.py)。

### 4.2 pyJianYingDraft 0.3.0

1. **GitHub 地址**：[GuanYixuan/pyJianYingDraft](https://github.com/GuanYixuan/pyJianYingDraft)
2. **Star/Fork**：4,468 / 677。
3. **最近更新时间**：2026-09-26；最新提交 `6bb2d06` 修复同一视频片段多次混合模式时的保留逻辑；2026-09-25 新增 `trange_seconds`。
4. **License**：Apache-2.0。
5. **主要功能**：剪映草稿文件夹、草稿脚本、素材、轨道、视频/音频/文字/贴纸/特效/滤镜、关键帧、转场、模板载入和部分 UI 控制。
6. **与现有系统重合**：与 `jianying_auto` 完全同域。
7. **是否已重复实现**：当前项目并非完全重复实现，而是**已经以它为底层依赖**，再对剪映 11.5、复合片段和元信息做 JSON 补丁。应避免未来再写一套标准轨道/片段序列化。
8. **是否可直接作为 Python 依赖**：可以；当前配置解释器已经安装 `pyJianYingDraft 0.3.0`。建议固定精确版本或提交，并把升级放入独立兼容性测试。
9. **是否适合部分复用代码**：适合。标准草稿能力直接调用；库暂未覆盖或高版本不稳定的能力由现有适配层处理。
10. **是否适合只借鉴架构**：不应只借鉴，因为直接使用的收益更高。
11. **Windows 支持**：良好，目标就是剪映 Windows 工作流；自动化部分依赖 Windows UI 自动化和本机剪映版本。
12. **RTX3060/3080 适配**：草稿生成基本不使用 GPU；真正导出是否用 GPU 取决于剪映和编码器设置。
13. **接入工作量**：现有接入已完成；后续收敛边界和补测试为 S–M。
14. **主要风险**：剪映私有格式随版本变化；高版本可编辑性与自动导出不稳定；时间范围取整曾造成相邻片段重叠 [#199](https://github.com/GuanYixuan/pyJianYingDraft/issues/199)；高版本和 10.8 编辑性问题见 [#193](https://github.com/GuanYixuan/pyJianYingDraft/issues/193)、[#194](https://github.com/GuanYixuan/pyJianYingDraft/issues/194)。README 中也明确存在版本功能差异。
15. **最终建议**：标准能力归 **A**；当前必要的高版本补丁归 **B**。不要“替换”现有系统，而是明确它已经是底层轮子，停止新增重复序列化代码。

核心阅读位置：[`draft_folder.py`](https://github.com/GuanYixuan/pyJianYingDraft/blob/main/pyJianYingDraft/draft_folder.py)、[`script_file.py`](https://github.com/GuanYixuan/pyJianYingDraft/blob/main/pyJianYingDraft/script_file.py)、[`draft_content_loader.py`](https://github.com/GuanYixuan/pyJianYingDraft/blob/main/pyJianYingDraft/draft_content_loader.py)、[`template_mode.py`](https://github.com/GuanYixuan/pyJianYingDraft/blob/main/pyJianYingDraft/template_mode.py)。

### 4.3 PySceneDetect 0.7.1

1. **GitHub 地址**：[Breakthrough/PySceneDetect](https://github.com/Breakthrough/PySceneDetect)
2. **Star/Fork**：5,211 / 523。
3. **最近更新时间**：2026-09-21；最新提交 `81c414c` 针对 Windows/OpenCV 图像写入问题增加规避。近期还有阈值检测、淡入淡出时长和错误处理修复。
4. **License**：BSD-3-Clause。
5. **主要功能**：`ContentDetector`、`AdaptiveDetector`、`ThresholdDetector`、直方图、感知哈希和 TransNetV2 场景检测；输出场景表、图像、EDL、FCP、OTIO，并可调用 FFmpeg 分割。
6. **与现有系统重合**：直接重合 `auto_remake/shot_detection.py` 的相邻帧差切镜，但算法和工程成熟度更高。
7. **是否已重复实现**：是。当前简单帧差检测是可用原型，但不值得继续自行扩展成完整镜头检测框架。
8. **是否可直接作为 Python 依赖**：可以。建议仅使用检测 API，不启用其分割和导出能力；依赖应固定版本并装在隔离测试环境后再进入生产环境。
9. **是否适合部分复用代码**：不需要复制源码，优先调用公开 API。
10. **是否适合只借鉴架构**：若实测不达标，可借鉴 stats/scene manager 设计并保留当前实现，但这是回退方案。
11. **Windows 支持**：良好，有 Windows 构建和持续修复；仍需验证当前 OpenCV 组合。
12. **RTX3060/3080 适配**：`ContentDetector`/`AdaptiveDetector` 主要走 CPU/OpenCV，不占显存；20 条视频无需 GPU。TransNetV2 才需要额外模型栈，不应作为第一步。
13. **接入工作量**：旁路评测 XS–S；生产薄适配 S；不涉及数据库迁移。
14. **主要风险**：可变帧率视频用 `frame_num` 可能不准确 [#569](https://github.com/Breakthrough/PySceneDetect/issues/569)；Windows 图像保存曾有间歇性崩溃 [#575](https://github.com/Breakthrough/PySceneDetect/issues/575)；阈值需按带货视频快切、字幕闪动和转场调参；解码仍是主要耗时。
15. **最终建议**：**A**。对 20 条带货视频建立人工边界真值，比较当前帧差、`AdaptiveDetector` 和 `ContentDetector`；用秒时间而不是帧号作为跨系统主键。通过门槛后，PySceneDetect 成为默认检测器，现有实现保留回退。

核心阅读位置：[`scene_manager.py`](https://github.com/Breakthrough/PySceneDetect/blob/main/scenedetect/scene_manager.py)、[`content_detector.py`](https://github.com/Breakthrough/PySceneDetect/blob/main/scenedetect/detectors/content_detector.py)、[`adaptive_detector.py`](https://github.com/Breakthrough/PySceneDetect/blob/main/scenedetect/detectors/adaptive_detector.py)、[官方手册](https://www.scenedetect.com/docs/latest/)。

### 4.4 faster-whisper 1.2.1

1. **GitHub 地址**：[SYSTRAN/faster-whisper](https://github.com/SYSTRAN/faster-whisper)
2. **Star/Fork**：25,632 / 2,101。
3. **最近更新时间**：主分支最近推送 2025-11-19；最新提交 `ed9a06c` 扩充 VAD 参数。2026 年仍有活跃 issue/PR，但主分支合并节奏相对放缓。
4. **License**：MIT；下载的 Whisper 模型及附加模型要分别核对许可证。
5. **主要功能**：CTranslate2 Whisper 推理、CPU INT8、CUDA FP16/INT8-FP16、批量转写、VAD、词级时间戳、hotwords 和语言检测。
6. **与现有系统重合**：它就是当前生产 ASR；无需另一个基础 ASR 引擎。
7. **是否已重复实现**：没有，当前系统合理地复用了成熟组件。
8. **是否可直接作为 Python 依赖**：可以；当前配置解释器已安装 1.2.1。
9. **是否适合部分复用代码**：不建议复制内部代码，使用公开 API。
10. **是否适合只借鉴架构**：不需要，只借鉴会重新造轮子。
11. **Windows 支持**：CPU 模式成熟；GPU 模式需要匹配 CTranslate2、CUDA、cuDNN 和 Python 版本。Python 3.14 仍有兼容性问题报告，例如 [#1492](https://github.com/SYSTRAN/faster-whisper/issues/1492)、[#1474](https://github.com/SYSTRAN/faster-whisper/issues/1474)。
12. **RTX3060/3080 适配**：两张卡都足够运行 base 模型；3080 10GB 的显存更小但算力更高，base 推理不是容量瓶颈。现有 CPU INT8 已验证，GPU 化应放在 Python 3.12 隔离环境做速度/准确率/稳定性对照，不能直接替换生产路径。
13. **接入工作量**：已接入；启用并评测词级时间戳/VAD/hotwords 为 S–M；GPU 隔离环境验证为 M。
14. **主要风险**：Python 3.14 和 CTranslate2 组合可能回归；CUDA/cuDNN 动态库版本敏感；词级时间戳不是强制对齐真值；多语种行为仍有回归报告 [#1476](https://github.com/SYSTRAN/faster-whisper/issues/1476)。
15. **最终建议**：**A**。保持 `base` + INT8 和现有回退；优先评测内置 `word_timestamps=True`、VAD 和 hotwords，再考虑 WhisperX/FunASR。

核心阅读位置：[`transcribe.py`](https://github.com/SYSTRAN/faster-whisper/blob/master/faster_whisper/transcribe.py)、[`vad.py`](https://github.com/SYSTRAN/faster-whisper/blob/master/faster_whisper/vad.py)、[README](https://github.com/SYSTRAN/faster-whisper#readme)。

### 4.5 FunClip 2.2.1

1. **GitHub 地址**：[modelscope/FunClip](https://github.com/modelscope/FunClip)
2. **Star/Fork**：6,356 / 756。
3. **最近更新时间**：2026-09-16；最新提交 `7e4b15f` 合并 CLI 帮助改动；最近版本为 2.2.1。
4. **License**：源码 MIT；FunASR、SenseVoice、LLM 等模型权重要单独核对其模型卡许可证和使用限制。
5. **主要功能**：FunASR/SenseVoice 转写、说话人/热词、基于识别文本选段、LLM 选段、字幕生成和 MoviePy 剪辑。
6. **与现有系统重合**：与 faster-whisper、字幕、`template_editing` 文案槽位匹配和自动剪辑链路部分重合。
7. **是否已重复实现**：基础 ASR 和候选片段搜索已存在；“选中文本 → 规范时间区间 → 字幕重映射”的胶水逻辑仍可借鉴。
8. **是否可直接作为 Python 依赖**：不适合。仓库更像应用源码，不是稳定 SDK；依赖 FunASR、ModelScope、Torch、Gradio、MoviePy 1.0.3、固定 NumPy 以及多个云服务 SDK，容易污染现有环境。
9. **是否适合部分复用代码**：适合。可从 `videoclipper.py`、`trans_utils.py`、字幕工具中提炼区间选择、合并和重映射逻辑，改造成接收 faster-whisper segment/word 的纯函数。
10. **是否适合只借鉴架构**：也适合，但仅借鉴会放弃一部分已经成熟的选段数据流。
11. **Windows 支持**：可运行，但安装链复杂，FFmpeg、Torch、FunASR、MoviePy 版本组合需要单独环境；不适合当前 Python 3.14 生产环境直接安装。
12. **RTX3060/3080 适配**：FunASR 常用模型推理通常能在 10–12GB 显存运行，但实际占用随模型和 batch 变化；完整 FunClip 并不需要为了文本选段而常驻第二套 ASR/GPU 栈。
13. **接入工作量**：移植纯逻辑为 S–M；把完整项目接入为 L，且收益不成比例。
14. **主要风险**：`trans_utils.py` 中部分时间换算绑定 FunASR 的时间戳语义；状态读取存在 `eval`，不可用于不可信输入；近期问题包括非 16k 音频处理 [#214](https://github.com/modelscope/FunClip/issues/214)、中文多字符与时间戳 [#215](https://github.com/modelscope/FunClip/issues/215)、拼接音频字幕时间重置 [#216](https://github.com/modelscope/FunClip/issues/216)；LLM/TwelveLabs 等路径违反纯本地原则。
15. **最终建议**：**B**。不安装、不导入完整 FunClip；只移植约束明确的时间轴纯逻辑，改用现有 faster-whisper 数据，并为中文标点、重复词、多段拼接、无词级时间戳写测试。

核心阅读位置：[`videoclipper.py`](https://github.com/modelscope/FunClip/blob/main/funclip/videoclipper.py)、[`trans_utils.py`](https://github.com/modelscope/FunClip/blob/main/funclip/utils/trans_utils.py)、[`subtitle_utils.py`](https://github.com/modelscope/FunClip/blob/main/funclip/utils/subtitle_utils.py)、[安装说明](https://github.com/modelscope/FunClip/blob/main/docs/INSTALL.md)。

### 4.6 auto-editor 31.6.1

1. **GitHub 地址**：[WyattBlue/auto-editor](https://github.com/WyattBlue/auto-editor)
2. **Star/Fork**：5,395 / 673。
3. **最近更新时间**：2026-09-19；最新提交 `7796222` 更新 FFmpeg 9.0.2。近期还在维护渲染、Whisper 和时间线能力。
4. **License**：仓库源码为 Unlicense；README 明确区分源码、在线服务/独有资产和不同发布物，二进制与高级功能必须按实际分发条款复核。
5. **主要功能**：按静音、音量、运动、字幕/表达式自动删除或加速片段，生成内部时间线，并导出到多种 NLE 或渲染结果。
6. **与现有系统重合**：与“停顿压缩、空白删除、机械粗剪”重合；不覆盖语义素材检索、带货结构和剪映草稿。
7. **是否已重复实现**：现有系统没有同等成熟的静音/运动规则引擎；语义剪辑方面不存在重复，因为 auto-editor 不解决它。
8. **是否可直接作为 Python 依赖**：不可以按 Python 库使用。当前主实现是 Nim，适合作为固定版本的独立 CLI 子进程。
9. **是否适合部分复用代码**：不建议复制 Nim 内部实现；直接调用 CLI 更稳。
10. **是否适合只借鉴架构**：可借鉴时间线和“分析—动作—渲染”分层，但不需要用它替代现有时间线模型。
11. **Windows 支持**：良好，有 Windows 使用路径和自带多媒体工具链的发布物；仍需在本机编码格式上验证。
12. **RTX3060/3080 适配**：核心分析以 CPU/FFmpeg 为主，不依赖显存；硬件编码是否可用取决于构建和编码参数。
13. **接入工作量**：作为可选预处理 CLI 为 S；若把它当多源剪辑核心则为 L 且不推荐。
14. **主要风险**：它按声学/运动规则剪，不理解“卖点”和“爆点”；当前源码中存在许可/功能门控，多源时间线与高分辨率能力不能假定免费发布物全部可用；不导出剪映格式；CLI 版本变化需固定。仓库当前未开放常规 GitHub Issues，外部问题可见性较弱。
15. **最终建议**：静音/运动裁剪这一限定模块归 **A**，时间线思想归 **C**。通过子进程和中间文件隔离，绝不让它操作生产索引或承担语义决策。

核心阅读位置：[`edit.nim`](https://github.com/WyattBlue/auto-editor/blob/master/src/edit.nim)、[`timeline.nim`](https://github.com/WyattBlue/auto-editor/blob/master/src/timeline.nim)、[`license.nim`](https://github.com/WyattBlue/auto-editor/blob/master/src/license.nim)、[文档](https://auto-editor.com/)。

---

## 5. 扩展候选项目审计

### 5.1 WhisperX

1. **地址**：[m-bain/whisperX](https://github.com/m-bain/whisperX)；2. **Star/Fork**：24,310 / 2,453；3. **最近更新**：2026-09-26；4. **License**：BSD-2-Clause。  
5. **功能**：Whisper 批量转写、wav2vec2 强制对齐、词级时间戳和可选说话人分离；6. **重合**：faster-whisper 词级时间戳与字幕；7. **重复实现**：基础 ASR 已有，对齐层没有；8. **直接依赖**：技术上可装，当前生产环境不建议直接装；9. **部分复用**：适合作为独立后处理服务；10. **只借鉴架构**：可；11. **Windows**：可用但 Torch/CUDA/对齐模型安装复杂；12. **GPU**：3060 12GB 与 3080 10GB 可运行小模型推理，需降低 batch，分离模型会增加显存；13. **工作量**：M；14. **风险**：语言对齐模型、pyannote 许可/令牌、模型下载、中文准确率和额外显存；15. **建议**：**B（条件式）**，只有 faster-whisper 自带词时间戳达不到人工标注门槛时才评测，不替换 ASR 主干。

### 5.2 FunASR

1. **地址**：[modelscope/FunASR](https://github.com/modelscope/FunASR)；2. **Star/Fork**：20,552 / 2,053；3. **最近更新**：2026-09-30；4. **License**：工具包 MIT，模型权重另计。  
5. **功能**：ASR、VAD、标点、说话人、时间戳和服务化；6. **重合**：完整覆盖当前 ASR；7. **重复实现**：若直接接入会形成第二套 ASR；8. **直接依赖**：可装，但依赖和模型栈较大；9. **部分复用**：可把 VAD/标点/时间戳服务放隔离环境；10. **只借鉴架构**：适合；11. **Windows**：Python 路径可用，部分推理方案有 Windows 构建；12. **GPU**：常用 Paraformer/SenseVoice 推理可在 10–12GB 级显卡评测，具体取决于模型、精度和 batch；13. **工作量**：M–L；14. **风险**：违反“不擅自更换已验证模型”，模型许可证、依赖冲突、双 ASR 维护；15. **建议**：当前归 **C**，仅作为对比基线。必须先在同一中文数据集证明时间戳或准确率显著提升，才能升级为 B。

### 5.3 OpenTimelineIO

1. **地址**：[AcademySoftwareFoundation/OpenTimelineIO](https://github.com/AcademySoftwareFoundation/OpenTimelineIO)；2. **Star/Fork**：2,002 / 357；3. **最近更新**：2026-09-26；4. **License**：Apache-2.0。  
5. **功能**：专业时间线、剪辑、轨道、媒体引用和多格式适配器；6. **重合**：与自动剪辑内部时间线和导出层重合；7. **重复实现**：现有系统已有更轻量的业务时间结构；8. **直接依赖**：有 Python 绑定，但当前支持版本主要到 Python 3.12，不能假定兼容 3.14；9. **部分复用**：未来多 NLE 导出时可作为中间表示；10. **只借鉴架构**：现在更合适；11. **Windows**：有轮子，但受 Python/本地扩展版本制约；12. **GPU**：无关；13. **工作量**：M；14. **风险**：它不读写媒体、不渲染，也不原生解决剪映私有格式；过早引入会增加模型转换；15. **建议**：当前 **C**。只有需要同时导出剪映、Premiere、Resolve 等至少两三种时间线时，再评估 B。

### 5.4 MoviePy

1. **地址**：[Zulko/moviepy](https://github.com/Zulko/moviepy)；2. **Star/Fork**：14,937 / 2,112；3. **最近更新**：2026-08-26；4. **License**：MIT。  
5. **功能**：Python 视频剪辑、合成、字幕和音频；6. **重合**：FFmpeg 裁剪/合成；7. **重复实现**：项目已有直接 FFmpeg 和剪映输出；8. **直接依赖**：可以，但 v1/v2 API 有破坏性差异，FunClip 固定 1.0.3 而 NarratoAI 使用 2.1.1；9. **部分复用**：适合小型预览，不适合核心批处理；10. **只借鉴架构**：可；11. **Windows**：支持；12. **GPU**：主要取决于 FFmpeg，Python 合成链未必使用 NVENC；13. **工作量**：S；14. **风险**：速度、内存、版本冲突和隐式重编码；15. **建议**：**C**，保留现有 FFmpeg 主路径，不因 FunClip/NarratoAI 间接引入两个不兼容版本。

### 5.5 MoneyPrinterTurbo

1. **地址**：[harry0703/MoneyPrinterTurbo](https://github.com/harry0703/MoneyPrinterTurbo)；2. **Star/Fork**：127,169 / 19,878；3. **最近更新**：2026-09-30；4. **License**：MIT。  
5. **功能**：主题/文案、素材搜索、配音、字幕、合成的一站式短视频生产；6. **重合**：任务编排、配音、字幕、素材选择和成片；7. **重复实现**：通用流水线与现有模块重合，但不是本地素材语义检索系统；8. **直接依赖**：否，属于完整应用；9. **部分复用**：不优先；10. **只借鉴架构**：适合借鉴阶段化任务、配置和原子产物；11. **Windows**：支持，通常建议 Python 3.11；12. **GPU**：多数路径 GPU 非必需；13. **工作量**：完整接入 XL；14. **风险**：大量在线素材/API 路径与纯本地原则冲突，形成第二套应用；15. **建议**：**C**。

### 5.6 MMAction2

1. **地址**：[open-mmlab/mmaction2](https://github.com/open-mmlab/mmaction2)；2. **Star/Fork**：5,165 / 1,360；3. **最近更新**：2026-03-18；4. **License**：Apache-2.0。  
5. **功能**：动作识别、时序动作定位、时空检测、视频检索模型与训练框架；6. **重合**：泛视频语义理解；7. **重复实现**：现有系统没有完整动作识别框架，但带货结构不等同于通用动作标签；8. **直接依赖**：不建议，OpenMMLab/Torch/MMCV 栈较重；9. **部分复用**：只有确定具体任务和模型后才有意义；10. **只借鉴架构**：适合；11. **Windows**：能配，但编译/版本组合维护成本高；12. **GPU**：两张卡可做选定小模型推理，训练或大型模型受 10–12GB 显存限制；13. **工作量**：L–XL；14. **风险**：领域错配、模型栈冲突、没有带货标签就难产生业务价值；15. **建议**：**C**，不是当前爆款分析的现成答案。

### 5.7 Marqo

1. **地址**：[marqo-ai/marqo](https://github.com/marqo-ai/marqo)；2. **Star/Fork**：5,034 / 243；3. **最近更新**：仓库 2026-09-03 有推送，默认分支最新提交时间为 2026-04-10；4. **License**：Apache-2.0。  
5. **功能**：通用文本/图像/多模态向量检索服务，偏搜索平台与电商检索；6. **重合**：FAISS/CLIP 语义检索；7. **重复实现**：会与现有索引形成另一套服务和数据模型；8. **直接依赖**：不是轻量 Python 库，通常以服务/Docker 使用；9. **部分复用**：收益有限；10. **只借鉴架构**：可借鉴过滤、索引管理和评测；11. **Windows**：通常需 Docker/WSL，原生本地体验不如现有方案；12. **GPU**：推理模型可用 GPU，但为现有规模引入整套服务不划算；13. **工作量**：L；14. **风险**：索引迁移、重复存储、服务运维，与“保留现有 FAISS”冲突；15. **建议**：**C/不采用**，保留现有检索实现。

### 5.8 pyCapCut（观察项，不可复用）

1. **地址**：[GuanYixuan/pyCapCut](https://github.com/GuanYixuan/pyCapCut)；2. **Star/Fork**：687 / 97；3. **最近更新**：2026-09-30；4. **License**：GitHub 未检测到许可证。  
5. **功能**：CapCut 草稿生成，与 pyJianYingDraft 类似；6. **重合**：剪映/CapCut 草稿；7. **重复实现**：与现有 pyJianYingDraft 路线高度重合；8. **直接依赖**：法律边界不清，不可；9. **部分复用**：无许可证时不可复制；10. **只借鉴架构**：只能观察公开接口思想，不能复制表达；11. **Windows**：目标平台相关，但成熟度仍需验证；12. **GPU**：无关；13. **工作量**：即使接入也为 M；14. **风险**：最大风险是没有明确开源许可证，其次是 CapCut/剪映格式差异；15. **建议**：归 **D/暂不采用**，仅跟踪。等待明确许可证和稳定版本后再评估。

### 5.9 Lighthouse

1. **地址**：[line/lighthouse](https://github.com/line/lighthouse)；2. **Star/Fork**：272 / 20；3. **最近更新**：2026-09-17，最新提交 `3e841d3` 修复 CASTELLA 相关问题；4. **License**：Apache-2.0。  
5. **功能**：可复现的视频片段检索与高光检测库，统一封装 Moment-DETR、QD-DETR、CG-DETR、UVCOM、TaskWeave 等模型，并支持 CLIP、SlowFast、PANNs 和音频片段检索；6. **重合**：与“文案/查询 → 视频时段”和高光评分直接相关；7. **重复实现**：现有系统有检索和顺序匹配，但没有成熟的通用 MR-HD 模型基线；8. **直接依赖**：不适合生产直装，当前包版本仍为 0.1，依赖 `numpy<=1.23.5`、旧 Torch/CUDA 组合和 Git 安装的 CLIP；9. **部分复用**：适合在独立 Python 3.9/3.10 环境调用 inference API，作为离线对比基线；10. **只借鉴架构**：适合借鉴“查询相关窗口 + saliency score”的输出接口；11. **Windows**：理论可用，但官方主要验证 Python 3.9/CUDA 11.8，SlowFast/特征提取链在 Windows 上维护成本较高；12. **GPU**：3060 12GB/3080 10GB 可运行选定模型推理，CLIP+SlowFast 比纯 CLIP 更慢、更占显存；CPU 模式应只用纯 CLIP 特征；13. **工作量**：建立隔离基线 M，生产适配 L；14. **风险**：官方说明当前视频最长 150 秒，预训练权重和特征链较分散，通用数据集高光不等于带货转化高光；采样 FPS [#75](https://github.com/line/lighthouse/issues/75)、checkpoint 兼容 [#74](https://github.com/line/lighthouse/issues/74) 和一致 saliency [#50](https://github.com/line/lighthouse/issues/50) 均有公开问题；15. **建议**：**C，附条件 B**。把它作为高光/片段检索研究基线，而不是直接上线；若在带货标注集上明显优于现有方法，只复用 predictor/inference 层并做领域微调。

核心阅读位置：[`models.py`](https://github.com/line/lighthouse/blob/main/lighthouse/models.py)、[`setup.py`](https://github.com/line/lighthouse/blob/main/setup.py)、[README](https://github.com/line/lighthouse#readme)。

---

## 6. 按模块的 A/B/C/D 最终归类

这是本审计的执行依据。一个项目可以在不同模块落入不同类别。

### A. 直接复用，不再自行开发

| 模块 | 直接复用方案 | 本项目只保留什么 |
|---|---|---|
| ASR 解码、VAD、基础词级时间戳 | faster-whisper 1.2.1 | 配置、缓存、结果规范化和失败回退 |
| 通用镜头边界检测 | PySceneDetect 0.7.1 的 `AdaptiveDetector`/`ContentDetector` | 20 条视频标注基准、参数配置、结果 JSON；现有帧差作回退 |
| 剪映标准草稿模型 | pyJianYingDraft 0.3.0 | 业务编排和高版本适配，不再写通用轨道/片段序列化 |
| 静音/停顿/运动规则粗剪（可选） | auto-editor 固定版本 CLI | 子进程封装、输入输出校验，不参与语义判断 |

“A”表示停止重复开发该底层能力，不表示本阶段立即安装或切换生产默认路径。PySceneDetect 和 auto-editor 都必须先在隔离环境验证。

### B. 复用核心代码，再做适配

| 模块 | 复用来源 | 适配要求 |
|---|---|---|
| 文本选段到时间区间 | FunClip | 改为 faster-whisper segment/word 输入；禁止 `eval`；处理中文标点、重复词、缺失词时间戳 |
| 多段字幕重映射 | FunClip | 修复拼接后时间归零/偏移问题，输出项目统一 SRT/JSON |
| 剪映 11.5、复合片段和库未覆盖能力 | pyJianYingDraft + 现有补丁 | 补丁集中在版本适配层，用黄金草稿回归，不能散落业务代码 |
| 强制对齐（条件式） | WhisperX | 仅在 faster-whisper 词时间戳未达标时，独立环境试验；不替换 ASR |
| 通用中间时间线（条件式） | OpenTimelineIO | 只有多 NLE 导出成为明确需求时再引入 |

### C. 只借鉴设计，保留自己的实现

| 模块/项目 | 借鉴点 | 不采用原因 |
|---|---|---|
| NarratoAI | 任务阶段、缓存、FFmpeg 降级、失败状态 | 整体应用/LLM/草稿体系与现有系统冲突 |
| MoneyPrinterTurbo | 流水线编排、原子产物、配置结构 | 偏在线素材和 API 驱动，不是本地检索底座 |
| FunASR | VAD/标点/时间戳服务设计和对比基线 | 已有 faster-whisper，不能无实验切换模型 |
| MMAction2 | 视频模型评测、数据集和推理管线 | 通用动作语义不能直接解决带货结构 |
| Lighthouse | 通用片段检索/高光模型和 saliency 输出接口 | 旧依赖、150 秒限制和通用数据集标签不能直接代表带货高光 |
| MoviePy | 小型预览/组合 API | 现有 FFmpeg 更适合大批量；v1/v2 冲突明显 |
| Marqo | 向量服务过滤、评测和索引管理 | 会重复现有 FAISS/CLIP 并引入服务运维 |
| auto-editor 时间线 | 分析—动作—渲染分层 | 不取代语义时间线和剪映导出 |

### D. 没有合适成熟方案，必须自行开发

| 模块 | 为什么不能直接复用现成项目 |
|---|---|
| 带货爆款结构识别 | 公开项目多做通用脚本生成、动作识别或 LLM 摘要，没有适配本地商品、话术和可验证时间轴的成熟组件 |
| 领域高光/钩子评分 | 通用 highlight 模型的标签与带货转化信号不同，必须用自己的定义和标注集评测 |
| 参考视频 → 本地素材语义匹配 | 需要同时利用现有视觉/语音索引、素材身份、可用时段和业务约束，现成编辑器不具备这些上下文 |
| 顺序约束、多源切换、去重复和节奏规划 | 属于本项目的组合优化与可解释决策层，FunClip/auto-editor 只做单源或规则裁剪 |
| 人工审核与证据链 | 必须展示为何匹配、原始/目标时间、相似度与回退原因，通用项目没有兼容现有数据的完整方案 |
| 稳定的资产/索引适配层 | 要兼容 `video_index_fixed.db`、FAISS meta 三元组、本地路径和旧索引，必须由本项目掌控 |
| 剪映版本回归与黄金样本 | 私有格式变化频繁，任何库都不能替代本项目对目标剪映版本的实际验证 |

---

## 7. 与现有生产资产的共存性

| 现有资产 | 共存方案 | 禁止事项 |
|---|---|---|
| `video_index_fixed.db` | 所有新工具只接收导出后的路径、时间段或只读查询结果；镜头结果写独立 JSON/新缓存 | 不让第三方工具迁移 schema、开启 WAL、改 `subtitles.start/end` |
| MobileNetV2 FAISS | 保持原文件和 1280 维协议；镜头边界仅用于限制候选时间范围 | 不重建、不换维度、不换 Normalize/L2，不把 Marqo 当替代索引 |
| faster-whisper | 保持唯一 ASR 主干；FunClip 逻辑消费其 segment/word 输出 | 不同时常驻 FunASR 第二套主 ASR；不无对比切模型 |
| ORB | 继续做局部特征校验，可在镜头候选内使用 | 不用场景检测代替相似画面确认 |
| 截图寻帧 | 继续作为精确定位/验证手段；镜头边界可减少搜索区间 | 不改现有评分权重，不假定镜头边界就是精确截图位置 |
| 本地素材库 | 所有项目只接收本地绝对路径；第三方输出使用稳定 `asset_id + start_s + end_s` | 不上传云端，不把路径改为网络地址，不让外部项目复制整库 |
| `jianying_auto` | pyJianYingDraft 负责标准对象；现有代码负责业务和版本补丁 | 不再新增另一套通用 JSON builder，不让 NarratoAI builder 并行存在 |

推荐的模块边界：

```text
本地视频/参考视频
    ├─ PySceneDetect ──> scene_ranges.json
    ├─ faster-whisper ─> transcript_words.json
    └─ 现有索引/ORB/截图寻帧（只读）
                │
                v
     本项目自研：结构识别、召回重排、顺序/去重/节奏规划
                │
                v
         统一 timeline_plan.json
                │
        ┌───────┴────────┐
        v                v
 pyJianYingDraft       FFmpeg/可选 auto-editor
 剪映草稿适配层       预览或规则粗剪
```

---

## 8. 下一阶段建议顺序

本次不执行下列开发，只给出低风险顺序。

### 阶段 1：建立 20 条视频镜头切分基准

- 人工标注硬切、淡入淡出、快速转场和应忽略的字幕/闪动；
- 并行比较当前帧差、PySceneDetect `ContentDetector`、`AdaptiveDetector`；
- 记录边界 Precision/Recall/F1（建议容差 0.3 秒和 0.5 秒各一组）、过切、漏切、耗时；
- 不修改数据库，只产生实验 JSON；
- 达标后将 PySceneDetect 设为默认，原实现保留回退。

### 阶段 2：冻结剪映草稿边界

- 明确 `pyJianYingDraft 0.3.0` 是标准能力提供者；
- 新代码优先调用库 API，不再手写标准轨道/片段 JSON；
- 收集 3–5 个能被目标剪映版本正常打开并编辑的黄金草稿；
- 所有 11.5/复合片段补丁集中到一个版本适配层；
- 升级库前跑黄金样本，而不是直接修改生产生成器。

### 阶段 3：提高 ASR 时间轴质量，但不换模型

- 在短中文带货片段上测试 faster-whisper 的词级时间戳、VAD、hotwords；
- 测量字幕起止误差、漏字、数字/商品名和重复词；
- 只有未达标，才在独立 Python 3.12 环境对比 WhisperX；
- FunASR 只作为研究基线，不进入生产依赖。

### 阶段 4：移植 FunClip 的小逻辑，不引入大应用

- 定义本项目自己的 `SelectedRange(start_s, end_s, text, source_words)`；
- 移植文本命中、区间合并和字幕重映射思想；
- 重写所有绑定 FunASR 16ms 时间单位和 `eval` 的部分；
- 对中文标点、重复词、跨句选择、多段拼接和空结果写单元测试。

### 阶段 5：只开发差异化决策层

- 结构标签体系和标注工具；
- 参考段落到本地素材的多模态匹配；
- 多源选择、顺序、去重、节奏、时长预算；
- 可解释证据和人工审核；
- 成果输出到统一时间线，再交给成熟底层组件。

---

## 9. 风险清单与决策门槛

1. **许可证分层**：源码许可证不自动覆盖模型权重、在线资产或发布二进制。FunASR/FunClip 模型、WhisperX 对齐/说话人模型、auto-editor 发布物都应分别留档。
2. **无许可证即不复用**：pyCapCut 当前没有明确 License，不能复制或分发其代码。
3. **剪映私有格式漂移**：pyJianYingDraft 降低了成本，但不能消除版本风险；必须用黄金草稿验证。
4. **Python 3.14 风险**：faster-whisper/CTranslate2、OpenTimelineIO、Torch 生态的 3.14 支持不统一。新实验优先隔离环境，不污染当前解释器。
5. **VFR 时间基风险**：跨工具统一使用秒和原始 time base，不能把帧号当永久主键。
6. **GPU 不是唯一约束**：3060 12GB 容量更宽松，3080 10GB 算力更强；对 base ASR 都足够。真正风险是 CUDA/cuDNN/torch/ctranslate2 版本矩阵。
7. **避免“框架吞项目”**：NarratoAI、MoneyPrinterTurbo、Marqo 都是应用/平台，不应为了一个模块把现有系统迁入其数据模型。
8. **先评测再替换**：任何模型或检测器必须在固定小样本上优于现有方案，才允许进入默认路径；旧实现保留回退。

---

## 10. 最终停止/继续清单

### 下一阶段应停止自行开发

- 通用 ASR 推理引擎、VAD 和基础词时间戳；
- 从零扩展通用镜头检测算法库；
- 剪映标准素材、轨道、片段、关键帧、字幕的底层 JSON 序列化；
- 静音/运动驱动的通用裁剪器；
- 通用视频合成 DSL 或第二套完整视频生产 Web 应用；
- 第二套向量数据库/向量检索服务；
- 仅为多格式时间线而过早自建专业 NLE 交换标准。

### 下一阶段真正值得自行开发

- 带货爆款的领域结构和可评测标签；
- 参考视频与本地素材的跨模态匹配及解释；
- 结合现有索引的候选召回、重排、去重和顺序约束；
- 多视频混剪规划、节奏控制、素材切换和失败回退；
- 本地资产身份、缓存、审计、人工复核和可恢复任务；
- 剪映目标版本的适配与回归测试；
- 一套小而稳定的统一时间线数据结构，连接分析层与输出层。

一句话决策：**底层媒体能力买“成熟轮子”，领域理解和本地素材决策保留为自己的护城河。**

---

## 11. 主要一手资料

- 六个指定仓库：[NarratoAI](https://github.com/linyqh/NarratoAI)、[pyJianYingDraft](https://github.com/GuanYixuan/pyJianYingDraft)、[PySceneDetect](https://github.com/Breakthrough/PySceneDetect)、[faster-whisper](https://github.com/SYSTRAN/faster-whisper)、[FunClip](https://github.com/modelscope/FunClip)、[auto-editor](https://github.com/WyattBlue/auto-editor)
- 扩展候选：[WhisperX](https://github.com/m-bain/whisperX)、[FunASR](https://github.com/modelscope/FunASR)、[OpenTimelineIO](https://github.com/AcademySoftwareFoundation/OpenTimelineIO)、[MoviePy](https://github.com/Zulko/moviepy)、[MoneyPrinterTurbo](https://github.com/harry0703/MoneyPrinterTurbo)、[MMAction2](https://github.com/open-mmlab/mmaction2)、[Marqo](https://github.com/marqo-ai/marqo)、[pyCapCut](https://github.com/GuanYixuan/pyCapCut)、[Lighthouse](https://github.com/line/lighthouse)
- 官方文档：[PySceneDetect docs](https://www.scenedetect.com/docs/latest/)、[auto-editor docs](https://auto-editor.com/)、[OpenTimelineIO quickstart](https://opentimelineio.readthedocs.io/en/latest/tutorials/quickstart.html)

---

## 12. Hypit 专项复用审计（2026-09-30 追加）

详细报告见 [HYPIT_REUSE_AUDIT.md](HYPIT_REUSE_AUDIT.md)。本次只读检查公开仓库、源码、文档、发行说明和公开 Issue；未安装 Hypit，未运行其服务，也未修改生产代码或生产数据。

**决策标记：`HYPIT_POC_RECOMMENDED`**，但只建议旁路验证，不建议整体迁移或直接进入生产。

最多三个值得吸收的点：

1. **语义词锚点**：借鉴 `Script token / Selection / Moment → SemanticTake → Timeline frame`，把 PRODUCT / PROOF / CTA、字幕、产品画面、B-roll 和特效绑定到台词语义区间，而不是只写绝对秒数。这是唯一高优先级 POC。
2. **变体产物身份**：借鉴 `.svrun` 的 Candidate、`satisfy` 和 Build Result 思路，为人物、产品、B-roll、台词替换建立轻量 manifest，继续由现有批量剪映草稿链输出。
3. **参考分析分层**：借鉴“转写/画面证据 → ANALYSIS/TIMELINE → Brief/Treatment → Recipe”的产物边界，连接现有 `bestseller_analysis` 与未来 Video Recipe。

不建议引入完整 SVML/SVS/SVRun runtime、HyperFrames、Studio、Hypit WhisperX 或生成 Provider。Hypit 可以读取显式指定的本地 MP4，但不替代现有 500GB 素材的 Speech Semantic / DINO / CLIP 检索；也没有发现 Jianying/CapCut/OTIO exporter，因此 pyJianYingDraft 仍应是可编辑剪映工程的最终输出层。

Hypit 使用修改后的 Hypit Open Source License，而不是标准 Apache-2.0。内部商业使用和自托管/单租户场景在许可证文本中被允许；面向外部的多租户托管/SaaS、商业再分发或衍生产品存在商业许可和品牌保留要求，源码级复用前必须单独做法务审查。
