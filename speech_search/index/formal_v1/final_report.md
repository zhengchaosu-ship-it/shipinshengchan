# 话术搜索全库语义formal_v1验收

完整性状态：**READY**。全库候选扩展后出现GT素材/时间Top10丢失或Top1明显下降；索引可查询，但不建议直接接入Web作为已验收能力。

## 实际产物

- 318个有字幕asset，3,099,048个向量；embedding=metadata=FAISS ntotal，window_id唯一。
- 1/2/3段窗口：{'1': 1055692, '2': 1031878, '3': 1011478}。缺字幕的约0.048秒asset没有伪造向量。
- FAISS：6,346,850,349 bytes（5.911GiB）；metadata：1,169,973,248 bytes（1115.8MiB）。
- 使用IndexFlatIP，不压缩、不与DINO/CLIP混合。vectors.f32保存512维FP32原向量；metadata独立保存全部窗口字段及主路径，原字幕ID可经既有segment_sources/window_sources追溯所有来源。
- BGE-small-zh-v1.5 revision 7999e1d3359715c523056ef9478215996d62a620，直接复用pilot Encoder：同tokenizer、CLS、L2、256 token上限、查询指令和FP32。16个已编码pilot样本数值与正式结果完全一致。
- 失败0；原44个asset/1,060条字幕异常原值保留，扩展为3,147个warning窗口，没有修时间或重新转写。

## 断点与严格验收

- 前2批共128向量停止并重启；原批次提交记录和向量SHA前后相同，续跑复用。先fsync向量，再SQLite FULL提交；未提交batch可重算，已提交batch跳过。
- 单条文本ValueError/编码格式异常递归隔离写failures，系统性CUDA故障停止保留checkpoint；合成故障测试通过。
- 318个asset集合、路径、start非负/start<=end、window_size、ID唯一、字段完整全部检查。全部metadata与原窗口逐行对比，全部FAISS向量与磁盘向量逐行比对、有限数/L2检查；32条自查询检查。
- 校验耗时71.3s；报告errors=[]。受保护文件集合/大小/mtime一致：True（轻量状态校验，不是生产全库逐字节hash）。
- 组装报告恢复标记：True。构建期间发现组装计时字段SQL取值问题，已在向量/FAISS原子发布后仅补写报告，没有重新编码任何已完成向量。
- 13项测试通过，包括坏文本隔离、系统故障保留断点、正式与pilot复用同一个Encoder，以及既有话术功能测试。

## 固定32例全库复测

沿用原32例与GT，不调参数。原32例为从旧转写构造的开发验证，并非独立听审的真实二创holdout。原pilot候选只有8个asset；本次318个。未运行或调整融合。

| 层 | 素材Top1 | Top5 | Top10 | 正确时间附近Top10 | median ms | P95 ms |
|---|---:|---:|---:|---:|---:|---:|
| exact | 16/32 (50.0%) | 16/32 (50.0%) | 16/32 (50.0%) | 16/32 (50.0%) | 13.1 | 33.8 |
| fuzzy | 22/32 (68.8%) | 23/32 (71.9%) | 24/32 (75.0%) | 24/32 (75.0%) | 554.2 | 2042.5 |
| semantic | 25/32 (78.1%) | 29/32 (90.6%) | 30/32 (93.8%) | 30/32 (93.8%) | 299.8 | 309.9 |

相对pilot Semantic：Top1变化-6例，素材Top10丢失['C_semantic20', 'C_semantic21']；时间附近Top10丢失['C_semantic21']。

时间附近定义保持GT起点落在结果窗口内±2秒；素材命中不代表口播时点正确。GT使用旧Whisper时间，不能代表真实听审时间误差。字幕里同句话可出现在多个视频/多个位置；本次严格沿用单一GT，不为了提高分数事后补标其它结果。

## 已保存结果的退化核对（未再调参）

- 原32例Semantic Top1从31/32降至25/32，Top10从32/32降至30/32。原句、删字/错字、跨段各8例的素材Top10仍为8/8；同义改写为6/8。
- C_semantic20：query“这个部位完全没有疼痛感”，GT“但是一点都不疼这个地方”掉出Top10，Top1却是“一個部位疼”（0.7289）。这暴露了否定含义区分问题，不能把语义相关视为同一句话。
- C_semantic21：query“我的工作就是做这个”，GT“我就是干这个活的”掉出Top10；其它asset的“我做的工作 就是这个”（0.7742）等同义句领先。单一GT的素材命中失败仍照实计分，没有事后把其它视频改标为正确。
- C_semantic19的“身体各个部位都是互相连通的”由rank1到6；其它素材“人身体所有的东西都相通”排前。B_fuzzy16也遇到另一asset几乎同文且相近时点的候选；仅凭字幕不能确定两个asset是否为不同编码的同一直播，不修改资产映射。
- 新20例中NEW13“你的腰有没有酸痛的感觉”的指定GT未进Top10，前排为其它asset的腰酸/腰疼短句。其余19例都在Top1；这不能抵消固定32例的退化。
- 观察指向全库相似话术竞争，以及通用短句、否定句区分不足；不是向量丢失或metadata错位。本轮没有修改query、GT、模型、候选数、折叠或融合参数。

## 额外20个asset的真实字幕

原句、删字、错字、同义改写、跨段各4例，20个asset均不在原8个pilot asset内。评测前冻结，不选结果后修改query或模型。

| 层 | 素材Top1/5/10 | 附近Top10 |
|---|---|---:|
| exact | 8/20 · 8/20 · 8/20 | 8/20 |
| fuzzy | 13/20 · 15/20 · 15/20 | 15/20 |
| semantic | 19/20 · 19/20 · 19/20 | 19/20 |

## 逐例semantic排名

| 集合/案例 | query | 素材rank | 时间附近rank |
|---|---|---:|---:|
| original32/A_exact01 | 但是它没考虑到这个时候压迫到这块的肌肉 | 1 | 1 |
| original32/A_exact02 | 这是两边肌肉受力不平衡引起的 | 1 | 1 |
| original32/A_exact03 | 我跟你说 就一个腰疼陶老师有十几种解访 | 1 | 1 |
| original32/A_exact04 | 我们所有的骨头的骨店都是靠肌肉来挑战的。 | 1 | 1 |
| original32/A_exact05 | 这个骨头跟肌肉不在一个条线上 | 1 | 1 |
| original32/A_exact06 | 60年的腰疼,那到底怎么疼呢? | 1 | 1 |
| original32/A_exact07 | 他这个肌肉紧张的卡压神经 | 1 | 1 |
| original32/A_exact08 | 去他们家有个亲戚做了个按摩椅 | 1 | 1 |
| original32/B_fuzzy09 | 吹风机吹吹晚上再吹吹 | 1 | 1 |
| original32/B_fuzzy10 | 还是这个脚不是一个长一个段 | 2 | 2 |
| original32/B_fuzzy11 | 刮出包要不要处理继续刮就好了 | 1 | 1 |
| original32/B_fuzzy12 | 这反正走路不安走这边都软的 | 1 | 1 |
| original32/B_fuzzy13 | 我这个调整一下这块的肌裙 | 1 | 1 |
| original32/B_fuzzy14 | 右边要严重左边也有 | 1 | 1 |
| original32/B_fuzzy15 | 那你就按两百次一阻 | 1 | 1 |
| original32/B_fuzzy16 | 但是我告诉她做没效果 | 2 | 2 |
| original32/C_semantic17 | 你奶奶对你太上心了 | 1 | 1 |
| original32/C_semantic18 | 对面那一侧发生萎缩 | 1 | 1 |
| original32/C_semantic19 | 身体各个部位都是互相连通的 | 6 | 6 |
| original32/C_semantic20 | 这个部位完全没有疼痛感 | Top10外 | Top10外 |
| original32/C_semantic21 | 我的工作就是做这个 | Top10外 | Top10外 |
| original32/C_semantic22 | 老人自己在家也能操作 | 3 | 3 |
| original32/C_semantic23 | 按到三百下的时候 | 2 | 3 |
| original32/C_semantic24 | 她整只手都发麻了 | 1 | 1 |
| original32/D_cross25 | 来 就这个点 这个点看到吧 自己摸一下 这个对 反手 反手群摸 | 1 | 1 |
| original32/D_cross26 | 这边住完了就住这边 这是两边肌肉受力不平衡引起的 | 1 | 1 |
| original32/D_cross27 | 每个解访它不同 你给我个手也行 给个脚也行 给个头也行 给个偶都也行 | 1 | 1 |
| original32/D_cross28 | 这反正走路不安走,这边都是软的。 来,现在再走走。 | 1 | 1 |
| original32/D_cross29 | 我这个调整一下这块的肌群 就把它抵押下去 | 1 | 1 |
| original32/D_cross30 | 今天教大家一个新招。 这个招呢,非常简单。 | 1 | 1 |
| original32/D_cross31 | 那你就按两百次一组 不就行的吗 | 1 | 1 |
| original32/D_cross32 | 按摩椅完以后的时候感觉舒服 过了没多久的话 | 1 | 1 |
| additional20/NEW01 | 我看他们按摩进去,我这个全是肉。 | 1 | 1 |
| additional20/NEW02 | 按摩 跑到我刚才教你的方法去做 | 1 | 1 |
| additional20/NEW03 | 我也是听了中一课跟她按摩,现在倒是好。 | 1 | 1 |
| additional20/NEW04 | 我叫你 我刚才给你做了按摩吗 | 1 | 1 |
| additional20/NEW05 | 不管头疼腰疼腿疼肩膀疼蹲不下起不来的 | 1 | 1 |
| additional20/NEW06 | 你那个是按摩力气活 | 1 | 1 |
| additional20/NEW07 | 这个飞骨上面的痛点扭开来肌肉八在上面 | 1 | 1 |
| additional20/NEW08 | 一边肌肉发达一边肌肉尾说不行 | 1 | 1 |
| additional20/NEW09 | 就在这个中间那个风里面腰腾了包括流伤了 | 1 | 1 |
| additional20/NEW10 | 你起来才知道你腰腾不疼了 | 1 | 1 |
| additional20/NEW11 | 腰痛直不起来看我的视屏也不用 | 1 | 1 |
| additional20/NEW12 | 这边这一块这两块肌肉一弄就胀痛了新给他上脸六要不然我弄他他会疼呢 | 1 | 1 |
| additional20/NEW13 | 你的腰有没有酸痛的感觉 | Top10外 | Top10外 |
| additional20/NEW14 | 我没说按摩一定很舒服 | 1 | 1 |
| additional20/NEW15 | 这里皮肤肌肉以及深处都会疼 | 1 | 1 |
| additional20/NEW16 | 你觉得我是在做推拿按摩吗 | 1 | 1 |
| additional20/NEW17 | 它这个痛风,我也是挺自己的,就是有没有运到好的妙症,让它自己按摩 对,这个风又看到到什么情况下,就像弹高也是一样的 | 1 | 1 |
| additional20/NEW18 | 我有躺在那边,每天都能按摩,早上一次,晚上一次,相关是课业,常常相关是课业,小堂门哪? 对,小堂那是原来多少啊? | 1 | 1 |
| additional20/NEW19 | 没听懂什么意思就是能给你按摩 对 给我按摩 | 1 | 1 |
| additional20/NEW20 | 還有尖夾骨鳳,又求按摩,又求推拉 又是砸什麼增的,多不多? | 1 | 1 |

## 性能与范围

- 建库自然耗时16.53分钟（含真实停止/重启间隔）；活跃构建累计16.02分钟，验收/查询评估另计。
- CUDA Encoder调用累计573.99s；CUDA事件包围encode累计569.71s。前者包含分词/CPU-GPU拷贝，事件包围段也包含排队/空闲，不冒称纯kernel计时。
- 峰值构建进程RAM 13.343GiB；Torch分配VRAM 450.6MiB，保留池1408.0MiB，不是整机或Web占用。RAM由外部进程PeakWorkingSet监控补齐早期计数器兼容性问题。
- CPU暖语义查询52例 median 297.1ms / P95 309.4ms；模型首次加载3.62s；索引加载2.21s。不含Web或预览。

## 使用与接入判断

全库候选扩展后出现GT素材/时间Top10丢失或Top1明显下降；索引可查询，但不建议直接接入Web作为已验收能力。

CLI：`.\.venv-cuda-test\Scripts\python.exe -X utf8 -B speech_search/formal_query.py "话术" --mode semantic`。Exact/Fuzzy独立可用，原pilot query.py保持原样；正式入口不提供hybrid。
未修改Web、DINO/CLIP、图片候选去重、ORB、原字幕；原验证数据与模型流程不变。完整规则及断点用法见speech_search/FORMAL_README.md。完成本阶段后停止，没有进行Web接入。
