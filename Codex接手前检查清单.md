# Codex 接手前检查清单

> 生成时间：2026-09-26
> 项目位置：D:\video_search_tool\

---

## ✅ 已完成项

### 文档
- [x] HANDOFF.md - 交接总览（项目状态、技术栈、数据流、算法、运行方式）
- [x] ARCHITECTURE.md - 架构文档（模块划分、数据存储、模型架构、接口关系）
- [x] ENVIRONMENT.md - 环境配置（从零部署步骤、模型说明、验证方法）
- [x] KNOWN_ISSUES.md - 已知问题（17个问题+3个历史事故+性能基线）
- [x] AGENTS.md - 给Codex的开发指南（核心原则、禁止事项、工作流）
- [x] .gitignore - Git忽略规则

### 代码审计
- [x] 无密码/API Key/敏感信息
- [x] 无恶意代码
- [x] 所有import在requirements.txt中有对应依赖
- [x] 数据库结构已核实（3张表，159万帧，106万字幕）
- [x] FAISS索引结构已核实（IndexFlatIP, 1280维, 159万向量）
- [x] 模型文件已核实（faster-whisper base + YuNet + SFace）
- [x] Web服务可正常启动（http://localhost:8501）

---

## ⚠️ 需要 Codex 接手后优先处理的问题

### P0 - 必须立即修复（影响核心功能）

1. **数据库路径不一致**
   - 现象：video_search.py第22行用 `video_index.db`，但实际数据在 `video_index_fixed.db`
   - 影响：Web界面搜不到D盘新素材
   - 修复：修改video_search.py第22行为 `video_index_fixed.db`，或重命名文件
   - 文件：D:\video_search_tool\video_search.py

2. **主程序硬编码C盘路径（4处）**
   - 第45行：`FFMPEG_DIR = r"C:\video_search_tool\bin"`
   - 第66行：`det_path = r'C:\video_search_tool\models\face_detection_yunet.onnx'`
   - 第67行：`rec_path = r'C:\video_search_tool\models\face_recognition_sface.onnx'`
   - 第372行：`THUMB_CACHE = Path(r"C:\video_search_tool\thumbnails")`
   - 修复：全部改为 `Path(__file__).parent / "xxx"`
   - 影响：项目在D盘，人脸功能会报错

### P1 - 建议尽快处理（影响体验）

3. **缩略图生成极慢**
   - 当前脚本逐帧seek，159万帧预计数十小时
   - 当前进度：10,448 / 1,591,127 (0.66%)
   - 优化方向：按视频分组，每个视频只open一次，顺序读取
   - 文件：generate_thumbnails.py

4. **废弃文件清理**
   - 0字节空文件：check_status.py, check_v2.py, find_0722.py, find_vid.py, list_videos.py
   - 历史脚本：resample_frames.py, fix_0719.py, fix_thumbs.py, scan_d_material.py, test_transcribe.py, gen_thumbnails.py, auto_shutdown.ps1
   - 历史截图：bug.png, bug2.png, bug3.png
   - 审计临时文件：_audit_db.py, _audit_versions.py, _versions.txt
   - 建议：移到archive/子目录或删除

### P2 - 后续优化

5. **config.json扩展为多素材目录**（当前只配了E盘，D盘素材不在配置中）
6. **增量FAISS索引**（当前每次全量重建）
7. **视频删除/清理机制**（删视频后残留无效索引）
8. **测试体系**（当前无任何自动化测试）

---

## 📋 关键数据速查

| 项目 | 值 |
|------|-----|
| 视频总数 | 360个 |
| 帧特征数 | 1,591,127 |
| 字幕数 | 1,062,422 |
| FAISS维度 | 1280 |
| FAISS类型 | IndexFlatIP |
| 抽帧间隔 | 1秒/帧 |
| 特征模型 | MobileNetV2 (ImageNet预训练) |
| 字幕模型 | faster-whisper base (INT8) |
| Python | 3.14.7 |
| PyTorch | 2.14.0+cpu (GPU不可用) |
| 主数据库 | video_index_fixed.db (32.3GB) |
| FAISS索引 | faiss_index.bin (7.59GB) |
| Web地址 | http://localhost:8501 |

---

## 🔒 绝对不要碰

- [ ] MobileNetV2 1280维输出 → 改了旧索引全废
- [ ] 预处理Normalize参数 → 改了特征分布变了
- [ ] L2归一化 → FAISS内积依赖它
- [ ] subtitles表的start/end列名 → 不是start_time/end_time
- [ ] faiss_meta.pkl三元组格式 → (file_path, file_name, timestamp)
- [ ] 综合得分权重 → 已调优
- [ ] 生产数据库video_index_fixed.db → 32GB，不要删
- [ ] 抽帧间隔1秒 → 用户确认的

---

## 🚀 快速启动命令

```cmd
# 启动Web服务
cd /d D:\video_search_tool
python -m streamlit run video_search.py --server.headless true --server.port 8501

# 添加新视频
python add_new_videos.py
python build_faiss.py

# 检查进度
python check_progress.py
```

---

## 📁 交付文件清单

| 文件 | 大小 | 说明 |
|------|------|------|
| HANDOFF.md | ~15KB | 交接总览（必读） |
| ARCHITECTURE.md | ~10KB | 架构详情 |
| ENVIRONMENT.md | ~8KB | 部署指南 |
| KNOWN_ISSUES.md | ~10KB | 已知问题 |
| AGENTS.md | ~8KB | Codex开发指南 |
| .gitignore | ~1KB | Git忽略规则 |

---

## 🎯 接手建议

1. **第一天**: 读HANDOFF.md → 读ARCHITECTURE.md → 读KNOWN_ISSUES.md → 启动服务跑一遍
2. **第二天**: 修复P0问题（数据库路径+硬编码路径）→ 验证搜索功能正常
3. **第三天**: 优化缩略图生成脚本 → 加速搜索体验
4. **后续**: 根据用户需求逐步迭代，不要大规模重构

记住：**这个项目已经能工作，你的任务是让它更好，不是推倒重来。**
