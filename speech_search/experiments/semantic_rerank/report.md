# 话术搜索V1 Semantic TopK精排验证

本轮不建议上线reranker；保留当前Semantic。Top20 window-only在32例和延迟上通过，但额外20例Top1从95%降至85%，收益没有稳定复现。

**实测最佳折中为Top20 + window only，但未通过额外20例。** 32例素材Top1从25/32升到27/32（78.1%→84.4%），救回B_fuzzy16、C_semantic23，新增素材Top1退化0；其中真正GT时间Top1只救回B_fuzzy16，C_semantic23仍优先给出GT前15秒的另一句话。额外20例素材Top1从19/20降至17/20（95%→85%），新增NEW15、NEW16两例退化，救回0。
32例正确时间Top10仍30/32，额外20例仍19/20。合计52例素材Top1为44/52→44/52，正确时间Top1为44/52→43/52；这只是描述性合计，不能抵消额外集退化。

## 模型与冻结实验

- 唯一reranker：**BAAI/bge-reranker-base**；revision `2cfc18c9415c912f9d8155881c133215df768a70`，官方约278M参数，原权重1,112,206,140 bytes，实验独立目录加载。
- 官方说明其为中英文cross-encoder、输入query/document直接输出相关性；参考[BAAI模型卡](https://huggingface.co/BAAI/bge-reranker-base)。中文与否定区分的实际表现以下方本地测试为准，不能由模型说明推定。
- 使用已有CUDA Python与Transformers，不重装生产依赖。RTX3060、FP16、batch8、最大512tokens；输出原始logit，不是概率，也不与Semantic/Fuzzy分数做加权融合。同logit仅以原semantic分数及window_id确定顺序。
- 只比较raw Semantic Top20、Top50、Top100。基线仍用当前Top200 + 原collapse，不增加Top500/1000模型精排。
- window输入：原query + candidate.original_text。context输入：原query + 前一句最后最多40token + 原窗口 + 后一句最前最多40token，核心窗口优先。query上限128tokens，无额外检索指令。
- 排序后复用现有collapse，未启用上一轮新增10秒规则，也未做新的去重实验。上下文不扩大输出窗口或GT时间判定，正确时间仍要求GT起点落在原窗口±2秒。
- 52例均重新生成查询向量和FAISS召回，但没有重新编码库存向量。6种组合在每例中轮换执行顺序，模型预热后计时；额外20例不用于改模型或调参数。
- 先按32例选择不降低素材Top5/Top10和时间Top10的方案，按素材Top1、时间Top1、较小K、window优先依次选择；随后额外20例检查不退化。交互延迟采用预先记录的总P95≤2秒判断，所有实测值仍完整披露。
- 模型加载1.14秒；Torch峰值分配显存0.566GiB，保留池0.596GiB；不含其它进程占用。
- 输入实际截断query或原window的pair数：0（上下文按固定上限裁剪另计）。

## 7个旧Top1错例的候选上限

| case | GT asset raw rank | 真正GT时间raw rank | 时间在Top10/20/50/100 | Top100可救状态 |
|---|---:|---:|---|---|
| B_fuzzy10 | 2 | 2 | 是/是/是/是 | GT_TIME_IN_POOL |
| B_fuzzy16 | 2 | 2 | 是/是/是/是 | GT_TIME_IN_POOL |
| C_semantic19 | 7 | 7 | 是/是/是/是 | GT_TIME_IN_POOL |
| C_semantic20 | 28 | 6827 | 否/否/否/否 | RERANK_UNRESCUABLE |
| C_semantic21 | 37 | 179 | 否/否/否/否 | RERANK_UNRESCUABLE |
| C_semantic22 | 3 | 3 | 是/是/是/是 | GT_TIME_IN_POOL |
| C_semantic23 | 2 | 3 | 是/是/是/是 | GT_TIME_IN_POOL |

真正GT时间口径：Top20/50/100都最多救回5/7。C_semantic20的asset虽在rank28，指定话术实际rank6827；C_semantic21的asset rank37，指定时间rank179。二者均为本轮RERANK_UNRESCUABLE，不把同asset错误时间包装为正确话术救回。

## 固定32例与额外20例

| 集合 | 方案 | 素材Top1 | Top5 | Top10 | 时间Top1 | 时间Top10 |
|---|---|---:|---:|---:|---:|---:|
| original32 | baseline | 25/32 (78.1%) | 29/32 (90.6%) | 30/32 (93.8%) | 25/32 (78.1%) | 30/32 (93.8%) |
| original32 | window_20 | 27/32 (84.4%) | 29/32 (90.6%) | 30/32 (93.8%) | 26/32 (81.2%) | 30/32 (93.8%) |
| original32 | context_20 | 22/32 (68.8%) | 28/32 (87.5%) | 30/32 (93.8%) | 17/32 (53.1%) | 30/32 (93.8%) |
| original32 | window_50 | 27/32 (84.4%) | 29/32 (90.6%) | 29/32 (90.6%) | 26/32 (81.2%) | 29/32 (90.6%) |
| original32 | context_50 | 22/32 (68.8%) | 28/32 (87.5%) | 30/32 (93.8%) | 16/32 (50.0%) | 30/32 (93.8%) |
| original32 | window_100 | 27/32 (84.4%) | 29/32 (90.6%) | 29/32 (90.6%) | 26/32 (81.2%) | 29/32 (90.6%) |
| original32 | context_100 | 22/32 (68.8%) | 28/32 (87.5%) | 29/32 (90.6%) | 15/32 (46.9%) | 29/32 (90.6%) |
| additional20 | baseline | 19/20 (95.0%) | 19/20 (95.0%) | 19/20 (95.0%) | 19/20 (95.0%) | 19/20 (95.0%) |
| additional20 | window_20 | 17/20 (85.0%) | 19/20 (95.0%) | 19/20 (95.0%) | 17/20 (85.0%) | 19/20 (95.0%) |
| additional20 | context_20 | 16/20 (80.0%) | 19/20 (95.0%) | 19/20 (95.0%) | 15/20 (75.0%) | 18/20 (90.0%) |
| additional20 | window_50 | 17/20 (85.0%) | 19/20 (95.0%) | 19/20 (95.0%) | 17/20 (85.0%) | 19/20 (95.0%) |
| additional20 | context_50 | 16/20 (80.0%) | 19/20 (95.0%) | 19/20 (95.0%) | 13/20 (65.0%) | 18/20 (90.0%) |
| additional20 | window_100 | 17/20 (85.0%) | 18/20 (90.0%) | 18/20 (90.0%) | 17/20 (85.0%) | 18/20 (90.0%) |
| additional20 | context_100 | 16/20 (80.0%) | 18/20 (90.0%) | 18/20 (90.0%) | 12/20 (60.0%) | 17/20 (85.0%) |

## 救回与新增退化

| 集合/方案 | Top1救回case | Top1退化case | 正确时间Top1救回 | 正确时间Top1退化 |
|---|---|---|---|---|
| original32/window_20 | B_fuzzy16, C_semantic23 | 无 | B_fuzzy16 | 无 |
| original32/context_20 | B_fuzzy10, C_semantic23 | A_exact08, B_fuzzy09, B_fuzzy14, C_semantic17, C_semantic24 | B_fuzzy10, C_semantic23 | A_exact08, B_fuzzy09, B_fuzzy14, C_semantic17, C_semantic24, D_cross25, D_cross26, D_cross27, D_cross28, D_cross29 |
| original32/window_50 | B_fuzzy16, C_semantic23 | 无 | B_fuzzy16 | 无 |
| original32/context_50 | B_fuzzy10, C_semantic23 | A_exact08, B_fuzzy09, B_fuzzy14, C_semantic17, C_semantic24 | B_fuzzy10, C_semantic23 | A_exact08, B_fuzzy09, B_fuzzy11, B_fuzzy14, C_semantic17, C_semantic24, D_cross25, D_cross26, D_cross27, D_cross28, D_cross29 |
| original32/window_100 | B_fuzzy16, C_semantic23 | 无 | B_fuzzy16 | 无 |
| original32/context_100 | B_fuzzy10, C_semantic23 | A_exact08, B_fuzzy09, B_fuzzy14, C_semantic17, C_semantic24 | B_fuzzy10 | A_exact08, B_fuzzy09, B_fuzzy11, B_fuzzy14, C_semantic17, C_semantic24, D_cross25, D_cross26, D_cross27, D_cross28, D_cross29 |
| additional20/window_20 | 无 | NEW15, NEW16 | 无 | NEW15, NEW16 |
| additional20/context_20 | 无 | NEW15, NEW16, NEW19 | 无 | NEW09, NEW15, NEW16, NEW19 |
| additional20/window_50 | 无 | NEW15, NEW16 | 无 | NEW15, NEW16 |
| additional20/context_50 | 无 | NEW15, NEW16, NEW19 | 无 | NEW01, NEW09, NEW15, NEW16, NEW17, NEW19 |
| additional20/window_100 | 无 | NEW15, NEW16 | 无 | NEW15, NEW16 |
| additional20/context_100 | 无 | NEW15, NEW16, NEW19 | 无 | NEW01, NEW09, NEW11, NEW15, NEW16, NEW17, NEW19 |

| 方案 | 7旧错例中asset Top1救回 | 真正GT时间Top1救回 |
|---|---|---|
| window_20 | 2：C_semantic23, B_fuzzy16 | 1：B_fuzzy16 |
| context_20 | 2：B_fuzzy10, C_semantic23 | 2：B_fuzzy10, C_semantic23 |
| window_50 | 2：C_semantic23, B_fuzzy16 | 1：B_fuzzy16 |
| context_50 | 2：B_fuzzy10, C_semantic23 | 2：B_fuzzy10, C_semantic23 |
| window_100 | 2：C_semantic23, B_fuzzy16 | 1：B_fuzzy16 |
| context_100 | 2：B_fuzzy10, C_semantic23 | 1：B_fuzzy10 |

## 旧7例逐例结果

| case | query | baseline素材/时间rank | 精排方案 | 精排素材/时间rank | Top1原文 | Top1 logit |
|---|---|---|---|---|---|
| B_fuzzy10 | 还是这个脚不是一个长一个段 | 2/2 | window_20 | 2/2 | 这个脚 这个不一段 | 6.9062 |
| B_fuzzy10 | 还是这个脚不是一个长一个段 | 2/2 | context_20 | 1/1 | 什么问题 还是这个脚不是一个长一个短 | 6.5547 |
| B_fuzzy10 | 还是这个脚不是一个长一个段 | 2/2 | window_50 | 2/2 | 这个脚 这个不一段 | 6.9062 |
| B_fuzzy10 | 还是这个脚不是一个长一个段 | 2/2 | context_50 | 1/1 | 什么问题 还是这个脚不是一个长一个短 | 6.5547 |
| B_fuzzy10 | 还是这个脚不是一个长一个段 | 2/2 | window_100 | 2/2 | 这个脚 这个不一段 | 6.9062 |
| B_fuzzy10 | 还是这个脚不是一个长一个段 | 2/2 | context_100 | 1/1 | 什么问题 还是这个脚不是一个长一个短 | 6.5547 |
| B_fuzzy16 | 但是我告诉她做没效果 | 2/2 | window_20 | 1/1 | 但是我告诉她她回去做没效果 | 7.8750 |
| B_fuzzy16 | 但是我告诉她做没效果 | 2/2 | context_20 | 2/2 | 她回去做没效果 | 7.2344 |
| B_fuzzy16 | 但是我告诉她做没效果 | 2/2 | window_50 | 1/1 | 但是我告诉她她回去做没效果 | 7.8750 |
| B_fuzzy16 | 但是我告诉她做没效果 | 2/2 | context_50 | 2/2 | 她回去做没效果 | 7.2344 |
| B_fuzzy16 | 但是我告诉她做没效果 | 2/2 | window_100 | 1/1 | 但是我告诉她她回去做没效果 | 7.8750 |
| B_fuzzy16 | 但是我告诉她做没效果 | 2/2 | context_100 | 2/2 | 她回去做没效果 | 7.2344 |
| C_semantic19 | 身体各个部位都是互相连通的 | 6/6 | window_20 | 6/6 | 人體是相通的 | 5.6797 |
| C_semantic19 | 身体各个部位都是互相连通的 | 6/6 | context_20 | 7/7 | 都可以 人體是相通的 今天教給你們的是心中 | 3.8047 |
| C_semantic19 | 身体各个部位都是互相连通的 | 6/6 | window_50 | Top10外/Top10外 | 人體是相通的 | 5.6797 |
| C_semantic19 | 身体各个部位都是互相连通的 | 6/6 | context_50 | 9/9 | 都可以 人體是相通的 今天教給你們的是心中 | 3.8047 |
| C_semantic19 | 身体各个部位都是互相连通的 | 6/6 | window_100 | Top10外/Top10外 | 人體是相通的 | 5.6797 |
| C_semantic19 | 身体各个部位都是互相连通的 | 6/6 | context_100 | 9/9 | 都可以 人體是相通的 今天教給你們的是心中 | 3.8047 |
| C_semantic20 | 这个部位完全没有疼痛感 | Top10外/Top10外 | window_20 | Top10外/Top10外 | 这个位置 还真没有疼的地方 | 7.6328 |
| C_semantic20 | 这个部位完全没有疼痛感 | Top10外/Top10外 | context_20 | Top10外/Top10外 | 这个位置 还真没有疼的地方 | 6.1758 |
| C_semantic20 | 这个部位完全没有疼痛感 | Top10外/Top10外 | window_50 | Top10外/Top10外 | 这个位置 还真没有疼的地方 | 7.6328 |
| C_semantic20 | 这个部位完全没有疼痛感 | Top10外/Top10外 | context_50 | Top10外/Top10外 | 这个位置 还真没有疼的地方 | 6.1758 |
| C_semantic20 | 这个部位完全没有疼痛感 | Top10外/Top10外 | window_100 | Top10外/Top10外 | 这个位置 还真没有疼的地方 | 7.6328 |
| C_semantic20 | 这个部位完全没有疼痛感 | Top10外/Top10外 | context_100 | Top10外/Top10外 | 还真没有疼的地方 | 6.4219 |
| C_semantic21 | 我的工作就是做这个 | Top10外/Top10外 | window_20 | Top10外/Top10外 | 我做的工作 就是这个 | 9.6562 |
| C_semantic21 | 我的工作就是做这个 | Top10外/Top10外 | context_20 | Top10外/Top10外 | 我做的工作 | 6.9336 |
| C_semantic21 | 我的工作就是做这个 | Top10外/Top10外 | window_50 | Top10外/Top10外 | 我做的工作 就是这个 | 9.6562 |
| C_semantic21 | 我的工作就是做这个 | Top10外/Top10外 | context_50 | Top10外/Top10外 | 我做的工作 | 6.9297 |
| C_semantic21 | 我的工作就是做这个 | Top10外/Top10外 | window_100 | Top10外/Top10外 | 我做的工作 就是这个 | 9.6562 |
| C_semantic21 | 我的工作就是做这个 | Top10外/Top10外 | context_100 | Top10外/Top10外 | 我做的工作 | 6.9297 |
| C_semantic22 | 老人自己在家也能操作 | 3/3 | window_20 | 3/3 | 老年人更有在家的學 他們更有時間做 | 4.3516 |
| C_semantic22 | 老人自己在家也能操作 | 3/3 | context_20 | 2/2 | 老年人更有在家的學 他們更有時間做 | 4.1836 |
| C_semantic22 | 老人自己在家也能操作 | 3/3 | window_50 | 4/4 | 老年人更有在家的學 他們更有時間做 你知道嗎 | 4.5430 |
| C_semantic22 | 老人自己在家也能操作 | 3/3 | context_50 | 2/2 | 老年人更有在家的學 他們更有時間做 | 4.1836 |
| C_semantic22 | 老人自己在家也能操作 | 3/3 | window_100 | 4/4 | 老年人更有在家的學 他們更有時間做 你知道嗎 | 4.5430 |
| C_semantic22 | 老人自己在家也能操作 | 3/3 | context_100 | 2/2 | 老年人更有在家的學 他們更有時間做 | 4.1836 |
| C_semantic23 | 按到三百下的时候 | 2/3 | window_20 | 1/2 | 按到三百次的时候 | 6.1875 |
| C_semantic23 | 按到三百下的时候 | 2/3 | context_20 | 1/1 | 按三百次的时候 | 2.9316 |
| C_semantic23 | 按到三百下的时候 | 2/3 | window_50 | 1/2 | 按到三百次的时候 | 6.1875 |
| C_semantic23 | 按到三百下的时候 | 2/3 | context_50 | 1/1 | 按三百次的时候 | 2.9316 |
| C_semantic23 | 按到三百下的时候 | 2/3 | window_100 | 1/2 | 按到三百次的时候 | 6.1875 |
| C_semantic23 | 按到三百下的时候 | 2/3 | context_100 | 1/2 | 一百下 | 3.0664 |

## 关键错例与上下文收益判断

- B_fuzzy16：GT完整句“但是我告诉她她回去做没效果”logit7.875，高于另一asset几乎同文候选7.6016，指定素材与时间均提升至Top1。
- C_semantic23：正确asset升Top1，但首先返回9962.64秒的“按到三百次的时候”；指定GT9977.64秒的“按三百次的时候”仍排第二。不能宣称两例真正话术时点都救回。
- NEW15：query“这里皮肤肌肉以及深处都会疼”，GT“这边的皮上疼,还有肌肉疼,还有里面疼”从1降至4（Top20），reranker logit3.1699；局部短句“越是這邊疼 這個肌肉”以4.8359领先。Top100时GT掉出Top10，扩池增加了其它局部短句干扰。
- NEW16：简体GT“你以为我是的是推拉还是按摩”5.7617，被另一asset繁体近乎同句5.8477超过，rank1→2。两者时间也相近，可能存在同源内容/标注歧义，但未做音视频确认，不修改asset或GT，仍按固定评测计退化。
- NEW13：GT时间raw rank76，Top20/50不在池；Top100已在池但GT logit2.0586，仍未进Top10。对比“腰有点酸”4.5234，说明扩大到100并没有自动解决这条模糊改写。
- small context未带来整体收益：32例素材Top1为22/32，低于baseline25/32与window-only27/32；额外20例16/20，低于baseline19/20。正确时间Top1下降更明显。
- 上下文可能让模型给邻句窗口高分：NEW09的query包含“就在这个中间…”，context方案首条窗口只有“腰疼了 包括流伤了”，匹配开头在前一句。返回窗口从463.8秒开始，GT460.38秒超过±2秒容差；不能通过把上下文时间算作输出时间来提高分数。本轮保持原时间判定。

## 否定表达诊断

词面筛选包括不、不是、没有、并非、不一定、不能、不要及没/未/无；含词不等于肯否反转（如有没有、不同）。不加手写规则、不修改原句。C_semantic20的真正否定GT未入池，reranker不能解决该条召回问题；其它视频的否定句也不能重新标作指定GT。

| query | 候选句 | reranker logit |
|---|---|---:|
| 腰疼是腰的问题 | 腰疼是腰的问题 | 10.2969 |
| 腰疼是腰的问题 | 腰疼不一定是腰的问题 | 6.4219 |
| 腰疼不一定是腰的问题 | 腰疼是腰的问题 | 6.2109 |
| 腰疼不一定是腰的问题 | 腰疼不一定是腰的问题 | 10.2734 |

以上是用户例句的固定2×2诊断，不计入52例准确率；即使通过也不能证明复杂否定已解决。
实测有局部改善：C_semantic20的Top20原来首位“一個部位疼”在reranker中仅1.9346；否定候选“这个位置 还真没有疼的地方”为7.6328并升Top1，差5.6982。该候选来自其它asset，真正GT仍在rank6827而不在精排池，素材/时间命中仍失败。2×2例句也都更偏向同含义句，但不足以断言所有否定问题解决；没有添加任何否定规则。

| 集合/case | query | 方案 | Top1原文 | GT素材/时间rank |
|---|---|---|---|---|
| original32/A_exact01 | 但是它没考虑到这个时候压迫到这块的肌肉 | baseline | 但是它没考虑到这个时候压迫到这块的肌肉 | 1/1 |
| original32/A_exact01 | 但是它没考虑到这个时候压迫到这块的肌肉 | window_20 | 但是它没考虑到这个时候压迫到这块的肌肉 | 1/1 |
| original32/A_exact02 | 这是两边肌肉受力不平衡引起的 | baseline | 这是两边肌肉受力不平衡引起的 | 1/1 |
| original32/A_exact02 | 这是两边肌肉受力不平衡引起的 | window_20 | 这是两边肌肉受力不平衡引起的 | 1/1 |
| original32/A_exact03 | 我跟你说 就一个腰疼陶老师有十几种解访 | baseline | 我跟你说 就一个腰疼陶老师有十几种解访 | 1/1 |
| original32/A_exact03 | 我跟你说 就一个腰疼陶老师有十几种解访 | window_20 | 我跟你说 就一个腰疼陶老师有十几种解访 | 1/1 |
| original32/A_exact05 | 这个骨头跟肌肉不在一个条线上 | baseline | 这个骨头跟肌肉不在一个条线上 | 1/1 |
| original32/A_exact05 | 这个骨头跟肌肉不在一个条线上 | window_20 | 这个骨头跟肌肉不在一个条线上 | 1/1 |
| original32/B_fuzzy09 | 吹风机吹吹晚上再吹吹 | baseline | 吹风机吹一吹 晚上再吹一吹 | 1/1 |
| original32/B_fuzzy09 | 吹风机吹吹晚上再吹吹 | window_20 | 吹风机吹一吹 晚上再吹一吹 | 1/1 |
| original32/B_fuzzy10 | 还是这个脚不是一个长一个段 | baseline | 这个脚 这个不一段 | 2/2 |
| original32/B_fuzzy10 | 还是这个脚不是一个长一个段 | window_20 | 这个脚 这个不一段 | 2/2 |
| original32/B_fuzzy11 | 刮出包要不要处理继续刮就好了 | baseline | 刮出包这个包要不要处理 继续刮就好了 | 1/1 |
| original32/B_fuzzy11 | 刮出包要不要处理继续刮就好了 | window_20 | 刮出包这个包要不要处理 继续刮就好了 | 1/1 |
| original32/B_fuzzy12 | 这反正走路不安走这边都软的 | baseline | 这反正走路不安走,这边都是软的。 | 1/1 |
| original32/B_fuzzy12 | 这反正走路不安走这边都软的 | window_20 | 这反正走路不安走,这边都是软的。 | 1/1 |
| original32/B_fuzzy13 | 我这个调整一下这块的肌裙 | baseline | 我这个调整一下这块的肌群 | 1/1 |
| original32/B_fuzzy13 | 我这个调整一下这块的肌裙 | window_20 | 我这个调整一下这块的肌群 | 1/1 |
| original32/B_fuzzy15 | 那你就按两百次一阻 | baseline | 那你就按两百次一组 | 1/1 |
| original32/B_fuzzy15 | 那你就按两百次一阻 | window_20 | 那你就按两百次一组 | 1/1 |
| original32/B_fuzzy16 | 但是我告诉她做没效果 | baseline | 但是我告诉她 她回去做没效果 但是我问她 | 2/2 |
| original32/B_fuzzy16 | 但是我告诉她做没效果 | window_20 | 但是我告诉她她回去做没效果 | 1/1 |
| original32/C_semantic20 | 这个部位完全没有疼痛感 | baseline | 一個部位疼 | Top10外/Top10外 |
| original32/C_semantic20 | 这个部位完全没有疼痛感 | window_20 | 这个位置 还真没有疼的地方 | Top10外/Top10外 |
| original32/D_cross26 | 这边住完了就住这边 这是两边肌肉受力不平衡引起的 | baseline | 这边住完了就住这边 这是两边肌肉受力不平衡引起的 | 1/1 |
| original32/D_cross26 | 这边住完了就住这边 这是两边肌肉受力不平衡引起的 | window_20 | 这边住完了就住这边 这是两边肌肉受力不平衡引起的 | 1/1 |
| original32/D_cross27 | 每个解访它不同 你给我个手也行 给个脚也行 给个头也行 给个偶都也行 | baseline | 每个解访它不同 你给我个手也行 给个脚也行 给个头也行 给个偶都也行 | 1/1 |
| original32/D_cross27 | 每个解访它不同 你给我个手也行 给个脚也行 给个头也行 给个偶都也行 | window_20 | 每个解访它不同 你给我个手也行 给个脚也行 给个头也行 给个偶都也行 | 1/1 |
| original32/D_cross28 | 这反正走路不安走,这边都是软的。 来,现在再走走。 | baseline | 这反正走路不安走,这边都是软的。 来,现在再走走。 | 1/1 |
| original32/D_cross28 | 这反正走路不安走,这边都是软的。 来,现在再走走。 | window_20 | 这反正走路不安走,这边都是软的。 来,现在再走走。 | 1/1 |
| original32/D_cross31 | 那你就按两百次一组 不就行的吗 | baseline | 那你就按两百次一组 不就行的吗 | 1/1 |
| original32/D_cross31 | 那你就按两百次一组 不就行的吗 | window_20 | 那你就按两百次一组 不就行的吗 | 1/1 |
| original32/D_cross32 | 按摩椅完以后的时候感觉舒服 过了没多久的话 | baseline | 按摩椅完以后的时候感觉舒服 过了没多久的话 | 1/1 |
| original32/D_cross32 | 按摩椅完以后的时候感觉舒服 过了没多久的话 | window_20 | 按摩椅完以后的时候感觉舒服 过了没多久的话 | 1/1 |
| additional20/NEW01 | 我看他们按摩进去,我这个全是肉。 | baseline | 我看他们按摩进去,我这个全是肉。 | 1/1 |
| additional20/NEW01 | 我看他们按摩进去,我这个全是肉。 | window_20 | 我看他们按摩进去,我这个全是肉。 | 1/1 |
| additional20/NEW02 | 按摩 跑到我刚才教你的方法去做 | baseline | 按摩 跑到我刚才教你的方法去做 | 1/1 |
| additional20/NEW02 | 按摩 跑到我刚才教你的方法去做 | window_20 | 按摩 跑到我刚才教你的方法去做 | 1/1 |
| additional20/NEW05 | 不管头疼腰疼腿疼肩膀疼蹲不下起不来的 | baseline | 不管是头疼,压疼,腰疼,腿疼,肩膀疼,蹲下,蹲不下,起不来的。 | 1/1 |
| additional20/NEW05 | 不管头疼腰疼腿疼肩膀疼蹲不下起不来的 | window_20 | 不管是头疼,压疼,腰疼,腿疼,肩膀疼,蹲下,蹲不下,起不来的。 | 1/1 |
| additional20/NEW08 | 一边肌肉发达一边肌肉尾说不行 | baseline | 那一边肌肉发达一边肌肉尾说那不行 | 1/1 |
| additional20/NEW08 | 一边肌肉发达一边肌肉尾说不行 | window_20 | 那一边肌肉发达一边肌肉尾说那不行 | 1/1 |
| additional20/NEW10 | 你起来才知道你腰腾不疼了 | baseline | 你起来 你起来才知道你腰疼不疼了 | 1/1 |
| additional20/NEW10 | 你起来才知道你腰腾不疼了 | window_20 | 你起来 你起来 你起来才知道你腰疼不疼了 | 1/1 |
| additional20/NEW11 | 腰痛直不起来看我的视屏也不用 | baseline | 腰痛直不起来,看我的视频也不用 | 1/1 |
| additional20/NEW11 | 腰痛直不起来看我的视屏也不用 | window_20 | 腰痛 直不起来看我的视频 也不用 | 1/1 |
| additional20/NEW12 | 这边这一块这两块肌肉一弄就胀痛了新给他上脸六要不然我弄他他会疼呢 | baseline | 这边这一块这两块肌肉,一弄就账痛了,新给他上脸六,要不然我弄他他会疼呢, | 1/1 |
| additional20/NEW12 | 这边这一块这两块肌肉一弄就胀痛了新给他上脸六要不然我弄他他会疼呢 | window_20 | 这边这一块这两块肌肉,一弄就账痛了,新给他上脸六,要不然我弄他他会疼呢, 上次也买了一瓶这个, | 1/1 |
| additional20/NEW13 | 你的腰有没有酸痛的感觉 | baseline | 有动不动 酸不酸的腰 | Top10外/Top10外 |
| additional20/NEW13 | 你的腰有没有酸痛的感觉 | window_20 | 腰有点酸 | Top10外/Top10外 |
| additional20/NEW14 | 我没说按摩一定很舒服 | baseline | 好舒服 我也不是说按摩的好舒服什么 | 1/1 |
| additional20/NEW14 | 我没说按摩一定很舒服 | window_20 | 嗯好舒服 好舒服 我也不是说按摩的好舒服什么 | 1/1 |
| additional20/NEW17 | 它这个痛风,我也是挺自己的,就是有没有运到好的妙症,让它自己按摩 对,这个风又看到到什么情况下,就像弹高也是一样的 | baseline | 它这个痛风,我也是挺自己的,就是有没有运到好的妙症,让它自己按摩 对,这个风又看到到什么情况下,就像弹高也是一样的 | 1/1 |
| additional20/NEW17 | 它这个痛风,我也是挺自己的,就是有没有运到好的妙症,让它自己按摩 对,这个风又看到到什么情况下,就像弹高也是一样的 | window_20 | 它这个痛风,我也是挺自己的,就是有没有运到好的妙症,让它自己按摩 对,这个风又看到到什么情况下,就像弹高也是一样的 | 1/1 |
| additional20/NEW19 | 没听懂什么意思就是能给你按摩 对 给我按摩 | baseline | 没听懂什么意思就是能给你按摩 对 给我按摩 | 1/1 |
| additional20/NEW19 | 没听懂什么意思就是能给你按摩 对 给我按摩 | window_20 | 没听懂什么意思就是能给你按摩 对 给我按摩 | 1/1 |
| additional20/NEW20 | 還有尖夾骨鳳,又求按摩,又求推拉 又是砸什麼增的,多不多? | baseline | 還有尖夾骨鳳,又求按摩,又求推拉 又是砸什麼增的,多不多? | 1/1 |
| additional20/NEW20 | 還有尖夾骨鳳,又求按摩,又求推拉 又是砸什麼增的,多不多? | window_20 | 還有尖夾骨鳳,又求按摩,又求推拉 又是砸什麼增的,多不多? | 1/1 |

## 性能（52次暖查询，各组合52次）

Semantic FAISS median/P95：277.8/332.6ms；基线总计算：302.4/356.4ms。

| 方案 | 精排额外median ms | P95 ms | 总查询median ms | P95 ms |
|---|---:|---:|---:|---:|
| window_20 | 19.4 | 42.6 | 329.4 | 381.5 |
| context_20 | 29.3 | 50.0 | 338.2 | 391.8 |
| window_50 | 46.1 | 79.5 | 356.6 | 422.4 |
| context_50 | 65.5 | 97.6 | 386.8 | 437.7 |
| window_100 | 84.5 | 124.4 | 400.1 | 469.2 |
| context_100 | 126.4 | 172.1 | 439.6 | 493.3 |

额外耗时包含分词、短上下文准备对应的SQL读取、CPU/GPU传输、CUDA推理、取回分数与现有输出折叠；GPU前后同步。总耗时为本次编码+FAISS+metadata基线和对应额外计算之和，不含磁盘写实验日志、模型/索引冷加载或Web预览。没有借Top100缓存分数伪装Top20/50耗时。

## 生产判断

32例上预先选出的方案：**window_20**。额外20例不退化：False；总P95≤2秒：True。

本轮不建议上线reranker；保留当前Semantic。Top20 window-only在32例和延迟上通过，但额外20例Top1从95%降至85%，收益没有稳定复现。

样本是冻结开发验证集，仍不是独立听审的真实二创业务准确率；不能仅依赖小样本承诺可靠找回原视频。没有继续寻找第二个模型或调整上下文/权重。

## 保护与产物

受保护文件集合、大小、mtime未变：True；GT SHA未变：True。FAISS/metadata额外SHA证据见index_hash_verification.json。
3项分词/上下文边界测试通过；52例基线window_id与分数逐条复现历史结果。6种组合共17,680个候选句对，逐项核对全部来自相应TopK；实际最长输入236tokens，无query/原window截断。
正式speech、DINO、CLIP、原字幕数据库、现有查询与Web均未修改。只新增本实验目录。results.json保留候选与所有logit、逐例指标、性能及2×2否定诊断；results.csv为全52例对比；errors.csv列出错误/退化；candidate_availability.json为候选上限。
