# 源视频播放位置人工对照

使用项目内 `bin/ffmpeg.exe`，按 repaired metadata 的新 timestamp 从源视频独立 seek 并导出 JPEG。人工比较修复 shard 中的 JPEG 与独立 seek 结果；允许秒内相邻帧差。

| video_id | 类型 | 新 timestamp | 修复 JPEG | 源视频 seek JPEG | 结果 |
|---:|---|---:|---|---|---|
| 4 | rerun_dino | 2555.019 | [video_4_58969.jpg](samples/video_4_58969.jpg) | [source](source_seek_checks/video_4_source_at_2555.019.jpg) | 通过，同一治疗场景与动作 |
| 342 | rerun_dino | 704.545 | [video_342_3316.jpg](samples/video_342_3316.jpg) | [source](source_seek_checks/video_342_source_at_704.545.jpg) | 通过，同一足部治疗场景 |
| 253 | metadata_only | 2541.584 | [video_253_49245.jpg](samples/video_253_49245.jpg) | [source](source_seek_checks/video_253_source_at_2541.584.jpg) | 通过，同一足部治疗场景与人物位置 |

三组源视频均能在新 timestamp 处成功解码；对照结果 3/3 通过。
