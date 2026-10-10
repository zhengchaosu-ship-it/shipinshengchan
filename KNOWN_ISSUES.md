# 已知问题和技术债 (KNOWN_ISSUES.md)

### 2026-10-07 17:49：2060独立真实发布追加验收PASS

`REAL_PROVIDER_PUBLISH_ON_2060_PASS`。用户新增最多1条正式任务授权后，实时核验夏禾OPEN/ONLINE，选择尚无PublishJob的READY成片 `STARTUP-94affa8d-6268-4e22-adaf-58f81f8d4929`。2060全片复验通过，新Export=0；新PublishJob `4026d43a-b45d-4ec2-9bae-b1564d3d350f` 由2060本地视频直接上传，视频/封面各1次、正式POST=1。官方scheduled/success，Task `6ac613e9799bed4c0357c33b`、Video ID `7693858927401848099`；Server已回写SCHEDULED_QUEUED，排期2026-10-08 09:08 +08，尚非公开PUBLISHED。

Server上传0且保持DISABLED；活动48次Mutex采样全持锁、最大执行并发1、无Render重叠；本轮没有同期Render，WAIT未重测。历史296条PublishJob/58条ProviderJob及6授权逐行未改，长期托管仍全部关闭；旧夏竹花开风险失败任务未重发。一次完成后停止真实测试，Worker READY、租约释放。详情及16项报告 `media_execution/runtime/real_provider_validation_20261007_additional/REPORT.md`，本条为最新状态，下方此前FAILED_ACCOUNT_RISK记录保留为上一次验收历史。


### 2026-10-07：Render/Publish执行交接完成；一次真实发布返回账号风险

`RENDER_PUBLISH_2060S_EXECUTION_HANDOFF_READY`。原Planner/ProviderStore/8502/常驻Coordinator/Recovery/Archive已正式接线，2060已部署并READY，Server上传执行器已在验收通过后DISABLED。此前“仅隔离原型/未部署”的描述已失效。10次剪映真导出、5次Mock提交、5个风险等待，单槽、非阻塞、提交后崩溃只读恢复和10份归档通过。

独立验收结果是 `REAL_PROVIDER_PUBLISH_VALIDATION = FAILED_ACCOUNT_RISK`：6份长期托管授权仍停用。初验时4个账号需要官方风险/Creator Center验证；后续真实发布及两账号验证恢复见下。只有稳定账号映射、账号门OPEN、Provider ONLINE且无官方验证要求后，才可按用户授权做最多1个全新正式PublishJob；不得重发任何历史Job。该项不阻塞执行交接READY。

已修复现场安装/剪映问题：PowerShell UNC ProviderPath、RUNTIME_PASS不等于完整安装成功、Task Scheduler残留venv子进程、前台焦点切换必须重新捕获UI、剪映环境检测成功后才记录已处理。对已核实版本/弹窗的有限处理可自动继续；未知弹窗仍需最少人工动作。旧夏禾成片本轮复验通过，未重复Export。不要通过改数据库或删除闩锁恢复生产任务。

运行边界：必须保持2060交互登录及蚁小二客户端，Worker进程/Server服务重启已验证，整机重启未做。真实Provider执行能力不能由Mock或7账号ONLINE缓存推定。已有Export闩锁却无有效MP4时原任务转待检查；不猜测导出结果。Archive不自动删除本机成片。恢复旧执行任务前先检查租约与重进程；不能同时启用第二个Publisher，也不能整体回滚operations.db覆盖其它业务。

本任务历史PublishJob修改0；旧后台持续对账更新21条Provider遥测/对账行，禁止宣称全部历史表hash不变。IMPLEMENTED/WIRED/DEPLOYED/VALIDATED均PASS；完整证据与23项结果见 `media_execution/runtime/finalization_20261007/REPORT.md`。

本轮追加真实发布验收：用户指定“夏竹花开”并确认已完成官方验证。实时CLI核验稳定账号 `6ac4b574faa99a4ec8670bb3` 后，选用其尚未创建PublishJob或提交的既有成片 `STARTUP-3d90a6f4-5783-468f-80c3-d1d55c86b7af`（122.033秒），2060复验SHA/全片decode通过、与已有归档相同，新增Export=0。按原额度和时段创建唯一新PublishJob `f69e3602-e088-47ec-b9a5-6a27f92dd062`，计划10月8日09:18，未重新开启长期托管。

2060本机真实上传视频1次、封面1次，validate与LOCAL dry-run通过，正式POST恰好1次。Provider TaskSet `0ee25a0c-775a-4dc0-87d1-a6e3251ee82f`、Task `6ac607c1e888b10a7efba166` 返回新的官方账号风险失败：仍要求到创作者中心单独发布并完成验证。Job为FAILED、无Video ID、没有成功进入平台定时队列；不能将预定10月8日09:18描述为已经安排成功。收到失败回执时账号重新BLOCKED_RISK，原任务不重发；用户随后再次确认验证后的账号状态见下。**REAL_PROVIDER_PUBLISH_VALIDATION = FAILED_ACCOUNT_RISK**，执行交接状态仍为READY。

实测补齐客户端异步执行保护：CLI返回任务ID后，2060继续持有执行槽/Mutex/busy直到只读回执确认定时队列或失败；Worker中断后，Server对未确认结束的Provider执行保留重任务门，禁止另一个Render/Publish或Archive进入。只读终态确认后才释放；账号失败只封该账号。另修复单独手工确认的新计划不被旧托管暂停错误阻断，以及LocalOperator预览和已核验恢复门的保持。60项最终本机回归通过；最终代码部署到2060并重新校验297个代码文件SHA，节点专项结果见node-provider-final.stderr.txt。

真实验收前后逐行对比：原295条PublishJob、57条ProviderJob及6份长期授权完全相同；仅新增上述1个PublishJob/ProviderJob。最终计数PublishJob296、ProviderJob58、submit_attempt总51（新增1）；长期托管enabled=0。切换主体阶段旧后台曾更新21条Provider遥测/对账行，独立记录。最终证据 `media_execution/runtime/finalization_20261007/FINAL_AUDIT.json`；官方CLI证据 `outputs/lan_render/2060_acceptance_20261007_v2/real-provider-evidence/`。

用户随后再次明确“夏竹花开和夏禾，完成了验证”。2026-10-07 17:28（Asia/Shanghai），2060官方CLI doctor及账号查询通过：两者稳定ID匹配、ONLINE、未冻结/锁定。原后台只读恢复请求均CHECKED，账号门恢复OPEN；6份长期托管授权保持enabled=0、旧失败Job和POST=1保留。此次复查新增PublishJob/Upload/Submit均0，不把账号门OPEN描述为真实发布已成功。本轮最多1个新正式PublishJob的额度已使用；若另做真实验收，须有追加范围授权。证据 `two_accounts_recovery.json` 与 `FINAL_AUDIT.json`。

> 项目：视频素材检索工具
> 最后更新：2026-09-26

---

## 严重问题（影响核心功能）

### ISSUE-001: 数据库文件不一致

**状态（2026-09-26）**：日常三个入口已修复，历史工具仍需逐项核对。

**原问题**:
- video_search.py、add_new_videos.py、build_faiss.py 原来都使用 `video_index.db`。
- full_process_and_shutdown.py、batch_add_d_material.py 使用 `video_index_fixed.db`。
- 网页文字搜索和统计读旧库；图搜候选来自现有 FAISS，不能简单断言所有 D 盘图搜都不可见。

**原因**: 
- 旧video_index.db曾出现"attempt to write a readonly database"错误
- 复制为video_index_fixed.db后恢复，但主程序路径未同步修改

**已完成**:
- 新增 database.py，将网页、日常增量录入和独立 FAISS 构建统一到项目目录下的主库。
- 查询默认只读；写入须显式选择。目标库缺失时禁止创建空库或回退旧库。
- 保留两个数据库原文件，未迁移数据、未重建索引。

**路径清理补充**：所有源码路径现从 config.py/config.json 读取；历史工具保留 legacy_database，初始化保留独立 init_database。统一配置不等于合并旧库和主库，也不修复 update_paths.py 的数据一致性问题。

**影响**: 高 - 新录入的视频在Web界面不可见

---

### ISSUE-002: 搜索速度慢（ORB匹配阶段）

**现象**: 
- 以图搜视频需要3-10秒
- 瓶颈在对20个候选逐个打开大视频文件seek抽帧

**原因**: 
- FAISS粗筛后，每个候选都要cv2.VideoCapture打开视频→seek到时间点→read一帧→release
- 视频文件大（几个GB），seek操作慢
- 缩略图只生成了0.66%（10448/1591127）

**临时解决**: 
- 缩略图生成脚本在后台运行中，生成完后搜索会快很多
- 已将候选从40减到20，ORB特征点从800减到500

**影响**: 中 - 用户体验差，但功能可用

---

### ISSUE-003: GPU完全未使用

**更新（2026-09-26，P1-1）**：独立 `.venv-cuda-test` 已用 Python 3.14.7 + PyTorch 2.11.0+cu128 成功运行 RTX 3060。100 张合成图的原 MobileNetV2 推理，GPU 中位耗时 1.126 秒、同环境 CPU 2.660 秒，数值一致性通过。生产环境仍为 CPU，本次没有接入 GPU。以下“最高支持 Python 3.12”的说法为过时历史判断。完整记录见 [CUDA_TEST.md](CUDA_TEST.md)。

**现象**: 
- RTX 3060 12GB闲置，所有计算在CPU
- 抽帧和字幕转写速度慢

**原因**: 
- PyTorch是CPU版(2.14.0+cpu)
- Python 3.14太新，PyTorch CUDA版最高支持Python 3.12
- 多次尝试安装cu121/cu118均失败

**临时解决**: 
- 无。继续用CPU跑。
- 未来换Python 3.12环境可启用GPU

**影响**: 中 - 处理速度慢，但功能正确

---

## 中等问题（影响特定场景）

### ISSUE-004: 人脸搜索功能极慢且路径错误

**更新（2026-09-26）**：模型路径已接入统一配置并通过加载测试；下面路径错误描述是修复前情况。全库遍历和准确率问题未改。

**现象**: 
- Tab6"找这个人"上传人脸后，全库遍历159万帧，每帧都要开视频抽帧+人脸检测+识别
- 预计需要数小时
- 人脸模型路径硬编码为 `C:\video_search_tool\models\`，项目已迁移到D盘，会报错

**原因**: 
- 设计为全库遍历，没有预计算人脸特征
- 路径硬编码

**临时解决**: 
- 不使用该功能
- 如需使用，先修改video_search.py第66-67行的路径为D盘

**影响**: 低 - 实验性功能，用户主要用Tab4以图搜视频

---

### ISSUE-005: config.json只支持单个素材目录

**路径清理补充（2026-09-26）**：原专用脚本目录已移入 material_folder 配置；主流程仍使用单个 video_folder，没有新增统一多目录扫描功能。下面为原问题记录。

**现象**: 
- config.json只有一个video_folder字段
- D盘素材是通过单独脚本录入的，不在配置中
- Web界面的"索引状态"只显示config.json里的目录

**原因**: 
- 最初设计为单目录，后续加了D盘素材但没扩展配置

**临时解决**: 
- 手动修改config.json，或用单独脚本处理D盘素材
- 搜索时两个目录的视频都在数据库里，都能搜到

**影响**: 低 - 功能不受影响，只是配置不完整

---

### ISSUE-006: 换背景/抠图后的视频匹配效果差

**现象**: 
- 用户核心需求是找别人剪辑过的切片（可能换背景、抠图、加特效）
- MobileNetV2全局特征受背景影响大，换背景后相似度下降明显
- ORB局部特征有帮助但不够

**原因**: 
- 全局特征包含大量背景信息
- 没有人物检测/ReID，无法聚焦人物
- ORB对大幅换背景也会失效

**临时解决**: 
- ORB权重设为最高(0.55)，一定程度缓解
- 镜像翻转已支持

**影响**: 中 - 核心需求场景准确率不够理想

---

### ISSUE-007: 无增量FAISS索引

**现象**: 
- 每次加新视频后必须全量重建FAISS索引
- 159万帧重建约需5分钟，加载7.6GB到内存

**原因**: 
- 使用IndexFlatIP，不支持增量add（实际上支持，但当前脚本是全量重建）
- 没有索引版本管理

**临时解决**: 
- 加新视频后手动运行build_faiss.py

**影响**: 低 - 重建时间可接受

---

### ISSUE-008: 视频删除后残留无效索引

**现象**: 
- 删除或移动视频后，数据库和FAISS里仍有对应记录
- 搜索可能返回已不存在的视频，缩略图加载失败

**原因**: 
- 没有视频删除/清理机制
- 没有路径有效性校验

**临时解决**: 
- 移动视频后用update_paths.py批量替换路径
- 删除视频后需手动清理数据库并重建FAISS

**影响**: 低 - 用户不常删视频

---

## 轻微问题（技术债）

### ISSUE-009: 硬编码路径

**状态（2026-09-26）**：运行源码路径已集中到 config.py/config.json，启动脚本通过 launch.ps1 读取配置；路径测试和小视频隔离流程验证通过。完整清单见 PATHS.md。下面为修复前位置记录，数据库内素材路径、历史备份和项目外的启动注册未改写。

**位置**:
- video_search.py第45行: `FFMPEG_DIR = r"C:\video_search_tool\bin"`
- video_search.py第66-67行: 人脸模型路径 `C:\video_search_tool\models\`
- video_search.py第372行: `THUMB_CACHE = Path(r"C:\video_search_tool\thumbnails")`
- build_faiss.py第4-6行: 硬编码D盘路径

**影响**: 迁移到其他电脑/路径时会出问题

---

### ISSUE-010: 全局变量非线程安全

**现象**: 
- `query_color_frame = None` 是全局变量
- extract_image_features()写入，search_similar_frames()读取
- Streamlit多用户/并发时可能串数据

**影响**: 单机单用户场景下无实际问题

---

### ISSUE-011: FRAME_INTERVAL值不一致

**现象**: 
- video_search.py第25行: `FRAME_INTERVAL = 10`（旧值，未使用）
- add_new_videos.py第20行: `FRAME_INTERVAL = 1`（实际建库用的）

**影响**: 容易误导开发者，实际以add_new_videos.py为准

---

### ISSUE-012: 废弃/临时文件未清理

**文件列表**:
- bug.png, bug2.png, bug3.png（历史截图）
- check_status.py, check_v2.py, find_0722.py, find_vid.py, list_videos.py（0字节空文件）
- resample_frames.py, fix_0719.py, fix_thumbs.py（历史修复脚本）
- scan_d_material.py, test_transcribe.py, gen_thumbnails.py（重复/历史脚本）
- auto_shutdown.ps1（历史关机脚本）
- _audit_db.py, _audit_versions.py, _versions.txt（本次审计临时文件）

**影响**: 项目目录混乱，不影响功能

---

### ISSUE-013: 缩略图生成慢

**现象**: 
- generate_thumbnails.py逐帧从视频seek抽帧
- 159万帧预计需要数十小时
- 当前只生成了0.66%

**原因**: 
- 每帧都要open→seek→read→release
- 没有按视频顺序批量处理

**优化方向**: 
- 按视频分组，每个视频只open一次，顺序读取所有需要的帧
- 多线程并行

---

### ISSUE-014: 无标准测试

**现象**: 
- 已新增数据库连接、缺失文件保护和文字检索的小数据库测试（tests/test_database.py）
- 没有集成测试
- 没有准确率benchmark
- 尚不能自动验证完整视觉检索链路和准确率

**影响**: 高风险修改容易引入bug

---

### ISSUE-015: 字幕转写可能失败

**现象**: 
- 某些视频转写失败时只打印错误，不重试
- 失败的视频没有字幕，但帧特征已录入
- 没有标记哪些视频转写失败

**原因**: 
- add_new_videos.py中try/except只捕获异常，不记录

**影响**: 部分视频无法文字搜索

---

### ISSUE-016: WAL模式不可用

**现象**: 
- 尝试启用SQLite WAL模式时报"unable to open database file"
- 并发写入时可能出现database is locked

**原因**: 
- 可能是数据库文件所在目录权限或文件系统问题

**临时解决**: 
- 使用timeout=120 + busy_timeout + 重试机制
- 避免同时运行多个写数据库的脚本

---

### ISSUE-017: 开机自启待验证

**现象**: 
- 计划任务+启动文件夹双保险已配置
- 启动脚本已改为完整Python路径
- 但尚未经过下次开机实际验证

**影响**: 待确认

---

### ISSUE-018: 历史特征混用，索引构建静默截断

**状态**：只读审查已确认，尚未修复或重算数据。

- 修复库 frames.id=1、2、3 的特征为 250,880 字节（62,720 维），最新抽查记录为 5,120 字节（1,280 维）。
- batch_transcribe.py 的旧提取实现没有 AdaptiveAvgPool2d，直接展平特征图；该入口还使用 10 秒间隔，且仍被网页的新增素材说明推荐。
- build_faiss.py 和完整处理脚本直接取前 1280 维。现有 FAISS 首向量与首条历史特征的截取结果逐字节一致，范数约 0.257606，不是单位向量。
- 影响范围与召回损失尚未量化。不能仅对截断向量重新归一化，也不能直接全库重建；必须保留现有索引，用小样本先验证处置方案。
- 此次只统一数据库目标，没有改变这些特征处理逻辑、模型、预处理或评分权重。

---

## 历史事故记录

### ACCIDENT-001: 144个视频0帧
- **时间**: 2026-09-24
- **原因**: 运行重采样脚本时用户说"你先停下"，脚本逻辑是先删旧帧再抽新帧，被叫停时144个视频已删帧但未重抽
- **解决**: 长时间补索引，多次遇到sqlite锁定/disk I/O error/MemoryError，最终改为每视频独立连接+timeout+重试全部补完

### ACCIDENT-002: 数据库只读错误
- **时间**: 2026-09-25
- **原因**: video_index.db出现"attempt to write a readonly database"，文件属性正常但无法写入
- **解决**: 复制为video_index_fixed.db后恢复正常

### ACCIDENT-003: PyTorch CUDA安装失败
- **时间**: 2026-09-25
- **原因**: Python 3.14太新，PyTorch CUDA版最高支持3.12，官方源和阿里云镜像都找不到匹配版本
- **解决**: 继续用CPU版，未解决

---

## 性能基线

| 指标 | 当前值 | 备注 |
|------|--------|------|
| 抽帧速度 | ~20倍实时 | CPU, MobileNetV2 FP32 |
| 转写速度 | ~20倍实时 | CPU, faster-whisper INT8 |
| FAISS搜索 | 200-500ms | 159万向量, IndexFlatIP |
| ORB精排 | 2-8秒 | 20候选, 无缩略图时 |
| 文字搜索 | ~100ms | SQL LIKE |
| 索引构建 | ~5分钟 | 159万帧 |
| 内存占用(搜索时) | ~10GB | FAISS 7.6GB + 其他 |
