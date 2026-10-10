# 独立embedding对比实验

已完成结果：[实验报告](results/20260927_005843/实验报告.md)。小规模实验图库结果，不代表完整159万帧全库召回率。

原图库717帧保留，实际统一使用715帧；异常见excluded_frames.json。不要为复测重新运行prepare_gallery.py。现有20个案例与评分均保持不变。

复测命令（使用有权限读取实验deps和weights的终端）：

```powershell
& .\.venv-cuda-test\Scripts\python.exe -X utf8 -B benchmark/experiments/embedding_comparison/run_comparison.py
```

该命令复用固定图片与本地权重，在新results目录运行三组。中途停止可用`--resume <results目录>`复用已完成模型；先核验输入/权重/协议一致。不联网，不抽取视频，不改生产。

本次修改仅run_comparison.py：明确排除获批准的两帧、保留异常、支持续跑、使用CLIP完整权重对应的图像特征接口；修改前备份保留。新增日志、异常列表、实验特征/评分JSON/报告均在本目录。模型配置未修改。
