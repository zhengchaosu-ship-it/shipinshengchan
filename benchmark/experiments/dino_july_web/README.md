# 寻帧本地素材搜索工具

已实现本地 Streamlit 网页：图片 → DINO formal_v1_repaired Top500 → 冻结候选去重 → Top10；文字 → 受控领域中文/英文 → CLIP formal_v1 Top20 → 页面前10；起号自动合成 → 调用独立 `jianying_auto/` 生成本机剪映草稿。运行时完全离线，不自动准备索引或抽帧。

2026-09-28正式文字入口验收通过，见 [接入报告](../clip_web_rollout/report.md)。文字库319个asset、362,752帧、5秒采样；图片库319个asset、1,843,351帧，两者约507小时。模式切换时分别显示当前库，文字查询独立使用CPU，不启用ORB或文字候选去重。

`search_config.json` 的 `text_search_enabled` 控制文字入口。设为false并重新运行根目录启动寻帧.bat后，文字提示暂不可用，图片保持工作；设true并重启恢复。图片search_index和candidate_dedup保持现有配置。CLIP缺少report、READY验收、FAISS、metadata或数量不一致时，文字拒绝加载，图片入口不受影响。

`jianying_auto_enabled` 控制“起号自动合成”入口，默认true。界面固定显示5个Slot：片段1必须选择引流/手法/坐诊/收尾；片段2～5增加“无”且默认“无”。实际可连续生成1～5段；第N段为“无”时后续自动重置为“无”并禁用，“无”不进入时间线。页面严格按实际选择顺序生成并只预览有效片段。同类重复选择时先无放回随机，只有该类素材不足才重复并提示。生成数量可选1～10、默认1；每条重新选材，批次内用组合签名和有限重试尽量避免整套素材重复，单条失败不会中止其余草稿。批次Manifest和逐条清单写入 `jianying_auto/runtime/batches/<batch_id>/`。4类路径统一位于 `jianying_auto/jianying_source_folders.json`，递归支持 `.mp4/.mov/.ts/.mkv/.avi/.flv/.m4v/.webm`。高级入口保留“流量1+手法2+收尾1”格式，旧“流量”映射到“引流”。网页只通过独立子进程调用原模块，使用项目配置的Python和本地Whisper base模型；搜索进程不导入剪辑依赖。同一时间只允许一个草稿任务，失败不会影响三个搜索入口。产物是剪映草稿，不直接导出MP4。

生成前会在剪映草稿根目录创建并立即删除一个写权限探针。如果8502服务由受限开发沙箱启动，页面会直接提示关闭服务并双击根目录 `启动寻帧.bat` 重启，不再返回pyJianYingDraft的长堆栈；正常双击启动不需要管理员权限。

文字反馈复用同一反馈库/schema：query_type=text，index_version=clip_formal_v1，保留原中文query、实际英文prompt和后端Top20；用户可确认页面所示素材并补充时间/备注。未知中文和否定句明确拒绝，细分动作/部位仍可能匹配不准。

## 界面

页面定位为“AI 视频素材搜索工作台”，采用响应式双栏布局：左侧选择图片、话术、文字搜索或起号自动合成，右侧显示结果与状态。图片模式提供上传预览；文字模式提供领域示例与能力提示；自动合成模式显示1～5段有效组合预览、1～10生成数量、实时分类数量、逐条进度、批次汇总、实际选中素材、草稿路径和Manifest。搜索过程中显示本地加载状态；未搜索、空结果、错误和缩略图缺失都有独立状态。

结果以双列卡片展示已有缩略图、排名、视频 ID、文件名、精确时间戳、六位相似度和完整路径。每张卡片可打开大图预览，并用本地 FFmpeg 从命中时间前1秒生成8秒短片段。窄屏会自动改为单列。界面只使用本地系统字体和已有画面，不加载外部前端资源。

## 启动

2026-10-02新增可选局域网入口：根目录 **启动寻帧-局域网.bat**，或在下述启动命令追加 `-Lan`。默认启动仍仅本机；局域网入口沿用原模型、索引、业务页面与员工权限。首次防火墙配置、伙伴访问与使用边界见 [局域网说明](../../../LAN_ACCESS.md)。`-CheckOnly`可只检查启动参数，不重启服务。

### 搜索反馈记录

结果卡片已增加“这是正确素材”、可选正确时间点和备注；结果末尾增加“没有正确结果”。左侧“搜索反馈 / 导出 CSV”保存并下载反馈快照。每次搜索记录独立 search_id、查询原图/文字、当前索引名和 TopK，反馈写入 `benchmark/feedback/search_feedback.db`。同次搜索改选覆盖旧标注；不填写正确时间点时只确认素材。存储字段、导出和转换现有 benchmark 案例的命令见 [反馈说明](../../feedback/README.md)。

双击项目根目录的 **启动寻帧.bat**，然后打开 **http://127.0.0.1:8502**。保持启动窗口打开，按 Ctrl+C 停止。旧的 **启动7月测试工具.bat** 继续兼容，并使用当前 `search_config.json` 所选索引。

也可在项目根目录执行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File benchmark/experiments/dino_july_web/launch.ps1
```

端口冲突时追加 `-Port 8503`，浏览器使用对应端口。启动器从自身目录解析路径，使用已有 `.venv-cuda-test`，不修改生产解释器/配置。自动优先 CUDA，不可用时使用 CPU；可先设置 `$env:JULY_SEARCH_DEVICE='cpu'` 强制 CPU。

## 搜索索引切换

网页通过 `search_adapter.py` 使用统一后端。唯一切换项位于 `search_config.json`：

```json
{
  "search_index": "formal_v1_repaired"
}
```

当前使用独立修复版正式库 `formal_v1_repaired`：319个素材、1,843,351帧、约506.85小时。adapter 支持 `july_test`、`formal_v1` 和 `formal_v1_repaired` 三个明确版本；正式版本加载前必须同时满足 `report.status=complete`、外部严格验收报告为 `READY`、验收报告目录绑定正确，并存在非空 `metadata.sqlite` 与 `dino.faiss`。

双击 **切换寻帧到7月测试库.bat** 可写回 `july_test` 并重启服务；双击 **切换寻帧到正式素材库.bat** 可恢复 `formal_v1_repaired`。切换只修改轻量配置，不复制或重命名索引。

各图片后端统一返回 `asset_id`、`video_id`、`file_name`、`file_path`、`timestamp`、`similarity`、`thumbnail`。7月实验数据没有asset_id，因此该字段为 `null`；正式metadata包含asset_id。正式缩略图不在metadata视图中，但可通过其中的`shard`和`frame_number`从对应只读shard取出，adapter 已封装这一步。

正式DINO索引不包含文字特征。选择 `formal_v1` 或 `formal_v1_repaired` 时页面只提供图片搜索；若未来需要全库文字搜画面，需另行建立与正式frame_id绑定的文字/多模态特征缓存，再在formal adapter中接入。

## 范围与界面

仅原7月文件夹：`E:\备份\陶老师直播录制\妙手陶老师本人_3xr7zzgq96gpawe\陶老师7月直播素材`。

以原实验 `inventory.json` 的18个视频为白名单，并校验其与 `experiment_manifest.json` 的路径相同。现有大实验索引还含20个 benchmark 原视频；这些全部排除，即使文件名包含7月日期也不扩展到本文件夹之外。

- 图片搜索覆盖18个视频的 **180,408帧**。只读原 `dino_index.faiss`，FAISS selector 在 TopK 前限制范围；不复制、裁剪或重建索引。
- Query 使用原 DINOv2-small 官方预处理、FP32、最后层 CLS 384维、L2归一化、内积余弦排序。模型来自原实验权重目录。
- 图片搜索与文字搜索使用明确的模式切换；切换时清理上一种模式的旧结果，避免误读。
- Top10逐帧排序，可包含同一视频的多个时间点；展示已有 JPEG 缩略图、文件名、video_id、时分秒/秒数、余弦分数、完整视频路径。分数不是概率。
- 缺失缩略图只提示；用户点击预览时才从源视频按命中时间生成8秒本地缓存片段，不写回索引。

## 文字检索实验的实际能力与限制

DINO不具备文本编码器。复用已有 `openai/clip-vit-base-patch32` 权重（同一固定revision），新增约1.4MB的同版本公开分词器文件；没有新增大型模型或安装依赖。

CLIP官方模型主要支持英文，因此本工具使用**有限领域中文词表转换为英文**，页面显示实际编码文本；并非通用中文语义模型。不认识的中文词和否定描述会提示，不默默忽略。直接输入英文可绕过词表。人物称呼“陶老师”转换为治疗师，不识别或验证身份。

已验证可执行的示例：

- 陶老师给患者按摩腰部
- 患者趴在床上治疗
- 治疗肩颈的视频

独立 `text_cache/clip_july.npz` 含 **6,023个512维向量**，来自每视频每30秒时间桶内第一张**已存在的 JPEG**，覆盖全部18个视频。此为文字实验的候选选择粒度，原1秒抽帧规则和所有 DINO 数据未改变。短动作可能不在候选中；文字结果相关性需内部人工评估，不能当作已验证的语义准确率。使用 NumPy 内积直接查询，无新增 FAISS 文件。

缓存已经准备完成，正常使用**无需运行任何准备脚本**。`prepare_text.py` 仅作为显式可复现入口保留：只读取已有JPEG，分批断点保存到独立 `text_cache/`；已有最终缓存时直接退出。页面从不调用它。准备记录见 `text_cache/summary.json`。

模型说明：[DINOv2-small](https://huggingface.co/facebook/dinov2-small)、[CLIP ViT-B/32](https://huggingface.co/openai/clip-vit-base-patch32)。

## 验证记录与复测

- 独立单元测试11项通过：七月范围在TopK前过滤、返回不足10项时不出现无效行、路径/索引不一致拒绝、词表/非法输入、时间格式、只读索引等。
- 真实DINO查询仅使用3张已有JPEG，首/中/末视频各一张，Top1均为原video_id与时间点，余弦大于0.999。
- 3条示例描述均实际经过CLIP编码，返回10项合法七月结果；验证排序、缩略图存在及页面展示。
- Streamlit AppTest：首页、空输入、文字结果10张图、未知中文错误及旧结果清理通过。
- 新增6项纯UI回归测试，使用合成图片和模拟引擎，覆盖模式切换、图文提交、加载/空结果/错误状态、结果卡片、预览入口、清空结果、缩略图缺失与HTML转义；不会加载模型、索引或原视频。
- 新增5项adapter测试，使用合成metadata、合成缩略图与mock索引，验证配置白名单、正式完成门槛、metadata字段检查、统一结果契约和shard缩略图映射；不读取正式输出。
- 原 `tests/` 26项及 `benchmark.test_benchmark` 11项通过；新增Python文件语法检查通过。
- 原生产代码/配置、数据库、生产索引、DINO索引及元数据的大小和修改时间未变。清单为 `protected_before.json`；实际查询记录为 `validation.json`。

```powershell
& .\.venv-cuda-test\Scripts\python.exe -X utf8 -B -m unittest discover -s benchmark/experiments/dino_july_web -p test_search.py -v
& .\.venv-cuda-test\Scripts\python.exe -X utf8 -B -m unittest discover -s benchmark/experiments/dino_july_web -p test_adapter.py -v
& .\.venv-cuda-test\Scripts\python.exe -X utf8 -B benchmark/experiments/dino_july_web/smoke_test.py
```

手动验收：启动网页，上传 `benchmark/experiments/dino_july_test/frames/249/0000002400.jpg`，应返回video_id 249、120秒附近结果；移除图片，逐一输入上述三个示例，核对10项结果和路径都在指定7月目录。然后试空输入、未知词或同时输入图文，应出现明确提示。

剪映入口手动验收：选择“剪映自动合成”→“坐诊”→“生成剪映草稿”，等待完成后核对草稿名称、时长和路径；在剪映专业版打开新草稿，确认贴纸为一个复合片段且外层为滤色、1%不透明度。自动化测试只验证适配器和页面状态，不代替剪映内实际渲染检查。

## 文件与隔离

原搜索代码、分词器、缓存、验证记录位于本目录；新增反馈数据和导出独立位于 `benchmark/feedback/`。修改前留有 `.bak`。生产的 `video_search.py`、`config.json`、`models/`、数据库及 FAISS 文件没有改动。默认启动监听127.0.0.1，可选局域网模式监听0.0.0.0；关闭Streamlit使用统计，无云端推理或云端上传。发布管理和起号模块的现有能力以HANDOFF.md最新记录为准。
# 2026-09-28 正式库候选去重

正式库图片查询默认使用 `search_config.json` 中的 `candidate_dedup: true`：DINO原图embedding → FAISS Top500 → 按原similarity顺序保留每asset最多5帧、代表帧相隔至少10秒 → 返回最多10条。相似度不修改，不运行ORB；正式索引、模型、metadata不变。仅最终结果读取JPEG。若Top500全部属于同一asset，最多返回5条，不放宽规则凑满10条。

双击项目根目录 `关闭寻帧候选去重.bat` 可设置false并重启8502，恢复原始DINO Top10；`开启寻帧候选去重.bat` 设置true并重启。也可手动修改此布尔字段后重新运行 `启动寻帧.bat`。旧配置缺省为false，7月图片/文字查询维持原实现；现有切库脚本保留该开关。Streamlit缓存引擎，因此手工修改配置后需重启。

正式engine提供 `search_with_timings(image, k=10)` 返回 `(rows, timing)`，记录embedding、FAISS、metadata、去重、缩略图及总耗时；原 `search(image, k=10)` 返回值不变。计时不存储跨线程共享状态。调用search时将本次计时输出到 `search_adapter` 的INFO日志（按运行环境日志级别显示）。

上线验证见 `../candidate_dedup_rollout/report.md`；30张原query逐项对齐冻结实验，关闭开关也逐项对齐原始Top10。独立20例去重后Top1/5/10为55%/80%/85%；hell10为20%/50%/60%。
