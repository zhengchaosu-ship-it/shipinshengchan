# formal_v1 验收报告：NOT_READY

生成时间：2026-09-27T08:14:51+00:00

正式索引目录（只读）：`D:\video_search_tool\dino_index\formal_v1`

逻辑资产库（只读）：`D:\video_search_tool\asset_inventory\results\20260927_assets\logical_assets.db`

## 检查结果

| 检查 | 结果 | 说明 |
|---|---|---|
| `build_report` | 失败 | report记录了130个解码异常 |
| `required_files` | 通过 | 必要文件均存在且非0字节 |
| `logical_assets` | 通过 | 逻辑资产库可用素材 319 / 预期 319 |
| `metadata_integrity` | 通过 | metadata frames=1808629, frame_metadata=1808629 |
| `asset_id_coverage` | 通过 | 已索引 319 / 应有 319 个asset |
| `video_paths` | 通过 | 检查319个视频路径；缺失0个 |
| `timestamps` | 失败 | 异常timestamp 27793 条 |
| `shards_and_embeddings` | 通过 | embedding=1808629, shard frames=1808629, metadata=1808629 |
| `report_counts` | 通过 | report videos=319, frames=1808629; assets=319, metadata=1808629 |
| `faiss_cardinality` | 跳过 | FAISS加载前检查未全部通过，安全跳过 |
| `query_smoke_test` | 跳过 | 完整性检查未通过，安全跳过 |

## asset_id 覆盖

- 应有 asset：319
- 已索引 asset：319
- 缺失 asset_id：{"total": 0, "items": [], "truncated": 0}
- 多余 asset_id：{"total": 0, "items": [], "truncated": 0}

## 失败与异常


### build_report / reported_anomalies

```json
{
  "total": 130,
  "items": [
    {
      "fps": 62.02619047619048,
      "step": 62,
      "declared_frames": 276742.0,
      "asset_id": "AST-00052AC3DB58040B3BC9",
      "video_id": 273,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\1-3月陶抖音直播素材\\一月\\1.30\\妙手陶老师_95765895385_2026-01-30_210601.ts",
      "decoded_frames": 267029,
      "last_sample_frame": 266972,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 4305.100763886223,
      "worker_seconds": 636.0596693999978,
      "complete": true,
      "embedded_frames": 4307
    },
    {
      "fps": 20.0,
      "step": 20,
      "declared_frames": 45437.0,
      "asset_id": "AST-001BD9F0ADD703165909",
      "video_id": 320,
      "file_path": "D:\\素材\\9月(1)\\妙手陶老师本人_3xr7zzgq96gpawe_2026-09-05_164105.ts",
      "decoded_frames": 45347,
      "last_sample_frame": 45340,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 2267.35,
      "worker_seconds": 79.78543589999026,
      "complete": true,
      "embedded_frames": 2268
    },
    {
      "fps": 20.0,
      "step": 20,
      "declared_frames": 240922.0,
      "asset_id": "AST-00A19A032B18F1045AF7",
      "video_id": 332,
      "file_path": "D:\\素材\\9月(1)\\妙手陶老师本人_3xr7zzgq96gpawe_2026-09-13_135858.ts",
      "decoded_frames": 237787,
      "last_sample_frame": 237780,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 11889.35,
      "worker_seconds": 506.61473680000927,
      "complete": true,
      "embedded_frames": 11890
    },
    {
      "fps": 30.0,
      "step": 30,
      "declared_frames": 185674.0,
      "asset_id": "AST-012A38D08459F67ADF1E",
      "video_id": 92,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\5.6月\\2026.5月\\5.8\\2026年05月08日17时02分36秒.ts",
      "decoded_frames": 184239,
      "last_sample_frame": 184230,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 6141.3,
      "worker_seconds": 235.1869880000013,
      "complete": true,
      "embedded_frames": 6142
    },
    {
      "fps": 20.0,
      "step": 20,
      "declared_frames": 49636.0,
      "asset_id": "AST-0216499049DA07E9A061",
      "video_id": 110,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\妙手陶老师本人_3xr7zzgq96gpawe_2026-09-08_141044.ts",
      "decoded_frames": 49311,
      "last_sample_frame": 49300,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 2465.55,
      "worker_seconds": 107.24324609999894,
      "complete": true,
      "embedded_frames": 2466
    },
    {
      "fps": 20.0,
      "step": 20,
      "declared_frames": 154898.0,
      "asset_id": "AST-07CDB6A38085143C78ED",
      "video_id": 128,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\陶老师3-4月直播\\2026年03月13日15时20分48秒.ts",
      "decoded_frames": 154821,
      "last_sample_frame": 154820,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 7741.05,
      "worker_seconds": 291.00458510000317,
      "complete": true,
      "embedded_frames": 7742
    },
    {
      "fps": 30.0,
      "step": 30,
      "declared_frames": 228181.0,
      "asset_id": "AST-090DE4261B82B53EF90A",
      "video_id": 83,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\5.6月\\2026.5月\\5.29\\2026年05月29日15时56分37秒.ts",
      "decoded_frames": 227561,
      "last_sample_frame": 227550,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 7585.366666666667,
      "worker_seconds": 263.3725487999909,
      "complete": true,
      "embedded_frames": 7586
    },
    {
      "fps": 20.0,
      "step": 20,
      "declared_frames": 180267.0,
      "asset_id": "AST-0B09B9B67A94327F8C92",
      "video_id": 319,
      "file_path": "D:\\素材\\9月(1)\\妙手陶老师本人_3xr7zzgq96gpawe_2026-09-05_141001.ts",
      "decoded_frames": 180232,
      "last_sample_frame": 180220,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 9011.6,
      "worker_seconds": 407.22759219999716,
      "complete": true,
      "embedded_frames": 9012
    },
    {
      "fps": 20.0,
      "step": 20,
      "declared_frames": 132066.0,
      "asset_id": "AST-0CF047F28BBF63C294DE",
      "video_id": 326,
      "file_path": "D:\\素材\\9月(1)\\妙手陶老师本人_3xr7zzgq96gpawe_2026-09-10_200334.ts",
      "decoded_frames": 122665,
      "last_sample_frame": 122660,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 6133.25,
      "worker_seconds": 201.8786681999918,
      "complete": true,
      "embedded_frames": 6134
    },
    {
      "fps": 20.0,
      "step": 20,
      "declared_frames": 189097.0,
      "asset_id": "AST-0D254DBC063085B92534",
      "video_id": 183,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\陶老师3-4月直播\\2026年06月14日16时39分20秒.ts",
      "decoded_frames": 189058,
      "last_sample_frame": 189040,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 9452.9,
      "worker_seconds": 402.6823574000009,
      "complete": true,
      "embedded_frames": 9453
    },
    {
      "fps": 20.0,
      "step": 20,
      "declared_frames": 177354.0,
      "asset_id": "AST-0D95452CFFEC7175FC8B",
      "video_id": 109,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\妙手陶老师本人_3xr7zzgq96gpawe_2026-09-07_145329.ts",
      "decoded_frames": 172782,
      "last_sample_frame": 172780,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 8639.1,
      "worker_seconds": 413.6666613999987,
      "complete": true,
      "embedded_frames": 8640
    },
    {
      "fps": 30.0,
      "step": 30,
      "declared_frames": 180197.0,
      "asset_id": "AST-0FA3B4F0DA663143D540",
      "video_id": 86,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\5.6月\\2026.5月\\5.4\\2026年05月04日15时55分13秒.ts",
      "decoded_frames": 180154,
      "last_sample_frame": 180150,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 6005.133333333333,
      "worker_seconds": 247.04970230000617,
      "complete": true,
      "embedded_frames": 6006
    },
    {
      "fps": 20.0,
      "step": 20,
      "declared_frames": 236840.0,
      "asset_id": "AST-100D0AE3F446F91C0735",
      "video_id": 7,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\妙手陶老师本人_3xr7zzgq96gpawe_2026-08-02_143642.ts",
      "decoded_frames": 146683,
      "last_sample_frame": 146680,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 7334.15,
      "worker_seconds": 321.6660412999918,
      "complete": true,
      "embedded_frames": 7335
    },
    {
      "fps": 29.97002997002997,
      "step": 29,
      "declared_frames": 164024.0,
      "asset_id": "AST-12D3AE1225F03BBE5941",
      "video_id": 72,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\5.6月\\2026.5月\\5.21\\2026年05月21日15时54分19秒.ts",
      "decoded_frames": 155634,
      "last_sample_frame": 155614,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 5192.9878,
      "worker_seconds": 202.66205319999426,
      "complete": true,
      "embedded_frames": 5367
    },
    {
      "fps": 30.0,
      "step": 30,
      "declared_frames": 137183.0,
      "asset_id": "AST-1383DBF0B7549771623B",
      "video_id": 78,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\5.6月\\2026.5月\\5.24\\2026年05月24日15时41分35秒.ts",
      "decoded_frames": 134549,
      "last_sample_frame": 134520,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 4484.966666666666,
      "worker_seconds": 592.574337500002,
      "complete": true,
      "embedded_frames": 4485
    },
    {
      "fps": 20.0,
      "step": 20,
      "declared_frames": 171904.0,
      "asset_id": "AST-17A1E6C13DF323B2614F",
      "video_id": 103,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\妙手陶老师本人_3xr7zzgq96gpawe_2026-08-28_141323.ts",
      "decoded_frames": 171863,
      "last_sample_frame": 171860,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 8593.15,
      "worker_seconds": 363.1347272999992,
      "complete": true,
      "embedded_frames": 8594
    },
    {
      "fps": 30.0,
      "step": 30,
      "declared_frames": 153997.0,
      "asset_id": "AST-1D48629B025DC5000F9B",
      "video_id": 69,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\5.6月\\2026.5月\\5.15\\2026年05月15日10时41分33秒.ts",
      "decoded_frames": 152851,
      "last_sample_frame": 152850,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 5095.033333333334,
      "worker_seconds": 662.8135413999989,
      "complete": true,
      "embedded_frames": 5096
    },
    {
      "fps": 30.0,
      "step": 30,
      "declared_frames": 245860.0,
      "asset_id": "AST-1E5C20355F834CB9E187",
      "video_id": 80,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\5.6月\\2026.5月\\5.26\\2026年05月26日15时54分20秒.ts",
      "decoded_frames": 245757,
      "last_sample_frame": 245730,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 8191.9,
      "worker_seconds": 311.925312700012,
      "complete": true,
      "embedded_frames": 8192
    },
    {
      "fps": 20.0,
      "step": 20,
      "declared_frames": 81767.0,
      "asset_id": "AST-1F448426C4F8C37D1DF6",
      "video_id": 154,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\陶老师3-4月直播\\2026年04月14日16时02分04秒.ts",
      "decoded_frames": 80558,
      "last_sample_frame": 80540,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 4027.9,
      "worker_seconds": 173.73443970001244,
      "complete": true,
      "embedded_frames": 4028
    },
    {
      "fps": 20.0,
      "step": 20,
      "declared_frames": 197145.0,
      "asset_id": "AST-1F73C79272197D1ED86E",
      "video_id": 185,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\陶老师3-4月直播\\2026年06月15日16时46分12秒.ts",
      "decoded_frames": 197105,
      "last_sample_frame": 197100,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 9855.25,
      "worker_seconds": 443.56863069999963,
      "complete": true,
      "embedded_frames": 9856
    },
    {
      "fps": 20.0,
      "step": 20,
      "declared_frames": 195200.0,
      "asset_id": "AST-276B1511ED0AB4EF3EE7",
      "video_id": 324,
      "file_path": "D:\\素材\\9月(1)\\妙手陶老师本人_3xr7zzgq96gpawe_2026-09-08_195604.ts",
      "decoded_frames": 186316,
      "last_sample_frame": 186300,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 9315.8,
      "worker_seconds": 342.74573090000194,
      "complete": true,
      "embedded_frames": 9316
    },
    {
      "fps": 20.0,
      "step": 20,
      "declared_frames": 269737.0,
      "asset_id": "AST-2843B90BF4C2B63B4B79",
      "video_id": 304,
      "file_path": "D:\\素材\\8月(1)\\妙手陶老师本人_3xr7zzgq96gpawe_2026-08-16_135255.ts",
      "decoded_frames": 269673,
      "last_sample_frame": 269660,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 13483.65,
      "worker_seconds": 598.8410262999969,
      "complete": true,
      "embedded_frames": 13484
    },
    {
      "fps": 30.0,
      "step": 30,
      "declared_frames": 229676.0,
      "asset_id": "AST-28A5FB0AA0CCF93C8F72",
      "video_id": 67,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\5.6月\\2026.5月\\5.12\\2026年05月12日16时51分37秒.ts",
      "decoded_frames": 228235,
      "last_sample_frame": 228210,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 7607.833333333333,
      "worker_seconds": 279.582849399987,
      "complete": true,
      "embedded_frames": 7608
    },
    {
      "fps": 30.0,
      "step": 30,
      "declared_frames": 300572.0,
      "asset_id": "AST-30BDD9631F51D4865F01",
      "video_id": 65,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\5.6月\\2026.5月\\5.10\\2026年05月10日18时07分31秒.ts",
      "decoded_frames": 300516,
      "last_sample_frame": 300510,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 10017.2,
      "worker_seconds": 344.86333960000775,
      "complete": true,
      "embedded_frames": 10018
    },
    {
      "fps": 20.0,
      "step": 20,
      "declared_frames": 100297.0,
      "asset_id": "AST-3289AB2EB7CCE20AD16B",
      "video_id": 158,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\陶老师3-4月直播\\2026年04月17日16时24分37秒.ts",
      "decoded_frames": 82385,
      "last_sample_frame": 82380,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 4119.25,
      "worker_seconds": 186.55939249999938,
      "complete": true,
      "embedded_frames": 4120
    },
    {
      "fps": 15.0,
      "step": 15,
      "declared_frames": 2743.0,
      "asset_id": "AST-34FB4F2795DD3C2E0EC3",
      "video_id": 215,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\陶老师3-4月直播\\未获取202606261443.ts",
      "decoded_frames": 2711,
      "last_sample_frame": 2700,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 180.73333333333332,
      "worker_seconds": 7.039695100000245,
      "complete": true,
      "embedded_frames": 181
    },
    {
      "fps": 20.0,
      "step": 20,
      "declared_frames": 5704.0,
      "asset_id": "AST-37FAA430A61733DC1CB3",
      "video_id": 159,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\陶老师3-4月直播\\2026年04月18日14时44分50秒.ts",
      "decoded_frames": 277,
      "last_sample_frame": 260,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 13.85,
      "worker_seconds": 0.8852926999970805,
      "complete": true,
      "embedded_frames": 14
    },
    {
      "fps": 30.0,
      "step": 30,
      "declared_frames": 188695.0,
      "asset_id": "AST-3A1A6DD798D745754101",
      "video_id": 88,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\5.6月\\2026.5月\\5.6\\2026年05月06日11时44分16秒.ts",
      "decoded_frames": 173294,
      "last_sample_frame": 173280,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 5776.466666666666,
      "worker_seconds": 798.1284266000002,
      "complete": true,
      "embedded_frames": 5777
    },
    {
      "fps": 30.0,
      "step": 30,
      "declared_frames": 152660.0,
      "asset_id": "AST-3AA62506F7066D37F251",
      "video_id": 90,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\5.6月\\2026.5月\\5.7\\2026年05月07日16时26分32秒.ts",
      "decoded_frames": 87816,
      "last_sample_frame": 87810,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 2927.2,
      "worker_seconds": 304.5466701999976,
      "complete": true,
      "embedded_frames": 2928
    },
    {
      "fps": 30.0,
      "step": 30,
      "declared_frames": 295945.0,
      "asset_id": "AST-3CE5069E3BB72C4BB790",
      "video_id": 18,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\5.6月\\2026(1).6月\\6.15\\2026年06月15日16时46分12秒.ts",
      "decoded_frames": 295588,
      "last_sample_frame": 295560,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 9852.933333333332,
      "worker_seconds": 375.6508581000089,
      "complete": true,
      "embedded_frames": 9853
    },
    {
      "fps": 30.0,
      "step": 30,
      "declared_frames": 215207.0,
      "asset_id": "AST-3E3986CF24E147F7409D",
      "video_id": 173,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\陶老师3-4月直播\\2026年06月01日16时02分31秒.ts",
      "decoded_frames": 214523,
      "last_sample_frame": 214500,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 7150.766666666666,
      "worker_seconds": 272.8856252999976,
      "complete": true,
      "embedded_frames": 7151
    },
    {
      "fps": 20.0,
      "step": 20,
      "declared_frames": 161408.0,
      "asset_id": "AST-403C5685A6A31B6468B4",
      "video_id": 112,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\妙手陶老师本人_3xr7zzgq96gpawe_2026-09-10_140837.ts",
      "decoded_frames": 159911,
      "last_sample_frame": 159900,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 7995.55,
      "worker_seconds": 391.71915550000267,
      "complete": true,
      "embedded_frames": 7996
    },
    {
      "fps": 20.0,
      "step": 20,
      "declared_frames": 93471.0,
      "asset_id": "AST-44630F6596D401E77353",
      "video_id": 143,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\陶老师3-4月直播\\2026年04月03日21时51分13秒.ts",
      "decoded_frames": 93440,
      "last_sample_frame": 93420,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 4672.0,
      "worker_seconds": 213.45793859999685,
      "complete": true,
      "embedded_frames": 4672
    },
    {
      "fps": 30.0,
      "step": 30,
      "declared_frames": 235898.0,
      "asset_id": "AST-45ACE6BF25B636A4A6BE",
      "video_id": 73,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\5.6月\\2026.5月\\5.22\\2026年05月22日11时27分00秒.ts",
      "decoded_frames": 234355,
      "last_sample_frame": 234330,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 7811.833333333333,
      "worker_seconds": 1192.2766701000073,
      "complete": true,
      "embedded_frames": 7812
    },
    {
      "fps": 20.0,
      "step": 20,
      "declared_frames": 13145.0,
      "asset_id": "AST-4A881C683CF4FEF78EBC",
      "video_id": 184,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\陶老师3-4月直播\\2026年06月14日16时50分46秒.ts",
      "decoded_frames": 13106,
      "last_sample_frame": 13100,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 655.3,
      "worker_seconds": 29.56909240000823,
      "complete": true,
      "embedded_frames": 656
    },
    {
      "fps": 20.0,
      "step": 20,
      "declared_frames": 33068.0,
      "asset_id": "AST-4C31A40171C7457DFCB0",
      "video_id": 144,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\陶老师3-4月直播\\2026年04月04日20时50分46秒.ts",
      "decoded_frames": 33034,
      "last_sample_frame": 33020,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 1651.7,
      "worker_seconds": 76.35520829999587,
      "complete": true,
      "embedded_frames": 1652
    },
    {
      "fps": 30.0,
      "step": 30,
      "declared_frames": 287708.0,
      "asset_id": "AST-4C9E94FAE499BB4C9DCA",
      "video_id": 68,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\5.6月\\2026.5月\\5.14\\2026年05月14日11时50分59秒.ts",
      "decoded_frames": 282733,
      "last_sample_frame": 282720,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 9424.433333333332,
      "worker_seconds": 1267.2860622000007,
      "complete": true,
      "embedded_frames": 9425
    },
    {
      "fps": 20.0,
      "step": 20,
      "declared_frames": 24375.0,
      "asset_id": "AST-4E08ACA20F2B6222AB55",
      "video_id": 342,
      "file_path": "D:\\素材\\9月(1)\\妙手陶老师本人_3xr7zzgq96gpawe_2026-09-14_143017.ts",
      "decoded_frames": 7867,
      "last_sample_frame": 7860,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 393.35,
      "worker_seconds": 19.475580199999968,
      "complete": true,
      "embedded_frames": 394
    },
    {
      "fps": 30.0,
      "step": 30,
      "declared_frames": 243925.0,
      "asset_id": "AST-51718E7F4237DEEFD9C1",
      "video_id": 94,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\5.6月\\2026.5月\\5.9\\2026年05月09日17时44分07秒.ts",
      "decoded_frames": 228104,
      "last_sample_frame": 228090,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 7603.466666666666,
      "worker_seconds": 1015.3298829999985,
      "complete": true,
      "embedded_frames": 7604
    },
    {
      "fps": 30.0,
      "step": 30,
      "declared_frames": 140138.0,
      "asset_id": "AST-524D3BCEAEC861ACBC47",
      "video_id": 174,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\陶老师3-4月直播\\2026年06月02日15时17分29秒.ts",
      "decoded_frames": 139183,
      "last_sample_frame": 139170,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 4639.433333333333,
      "worker_seconds": 183.07150369999,
      "complete": true,
      "embedded_frames": 4640
    },
    {
      "fps": 20.0,
      "step": 20,
      "declared_frames": 161371.0,
      "asset_id": "AST-5310E9E28FAE41B44238",
      "video_id": 325,
      "file_path": "D:\\素材\\9月(1)\\妙手陶老师本人_3xr7zzgq96gpawe_2026-09-10_140833.ts",
      "decoded_frames": 159874,
      "last_sample_frame": 159860,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 7993.7,
      "worker_seconds": 396.11675119999563,
      "complete": true,
      "embedded_frames": 7994
    },
    {
      "fps": 20.0,
      "step": 20,
      "declared_frames": 113368.0,
      "asset_id": "AST-54E8D75E58E383550F5D",
      "video_id": 157,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\陶老师3-4月直播\\2026年04月16日15时56分24秒.ts",
      "decoded_frames": 113331,
      "last_sample_frame": 113320,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 5666.55,
      "worker_seconds": 267.21709420000843,
      "complete": true,
      "embedded_frames": 5667
    },
    {
      "fps": 30.0,
      "step": 30,
      "declared_frames": 294377.0,
      "asset_id": "AST-583E40C4CD6A9ED71F9E",
      "video_id": 77,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\5.6月\\2026.5月\\5.24\\2026年05月24日12时24分03秒.ts",
      "decoded_frames": 294244,
      "last_sample_frame": 294240,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 9808.133333333333,
      "worker_seconds": 386.09653219999745,
      "complete": true,
      "embedded_frames": 9809
    },
    {
      "fps": 20.0,
      "step": 20,
      "declared_frames": 172405.0,
      "asset_id": "AST-59D584CFC6E424196B87",
      "video_id": 328,
      "file_path": "D:\\素材\\9月(1)\\妙手陶老师本人_3xr7zzgq96gpawe_2026-09-11_135840.ts",
      "decoded_frames": 159114,
      "last_sample_frame": 159100,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 7955.7,
      "worker_seconds": 354.26670529998955,
      "complete": true,
      "embedded_frames": 7956
    },
    {
      "fps": 20.0,
      "step": 20,
      "declared_frames": 138921.0,
      "asset_id": "AST-5A1E4C54345BCD9E608E",
      "video_id": 331,
      "file_path": "D:\\素材\\9月(1)\\妙手陶老师本人_3xr7zzgq96gpawe_2026-09-12_200923.ts",
      "decoded_frames": 133702,
      "last_sample_frame": 133700,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 6685.1,
      "worker_seconds": 296.824443000005,
      "complete": true,
      "embedded_frames": 6686
    },
    {
      "fps": 30.0,
      "step": 30,
      "declared_frames": 501404.0,
      "asset_id": "AST-5B6A0D0CB2E0D0ED61A5",
      "video_id": 177,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\陶老师3-4月直播\\2026年06月06日18时37分17秒.ts",
      "decoded_frames": 499230,
      "last_sample_frame": 499200,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 16641.0,
      "worker_seconds": 624.9446992000012,
      "complete": true,
      "embedded_frames": 16641
    },
    {
      "fps": 20.0,
      "step": 20,
      "declared_frames": 246124.0,
      "asset_id": "AST-5D3B73C50B0916D4FBDD",
      "video_id": 256,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\陶老师7月直播素材\\妙手陶老师本人_3xr7zzgq96gpawe_2026-07-06_141143.ts",
      "decoded_frames": 246094,
      "last_sample_frame": 246080,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 12304.7,
      "worker_seconds": 541.9024849000125,
      "complete": true,
      "embedded_frames": 12305
    },
    {
      "fps": 20.0,
      "step": 20,
      "declared_frames": 106444.0,
      "asset_id": "AST-5FC7798E65E4345BB140",
      "video_id": 131,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\陶老师3-4月直播\\2026年03月15日14时54分33秒.ts",
      "decoded_frames": 106275,
      "last_sample_frame": 106260,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 5313.75,
      "worker_seconds": 207.6090411000041,
      "complete": true,
      "embedded_frames": 5314
    },
    {
      "fps": 20.0,
      "step": 20,
      "declared_frames": 152359.0,
      "asset_id": "AST-632F707047438C21EAB4",
      "video_id": 306,
      "file_path": "D:\\素材\\8月(1)\\妙手陶老师本人_3xr7zzgq96gpawe_2026-08-22_140426.ts",
      "decoded_frames": 140466,
      "last_sample_frame": 140460,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 7023.3,
      "worker_seconds": 281.47687099999166,
      "complete": true,
      "embedded_frames": 7024
    },
    {
      "fps": 20.0,
      "step": 20,
      "declared_frames": 36017.0,
      "asset_id": "AST-6472D4283A8CFB20107C",
      "video_id": 245,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\陶老师3-4月直播\\未获取202607011644.ts",
      "decoded_frames": 34773,
      "last_sample_frame": 34760,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 1738.65,
      "worker_seconds": 76.65163880000182,
      "complete": true,
      "embedded_frames": 1739
    },
    {
      "fps": 20.0,
      "step": 20,
      "declared_frames": 133942.0,
      "asset_id": "AST-6642C9506638FB62B96D",
      "video_id": 126,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\陶老师3-4月直播\\2026年03月13日11时32分55秒.ts",
      "decoded_frames": 106897,
      "last_sample_frame": 106880,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 5344.85,
      "worker_seconds": 212.1239140999969,
      "complete": true,
      "embedded_frames": 5345
    },
    {
      "fps": 62.02619047619048,
      "step": 62,
      "declared_frames": 18780.0,
      "asset_id": "AST-6A3759C100EC8C00E7F5",
      "video_id": 277,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\1-3月陶抖音直播素材\\三月\\3.3\\妙手陶老师_95765895385_2026-03-03_213502.ts",
      "decoded_frames": 18163,
      "last_sample_frame": 18104,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 292.82791447545196,
      "worker_seconds": 46.94384469999932,
      "complete": true,
      "embedded_frames": 293
    },
    {
      "fps": 30.0,
      "step": 30,
      "declared_frames": 285210.0,
      "asset_id": "AST-6C496860466588CB8309",
      "video_id": 89,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\5.6月\\2026.5月\\5.7\\2026年05月07日11时54分04秒.ts",
      "decoded_frames": 159817,
      "last_sample_frame": 159810,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 5327.233333333334,
      "worker_seconds": 581.9113574999938,
      "complete": true,
      "embedded_frames": 5328
    },
    {
      "fps": 20.0,
      "step": 20,
      "declared_frames": 27293.0,
      "asset_id": "AST-6D076C35AA7D3A49F10C",
      "video_id": 96,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\妙手陶老师本人_3xr7zzgq96gpawe_2026-08-14_140439.ts",
      "decoded_frames": 27270,
      "last_sample_frame": 27260,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 1363.5,
      "worker_seconds": 56.92010120001214,
      "complete": true,
      "embedded_frames": 1364
    },
    {
      "fps": 62.02619047619048,
      "step": 62,
      "declared_frames": 253029.0,
      "asset_id": "AST-7042181A43B6AD1269C8",
      "video_id": 281,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\1-3月陶抖音直播素材\\二月\\2.28\\妙手陶老师_95765895385_2026-02-28_192150.ts",
      "decoded_frames": 244760,
      "last_sample_frame": 244714,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 3946.0750067175923,
      "worker_seconds": 545.4884934000002,
      "complete": true,
      "embedded_frames": 3948
    },
    {
      "fps": 30.0,
      "step": 30,
      "declared_frames": 326270.0,
      "asset_id": "AST-73A83CF376D1198336C6",
      "video_id": 175,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\陶老师3-4月直播\\2026年06月04日17时06分14秒.ts",
      "decoded_frames": 322277,
      "last_sample_frame": 322260,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 10742.566666666668,
      "worker_seconds": 410.68443619999744,
      "complete": true,
      "embedded_frames": 10743
    },
    {
      "fps": 30.0,
      "step": 30,
      "declared_frames": 284015.0,
      "asset_id": "AST-73E51EB025E29C5C05F2",
      "video_id": 181,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\陶老师3-4月直播\\2026年06月12日16时42分12秒.ts",
      "decoded_frames": 283795,
      "last_sample_frame": 283770,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 9459.833333333334,
      "worker_seconds": 357.90635920000204,
      "complete": true,
      "embedded_frames": 9460
    },
    {
      "fps": 29.97002997002997,
      "step": 29,
      "declared_frames": 382325.0,
      "asset_id": "AST-76117F63B276380F01B0",
      "video_id": 179,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\陶老师3-4月直播\\2026年06月08日17时30分32秒.ts",
      "decoded_frames": 379651,
      "last_sample_frame": 379639,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 12667.688366666667,
      "worker_seconds": 477.002705100007,
      "complete": true,
      "embedded_frames": 13092
    },
    {
      "fps": 20.0,
      "step": 20,
      "declared_frames": 269509.0,
      "asset_id": "AST-767397B9594BB9F41785",
      "video_id": 99,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\妙手陶老师本人_3xr7zzgq96gpawe_2026-08-16_135313.ts",
      "decoded_frames": 269445,
      "last_sample_frame": 269440,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 13472.25,
      "worker_seconds": 560.3132996999921,
      "complete": true,
      "embedded_frames": 13473
    },
    {
      "fps": 30.0,
      "step": 30,
      "declared_frames": 324354.0,
      "asset_id": "AST-7738FF97E1E213943D2D",
      "video_id": 79,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\5.6月\\2026.5月\\5.25\\2026年05月25日12时05分40秒.ts",
      "decoded_frames": 324212,
      "last_sample_frame": 324210,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 10807.066666666668,
      "worker_seconds": 394.19286779999675,
      "complete": true,
      "embedded_frames": 10808
    },
    {
      "fps": 30.0,
      "step": 30,
      "declared_frames": 217983.0,
      "asset_id": "AST-7751461C21762E7460DF",
      "video_id": 71,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\5.6月\\2026.5月\\5.21\\2026年05月21日11时49分34秒.ts",
      "decoded_frames": 210380,
      "last_sample_frame": 210360,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 7012.666666666667,
      "worker_seconds": 969.5606368000008,
      "complete": true,
      "embedded_frames": 7013
    },
    {
      "fps": 20.0,
      "step": 20,
      "declared_frames": 175742.0,
      "asset_id": "AST-7867BA77E879D7A17843",
      "video_id": 254,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\陶老师7月直播素材\\妙手陶老师本人_3xr7zzgq96gpawe_2026-07-05_140942.ts",
      "decoded_frames": 175711,
      "last_sample_frame": 175700,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 8785.55,
      "worker_seconds": 380.22328350000316,
      "complete": true,
      "embedded_frames": 8786
    },
    {
      "fps": 20.0,
      "step": 20,
      "declared_frames": 101944.0,
      "asset_id": "AST-7868C957DD065149B9B1",
      "video_id": 4,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\妙手陶老师本人_3xr7zzgq96gpawe_2026-07-22_141704.ts",
      "decoded_frames": 6700,
      "last_sample_frame": 6680,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 335.0,
      "worker_seconds": 14.471289900000556,
      "complete": true,
      "embedded_frames": 335
    },
    {
      "fps": 20.0,
      "step": 20,
      "declared_frames": 289547.0,
      "asset_id": "AST-7AF29ABC32F700B93156",
      "video_id": 311,
      "file_path": "D:\\素材\\8月(1)\\妙手陶老师本人_3xr7zzgq96gpawe_2026-08-29_141344.ts",
      "decoded_frames": 289407,
      "last_sample_frame": 289400,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 14470.35,
      "worker_seconds": 642.3125733000052,
      "complete": true,
      "embedded_frames": 14471
    },
    {
      "fps": 30.0,
      "step": 30,
      "declared_frames": 242092.0,
      "asset_id": "AST-7E7DEB42D95F33E10EB6",
      "video_id": 76,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\5.6月\\2026.5月\\5.23\\2026年05月23日16时12分15秒.ts",
      "decoded_frames": 241995,
      "last_sample_frame": 241980,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 8066.5,
      "worker_seconds": 1002.4219941000047,
      "complete": true,
      "embedded_frames": 8067
    },
    {
      "fps": 20.0,
      "step": 20,
      "declared_frames": 3110.0,
      "asset_id": "AST-7EA18A56598C7F13D974",
      "video_id": 334,
      "file_path": "D:\\素材\\9月(1)\\妙手陶老师本人_3xr7zzgq96gpawe_2026-09-13_210703.ts",
      "decoded_frames": 3027,
      "last_sample_frame": 3020,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 151.35,
      "worker_seconds": 6.124939899993478,
      "complete": true,
      "embedded_frames": 152
    },
    {
      "fps": 20.0,
      "step": 20,
      "declared_frames": 170136.0,
      "asset_id": "AST-7EA7D1D04B0582081DBD",
      "video_id": 308,
      "file_path": "D:\\素材\\8月(1)\\妙手陶老师本人_3xr7zzgq96gpawe_2026-08-24_140840.ts",
      "decoded_frames": 170098,
      "last_sample_frame": 170080,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 8504.9,
      "worker_seconds": 383.76754039998923,
      "complete": true,
      "embedded_frames": 8505
    },
    {
      "fps": 20.0,
      "step": 20,
      "declared_frames": 107257.0,
      "asset_id": "AST-7F11D44F62D72D0F9510",
      "video_id": 150,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\陶老师3-4月直播\\2026年04月10日15时39分15秒.ts",
      "decoded_frames": 107219,
      "last_sample_frame": 107200,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 5360.95,
      "worker_seconds": 210.07974420000392,
      "complete": true,
      "embedded_frames": 5361
    },
    {
      "fps": 20.0,
      "step": 20,
      "declared_frames": 232741.0,
      "asset_id": "AST-7FF49A83E81B6CE5F46C",
      "video_id": 114,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\妙手陶老师本人_3xr7zzgq96gpawe_2026-09-12_142021.ts",
      "decoded_frames": 223125,
      "last_sample_frame": 223120,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 11156.25,
      "worker_seconds": 455.81812830000126,
      "complete": true,
      "embedded_frames": 11157
    },
    {
      "fps": 20.0,
      "step": 20,
      "declared_frames": 82123.0,
      "asset_id": "AST-81C3434F9E5FF5B33BAE",
      "video_id": 156,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\陶老师3-4月直播\\2026年04月16日11时17分58秒.ts",
      "decoded_frames": 82087,
      "last_sample_frame": 82080,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 4104.35,
      "worker_seconds": 164.67532920000667,
      "complete": true,
      "embedded_frames": 4105
    },
    {
      "fps": 20.0,
      "step": 20,
      "declared_frames": 141437.0,
      "asset_id": "AST-8341B33A407EA35FCADE",
      "video_id": 25,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\5.6月\\2026(1).6月\\6.27\\妙手陶老师本人_3xr7zzgq96gpawe_2026-06-27_142207.ts",
      "decoded_frames": 140899,
      "last_sample_frame": 140880,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 7044.95,
      "worker_seconds": 323.39700399999856,
      "complete": true,
      "embedded_frames": 7045
    },
    {
      "fps": 20.0,
      "step": 20,
      "declared_frames": 115931.0,
      "asset_id": "AST-87C38ACC7950AFF7E7C3",
      "video_id": 149,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\陶老师3-4月直播\\2026年04月09日17时22分30秒.ts",
      "decoded_frames": 115896,
      "last_sample_frame": 115880,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 5794.8,
      "worker_seconds": 259.6808280000114,
      "complete": true,
      "embedded_frames": 5795
    },
    {
      "fps": 20.0,
      "step": 20,
      "declared_frames": 27407.0,
      "asset_id": "AST-89A142C2BFC3DA41B872",
      "video_id": 301,
      "file_path": "D:\\素材\\8月(1)\\妙手陶老师本人_3xr7zzgq96gpawe_2026-08-14_140427.ts",
      "decoded_frames": 27382,
      "last_sample_frame": 27380,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 1369.1,
      "worker_seconds": 60.75066649999644,
      "complete": true,
      "embedded_frames": 1370
    },
    {
      "fps": 20.0,
      "step": 20,
      "declared_frames": 92623.0,
      "asset_id": "AST-8CD618A352F5E7AC3C71",
      "video_id": 133,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\陶老师3-4月直播\\2026年03月23日22时00分21秒.ts",
      "decoded_frames": 92583,
      "last_sample_frame": 92580,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 4629.15,
      "worker_seconds": 174.34258440000121,
      "complete": true,
      "embedded_frames": 4630
    },
    {
      "fps": 20.0,
      "step": 20,
      "declared_frames": 259274.0,
      "asset_id": "AST-8DD57F60600011244D0E",
      "video_id": 169,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\陶老师3-4月直播\\2026年04月29日12时48分55秒.ts",
      "decoded_frames": 253777,
      "last_sample_frame": 253760,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 12688.85,
      "worker_seconds": 459.3743601999886,
      "complete": true,
      "embedded_frames": 12689
    },
    {
      "fps": 20.0,
      "step": 20,
      "declared_frames": 210500.0,
      "asset_id": "AST-8EA0AEFA1F1B7BB1E27C",
      "video_id": 11,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\妙手陶老师本人_3xr7zzgq96gpawe_2026-08-07_140450.ts",
      "decoded_frames": 210458,
      "last_sample_frame": 210440,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 10522.9,
      "worker_seconds": 473.8632438000059,
      "complete": true,
      "embedded_frames": 10523
    },
    {
      "fps": 20.0,
      "step": 20,
      "declared_frames": 120665.0,
      "asset_id": "AST-8F7F1037EE70B9642852",
      "video_id": 137,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\陶老师3-4月直播\\2026年03月27日11时44分45秒.ts",
      "decoded_frames": 120625,
      "last_sample_frame": 120620,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 6031.25,
      "worker_seconds": 236.2875364000065,
      "complete": true,
      "embedded_frames": 6032
    },
    {
      "fps": 20.0,
      "step": 20,
      "declared_frames": 36315.0,
      "asset_id": "AST-8F8168DEEEFC352A7E7D",
      "video_id": 289,
      "file_path": "D:\\素材\\8月(1)\\妙手陶老师本人_3xr7zzgq96gpawe_2026-08-01_140420.ts",
      "decoded_frames": 36112,
      "last_sample_frame": 36100,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 1805.6,
      "worker_seconds": 82.6955522000062,
      "complete": true,
      "embedded_frames": 1806
    },
    {
      "fps": 20.0,
      "step": 20,
      "declared_frames": 172057.0,
      "asset_id": "AST-908A31BFFF9AF3A61379",
      "video_id": 310,
      "file_path": "D:\\素材\\8月(1)\\妙手陶老师本人_3xr7zzgq96gpawe_2026-08-28_141311.ts",
      "decoded_frames": 172015,
      "last_sample_frame": 172000,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 8600.75,
      "worker_seconds": 357.9343552000064,
      "complete": true,
      "embedded_frames": 8601
    },
    {
      "fps": 45.0,
      "step": 45,
      "declared_frames": 181507.0,
      "asset_id": "AST-92286CE9A51FFE22FBBA",
      "video_id": 285,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\1-3月陶抖音直播素材\\二月\\2.5\\妙手陶老师_95765895385_2026-02-05_203616.ts",
      "decoded_frames": 180670,
      "last_sample_frame": 180630,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 4014.8888888888887,
      "worker_seconds": 502.22194500001206,
      "complete": true,
      "embedded_frames": 4015
    },
    {
      "fps": 62.02619047619048,
      "step": 62,
      "declared_frames": 332427.0,
      "asset_id": "AST-93DD209D5FD6A9AD594A",
      "video_id": 280,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\1-3月陶抖音直播素材\\二月\\2.27\\妙手陶老师_95765895385_2026-02-27_194357.ts",
      "decoded_frames": 321547,
      "last_sample_frame": 321532,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 5184.052051744655,
      "worker_seconds": 800.8061217000068,
      "complete": true,
      "embedded_frames": 5187
    },
    {
      "fps": 30.0,
      "step": 30,
      "declared_frames": 128912.0,
      "asset_id": "AST-9689572D2786EA43E24F",
      "video_id": 82,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\5.6月\\2026.5月\\5.28\\2026年05月28日15时24分54秒.ts",
      "decoded_frames": 107119,
      "last_sample_frame": 107100,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 3570.633333333333,
      "worker_seconds": 146.179830699999,
      "complete": true,
      "embedded_frames": 3571
    },
    {
      "fps": 29.97002997002997,
      "step": 29,
      "declared_frames": 437493.0,
      "asset_id": "AST-980E63A697C98AD2662C",
      "video_id": 176,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\陶老师3-4月直播\\2026年06月05日17时59分53秒.ts",
      "decoded_frames": 435055,
      "last_sample_frame": 435029,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 14516.335166666668,
      "worker_seconds": 584.324646500012,
      "complete": true,
      "embedded_frames": 15002
    },
    {
      "fps": 20.0,
      "step": 20,
      "declared_frames": 93337.0,
      "asset_id": "AST-9AC26B9B0923E72F0C6E",
      "video_id": 120,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\陶老师3-4月直播\\2026年03月07日10时52分28秒.ts",
      "decoded_frames": 93191,
      "last_sample_frame": 93180,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 4659.55,
      "worker_seconds": 178.40706409999984,
      "complete": true,
      "embedded_frames": 4660
    },
    {
      "fps": 62.02619047619048,
      "step": 62,
      "declared_frames": 231229.0,
      "asset_id": "AST-9CAE41D7D7284D44B25A",
      "video_id": 282,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\1-3月陶抖音直播素材\\二月\\2.3\\妙手陶老师_95765895385_2026-02-03_204043.ts",
      "decoded_frames": 223386,
      "last_sample_frame": 223324,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 3601.4786380561204,
      "worker_seconds": 646.3129417000018,
      "complete": true,
      "embedded_frames": 3603
    },
    {
      "fps": 62.02619047619048,
      "step": 62,
      "declared_frames": 122203.0,
      "asset_id": "AST-9E2DE06C79A642E1387E",
      "video_id": 278,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\1-3月陶抖音直播素材\\二月\\2.2\\妙手陶老师_95765895385_2026-02-02_204431.ts",
      "decoded_frames": 118211,
      "last_sample_frame": 118172,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 1905.8239606924878,
      "worker_seconds": 305.3110355999961,
      "complete": true,
      "embedded_frames": 1907
    },
    {
      "fps": 20.0,
      "step": 20,
      "declared_frames": 280021.0,
      "asset_id": "AST-9F0B4AA659E2ADB1B126",
      "video_id": 292,
      "file_path": "D:\\素材\\8月(1)\\妙手陶老师本人_3xr7zzgq96gpawe_2026-08-02_140033.ts",
      "decoded_frames": 189825,
      "last_sample_frame": 189820,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 9491.25,
      "worker_seconds": 465.49071040000126,
      "complete": true,
      "embedded_frames": 9492
    },
    {
      "fps": 20.0,
      "step": 20,
      "declared_frames": 35973.0,
      "asset_id": "AST-A12E8CEDD4EE0784CEF9",
      "video_id": 191,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\陶老师3-4月直播\\未获取202606211502.ts",
      "decoded_frames": 35888,
      "last_sample_frame": 35880,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 1794.4,
      "worker_seconds": 86.15880029999244,
      "complete": true,
      "embedded_frames": 1795
    },
    {
      "fps": 20.0,
      "step": 20,
      "declared_frames": 91657.0,
      "asset_id": "AST-A43789948358EA116611",
      "video_id": 151,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\陶老师3-4月直播\\2026年04月11日15时46分19秒.ts",
      "decoded_frames": 91091,
      "last_sample_frame": 91080,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 4554.55,
      "worker_seconds": 205.63129199999094,
      "complete": true,
      "embedded_frames": 4555
    },
    {
      "fps": 20.0,
      "step": 20,
      "declared_frames": 9971.0,
      "asset_id": "AST-A77EC9C39CBD9CDE459E",
      "video_id": 243,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\陶老师3-4月直播\\未获取202607011604.ts",
      "decoded_frames": 9585,
      "last_sample_frame": 9580,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 479.25,
      "worker_seconds": 24.828411300011794,
      "complete": true,
      "embedded_frames": 480
    },
    {
      "fps": 20.0,
      "step": 20,
      "declared_frames": 141406.0,
      "asset_id": "AST-A7918544FDDB51028625",
      "video_id": 329,
      "file_path": "D:\\素材\\9月(1)\\妙手陶老师本人_3xr7zzgq96gpawe_2026-09-11_200510.ts",
      "decoded_frames": 141383,
      "last_sample_frame": 141380,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 7069.15,
      "worker_seconds": 328.4647249000118,
      "complete": true,
      "embedded_frames": 7070
    },
    {
      "fps": 20.0,
      "step": 20,
      "declared_frames": 36008.0,
      "asset_id": "AST-A7F224E6B94DBC89F1DF",
      "video_id": 246,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\陶老师3-4月直播\\未获取202607011713.ts",
      "decoded_frames": 35976,
      "last_sample_frame": 35960,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 1798.8,
      "worker_seconds": 83.97946210000373,
      "complete": true,
      "embedded_frames": 1799
    },
    {
      "fps": 30.0,
      "step": 30,
      "declared_frames": 154538.0,
      "asset_id": "AST-AA29AB02E114DD0A4BDE",
      "video_id": 85,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\5.6月\\2026.5月\\5.3\\2026年05月03日16时31分47秒.ts",
      "decoded_frames": 154381,
      "last_sample_frame": 154380,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 5146.033333333334,
      "worker_seconds": 706.3596187999938,
      "complete": true,
      "embedded_frames": 5147
    },
    {
      "fps": 20.0,
      "step": 20,
      "declared_frames": 35735.0,
      "asset_id": "AST-AD2A556961328C7F5C38",
      "video_id": 333,
      "file_path": "D:\\素材\\9月(1)\\妙手陶老师本人_3xr7zzgq96gpawe_2026-09-13_203527.ts",
      "decoded_frames": 27890,
      "last_sample_frame": 27880,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 1394.5,
      "worker_seconds": 63.066197599997395,
      "complete": true,
      "embedded_frames": 1395
    },
    {
      "fps": 29.97002997002997,
      "step": 29,
      "declared_frames": 189841.0,
      "asset_id": "AST-AF42C8D0A7D3EC52B30E",
      "video_id": 74,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\5.6月\\2026.5月\\5.22\\2026年05月22日15时58分53秒.ts",
      "decoded_frames": 188573,
      "last_sample_frame": 188558,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 6292.052433333333,
      "worker_seconds": 250.5307613999903,
      "complete": true,
      "embedded_frames": 6503
    },
    {
      "fps": 30.0,
      "step": 30,
      "declared_frames": 225873.0,
      "asset_id": "AST-B8BA55784E8826FF6C5D",
      "video_id": 180,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\陶老师3-4月直播\\2026年06月11日16时11分22秒.ts",
      "decoded_frames": 225660,
      "last_sample_frame": 225630,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 7522.0,
      "worker_seconds": 310.7117302999977,
      "complete": true,
      "embedded_frames": 7522
    },
    {
      "fps": 20.0,
      "step": 20,
      "declared_frames": 293410.0,
      "asset_id": "AST-BC4025DCCB64FB897A4A",
      "video_id": 104,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\妙手陶老师本人_3xr7zzgq96gpawe_2026-08-30_141848.ts",
      "decoded_frames": 292856,
      "last_sample_frame": 292840,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 14642.8,
      "worker_seconds": 701.630270099995,
      "complete": true,
      "embedded_frames": 14643
    },
    {
      "fps": 62.02619047619048,
      "step": 62,
      "declared_frames": 282548.0,
      "asset_id": "AST-C40533554EE2E7FA2D2F",
      "video_id": 276,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\1-3月陶抖音直播素材\\三月\\3.3\\妙手陶老师_95765895385_2026-03-03_201658.ts",
      "decoded_frames": 273313,
      "last_sample_frame": 273296,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 4406.412805650455,
      "worker_seconds": 726.8775138000055,
      "complete": true,
      "embedded_frames": 4409
    },
    {
      "fps": 30.0,
      "step": 30,
      "declared_frames": 331323.0,
      "asset_id": "AST-C77D5A7246E94E42BE55",
      "video_id": 178,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\陶老师3-4月直播\\2026年06月07日17时05分18秒.ts",
      "decoded_frames": 329973,
      "last_sample_frame": 329970,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 10999.1,
      "worker_seconds": 445.7206329000037,
      "complete": true,
      "embedded_frames": 11000
    },
    {
      "fps": 20.0,
      "step": 20,
      "declared_frames": 68006.0,
      "asset_id": "AST-C7F0B096A5B9EA60C8FD",
      "video_id": 140,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\陶老师3-4月直播\\2026年03月31日12时12分05秒.ts",
      "decoded_frames": 67714,
      "last_sample_frame": 67700,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 3385.7,
      "worker_seconds": 126.02354470000137,
      "complete": true,
      "embedded_frames": 3386
    },
    {
      "fps": 20.0,
      "step": 20,
      "declared_frames": 269701.0,
      "asset_id": "AST-CC4E84F46058F4D809BC",
      "video_id": 314,
      "file_path": "D:\\素材\\9月(1)\\妙手陶老师本人_3xr7zzgq96gpawe_2026-09-01_142402.ts",
      "decoded_frames": 265740,
      "last_sample_frame": 265720,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 13287.0,
      "worker_seconds": 597.9157620000042,
      "complete": true,
      "embedded_frames": 13287
    },
    {
      "fps": 29.97002997002997,
      "step": 29,
      "declared_frames": 298751.0,
      "asset_id": "AST-CCB6CD81C8BD6C47BED1",
      "video_id": 171,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\陶老师3-4月直播\\2026年04月30日11时58分11秒.ts",
      "decoded_frames": 289489,
      "last_sample_frame": 289478,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 9659.282966666668,
      "worker_seconds": 2277.4736505000037,
      "complete": true,
      "embedded_frames": 9983
    },
    {
      "fps": 20.0,
      "step": 20,
      "declared_frames": 228626.0,
      "asset_id": "AST-CD5C4D21398389ED8BD3",
      "video_id": 249,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\陶老师7月直播素材\\妙手陶老师本人_3xr7zzgq96gpawe_2026-07-01_140217.ts",
      "decoded_frames": 227666,
      "last_sample_frame": 227660,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 11383.3,
      "worker_seconds": 449.96926359999634,
      "complete": true,
      "embedded_frames": 11384
    },
    {
      "fps": 20.0,
      "step": 20,
      "declared_frames": 64200.0,
      "asset_id": "AST-CD7568DE51BD71E32C60",
      "video_id": 155,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\陶老师3-4月直播\\2026年04月15日21时24分17秒.ts",
      "decoded_frames": 64160,
      "last_sample_frame": 64140,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 3208.0,
      "worker_seconds": 116.962704199992,
      "complete": true,
      "embedded_frames": 3208
    },
    {
      "fps": 20.0,
      "step": 20,
      "declared_frames": 100518.0,
      "asset_id": "AST-D379DCF603A23406D016",
      "video_id": 1,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\妙手陶老师本人_3xr7zzgq96gpawe_2026-07-19_145449.ts",
      "decoded_frames": 93634,
      "last_sample_frame": 93620,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 4681.7,
      "worker_seconds": 217.05416040000273,
      "complete": true,
      "embedded_frames": 4682
    },
    {
      "fps": 20.0,
      "step": 20,
      "declared_frames": 146710.0,
      "asset_id": "AST-D462EB1034502C230032",
      "video_id": 130,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\陶老师3-4月直播\\2026年03月15日11时52分10秒.ts",
      "decoded_frames": 141203,
      "last_sample_frame": 141200,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 7060.15,
      "worker_seconds": 269.49913170000946,
      "complete": true,
      "embedded_frames": 7061
    },
    {
      "fps": 30.0,
      "step": 30,
      "declared_frames": 255536.0,
      "asset_id": "AST-D4C986B8FDDB659FDB5B",
      "video_id": 81,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\5.6月\\2026.5月\\5.27\\2026年05月27日16时21分51秒.ts",
      "decoded_frames": 255368,
      "last_sample_frame": 255360,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 8512.266666666666,
      "worker_seconds": 314.8212438000046,
      "complete": true,
      "embedded_frames": 8513
    },
    {
      "fps": 20.0,
      "step": 20,
      "declared_frames": 177331.0,
      "asset_id": "AST-D6FF653DC3E618F11529",
      "video_id": 358,
      "file_path": "D:\\素材\\9月(1)\\妙手陶老师本人_3xr7zzgq96gpawe_2026-09-19_141020.ts",
      "decoded_frames": 175405,
      "last_sample_frame": 175400,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 8770.25,
      "worker_seconds": 375.79391160000523,
      "complete": true,
      "embedded_frames": 8771
    },
    {
      "fps": 30.0,
      "step": 30,
      "declared_frames": 184958.0,
      "asset_id": "AST-D8C6D3E403481F7F101D",
      "video_id": 87,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\5.6月\\2026.5月\\5.5\\2026年05月05日16时00分05秒.ts",
      "decoded_frames": 184874,
      "last_sample_frame": 184860,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 6162.466666666666,
      "worker_seconds": 766.8678357999888,
      "complete": true,
      "embedded_frames": 6163
    },
    {
      "fps": 20.0,
      "step": 20,
      "declared_frames": 177323.0,
      "asset_id": "AST-DC2169C74B5621763C34",
      "video_id": 321,
      "file_path": "D:\\素材\\9月(1)\\妙手陶老师本人_3xr7zzgq96gpawe_2026-09-07_145327.ts",
      "decoded_frames": 172751,
      "last_sample_frame": 172740,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 8637.55,
      "worker_seconds": 423.58645070000784,
      "complete": true,
      "embedded_frames": 8638
    },
    {
      "fps": 30.0,
      "step": 30,
      "declared_frames": 284069.0,
      "asset_id": "AST-DE4047839ECA16C53A1A",
      "video_id": 16,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\5.6月\\2026(1).6月\\6.14\\2026年06月14日16时39分20秒.ts",
      "decoded_frames": 283647,
      "last_sample_frame": 283620,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 9454.9,
      "worker_seconds": 338.3062346000079,
      "complete": true,
      "embedded_frames": 9455
    },
    {
      "fps": 90000.0,
      "step": 90000,
      "declared_frames": 775830511.0,
      "asset_id": "AST-DECBE530687EAB1844D7",
      "video_id": 75,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\5.6月\\2026.5月\\5.23\\2026年05月23日11时21分17秒.ts",
      "decoded_frames": 152304,
      "last_sample_frame": 90000,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 1.6922666666666666,
      "worker_seconds": 127.543413899999,
      "complete": true,
      "embedded_frames": 2
    },
    {
      "fps": 30.0,
      "step": 30,
      "declared_frames": 294431.0,
      "asset_id": "AST-E3EAD0FAD10420B108C6",
      "video_id": 84,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\5.6月\\2026.5月\\5.30\\2026年05月30日16时38分07秒.ts",
      "decoded_frames": 288127,
      "last_sample_frame": 288120,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 9604.233333333334,
      "worker_seconds": 334.52129720000084,
      "complete": true,
      "embedded_frames": 9605
    },
    {
      "fps": 20.0,
      "step": 20,
      "declared_frames": 187166.0,
      "asset_id": "AST-E432C531EEA1E83BF8C0",
      "video_id": 252,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\陶老师7月直播素材\\妙手陶老师本人_3xr7zzgq96gpawe_2026-07-03_140134.ts",
      "decoded_frames": 182618,
      "last_sample_frame": 182600,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 9130.9,
      "worker_seconds": 412.74290130000736,
      "complete": true,
      "embedded_frames": 9131
    },
    {
      "fps": 20.0,
      "step": 20,
      "declared_frames": 49978.0,
      "asset_id": "AST-E44366A35CC49BDDBC72",
      "video_id": 322,
      "file_path": "D:\\素材\\9月(1)\\妙手陶老师本人_3xr7zzgq96gpawe_2026-09-08_141021.ts",
      "decoded_frames": 49637,
      "last_sample_frame": 49620,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 2481.85,
      "worker_seconds": 108.72216550000303,
      "complete": true,
      "embedded_frames": 2482
    },
    {
      "fps": 20.0,
      "step": 20,
      "declared_frames": 299781.0,
      "asset_id": "AST-E61BC49ED42CCA012366",
      "video_id": 312,
      "file_path": "D:\\素材\\8月(1)\\妙手陶老师本人_3xr7zzgq96gpawe_2026-08-30_141323.ts",
      "decoded_frames": 299224,
      "last_sample_frame": 299220,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 14961.2,
      "worker_seconds": 613.3885865000047,
      "complete": true,
      "embedded_frames": 14962
    },
    {
      "fps": 30.0,
      "step": 30,
      "declared_frames": 240801.0,
      "asset_id": "AST-E7B27F4167628532EB62",
      "video_id": 15,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\5.6月\\2026(1).6月\\6.13\\2026年06月13日16时13分33秒.ts",
      "decoded_frames": 240704,
      "last_sample_frame": 240690,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 8023.466666666666,
      "worker_seconds": 305.29793089999293,
      "complete": true,
      "embedded_frames": 8024
    },
    {
      "fps": 30.0,
      "step": 30,
      "declared_frames": 133271.0,
      "asset_id": "AST-E9DD0103172C33FE63E8",
      "video_id": 70,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\5.6月\\2026.5月\\5.17\\2026年05月17日12时08分04秒.ts",
      "decoded_frames": 132463,
      "last_sample_frame": 132450,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 4415.433333333333,
      "worker_seconds": 548.2687986000092,
      "complete": true,
      "embedded_frames": 4416
    },
    {
      "fps": 30.0,
      "step": 30,
      "declared_frames": 214536.0,
      "asset_id": "AST-E9E8054E49535431495A",
      "video_id": 64,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\5.6月\\2026.5月\\5.10\\2026年05月10日11时41分07秒.ts",
      "decoded_frames": 197582,
      "last_sample_frame": 197580,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 6586.066666666667,
      "worker_seconds": 801.7445300999971,
      "complete": true,
      "embedded_frames": 6587
    },
    {
      "fps": 45.0,
      "step": 45,
      "declared_frames": 123320.0,
      "asset_id": "AST-EC2DC5421D68A50C4D66",
      "video_id": 268,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\1-3月陶抖音直播素材\\一月\\1.19\\妙手陶老师_95765895385_2026-01-19_214639.ts",
      "decoded_frames": 123174,
      "last_sample_frame": 123165,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 2737.2,
      "worker_seconds": 350.28964620000625,
      "complete": true,
      "embedded_frames": 2738
    },
    {
      "fps": 30.0,
      "step": 30,
      "declared_frames": 235036.0,
      "asset_id": "AST-EEDE7CD0655CD5CF1382",
      "video_id": 93,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\5.6月\\2026.5月\\5.9\\2026年05月09日11时45分12秒.ts",
      "decoded_frames": 161786,
      "last_sample_frame": 161760,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 5392.866666666667,
      "worker_seconds": 663.3602675000002,
      "complete": true,
      "embedded_frames": 5393
    },
    {
      "fps": 20.0,
      "step": 20,
      "declared_frames": 86486.0,
      "asset_id": "AST-F1D8F7910477565DDD6B",
      "video_id": 153,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\陶老师3-4月直播\\2026年04月12日15时23分08秒.ts",
      "decoded_frames": 86451,
      "last_sample_frame": 86440,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 4322.55,
      "worker_seconds": 174.36331200000132,
      "complete": true,
      "embedded_frames": 4323
    },
    {
      "fps": 20.0,
      "step": 20,
      "declared_frames": 36016.0,
      "asset_id": "AST-F3CED4CD47A9249942BD",
      "video_id": 190,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\陶老师3-4月直播\\未获取202606211431.ts",
      "decoded_frames": 35946,
      "last_sample_frame": 35940,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 1797.3,
      "worker_seconds": 75.08247739999206,
      "complete": true,
      "embedded_frames": 1798
    },
    {
      "fps": 20.0,
      "step": 20,
      "declared_frames": 71898.0,
      "asset_id": "AST-F3FDC4BFC860F16850B2",
      "video_id": 132,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\陶老师3-4月直播\\2026年03月20日21时54分56秒.ts",
      "decoded_frames": 71858,
      "last_sample_frame": 71840,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 3592.9,
      "worker_seconds": 147.0639463999978,
      "complete": true,
      "embedded_frames": 3593
    },
    {
      "fps": 20.0,
      "step": 20,
      "declared_frames": 79765.0,
      "asset_id": "AST-F63B353A455E0E5BB2B7",
      "video_id": 250,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\陶老师7月直播素材\\妙手陶老师本人_3xr7zzgq96gpawe_2026-07-01_171259.ts",
      "decoded_frames": 79625,
      "last_sample_frame": 79620,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 3981.25,
      "worker_seconds": 182.81186430000525,
      "complete": true,
      "embedded_frames": 3982
    },
    {
      "fps": 20.0,
      "step": 20,
      "declared_frames": 72413.0,
      "asset_id": "AST-F84717A0FF4253060D2C",
      "video_id": 134,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\陶老师3-4月直播\\2026年03月25日16时12分56秒.ts",
      "decoded_frames": 72374,
      "last_sample_frame": 72360,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 3618.7,
      "worker_seconds": 129.20427319999726,
      "complete": true,
      "embedded_frames": 3619
    },
    {
      "fps": 20.0,
      "step": 20,
      "declared_frames": 134549.0,
      "asset_id": "AST-F96F63E4F5F6E39353E3",
      "video_id": 330,
      "file_path": "D:\\素材\\9月(1)\\妙手陶老师本人_3xr7zzgq96gpawe_2026-09-12_154211.ts",
      "decoded_frames": 125052,
      "last_sample_frame": 125040,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 6252.6,
      "worker_seconds": 254.62099149999267,
      "complete": true,
      "embedded_frames": 6253
    },
    {
      "fps": 30.0,
      "step": 30,
      "declared_frames": 182856.0,
      "asset_id": "AST-FA78A48EC35CE5EFBA92",
      "video_id": 66,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\5.6月\\2026.5月\\5.11\\2026年05月11日16时56分50秒.ts",
      "decoded_frames": 182766,
      "last_sample_frame": 182760,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 6092.2,
      "worker_seconds": 701.2372460000042,
      "complete": true,
      "embedded_frames": 6093
    },
    {
      "fps": 20.0,
      "step": 20,
      "declared_frames": 36015.0,
      "asset_id": "AST-FAE449A211974312DFF4",
      "video_id": 216,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\陶老师3-4月直播\\未获取202606261510.ts",
      "decoded_frames": 35883,
      "last_sample_frame": 35880,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 1794.15,
      "worker_seconds": 74.33615940000163,
      "complete": true,
      "embedded_frames": 1795
    },
    {
      "fps": 62.02619047619048,
      "step": 62,
      "declared_frames": 228797.0,
      "asset_id": "AST-FB110FBF29F390BDB347",
      "video_id": 272,
      "file_path": "E:\\备份\\陶老师直播录制\\妙手陶老师本人_3xr7zzgq96gpawe\\1-3月陶抖音直播素材\\一月\\1.29\\妙手陶老师_95765895385_2026-01-29_203730.ts",
      "decoded_frames": 221321,
      "last_sample_frame": 221278,
      "retrieve_failures": [],
      "early_decode_end": true,
      "decoded_duration_seconds": 3568.186250047983,
      "worker_seconds": 527.1833764000039,
      "complete": true,
      "embedded_frames": 3570
    }
  ],
  "truncated": 0
}
```

### timestamps / anomalous_timestamps

```json
{
  "total": 27793,
  "items": [
    {
      "frame_id": "AST-077629B2B73C06B423BA:20",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 1.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:40",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 2.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:60",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 3.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:80",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 4.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:100",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 5.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:120",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 6.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:140",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 7.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:160",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 8.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:180",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 9.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:200",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 10.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:220",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 11.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:240",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 12.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:260",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 13.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:280",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 14.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:300",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 15.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:320",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 16.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:340",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 17.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:360",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 18.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:380",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 19.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:400",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 20.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:420",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 21.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:440",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 22.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:460",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 23.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:480",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 24.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:500",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 25.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:520",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 26.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:540",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 27.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:560",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 28.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:580",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 29.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:600",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 30.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:620",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 31.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:640",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 32.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:660",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 33.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:680",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 34.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:700",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 35.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:720",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 36.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:740",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 37.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:760",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 38.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:780",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 39.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:800",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 40.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:820",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 41.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:840",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 42.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:860",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 43.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:880",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 44.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:900",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 45.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:920",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 46.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:940",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 47.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:960",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 48.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:980",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 49.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:1000",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 50.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:1020",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 51.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:1040",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 52.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:1060",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 53.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:1080",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 54.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:1100",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 55.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:1120",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 56.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:1140",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 57.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:1160",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 58.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:1180",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 59.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:1200",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 60.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:1220",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 61.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:1240",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 62.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:1260",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 63.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:1280",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 64.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:1300",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 65.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:1320",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 66.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:1340",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 67.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:1360",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 68.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:1380",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 69.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:1400",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 70.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:1420",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 71.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:1440",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 72.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:1460",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 73.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:1480",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 74.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:1500",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 75.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:1520",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 76.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:1540",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 77.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:1560",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 78.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:1580",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 79.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:1600",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 80.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:1620",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 81.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:1640",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 82.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:1660",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 83.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:1680",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 84.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:1700",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 85.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:1720",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 86.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:1740",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 87.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:1760",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 88.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:1780",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 89.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:1800",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 90.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:1820",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 91.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:1840",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 92.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:1860",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 93.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:1880",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 94.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:1900",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 95.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:1920",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 96.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:1940",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 97.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:1960",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 98.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:1980",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 99.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:2000",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 100.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:2020",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 101.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-077629B2B73C06B423BA:2040",
      "asset_id": "AST-077629B2B73C06B423BA",
      "video_id": 218,
      "timestamp": 102.0,
      "duration_seconds": 0.0477
    },
    {
      "frame_id": "AST-078F4DCD016AEFDA1362:6945",
      "asset_id": "AST-078F4DCD016AEFDA1362",
      "video_id": 335,
      "timestamp": 463.0,
      "duration_seconds": 462.094667
    },
    {
      "frame_id": "AST-078F4DCD016AEFDA1362:6960",
      "asset_id": "AST-078F4DCD016AEFDA1362",
      "video_id": 335,
      "timestamp": 464.0,
      "duration_seconds": 462.094667
    },
    {
      "frame_id": "AST-078F4DCD016AEFDA1362:6975",
      "asset_id": "AST-078F4DCD016AEFDA1362",
      "video_id": 335,
      "timestamp": 465.0,
      "duration_seconds": 462.094667
    },
    {
      "frame_id": "AST-078F4DCD016AEFDA1362:6990",
      "asset_id": "AST-078F4DCD016AEFDA1362",
      "video_id": 335,
      "timestamp": 466.0,
      "duration_seconds": 462.094667
    },
    {
      "frame_id": "AST-078F4DCD016AEFDA1362:7005",
      "asset_id": "AST-078F4DCD016AEFDA1362",
      "video_id": 335,
      "timestamp": 467.0,
      "duration_seconds": 462.094667
    },
    {
      "frame_id": "AST-078F4DCD016AEFDA1362:7020",
      "asset_id": "AST-078F4DCD016AEFDA1362",
      "video_id": 335,
      "timestamp": 468.0,
      "duration_seconds": 462.094667
    },
    {
      "frame_id": "AST-078F4DCD016AEFDA1362:7035",
      "asset_id": "AST-078F4DCD016AEFDA1362",
      "video_id": 335,
      "timestamp": 469.0,
      "duration_seconds": 462.094667
    },
    {
      "frame_id": "AST-078F4DCD016AEFDA1362:7050",
      "asset_id": "AST-078F4DCD016AEFDA1362",
      "video_id": 335,
      "timestamp": 470.0,
      "duration_seconds": 462.094667
    },
    {
      "frame_id": "AST-078F4DCD016AEFDA1362:7065",
      "asset_id": "AST-078F4DCD016AEFDA1362",
      "video_id": 335,
      "timestamp": 471.0,
      "duration_seconds": 462.094667
    },
    {
      "frame_id": "AST-078F4DCD016AEFDA1362:7080",
      "asset_id": "AST-078F4DCD016AEFDA1362",
      "video_id": 335,
      "timestamp": 472.0,
      "duration_seconds": 462.094667
    },
    {
      "frame_id": "AST-078F4DCD016AEFDA1362:7095",
      "asset_id": "AST-078F4DCD016AEFDA1362",
      "video_id": 335,
      "timestamp": 473.0,
      "duration_seconds": 462.094667
    },
    {
      "frame_id": "AST-078F4DCD016AEFDA1362:7110",
      "asset_id": "AST-078F4DCD016AEFDA1362",
      "video_id": 335,
      "timestamp": 474.0,
      "duration_seconds": 462.094667
    },
    {
      "frame_id": "AST-078F4DCD016AEFDA1362:7125",
      "asset_id": "AST-078F4DCD016AEFDA1362",
      "video_id": 335,
      "timestamp": 475.0,
      "duration_seconds": 462.094667
    },
    {
      "frame_id": "AST-078F4DCD016AEFDA1362:7140",
      "asset_id": "AST-078F4DCD016AEFDA1362",
      "video_id": 335,
      "timestamp": 476.0,
      "duration_seconds": 462.094667
    },
    {
      "frame_id": "AST-078F4DCD016AEFDA1362:7155",
      "asset_id": "AST-078F4DCD016AEFDA1362",
      "video_id": 335,
      "timestamp": 477.0,
      "duration_seconds": 462.094667
    },
    {
      "frame_id": "AST-078F4DCD016AEFDA1362:7170",
      "asset_id": "AST-078F4DCD016AEFDA1362",
      "video_id": 335,
      "timestamp": 478.0,
      "duration_seconds": 462.094667
    },
    {
      "frame_id": "AST-078F4DCD016AEFDA1362:7185",
      "asset_id": "AST-078F4DCD016AEFDA1362",
      "video_id": 335,
      "timestamp": 479.0,
      "duration_seconds": 462.094667
    },
    {
      "frame_id": "AST-078F4DCD016AEFDA1362:7200",
      "asset_id": "AST-078F4DCD016AEFDA1362",
      "video_id": 335,
      "timestamp": 480.0,
      "duration_seconds": 462.094667
    },
    {
      "frame_id": "AST-078F4DCD016AEFDA1362:7215",
      "asset_id": "AST-078F4DCD016AEFDA1362",
      "video_id": 335,
      "timestamp": 481.0,
      "duration_seconds": 462.094667
    },
    {
      "frame_id": "AST-078F4DCD016AEFDA1362:7230",
      "asset_id": "AST-078F4DCD016AEFDA1362",
      "video_id": 335,
      "timestamp": 482.0,
      "duration_seconds": 462.094667
    },
    {
      "frame_id": "AST-078F4DCD016AEFDA1362:7245",
      "asset_id": "AST-078F4DCD016AEFDA1362",
      "video_id": 335,
      "timestamp": 483.0,
      "duration_seconds": 462.094667
    },
    {
      "frame_id": "AST-078F4DCD016AEFDA1362:7260",
      "asset_id": "AST-078F4DCD016AEFDA1362",
      "video_id": 335,
      "timestamp": 484.0,
      "duration_seconds": 462.094667
    },
    {
      "frame_id": "AST-078F4DCD016AEFDA1362:7275",
      "asset_id": "AST-078F4DCD016AEFDA1362",
      "video_id": 335,
      "timestamp": 485.0,
      "duration_seconds": 462.094667
    },
    {
      "frame_id": "AST-078F4DCD016AEFDA1362:7290",
      "asset_id": "AST-078F4DCD016AEFDA1362",
      "video_id": 335,
      "timestamp": 486.0,
      "duration_seconds": 462.094667
    },
    {
      "frame_id": "AST-078F4DCD016AEFDA1362:7305",
      "asset_id": "AST-078F4DCD016AEFDA1362",
      "video_id": 335,
      "timestamp": 487.0,
      "duration_seconds": 462.094667
    },
    {
      "frame_id": "AST-078F4DCD016AEFDA1362:7320",
      "asset_id": "AST-078F4DCD016AEFDA1362",
      "video_id": 335,
      "timestamp": 488.0,
      "duration_seconds": 462.094667
    },
    {
      "frame_id": "AST-078F4DCD016AEFDA1362:7335",
      "asset_id": "AST-078F4DCD016AEFDA1362",
      "video_id": 335,
      "timestamp": 489.0,
      "duration_seconds": 462.094667
    },
    {
      "frame_id": "AST-078F4DCD016AEFDA1362:7350",
      "asset_id": "AST-078F4DCD016AEFDA1362",
      "video_id": 335,
      "timestamp": 490.0,
      "duration_seconds": 462.094667
    },
    {
      "frame_id": "AST-078F4DCD016AEFDA1362:7365",
      "asset_id": "AST-078F4DCD016AEFDA1362",
      "video_id": 335,
      "timestamp": 491.0,
      "duration_seconds": 462.094667
    },
    {
      "frame_id": "AST-078F4DCD016AEFDA1362:7380",
      "asset_id": "AST-078F4DCD016AEFDA1362",
      "video_id": 335,
      "timestamp": 492.0,
      "duration_seconds": 462.094667
    },
    {
      "frame_id": "AST-078F4DCD016AEFDA1362:7395",
      "asset_id": "AST-078F4DCD016AEFDA1362",
      "video_id": 335,
      "timestamp": 493.0,
      "duration_seconds": 462.094667
    },
    {
      "frame_id": "AST-078F4DCD016AEFDA1362:7410",
      "asset_id": "AST-078F4DCD016AEFDA1362",
      "video_id": 335,
      "timestamp": 494.0,
      "duration_seconds": 462.094667
    },
    {
      "frame_id": "AST-078F4DCD016AEFDA1362:7425",
      "asset_id": "AST-078F4DCD016AEFDA1362",
      "video_id": 335,
      "timestamp": 495.0,
      "duration_seconds": 462.094667
    },
    {
      "frame_id": "AST-078F4DCD016AEFDA1362:7440",
      "asset_id": "AST-078F4DCD016AEFDA1362",
      "video_id": 335,
      "timestamp": 496.0,
      "duration_seconds": 462.094667
    },
    {
      "frame_id": "AST-078F4DCD016AEFDA1362:7455",
      "asset_id": "AST-078F4DCD016AEFDA1362",
      "video_id": 335,
      "timestamp": 497.0,
      "duration_seconds": 462.094667
    },
    {
      "frame_id": "AST-078F4DCD016AEFDA1362:7470",
      "asset_id": "AST-078F4DCD016AEFDA1362",
      "video_id": 335,
      "timestamp": 498.0,
      "duration_seconds": 462.094667
    },
    {
      "frame_id": "AST-078F4DCD016AEFDA1362:7485",
      "asset_id": "AST-078F4DCD016AEFDA1362",
      "video_id": 335,
      "timestamp": 499.0,
      "duration_seconds": 462.094667
    },
    {
      "frame_id": "AST-078F4DCD016AEFDA1362:7500",
      "asset_id": "AST-078F4DCD016AEFDA1362",
      "video_id": 335,
      "timestamp": 500.0,
      "duration_seconds": 462.094667
    },
    {
      "frame_id": "AST-078F4DCD016AEFDA1362:7515",
      "asset_id": "AST-078F4DCD016AEFDA1362",
      "video_id": 335,
      "timestamp": 501.0,
      "duration_seconds": 462.094667
    },
    {
      "frame_id": "AST-078F4DCD016AEFDA1362:7530",
      "asset_id": "AST-078F4DCD016AEFDA1362",
      "video_id": 335,
      "timestamp": 502.0,
      "duration_seconds": 462.094667
    },
    {
      "frame_id": "AST-078F4DCD016AEFDA1362:7545",
      "asset_id": "AST-078F4DCD016AEFDA1362",
      "video_id": 335,
      "timestamp": 503.0,
      "duration_seconds": 462.094667
    },
    {
      "frame_id": "AST-078F4DCD016AEFDA1362:7560",
      "asset_id": "AST-078F4DCD016AEFDA1362",
      "video_id": 335,
      "timestamp": 504.0,
      "duration_seconds": 462.094667
    },
    {
      "frame_id": "AST-078F4DCD016AEFDA1362:7575",
      "asset_id": "AST-078F4DCD016AEFDA1362",
      "video_id": 335,
      "timestamp": 505.0,
      "duration_seconds": 462.094667
    },
    {
      "frame_id": "AST-078F4DCD016AEFDA1362:7590",
      "asset_id": "AST-078F4DCD016AEFDA1362",
      "video_id": 335,
      "timestamp": 506.0,
      "duration_seconds": 462.094667
    },
    {
      "frame_id": "AST-078F4DCD016AEFDA1362:7605",
      "asset_id": "AST-078F4DCD016AEFDA1362",
      "video_id": 335,
      "timestamp": 507.0,
      "duration_seconds": 462.094667
    },
    {
      "frame_id": "AST-078F4DCD016AEFDA1362:7620",
      "asset_id": "AST-078F4DCD016AEFDA1362",
      "video_id": 335,
      "timestamp": 508.0,
      "duration_seconds": 462.094667
    },
    {
      "frame_id": "AST-078F4DCD016AEFDA1362:7635",
      "asset_id": "AST-078F4DCD016AEFDA1362",
      "video_id": 335,
      "timestamp": 509.0,
      "duration_seconds": 462.094667
    },
    {
      "frame_id": "AST-078F4DCD016AEFDA1362:7650",
      "asset_id": "AST-078F4DCD016AEFDA1362",
      "video_id": 335,
      "timestamp": 510.0,
      "duration_seconds": 462.094667
    },
    {
      "frame_id": "AST-078F4DCD016AEFDA1362:7665",
      "asset_id": "AST-078F4DCD016AEFDA1362",
      "video_id": 335,
      "timestamp": 511.0,
      "duration_seconds": 462.094667
    },
    {
      "frame_id": "AST-078F4DCD016AEFDA1362:7680",
      "asset_id": "AST-078F4DCD016AEFDA1362",
      "video_id": 335,
      "timestamp": 512.0,
      "duration_seconds": 462.094667
    },
    {
      "frame_id": "AST-078F4DCD016AEFDA1362:7695",
      "asset_id": "AST-078F4DCD016AEFDA1362",
      "video_id": 335,
      "timestamp": 513.0,
      "duration_seconds": 462.094667
    },
    {
      "frame_id": "AST-078F4DCD016AEFDA1362:7710",
      "asset_id": "AST-078F4DCD016AEFDA1362",
      "video_id": 335,
      "timestamp": 514.0,
      "duration_seconds": 462.094667
    },
    {
      "frame_id": "AST-078F4DCD016AEFDA1362:7725",
      "asset_id": "AST-078F4DCD016AEFDA1362",
      "video_id": 335,
      "timestamp": 515.0,
      "duration_seconds": 462.094667
    },
    {
      "frame_id": "AST-078F4DCD016AEFDA1362:7740",
      "asset_id": "AST-078F4DCD016AEFDA1362",
      "video_id": 335,
      "timestamp": 516.0,
      "duration_seconds": 462.094667
    },
    {
      "frame_id": "AST-078F4DCD016AEFDA1362:7755",
      "asset_id": "AST-078F4DCD016AEFDA1362",
      "video_id": 335,
      "timestamp": 517.0,
      "duration_seconds": 462.094667
    },
    {
      "frame_id": "AST-078F4DCD016AEFDA1362:7770",
      "asset_id": "AST-078F4DCD016AEFDA1362",
      "video_id": 335,
      "timestamp": 518.0,
      "duration_seconds": 462.094667
    },
    {
      "frame_id": "AST-078F4DCD016AEFDA1362:7785",
      "asset_id": "AST-078F4DCD016AEFDA1362",
      "video_id": 335,
      "timestamp": 519.0,
      "duration_seconds": 462.094667
    },
    {
      "frame_id": "AST-078F4DCD016AEFDA1362:7800",
      "asset_id": "AST-078F4DCD016AEFDA1362",
      "video_id": 335,
      "timestamp": 520.0,
      "duration_seconds": 462.094667
    },
    {
      "frame_id": "AST-078F4DCD016AEFDA1362:7815",
      "asset_id": "AST-078F4DCD016AEFDA1362",
      "video_id": 335,
      "timestamp": 521.0,
      "duration_seconds": 462.094667
    },
    {
      "frame_id": "AST-078F4DCD016AEFDA1362:7830",
      "asset_id": "AST-078F4DCD016AEFDA1362",
      "video_id": 335,
      "timestamp": 522.0,
      "duration_seconds": 462.094667
    },
    {
      "frame_id": "AST-078F4DCD016AEFDA1362:7845",
      "asset_id": "AST-078F4DCD016AEFDA1362",
      "video_id": 335,
      "timestamp": 523.0,
      "duration_seconds": 462.094667
    },
    {
      "frame_id": "AST-078F4DCD016AEFDA1362:7860",
      "asset_id": "AST-078F4DCD016AEFDA1362",
      "video_id": 335,
      "timestamp": 524.0,
      "duration_seconds": 462.094667
    },
    {
      "frame_id": "AST-078F4DCD016AEFDA1362:7875",
      "asset_id": "AST-078F4DCD016AEFDA1362",
      "video_id": 335,
      "timestamp": 525.0,
      "duration_seconds": 462.094667
    },
    {
      "frame_id": "AST-078F4DCD016AEFDA1362:7890",
      "asset_id": "AST-078F4DCD016AEFDA1362",
      "video_id": 335,
      "timestamp": 526.0,
      "duration_seconds": 462.094667
    },
    {
      "frame_id": "AST-078F4DCD016AEFDA1362:7905",
      "asset_id": "AST-078F4DCD016AEFDA1362",
      "video_id": 335,
      "timestamp": 527.0,
      "duration_seconds": 462.094667
    },
    {
      "frame_id": "AST-078F4DCD016AEFDA1362:7920",
      "asset_id": "AST-078F4DCD016AEFDA1362",
      "video_id": 335,
      "timestamp": 528.0,
      "duration_seconds": 462.094667
    },
    {
      "frame_id": "AST-078F4DCD016AEFDA1362:7935",
      "asset_id": "AST-078F4DCD016AEFDA1362",
      "video_id": 335,
      "timestamp": 529.0,
      "duration_seconds": 462.094667
    },
    {
      "frame_id": "AST-078F4DCD016AEFDA1362:7950",
      "asset_id": "AST-078F4DCD016AEFDA1362",
      "video_id": 335,
      "timestamp": 530.0,
      "duration_seconds": 462.094667
    },
    {
      "frame_id": "AST-078F4DCD016AEFDA1362:7965",
      "asset_id": "AST-078F4DCD016AEFDA1362",
      "video_id": 335,
      "timestamp": 531.0,
      "duration_seconds": 462.094667
    },
    {
      "frame_id": "AST-078F4DCD016AEFDA1362:7980",
      "asset_id": "AST-078F4DCD016AEFDA1362",
      "video_id": 335,
      "timestamp": 532.0,
      "duration_seconds": 462.094667
    },
    {
      "frame_id": "AST-078F4DCD016AEFDA1362:7995",
      "asset_id": "AST-078F4DCD016AEFDA1362",
      "video_id": 335,
      "timestamp": 533.0,
      "duration_seconds": 462.094667
    },
    {
      "frame_id": "AST-078F4DCD016AEFDA1362:8010",
      "asset_id": "AST-078F4DCD016AEFDA1362",
      "video_id": 335,
      "timestamp": 534.0,
      "duration_seconds": 462.094667
    },
    {
      "frame_id": "AST-078F4DCD016AEFDA1362:8025",
      "asset_id": "AST-078F4DCD016AEFDA1362",
      "video_id": 335,
      "timestamp": 535.0,
      "duration_seconds": 462.094667
    },
    {
      "frame_id": "AST-078F4DCD016AEFDA1362:8040",
      "asset_id": "AST-078F4DCD016AEFDA1362",
      "video_id": 335,
      "timestamp": 536.0,
      "duration_seconds": 462.094667
    },
    {
      "frame_id": "AST-078F4DCD016AEFDA1362:8055",
      "asset_id": "AST-078F4DCD016AEFDA1362",
      "video_id": 335,
      "timestamp": 537.0,
      "duration_seconds": 462.094667
    },
    {
      "frame_id": "AST-078F4DCD016AEFDA1362:8070",
      "asset_id": "AST-078F4DCD016AEFDA1362",
      "video_id": 335,
      "timestamp": 538.0,
      "duration_seconds": 462.094667
    },
    {
      "frame_id": "AST-078F4DCD016AEFDA1362:8085",
      "asset_id": "AST-078F4DCD016AEFDA1362",
      "video_id": 335,
      "timestamp": 539.0,
      "duration_seconds": 462.094667
    },
    {
      "frame_id": "AST-078F4DCD016AEFDA1362:8100",
      "asset_id": "AST-078F4DCD016AEFDA1362",
      "video_id": 335,
      "timestamp": 540.0,
      "duration_seconds": 462.094667
    },
    {
      "frame_id": "AST-078F4DCD016AEFDA1362:8115",
      "asset_id": "AST-078F4DCD016AEFDA1362",
      "video_id": 335,
      "timestamp": 541.0,
      "duration_seconds": 462.094667
    },
    {
      "frame_id": "AST-078F4DCD016AEFDA1362:8130",
      "asset_id": "AST-078F4DCD016AEFDA1362",
      "video_id": 335,
      "timestamp": 542.0,
      "duration_seconds": 462.094667
    },
    {
      "frame_id": "AST-078F4DCD016AEFDA1362:8145",
      "asset_id": "AST-078F4DCD016AEFDA1362",
      "video_id": 335,
      "timestamp": 543.0,
      "duration_seconds": 462.094667
    },
    {
      "frame_id": "AST-078F4DCD016AEFDA1362:8160",
      "asset_id": "AST-078F4DCD016AEFDA1362",
      "video_id": 335,
      "timestamp": 544.0,
      "duration_seconds": 462.094667
    },
    {
      "frame_id": "AST-078F4DCD016AEFDA1362:8175",
      "asset_id": "AST-078F4DCD016AEFDA1362",
      "video_id": 335,
      "timestamp": 545.0,
      "duration_seconds": 462.094667
    },
    {
      "frame_id": "AST-078F4DCD016AEFDA1362:8190",
      "asset_id": "AST-078F4DCD016AEFDA1362",
      "video_id": 335,
      "timestamp": 546.0,
      "duration_seconds": 462.094667
    },
    {
      "frame_id": "AST-078F4DCD016AEFDA1362:8205",
      "asset_id": "AST-078F4DCD016AEFDA1362",
      "video_id": 335,
      "timestamp": 547.0,
      "duration_seconds": 462.094667
    },
    {
      "frame_id": "AST-078F4DCD016AEFDA1362:8220",
      "asset_id": "AST-078F4DCD016AEFDA1362",
      "video_id": 335,
      "timestamp": 548.0,
      "duration_seconds": 462.094667
    },
    {
      "frame_id": "AST-078F4DCD016AEFDA1362:8235",
      "asset_id": "AST-078F4DCD016AEFDA1362",
      "video_id": 335,
      "timestamp": 549.0,
      "duration_seconds": 462.094667
    },
    {
      "frame_id": "AST-078F4DCD016AEFDA1362:8250",
      "asset_id": "AST-078F4DCD016AEFDA1362",
      "video_id": 335,
      "timestamp": 550.0,
      "duration_seconds": 462.094667
    },
    {
      "frame_id": "AST-078F4DCD016AEFDA1362:8265",
      "asset_id": "AST-078F4DCD016AEFDA1362",
      "video_id": 335,
      "timestamp": 551.0,
      "duration_seconds": 462.094667
    },
    {
      "frame_id": "AST-078F4DCD016AEFDA1362:8280",
      "asset_id": "AST-078F4DCD016AEFDA1362",
      "video_id": 335,
      "timestamp": 552.0,
      "duration_seconds": 462.094667
    },
    {
      "frame_id": "AST-078F4DCD016AEFDA1362:8295",
      "asset_id": "AST-078F4DCD016AEFDA1362",
      "video_id": 335,
      "timestamp": 553.0,
      "duration_seconds": 462.094667
    },
    {
      "frame_id": "AST-078F4DCD016AEFDA1362:8310",
      "asset_id": "AST-078F4DCD016AEFDA1362",
      "video_id": 335,
      "timestamp": 554.0,
      "duration_seconds": 462.094667
    },
    {
      "frame_id": "AST-078F4DCD016AEFDA1362:8325",
      "asset_id": "AST-078F4DCD016AEFDA1362",
      "video_id": 335,
      "timestamp": 555.0,
      "duration_seconds": 462.094667
    },
    {
      "frame_id": "AST-078F4DCD016AEFDA1362:8340",
      "asset_id": "AST-078F4DCD016AEFDA1362",
      "video_id": 335,
      "timestamp": 556.0,
      "duration_seconds": 462.094667
    },
    {
      "frame_id": "AST-078F4DCD016AEFDA1362:8355",
      "asset_id": "AST-078F4DCD016AEFDA1362",
      "video_id": 335,
      "timestamp": 557.0,
      "duration_seconds": 462.094667
    },
    {
      "frame_id": "AST-0AF77D4817E2C7D21ED6:5640",
      "asset_id": "AST-0AF77D4817E2C7D21ED6",
      "video_id": 196,
      "timestamp": 282.0,
      "duration_seconds": 281.191056
    },
    {
      "frame_id": "AST-1D065EE2217432F15E45:36020",
      "asset_id": "AST-1D065EE2217432F15E45",
      "video_id": 234,
      "timestamp": 1801.0,
      "duration_seconds": 1800.112855
    },
    {
      "frame_id": "AST-1D065EE2217432F15E45:36040",
      "asset_id": "AST-1D065EE2217432F15E45",
      "video_id": 234,
      "timestamp": 1802.0,
      "duration_seconds": 1800.112855
    }
  ],
  "truncated": 27593
}
```

## 最终结论

存在关键检查失败或跳过，不能切换 Web 搜索索引。
