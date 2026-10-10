# CLIP正式全素材索引验收

结论：**READY（构建完整性与查询功能）**。独立输出 `clip_index/formal_v1`，尚未接入寻帧Web。

## 协议和数量

仅使用只读DINO `formal_v1_repaired` 的已有JPEG，不读取/解码原视频。固定 `openai/clip-vit-base-patch32` revision `3d74acf9a28c67741b2f4f2ea7635f0aaf6f0268`，512维FP32/L2，IndexFlatIP；每asset按timestamp每5秒分桶选首帧。

计划和最终均为319个asset、362,752帧。manifest、build_plan、319个embedding shard、progress、sessions、clip.faiss、metadata、failures、assembly、report均已生成。

embedding = metadata = FAISS ntotal = **362,752**。逐行核对frame_id、asset_id、video_id、timestamp、frame_number、source_index_id、路径、plan和FAISS向量，差异0；重复frame_id、负/无效时间、缺失路径、JPEG/编码失败、asset失败全部0。所有向量有限且归一化，向量比对容差1e-6、单位长度容差1e-5。

两个DINO正式目录、repaired验收目录及Web目录共957个文件，构建前后文件集合、大小、mtime_ns一致；源report另核对SHA-256。未对全部大型shard计算全文件哈希。源SQLite始终mode=ro/query_only；未改图片排序、candidate_dedup、Web配置和ORB实验。

## 性能与断点恢复

| 指标 | 实测 |
|---|---:|
| 建库墙钟时间（初次manifest至组装完成，含中断恢复） | 1,894.481秒，31分34.5秒 |
| 两次编码会话活动时间合计 | 1,720.079秒 |
| CUDA模型前向事件耗时 | 598.995秒 |
| CUDA allocated显存峰值 | 712,590,336字节，679.6MiB |
| FAISS | 742,916,141字节，708.50MiB |
| metadata | 69,312,512字节，66.10MiB |
| CPU暖查询median | 47.4145ms |
| CPU暖查询P95 | 52.8427ms |

GPU事件计时不含JPEG读取、CPU预处理、数据库提交和组装；allocated峰值不代表整卡所有进程占用。查询使用现有search_text默认CPU，每条描述重复3次，共15次，包含文本编码、FAISS与Top20 metadata读取；不含冷加载。小样本功能测量，不是负载benchmark。

首次会话在217,476帧提交后遇到Windows进度文件替换短暂拒绝访问，保留全部断点退出。仅为原子JSON写入增加PermissionError重试，使用相同模型/采样/batch=32续跑；跳过210个已完成asset，其余从已提交plan_id继续。没有从零重建，没有OOM，没有降低batch。8项合成测试通过，随后新增Windows占用重试测试单独通过；共9项覆盖坏图隔离、单asset读取失败、批次恢复、降低batch续跑、目录保护和进度文件重试。

## 五条中文查询和画面抽查

五条均正常返回Top20；100项结果及15次计时见query_smoke.json，逐项检查asset_id、video_id、timestamp、路径和similarity。人工查看每条Top3共15张，见query_top3_contact_sheet.jpg。

| 描述 | Top3观察 |
|---|---|
| 患者趴着接受治疗 | 躺卧接受手法操作，但靠前含侧卧，未严格满足“趴着” |
| 按摩腰部 | 腰背部手法操作，主题基本相关 |
| 肩颈治疗 | 坐姿肩颈附近操作，主题基本相关 |
| 患者坐着，老师站在旁边 | 一人坐着、另一人站旁边；角色关系不能仅凭画面确认；Top3同一片段 |
| 老师给患者按摩背部 | 手法操作场景，Top1偏肩颈，后续含俯身姿态；具体部位仍有误差 |

功能跑通**不等于五条语义均准确命中**，这不是准确率benchmark。继续使用既有受控中文转英文，未知中文及否定句明确拒绝；未更换模型、调参或加入文字去重。

已具备后续单独接入Web的接口与索引条件，但本轮未接入或上线正式文字搜索。任务在此停止。
