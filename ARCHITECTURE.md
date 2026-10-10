# 架构文档 (ARCHITECTURE.md)

### 2026-10-07 17:49：2060独立真实发布追加验收PASS

`REAL_PROVIDER_PUBLISH_ON_2060_PASS`。用户新增最多1条正式任务授权后，实时核验夏禾OPEN/ONLINE，选择尚无PublishJob的READY成片 `STARTUP-94affa8d-6268-4e22-adaf-58f81f8d4929`。2060全片复验通过，新Export=0；新PublishJob `4026d43a-b45d-4ec2-9bae-b1564d3d350f` 由2060本地视频直接上传，视频/封面各1次、正式POST=1。官方scheduled/success，Task `6ac613e9799bed4c0357c33b`、Video ID `7693858927401848099`；Server已回写SCHEDULED_QUEUED，排期2026-10-08 09:08 +08，尚非公开PUBLISHED。

Server上传0且保持DISABLED；活动48次Mutex采样全持锁、最大执行并发1、无Render重叠；本轮没有同期Render，WAIT未重测。历史296条PublishJob/58条ProviderJob及6授权逐行未改，长期托管仍全部关闭；旧夏竹花开风险失败任务未重发。一次完成后停止真实测试，Worker READY、租约释放。详情及16项报告 `media_execution/runtime/real_provider_validation_20261007_additional/REPORT.md`，本条为最新状态，下方此前FAILED_ACCOUNT_RISK记录保留为上一次验收历史。


### 2026-10-07媒体执行正式拓扑

`RENDER_PUBLISH_2060S_EXECUTION_HANDOFF_READY`。Server为CONTROL_PLANE：原DailyPlanner/CompositionPlanner产生原Content及RenderJob，正式ProductionControlPlane扫描原队列和ProviderStore，按稳定business_account_id/provider_account_id核验账号门、计算RUNNABLE集合及优先级，事务发放租约。2060为RENDER_AND_PUBLISH_EXECUTOR：原登录计划任务常驻Coordinator主动连接8766，统一Render/Export/Upload/Submit/只读对账。Server启动任务及Worker登录任务独立于Codex；剪映需要Windows交互登录会话。

执行槽固定1；Server事务租约 + `Global\WORKSTATION_MEDIA_EXECUTION_LOCK` + 进程内线程闩锁。eligible-set先过滤账号/Job/Infrastructure门，再按安全提交截止期排序，不按FIFO阻塞、不抢占。原ProviderStore的SUBMIT_INTENT/count与执行提交闩锁同事务落库；已提交或结果未知不得再次POST，只读对账。账号恢复经原Planner重新排期、每日最多5条与去重检查，不直接解锁过期排期。READY积压默认15。

原RenderJob完成后2060回传带SHA、ffprobe、全片decode及封面SHA的元数据；原Content READY、Plan Prepare/Preview/Confirm读取冻结回执，支持Server无本地MP4。生产发布路径为2060 local MP4 → 本机蚁小二 → Provider；Server上传执行器DISABLED，fallback代码保留且不被新Scheduler选择。后台归档另行单路限速，重任务忙时暂停，失败不修改Render/Publish结果，也不自动删除本机成片。

重启恢复必须先持有全局锁并证明旧执行器静止。已有有效MP4复验后完成原Job；无Export闩锁时恢复原任务；已触发Export却无有效输出则原Job待检查，禁止盲目二次导出。Job、Account、Publisher Infrastructure、Archive各自隔离。8502正式面板从生产库读取Worker、执行槽、当前任务、队列、账号门、基础设施和归档状态。

IMPLEMENTED/WIRED/DEPLOYED/VALIDATED均PASS：2060真实10 Render + 10 Mock Publish（5可执行、5风险等待），最大重任务1、队首阻塞0，真实进程中断与Server服务重启恢复通过。REAL_PROVIDER_VALIDATED未通过，一次真实发布返回账号风险；切换主体初验未做真实发布，整机重启仍未做。详见 `media_execution/runtime/finalization_20261007/REPORT.md`。

本轮追加真实发布验收：用户指定“夏竹花开”并确认已完成官方验证。实时CLI核验稳定账号 `6ac4b574faa99a4ec8670bb3` 后，选用其尚未创建PublishJob或提交的既有成片 `STARTUP-3d90a6f4-5783-468f-80c3-d1d55c86b7af`（122.033秒），2060复验SHA/全片decode通过、与已有归档相同，新增Export=0。按原额度和时段创建唯一新PublishJob `f69e3602-e088-47ec-b9a5-6a27f92dd062`，计划10月8日09:18，未重新开启长期托管。

2060本机真实上传视频1次、封面1次，validate与LOCAL dry-run通过，正式POST恰好1次。Provider TaskSet `0ee25a0c-775a-4dc0-87d1-a6e3251ee82f`、Task `6ac607c1e888b10a7efba166` 返回新的官方账号风险失败：仍要求到创作者中心单独发布并完成验证。Job为FAILED、无Video ID、没有成功进入平台定时队列；不能将预定10月8日09:18描述为已经安排成功。收到失败回执时账号重新BLOCKED_RISK，原任务不重发；用户随后再次确认验证后的账号状态见下。**REAL_PROVIDER_PUBLISH_VALIDATION = FAILED_ACCOUNT_RISK**，执行交接状态仍为READY。

实测补齐客户端异步执行保护：CLI返回任务ID后，2060继续持有执行槽/Mutex/busy直到只读回执确认定时队列或失败；Worker中断后，Server对未确认结束的Provider执行保留重任务门，禁止另一个Render/Publish或Archive进入。只读终态确认后才释放；账号失败只封该账号。另修复单独手工确认的新计划不被旧托管暂停错误阻断，以及LocalOperator预览和已核验恢复门的保持。60项最终本机回归通过；最终代码部署到2060并重新校验297个代码文件SHA，节点专项结果见node-provider-final.stderr.txt。

真实验收前后逐行对比：原295条PublishJob、57条ProviderJob及6份长期授权完全相同；仅新增上述1个PublishJob/ProviderJob。最终计数PublishJob296、ProviderJob58、submit_attempt总51（新增1）；长期托管enabled=0。切换主体阶段旧后台曾更新21条Provider遥测/对账行，独立记录。最终证据 `media_execution/runtime/finalization_20261007/FINAL_AUDIT.json`；官方CLI证据 `outputs/lan_render/2060_acceptance_20261007_v2/real-provider-evidence/`。

用户随后再次明确“夏竹花开和夏禾，完成了验证”。2026-10-07 17:28（Asia/Shanghai），2060官方CLI doctor及账号查询通过：两者稳定ID匹配、ONLINE、未冻结/锁定。原后台只读恢复请求均CHECKED，账号门恢复OPEN；6份长期托管授权保持enabled=0、旧失败Job和POST=1保留。此次复查新增PublishJob/Upload/Submit均0，不把账号门OPEN描述为真实发布已成功。本轮最多1个新正式PublishJob的额度已使用；若另做真实验收，须有追加范围授权。证据 `two_accounts_recovery.json` 与 `FINAL_AUDIT.json`。

> 项目：视频素材检索工具
> 最后更新：2026-09-26

---

## 1. 系统总览

**统一路径入口（2026-09-26）**：config.py 读取 config.json，所有项目相对路径以项目目录为基准；主库、旧库、模型、索引、FFmpeg、缓存和日志各有配置项。database.py 保留已有连接保护；launch.ps1 让两个原有 BAT 入口从任意工作目录启动。详见 PATHS.md。

本项目是一个单机运行的本地视频检索系统，无客户端-服务器分离，无外部API依赖，所有计算在本地完成。

```
┌─────────────────────────────────────────────────────┐
│                   Streamlit Web UI                   │
│  (设置 / 索引状态 / 文字搜索 / 以图搜 / OCR / 人脸)  │
└──────────────┬──────────────────┬───────────────────┘
               │                  │
    ┌──────────▼──────┐  ┌───────▼──────────┐
    │   搜索引擎       │  │   建库引擎        │
    │  (search)       │  │  (indexing)      │
    │                 │  │                  │
    │  FAISS粗筛      │  │  视频扫描         │
    │  ORB精排        │  │  抽帧             │
    │  pHash/颜色     │  │  特征提取         │
    │  字幕搜索       │  │  字幕转写         │
    └──────────┬──────┘  └───────┬──────────┘
               │                  │
    ┌──────────▼──────────────────▼──────────┐
    │         SQLite + FAISS + 模型文件        │
    │  video_index_fixed.db / faiss_index.bin│
    │  models/ (MobileNetV2权重在线下载)      │
    └─────────────────────────────────────────┘
```

---

## 2. 核心模块

### 2.1 视觉特征模块 (vision)

**文件**: video_search.py 中 `load_feature_model()`, `extract_image_features()`

**模型**: MobileNetV2 (torchvision预训练, ImageNet)
- 去掉最后分类层
- 追加 AdaptiveAvgPool2d(1)
- 输出: 1280维向量
- 设备: CPU (torch 2.14.0+cpu)
- 精度: FP32

**预处理流水线**:
```
BGR帧 → cv2.cvtColor(BGR2RGB) → PIL Image → 
transforms.Resize((224,224)) → ToTensor → 
Normalize(mean=[0.485,0.456,0.406], std=[0.229,0.224,0.225]) → 
MobileNetV2 → flatten → L2 normalize → float32
```

**辅助特征**:
- pHash: 32x32灰度DCT，8x8低频二值化，64位
- HSV颜色直方图: 12x8 bins，96维
- ORB: 500特征点，BFMatcher crossCheck，距离<50为好匹配

### 2.2 索引模块 (indexing)

**文件**: add_new_videos.py, build_faiss.py, init_database.py

**流程**:
```
os.walk扫描目录 → 对比数据库已有路径 → 新视频列表
  ↓
对每个视频:
  cv2.VideoCapture → 获取fps/duration
  INSERT videos
  逐帧读取 → 每1秒1帧 → MobileNetV2特征 → INSERT frames (每20帧批量)
  faster-whisper转写 → INSERT subtitles
  ↓
build_faiss.py:
  分批加载frames表 → numpy矩阵(N,1280) → faiss.IndexFlatIP → 保存
```

**关键参数**:
- 抽帧间隔: 1秒 (FRAME_INTERVAL=1 in add_new_videos.py)
- 批量插入: 20帧/批
- 数据库超时: 120秒，busy_timeout=120000，synchronous=OFF
- FAISS批次加载: 10000帧/批

### 2.3 搜索模块 (search)

**文件**: video_search.py 中 `search_similar_frames()`, `search_by_keyword()`

**以图搜视频流程**:
```
上传截图 → extract_image_features() → (1280维, pHash, 颜色直方图, 原始BGR)
  ↓
FAISS粗筛: index.search(query, 20) → 20候选 (file_path, file_name, timestamp, sim_mobi)
  ↓
批量查询video_id (SELECT id FROM videos WHERE file_path=?)
  ↓
对每个候选:
  load_frame_for_matching() → 优先读缩略图，否则开视频seek抽帧
  ORB匹配(原图+镜像) → orb_score
  pHash汉明距离 → sim_phash
  颜色直方图相关 → sim_color
  综合得分 = min(orb/30,1)*0.55 + phash*0.2 + color*0.15 + mobi*0.1
  ↓
过滤得分>0.2 → 排序 → Top10返回
```

**文字搜索**:
```
关键词 → SQL LIKE '%keyword%' ON subtitles.text → JOIN videos → 返回时间戳和台词
```

### 2.4 Web模块 (web)

**文件**: video_search.py (Streamlit单文件)

**6个标签页**:
1. ⚙️ 设置 - 素材路径、路径修复、繁简转换
2. 📊 索引状态 - 视频/字幕/帧数统计
3. 🔍 文字搜索 - 关键词搜字幕
4. 🖼️ 以图搜视频 - 上传截图搜索
5. 📝 截图OCR - 识别文字后搜字幕
6. 🧑 找这个人 - 人脸搜索（实验性，全库遍历极慢）

**缓存机制**:
- @st.cache_resource: MobileNetV2模型、FAISS索引、OCR模型、Whisper模型（只加载一次）
- 全局变量query_color_frame: 保存查询图原始BGR供ORB使用（注意：这不是线程安全的）

---

## 3. 数据存储架构

### 3.1 SQLite (video_index_fixed.db, 32.3GB)

```
videos (360行)
  ├── id INTEGER PK
  ├── file_path TEXT UNIQUE
  ├── file_name TEXT
  ├── duration REAL
  └── processed_at TEXT

frames (1,591,127行)
  ├── id INTEGER PK
  ├── video_id INTEGER → videos.id
  ├── timestamp REAL (秒)
  └── features BLOB (1280*4=5120字节/行)

subtitles (1,062,422行)
  ├── id INTEGER PK
  ├── video_id INTEGER → videos.id
  ├── start REAL (秒)
  ├── end REAL (秒)
  └── text TEXT
```

**注意**: 存在两个数据库文件：
- `video_index.db` (30.7GB) - 旧库，曾出现"attempt to write a readonly database"错误
- `video_index_fixed.db` (32.3GB) - 当前主用，是旧库的复制修复版
- 2026-09-26 起，video_search.py、add_new_videos.py、build_faiss.py 通过 database.py 统一使用 `video_index_fixed.db`，查询默认只读，写入显式开启；文件缺失时不会创建空库。
- 其他历史脚本仍可能使用旧库，尚未全项目统一。
- 生产 frames 表还有历史 `thumbnail TEXT DEFAULT ''` 列。存量特征并非全部 5120 字节，已发现 62,720 维历史记录；见 KNOWN_ISSUES.md 的 ISSUE-018。

### 3.2 FAISS (faiss_index.bin, 7.59GB)

- 类型: IndexFlatIP (暴力内积搜索)
- 维度: 1280
- 向量数: 1,591,127
- 元数据: faiss_meta.pkl (270MB), Python list of (file_path, file_name, timestamp)
- 对应关系: faiss_meta[i] ↔ index第i个向量

### 3.3 缩略图 (thumbnails/, 生成中)

- 命名: {video_id}_{timestamp:.1f}.jpg
- 尺寸: 宽320px，等比缩放
- 质量: JPEG 70
- 用途: 搜索时ORB匹配优先读缩略图，避免开大视频seek
- 进度: 10,448 / 1,591,127 (0.66%)

---

## 4. 模型架构

### 4.1 MobileNetV2 (画面特征)
- 来源: torchvision.models.mobilenet_v2(weights=DEFAULT)
- 权重: ImageNet预训练，首次运行自动下载到缓存
- 修改: 去掉classifier，追加AdaptiveAvgPool2d(1)
- 输出: 1280维
- **注意**: 权重不包含在models/目录中，依赖torchvision自动下载。离线环境需提前缓存

### 4.2 faster-whisper (语音转字幕)
- 模型: base (约138MB)
- 文件: models/model.bin, config.json, tokenizer.json, vocabulary.txt
- 后端: CTranslate2 (INT8量化)
- 设备: CPU
- 语言: 中文 (language="zh")
- beam_size: 1

### 4.3 RapidOCR (截图文字识别)
- 库: rapidocr-onnxruntime
- 模型: 内置，无需额外文件
- 后端: ONNX Runtime

### 4.4 YuNet + SFace (人脸，实验性)
- 检测: models/face_detection_yunet.onnx (227KB)
- 识别: models/face_recognition_sface.onnx (37MB)
- 加载: cv2.FaceDetectorYN_create / cv2.FaceRecognizerSF_create
- 阈值: 检测0.7，识别余弦相似度>0.45
- **路径已修复**: 从统一配置读取两个模型文件；检测、识别算法和阈值未改。

---

## 5. 接口和调用关系

### 5.1 内部函数调用图

```
video_search.py (Streamlit入口)
├── load_config() / save_config()
├── load_feature_model() [缓存]
│   └── extract_image_features(img_bgr) → (feat, phash, color_hist)
├── load_faiss_index() [缓存]
│   └── search_similar_frames(feat, phash, color, top_k) → results[]
│       ├── faiss_index.search() → 20候选
│       ├── load_frame_for_matching() → 帧图像
│       ├── match_orb_features() → orb_score
│       ├── calc_phash() / hamming_dist()
│       └── calc_color_hist() / cv2.compareHist()
├── search_by_keyword(keyword) → results[]
├── ocr_image(img_bytes) → texts[]
├── extract_face_feature() / match_face() [实验性]
├── get_thumbnail_for_time() → 缩略图路径
└── fix_old_paths() → 路径替换
```

### 5.2 脚本间关系

```
database.py        → 主库绝对路径 + 只打开已有数据库的连接函数
add_new_videos.py → 写入 video_index_fixed.db (videos, frames, subtitles)
build_faiss.py     → 只读 video_index_fixed.db → 写入 faiss_index.bin + faiss_meta.pkl
video_search.py    → 只读查询 video_index_fixed.db + FAISS；维护按钮显式写库
init_database.py   → 创建空库
update_paths.py    → 更新videos表路径
generate_thumbnails.py → 读取DB → 写thumbnails/
```

---

## 6. 性能特征

| 操作 | 耗时 | 瓶颈 |
|------|------|------|
| 抽帧+特征 (1小时视频) | ~3分钟 | CPU (MobileNetV2推理) |
| 字幕转写 (1小时视频) | ~3分钟 | CPU (faster-whisper INT8) |
| FAISS构建 (159万帧) | ~5分钟 | 内存+磁盘IO |
| 以图搜视频 (有缩略图) | ~200-500ms | FAISS搜索+ORB |
| 以图搜视频 (无缩略图) | ~3-10秒 | 开视频seek抽帧 |
| 文字搜索 | ~100ms | SQL LIKE |
| 人脸搜索 (全库) | 极慢(小时级) | 逐帧开视频+人脸检测+识别 |

---

## 7. 已知架构缺陷

1. **单文件应用**: video_search.py 650行，UI/搜索/视觉混在一起
2. **历史工具数据库不一致**: 三个日常入口已统一到主库，其他工具仍需逐项核对
3. **全局变量污染**: query_color_frame用全局变量传递，非线程安全
4. **路径配置**: 源码硬编码路径已清理；数据库/元数据内的历史素材路径和外部开机启动注册仍需分别管理
5. **无增量索引**: 加新视频必须全量重建FAISS
6. **无视频删除机制**: 删视频后残留无效索引
7. **人脸搜索未接入主流程**: 独立全库遍历，极慢
8. **未统一多目录录入**: video_folder 为主目录，material_folder 供原专用脚本使用；目录现可配置，但流程尚未合并
