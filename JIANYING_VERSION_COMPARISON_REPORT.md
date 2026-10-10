# JIANYING_VERSION_COMPARISON_REPORT

研究编号：**JIANYING_5_9_EXPORT_COMPATIBILITY_TEST**  
日期：2026-10-02（Asia/Shanghai）  
状态：**PARTIAL / TEST_INPUT_READY / VERSION_RUNTIME_COMPARISON_NOT_RUN**

**目前不能确认剪映5.9具有更稳定的导出路径。** 已完成本机环境核查、Controller静态检查和独立小样本测试包；两版实际打开与导出均未执行。缺少可核验的5.9安装包和可用的独立Windows来宾环境。不能将上游兼容性声明或草稿结构检查写成本机实测通过。

当前剪映未卸载、降级、重启或重新配置；没有打开生产草稿。生产生成器、发布流水线、Planner、Worker、数据库、索引和模型未进行修改。本轮没有创建或登记剪映导出的MP4。

## 1. 环境与隔离状态

本机正在运行的剪映专业版EXE为：

```text
C:\Users\Administrator\AppData\Local\JianyingPro\Apps\11.5.0.14471\JianyingPro.exe
```

文件版本 **11.5.0.14471**，Authenticode签名状态Valid，SHA256：

```text
F77353701EFD7BC3E010B054E61A48AB78CC2F4413407109989FE8447CF622CC
```

安装目录只发现11.1、11.2、11.3、11.4.1、11.4.2、11.5，没有5.9。已检查已知下载目录和`D:\Program File`顶层，没有匹配的安装包。该结论只覆盖列出的目录，不是全盘不存在的证明。

| 独立运行条件 | 本机检查结果 |
| --- | --- |
| Windows Sandbox启动程序 | 未发现；没有可用Sandbox环境 |
| Hyper-V | 查询到的功能全部Disabled；本轮未启用 |
| VMware / VirtualBox | 常见安装路径未发现；不等于排除所有自定义路径 |
| 剪映5.9可核验程序 | 未取得，完整构建号/签名/哈希未知 |
| 独立研究目录 | 已建立：`research/jianying_5_9_compatibility/` |
| 共用测试输入及记录表 | 已建立，结构和哈希检查通过 |
| 可运行的两版隔离应用环境 | **尚未建立** |

证据：[环境快照](research/jianying_5_9_compatibility/environment.json)。系统功能与进程查询使用只读提升权限；没有安装软件、创建Windows用户、修改注册表、启用虚拟化或改变安全设置。

单独安装到另一个文件夹、仅改变CEF的`--user-data-dir`、修改LOCALAPPDATA，均没有被证明能隔离整个剪映Qt宿主的全局配置、草稿注册和自动升级行为，故本轮未采用。独立环境拟采用同一干净Windows快照克隆出的CURRENT/V59来宾，仅共享小型测试包；这仍是待执行步骤。

## 2. 六项比较记录

| 项目 | 当前剪映11.5.0.14471 | 剪映5.9 | 本轮结论 |
| --- | --- | --- | --- |
| 1. 同一草稿是否正常打开 | **NOT_RUN**，没有打开本轮草稿 | **NOT_RUN**，程序未取得 | 不能判断兼容性 |
| 2. 是否可以导出 | **NOT_RUN**，导出尝试0 | **NOT_RUN**，导出尝试0 | 不能判断导出成功率 |
| 3. 导出耗时 | **未测，null** | **未测，null** | 不填0秒、不推算速度 |
| 4. 导出路径是否可控 | 实际导出路径未测；本机Controller静态实现为先导出再move | 同一Controller可能适配旧控件；运行与路径行为未测 | 最终移动路径与直接渲染路径须分开 |
| 5. 命令行/接口线索 | 前次研究发现内部`lyra-cli draft export`，外部帮助调用遭宿主授权拒绝；本轮未重跑 | 安装包未取得，CLI/私有接口未知；上游旧版Controller依赖UI | 无已验证的无界面接口 |
| 6. 特效、贴纸、绿幕保持 | 草稿字段结构检查通过，**实际渲染NOT_RUN** | **实际渲染NOT_RUN** | 不能宣称画面等价或资源已可用 |

预留18条运行记录：2版本×3样本×3次，当前全部NOT_RUN，实测布尔值和耗时均为null。见[trial_results.json](research/jianying_5_9_compatibility/trial_results.json)。前次生产草稿的结构记录、已有手动导出MP4，都不是本轮同输入比较证据。

## 3. 已准备的同输入小样本

采用本机已安装 **pyJianYingDraft 0.3.0**，没有升级或修改该包。仅用项目已有FFmpeg在本地生成3个合成短视频，不读取生产素材，不调用Whisper，不扫描任何素材库。测试草稿每份4秒、画布1080×1920、30fps，输入视频360×640，含音频校验音。

| 草稿 | 内容 | 验证目的 |
| --- | --- | --- |
| `01_plain` | 基础视频、声音、文字 | 排除特效资源干扰，验证打开/基础导出 |
| `02_effect_sticker_chroma` | 蓝背景、绿幕白方块、2个独立贴纸、1998特效 | 分别观察色度抠像、贴纸和特效 |
| `03_production_combination` | 同类画面，2个贴纸打包为复合片段，外层滤色与1%不透明度 | 检验当前11.5复合结构能否在5.9保持 |

第三样本直接从现有`jianying_auto.py`抽取并执行两个构造函数`_combination_video_material`、`wrap_stickers_as_combination`，只对本研究对象和本研究目录写入；没有导入或运行生产main、选材、字幕、批次生成。骨架来自现有`combo_skeleton.json`，不改变生产格式。仅用两张贴纸缩小实验，并不替代完整起号工程验收。

全部草稿只生成一次。两个来宾应复制同一组文件，分别核对[fixture_manifest.json](research/jianying_5_9_compatibility/fixture_manifest.json)中的文件SHA256，不能分别随机生成。素材与子草稿引用已统一为来宾`X:/JIANYING_TEST/...`，不能直接把这些草稿放进宿主生产目录测试。

贴纸仅写入公开资源ID；1998的本机包元数据标记非VIP。这些都**不证明5.9能获取该资源或实际账号无需权益**。测试包没有附带剪映缓存特效/贴纸资源，因此离线加载可能失败。资源不可用、版本不兼容和权益拦截应分别记录，不能相互替代。

第三样本的1%贴纸可能肉眼难辨。后续必须核对子草稿与外层混合设置、关键帧画面对照；不能临时改透明度后声称是同输入兼容性结果。

## 4. 已验证的导出路径线索

### pyJianYingDraft Controller

本机`jianying_controller.py`的SHA256：

```text
6f871913afdba7c86ce8f2d4fe238de857c2c0e3d66bdc49c6258427cc55873e
```

静态代码显示以下行为，本轮没有实例化Controller或发送窗口输入：

- 根据草稿名和旧版窗口描述查找控件，点击打开、导出和完成按钮。
- 读取导出窗口中的默认输出路径。
- 导出完成后执行`shutil.move(export_path, output_path)`。
- 方法说明限于剪映6及以下；存在固定等待，并依赖窗口状态。
- 等待循环中`app_status != pre_export`会先continue，可能跳过本轮超时检查。这是静态风险，不是已复现的5.9故障；若后续运行需外层超时保护。

因此，**5.9值得验证的主要候选是旧控件导出路径**。调用Python函数或把它包装成HTTP接口，不会自动成为剪映原生无界面导出API。`output_path`参数也不能证明剪映引擎直接渲染到该位置。

证据：[本机Controller静态记录](research/jianying_5_9_compatibility/controller_static.json)。上游当前文档将5.9的草稿打开、指定位置导出和导出参数控制列为支持，注明新版自动导出依赖控件前提；这些属于上游声明，尚非本机5.9结果。该文档的新版列主要针对10.8，也不能直接当成11.5实测。[上游README](https://github.com/GuanYixuan/pyJianYingDraft/blob/main/README.md)

### 当前版内部CLI

沿用2026-10-02前次只读研究：11.5安装包存在`lyra-cli draft export --ref ... --output ...`静态调用；外部帮助POC返回`unauthorized host process`。没有成功导出、没有得到对外受支持的执行契约。本轮不重试鉴权或绕过宿主检查。

见[JIANYING_EXPORT_RESEARCH_REPORT.md](JIANYING_EXPORT_RESEARCH_REPORT.md)和前次[CLI证据](research/jianying_export/cli_help_poc.json)。5.9安装包尚未取得，无法做对应静态或帮助比较；不能把11.5组件的能力推到5.9。

## 5. 特效与兼容性的待测风险

上游报告5.9支持色度抠图、贴纸和轨道特效，同时提示旧版可能出现资源加载超时。这支持安排实验，不能证明本项目全部效果均向后兼容。[功能与资源说明](https://github.com/GuanYixuan/pyJianYingDraft/blob/main/README.md)

当前生产贴纸复合结构专门取自11.5；5.9是否接受虚拟video材料、内嵌draft、子草稿路径和混合模式尚不确定。即使第二样本通过，第三样本失败仍意味着不能直接将当前生产草稿搬到5.9。不能为迁就5.9而修改生产骨架后继续称“同一草稿”。

上游有5.9自动升级的用户问题；它只能证明有人报告过升级问题，不提供本机已经验证的防升级方案。独立来宾默认离线，任何资源准备后都应再次核验EXE版本，发生升级则该轮不能列为5.9。[上游Issue #115](https://github.com/GuanYixuan/pyJianYingDraft/issues/115)

## 6. 后续实测协议

完整步骤见[ISOLATED_TEST_RUNBOOK.md](research/jianying_5_9_compatibility/ISOLATED_TEST_RUNBOOK.md)。必要条件为：可核验的5.9程序，以及现有独立Windows虚拟机或测试电脑。安装与运行均在该环境内进行，保留宿主当前剪映。

两版使用相同来宾配置、编码设置与测试输入。每样本至少3次，分开记录冷资源准备、打开草稿、确认导出→完成、全流程耗时。记录请求路径、直接渲染路径、最终路径和移动方式。报告重复成功率与热轮中位数；虚拟机软件编码速度不作为原机RTX3060性能结论。

真实输出须完整解码，核验4秒时长、1080×1920、30fps和音频，再检查0.5/2/3.5秒画面及工程设置。已提供`verify_export.py`，只允许验证研究`results/`中的MP4，不调用导出或生产成片登记；它不会自动判定特效/贴纸/绿幕保持。

## 7. 本轮验证与保护记录

| 检查 | 结果 |
| --- | --- |
| 4个新增Python研究脚本语法检查 | PASS |
| 3个小草稿结构检查 | PASS，运行/渲染仍NOT_RUN |
| 测试包文件哈希 | 全部一致 |
| 工具自检6项 | PASS：3个输入完整解码、验证器接受正确合成媒体、拒绝损坏媒体、拒绝研究结果目录外路径 |
| 受保护小文件/配置/程序SHA256 | 246个，变化0 |
| 5个生产数据库/索引文件stat | 大小和修改时间未变；没有扫描内容哈希 |
| 剪映打开/导出测试 | 0 / 0 |
| 发布与生产成片登记 | 0 |
| 安装、卸载、降级、系统功能修改 | 0 |

保护覆盖已安装pyJianYingDraft、`jianying_auto/`、`startup_pipeline/`、`publish_planner/`、`xiaovcat_adapter/desktop_worker/`非缓存文件，相关配置和核心搜索源文件、当前EXE，以及前次实际检查的19个草稿配置等。不是全部素材/全部草稿的完整性审计。证据：[保护基线](research/jianying_5_9_compatibility/protected_before.json)、[核验结果](research/jianying_5_9_compatibility/validation.json)。

工具自检使用FFmpeg合成/缩放文件，保存在明确命名的`results/tool_selfcheck_NOT_JIANYING_EXPORT/`；**它们不是剪映导出文件，不计入两版试验次数或导出成功率**。见[工具自检记录](research/jianying_5_9_compatibility/tool_validation.json)。

本轮只增加此报告及独立研究目录；生产功能不变，未修改HANDOFF，也未启动无关Streamlit或数据库迁移。初次准备因现有生产源文件UTF-8 BOM导致AST读取失败，已修复研究读取方式并重新生成；生产源文件未改。保留研究脚本`.bak`，失败准备目录已清理。

复验：

```powershell
$researchPython = (Get-Content -LiteralPath config.json -Raw | ConvertFrom-Json).paths.python_executable
& $researchPython -X utf8 -B research/jianying_5_9_compatibility/prepare_test.py verify
```

`baseline`和`generate`拒绝覆盖已有基线/测试包。不要为重跑删除生产文件。后续新轮次应另建研究目录并保存原证据。

**阶段结论：值得继续在隔离环境验证5.9旧控件路径；目前没有证据宣布5.9更稳定、导出更快、路径完全可控或本项目特效完整兼容。研究尚未完成双版本运行验收。**
