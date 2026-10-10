# TopK召回范围实验

只在独立进程内改变候选数量，不修改磁盘上的生产代码、模型、预处理、索引、数据库、标注或评分规则。

## 方法

使用既有20例、原生产CPU环境与原搜索函数。FAISS分别检索20/50/100/200/500帧，保留原多正确ID、2秒时间容差和逐帧排名。

为避免五轮重复解码，对每例Top500候选执行一次原生产评分。实验只把函数内 `faiss_index.search(query_vec,20)` 的常数替换为500，其余函数体保持原样。内部请求最多500条评分输出，以保留所有通过原阈值的候选；各K最终结果仍截取10条。

各K独立执行真实FAISS检索，确认其候选属于Top500集合。随后用实际候选顺序恢复评分、稳定排序和Top10。由于原评分逐候选独立，与候选总量无关，这种复用不会引入新的排序公式。每例另外直接执行原Top20搜索，逐项比较返回结果（包括分数和顺序）；若不一致则停止，不生成成功结论。相同候选得分的多条记录按对应K原FAISS顺序处理。

保留原解码、镜像ORB、pHash、颜色、MobileNet权重和综合分数>0.2过滤。模型eval加载只做进程内缓存；不切换设备。没有人物crop、其他模型或额外查询变换。

## 指标

- 候选视频召回率：K候选里至少一条video_id属于acceptable_video_ids的case数/20。
- 候选时间召回率：K候选里至少一条正确视频且时间误差≤2秒的case数/20。
- 最终Top1/5/10视频命中率：应用原综合排序与阈值后，用现有benchmark计算。
- 最终Top1/5/10时间命中率：同一结果视频正确且时间误差≤2秒。

扩大候选池并不保证最终Top10提升：新加入的错误候选也可能获得更高综合分数。只有候选召回和最终结果分别统计，才能区分召回与排序瓶颈。Top500未召回也不能单独证明模型不足，仍需考虑标签、索引覆盖及历史解码质量。

## 运行

在项目根目录运行：

```powershell
$taskPython = (Get-Content config.json -Raw | ConvertFrom-Json).paths.python_executable
& $taskPython -X utf8 -B -m unittest benchmark.experiments.topk_recall.test_experiment benchmark.test_benchmark -v
& $taskPython -X utf8 -B benchmark/experiments/topk_recall/run_experiment.py
```

结果写入本目录的 `results/日期_唯一ID/`。每例完成后保存独立JSON，记录Top500原候选、通过阈值的全部评分、各K候选命中和最终结果。完成所有20例后生成汇总 `report.json`；中途失败的目录不是完整实验报告。

协议在正式评分前保存，包含源码和标注哈希、环境及固定方法。实验结束检查生产文件元数据、代码配置及模型哈希。耗时包含评分复用，不作为五个K各自的生产性能benchmark。
