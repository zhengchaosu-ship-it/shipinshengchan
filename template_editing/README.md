# Template Editing V0.1

独立内容片段推荐与人工审核。复用只读正式Speech BGE与原字幕，不修改寻帧、正式库和auto_remake。未实现自动组合、Transition Scoring、timeline或剪映草稿。

## 日常审核

双击项目根目录 `打开模板候选审核.bat`，访问 `http://127.0.0.1:8503/report.html`。也可直接运行：

```powershell
.\.venv-cuda-test\Scripts\python.exe -X utf8 -B -m template_editing.serve
```

服务仅监听127.0.0.1，与寻帧8502独立。已有服务时直接访问地址。选择“会用/勉强可用/不会用”，填写备注，点击保存；刷新后恢复。反馈写本模块结果目录 `template_feedback.json`，按report_id/slot_id/segment_id区分，重复CALL_RESULT位置不会互相覆盖。直接双击HTML仍可看预览，但保存需本机服务。

## 重现

```powershell
# 已有结果可直接看，不必重新计算。
.\.venv-cuda-test\Scripts\python.exe -X utf8 -B -m template_editing.run all
# 分阶段：原召回 → Gold增量 → 片段、排序、有限预览、报告
.\.venv-cuda-test\Scripts\python.exe -X utf8 -B -m template_editing.run recall
.\.venv-cuda-test\Scripts\python.exe -X utf8 -B -m template_editing.gold
.\.venv-cuda-test\Scripts\python.exe -X utf8 -B -m template_editing.run review
```

原始 `recall.json` 与增量 `recall_with_gold.json` 分别保留。索引本身不做任何写入。入口首次保存保护快照，后续不覆盖；正式数据若发生合法变更须先人工审查快照差异。依赖沿用现有环境，不联网下载。

Gold提取通过 `gold_extract.py <xlsx> <output-json>`，只读Excel；首次20行的功能映射在该脚本中逐行记录阅读依据。新案例行需审核映射，不机械依赖“逼单/反馈”标签。当前Gold JSON为独立副本，原Excel未经修改。15条话术、5条标题/摘要，25个有限长度原型；病例中的疗效表述并未经系统证实。

## 数据和评分

- `content_pool/schema.py` 定义ContentSegment，池文件在 `content_pool/results/consult_conversion_v1_v01/segments.jsonl`。
- 回查原字幕ID和转写run；最多扩展前1句/后2句，3–20秒内连接，间隙≤1.5秒。上下文额外读至多前后4句，消歧只使用片段邻近各2句。
- 小妙招默认商品先验；商品证据优先于动作；没有商品证据且明确具体动作才判TIP_GENERIC。含糊和否定冲突保留原文及原因。
- 各slot最多500窗口，透明分类和7项基础分；Gold占最终分12%，无共同功能不加分，摘要原型折减。不是概率，也不能证明会用或销售表现。
- Gold相似度使用本地同一BGE，对匿名化候选与原型计算归一化向量内积，保留原话、单元格、功能、共同功能理由及最相似子句。
- 模板是有序slot列表，每项独立ID和可重复type；当前8个位置，不在协议层限制数量。Slot5/7允许同池候选，未进行跨slot组合。`evaluate_transition`返回None表示未实现。
- 原画面等比缩放为有限MP4预览，原声转AAC；不加旁白/背景音。不修改原视频。解码检查视频、音轨、时长；失败记录并换下一候选，不伪报成功。
- 场景/说话人由字幕规则推测，未做视觉验证；效果问句不会标成肯定PROOF；原ASR错误和字幕剪点偏差需人工试听。

## 测试

```powershell
.\.venv-cuda-test\Scripts\python.exe -X utf8 -B -m unittest discover -s content_pool/tests -v
.\.venv-cuda-test\Scripts\python.exe -X utf8 -B -m unittest discover -s template_editing/tests -v
.\.venv-cuda-test\Scripts\python.exe -X utf8 -B -m unittest discover -s tests -v
.\.venv-cuda-test\Scripts\python.exe -X utf8 -B -m unittest discover -s speech_search/tests -v
```

新测试生成3个8秒合成视频并检查预览/源文件不变，验证反馈更新、重复slot隔离、HTTP Range及同源约束。原项目回归使用已有测试，不运行生产全库建库。验收统计与每slot各阶段耗时见结果目录 `report.md` 和 `report_data.json`。
