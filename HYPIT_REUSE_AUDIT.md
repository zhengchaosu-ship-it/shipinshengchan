# Hypit 开源复用专项审计

> 审计日期：2026-09-30  
> 审计对象：[hypit-ai/hypit](https://github.com/hypit-ai/hypit)  
> 审计方式：只读检查公开仓库、源码、官方文档、发行说明和公开 Issue；未安装 Hypit，未运行其服务，未下载模型，未修改任何生产代码或生产数据。  
> 版本口径：以审计时的 `main` 源码和公开 Releases 为准。仓库处于 `0.x` 快速迭代期；Releases 页面显示 `v0.2.16`，而检索到的 `package.json` 版本曾为 `0.2.13`，因此本文不把内部接口视为稳定 API。

---

## 1. 结论先行

**决策标记：`HYPIT_POC_RECOMMENDED`**

这个标记只表示：建议在旁路、小样本、无生产依赖的条件下验证一个“word/speech 语义锚点”数据契约。它不表示建议安装 Hypit、迁移项目、引入 Hypit 渲染器，或替换现有检索与剪映输出链。

### 最多三个真正值得拿来复用的模块/设计

| 优先级 | 候选 | 复用方式 | 对当前项目的实际价值 |
|---|---|---|---|
| 1 | `Script token/Selection/Moment → SemanticTake → Timeline frame` 语义锚点链 | **适配后复用其数据模型；优先自行实现兼容思想，不直接复制源码** | 让 PRODUCT / PROOF / CTA、字幕、产品画面、B-roll 和特效绑定“哪句话/哪个词”，重排或换台词后可重新解算时间，而不是把绝对秒数写死 |
| 2 | `.svrun` 的 Candidate / `satisfy` / Build Result 身份模型 | **只借鉴结构，做成本项目轻量 variant manifest** | 明确哪些人物、产品、B-roll、台词是本次变量，哪些已对齐素材可复用，避免每个变体都从头计算 |
| 3 | Reference Video 的证据分层：转写/画面证据 → `ANALYSIS.md` / `TIMELINE.md` → Brief / Treatment → 可执行 Recipe | **只借鉴流程和产物边界** | 补齐 `bestseller_analysis` 到 Video Recipe 之间的桥，不把分析结论、创意意图和最终时间线混在一个对象中 |

**当前没有建议直接并入生产环境的 Hypit 模块。** 如果一定要评估源码级复用，候选接口仅限 `@hypit/narrative`、`@hypit/speech-alignment` 和 `@hypit/timeline` 中的纯数据类型/纯函数；在复制任何实现前必须先完成许可证和衍生作品边界审查。

以下部分明确不建议引入：完整 SVML 编译/运行时、HyperFrames 浏览器渲染器、Studio、Hypit 的 WhisperX 服务、生成模型 Provider 体系、第二套完整视频生产环境。

---

## 2. 审计基线：我们已经有什么

本结论按当前仓库实际代码和文档判断，而不是把规划能力当作已实现：

- `bestseller_analysis`：已能分析 20 条带货爆款并形成 HOOK / PRODUCT / PROOF / CTA、节奏等业务结构；这是 Hypit 不提供的领域判断能力。
- 本地 500GB 素材检索：已有 Speech Semantic、DINO、CLIP 等召回能力；Hypit 不提供对这批素材的自动索引、搜索或业务重排。
- `template_editing`：能按业务功能选择素材，现阶段核心是槽位候选检索，不是完整的跨槽时间线编排器。
- `jianying_auto` / pyJianYingDraft：能输出可编辑剪映草稿，并已有 1–10 个草稿的批量生成与 manifest 能力。
- `auto_remake`：已有参考视频复刻实验链，但多源定位、完整源时间线和自动裁切仍有未完成部分。
- 当前 faster-whisper 已能请求词级时间戳；因此引入语义锚点不等于必须换成 Hypit 的 WhisperX。

---

## 3. A：Reference Video → workflow / composition

### Hypit 实际怎么做

Hypit 的参考视频流程不是一个确定性的“视频输入 → workflow JSON”编译器。官方 Skill 指导 Agent：

1. 完整观看参考视频；
2. 转写并检查词级时间；
3. 用 probe、cut、frames、tile、boundaries 等媒体工具检查画面和边界；
4. 编写 `ANALYSIS.md` 和 `TIMELINE.md`；
5. 再形成立意、Brief、Treatment、Script、Style 和 Run；
6. 由作者/Agent 写出 `.svml`、`.svs`、`.svrun`，再构建成片。

因此，它的优势是**一套规范化的证据与创作产物链**，不是现成的参考视频结构识别模型。Hypit 不会自动给出本项目的 HOOK / PRODUCT / PROOF / CTA，也不会自动把参考镜头定位到本地 500GB 素材库。

### 对当前项目的判断

- 可借鉴：把“观察证据”“业务结构”“目标创意”“可执行 Recipe”分层保存。
- 不可替代：`bestseller_analysis` 的电商业务标签、现有多模态检索、`auto_remake` 的本地素材定位。
- 最合适的接入点：经人工确认的爆款分析结果之后、素材检索和剪映草稿生成之前。

建议未来的轻量产物边界如下（只是审计建议，尚未实现）：

```text
ReferenceEvidence
  ├─ transcript_words / shots / visual_notes
  └─ source_timeline
          ↓
VideoRecipe
  ├─ sections: HOOK / PRODUCT / PROOF / CTA
  ├─ semantic selections / moments
  └─ asset intent + constraints
          ↓
TimelinePlan
  ├─ selected local asset IDs + source ranges
  ├─ resolved target frames + confidence
  └─ captions / B-roll / effects events
          ↓
pyJianYingDraft
  └─ editable Jianying project
```

---

## 4. B：word-anchored editing

### 4.1 机制

Hypit 的 Script 本身不以秒或帧为主键。`.svml` 中的文本先生成稳定 Narrative token，并通过两种语义对象挂接编辑意图：

- **Selection**：有开始和结束 anchor，例如一段“产品演示”台词；
- **Moment**：单点 anchor，例如说到价格或排名的瞬间；
- **Dual Text**：屏幕展示文本与实际口播文本可以不同；
- **Alignment Unit**：支持展示词与语音词之间 N:M 的对应，而非强制一词对一词。

语音对齐后，`SemanticTakeToken` 保存 token 对应的起止帧；Timeline 再把 Selection / Moment 的语义 anchor 解算为全局帧区间。绝对时间仍然存在，但它是 fallback 或最终解算结果，不是业务意图的唯一身份。

公开源码中最相关的接口是：

- `@hypit/narrative`
  - 类型：`NarrativeToken`、`NarrativeSelection`、`NarrativeMoment`、`NarrativeExcerpt`
  - 函数：`narrativeAnchorTokenBoundary`、`narrativeSelectionTokenRange`、`narrativeTokensForSelection`
- `@hypit/speech-alignment`
  - 函数：`alignWordGroups`、`alignSemanticTake`、`normalizeForAlignment`
  - `alignWordGroups` 是支持合并、拆分、替换、插入、遗漏的动态规划 N:M 对齐逻辑
- `@hypit/timeline`
  - 函数：`semanticAnchorFrames`、`selectionFrameSpan`、`segmentFrameSpan`、`tokenFrameSpan`、`momentFrame`

这些是**候选接口清单，不是当前建议直接复制进生产的清单**。

### 4.2 字幕、B-roll、画面、特效、剪辑节点如何锚定

| 对象 | Hypit 的锚定方式 | 本项目可对应的用法 |
|---|---|---|
| 字幕 | Script token → Alignment Unit → timed cue；字幕分组可保留词级对应 | 台词变化后重算字幕时间；中文需保留字符/词组策略和置信度 |
| B-roll | 轨道 Item 的 `during` 指向某个 Selection | PRODUCT 或 PROOF 的话术区间内覆盖检索到的本地 B-roll |
| 产品画面 | 媒体轨道绑定产品演示 Selection，或在价格/卖点 Moment 切入 | 产品近景、使用演示、对比证据与业务段落同步 |
| 文字/贴纸/特效 | Selection 控制持续区间；Moment 触发单点效果 | 价格强调、排行榜、证据数字、CTA 按钮出现 |
| 剪辑节点 | 语义段落边界和 moment 解算到帧，再形成 cut/transition 事件 | 台词重排时自动移动切点；低置信对齐回退到人工或绝对秒 |

### 4.3 是否值得引入

**值得，且是本次审计中唯一的高优先级 POC。** 原因不是 Hypit 的 ASR 比现有模型更好，而是它在“业务语义 ID”和“最终帧区间”之间增加了一个可重算的窄腰层。

建议本项目保留以下安全边界：

- 不更换 faster-whisper；优先复用现有 `word_timestamps=True` 输出。
- 每个 anchor 同时保存 `word_id/token_id`、转写文本、对齐置信度、fallback 绝对区间。
- PRODUCT / PROOF / CTA 以业务 section ID 为一级身份，以词区间为二级定位。
- 中文商品名、数字、重复词、口误、删词和插词必须进入测试集。
- 不把 ASR word timestamp 当成绝对真值；Hypit 自己也曾修复相邻词窗口重叠导致中文字幕重叠的问题。

---

## 5. C：SVML / workflow DSL

### 5.1 三类文件的职责

- `.svml`：Script、媒体、组件、Composition 和构建图；本质是一个完整作者图和类型化工作流语言。
- `.svs`：类似 CSS 的视觉 Recipe / 样式值。
- `.svrun`：选择 Author Source、构建目标、Candidate，并用 `satisfy` 把某个 Candidate 绑定到本次构建需要的输出。

这不是一个轻量 JSON schema，而是 TypeScript 编译器、运行时、Provider、Worker、Studio 和渲染器组成的生态。

### 5.2 与未来三种结构的比较

| 我们未来需要的结构 | 是否应直接用 Hypit | 建议 |
|---|---|---|
| Video Recipe | 否 | 借鉴 Segment / Role / Selection / Moment；字段保持 Python/JSON 可读，并保留 HOOK / PRODUCT / PROOF / CTA 业务语义 |
| Timeline Plan | 否 | 借鉴 semantic anchor → resolved frame；时间线仍使用本项目轻量结构，并为 pyJianYingDraft 准备明确的目标轨道事件 |
| Template Structure | 否 | 保留现有业务槽位；增加 `allowed_roles`、是否必需、重复规则、素材约束和转场策略即可 |

### 5.3 结论

**SVML / SVS / SVRun 整体只借鉴思想，不直接复用。** 直接采用会让现有 Python、SQLite、FAISS、pyJianYingDraft 项目额外承担 Node 编译图、Worker、浏览器渲染和受限许可证的长期耦合，收益不足以覆盖复杂度。

---

## 6. D：素材替换与 variant generation

### Hypit 的方法

`.svrun` 可声明三类 Candidate：

- `file`：本地文件候选；
- `value`：结构化值候选；
- `build-record`：引用之前某次构建的输出。

`satisfy` 决定本次哪个输出需求由哪个候选满足。复用原始视频通常仍需重新标准化、转写和对齐；复用已经生成的 `SemanticTake` 才能保留准备好的时序结果。每次构建有新的 build ID，并产生结果记录。

### 对“同一带货结构 → 多套陶老师素材组合”的意义

它适合借鉴成一个显式 variant manifest：

```text
variant_id
recipe_id
replacements:
  person -> local_asset_id
  product -> local_asset_id
  broll.PROOF -> local_asset_id + source_range
  dialogue.PRODUCT -> script_version_id
reuse:
  transcript / alignment / selected_range / thumbnail
output:
  jianying_draft_id / manifest_path
```

但审计到的技术文档只证明“每次 Run 可替换候选并引用已有输出”，没有证明存在成熟的一条命令生成 100 个笛卡尔组合、自动去重并做业务质量筛选的批量 API。官网的“100 variants”应理解为可编排多次 Run 的能力，不能当作已验证的现成批量生成器。

本项目已有 `jianying_auto` 的 1–10 草稿批量和 manifest，Hypit 不应替换它。真正可取的是更明确的**变量、产物身份和可复用中间结果**模型。

---

## 7. E：本地素材支持

结论：**可以直接使用显式指定的本地 MP4，不强制调用生成模型。**

- `media:Video` 可引用相对路径的 `.mp4`、`.mov`、`.m4v`、`.webm`；
- `--asset-root` 可以额外挂载只读资产根目录，并可重复指定；
- `.svrun` 的 `file` Candidate 可直接绑定已有本地文件；
- `pipeline:Normalize` 会通过本地媒体 Provider / FFmpeg 检查并标准化流。

但需要区分“能读取文件”和“能管理我们的素材库”：

- Hypit 不会替代当前 500GB 素材的 Speech Semantic / DINO / CLIP 索引与检索；
- 必须先由我们的检索层选出具体路径，再交给 Hypit 风格的 Recipe/Timeline 层；
- 源码白名单明确覆盖 MP4/MOV/M4V/WebM；TS、MKV、AVI、FLV 等现有素材格式不能假定开箱即用，应先做格式探测或标准化测试；
- `asset-root` 是路径可见性，不是资产目录、去重、语义搜索或权限系统。

---

## 8. F：输出层和与 pyJianYingDraft 的分工

| 输出 | Hypit 状态 | 对本项目的判断 |
|---|---|---|
| MP4 | 支持。HyperFrames 用 Chromium 渲染 HTML/CSS/JS 帧，再经 FFmpeg 编码、混音、封装 | 可用但不建议引入；与现有剪映输出目标形成第二套渲染栈 |
| 内部 timeline | 支持类型化 Timeline、ProgramSpace、语义 anchor 和 Studio 可视化 | 可借鉴其语义层；不是已证明的通用 NLE 交换时间线 |
| Editable project | 有 Hypit 自己的 `.svml` / `.svs` / `.svrun` 源项目和 Studio | 是 Hypit 可编辑项目，不是剪映/CapCut 工程 |
| Manifest / build record | 支持 `result.json`、files、values、日志和 receipts | 值得借鉴产物身份与依赖记录 |
| Jianying / CapCut | 未在公开仓库和文档中发现 exporter | 不能替代 pyJianYingDraft |
| OTIO / EDL / FCPXML | 未发现公开 exporter | 不能假定支持；未来真有多 NLE 需求时再单独评估 OTIO |

建议分工非常明确：

- 我们的分析、检索和轻量 Recipe 层决定“为什么用这段素材、绑定哪句台词”；
- 语义锚点层把业务意图解算为具体时间区间；
- pyJianYingDraft 继续负责最终可编辑剪映工程；
- 不在同一条生产链同时维护 Hypit HyperFrames 和剪映两个主输出后端。

---

## 9. 与现有系统逐项比较

表中“直接复用”只表示当前是否建议不改或少改地引入 Hypit 实现；不是 Hypit 是否具备该能力。

| Hypit 能力 | 我们现有能力 | 直接复用 | 适配后复用 | 只借鉴思想 | 不需要 |
|---|---|:---:|:---:|:---:|:---:|
| Reference Video 分析工作流 | `bestseller_analysis` + `auto_remake` 已有领域分析和实验链 |  |  | ✓ 证据/分析/Recipe 分层 |  |
| HOOK / PRODUCT / PROOF / CTA 自动识别 | 我们已有 20 条业务分析；Hypit 无此领域分类器 |  |  |  | ✓ Hypit 部分不需要 |
| Script token / Selection / Moment | 现有结构标签与绝对时间之间缺少稳定语义层 |  | ✓ **最高优先级** |  |  |
| N:M 展示词—语音词对齐 | faster-whisper 已有词时间戳，但未形成统一业务 anchor |  | ✓ 小样本验证后实现 |  |  |
| word-anchored 字幕/B-roll/效果 | 当前多以槽位和具体区间为主 |  | ✓ 作为 Recipe→Timeline 窄腰 |  |  |
| 完整 SVML 编译与运行时 | 当前 Python/JSON/SQLite/FAISS 链稳定 |  |  | ✓ 类型和职责划分 | ✓ 运行时本身不需要 |
| `.svs` 视觉样式 DSL | 剪映草稿已有样式与轨道表达 |  |  | ✓ 若未来统一样式 token | ✓ DSL 本身不需要 |
| `.svrun` Candidate / `satisfy` | 已有批量草稿和 manifest，但中间产物复用身份较弱 |  |  | ✓ 轻量 variant manifest |  |
| 本地 MP4 / asset root | 已有本地素材和绝对路径工作流 |  |  | ✓ 路径安全和只读根设计 | ✓ Hypit 资产层不需要 |
| 500GB 语义/视觉检索 | 已有 Speech Semantic / DINO / CLIP |  |  |  | ✓ Hypit 不能替代 |
| WhisperX 对齐服务 | 已有 faster-whisper base 和词时间戳 |  |  | ✓ 对齐契约 | ✓ 第二套 ASR 服务不需要 |
| 多 variant 构建 | `jianying_auto` 已支持 1–10 草稿 |  |  | ✓ 变量与复用记录 | ✓ Hypit 批量执行栈不需要 |
| HyperFrames MP4 渲染 | 当前目标是可编辑剪映草稿 |  |  | ✓ 可参考动效表达 | ✓ 第二套渲染后端不需要 |
| Hypit Studio | 当前工作流未要求第二套编辑器 |  |  |  | ✓ |
| Jianying / CapCut / OTIO 输出 | pyJianYingDraft 已能输出可编辑剪映草稿；Hypit 未见 exporter |  |  |  | ✓ Hypit 输出适配层不需要 |

---

## 10. 十个问题的明确回答

### 1. Hypit 是否能替代 `auto_remake` 的一部分？

**只能在未来替代/补充“参考结构落成可执行语义时间线”的表示层，不能替代当前核心。** 它不负责我们的 Speech/DINO/CLIP 素材召回、多源定位、置信门槛和业务结构判断。当前也没有一个可直接调用的 reference-video-to-workflow 编译器，所以不能把 Hypit 当作 `auto_remake` 的现成替代品。

### 2. 是否能替代 Template Editing 的一部分？

**可补充槽位选完之后的语义绑定与时间线计划，不能替代素材候选搜索、排序和人工审核。** 应把它看成 Template Editing 的下游表达层，而不是替代整个模块。

### 3. 是否能帮助实现“爆款 → 视频 Recipe”？

**能，且价值明显。** 可将经确认的 HOOK / PRODUCT / PROOF / CTA 映射为稳定 section ID、Selection、Moment、素材意图和时间预算。需要自行保留电商业务字段，不能照搬通用 SVML。

### 4. 是否能帮助批量生成多个变体？

**能帮助设计变量替换和中间产物复用，但不是已验证的现成批量产品。** 建议借鉴 Candidate / `satisfy` / build result 模型，继续用现有批量草稿生成器完成实际输出。

### 5. word anchoring 是否值得引入？

**值得，是唯一建议做 POC 的核心。** 它能显著降低换台词、删词、重排后字幕、产品画面、B-roll、特效和剪辑点整体漂移的问题。必须保留绝对时间 fallback、对齐置信度与中文专项测试。

### 6. 是否能直接吃我们的本地素材？

**能直接吃明确指定的本地 MP4/MOV/M4V/WebM，不需要生成模型。** 但它不会自动搜索 500GB 素材库；必须由我们的检索层先返回路径。其他容器格式需单独探测或转码验证。

### 7. 与 pyJianYingDraft 如何分工？

Hypit 值得借鉴的部分负责“Recipe、语义 anchor 和解算后的 Timeline Plan”；pyJianYingDraft 继续负责“剪映轨道、片段、字幕、关键帧和可编辑工程”。**pyJianYingDraft 是最终输出层，不能被 Hypit 的内部项目格式替代。**

### 8. 引入 Hypit 会增加哪些 Node / FFmpeg / 环境复杂度？

完整引入至少增加：Node.js `>=22.15`、TypeScript 工具链、npm/pnpm、Hypit Worker 与本地 SQLite 状态、FFmpeg/ffprobe、Chromium/Chrome 与 Puppeteer、`sharp`/`koffi` 等原生依赖、缓存与构建结果目录。若启用本地语音对齐，还会增加 `uv`、Python 3.10–3.13、WhisperX、PyTorch/模型和对齐模型下载。若启用生成 Provider，还会增加相应服务或凭据。

这与当前 Python 3.14 主环境并不一致；完整引入意味着维护第二套运行时，而不是增加一个普通 Python 包。

### 9. Windows 兼容性如何？

**可运行，但不能认定为无摩擦。** 仓库和发布流程考虑了 Windows，源码也处理过 `Scripts`、`TEMP`、`PATHEXT`、`SYSTEMROOT`、`WINDIR`、`ComSpec` 等问题；同时公开 Issue 仍出现 HyperFrames 的 FFmpeg 查找忽略 Windows `PATHEXT` shim 等问题。再加上本地 WhisperX 要求 Python 3.10–3.13，而本项目主解释器是 3.14，生产引入风险为中高。隔离 POC 可行，直接并入现有环境不建议。

### 10. 许可证对公司内部使用和未来多用户产品有什么限制？

Hypit 使用的是修改后的 **Hypit Open Source License（基于 Apache 2.0，但不是标准 Apache 2.0）**：

- 组织内部商业使用、客户项目、自托管和单租户使用在文本中被允许；
- 面向外部第三方提供多租户托管、managed service、SaaS，或商业再分发 Hypit/其衍生作品，需要另行商业许可；
- CLI、生成的 run report / manifest，以及由其派生并对用户展示的界面中，Hypit 名称、Logo 和版权标识不得移除或修改；
- 用户拥有自己的输入和生成输出，但第三方模型/服务条款仍需另看；
- 贡献条款允许项目方商业使用贡献，并保留未来调整许可证的空间。

因此，未来多用户产品不能按“普通 Apache-2.0 项目”处理。若复制核心实现并形成衍生产品，或把 Hypit 作为对外多租户服务的一部分，必须先让法务核对并与权利方确认。本文不是法律意见。

---

## 11. 建议的旁路 POC 边界（本次不实施）

只验证一个问题：**当前 faster-whisper 的词时间戳，能否可靠地把 PRODUCT / PROOF / CTA 的语义 Selection 和 Moment 解算成字幕、产品画面与 B-roll 的时间区间。**

- 数据：`test_videos/` 中 3–5 个短中文带货视频，不扫生产库；
- 输入：现有转写词时间戳 + 人工确认的业务段落；
- 输出：独立实验 JSON，不写生产数据库、不生成新 FAISS 索引；
- 对照：绝对秒版本 vs word-anchor 版本；
- 指标：anchor 命中率、首尾误差、换词/删词后漂移、中文商品名/数字/重复词错误、人工修正次数；
- 回退：每个事件保留 `fallback_start_s` / `fallback_end_s`；
- 代码策略：先自行实现最小数据契约，不安装完整 Hypit；只有纯函数实现确有明显收益且法务认可，才讨论源码级复用。

进入下一阶段的门槛应是：在换一版台词后，语义锚定相对绝对秒明显减少人工重调，并且不会让中文字幕边界或剪辑节点错误上升。

---

## 12. 风险与停止项

1. `0.x` 接口变化快，不能把当前包内类型当长期稳定 API。
2. 修改许可证对多租户和衍生产品有限制，源码可见不等于可无条件商业复用。
3. word anchoring 的收益依赖 ASR 和 N:M 对齐质量；中文、口误、重复词是主要风险。
4. 引入完整 runtime 会制造 Node/Python/FFmpeg/Chromium 四套环境耦合。
5. HyperFrames、Studio 和 Provider 会把项目带向第二套视频平台，与当前“小步增量、保留剪映输出”的路线冲突。
6. Hypit 不解决本地素材搜索，也不提供本项目需要的电商质量判断。

**停止项：不安装 Hypit，不引入完整 SVML runtime，不接入 Hypit WhisperX，不接入 HyperFrames，不修改生产代码，不扫描生产素材库。**

---

## 13. 主要一手资料

- 仓库、说明和许可证：[Hypit repository](https://github.com/hypit-ai/hypit)、[README](https://github.com/hypit-ai/hypit/blob/main/README.md)、[LICENSE](https://github.com/hypit-ai/hypit/blob/main/LICENSE)、[package.json](https://github.com/hypit-ai/hypit/blob/main/package.json)、[Releases](https://github.com/hypit-ai/hypit/releases)
- Reference Video 与项目文件：[Hypit Skill](https://github.com/hypit-ai/hypit/blob/main/skills/hypit/SKILL.md)、[reference-video.md](https://github.com/hypit-ai/hypit/blob/main/skills/hypit/references/creation/reference-video.md)、[project-files.md](https://github.com/hypit-ai/hypit/blob/main/skills/hypit/references/creation/project-files.md)
- 官方 Quickstart：[Script](https://hypit.ai/quickstart/script/)、[Timing](https://hypit.ai/quickstart/timing/)、[Tracks](https://hypit.ai/quickstart/tracks/)、[Composition](https://hypit.ai/quickstart/composition/)、[Run](https://hypit.ai/quickstart/run/)、[Preview](https://hypit.ai/quickstart/preview/)
- 核心源码：[Narrative types](https://github.com/hypit-ai/hypit/blob/main/packages/narrative/src/types.ts)、[Narrative selections](https://github.com/hypit-ai/hypit/blob/main/packages/narrative/src/selection.ts)、[Speech alignment](https://github.com/hypit-ai/hypit/blob/main/packages/speech-alignment/src/align.ts)、[Timeline location](https://github.com/hypit-ai/hypit/blob/main/packages/timeline/src/location.ts)、[Media surface](https://github.com/hypit-ai/hypit/blob/main/packages/media/src/surface.ts)
- 运行环境：[Contributing](https://github.com/hypit-ai/hypit/blob/main/CONTRIBUTING.md)、[WhisperX service](https://github.com/hypit-ai/hypit/tree/main/services/whisperx)、[HyperFrames](https://github.com/hypit-ai/hypit/tree/main/packages/render-hyperframes)
- Windows 相关公开问题：[Issue #319](https://github.com/hypit-ai/hypit/issues/319)、[Issue #256](https://github.com/hypit-ai/hypit/issues/256)

---

## 最终判断

**Hypit 对本项目最大的价值不是作为新的视频生产平台，而是提供了一个清晰的“业务语义 → 词锚点 → 帧区间”中间层设计。**

最终建议保持 `HYPIT_POC_RECOMMENDED`：只旁路验证语义锚点和轻量 manifest；其余最多借鉴设计。若这个 POC 不能显著减少台词变化后的人工调时，立即将结论降级为 `HYPIT_NO_NEED`，不继续投入。
