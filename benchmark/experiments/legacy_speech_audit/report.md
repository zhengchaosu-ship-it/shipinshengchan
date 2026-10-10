# 原有话术搜索只读审计与小型测试

日期：2026-09-28。结论：现有字幕数据与关键词搜索可直接复用，无需全库重新转写，也无需新建 speech_index。旧功能是连续字面子串搜索，不能当作错字容错或语义话术搜索。尚未接入寻帧，也不声明全库时间定位已验收。

## 1. 数据与覆盖

| 数据库 | videos 行数 | 有字幕文件 | subtitles 行数 | 正式 asset 覆盖 |
|---|---:|---:|---:|---:|
| video_index_fixed.db（当前默认主库） | 360 | 359 | 1,062,422 | 318/319 |
| video_index.db（仅只读对照） | 285 | 284 | 834,063 | 244/319 |

主库所有360条视频记录均可按规范化完整路径映射到已由SHA-256确认的asset_files，再取得正式asset_id及主文件路径。359个有字幕文件归并成318个asset，覆盖率99.69%。所有旧路径及映射后的主文件路径均存在。数量代表至少有一段转写，不代表每秒语音都转写完整。

唯一无字幕：video_id=218，asset_id=AST-077629B2B73C06B423BA，文件 未获取202606261625.ts，实际媒体头时长约0.0477秒。无需因此转写506小时。

旧库285个video_id及路径均与主库对应项一致；逐video按(start,end,text)序列计算SHA-256，两库共有视频的字幕内容全部一致（包括无字幕项）。主库多228,359条字幕、74个有转写逻辑asset。没有需要从旧库补入主库的独有字幕。

## 2. 表结构与字段

```sql
videos(id INTEGER PRIMARY KEY AUTOINCREMENT, file_path TEXT UNIQUE,
       file_name TEXT, duration REAL DEFAULT 0,
       processed_at TEXT DEFAULT CURRENT_TIMESTAMP);
subtitles(id INTEGER PRIMARY KEY AUTOINCREMENT, video_id INTEGER,
          start REAL, end REAL, text TEXT,
          FOREIGN KEY(video_id) REFERENCES videos(id));
```

- segment_id可使用subtitles.id；start_time/end_time对应原列start/end，禁止误写列名。
- file_path/file_name通过videos.id连接取得，字幕表本身不重复存路径。
- 没有asset_id、normalized_text、独立original_text或word timestamps列。text是现有存储文本；部分转写脚本曾繁转简，旧UI也有原地繁转简功能，不能声称保留了未经处理的Whisper原始输出。
- idx_sub_text是普通B-tree索引，idx_sub_video用于video_id；没有FTS虚拟表或文字embedding。frames只用于原图像功能，本次未扫描features。

## 3. 真正调用链

`video_search.py:519` 旧文字Tab → `search_by_keyword`（334行）→ `database.connect_database` → `config.json paths.database` → video_index_fixed.db → subtitles JOIN videos → `show_text_results`（407行）。OCR也会复用该函数（580行）。

```sql
SELECT v.file_path, v.file_name, s.start, s.end, s.text
FROM subtitles s JOIN videos v ON s.video_id = v.id
WHERE s.text LIKE ? ORDER BY v.file_path, s.start;
```

参数是 %keyword%。没有中文normalize、分词、fuzzy、同音字、语义、跨segment窗口、相关性分数或TopK限制。SQL计划为SCAN s → videos主键查找 → 临时排序。显示排名仅按路径/时间，不能解释成相关度排名。%和_仍具有LIKE通配符含义。旧UI能显示原文/时间/路径/缩略图和导出命令，不能据此声称已经复用了当前寻帧短预览组件。

## 4. 只读asset映射

映射结果：video_asset_mapping.json。键必须带database和legacy_video_id，以规范化完整路径找到asset_files，再沿既有SHA-256分组得到asset_id与正式primary_video_id/primary_file_path。此次ID恰好一致，但映射不以这个巧合为依据。

数据库主键没有重复video_id，也没有孤立subtitle.video_id。41个asset各有两个已转写物理文件：应归到同一asset，保留原字幕来源与segment_id，不要把两个版本的转写串成一条时间线。例如旧video_id=33与64都映射AST-E9E8054E49535431495A，主文件video_id=64。

另有同video_id下完全相同(start,end,text)重复行127条，分布：{122: 29, 124: 98}；3次插入顺序时间回退发生于120、122、124，均从尾部重新回到0秒，疑似追加第二轮转写，未删改。

## 5. 时间轴核查

- add_new_videos.py:134–138、batch_transcribe.py:182–200、full_process_and_shutdown.py:166–170、batch_transcribe_missing.py:40–44直接保存seg.start/seg.end；抽帧的frame_number/FPS另在frames逻辑中，两者未混算。
- 1,062,422条字幕无负时间、无end<start/非法时间、无零时长；有2条空文本。
- 初始探索与DINO decoded_duration_seconds比较得到8,687条超时，但该字段在未修复asset中仍可能是旧frame_count/FPS，不能当真实播放时长。已改用formal declared_duration_seconds（容器或真实PTS修复时长）复核；最终筛查为44个asset、1,060条end超过时长2秒。这个比较仅用于标记待核对，并非认定44个视频全部字幕不可用。
- 8个文件只读PyAV/FFmpeg媒体头抽查：音视频起点并不总一致，例如video_id129音频比视频晚0.97秒；video_id64音轨时长也比画轨长。
- 当前faster_whisper/audio.py:95会忽略音频frame PTS后按采样序列处理；转写时间是音频样本轴，不经过视频FPS，但遇音频PTS跳变/损坏跳帧仍不能保证与播放器时间轴完全相同。数据库未保存历史运行版本或解码日志，不能断言每条旧记录所用版本。
- 不重算/缩放/钳制任何时间。3个成功样例命中点均可进行短距离音频和视频seek；仅证明该位置可解码，没有逐句听审，不能报口播对齐误差或保证全库预览准确。

| video_id | 字幕最晚end(s) | formal参考时长(s) | 最大超时(s) | 超时行数 |
|---|---:|---:|---:|---:|
| 4 | 5501.220 | 5097.202 | 404.018 | 221 |
| 7 | 12117.960 | 11842.099 | 275.861 | 230 |
| 292 | 14276.860 | 14001.477 | 275.383 | 202 |
| 333 | 2049.800 | 1786.756 | 263.044 | 129 |
| 215 | 352.300 | 182.847 | 169.453 | 98 |
| 336 | 351.580 | 313.327 | 38.253 | 14 |
| 25 | 7103.920 | 7071.835 | 32.085 | 16 |
| 326 | 6627.000 | 6603.306 | 23.694 | 8 |
| 219 | 499.940 | 478.334 | 21.606 | 11 |
| 189 | 1822.100 | 1801.094 | 21.006 | 1 |

完整44个asset及段ID见timeline.json；最突出4、7、292、333、215应优先做局部口播/播放时间对照，不能套用DINO FPS修复比例。

## 6. 实际原函数测试

直接从video_search.py AST提取原search_by_keyword函数执行，函数体未更改；沿用database.py主库只读连接。没有导入Streamlit整页，未加载/调用Whisper、DINO或CLIP。选3句真实存储字幕，每句测试5种输入；另测用户示例与跨segment拼接，共17项。改写为测试输入，不冒充人工听审真值。

### 原句与实际返回

| segment_id | video_id | 文件名 | 时间(s) | 匹配原文 | 排名 |
|---|---:|---|---|---|---:|
| 93981 | 24 | 妙手陶老师本人_3xr7zzgq96gpawe_2026-06-25_140423.ts | 311.20–317.20 | 但是它没考虑到这个时候压迫到这块的肌肉 | 1 |
| 467034 | 129 | 2026年03月14日16时14分34秒.ts | 3747.28–3753.28 | 这是两边肌肉受力不平衡引起的 | 1 |
| 758233 | 262 | 妙手陶老师本人_3xr7zzgq96gpawe_2026-07-13_140307.ts | 2368.75–2371.75 | 我跟你说 就一个腰疼陶老师有十几种解访 | 1 |

### 全部输入结果

| 类型 | 搜索文字 | 返回数 | 目标segment排名 | 中位耗时(ms) |
|---|---|---:|---:|---:|
| A_exact | 但是它没考虑到这个时候压迫到这块的肌肉 | 1 | 1 | 90.41 |
| B_trim | 它没考虑到这个时候压迫到这块的肌肉 | 1 | 1 | 90.31 |
| B_internal_delete | 但是它没考虑到压迫到这块的肌肉 | 0 | 未命中/无GT | 90.15 |
| C_typo | 但是它没考虑到这个时候压迫到这块的肌内 | 0 | 未命中/无GT | 90.11 |
| D_paraphrase | 他没有考虑到这时候肌肉受到了压迫 | 0 | 未命中/无GT | 91.06 |
| A_exact | 这是两边肌肉受力不平衡引起的 | 1 | 1 | 96.03 |
| B_trim | 两边肌肉受力不平衡 | 1 | 1 | 90.35 |
| B_internal_delete | 这是两边受力不平衡引起的 | 0 | 未命中/无GT | 96.85 |
| C_typo | 这是两边肌肉受力不平横引起的 | 0 | 未命中/无GT | 96.04 |
| D_paraphrase | 这是左右两侧肌肉用力不均造成的 | 0 | 未命中/无GT | 96.45 |
| A_exact | 我跟你说 就一个腰疼陶老师有十几种解访 | 1 | 1 | 95.01 |
| B_trim | 就一个腰疼陶老师有十几种解访 | 1 | 1 | 93.65 |
| B_internal_delete | 就一个腰疼有十几种解访 | 0 | 未命中/无GT | 94.05 |
| C_typo | 我跟你说 就一个腰疼陶老师有十几种解法 | 0 | 未命中/无GT | 94.85 |
| D_paraphrase | 陶老师治疗腰痛有十多种方法 | 0 | 未命中/无GT | 90.36 |
| user_example_no_GT | 腰疼不一定是腰的问题 | 0 | 未命中/无GT | 89.89 |
| cross_segment | 那只不见有这个腰疼 今天陶老师又教一个新招了我跟你说 就一个腰疼陶老师有十几种解访 | 0 | 未命中/无GT | 91.97 |

原句3/3和保留连续子串的删头尾3/3均Rank1；句中删字0/3、错字/识别字替换0/3、同义改写0/3；跨段1例未命中。用户示例未命中，没有该句GT，不能据此断言素材没说过。完整返回、asset映射、原文与各次计时在search_tests.json。
47次有限查询含函数连接/SQL/组装：median 93.58ms，经验P95 96.50ms（排序取较低整位）；每个核心输入3次。不是新检索算法准确率benchmark。

## 7. 接入判断与缺口

可以复用现有主库和函数接入独立“话术关键词搜索”，只需adapter补video_id/segment_id、asset映射及现有预览格式，不需要重做语音转写或另造数据库。本次遵照要求仅审计，未接Web。

若目标是“二创字幕与原话不完全相同也能找到”，当前不能直接满足。最大能力缺口是连续LIKE没有错字/同义表达/跨段容错；最大定位缺口是部分旧音频时间轴与播放器时长不一致及3个视频重复转写。全库无条件生产验收尚不成立。建议下一步先复用现有文本做最小适配并对异常素材局部核对；这属于后续任务，本次未实施。

## 8. 保护与产物

生产代码修改0个；未新建speech_index、未调用转写或模型、未接Web。1269个既有受保护文件大小和mtime_ns前后核对：全部一致。这是轻量文件状态校验，不是数十GB数据库逐字节哈希。DINO两库、CLIP正式库、原数据库和Web源码/配置均未写入。

本次仅新增benchmark/experiments/legacy_speech_audit内审计证据：report.md、summary.json、audit.json、video_asset_mapping.json、timeline.json、search_tests.json、seek_checks.json、protected_before.json。
