# 可重复运行的检索 benchmark

独立调用当前生产搜索函数，不改生产流程、模型、预处理、数据库或FAISS索引。评估范围为现有完整链路：MobileNetV2查询embedding → FAISS Top20粗筛 → 原ORB/pHash/颜色综合评分 → 原阈值过滤 → Top10结果。

## 目录

```text
benchmark/
  __init__.py
  run.py                 # 校验案例、顺序搜索、计算指标和生成报告
  search_adapter.py      # 从video_search.py读取现有搜索函数，跳过页面/维护入口
  test_benchmark.py      # 评估指标与案例解析测试
  cases/
    example.json         # 一个有来源记录的示例case
  queries/
    example.jpg          # 复制自现有素材帧缩略图
  results/
    日期时间_唯一ID/
      report.json        # 指标、环境、标注、每条结果和错误
      report.md          # 可读的汇总报告
```

## 使用方法

在项目根目录打开PowerShell，使用当前配置中的已安装依赖的解释器：

```powershell
$taskPython = (Get-Content config.json -Raw | ConvertFrom-Json).paths.python_executable
# 仅校验案例结构和图片路径，不加载模型/索引
& $taskPython -X utf8 -B benchmark/run.py --cases benchmark/cases/example.json --validate-only
# 自动执行搜索并生成独立报告
& $taskPython -X utf8 -B benchmark/run.py --cases benchmark/cases/example.json
```

省略 `--cases` 时使用 example.json。每次运行生成新的results子目录，不覆盖旧报告。程序正常完成返回0；案例格式/视频ID无效、生产文件变化或case运行错误时返回非0。单case运行错误会记录在报告中，继续处理其他case；启动错误直接停止。

设备读取现有 `config.json` 的 `query_device`，当前默认CPU。没有benchmark专用的生产配置写操作；切换解释器/设备前沿用项目已验证的方法。若使用 `VIDEO_SEARCH_CONFIG`，该环境变量也会被正常读取。

首次查询需加载约7.6GB生产索引及元数据；同次运行复用索引。只顺序运行案例，避免现有全局查询图被并发覆盖。缺少索引或本地权重时直接停止，不创建空库、不建索引、不下载模型，也不回退全库特征扫描。

## 添加案例

将图片放入queries，复制example.json为新的清单，例如cases/my_cases.json，修改/追加cases：

```json
{
  "schema_version": 1,
  "time_tolerance_seconds": 2.0,
  "cases": [
    {
      "id": "query_001",
      "image": "../queries/example.jpg",
      "acceptable_video_ids": [11],
      "expected_timestamp": 5460.0
    }
  ]
}
```

- `id`：唯一非空名称。
- `image`：查询图片；相对路径基于**案例JSON所在目录**，也可使用绝对路径。
- `acceptable_video_ids`：非空正整数列表，例如 `[14, 181]`，表示返回任意一个ID都算视频命中。不取最小ID，不选择代表ID。ID是当前生产数据库的 `videos.id`，不是截图序号或FAISS行号；不允许重复ID，正式运行前只读核对列表中每个ID存在。
- 兼容旧清单的 `expected_video_id`：自动作为单元素列表使用。两个字段同时存在时，旧ID必须在列表内，否则拒绝运行；评分仍接受整个列表。
- `expected_timestamp`：正确位置，单位秒，支持小数；如01:31:00为5460秒。
- `time_tolerance_seconds`：全局默认2秒，也可在单个case内覆盖。必须为非负有限数。

每个case可指定多个正确视频ID，共用一个 `expected_timestamp` 和时间容差。适用于时间轴一致的重复导入或备份视频；若视频经过剪辑导致时间轴不同，不能直接共享此时间标注。保留逐帧排名，不按视频去重，不自动生成标签。请人工确认标签，不根据搜索结果反向生成标签。

本次多ID框架更新未执行20个真实业务案例的baseline；原始图片和表格保持原样。

## 指标口径

报告分别列出两组Top1/5/10指标：

- **video命中**：返回 `video_id` 在 `acceptable_video_ids` 中，不限制时间。
- **timestamp命中**：同一条结果满足video命中，且与 `expected_timestamp` 的绝对误差 ≤ case容差。错误视频即使时间戳相同，也不算timestamp命中。

保留原搜索结果逐帧排序，不按视频去重；重复视频不会增加案例分母，也不会让同一案例多计命中。

- Top1准确率：第1条满足相应命中条件的case数 / 全部case数。
- Top5命中率：前5条至少一条满足相应命中条件的case数 / 全部case数。
- Top10命中率：前10条至少一条满足相应命中条件的case数 / 全部case数。
- 平均时间误差：对Top10内出现正确视频的case，取**其中排名最高的正确视频条目**，计算与标注时间的绝对误差，再求平均；不从多个候选中挑误差最小者，也不要求该误差在容差内。

平均时间误差同时输出有效样本数。完全没找到正确视频的case不参与该均值，不虚记0秒；有效样本数为0时输出JSON null / Markdown N/A。该均值有条件采样性质，必须结合命中率、样本数阅读。

JSON汇总分别输出 `video_hit_rates` 和 `timestamp_hit_rates`；逐case分别输出 `video_hits` 和 `timestamp_hits`，键为 `"1"`、`"5"`、`"10"`。`time_error_video_id` 记录参与时间误差计算的实际视频ID。

兼容旧报告字段：`video_only_hit_rates` / `video_only_hits` 是video指标的别名；`top1_accuracy`、`top5_hit_rate`、`top10_hit_rate` / `hits` 保持原含义，对应timestamp指标。历史报告不回写。

损坏图片、运行异常计入错误列表且按未命中计入分母，不偷偷剔除。生产搜索内部原有的异常回退仍保持原样，`sim_detail`保留在结果中；解码器警告继续输出到终端，不将警告自动等同于case失败。

## 重复性与只读边界

- 每次从现有video_search.py读取实际函数体及ORB初始化参数，不复制另一套排序实现。仅把Streamlit索引缓存替换为独立进程内等价缓存，跳过UI和维护按钮。
- 数据库连接沿用默认只读方式；只执行现有搜索查询及ID映射，不写数据库。
- 不调用生产批量录入、索引构建或缩略图生成脚本。原匹配函数遇到缺失缓存时可能只读打开候选视频，行为与现有搜索一致。
- 报告记录清单与图片哈希、生产搜索源码与权重哈希、实际解释器/torch/FAISS/device、生产文件大小/修改时间及逐case完整结果。
- 再次比较时应保持同一清单、图片、素材、缩略图缓存、索引和环境；缓存或素材变化仍可能影响原算法结果。运行中校验生产文件元数据和源码/权重哈希；不对几十GB生产数据做全字节哈希。
- 每个case的elapsed_seconds包含当前实际执行开销，首次查询包含索引加载；本框架不把该字段当作严格性能benchmark。

## 示例与验证

example.jpg来自已有 `11_5460.0.jpg`，正确ID/时间沿用此前已核对的生产元数据；它不是历史用户查询。仅一个示例用于验证框架，不代表整体检索准确率。

已运行一次完整示例搜索：未命中，Top1/5/10均为0，平均时间误差N/A，有效时间样本0/1，运行错误0。报告保留在results；未因结果不佳更换示例或调整算法。过程中候选视频解码器有H.264警告，按原逻辑保留。

框架测试：

```powershell
& $taskPython -X utf8 -B -m unittest benchmark.test_benchmark -v
```

覆盖多正确ID（含较大ID命中）、video与timestamp指标区分、时间误差取最高排名可接受结果、Top5/10边界、空结果/运行错误分母、旧单ID兼容、冲突及无效列表、示例相对路径解析。
