# 独立素材资产扫描

扫描两个用户确认的本地目录及其子目录：

- `E:\备份\陶老师直播录制\妙手陶老师本人_3xr7zzgq96gpawe`
- `D:\素材`

仅读取文件系统属性、媒体容器/视频流头信息和全文件SHA-256，不抽帧、不生成图像特征、不修改FAISS或生产检索。没有导入生产建库脚本。媒体头探测使用已有环境中的PyAV，未安装依赖。

## 输出

本次输出目录：`asset_inventory/results/20260927_assets/`。

- `assets.db`：独立SQLite资产数据库，`videos`表保存每个视频资产；`scan_info`表保存扫描范围、状态、时间及目录访问异常。
- `summary.json`：素材数量、总字节数、总时长、重复组/副本数量、损坏或不可读数量、待复核数量及保护检查。
- `duplicates.json`：完整SHA-256相同的重复文件组和全部路径。
- `damaged_or_unreadable.json`：空文件、无法识别视频流、明确无效容器、全文件读取失败记录。
- `needs_review.json`：探测超时、未知探测错误、字段不完整、扫描期间变化等，不武断归类为损坏。
- `progress.json`：最近一次哈希进度，仅记录本轮剩余文件的处理情况。
- `protected_before.json`：生产代码、配置、数据库、生产FAISS及DINO实验源文件的大小/修改时间快照，用于结束时核验。

### 逻辑资产输出（2026-09-27）

在同一结果目录内，`build_logical_assets.py` 基于完整SHA-256建立独立逻辑层，不修改 `assets.db`：

- `logical_assets.db`：独立SQLite快照。`logical_assets` 每个SHA-256一行；`asset_files` 保留源 `videos` 表全部字段，并增加 `asset_id`、`is_primary`、`primary_rank`。还提供 `asset_map`、`primary_files`、`duplicate_groups` 三个视图。
- `asset_file_map.json`：388条 `asset_id → video_id / 路径 / 文件名 / 大小 / SHA-256` 映射。
- `logical_assets.json`：320个SHA逻辑组的摘要。
- `duplicate_groups_logical.json`：42个重复组的组内数量、全部文件路径和主文件标记。
- `primary_files.json`、`primary_files.csv`：319个可用逻辑资产的主文件候选完整列表。
- `logical_summary.json`、`logical_verification.json`、`逻辑资产报告.md`：统计、核验和中文报告。

`asset_id` 为 `AST-` 加SHA-256前20位大写十六进制，构建时检查短ID冲突；同一文件内容在后续快照中保持同一ID。主文件按以下固定顺序选择：可用非空视频、生产库已登记、路径副本标记更少、路径层级更浅、路径更短、video_id更小。它只是推荐标记，不移动或删除任何文件。

本次320个SHA组包括319个唯一可用视频素材和1个零字节空文件组。空文件组保留28条原记录，但不指定主文件。42个重复组中，41个非空组各2个文件，空文件组28个文件。

显式核验命令：

```powershell
& .\.venv-cuda-test\Scripts\python.exe -X utf8 -B asset_inventory/build_logical_assets.py --verify-only
```

核验包含数据库完整性、388条源字段逐字段一致、归组SHA/大小一致、主文件唯一性与规则重算、asset_id推导、源扫描库未变化和主文件路径存在性。

以 `summary.json` 中 `status=complete` 为扫描结束依据；进行中的库也会逐文件提交结果。目录读取错误会导致状态 `incomplete`，不会被误报为空目录或全部成功。

## 数据字段与统计口径

`video_id` 对原生产库已知完整路径复用原ID；本次新发现的文件从原ID最大值之后分配，并在独立库中持久保存。`production_video_id` 可为空，供区分已有和新资产。原生产库仅只读查询 `videos` 的ID/路径，不修改它。

其余字段包含 `file_path`、`file_name`、`root_path`、`size_bytes`、`duration_seconds`、`resolution`、`width`、`height`、`fps`及分数形式、`video_codec`、`container_format`、`created_at`、`modified_at`、`sha256`。还保存时长/FPS来源、媒体创建时间（如果存在）、状态和错误信息。

- 创建时间使用Windows文件系统birthtime，按UTC ISO8601保存；它是当前文件的创建时间，不保证是拍摄时间。媒体内嵌创建时间另列。
- 时长来自容器/视频流头信息，单位秒；未知值为NULL，不伪装成0。总时长是所有已知文件时长之和，**包含重复副本**；TS等文件的头部时长是估算，不保证等于完整可解码时长。
- 分辨率/FPS/编码取第一个非封面视频流。优先平均FPS，缺失时使用base_rate并记录来源；不是帧率恒定性的结论。
- SHA-256读取完整文件，不是首尾采样哈希。大小和修改时间在读取前、读取后及扫描结束时检查；变化文件的哈希作废，不参与重复统计。
- `duplicate_extra_copies` 是每组除一份保留副本外的重复数量，`duplicate_files_in_groups` 是所有参与重复组的文件数；`duplicate_group_count` 是组数。不删除任何副本。
- 零字节文件也有合法的SHA-256，内容相同的空文件会构成重复组；因此“重复”和“损坏/空文件”两类可重叠。最终中文报告另列非空重复副本与空文件重复副本，避免把空文件当作可用视频。
- **损坏检查只覆盖可读性、容器和视频流头探测，未进行全片解码**。无法排除文件中途损坏；单纯探测warning不直接计为损坏，错误和warning均保留供复核。
- 不跨越目录链接/junction，避免越出约定目录；跳过项会记入报告。当前按常见视频扩展名发现文件，本次两个目录没有其他扩展名文件。

## 显式运行与恢复

在项目根目录运行：

```powershell
& .\.venv-cuda-test\Scripts\python.exe -X utf8 -B asset_inventory/scan.py --output asset_inventory/results/20260927_assets
```

默认素材目录读取现有 `config.json`，不改写配置。新扫描可指定新的输出目录；已完成输出会直接返回，不重新读全文件。中断后同一命令复用原清单及已完成逐文件结果，仅继续pending项。若上次进程被强制终止导致 `scan.lock` 残留，必须先确认对应PID已经停止再手动移除锁，不能并行运行同一输出目录。

若需要扫描后来新增的文件，请使用**新的输出目录**；恢复命令只针对已保存的扫描快照。现有库先通过SQLite application_id识别，拒绝写入外来数据库，使用DELETE journal，不启用WAL。

## 验证

```powershell
& .\.venv-cuda-test\Scripts\python.exe -X utf8 -B -m unittest discover -s asset_inventory -p test_scan.py -v
```

6项小范围测试覆盖：完整哈希/重复与文件变化、重叠目录不重复计数、中文文件名/创建时间、缺失目录、外来库保护、统计口径、1秒合成视频的真实元数据以及损坏/空文件识别。测试用文件位于独立临时目录并在结束清理，不处理生产视频。

逻辑资产另有4项隔离测试，覆盖稳定asset_id、归组保留、主文件副本标记规则、空文件无主文件、源字段完整复制及外来目标库保护。合计10项资产测试。

手动核验可用SQLite浏览器只读打开 `assets.db`，查看以下查询：

```sql
SELECT video_id,file_path,size_bytes,duration_seconds,resolution,fps,video_codec,created_at,sha256
FROM videos ORDER BY video_id;

SELECT sha256,COUNT(*) AS file_count FROM videos
WHERE hash_status='ok' GROUP BY sha256 HAVING COUNT(*)>1;

SELECT video_id,file_path,probe_status,probe_error,hash_status,hash_error
FROM videos WHERE probe_status!='ok' OR hash_status!='ok';
```
