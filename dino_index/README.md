# 独立正式 DINO 索引

输入为 `asset_inventory/results/20260927_assets/primary_files.csv` 中的319个主文件。脚本只读源素材、资产库及已有模型；输出全部放在本目录，生产 MobileNet 索引和检索服务不参与此流程。

## 运行

在项目根目录 PowerShell 中执行：

```powershell
.\.venv-cuda-test\Scripts\python.exe dino_index/build.py
```

需要已有的本地 CUDA Python 环境，以及 `benchmark/experiments/embedding_comparison` 中已校验的 DINOv2-small 模型和依赖。不联网下载、不安装依赖。重复运行从已提交的特征批次恢复；已完成的视频不重复处理。Windows 文件锁阻止同一输出目录的并行建库。

## 数据协议

- 使用 OpenCV FFmpeg 报告的 FPS，生产规则为从第0帧开始，每 `int(FPS * 1)` 帧采样，时间戳为 `frame_number / FPS`。
- 原始解码 RGB 在内存中经过模型官方 slow processor；最短边256、中心裁剪224、ImageNet归一化。DINOv2-small 最后一层 CLS，384维 FP32，再进行 L2 归一化。
- 不写原尺寸图片。每个采样帧保存一张长边不超过256像素、JPEG质量75的缩略图，用于定位和核对检索结果。
- FAISS 为 `IndexFlatIP(384)`，内积即归一化向量的余弦相似度。
- `frame_id = asset_id + ':' + 原始解码帧序号`，可跨断点保持稳定。

## 输出

默认目录 `formal_v1/`：

- `manifest.json`：冻结输入清单、源文件状态、模型文件SHA-256、采样协议及受保护文件状态。
- `shards/<asset_id>.db`：每个视频的事务断点。`frames`保存原始帧序号、时间戳、384维float32特征及JPEG缩略图；`info`保存解码与完成状态。
- `dino.faiss`：全部特征的独立索引。
- `metadata.sqlite`：`videos`表和`frames`表；`frame_metadata`视图绑定asset_id、原video_id、完整路径、timestamp、frame_id与FAISS序号。缩略图可按shard和frame_number读取。
- `progress.json`：实时进度。
- `sessions.json`：各次特征处理耗时，含恢复记录。
- `assembly.json`：FAISS组装耗时和解码异常。
- `query_benchmark.json`：真实向量Top10检索及图片特征+检索延迟（中位数/P95）。
- `report.json`：全部完成后才生成的验收汇总。没有此文件时不得把索引标记为已完成。

剩余磁盘低于12GiB、输入改变、模型校验不符或某个视频无法产生特征时停止并保留断点。解码提前结束会记录在报告的`anomalies`中，不能据此声称源视频完整健康。计时中的wall_seconds包括中断间隔；sessions分别记录实际处理时长。文件状态核对使用已有SHA-256身份配合大小和修改时间，不再次读取数百GB文件计算哈希。

## 验证与查询

### formal_v1 完成后的一键验收

双击项目根目录的 `验收正式DINO索引.bat`，或在项目根目录运行：

```powershell
.\.venv-cuda-test\Scripts\python.exe -X utf8 -B dino_index/validate_formal.py
```

验收器首先且只检查 `formal_v1/report.json`。文件尚未生成时立即输出“正式索引尚未完成”并以退出码2结束；此路径不导入FAISS/NumPy，不读取metadata、shard、逻辑资产库或原视频，也不创建报告目录。

完成标记存在后，工具执行以下只读核对：report完成状态与异常、逻辑资产库319个主素材、metadata必要字段/空值/重复/连续index_id、asset_id覆盖、视频路径存在性、时间戳落在逻辑资产时长内、所有shard存在且完整、384维FP32 embedding数量。只有这些前置检查全部通过，才在CPU上加载 `dino.faiss`，核对 `ntotal`，并用固定随机种子抽取10个shard内已有feature做Top50自身查询；不加载DINO模型或Torch。

验收结果写在 formal_v1 外部：

- `dino_index/validation/formal_v1/validation_report.json`
- `dino_index/validation/formal_v1/validation_report.md`

状态只有 `READY` / `NOT_READY`。工具显式拒绝把报告目录设在formal_v1内部。退出码0表示READY，1表示检查失败，2表示正式索引尚未完成。只有READY报告会提示把 `benchmark/experiments/dino_july_web/search_config.json` 从 `july_test` 切换为 `formal_v1`；工具本身绝不修改该配置、正式索引、生产数据库或任何素材。

轻量测试只使用合成SQLite、合成feature和内存FAISS替身：

```powershell
.\.venv-cuda-test\Scripts\python.exe -X utf8 -B dino_index/test_validate_formal.py -v
```

当前真实 `report.json` 尚不存在时，只运行安全拒绝路径，不等待建库完成，不读取半成品。

```powershell
.\.venv-cuda-test\Scripts\python.exe -m py_compile dino_index/build.py dino_index/query.py dino_index/test_pipeline.py
.\.venv-cuda-test\Scripts\python.exe dino_index/test_pipeline.py
.\.venv-cuda-test\Scripts\python.exe dino_index/query.py --image "D:\查询图片.jpg"
```

测试使用3个合成短视频、真实本地DINO模型，验证逐帧生产采样与优化解码的采样序号一致、非整数FPS、断点恢复、向量归一化、缩略图尺寸、数据库关联与FAISS自查询。正式查询命令要求report.json已经存在，返回Top10 JSON。基准图片使用索引内缩略图，仅测试速度和链路，不作为独立准确率评测。
