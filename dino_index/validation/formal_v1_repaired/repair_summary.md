# formal_v1_repaired 针对性修复总结

- 严格验收：**READY**
- metadata-only 修复：40 个（主要异常 27，轻微尾部异常 13）
- 单视频 DINO 重跑：13 个；名单：4, 7, 75, 82, 89, 90, 93, 126, 158, 159, 292, 333, 342
- 被替换的旧候选帧：45,652
- 新生成候选帧：80,374
- 净新增帧：34,722
- repaired 总帧数：1,843,351
- metadata / embedding / FAISS：1,843,351 / 1,843,351 / 1,843,351
- FAISS 大小：2,831,387,181 bytes
- timestamp 越界：0
- 逐 asset 严格单调失败：0
- 负 timestamp：0
- 查询速度：median 133.97 ms，P95 140.48 ms
- 总修复耗时：1 小时 21 分 11.3 秒
- 原 formal_v1 快照：329 个文件全部未变：True
- 未完成的 .building 文件：0
- Web search_index：`july_test`；已切换 repaired：False
