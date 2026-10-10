# 剪映自动导出只读研究报告

研究日期：2026-10-02（Asia/Shanghai）  
本机版本：剪映专业版 **11.5.0.14471 / Windows**  
结论：**RESEARCH_COMPLETE / AUTOMATIC_EXPORT_NOT_VALIDATED**  
Lyra专项最终状态：**LYRA_EXPORT_UNAVAILABLE / STOP**（2026-10-02 02:36，Asia/Shanghai）

## Lyra专项收尾：当前结果优先于原报告的继续研究建议

**确认是剪映厂商签名、随当前安装目录提供的组件；未确认 `draft export` 是面向外部程序正式开放的能力。当前外部调用不可用，停止继续投入Lyra路线。** 数字签名证明发布者和文件完整性，不等于厂商对第三方承诺导出API可用。

| 检查项 | 本次结果 | 能证明什么/限制 |
| --- | --- | --- |
| 1. `lyra-cli --help` | 使用完整路径，仅再运行1次；exit code `1`、错误码 `-100015`、`unauthorized host process` | 普通外部调用连帮助输出也无法取得；遇拒绝后没有再执行CLI命令 |
| 2. 文件路径 | `C:\Users\Administrator\AppData\Local\JianyingPro\Apps\11.5.0.14471\lyra-cli.exe`，12,184,088字节；当前shell的PATH中未找到 `lyra-cli` | 本机安装包内置文件，没有下载或安装另一个同名工具 |
| 3. 文件版本 | Windows `FileVersion`、`ProductVersion`、`ProductName`、`CompanyName`、`OriginalFilename` 均为空 | CLI自己的版本未知；目录版本不能替代文件版本。没有在帮助拒绝后追加`--version`试探 |
| 4. 数字签名/来源 | Authenticode状态 `Valid`，签名方“深圳市脸萌科技有限公司”；与本机 `JianyingPro.exe`、`jianying-agent-cli.exe` 使用同一签名证书 | 结合官方开发者信息，支持厂商来源判断；未重新下载官方安装包做逐文件比对 |
| 5. 官方文档/配置入口 | 未找到公开的Lyra导出CLI文档或对外启用入口；安装包文档中的命令名搜索无匹配，只有内置运行时代码引用 | 存在内部调用不等于公开能力。未读取账号配置、进程环境或授权值 |
| 6. 是否需要剪映进程运行 | 本次帮助运行前，剪映主工作进程PID `37376`及其相关进程存在；帮助仍被拒绝 | **剪映运行不是充分条件；是否为必要条件未知**。没有关闭/重启剪映做对照 |
| 7. 是否需要登录状态 | CLI静态提示包含先在剪映桌面登录，以及commerce导出需凭据/VIP的提示；未检查当前登录状态 | 某些CLI业务存在登录/权益要求，但**不能确认普通`draft export`是否必须登录**。当前错误是宿主授权拒绝，不能当作“未登录” |

CLI文件SHA256：

```text
8db519e796a17d074fbe071adb5635b8a069c9c9629bbefb056a3ba6eb24d87f
```

签名证书指纹：`8B2FD398702FB53F0EAEC04CB9CD82480A319D2E`。Windows核验状态为Valid，存在Sectigo时间戳签名；证书签发机构为DigiCert。剪映主程序的FileVersion为`11.5.0.14471`、ProductVersion为`11.5.0.43bd85e8548`；这些是主程序版本，**CLI版本仍未知**。证书是公开签名材料，不涉及账户凭据。

官网将“深圳市脸萌科技有限公司”列为开发者，与本机三个可执行文件的签名方相符。[剪映官方开发者信息](https://www.jianying.com/web/mobile_portal)

官方资料检查范围：公开搜索`lyra-cli`、`lyra-cli draft export`及剪映CLI导出，并将文档查询限定到`jianying.com / capcut.com / bytedance.com`；同时查看[剪映官网](https://www.jianying.com/)。未定位到此命令的公开接入文档。搜索无结果不是“官方永远不存在文档”的证明。

本地配置/文档检查限定为安装目录的README/帮助文件名、`Resources/canvas_agent/skills`与`prompts`中的Markdown/JSON、`Resources/agent_runtime_env/cli/npm-tools/package.json`，以及仅枚举`User Data/Config/Agent`的文件名（当时为空）。npm-tools清单实际只有`@larksuite/cli`，不是Lyra启用入口。内置客户端的transport/工作区环境变量是内部运行契约，**未验证为面向用户的配置入口**；没有尝试设置变量、注入宿主授权值或改配置。

静态代码仍有 `lyra-cli draft export --ref ... --output ...` 引用；CLI也仍包含 `draft export is disabled in this build` 文本。两者可以同时存在。由于本次在宿主检查就被拦截，不能把限制文本当作已经运行导出分支的结果，也不能把内部引用当作当前可用的正式对外能力。

本次仅执行一次 `--help`；没有执行`auth/login/status`、`--version`、`draft export`业务命令，没有读取账号、Cookies、token或进程内存，没有绕过、修改二进制、注入或Hook。研究终止状态已保存：

```text
LYRA_EXPORT_UNAVAILABLE
Further investment: STOP
Scope: 当前Windows剪映11.5.0.14471的外部自动导出接入
```

该状态不是宣称剪映内部永远不能导出，而是明确本项目在本次约束下无法使用该接口。**本次不再扩大CLI、权限或渲染实验，不开发适配器。**

本次证据：[版本/签名/运行进程](research/jianying_export/lyra_followup/metadata.json)、[唯一帮助请求](research/jianying_export/lyra_followup/help_poc.json)、[静态提示及内部调用](research/jianying_export/lyra_followup/static_evidence.json)、[最终停止决定](research/jianying_export/lyra_followup/decision.json)、[保护核验](research/jianying_export/lyra_followup/protection_check.json)、[记录及语法验证](research/jianying_export/lyra_followup/validation.json)。受保护217文件及19个既有草稿配置在本次前后仍无变化；原轮证据不覆盖。本报告修改前已备份为`JIANYING_EXPORT_RESEARCH_REPORT.md.lyra-before-20261002_023659.bak`。

以下A～C保留第一轮研究证据；D～E的当前决策已按本次停止要求修正。

**发现了真实的内部导出调用线索，但尚未找到本机外部程序能直接使用、无需模拟点击的导出接口。** 安装包内有 `lyra-cli draft export` 调用代码；外部执行该 CLI 的帮助命令即返回 `unauthorized host process`。本地 HTTP 服务也有授权拦截。不能把“安装包存在导出代码”写成“自动导出已实现”。

本轮仅检查本地文件、进程/端口/管道名称、窗口元数据，执行 HTTP GET 和固定 CLI 帮助 POC，并查阅公开一手资料。没有启动或重启剪映，没有使用 computer-use、UIA 点击或合成输入，没有打开/修改工程，没有真实导出、发布或接入生产。

## A. 发现的接口与结构

### A1. 草稿目录、工程字段与项目身份

实际草稿根目录：

```text
C:\Users\Administrator\AppData\Local\JianyingPro\User Data\Projects\com.lveditor.draft
```

只检查了六个既有草稿的顶层配置：`组合1～5-自动合成`、`自动合成_120248`。没有遍历或解码素材视频，没有扫描生产素材库。根目录还存在 `root_meta_info.json`；本轮只记录存在，没有修改或重新注册项目。

`组合1-自动合成` 的实际结构示例：

```text
组合1-自动合成/
  draft_content.json
  draft_meta_info.json
  draft_agency_config.json
  draft_settings
  draft.extra
  attachment_editing.json
  attachment_pc_common.json
  key_value.json
  timeline_layout.json
  Timelines/  subdraft/  Resources/
  matting/  adjust_mask/  smart_crop/
  common_attachment/  deepagent/  .backup/
  agent_adoption_ledger.db
```

没有读取上面的 SQLite ledger、备份目录或 DeepAgent 会话内容。`draft_settings` 是 INI，不能因为 JSON 解析失败就判定损坏；`draft.extra` 是二进制。本轮保留解析失败状态，没有加载编解码 DLL。

四个明文 `draft_content.json` 的关键发现：

| 字段 | 实际值/示例 | 判断 |
| --- | --- | --- |
| `canvas_config.width / height` | `1080 / 1920` | 工程画布；不证明最终文件一定按此分辨率导出 |
| `fps` | `30` | 工程帧率；不等于已验证的导出帧率 |
| `duration` | 组合3：`127667000` | 微秒时间线长度，127.667秒；与最新批次 Manifest 一致 |
| `config.export_range` | `null` | 存在导出范围配置槽位，没有导出任务或触发指令 |
| `render_index / track_render_index` | 片段中的整数 | 渲染层级/排序线索，不是导出 RPC |
| `render_index_track_mode_on` | `false`（复合草稿中亦存在） | 时间线渲染配置，不是后台任务开关 |
| `free_render_index_mode_on` | `false` | 同上 |
| `materials.drafts[0].draft` | 嵌套工程 | 存在复合片段，不能按简单视频列表渲染 |
| `draft_meta_info.json: draft_id` | 每个明文样本有独立 UUID | 草稿登记身份，需与工程内 `id` 区分 |
| `draft_meta_info.json: draft_new_version` | `164.0.0` | 草稿格式标记，不是安装程序版本 |
| `draft_meta_info.json: tm_duration` | 与对应时间线长度一致 | 元数据时长，不是导出状态 |

明文样本时长：组合2 **221.768s**、组合3 **127.667s**、组合4 **115.901s**、组合5 **81.535s**。

组合2～5的顶层工程 `id` 全部为 `91E08AC5-22FB-47e2-9AA0-7DC300FAEA2B`，但 `draft_id` 不同。这是实测身份复用现象；不能用该工程 `id` 作为批次成片唯一键。未来应核对既有 `batch_id + video_index + composition_signature + draft_path`，并额外校验草稿登记身份和快照，不能仅凭草稿名或工程 `id` 绑定输出。这里只记录风险，没有修改生成器。

`组合1-自动合成` 的 content/meta 文件不能直接按 UTF-8 JSON 解析，文件头也不以 JSON 对象开始；仅可判定它们当前为非明文 JSON，**未确认封装/加密算法，没有尝试解密**。`自动合成_120248` 的顶层没有 `draft_content.json`；未进一步解析 `Timelines/`，不能声称这个草稿没有时间线。

在已解析的配置键中，没有找到可用于提交导出任务的 `output`/MP4目标路径字段；也没有找到“修改某字段就会自动渲染”的证据。全局 `Config/Export.ini` 仅有：

```ini
[General]
userFirstVideoEnhanceExport=false
```

以上是样本内的否定结论，不代表所有剪映文件或所有版本都不存在该能力。证据：[草稿检查结果](research/jianying_export/draft_inspection.json)。

### A2. Electron/CDP：本机是 Qt + CEF

可见主窗口标题为“剪映专业版”，窗口类为 `Qt622QWindowIcon`。安装目录有 Qt6组件、`CefCreator.dll`、`cef/`；子进程包含 `--type=renderer`、`--type=gpu-process`、`--type=utility`、`Chrome/121.0.6167.86` 和 CEF用户数据目录。**这些证据支持 Qt原生宿主 + CEF网页的混合结构，不能直接套用 Electron 的全窗口 DOM 控制假设。**

进程里未发现 `--remote-debugging-port`；但一个父进程的命令行为空，不能据此声称已排除所有启动参数。CEF目录也未发现 `DevToolsActivePort`。

CEF本身支持 `remote_debugging_port` 和同名命令行开关，这是框架能力；**剪映11.5是否接收/转发该开关仍未验证**。[CEF官方定义](https://raw.githubusercontent.com/chromiumembedded/cef/master/include/internal/cef_types.h)

本轮没有带调试参数新启动剪映：这会改变当前运行状态，并可能导致配置/草稿自动写入，不属于本次只读研究。没有篡改快捷方式、启动参数或注册表。

对当前两个 loopback监听端口，执行了 `/json/version`、`/json/list` 的 GET POC：

| 端口 | 返回 | CDP判断 |
| --- | --- | --- |
| `127.0.0.1:7264` | 每个请求2秒超时 | 未识别为CDP；超时不能证明它不支持其他协议 |
| `127.0.0.1:63733` | HTTP `401`，JSON错误对象 | 未取得CDP握手或 target列表；不继续鉴权 |

没有取得 `webSocketDebuggerUrl`，因此没有连接CDP/WebSocket、没有读取页面DOM、没有执行 `Runtime.evaluate` 或枚举网页中的账号数据。窗口信息由只读 `EnumWindows` 获得；它不提供DOM。即使未来CDP连通，仍需证明网页能调用原生导出服务，CDP连通本身不代表可导出。

证据：[进程/端口](research/jianying_export/system_snapshot.json)、[窗口](research/jianying_export/windows.json)、[HTTP POC](research/jianying_export/http_poc.json)。

### A3. 本地通信与内置CLI

进程快照中，主工作进程 PID `37376` 拥有三个TCP监听：

| 地址 | 本轮动作 | 结论 |
| --- | --- | --- |
| `127.0.0.1:63733` | 只读GET | 存在要求授权的HTTP响应，协议业务归属未确认 |
| `127.0.0.1:7264` | 只读GET | 未取得HTTP响应；用途未知 |
| `192.168.0.29:25713` | 仅记录监听 | 未连接LAN入口，不猜测用途 |

本次未发现归属这些剪映进程的UDP端点。PID/端口是当时快照，不应硬编码为生产配置。

子进程启动参数包含 `--external-video-source-endpoint=\\.\pipe\videoeditor-runtime-37376`，并使用 Mojo channel句柄。这是**内部视频源/IPC线索**，不是已确认的导出入口。管道名称枚举另外发现 `jianying_data_sync_server__64400 / __74040 / __64401`；未确定这些管道的进程归属，也未在当时枚举结果中找到上述 `videoeditor-runtime` 管道。没有连接管道、写请求文件或捕获通信载荷。

安装包 `Resources/canvas_agent/skills/_lib/host-capability-client.mjs` 提供如下契约：

| 契约 | 静态发现 | 是否调用 |
| --- | --- | --- |
| `GET /api/custom-agent/host-capabilities/manifest` | 能力清单入口 | 在现有loopback监听做无凭据GET，未得到清单 |
| `POST /api/custom-agent/host-capabilities/invoke` | capabilityId/requestId/input 调用契约 | 没有调用 |
| HTTP / named-pipe / unix-socket / file-rpc | 客户端支持四种 transport | 仅静态检查；不能证明本机全部启用 |
| Bearer授权 | 客户端要求宿主注入的授权信息 | 未读取进程环境、token值或账号文件 |

`63733` 对探测路径统一返回401；**401可能发生在路由匹配前，不能证明 manifest路由实际挂载在这个端口**。源码存在契约与运行服务返回401是两组不同证据，尚不能建立确定映射。首次探测共6条GET、无业务请求；保存的重跑脚本已增加遇401/403停止该端口后续请求的限制。

安装包另有 `runtime/videoeditor-service.mjs` 和 `videoeditor_addon.node`。源码加载 addon 的 `initialize / invoke`，通过服务端点组织任务；本轮没有加载 addon、DLL或启动服务。安装目录的 `videoeditor.dll`、`ffmpeg.exe` 也只是组件存在证据，不表示存在“输入草稿JSON即可输出MP4”的公开接口。

#### 内置CLI POC：最重要的发现

1. `jianying-agent-cli.exe --help` 成功，展示草稿子命令 `fetch-feishu-doc / query-content / plan-patch / validate-patch / apply-patch`。帮助中没有视频导出命令。没有运行其中任何子命令。
2. `canvas_agent/runtime/app-server.mjs` 内存在导出预览的实际调用代码，参数如下，**这是静态引用，本轮未执行这条导出调用**：

```text
lyra-cli draft export --ref <draftRef> --output <final_preview.mp4> --timeout <seconds>s
```

3. `lyra-cli.exe --help`、`draft --help`、`draft export --help` 均返回exit code 1及：

```json
{"err_category":"runtime","err_code":-100015,"err_msg":"unauthorized host process","recovery":"upgrade_or_switch_path","result":null,"severity":"failed"}
```

所有命令都以 `--help` 结束，没有传工程路径、`--ref`、输出位置或执行真实导出。初次POC记录了三次帮助失败；重跑脚本已改为第一次出现宿主授权拒绝即停止，不继续尝试其它调用。

4. 安装包二进制静态字符串包含 `draft export is disabled in this build`。**这是限制线索，不能单凭字符串认定每个导出分支都必定禁用**；本机已经在宿主身份检查阶段停止，没有执行到导出处理器。

因此可以确认：厂商安装包包含内部导出调用路径；无法确认：外部程序可否获得厂商支持的宿主执行权限、当前构建是否允许该调用、任意既有草稿能否渲染。禁止伪装宿主、注入DLL、patch校验、获取内部运行token或绕过账号权益。

证据：[CLI帮助POC](research/jianying_export/cli_help_poc.json)、[安装包静态检查及文件SHA256](research/jianying_export/static_inspection.json)。

### A4. 开源方案是否真正解决本机问题

| 方案 | 一手资料/本机源码核对 | 本轮评价 |
| --- | --- | --- |
| 已安装 pyJianYingDraft 0.3.0 | 本机 `jianying_controller.py` 的导出实现调用 `.Click()`、激活/置顶窗口，并移动结果文件 | 仍是UI自动化，不符合本任务；未导入或执行Controller |
| jianying-tool 0.5.0 | 作者说明 Windows导出驱动对话框，依赖截图模板和合成输入 | MCP/CLI包装没有消除模拟点击，排除 |
| jianying-headless | 作者明确原生引擎导出面向macOS；Windows分支另走FFmpeg且能力有限 | 不能当成本机Windows剪映原生导出的现成方案 |

来源：[pyJianYingDraft上游Controller源码](https://raw.githubusercontent.com/GuanYixuan/pyJianYingDraft/main/pyJianYingDraft/jianying_controller.py)、[jianying-tool作者说明](https://pypi.org/project/jianying-tool/)、[jianying-headless作者README](https://github.com/mcncarl/jianying-headless)。本机Controller行号及哈希在[证据](research/jianying_export/package_controller.json)，与当前上游行号不同，应以本机文件为准。没有安装、克隆或运行这些第三方方案。

“export draft”常指生成/登记草稿文件；“MCP支持export”也可能只是包装对话框自动化。必须核实最终是否生成MP4以及使用何种执行机制，不能根据工具名称认定可用。未找到适用于本机版本的公开、可直接调用的厂商导出API文档；这不是对所有未公开能力的否定。

## B. 可行性

| 路线 | 当前证据强度 | 当前能否接生产 |
| --- | --- | --- |
| 修改草稿导出字段触发渲染 | 只有配置/排序字段，未发现任务触发契约 | 否 |
| 现有端口连接CDP | 未取得握手、DOM或WebSocket端点 | 否 |
| `--remote-debugging-port` 启动实验 | CEF有此能力，剪映转发行为未验证；本轮不重启 | 未验证 |
| 内置 `lyra-cli draft export` | 安装包确有调用代码；外部帮助请求被宿主授权拦截 | 否，等待厂商支持的接入途径 |
| Host Capability接口 | 找到契约；未取得manifest、capabilityId清单和导出能力 | 否 |
| 视频IPC/同步管道 | 仅名称/启动参数，未确认消息协议或导出用途 | 否 |
| pyJianYingDraft / jianying-tool 导出 | UI模拟输入已确认 | 不符合本任务 |
| 独立本地FFmpeg导出后端 | 可作为另一个研发方向；不是剪映原生引擎 | 只值得先做能力覆盖分析，未实现 |

本轮没有证明无界面导出绝对不可能；证明的是**目前没有满足本次约束并经过本机验证的可用接口**。

## C. 风险

- **身份/权限限制**：HTTP401和CLI宿主拒绝都是实际边界。需要厂商提供支持的执行途径；不通过读取token、账号文件、注入或patch继续。
- **版本兼容性**：内置CLI和私有RPC的契约可能变化；二进制已有构建限制提示。厂商打包组件不等于对第三方承诺稳定API。
- **CDP覆盖有限**：Qt主编辑器不保证有网页DOM。网页能连接也未必能操作原生时间线或导出引擎。
- **草稿格式混合**：明文、非明文JSON、二进制附件及嵌套时间线同时存在；不能批量改字段或统一解码后覆盖源文件。
- **输出绑定错误**：多个样本复用工程`id`，草稿名也可能跨批次重复；不能依名称/ID猜批次。
- **画面和声音损失**：组合3有18条轨道、3条抠像材料、44条效果材料、43条文字材料及1个复合草稿，还包含滤镜/蒙版等结构。简单concat/transcode无法证明视觉等价；数量是材料表计数，不等于全部实际使用。
- **状态误报**：调用受理、窗口关闭、文件出现均不能替代导出成功验证。后续必须检查进程结果、文件稳定性、完整可解码性、时长/尺寸/音轨，并按既有登记流程绑定；本轮没有创建或登记新MP4。

## D. 推荐方案

**保留现有链路和人工剪映导出回退；Lyra路线已记为 `LYRA_EXPORT_UNAVAILABLE`，停止继续投入。** 本轮不改现有`pyJianYingDraft → 草稿 → MP4登记 → Planner/Worker`的代码或数据库。

以下为第一轮备选方案的历史记录，均未实现；不构成本次继续执行的任务。Lyra条目已停止，其他路线本次不开展：

1. **Lyra停止。** 本次未取得厂商支持的对外导出契约或启用入口，外部帮助请求仍被拒绝。没有联系厂商、没有开发适配器，不再尝试内部token、宿主身份或权限机制。
2. **CDP仅作为有限验证。** 如果另行安排隔离环境启动实验，使用独立测试配置和小草稿，先验证调试参数是否生效、target类型及Qt/CEF边界，只读检查DOM和接口名。当前生产剪映保持原状；连接成功后也不自动触发导出。
3. **如果官方入口不可用，评估独立本地渲染器。** 先只读建立起号工程的能力清单：剪切、拼接、缩放、绿幕/色度抠像、字幕样式、关键帧、蒙版、复合片段、特效/滤镜及音频同步。以受支持的有限组合建立独立计划契约；未知效果拒绝渲染，保留原草稿供人工导出。不能宣传“兼容任意剪映草稿”。
4. **真正导出验收属于下一任务。** 只有后续明确允许生成小样本MP4时，才做3～5条短视频、逐帧/关键帧及音频对照，并通过现有登记校验接口。不要修改生成器、startup_pipeline、Planner或Worker来绕过缺失的渲染能力；本轮不会进入该阶段。

不推荐继续沿截图模板/UIA模拟点击路线，也不推荐仅为旧Controller而更换或降级生产剪映。

## E. 是否值得继续开发

**Lyra当前不可用，停止这条路线的研究和开发，不将其作为生产依赖。**

- 已确认厂商签名来源及内部调用线索，但未确认正式对外支持；当前宿主授权拒绝没有解除。
- 是否必须运行剪映、是否必须登录的必要条件仍未知；没有通过干预运行状态或读取凭据来验证。
- 原报告的CDP/独立FFmpeg备选不在本次继续范围，不启动新实验或替代开发。

最终结论：**LYRA_EXPORT_UNAVAILABLE；停止继续投入。自动MP4导出未实现、未验收，原阻塞仍然存在。**

## POC复现、保护与验收记录

所有新增文件均在本报告和 `research/jianying_export/`；没有修改HANDOFF或任何生产功能。未启动Streamlit、未执行生产迁移/验收脚本，以避免无关服务和数据库写入。

固定复现入口（本机当前版本；进程快照必须重新采集，不复用过期端口）：

```powershell
$researchPython = (Get-Content -LiteralPath config.json -Raw | ConvertFrom-Json).paths.python_executable
& .\research\jianying_export\capture_system.ps1
& $researchPython -X utf8 -B research/jianying_export/readonly_poc.py baseline
& $researchPython -X utf8 -B research/jianying_export/readonly_poc.py inspect
& $researchPython -X utf8 -B research/jianying_export/readonly_poc.py windows
& $researchPython -X utf8 -B research/jianying_export/static_inspection.py
& $researchPython -X utf8 -B research/jianying_export/cli_help_poc.py
& $researchPython -X utf8 -B research/jianying_export/readonly_poc.py verify
```

系统进程和可见窗口查询需要具备系统读取权限；本轮沙箱普通查询失败后仅提升这些只读查询的权限并成功，没有扩大业务操作权限。重跑会覆盖研究证据，需保留本次证据时先复制研究目录；不复制生产素材。

验证结果：

| 项目 | 结果 |
| --- | --- |
| 3个新增Python研究脚本 | AST语法检查通过；py_compile另记录在validation.json |
| HTTP请求契约 | 保存记录全部为GET，无导出/发布POST |
| CLI请求契约 | 保存记录全部以`--help`结尾，无工程/输出参数 |
| 受保护文件SHA256前后对比 | **217个文件，修改0、新增0、删除0** |
| 已检查草稿配置SHA256前后对比 | **19个配置，变化0** |
| 生产数据库/索引/模型 | 本轮没有写入、重建或删除，也没有做全文件哈希扫描 |
| 真实导出/发布 | **0** |
| 账号密码、token、Cookies | 没有读取值；没有执行auth/login命令或检查进程环境/内存 |

217个文件覆盖已安装pyJianYingDraft包，以及项目`startup_pipeline/`、`publish_planner/`、`xiaovcat_adapter/desktop_worker/`和`jianying_auto/`中的非缓存文件。草稿保护只覆盖本轮实际检查的19个配置，不冒充所有草稿/全部素材的完整性审计。[保护核验](research/jianying_export/protection_check.json)

研究产物索引：`system_snapshot.json`、`windows.json`、`draft_inspection.json`、`http_poc.json`、`cli_help_poc.json`、`static_inspection.json`、`package_controller.json`、`protected_before.json`、`protection_check.json`、`validation.json`，以及4个复现脚本。报告中“已发现/已验证”以这些本机证据为准，“后续/建议”不表示已经开发。
