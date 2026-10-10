# 生产素材上传入口 V1

8502 → 视频生成模块 → 生产素材库，默认「上传素材」。用于员工已经剪好的生产视频；背景另属 VISUAL。一级导航、原始索引、生成与发布算法保持原样。

## 使用

1. 选择起号 / 带货 / 背景，选择分类；带货另选通用或具体产品。
2. 拖入多个文件，点击「开始入库」，等待中文结果与批次汇总。
3. 可暂停、继续；刷新页面后重新选择同一原文件即可续传。大批量上传可使用页面的独立窗口入口，切换8502页面时保持上传窗口打开。
4. 20分钟以上视频保留在暂存区，用户确认「是剪好素材」后才提交。损坏文件隔离，不进入正式目录。
5. 总览按产品筛选、每页12条、支持缩略图与图片/视频预览。普通页面没有删除、移动、覆盖或路径设置操作。

## 目录与产品

| 池 | 正式目录 |
|---|---|
| 起号 / 引流（STARTUP_LEAD） | `E:\寻帧生产素材库\起号素材\01_引流` |
| 起号 / 手法 | `E:\寻帧生产素材库\起号素材\02_手法` |
| 起号 / 坐诊 | `E:\寻帧生产素材库\起号素材\03_坐诊` |
| 起号 / 收尾（STARTUP_CLOSE） | `E:\寻帧生产素材库\起号素材\04_收尾` |
| 背景 | `E:\寻帧生产素材库\背景素材` |
| 引流坐诊 | `E:\寻帧生产素材库\带货素材\01_引流坐诊` |
| 承接坐诊 | `E:\寻帧生产素材库\带货素材\02_承接坐诊` |
| 述品介绍 | `E:\寻帧生产素材库\带货素材\03_述品介绍` |
| 连麦反馈 | `E:\寻帧生产素材库\带货素材\04_连麦反馈` |
| 销售逼单 | `E:\寻帧生产素材库\带货素材\05_销售逼单` |

2026-10-07已自动绑定全部正式目录，普通用户无需选路径。根目录配置为 `service.config.json.production_library_root`，具体映射见 `library.py`。高级管理仍可查看登记值；拒绝链接、原始直播目录及服务暂存目录，已经有上传记录的池禁止直接改址。普通LAN客户端不能配置路径。产品范围保存在数据库，不复制产品目录。

本轮迁移249文件：起号125、背景6、待确认118、带货0；30个目录（含来源层级），Duplicate/Failed均0。完整SHA256和迁移清单在正式库 `_管理/`，工作证据与三库一致性备份在 `runtime/e_drive_migration_20261007/`。四类起号、6账号池与背景绑定同步新路径，旧目录保留。历史module_type STARTUP_HOOK/STARTUP_ENDING不变，正式pool_id为STARTUP_LEAD/STARTUP_CLOSE，旧上传池名兼容解析。持久materials原为0条，旧文件继续使用legacy_inventory编目，没有伪造新material_id。

ProductRegistry初始读取 `content_pool/products.json`（现有产品：小妙招）。高级管理可登记稳定产品ID与名称。上传保存 `GLOBAL / NULL` 或 `PRODUCT_SPECIFIC / product_id`，从不使用昵称确定路径。

## 服务与持久化

- 员工正式入口与8502同源：`http://192.168.1.126:8502/production-materials/`。嵌入页和独立窗口使用同一路径；8502正式启动入口为 `benchmark/experiments/dino_july_web/server.py`，通过已有Streamlit `App` API挂载固定回环代理，原 `app.py`保持原样。客户端不依赖8510入站端口。
- `proxy.py`只转发至配置的回环后端，校验LAN对端、Host与Origin，不接收任意转发地址或服务器路径；最大缓冲一个4MiB分片。前端JS/CSS、API、缩略图和预览Range均使用当前同源目录。服务不可用返回可恢复提示，健康检查验证同源路径的真实服务标识。
- `service.config.json`：独立SQLite、暂存、缩略图、ffprobe/ffmpeg路径、磁盘保留空间、分片限制、长视频阈值及LAN配置。
- Windows计划任务 `XunZhen-ProductionMaterialUpload-8510`：启动时运行，S4U本地身份、pythonw、异常退出间隔1分钟重启，连续自动恢复最多3次；同一任务不并发。分钟守护 `XunZhen-ProductionMaterialUpload-Watchdog`只在健康失败且原任务Ready、启用、服务进程为0时启动原任务；有进程绝不启动第二实例，不自动解除人工禁用。守护恢复预算持久化，间隔至少1小时、24小时最多3次，避免重启风暴。
- 仅绑定 `127.0.0.1:8510` 与 `192.168.1.126:8510`，应用检查对端网段、Host、写请求Origin及每个上传的随机凭据。防火墙新增规则只放行 `192.168.1.0/24` 到本机该端口。不开放公网、不调用云API。
- 管理员部署或升级：管理员PowerShell中运行 `& .\production_materials\install_service.ps1`，更新守护/防火墙并保留正在运行的上传服务；`-Restart`只在无未完成上传时升级本服务。防火墙匹配venv派生的实际基础pythonw.exe，同时保留LAN地址和网段限制。只管理本服务，不操作8502、Render或Publisher任务。
- 字节流为每片最大4 MiB、服务按1 MiB写盘；浏览器仅读取当前分片和首尾各1 MiB指纹。LAN普通HTTP具备自带SHA256校验回退，不依赖仅HTTPS可用的WebCrypto。
- 每批最多100个文件、每文件默认50 GiB；不是已实测50 GiB上限。所有并发上传预留暂存剩余量与提交副本空间，最低余量默认5 GiB；开始前用服务身份验证目录可写。
- SQLite schema迁移只发生在 `production_materials/runtime/catalog.sqlite`。上传、素材、批次、事件与revision均独立保存。
- `UPLOADING → STAGED → VALIDATING → DEDUPLICATING → COMMITTING → LIBRARY_READY`。ffprobe校验并实际解码首帧；这是明显损坏检测，不承诺检测视频后半段的全部编码损伤。
- SHA256按字节内容全局去重。现有生产文件只在启动时列目录元数据；上传时仅对同大小候选按需计算SHA256，不重读整库视频。
- 正式提交先写无视频扩展名临时副本，校验hash，再用Windows拒绝覆盖的原子rename完成。同名不同内容使用短hash后缀。
- 成功/重复的暂存副本自动回收；损坏、长视频待确认、失败暂存保留。普通员工无清理权限；管理员应定期检查暂存容量，不能直接清理未完成批次。
- 单校验队列避免并发同内容提交；重启恢复UPLOADING已确认偏移、STAGED校验以及COMMITTING的既有目标。失败进入ATTENTION_REQUIRED，不无穷重试。

## 现有消费端接线

起号：保存到四个正式目录，更新既有账号素材池的SHA缓存；8502在入库revision变化后清除素材选项会话缓存。`jianying_auto.source_catalog` 与 `CompositionCatalog.refresh(hash_budget=0)` 均可直接读取，不改模板或托管计划，不自动生成视频。

背景：更新 `BackgroundMaterialCatalog` 和别名记录，供 `AccountBackgroundBinding` 的现有选择器读取；不自动绑定任何账号。

带货：`ProductionMaterialCatalog.for_commerce(product_id,module_type)` / `CommerceMaterialSource.materials(...)` 返回该产品专属素材及通用素材，按五种正式模块隔离；排除STARTUP与VISUAL。**当前没有实现CommerceCompositionPlanner或带货Autopilot**，这是供未来Planner消费的正式查询接口。

```python
from production_materials.config import settings
from production_materials.store import ProductionMaterialCatalog
catalog = ProductionMaterialCatalog(settings())
items = catalog.for_commerce('xiaomiaozhao', 'COMMERCE_PRODUCT_INTRO')
```

## 验收和维护

2026-10-09员工入口修复：原iframe为 `http://192.168.1.126:8510/`，员工报告连接拒绝；服务实际监听正常，防火墙却绑定venv启动器而非实际监听的基础pythonw。已修正规则，并部署8502同源入口绕过员工网络对8510的依赖。29项隔离回归通过，正式同源API完成256.4MiB有效MP4传输、中断后从8MiB续传、SHA256校验、正式池识别、重复仅一份、终态暂存清理；小视频通过浏览器界面成功入库。大样本使用合法MP4 free atom填充，属于大字节传输验收，未验证50GiB上限或长时长编码压力。

证据位于 `runtime/employee_material_upload_repair_20261009/`。测试素材属于独立产品 `upload_acceptance_20261009`，正式目录为 `E:\寻帧生产素材库\带货素材\03_述品介绍\upload_acceptance_20261009`；未放入现有起号池，不用于发布。无新增RenderJob/PublishJob、无真实Submit；普通员工电脑最终访问确认以该目录的最终报告为准，不能用服务器本机200替代。

`python -m unittest production_materials.tests.test_portal -v` 使用3个半秒视频和1张图片，全部在隔离临时目录；覆盖A-H、续传、分片校验、长视频确认、磁盘预留、路径拒绝、崩溃恢复、HTTP同源与预览Range、分页。`node production_materials/tests/test_hash.cjs`验证4个SHA256向量（含4 MiB）。

现场：5,573,160字节既有手法素材改名后，由浏览器分两片提交，被标记DUPLICATE_SKIPPED；正式手法池保持44条。没有添加模拟视频到正式池。新文件成功提交与业务隔离在fixture中验收。

验收证据在 `runtime/acceptance_20261007/`。生产保护快照显示：原始索引1112个文件元数据完全一致；96个原有算法文件指纹一致；模板、Profile、背景绑定及计划等保护表不变；PublishJob 294→294、ProviderJob 56→56，提交闩锁合计49。既有后台周期对账继续更新观察时间，观察事件维持SCHEDULED_QUEUED或SUBMITTED，不能误报为“整个数据库完全没变化”。本服务没有RenderJob、PublishJob、Provider Upload、publish或历史重试入口。

备份：使用SQLite backup API保存本服务catalog.sqlite，同时备份staging、thumbnails、service.config.json及配置的正式生产目录；恢复时先停本服务，再恢复同一路径。重新启动会按原upload_id恢复；不要只恢复数据库而丢失未完成暂存文件。

回退：停止/禁用本服务计划任务并恢复8502入口两份 `.bak`，不会删除已入库素材或账号背景记录；不要回滚其他生产数据库或任务。预览缩略图与上传日志在本服务runtime，定期归档即可。
