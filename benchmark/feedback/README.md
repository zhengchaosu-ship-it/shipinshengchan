# 寻帧搜索反馈

当前独立“寻帧”网页已接入，保持 `july_test` 配置与原搜索逻辑。使用原结果卡片中的“这是正确素材”，可展开填写正确时间点和备注；结果列表下方可点击“没有正确结果”。左侧“搜索反馈 / 导出 CSV”生成本机文件，并提供浏览器下载。

## 存储与字段

- 独立库：`D:\video_search_tool\benchmark\feedback\search_feedback.db`。不连接生产数据库，不读取任何索引或素材。
- CSV：`benchmark/feedback/exports/search_feedback_日期_时间_随机ID.csv`，UTF-8 BOM，中文、逗号、换行通过标准 CSV 引号保留。每次导出独立快照，不覆盖旧文件。
- 查询图片：原始上传字节与 SHA-256 存入 SQLite；导出时写入 `benchmark/feedback/queries/<SHA256>.img`，按文件内容可正常打开。CSV 的 `query_image_path` 是本机绝对路径。迁移机器时一起复制反馈目录并重新导出，以更新路径。
- `searches` 保存 UUID `search_id`、UTC 搜索时间、`image/text` 类型、原始文字/图片名/图片、索引名称 `index_version`、实际编码文本、词表说明、状态与完整 TopK JSON。排名从 1 开始；保存返回顺序、分数、asset_id、video_id、路径和时间，不复制结果缩略图。
- `feedback` 保存每次搜索的最新人工反馈，通过 `search_id` 关联查询。包含 `selected_rank`、`asset_id`、`video_id`、`file_path`、`predicted_timestamp`、`corrected_timestamp`、`note`、反馈时间与 `correct/no_correct` 状态。CSV 将两表合并，含全部必需字段及 TopK。
- 七月实验结果原本没有 `asset_id`，这里如实保存 NULL，仍有 video_id 与路径可定位。今后 adapter 返回 asset_id 时自动保留；本功能不访问正式索引补全。跨库资产比较前，可用独立逻辑资产清单按原路径/视频 ID 补映射。

每次有效提交先创建搜索记录；成功后冻结 TopK 快照，失败记 `error`，意外中断留下 `pending`。切换输入、预览、填写反馈和导出不会重新搜索或新增 search_id。未提交反馈导出为 `unreviewed`，与人工 `no_correct` 严格区分。同次搜索只保留最新选择，重复点击不增加样本；改选“没有正确结果”会清空之前的素材与时间字段。

正确时间点支持非负秒数、`分:秒`、`时:分:秒` 和小数秒，0 秒有效。**留空只确认素材，绝不把预测时间自动填成真值**。反馈写入异常明确提示；已完成的搜索结果仍可查看。

## 转换为 benchmark 案例

项目根目录运行（只操作反馈库，无模型推理）：

```powershell
& .\.venv-cuda-test\Scripts\python.exe -X utf8 -B -m benchmark.feedback.store
& .\.venv-cuda-test\Scripts\python.exe -X utf8 -B -m benchmark.feedback.store --cases
```

第一条导出 CSV；第二条在 `exports/benchmark_cases_<随机ID>.json` 生成现有 `benchmark/run.py` 的 schema_version=1 案例。

转换规则：只有 **图片搜索 + 人工确认正确素材 + 明确填写正确时间点** 才进入 `cases`。`id=search_id`，`image=查询原图路径`，`acceptable_video_ids=[video_id]`，`expected_timestamp=corrected_timestamp`，保留源索引名、asset_id、备注；默认时间容差为 2 秒，可人工调整。不自动推断重复素材的其他正确 ID。

没有正确结果、只确认素材但未标时间、文字搜索、未反馈或搜索失败，均列入 `pending`，同时完整保留在 CSV/SQLite 中。没有正确结果只表示这次返回未命中，不能推断整个素材库都没有目标；需人工补充真实目标素材和时间。没有合格图片案例时 `cases=[]`，需先补标注再运行，现有 runner 不接受空案例集。

现有 `benchmark/run.py` **仅支持图片，调用 MobileNet 生产搜索链路**；转换出的 JSON 可以直接供它使用，但不会自动改成 DINO benchmark。评测 july_test/DINO 时需将同一案例清单接入相应实验 runner；文字反馈还需要文字评测 runner，不能拿图片 runner 代跑。本轮没有运行任何真实 benchmark 或扩展评测算法。

仅检查非空案例清单可用（不加载模型或索引）：

```powershell
& .\.venv-cuda-test\Scripts\python.exe -X utf8 -B benchmark/run.py --cases benchmark/feedback/exports/benchmark_cases_实际ID.json --validate-only
```

## 轻量验证

```powershell
& .\.venv-cuda-test\Scripts\python.exe -X utf8 -B -m unittest benchmark.feedback.test_store -v
& .\.venv-cuda-test\Scripts\python.exe -X utf8 -B -m unittest discover -s benchmark/experiments/dino_july_web -p test_ui.py -v
```

使用临时数据库、合成图片与 july_test 模拟引擎；测试数据不会进入真实反馈库。覆盖图文查询、搜索快照、正确/未命中互改、重复点击、时间校验、空结果、失败搜索、写入失败、中文 CSV、原图恢复、现有 benchmark 清单读取。原搜索/adapter、数据库/路径和 benchmark 指标测试也通过，总计64项。未执行含真实 CPU/GPU 推理的设备测试或 smoke_test.py。

人工使用时：搜索后给第2个结果填 `00:02:03.500` 与备注并确认，检查下方记录；改点“没有正确结果”确认覆盖；另做图片查询、确认素材且留空时间；导出 CSV，核对两次搜索ID不同、原查询可恢复、空时间仍为空。正式建库运行期间，本轮仅做模拟引擎 AppTest 验证，未主动进行真实图文推理。
