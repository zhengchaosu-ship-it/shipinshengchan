# 视频生产平台源码备份

本仓库保存 2026-10-10 从 `D:\video_search_tool` 导出的源码快照，包括素材检索、生产规划、剪映执行、发布适配、维护工具、测试及项目文档。

这是当前源码备份，不包含生产数据库、视频素材、成片、模型权重、FAISS 索引、账号登录资料、密钥、运行日志或历史 `.bak` 文件。完整运行环境仍需在本地恢复这些数据与配置。

项目入口与架构见 `HANDOFF.md`、`ARCHITECTURE.md`、`KNOWN_ISSUES.md`；视频生产界面入口是 `benchmark/experiments/dino_july_web/app.py`。各模块的 README 及 `development_link/USAGE.txt` 保留部署说明。文档中的历史验收记录及计划须结合日期与实际代码判断。

配置模板为 `*.example.json`；模板中的 Worker 默认停用，发布执行模式为 `DRY_RUN`。恢复时按本机环境配置，勿以备份模板替换正在运行的生产配置。

`media_execution/acceptance.py` 在备份副本中将固定验收密码改为从环境变量 `XUNZHEN_ACCEPTANCE_PASSWORD` 读取。真实运行目录的源码没有修改。

`SOURCE_MANIFEST.json` 记录文件 SHA-256、大小及备份副本变换；其余已导出的源码与原文件逐字节一致。本仓库不包含更早的 Git 历史。
