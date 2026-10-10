# 正式 CLIP 文字搜视频索引

本目录是“寻帧”全素材文字搜索的独立构建代码。它不修改 DINO、MobileNet、生产数据库或现有 FAISS，也不自动接入 Web。当前图片搜索生产配置保持不变。

## 模型和中文范围

沿用七月工具已经落盘并跑通的 `openai/clip-vit-base-patch32`：

- revision：`3d74acf9a28c67741b2f4f2ea7635f0aaf6f0268`
- 512维 FP32、L2归一化、FAISS `IndexFlatIP`
- 权重与预处理来自 `benchmark/experiments/embedding_comparison/weights/clip/`
- tokenizer复用 `benchmark/experiments/dino_july_web/tokenizer/`
- 正式执行前逐文件核对现有权重清单的大小和SHA-256，全程离线

该 OpenAI CLIP **本身不是中文模型**。正式流程复用七月已验证方案：有限领域中文规则转为英文 prompt，再用CLIP文本编码器。明确覆盖：

- 患者趴着接受治疗
- 按摩腰部
- 肩颈治疗
- 患者坐着，老师站在旁边

中文否定句或词表未覆盖内容会明确报错，不会静默忽略。“老师/医生”仅转成 therapist，不识别身份。直接英文输入原样编码。这是可控的业务词表能力，不应描述为通用中文理解；后续真实反馈 benchmark 若显示不足，再单独对比中文原生多模态模型，不能直接替换正式索引模型。

## 画面来源和数量

默认源是 `dino_index/formal_v1_repaired`。先执行 `python -X utf8 -B clip_index/preflight_formal.py`，核对严格验收READY、固定模型文件SHA、CUDA环境及4个asset的JPEG编码/FAISS smoke test。失败时停止。构建器同时检查源report的完成时间、源文件保护和异常；门槛未满足时，在创建CLIP输出、读取DINO metadata/shard或加载模型之前退出。

画面直接读取 DINO 每帧 shard 中已经保存的最长边256像素 JPEG thumbnail，通过 `frame_number` 与 `frame_id` 绑定，**不打开或解码任何原视频**。默认按每个asset的timestamp每5秒取一个桶的首帧，保留原DINO：

- `frame_id`
- `asset_id`
- `video_id`
- `timestamp`
- `file_path`
- DINO `source_index_id` 与 `frame_number`

正式repaired源共319个素材、约506.85小时、1,843,351个DINO画面。2026-09-28生成的 `build_plan.sqlite` 按5秒时间桶选择 **362,752张** 已有JPEG，实际数量由源metadata覆盖决定。本方案不改变DINO的一秒抽帧协议。

## 输出结构

默认写入独立的 `clip_index/formal_v1/`：

```text
formal_v1/
  manifest.json                 # 冻结DINO来源、模型revision/hash、采样与特征协议
  build_plan.sqlite             # 确定性的5秒选帧计划
  embedding_shards/
    <asset_id>.sqlite           # 每asset特征、失败记录和完成状态；也是断点
  progress.json                 # 当前阶段、已完成asset/embedding/失败数
  sessions.json                 # 每次启动、耗时、结束/中断状态
  clip.faiss                    # 512维归一化图像向量IndexFlatIP
  metadata.sqlite               # videos、frames、failed_frames、frame_metadata
  failures.json                 # 单图JPEG读取/解析失败明细
  assembly.json                 # 组装数量与时间
  report.json                   # 全流程组装完成后最后生成
```

每个batch提交到对应asset的SQLite embedding shard。重启时已写入的 `plan_id/frame_id` 不会再次编码；单张JPEG损坏记入errors后继续。默认重启保留失败记录并跳过；确认源数据已修复后可加 `--retry-errors`。模型或源协议改变时拒绝混用旧断点。DINO report、metadata和全部引用shard在构建前后核对大小/修改时间或SHA，所有源SQLite只读打开。

运行batch可以由32降至16继续原断点，不改变已冻结的manifest/checkpoint身份；显存不足会将当前batch减半重试。单asset源shard无法打开时记录其未完成frame并继续其它asset；输出磁盘/模型系统性问题仍停止并保留断点。失败明细在asset结束时写入failures.json，最终组装再次汇总。sessions.json记录实际batch、GPU模型前向时间及CUDA allocated显存峰值。

## DINO完成后的正式启动命令

先运行DINO验收并确认READY。随后在项目根目录执行一条命令：

```powershell
.\.venv-cuda-test\Scripts\python.exe -X utf8 -B clip_index/build.py --execute --device cuda --interval-seconds 5 --batch-size 32
```

`--execute` 是防误启动门槛；省略时只打印“未启动正式CLIP建库”，不会创建目录或加载模型。中断后运行同一命令续跑，不删除formal_v1输出。2026-09-28已完成正式构建及功能验收READY：319个asset、362,752帧，失败0。五条中文Top20正常返回，但姿势/部位仍有偏差；详见validation/formal_v1/report.md。尚未接入Web。

构建完成后运行 `python -X utf8 -B clip_index/validate_formal_clip.py`。验收全部向量的维度/归一化/FAISS对应关系、metadata与DINO/plan映射、319个asset覆盖、路径及失败记账，并执行5条中文Top20查询。结果和Top3画面抽样保存在 `clip_index/validation/formal_v1/`，不写DINO或Web。

## Query API

```python
from clip_index.query import search_text

rows = search_text('患者趴着按摩腰部', top_k=20)
```

每条结果至少包含：

```python
{
    'frame_id': 'AST-...:12345',
    'asset_id': 'AST-...',
    'video_id': 123,
    'timestamp': 456.0,
    'similarity': 0.31,
    'file_path': 'D:/.../video.ts',
}
```

`TextSearch.search(text, k)` 另提供现有 adapter 使用的 `(rows, prompt, notes)` 契约；结果也含 `file_name`，因此可直接交给当前 `normalize_result`。便捷接口默认用CPU做单条文字embedding，不自动占用GPU。正式CLIP `report.json` 不存在时查询API拒绝加载FAISS或模型。

## 轻量测试

```powershell
$env:CUDA_VISIBLE_DEVICES=''
.\.venv-cuda-test\Scripts\python.exe -X utf8 -B -m unittest clip_index.test_clip_index -v
```

9项测试只使用合成DINO metadata、8张24×18合成JPEG、模拟CLIP编码器和CPU FAISS。覆盖领域中文、5秒选帧、完整build→FAISS→metadata→query、单图损坏继续、批次中断恢复、降低batch续跑跳过已完成asset、单asset读取失败隔离、不执行门槛、源/输出隔离和Windows进度文件占用重试。不会读取真实formal_v1、原视频或加载模型。
