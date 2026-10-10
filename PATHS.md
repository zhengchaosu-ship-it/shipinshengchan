# 路径配置与本次清理记录

本轮只清理路径，没有调整模型、预处理、数据库结构、FAISS 格式、检索排序或性能策略。

## 使用方式

`config.py` 是统一读取入口，实际机器配置保存在原有 `config.json`。保留 `video_folder` 字段，旧配置仍可读取；新增字段有默认值，无需引入 YAML 依赖。

所有相对路径都相对于 `config.py` 所在项目目录，绝对路径按配置使用；支持 `~` 和环境变量。修改路径配置后重启进程。网页保存素材目录会保留其他配置字段。

可通过 `VIDEO_SEARCH_CONFIG` 指定其他 JSON 文件，便于小样本隔离验证。该配置文件内部的相对路径仍相对于项目目录，不相对于配置文件所在目录。

双击 `启动工具.bat`、`开机启动服务.bat`，或直接使用原来的 Python 命令，入口名称均保留。两个批处理脚本通过自身所在目录定位 `launch.ps1`，启动不再依赖工作目录。启动器优先使用 `paths.python_executable`，未配置时查找 PATH 中的 python，再查找 py -3；明确配置但不存在时直接报错。

当前解释器确实安装在 C 盘，所以当前机器的配置值仍包含 C 盘路径；它只存在于配置中，代码不再写死该位置。迁移时修改配置即可，无需升级或重装环境。

## 配置项

| 配置项 | 默认值/含义 |
|---|---|
| `video_folder` | 原有主素材目录字段；扫描脚本要求配置 |
| `material_folder` | 原 D 盘专用脚本的素材目录；旧配置未提供时沿用 video_folder |
| `paths.database` | `video_index_fixed.db`，现行三个入口及原修复库脚本 |
| `paths.legacy_database` | `video_index.db`，历史旧库脚本 |
| `paths.init_database` | 独立初始化目标，默认沿用 legacy_database；当前 JSON 明确设为 video_index.db |
| `paths.faiss_index` / `paths.faiss_meta` | `faiss_index.bin` / `faiss_meta.pkl` |
| `paths.models_dir` | `models`，本地 Whisper 模型目录 |
| `paths.face_detection_model` / `paths.face_recognition_model` | 留空时使用 models_dir 内原有 YuNet/SFace 文件 |
| `paths.ffmpeg_executable` | `bin/ffmpeg.exe`；用于 PATH 和网页生成的裁剪命令 |
| `paths.thumbnails_dir` | `thumbnails`，匹配及批量生成缓存 |
| `paths.display_cache_dir` | 留空时沿用 thumbnails_dir，展示图片仍保留原有 live_ 命名 |
| `paths.log_file` / `paths.completion_file` | `process_log.txt` / `处理完成.txt` |
| `paths.export_dir` | `.`；网页显示的裁剪命令输出目录，网页不会执行导出 |
| `paths.python_executable` | 启动器使用的解释器；当前机器完整路径已移入 JSON |
| `paths.torch_home` | null 保持 TORCH_HOME / XDG_CACHE_HOME / 用户默认缓存；明确配置时覆盖 |
| `paths.cuda_library_dirs` | null 按当前解释器寻找原有 cublas/cudnn 目录；列表可显式配置，空列表不添加 |
| `sample_videos.transcribe` / `sample_videos.green` | 历史手动测试视频；相对路径以 video_folder 为基准 |

FFmpeg 目录会优先加入 PATH，并去除同一路径的重复项。旧 openai-whisper 通过 `ffmpeg` 命令找程序，因此配置的文件仍应使用 `ffmpeg.exe` 文件名。CUDA 路径配置不会改变现有 CPU/GPU 选择逻辑。

## 主库与历史库边界

本次没有把历史重采样、修复、初始化脚本改指向生产主库。它们保留独立的 legacy_database / init_database 配置，避免路径清理改变操作对象。原先位于 C 盘旧项目下的旧库依赖改为项目目录下的旧库路径；如需使用另一个旧库，必须在配置中明确指定。

`update_paths.py` 仍操作 legacy_database 和 faiss_meta；它们的数据一致性问题尚未修复，不应作为生产迁移方案直接运行。历史脚本中的删除、Schema 修改、全库遍历和自动关机逻辑原样保留，本次未执行这些流程。

## 扫描发现的隐藏依赖

1. `add_new_videos.py` 的 config.json 和 models 原来相对于当前工作目录。
2. 多个脚本写死豆包解释器下的 NVIDIA DLL 目录。
3. `full_process_and_shutdown.py`、`check_progress.py` 在 SQL 字符串里写死素材目录；现改为读取 material_folder 后传 SQL 参数，查询条件含义不变。
4. 展示缓存原在 C 盘、匹配缓存原在 D 盘；现默认同目录，命名和读取策略保持原样。
5. MobileNetV2 使用用户目录下的 torch 权重缓存，不在 models/ 中。本次沿用已有 V2 权重缓存，没有下载或替换。
6. C 盘旧项目仍存在；本次不再引用它，也没有移动或删除其中任何文件。
7. 生产数据库、FAISS 元数据和历史 thumbnail 列包含素材绝对路径。这些是持久化数据，不属于本次源码清理；没有迁移或改写。
8. Windows 计划任务、启动文件夹快捷方式属于项目外部配置，本次未修改或重新注册；批处理启动检查通过不代表已经完成开机重启验收。

运行 Python、BAT、PowerShell 源码已无写死的机器盘符路径。config.json 中的真实机器配置、历史文档示例、备份和日志中的原始路径保留，不批量替换历史记录或数据文件。

## 修改文件列表

新增：
- config.py
- launch.ps1
- PATHS.md
- tests/test_paths.py
- tests/run_path_smoke.py

修改的配置、主程序和入口：
- config.json
- database.py
- video_search.py
- add_new_videos.py
- build_faiss.py
- 启动工具.bat
- 开机启动服务.bat

修改的处理及历史工具（只替换路径来源）：
- batch_add_new.py
- batch_add_d_material.py
- batch_transcribe.py
- batch_transcribe_missing.py
- full_process_and_shutdown.py
- resample_frames.py
- generate_thumbnails.py
- gen_thumbnails.py
- fix_thumbs.py
- fix_0719.py
- check_progress.py
- check_status.py
- check_thumbs.py
- check_v2.py
- find_0722.py
- find_vid.py
- list_videos.py
- scan_d_material.py
- test_transcribe.py
- find_green.py
- init_database.py
- update_paths.py

修改的测试与文档：
- tests/test_database.py
- tests/README.md
- HANDOFF.md
- ARCHITECTURE.md
- KNOWN_ISSUES.md
- ENVIRONMENT.md

原有文件修改前均备份为 `.paths-20260926.bak`，上一轮 `.bak` 也保留。

## 验证结果

- 21 项单元测试通过：旧配置、路径解析、默认缓存继承、环境变量、启动目录独立性、配置保存、原有搜索与数据库保护。
- 使用配置中的原有 FFmpeg 创建 3 个 1.2 秒合成视频；在隔离数据库中实际运行增量处理，得到 3 个视频、6 条 1280 维帧特征，调用本地 faster-whisper 成功。
- 只为这 6 条测试特征构建隔离索引，并实际运行缩略图脚本生成 6 张匹配图片。
- 原有图搜和文字搜索函数、展示缩略图、YuNet/SFace 路径加载以及 Streamlit 文字搜索页面测试通过。
- 从项目外目录运行 launch.ps1，测试服务在本机 18501 端口返回 HTTP 200；测试后停止。
- 模型构造、特征提取、预处理、排序和字幕搜索 SQL 的函数 AST 与本轮备份一致。
- 没有修改或重建生产数据库、生产 FAISS、模型文件及生产素材；合成视频及隔离产物验证后清理。

复测命令（使用 config.json 中指定的现有解释器）：

```text
python -X utf8 -B -m unittest discover -s tests -v
python -X utf8 -B tests/run_path_smoke.py
powershell.exe -NoProfile -ExecutionPolicy Bypass -File launch.ps1 -CheckOnly
```

本轮未进行性能优化，也未修复历史特征混用、任务恢复、索引发布和路径数据迁移问题。
