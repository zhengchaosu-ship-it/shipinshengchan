# DINO真实规模验证（独立实验）

**已完成并停止。** 本轮共319,702帧；Top1/5/10视频命中率75%/90%/90%，Top1/5/10时间命中率45%/55%/55%。完整统计、20例明细及business_11的时间覆盖缺口见[实验报告](实验报告.md)。不要把仅七月目录的历史前置检查当作本轮结果。

图库由指定7月目录的18个视频和20例benchmark全部可接受ID对应的20个原视频组成，合计38个文件。精确路径、源文件状态、案例图片哈希和模型版本见 `experiment_manifest.json`。原 `inventory.json` 与 `前置检查报告.md` 是仅7月目录阶段的历史检查，不代表本轮合并图库。

不修改生产代码、数据库、MobileNet索引或配置，不切换生产。所有素材本地读取，DINO使用前一实验已下载并校验SHA256的权重及官方预处理，不联网。

## 运行与恢复

在项目根目录，使用能够读取已有实验依赖目录的终端：

```powershell
& .\.venv-cuda-test\Scripts\python.exe -X utf8 -B benchmark/experiments/dino_july_test/run_experiment.py
```

运行前请检查是否已有该脚本进程，不能同时启动两份。若进程中断，可用同一命令续跑：复用固定清单、已完成视频抽帧清单及32帧一批的特征文件；未完成视频会从头顺序解码，但复用已有JPEG。不要在运行中更换图片、权重或清单。首次正常完成后应停止，不自行重新运行。

## 方法与输出

- 顺序OpenCV/FFmpeg解码，采样规则为生产的 `n % int(fps * 1) == 0`，时间戳为 `n / fps`；使用grab/retrieve仅跳过非采样帧的像素转换，不跳过视频解码。
- JPEG：OpenCV编码，质量95，原分辨率，默认色度抽样；与原像素相比存在有损压缩。路径 `frames/<video_id>/<frame_number>.jpg`。
- 4个抽帧子进程，每个解码器2线程；GPU推理单进程，FP32，关闭TF32，batch32。DINOv2-small最后层CLS为384维，L2归一化。
- 续跑时增加4个CPU预处理线程，最多预取4批；128图逐元素一致性验证见prefetch_validation.json。已完成的28,810个特征保留复用，转接信息见prefetch_transition.json。全部抽帧现已完成，历史外部抽帧等待条件不会在当前缓存上触发。
- `features/` 保存特征分块和含读图/预处理的耗时；`dino_index.faiss` 是独立CPU IndexFlatIP，逐帧余弦排序，无视频去重、无生产ORB精排。
- 解码warning保留在 `logs/decode_*.log`；打开失败、图像取回失败、提前结束记录在 `extraction/` 和最终汇总中。与生产读取终止规则一致，无法继续解码的文件结束后处理其余视频，不把缺失帧伪记为有效帧。
- `progress/` 和 `run.log` 用于监控；出现剩余磁盘空间低于8GiB时停止新增图片，保留已有结果。
- 最终 `report.json`、`实验报告.md` 包含实际帧数/特征数、缓存/索引大小、抽帧worker秒数、特征耗时、显存峰值、20例逐例结果和查询延迟。只有这些文件完整生成且日志出现COMPLETE，才能声称实验完成。
- `report_supplement.json`保存分类结果、完整异常列表、两阶段总体耗时和历史baseline对照；首次日志为run.log，正常完成日志为resume.log。原始测量JSON保留，人工整理报告不改评分。

评分复用现有benchmark，多正确video_id和2秒容差不变。20例全部计入分母；另报告每例在实际图库中正确时间附近的有效帧覆盖。

生产MobileNet全库baseline仅作为历史参考：其图库与精排流程不同，不构成严格同图库模型对照。本轮也不是完整159万帧全库召回率。
