# JIANYING59_INSTALL_DIAGNOSTIC_REPORT

诊断完成：**JIANYING59_INSTALL_DIAGNOSTIC_COMPLETE**。

实际状态修正为：**INSTALLATION_FAILED / EXPORT_NOT_TESTED**。此前 `JIANYING59_EXPORT_FAIL` 是前轮结果标签，本次失败发生在安装阶段，不能称为导出失败。5.9没有安装成功，没有 `JianyingPro.exe`，没有进行导出测试。

**主要结论**

`bRet=0` 的高置信原因是：**5.9安装器在解包前发现正在运行的同名 `JianyingPro.exe`，进入“请关闭剪映后继续”的前置检查失败分支，返回false。独立Windows用户隔离了数据目录，却没有隔离系统进程枚举。** 安装时管理员11.5及其子进程持续运行；本轮独立用户的只读探针仍能枚举到相同9个剪映进程。

该判断来自安装器静态控制流、原始安装日志及运行现场的相互印证，置信度HIGH。**没有采集上次安装的动态执行分支跟踪，也没有重跑安装器**，因此不声称拥有历史分支被执行的逐指令证据。原日志本身没有把进程阻塞原因写出来。

| 必答问题 | 结论 |
|---|---|
| 1. bRet=0具体原因 | 高置信为运行中的 `JianyingPro.exe` 被安装器系统级进程名检查发现，安装在解包前被拦截。未证明是“检测到已安装11.5版本就拒绝降级”。 |
| 2. 是否安装包损坏 | 没有损坏证据：本轮SHA256仍与此前验证的厂商包及winget清单匹配，数字签名Valid，内嵌7z头CRC校验通过。可排除本机下载/复制造成的字节变化。 |
| 3. 是否在线安装器 | 属于带内嵌核心程序载荷的离线安装EXE，非必须先下载 `JianyingPro.exe` 的轻量在线引导器。未发现本次失败来自下载资源。运行时在线特效/账户等资源需求未测试。 |
| 4. 是否需要卸载新版 | **不需要依据本次诊断卸载11.5，也没有做卸载。** 检测目标是正在运行的进程名，不能从中推出必须卸载。关闭后是否可共存尚未验证。 |
| 5. 是否需要独立机器 | 若生产11.5必须持续运行且不得干扰，建议独立操作系统环境：独立测试机或Windows虚拟机。物理机器不是唯一选择；仅新建用户不足以绕开该系统级进程检查。 |
| 6. 是否需要寻找其它5.9安装包 | **当前没有换包的必要证据。** 优先在独立操作系统中诊断当前已验证的5.9.0.11632包；不因bRet=0转用未知、修改或重打包版本。 |

**安装日志检查**

检查的原始日志共23行：`research/jianying_59/isolated_test/JianyingPro_Install_2026-10-02T05-24-32.log`。SHA256为 `854E3DBC2C8284441F00EAA734EAFC67B7DD9E06684099D70E7767C29D4C5DD3`。本轮没有修改该日志。

| 检索项 | 结果 |
|---|---|
| error | 3处，均为 `errorcode=0`；对应打开文件、建立文件映射、映射视图成功 |
| failed | 0处 |
| rollback | 0处；不能把末尾 `clear temp` 单独解释成已执行安装回滚 |
| exit code / ret_code | `process end ret_code=0`；退出码没有传递内部失败状态 |
| install state | 没有显式install-state记录；有 `bSilentInstall=1, bUpdateInstall=0, bForceInstall=0` 及 `binstalled=0` |
| 包初始化 | `packet init filemap end, bRet=1`、`init end 1` |
| 实际失败 | `update bRet=0` |
| 下载/解包开始 | 没有download/extract记录；测试目录仍没有应用EXE |

关键时间顺序：

```text
05:24:32.019  包映射成功，bRet=1
05:24:32.020  测试用户安装目录 binstalled=0；init end 1
05:25:47.303  update bRet=0
05:25:47.303  clear temp；process end ret_code=0
```

初始化结束与失败之间约75.28秒。没有历史UI录像或动态跟踪，不能断言该间隔一定是弹窗等待、超时或下载耗时。

**静态代码定位：运行进程检查**

仅读取安装器PE头、导入表、明文字符串及有限x86代码片段；没有加载或执行其代码，没有安装反汇编工具，也没有修改安装器。对以下11处代码片段进行了精确字节断言。地址是本包PE首选基址 `0x00400000` 下的静态地址，不是运行时地址。

| 静态位置 | 证据 |
|---|---|
| `0x00435338` | 调用 `0x00461F10`；返回值随后进入 `update bRet=%d` 日志 |
| `0x00461FEA` | 将字符串 `JianyingPro.exe` 传给进程枚举函数 `0x0045C0CB`，检查返回值 |
| `0x0045C106` | 调用 `CreateToolhelp32Snapshot`，flags=2，即 `TH32CS_SNAPPROCESS` |
| `0x0045C125`、`0x0045C16C` | 遍历 `Process32FirstW` / `Process32NextW`，按进程可执行名称比较；该检查没有用户SID、已安装版本号或安装路径条件 |
| `0x00461FF9` | 找到同名进程后准备标题“安装提示”及文字“剪映专业版正在运行，请关闭后再继续运行” |
| `0x004620F6` | 进入 `MessageBoxW` 提示分支，随后 `xor eax,eax`，返回false |

Windows文档确认 `TH32CS_SNAPPROCESS` 包含系统所有进程；因此换用户不会使其他用户的剪映进程从该检查中消失。[Microsoft进程快照说明](https://learn.microsoft.com/en-us/windows/win32/api/tlhelp32/nf-tlhelp32-createtoolhelp32snapshot)

上次现场记录显示，管理员主进程35720和8个子进程均来自 `C:\Users\Administrator\AppData\Local\JianyingPro\Apps\11.5.0.14471\JianyingPro.exe`。本轮在 `Jianying59Test` 身份下只读枚举，也发现相同9个进程，均在Session 1。探针只枚举进程，没有调用关闭、Kill、TerminateProcess或安装器。

这解释了“测试用户的安装目录未安装任何剪映，`binstalled=0`，却仍被拦截”的现象：**运行进程检查与用户目录的安装状态检查是两个不同条件**。现有证据支持运行冲突，不支持把卸载新版列为必要步骤。

**安装包类型与完整性**

| 项目 | 记录 |
|---|---|
| 文件 | `Jianying_5_9_0_11632_jianyingpro_0_creatortool.exe` |
| 大小 | 564,045,480字节 |
| 文件版本 | 5.9.0.11632 |
| SHA256 | `C0919B9A6D499FB8659DE3D314D25B10C7892F9072CB3AD00BEF62A89D13E399` |
| 本轮签名 | Valid，发布者深圳市脸萌科技有限公司 |
| 安装器格式 | 自定义原生EXE，PE32/x86；不是MSI |
| 应用架构 | winget清单记录x64；32位安装器与64位应用载荷不矛盾 |
| 内嵌载荷 | 7z，起点文件偏移1,670,158，大小562,363,431字节 |
| 载荷文件名 | 2362条；包含Qt、CEF、DLL、Resources、本地模型等核心资源 |
| 包内应用 | `JYPacket/5.9.0.11632/JianyingPro.exe`、`JYPacket/JianyingPro.exe` |
| 包内维护程序 | `JYPacket/uninst.exe`、`JYPacket/5.9.0.11632/update.exe`；本轮均未执行 |

厂商包来源与SHA256清单此前已验证：[厂商CDN](https://lf3-package.vlabstatic.com/obj/faceu-packages/Jianying_5_9_0_11632_jianyingpro_0_creatortool.exe)、[Microsoft winget 5.9清单](https://raw.githubusercontent.com/microsoft/winget-pkgs/master/manifests/b/ByteDance/JianyingPro/5.9.0.11632/ByteDance.JianyingPro.installer.yaml)。本轮没有下载其它剪映安装包。

此前先用系统tar解析时报告“LZMA codec is unsupported”，属于工具不支持编码；随后Python标准库成功解析内嵌7z文件名及头结构。不能将前一条工具错误或旧JSON中的 `contains_JianyingPro_exe=false` 当成包缺少程序；最终成功的 `payload_names_verification.json` 已确认包含应用EXE。

完整性结论的范围：整包SHA256匹配、Authenticode有效、7z起始头/后续头/解码头CRC有效；没有逐个解压并核验全部2362个文件的内容CRC或内部签名，也没有进行离线安装成功验收。故“带离线核心程序载荷”已经证实，“所有运行功能均无需网络”没有被验证。

**参数、路径和返回码**

```text
/silent_install=1
/install_path="C:\Users\Jianying59Test\AppData\Local\JianyingPro"
```

清单记录静默参数 `/silent_install=1`，自定义路径参数 `/install_path="<INSTALLPATH>"`，升级参数 `/update_install`。实际日志确认静默模式开启、升级和强制模式均关闭；没有使用升级/强制参数。

日志中的默认路径和实际目标均为 `C:\Users\Jianying59Test\AppData\Local\JianyingPro\Apps\`。请求路径恰好与新用户默认根目录一致，无法用本次记录单独证明任意自定义路径参数都会生效。没有指向管理员安装目录。包映射及目录初始化成功，当前C盘可用空间约33.42GB；当前空间数据不是安装当时的快照，不能据此绝对排除历史空间问题。

安装器进程退出码0，内部安装方法返回false。两者不是同一个结果；本轮仍以无应用EXE、内部bRet=0判定安装失败。5.9实际EXE版本和SHA256继续为null。

**系统事件日志**

只读检查本地时间 `2026-10-02 05:15:00～05:35:00`，覆盖安装前后。没有启用、清除或改变任何事件通道。

| 通道 | 查询结果 |
|---|---|
| Application | 1条：05:21:15 Windows Search为测试用户创建默认配置，信息级。没有MsiInstaller、Application Error或Windows Error Reporting事件 |
| System | 2条Kernel-General信息事件，属于新用户配置文件初始化；没有对应安装错误 |
| Setup | 时间窗内没有事件 |
| CodeIntegrity/Operational | 时间窗内没有事件 |
| Windows Defender/Operational | 本机找不到该日志通道，查询不可用；不能声明已排除所有安全软件拦截 |
| AppLocker/EXE and DLL | 通道未启用，未为诊断开启 |

本包是自定义EXE，未出现MSI事件不代表安装成功。系统事件没有提供“包损坏”“应用崩溃”或“被安全软件阻止”的具体错误；直接证据仍是安装器前置进程检查。

**本轮边界、生产复核与后续判断**

本轮安装器执行0次、导出测试0次；没有关闭或卸载11.5、删除草稿、修改注册表、修改生产代码或安装未知版本。研究过程仅新增本地诊断脚本与证据文件。没有新建用户，本轮只复用已批准建立的标准测试账户做只读枚举。

生产复核PASS：396个受保护文件SHA256与前轮安装后的基线一致；5个大型数据库/索引的大小及修改时间一致。PublishJob仍5条且逐行哈希一致，`real_publish_enabled=false`，没有创建发布任务。测试用户目录仍只有安装日志，没有5.9应用EXE。

在保持生产11.5持续运行的要求下，后续应把现有已验证包放到独立测试机或Windows虚拟机，避开该系统级进程名检查。仅切换用户或会话不构成同等级隔离。关闭新版后能否在同机独立目录成功安装、运行时是否有其它互斥条件，均未验证；本轮不会为验证它们干扰生产。当前无需寻找其它5.9包，也不建议尝试绕过检查的强制参数。

证据目录：`research/jianying_59/install_diagnostic/`。

- `INSTALL_LOG_SEARCH.json`：日志关键字和原始行号。
- `STATIC_INSPECTION.json`：PE结构、导入函数、相关字符串、整包SHA256。
- `CONTROL_FLOW_EVIDENCE.json`、`PROCESS_GATE_CODE.hex.txt`：前置进程检查的精确代码片段与解读。
- `TEST_USER_PROCESS_PROBE.json`：测试用户可见的9个同名生产进程。
- `SYSTEM_EVENTS.json`：各事件通道查询结果及不可用原因。
- `PACKAGE_RECHECK.json`、`READ_ONLY_STATE.json`：签名、目录与生产进程现状。
- `PRODUCTION_VERIFICATION.json`：本轮生产保护复核。
- `DIAGNOSTIC_SUMMARY.json`：安装失败/导出未测试的修正状态和六项结论。

**诊断完成，已停止。没有进入安装重试或导出测试。**
