# JIANYING59_EXPORT_POC_REPORT

最终状态：**JIANYING59_EXPORT_FAIL**。本次PoC在隔离安装阶段失败并停止，**没有进入草稿打开或自动导出阶段**。该状态表示本轮没有完成导出验收，不能据此断定5.9的渲染能力失败，也不能断定5.9一定无法与新版并存。

记录日期：2026-10-02，Asia/Shanghai。测试活动已停止，不继续安装、切换版本或接生产发布。

**隔离环境与安装结果**

创建了独立标准Windows用户 `Jianying59Test`，SID `S-1-5-21-1003218081-2795646701-4076737436-1002`，没有管理员组权限。新用户无法读取管理员的剪映目录；管理员11.5继续运行。

首次环境探针发现 `Start-Process -Credential -LoadUserProfile` 仍继承管理员的 `USERPROFILE/LOCALAPPDATA/TEMP`，因此没有使用该环境安装。改用Windows `CreateProcessWithLogonW` 的 `LOGON_WITH_PROFILE` 和空环境参数后，探针确认三个目录均属于测试用户，才允许启动安装程序。[Microsoft API说明](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-createprocesswithlogonw)

| 项目 | 实际记录 |
|---|---|
| 已验证安装包 | `research/jianying_59/installers/Jianying_5_9_0_11632_jianyingpro_0_creatortool.exe` |
| 安装包版本 | 5.9.0.11632 |
| 安装包SHA256 | `C0919B9A6D499FB8659DE3D314D25B10C7892F9072CB3AD00BEF62A89D13E399` |
| 启动前签名复核 | Valid，原官方发布者；哈希匹配 |
| 请求的独立安装路径 | `C:\Users\Jianying59Test\AppData\Local\JianyingPro` |
| 安装器日志中的实际目标 | `C:\Users\Jianying59Test\AppData\Local\JianyingPro\Apps\` |
| 使用参数 | `/silent_install=1 /install_path="C:\Users\Jianying59Test\AppData\Local\JianyingPro"` |
| 安装开始 | 2026-10-02 05:24:31.9245268 +08:00 |
| 安装退出确认 | 2026-10-02 05:25:47.6344761 +08:00 |
| 安装进程耗时 | 约75.71秒；这是安装等待时间，非导出耗时 |
| 安装进程退出码 | 0 |
| 安装器内部结果 | `update bRet=0` |
| 实际安装成功 | 否：测试目录没有 `JianyingPro.exe`，没有5.9运行进程 |
| 5.9实际EXE路径/版本/SHA256 | null；程序未安装，不能用安装包哈希代替应用EXE哈希 |
| 5.9安装完成时间 | null |
| 新用户数据目录 | `C:\Users\Jianying59Test\AppData\Local\JianyingPro\User Data`，仅发现安装日志 |
| 预期草稿目录 | `C:\Users\Jianying59Test\AppData\Local\JianyingPro\User Data\Projects\com.lveditor.draft`，不存在 |

安装日志关键证据：

```text
[05:24:32.019] is_all_user=0
[05:24:32.020] installpath=C:\Users\Jianying59Test\AppData\Local\JianyingPro\Apps\, binstalled=0
[05:25:47.303] update bRet=0
[05:25:47.303] process end ret_code=0
```

退出码0没有对应安装产物，因此判定安装失败。日志没有解释具体失败原因，不能把失败原因写成已确认的版本冲突。真正执行安装器共1次；之前两个包装器失败都发生在安装器启动前。安装器执行后没有重试，没有使用 `/update_install` 或强制安装参数，没有关闭、卸载或覆盖生产剪映。未通过解包运行绕过本次停止条件。

安装包来源是[厂商CDN](https://lf3-package.vlabstatic.com/obj/faceu-packages/Jianying_5_9_0_11632_jianyingpro_0_creatortool.exe)，参数和SHA256依据此前下载保存的[Microsoft winget清单](https://raw.githubusercontent.com/microsoft/winget-pkgs/master/manifests/b/ByteDance/JianyingPro/5.9.0.11632/ByteDance.JianyingPro.installer.yaml)。本轮没有重新下载其他版本。

**真实模板核实与执行边界**

只读核实当前真实生产草稿，未使用此前4秒简化夹具。没有启动生产生成器、重新选择素材、重新转写字幕、修改草稿或降低特效数量。由于安装失败，没有生成或注册测试用户草稿副本，也没有调用 `pyJianYingDraft.JianyingController.export_draft`。以下内容是源草稿清单，不能当成5.9已打开或兼容的证据。

| 生产草稿 | 时间线时长 | 主轨道数 | 子草稿贴纸 | 字幕素材 | 色度抠图素材 | video_effects素材 | 转场素材 | 计划输出 |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| 组合3-自动合成 | 127.667秒 | 18 | 6 | 43 | 3 | 3 | 0 | 001.mp4 |
| 组合4-自动合成 | 115.901秒 | 18 | 6 | 51 | 3 | 3 | 0 | 002.mp4 |
| 组合5-自动合成 | 81.535秒 | 18 | 6 | 31 | 3 | 3 | 0 | 003.mp4 |

三条草稿的画布均为1080×1920、30fps，包含背景图引用、3条effect轨道、3条filter轨道和贴纸复合子草稿。素材表数量不等同实际可见效果数量；目前没有转场素材，不人为补加。抠图、换背景、贴纸复合、特效和字幕的5.9运行兼容性仍未验证。

**必须回答的九项结果**

| 问题 | 本轮结论 |
|---|---|
| 1. 是否自动导出成功 | 否；安装阶段阻塞，导出调用0次，MP4产出0条 |
| 2. 是否需要人工点击 | 无法判断；本轮人工/Agent导出点击均0次，未到导出界面 |
| 3. 单条耗时 | 未测量；导出开始/结束/耗时均null，不把安装耗时写成导出耗时 |
| 4. 三条连续成功率 | 未执行；尝试0条，成功0条，成功率null，不写0/3或0% |
| 5. MP4质量 | 未检查；无输出文件，codec/resolution/fps/duration均null |
| 6. 抠图效果 | 未评估；没有人物移动、边缘稳定性或背景成片可供人工检查 |
| 7. 特效兼容 | 未评估；只确认源模板中保留贴纸/特效/字幕/抠图/背景结构 |
| 8. 是否比当前版本稳定 | 无法比较；没有同一草稿的两版本实际导出样本 |
| 9. 是否推荐作为Render Worker | **目前不推荐**；需要先完成隔离安装和真实三条自动导出验收 |

| 性能/媒体指标 | 5.9 | 当前11.5 |
|---|---|---|
| 草稿打开、自动导出 | 未执行 | 本轮未操作生产窗口 |
| 导出输出路径及是否可控 | 未验证 | 未做本轮导出测试 |
| CPU/GPU占用、显存 | 无导出测量值 | 未采集对照导出测量值 |
| 导出速度/实时倍数 | 未测量 | 未测量 |
| ffprobe结果、文件大小 | null，无测试MP4 | 无本轮对照MP4 |
| 人工检查字幕/贴纸/背景/特效/转场 | 未执行 | 未执行本轮对照 |

**生产保护复核**

前后只读快照覆盖396个受保护文件：生产代码、pyJianYingDraft、当前剪映EXE、生产草稿、剪映配置、批次Manifest等。全部SHA256保持一致。另5个大型数据库/索引的大小及纳秒修改时间一致；这些大文件没有进行全文件哈希，结论限于记录的属性。

当前EXE仍为 `C:\Users\Administrator\AppData\Local\JianyingPro\Apps\11.5.0.14471\JianyingPro.exe`，版本11.5.0.14471，SHA256仍为 `F77353701EFD7BC3E010B054E61A48AB78CC2F4413407109989FE8447CF622CC`，原主进程35720继续运行。没有切换生产版本。

`real_publish_enabled=false` 保持不变。PublishJob前后均5条，全表逐行哈希一致，新增正式PublishJob为0；没有调用小V猫发布或生产发布服务，没有注册测试内容到生产待发布池。

已验证备份仍保留：3368个文件，共4,915,360,316字节；本轮没有修改备份或执行恢复。独立标准测试账户、其用户目录及安装失败日志保留。随机凭据仅存在受ACL保护的DPAPI加密文件，不在报告公开，研究目录私有文件已局部gitignore。

**证据文件**

- `JIANYING59_INSTALL_RESULT.json`：安装阶段结果，未安装EXE的字段明确为null。
- `research/jianying_59/isolated_test/PROFILE_PROBE.inherited-env.json`：首个被拦截的继承环境探针。
- `research/jianying_59/isolated_test/PROFILE_PROBE.json`：独立标准用户环境检查通过。
- `research/jianying_59/isolated_test/INSTALL_PROCESS.json`：唯一实际安装器的PID、参数、开始/退出时间。
- `research/jianying_59/isolated_test/JianyingPro_Install_2026-10-02T05-24-32.log`：原始日志副本，SHA256 `854E3DBC2C8284441F00EAA734EAFC67B7DD9E06684099D70E7767C29D4C5DD3`。
- `research/jianying_59/isolated_test/REAL_TEMPLATE_INVENTORY.json`：组合3/4/5真实模板的路径、哈希、子草稿和素材计数。
- `research/jianying_59/isolated_test/EXPORT_RESULTS.json`：三条导出均未尝试，媒体和性能字段为null。
- `research/jianying_59/isolated_test/PRODUCTION_BEFORE.json`、`PRODUCTION_AFTER.json`、`PRODUCTION_VERIFICATION.json`：生产保护复核PASS。

后续测试应在独立测试机器或Windows虚拟机完成5.9安装，确认真实EXE版本/签名/哈希和用户数据隔离后，再用完整组合3/4/5及其子草稿、所需素材和本地资源副本验证pyJianYingDraft自动导出。先通过单条，再执行001/002/003连续测试并采集ffprobe与CPU/GPU/显存，最后取得同素材新版成片做人工质量对照。此项是后续方案，本轮未执行。

**最终状态：JIANYING59_EXPORT_FAIL。已停止。**
