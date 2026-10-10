# 两例真实PTS验证

总结果：**通过**

| video_id | 旧FPS | avg/r FPS | time_base | 解码帧 | 1秒样本 | 最后PTS | 容器时长 | 原始reorder | 结果 |
|---:|---:|---|---|---:|---:|---:|---:|---:|---|
| 75 | 90000.0 | None/90000.0 | 1/90000 | 152,304 | 8,621 | 8620.205 | 8620.339 | 929 | 通过 |

video_id 75 JPEG人工抽查：

- first：frame 0，PTS 0.000s，[video_75_first_0.jpg](video_75_first_0.jpg)
- middle：frame 75723，PTS 4311.061s，[video_75_middle_75723.jpg](video_75_middle_75723.jpg)
- last：frame 152299，PTS 8620.005s，[video_75_last_152299.jpg](video_75_last_152299.jpg)
| 350 | 20.0 | 20.0/30.0 | 1/90000 | 132,128 | 4,406 | 4405.566 | 4405.686 | 0 | 通过 |

video_id 350 JPEG人工抽查：

- first：frame 0，PTS 0.000s，[video_350_first_0.jpg](video_350_first_0.jpg)
- middle：frame 66070，PTS 2203.018s，[video_350_middle_66070.jpg](video_350_middle_66070.jpg)
- last：frame 132112，PTS 4405.033s，[video_350_last_132112.jpg](video_350_last_132112.jpg)
