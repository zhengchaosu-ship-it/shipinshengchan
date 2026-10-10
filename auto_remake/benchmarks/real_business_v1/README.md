# REAL BUSINESS BENCHMARK V1

按用户确认，只执行现有4条新视频。88888888重复片不参与主统计。

最终状态：`COMPLETE_WITH_LIMITATIONS`。3条完整执行，case_02 有1个候选音频带未通过既有95%解码覆盖门槛。全部已验证区域无严格接受片段；不能将未完成区域记成确定检索失败。

查看 `report.md` 或离线 `report.html`。机器结果见 `results.json`、`results.csv`；原始候选、时间带和固定十档音频分数在各 case 子目录。没有外部GT，不提供伪造的召回率或时间准确率。

## 复现与断点

在 `D:\video_search_tool` 的 PowerShell 中：

```powershell
$env:PYTHONPATH='D:\video_search_tool\benchmark\experiments\embedding_comparison\deps;D:\video_search_tool'
$env:HF_HUB_OFFLINE='1'
.\.venv-cuda-test\Scripts\python.exe -X utf8 -B -m auto_remake.business_benchmark --case all
.\.venv-cuda-test\Scripts\python.exe -X utf8 -B -m auto_remake.business_speed --case all
.\.venv-cuda-test\Scripts\python.exe -X utf8 -B -m auto_remake.business_report
```

已完成Baseline及音频带复用缓存。不要删除结果从头运行；不要修改失败门槛或自动修复源视频。case_02的解码异常保留原始证据，本任务没有重试放宽门槛。

`baseline_freeze.json`及`speed_diagnostics_plan.json`保存执行前冻结方案，其中`FROZEN_NOT_EXECUTED`是当时状态，不代表尚未运行。当前状态见`execution_summary.json`及`final_validation.json`。

## 验证

- 67项单元回归通过，完整日志：`test_results.txt`。
- 4个新增Python文件语法通过；代码摘要：`implementation_manifest.json`。
- 42个冻结代码/规则文件SHA256一致，历史适配回放一致。
- 1319个生产/历史文件轻量校验一致：大小、mtime及预先记录的小文件SHA256。
- 所有参考输入SHA256一致；Baseline目录所有文件SHA256在诊断前后一致。
- 70个成功音频带共125个候选/参考块组合，统一测试10个倍率；1.0倍率分数复现Baseline。
- 1.20倍合成正控通过，不计入业务指标。

没有修改生产模型、索引、Web、旧实验结果或源视频。没有继续优化算法，也没有生成剪辑或剪映草稿。
