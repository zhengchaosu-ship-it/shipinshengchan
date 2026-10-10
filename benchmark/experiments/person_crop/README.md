# 人物区域独立实验

这是实验目录，不导入生产入口。项目目录当前不是Git仓库，因此采用独立目录隔离，没有创建或合并Git分支。

## 固定实验口径

- 使用既有20例清单、多正确ID和逐帧Top1/5/10视频命中规则。
- 原FAISS索引只读，每个query全图embedding取Top20；三组候选池完全相同。
- A：全图FAISS余弦分数。它是纯embedding对照，不是原生产ORB/pHash/颜色综合排序；报告另列原生产baseline。
- B：query和候选各自检测人脸并扩展人物框，使用原MobileNetV2和预处理提取crop embedding。多框之间取最大余弦分数。
- C：0.5 × A分数 + 0.5 × crop分数。两种分数都是归一化embedding余弦，不进行按标签拟合或权重搜索。
- 无脸、不可用裁剪或候选解码失败时，B/C该候选回退A分数，并记录原因。不删除案例或候选，不改变分母。
- 检测使用本地YuNet，阈值0.8，检测图长边最大640，人脸面积至少为画面0.5%；人物框宽3倍脸宽，范围从脸顶上0.25倍脸高至脸顶下5倍脸高，截断到图像边界。协议在检索前写入运行目录。

该方案不区分医生/患者，不等同于患者专属特征；可能漏检背身/小脸，也可能包含背景。配对取最大值可能由医生区域决定。它只评估人物区域重排，不能证明全库患者区域召回能力。

## 运行

在项目根目录PowerShell运行，使用当前CPU环境，不需安装依赖：

```powershell
$taskPython = (Get-Content config.json -Raw | ConvertFrom-Json).paths.python_executable
& $taskPython -X utf8 -B -m unittest benchmark.experiments.person_crop.test_experiment benchmark.test_benchmark -v
& $taskPython -X utf8 -B benchmark/experiments/person_crop/run_experiment.py
```

默认使用 `benchmark/cases/business20_baseline.json`，并核对其哈希与原baseline报告一致。每次生成独立结果目录，含运行前协议、各组指标、分类型结果、逐case结果、所有Top20候选、区域坐标、分数和回退状态。

数据库、索引、模型、生产代码与配置保持不变；仅实验输出写入本目录。沿用原候选取帧，不修复此前发现的解码问题。模型、检测器缺失时停止，不下载模型。

## 解释结果

先比较A/B/C在相同候选池中的效果，再将原生产baseline作为独立参考。候选池以外的正确视频不能被B/C补回；报告记录候选池视频命中上限及crop覆盖率。只有20个样本，每例对应5个百分点，不能据此宣称已证实泛化提升。二创截图与困难样本分别统计，普通截图本批为0例。

不根据本轮分数改动参数，不合并生产。
