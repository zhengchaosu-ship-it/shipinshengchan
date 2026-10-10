# AGENTS.md - 给 Codex 的开发指南

> 服务器/2060维护任务同时遵守 `server_maintenance/RUNBOOK.md` 的 CROSS_NODE_COORDINATION_POLICY：当前服务器Codex为SERVER_ENGINEER；2060电脑的AUTOPILOT_UNATTENDED_LEVEL1聊天为EXECUTOR_2060_ENGINEER。先读 `runtime/maintenance_watchdog/coordination/server_state.json` 核对incident_owner与恢复状态。Server只改Server组件；Heavy Slot/Worker/Session/Jianying/Journal归执行节点Owner，Server只发EXECUTOR_ACTION_REQUIRED。不得把“发布计划交接流程”绑定成执行节点工程师；用户明确暂不发送聊天通知。两个节点不能同时恢复同一根因，不直接修改Peer DB传话。原有业务授权与安全约束仍适用。

> 本文件专门写给接手本项目的 AI 编程 Agent（Codex）
> 最后更新：2026-09-26

---

## 机器环境

- **GPU**: NVIDIA RTX 3060 12GB（当前未使用，PyTorch是CPU版）
- **内存**: 32GB RAM
- **CPU**: 14代 i5
- **系统**: Windows
- **Python**: 3.14.7（豆包沙箱内置，路径见HANDOFF.md）
- **项目位置**: D:\video_search_tool\

---

## 核心原则

### 1. 优先本地运行
- 所有功能必须能在本地Windows电脑上运行
- 不依赖云服务、外部API
- 素材不上传任何服务器

### 2. 不得擅自更换已验证模型
- **MobileNetV2** (torchvision预训练, 1280维) - 已验证，不要换成CLIP/DINO等
- **faster-whisper base** (INT8) - 已验证
- **ORB** (OpenCV) - 已验证
- 如果要换模型，必须：先做对比实验 → 证明准确率/速度提升 → 保留旧模型作为回退

### 3. 不得擅自重写整个项目
- 现有代码虽然不完美，但功能已验证可用
- 优先增量修改、小步迭代
- 不要"为了代码整洁"而大规模重构

### 4. 修改必须尽量向后兼容
- 数据库Schema不要随便改（如果改了，必须写迁移脚本）
- FAISS索引格式不要变（变了旧索引就废了，159万帧重建要5分钟+7.6GB内存）
- 配置文件格式保持兼容
- API/函数签名尽量不变

### 5. 修改前先理解现有实现
- 读 HANDOFF.md 了解整体
- 读 ARCHITECTURE.md 了解架构
- 读 KNOWN_ISSUES.md 了解已知坑
- 读 video_search.py 核心搜索逻辑
- 读 add_new_videos.py 建库逻辑

### 6. 每次任务尽量小范围修改
- 一个任务只改一个功能点
- 改完立即测试
- 不要一次改5个地方然后一起测

### 7. 不要扫描全部几百GB素材做开发测试
- 开发测试用小型测试数据（3-5个短视频）
- 建一个 test_videos/ 目录放测试视频
- 不要对生产库做破坏性操作

### 8. 新功能尽量带测试
- 至少写一个手动验证步骤
- 能写单元测试就写
- 修改后运行现有测试（如果有的话）

### 9. 不允许把"规划中的功能"当成"已经实现"
- HANDOFF.md里的"下一阶段产品目标"只是方向，不是已实现功能
- 回答用户时明确区分"已实现"和"计划中"
- 不要在文档里写"支持XXX"如果代码里没有

---

## 绝对不要碰的东西

| 内容 | 原因 |
|------|------|
| MobileNetV2 1280维输出 | 改了旧FAISS索引全废 |
| 预处理Normalize参数 | 改了特征分布变了，旧索引全废 |
| L2归一化 | FAISS用内积，依赖归一化 |
| FAISS维度1280 | 索引文件硬编码 |
| subtitles表的start/end列名 | 不是start_time/end_time，改了查询全崩 |
| faiss_meta.pkl的三元组格式 | (file_path, file_name, timestamp) |
| 综合得分权重 | 已调优，改动需重新验证 |
| models/目录的模型文件 | 不要替换版本 |
| 生产数据库video_index_fixed.db | 32GB，不要随便删改 |

---

## 开发工作流

### 开始一个新任务前
1. 读 HANDOFF.md 相关章节
2. 读 KNOWN_ISSUES.md 看是否有相关坑
3. 确认要改的文件和函数
4. 备份要改的文件（复制为 .bak）

### 修改时
1. 小范围修改
2. 保持代码风格一致（中文注释、4空格缩进）
3. 不引入新的大型依赖（除非必要）
4. 硬编码路径要改成相对路径或配置项

### 修改后
1. 语法检查: `python -c "import py_compile; py_compile.compile('xxx.py', doraise=True)"`
2. 启动服务测试: `python -m streamlit run video_search.py --server.port 8501`
3. 手动验证核心功能：以图搜视频、文字搜索
4. 确认没有破坏旧功能

### 提交前
1. 更新相关文档（HANDOFF.md如果功能变了）
2. 清理临时文件
3. 记录修改内容

---

## 已知坑（必读）

1. **数据库不一致**: video_search.py用video_index.db，实际数据在video_index_fixed.db。修改前先统一。
2. **人脸模型路径硬编码C盘**: 项目在D盘，人脸功能会报错。
3. **Python 3.14装不了CUDA版PyTorch**: 不要浪费时间试，要么换Python 3.12，要么继续CPU。
4. **全局变量query_color_frame**: 不是线程安全的，不要在并发场景依赖它。
5. **缩略图生成极慢**: 159万帧，当前脚本逐帧seek，要几十小时。优化方向是按视频批量处理。
6. **WAL模式不可用**: 不要尝试PRAGMA journal_mode=WAL，会报错。
7. **FRAME_INTERVAL=10是旧值**: video_search.py里的没用，实际建库用add_new_videos.py里的1。
8. **config.json只配了E盘**: D盘素材不在配置里，但数据库里有。

---

## 建议的优先级

### 高优先级（影响日常使用）
1. 统一数据库路径（ISSUE-001）
2. 加速缩略图生成（ISSUE-013）
3. 修复硬编码路径（ISSUE-009）

### 中优先级（提升体验）
4. 搜索速度优化（ISSUE-002）
5. 多素材目录支持（ISSUE-005）
6. 增量FAISS索引（ISSUE-007）

### 低优先级（长期）
7. 人脸搜索优化（ISSUE-004）
8. 换背景匹配提升（ISSUE-006）
9. 测试体系（ISSUE-014）
10. 代码模块化拆分

---

## 禁止事项

- ❌ 不要删除生产数据库
- ❌ 不要删除FAISS索引（除非你确定要重建）
- ❌ 不要对全部360个视频做实验性处理
- ❌ 不要安装不兼容的依赖版本
- ❌ 不要把素材路径改成网络路径
- ❌ 不要在用户没要求的情况下加用户系统/登录
- ❌ 不要把数据上传到任何云端
- ❌ 不要修改抽帧间隔（1秒/帧是用户确认的）

---

## 联系方式

如果遇到不确定的情况，优先选择保守方案，记录在文档里，让用户做决定。不要擅自做高风险操作。
