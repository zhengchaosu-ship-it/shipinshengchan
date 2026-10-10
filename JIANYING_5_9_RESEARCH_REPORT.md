# JIANYING_5_9_RESEARCH_REPORT

任务：**JIANYING_5_9_ROLLBACK_AND_INSTALLER_RESEARCH**  
日期：2026-10-02（Asia/Shanghai）  
最终状态：**JIANYING59_RESEARCH_READY**

**当前环境基线和关键数据备份已完成；已取得可验证的剪映专业版5.9.0.11632 Windows安装包，可信度HIGH。仅推荐用于后续经人工确认的独立环境测试。** 本轮未对当前剪映进行安装、替换、卸载或重启；5.9安装和运行次数均为0。到报告完成为止停止，不自动切换版本。

## 1. 当前环境

基线采集于 **2026-10-02 04:53:42 +08:00**，早于备份和候选下载。系统为Windows10专业版x64，10.0.19045。完整记录见[CURRENT_ENVIRONMENT.json](research/jianying_59/baseline/CURRENT_ENVIRONMENT.json)。

| 当前JianyingPro.exe项目 | 实测值 |
| --- | --- |
| 剪映版本/文件版本 | **11.5.0.14471** |
| 完整路径 | `C:\Users\Administrator\AppData\Local\JianyingPro\Apps\11.5.0.14471\JianyingPro.exe` |
| 安装目录 | 同上EXE所在的`Apps\11.5.0.14471` |
| 文件修改时间 | 2026-09-18 03:24:39.856 UTC，即北京时间11:24:39.856 |
| 文件大小 | **438,552字节** |
| SHA256 | `F77353701EFD7BC3E010B054E61A48AB78CC2F4413407109989FE8447CF622CC` |
| 数字签名 | Valid，深圳市脸萌科技有限公司 |

用户数据根目录为`C:\Users\Administrator\AppData\Local\JianyingPro\User Data`。草稿生成实际根目录为其中`Projects\com.lveditor.draft`；另有`D:\JianyingPro Drafts`，其中“贴纸”和“特效滤镜”是生产资源模板，二者均纳入备份。配置为用户数据下`Config`。模板/预设目录存在于用户数据下`Presets`和`D:\JianyingPro Presets`，同样纳入备份。

| Python环境 | 版本 |
| --- | --- |
| Python | 3.14.7，64位 |
| pyJianYingDraft | 0.3.0 |
| uiautomation / comtypes | 2.0.29 / 1.4.16 |
| pymediainfo | 7.0.1 |
| Pillow / opencv-python / numpy | 12.3.0 / 5.0.0.93 / 2.5.3 |
| pywin32 / pyautogui | 未安装；记录null，不改环境 |

Python完整路径记录在基线JSON：豆包本机`sandbox_runtime\bases\c98c5042338ed152c6f10ecd8591889f\python\python.exe`。本轮没有安装或更换任何Python依赖。

项目路径：

- `startup_pipeline`：`D:\video_search_tool\startup_pipeline`。
- 草稿生成代码/配置目录：`D:\video_search_tool\jianying_auto`；批次清单为`runtime\batches`。
- 主项目`config.json`的`paths.export_dir`为`.`，项目相对路径基于`D:\video_search_tool`。
- 起号实际导出交接配置为`startup_pipeline/export_config.json`，`export_root=outputs/startup_exports`，解析为`D:\video_search_tool\outputs\startup_exports`。
- 剪映`Config/Export.ini`只有`userFirstVideoEnhanceExport=false`，未从该文件确认剪映默认直接渲染目录。起号交接目标目录不等于剪映全局默认导出目录。
- 生产复合模板为`jianying_auto/combo_skeleton.json`，贴纸和特效索引位于`D:\JianyingPro Drafts`对应模板目录下。

## 2. 当前版本备份状态

**VERIFIED：3368个文件，共4,915,360,316字节，约4.92GB（4.58GiB）。** 原文件和备份文件的SHA256逐一一致，最终复核无变化。备份位于`research/jianying_59/backup/`，数据仅保存在本机，未上传。

| 备份类别 | 文件数 | 字节数 | 状态 |
| --- | ---: | ---: | --- |
| 当前C盘草稿 | 93 | 5,230,139 | VERIFIED |
| D盘旧草稿及贴纸/特效资源模板 | 75 | 1,917,081 | VERIFIED |
| 剪映Config目录 | 80 | 3,925,549 | VERIFIED |
| 用户数据Presets | 71 | 2,346,768,550 | VERIFIED |
| D盘Presets | 2994 | 2,556,584,996 | VERIFIED |
| 草稿批次身份清单 | 42 | 96,654 | VERIFIED |
| 项目配置、需求文件及安装/用户配置补充 | 13 | 837,347 | VERIFIED |

项目配置覆盖主`config.json/config.py`、草稿生成配置、来源目录配置、复合骨架、起号export配置和自动化adapter配置等。剪映Config按原始字节本地复制，未在报告输出非公开配置值。保留模板预设的实际文件内容，不只记录路径。

可恢复清单包括每个源路径、备份路径、大小、修改时间和SHA256，并保留空目录记录。按明确规则排除cache/log/tmp、回收站、DeepAgent会话等；全部排除项目在清单中列出。没有扫描几百GB素材库或复制生产视频。

产物：

- [FILE_HASHES.json](research/jianying_59/baseline/FILE_HASHES.json)：备份前的文件哈希及当前EXE哈希。
- [BACKUP_MANIFEST.json](research/jianying_59/baseline/BACKUP_MANIFEST.json)：备份前计划，保持原始PLANNED状态。
- [backup_manifest.json](research/jianying_59/backup_manifest.json)：实际完成清单，状态VERIFIED，以此作为恢复映射。
- [BACKUP_VERIFICATION.json](research/jianying_59/BACKUP_VERIFICATION.json)：源/备份复验PASS，222个受保护文件变化0，当前EXE哈希未变。

备份为应用运行期间的逐文件复制，复制前后做源与目标哈希一致性检查，**不是VSS或完整系统镜像**。没有实际覆盖原文件做恢复演练；仅已确认备份内容完整一致。当前完整剪映安装目录和Python运行时只记录而未复制；生产数据库、索引、模型及原素材保持原地，本轮不备份或修改。该范围适合关键草稿/模板/配置恢复，不代表可从空电脑重装当前系统。

## 3. 找到的5.9候选安装包

只取得以下一个候选，下载后未继续搜索其它包，未接受破解/绿色/改版/网盘重包。

| 项目 | 实测结果 |
| --- | --- |
| 文件名 | `Jianying_5_9_0_11632_jianyingpro_0_creatortool.exe` |
| 保存路径 | `D:\video_search_tool\research\jianying_59\installers\Jianying_5_9_0_11632_jianyingpro_0_creatortool.exe` |
| 类型 | EXE，内嵌7z载荷；非MSI |
| 架构 | WinGet清单标记x64 |
| 文件/产品版本 | **5.9.0.11632 / 5.9.0.11632** |
| 产品名称 | 剪映专业版 |
| 文件大小 | **564,045,480字节**，约564.05MB |
| MD5 | `1280D184BCA37F70C0C830A71CEE7B3A` |
| SHA256 | **`C0919B9A6D499FB8659DE3D314D25B10C7892F9072CB3AD00BEF62A89D13E399`** |
| 数字签名 | **Valid / Signature verified.** |
| 签名发布者 | **深圳市脸萌科技有限公司** |
| 签名证书颁发者 | DigiCert Trusted G4 Code Signing RSA4096 SHA384 2021 CA1 |
| 时间戳签名者 | DigiCert Timestamp 2023 |
| 是否包含JianyingPro.exe | **是，压缩包文件名表已验证** |
| 安装包执行/安装 | **0 / 0** |

## 4. 来源与完整性证据

实际下载直连：[厂商CDN 5.9.0.11632安装包](https://lf3-package.vlabstatic.com/obj/faceu-packages/Jianying_5_9_0_11632_jianyingpro_0_creatortool.exe)。下载没有跳转其它域名，长度与HTTP Content-Length一致。服务器Last-Modified为2024-05-08 16:35:45 GMT；它不是另行确认的软件发布日期。

来源依据为[微软WinGet仓库中的5.9安装清单](https://github.com/microsoft/winget-pkgs/blob/master/manifests/b/ByteDance/JianyingPro/5.9.0.11632/ByteDance.JianyingPro.installer.yaml)，记录了同一厂商CDN URL、版本和SHA256。实际下载哈希与清单完全一致。[同版本发布者清单](https://github.com/microsoft/winget-pkgs/blob/master/manifests/b/ByteDance/JianyingPro/5.9.0.11632/ByteDance.JianyingPro.locale.zh-CN.yaml)记录开发者为深圳市脸萌科技有限公司，与本机签名结果一致。

WinGet是独立软件包目录，不是剪映厂商关于旧版仍受支持的承诺。官网当前下载入口未取得可直接验证的5.9历史版本页，本轮采用“厂商CDN直连＋独立目录哈希＋有效开发者签名”的交叉验证，不把软件镜像站“官方版”字样作为主要证据。

安装包签名证书的有效期结束时间早于本次研究日期，但Windows验证状态为Valid，并存在DigiCert时间戳签名；未仅因历史证书有效期结束而错误判为文件遭修改。完整证书元数据保存在签名记录。

本机系统tar不支持此包使用的LZMA编解码器，首次静态列目录失败；没有转而运行安装器自解压，也没有安装工具或调用未验证的WinRAR。最终用Python标准库读取内嵌7z压缩头、校验各级CRC、解码FilesInfo的文件名表。2362个文件/目录名中包含：

```text
JYPacket/5.9.0.11632/JianyingPro.exe
JYPacket/JianyingPro.exe
```

该方法依据[7-Zip官方格式定义](https://github.com/ip7z/7zip/blob/main/DOC/7zFormat.txt)，未执行载荷。它确认文件名表和包头完整性，不等于逐个解压、核验包内EXE的签名；整包SHA256和外层Authenticode另行验证。包内EXE目录为剪映、FFmpeg、反馈/崩溃处理/更新等组件，没有发现额外第三方安装器名称；没有做行为运行，不能由文件名断言所有安装行为。

证据在`research/jianying_59/installers/`：

- [download_record.json](research/jianying_59/installers/download_record.json)：URL、大小、MD5、SHA256、下载时间、Manifest哈希。
- [signature_verification.json](research/jianying_59/installers/signature_verification.json)：版本、签名状态、发布者、证书与时间戳元数据。
- [payload_names_verification.json](research/jianying_59/installers/payload_names_verification.json)：包头CRC、文件名数量及JianyingPro路径。
- `payload_file_names.txt`、原始WinGet YAML：本次目录和来源记录。
- [INSTALLER_ASSESSMENT.json](research/jianying_59/INSTALLER_ASSESSMENT.json)：最终判定，以此覆盖download_record中的“待验证”下载阶段状态。

## 5. 安全与安装建议

**可信度：HIGH。推荐：仅用于人工确认后的独立环境测试安装。当前生产安装/降级：不推荐，本轮禁止。**

判断依据：厂商CDN、与WinGet历史指纹一致、签名Valid且发布者匹配、文件版本明确、内嵌官方产品路径符合。没有发现二次包装或下载内容被修改的证据；不是绿色版或第三方网盘文件。

HIGH评估的是来源及文件完整性，不是对旧版漏洞、遥测、权益政策或自动导出能力的保证。本轮没有行为沙箱运行、在线恶意文件上传或安装；没有声称安装器全部行为已验证。后续若文件哈希/签名/版本不匹配，应标NOT_RECOMMENDED并停止。

## 6. 下一步测试方案与停止点

已生成[JIANYING59_TEST_PLAN.md](JIANYING59_TEST_PLAN.md)，覆盖当前11.5与5.9的：草稿打开、自动导出、速度、MP4质量、字幕、贴纸、特效、抠图、换背景、连续3条导出。两版使用同输入快照和同编码设置，记录错误与资源准备，完整解码并保存画面对照。当前版贴纸复合结构来自11.5，必须额外验证5.9兼容性，不能先改生产生成器迁就旧版。

独立Windows来宾/测试机仍需安排；没有在本机启用Sandbox/Hyper-V、创建用户或安装虚拟化软件。恢复时优先还原来宾快照。关键本机备份可作为额外保障，手动恢复须另行授权，当前不覆盖任何源数据。

本轮修改只限新增报告、测试计划和`research/jianying_59/`研究产物。原源码、依赖、草稿、安装程序、发布状态及配置保持不变；未运行生产迁移、验收、Streamlit或Worker。脚本语法检查与备份/载荷验证结果保存于研究目录。

**JIANYING59_RESEARCH_READY。已找到并验证候选，准备工作完成；现在停止，等待人工确认后续隔离环境及安装测试。**
