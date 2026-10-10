# 本机交互式 Xiaovcat Worker V0.3

本轮结论：`XIAOVCAT_DESKTOP_WORKER_PASS`。只表示当前版本小V猫的提交前 UI dry-run 已真实跑通，不表示真实发布已验证。唯一主通道 **UIA**，唯一 fallback **KEYBOARD_ASSISTED**。没有视觉点击、CDP 控制实现或平台私有 API。

## 运行

从已登录、已解锁的 Windows 桌面双击项目根目录 `小V猫自动化测试.bat`，或 `xiaovcat_adapter/desktop_worker/run_worker.bat`。内部读取项目 `config.json` 的 Python 路径，不硬编码解释器路径。不依赖 Codex computer-use RPC。

运行前把小V猫的“发单条视频”表单保持空白。已有视频、账号或文字（包括上一次 POC）会安全转 `NEEDS_MANUAL`，**不会自动清空用户表单**。先自行保存/清理当前表单后再复跑。运行期间不要抢焦点、锁屏、操作表单或切换 Windows 用户。

Runner 只做以下固定流程：连接/启动 → 验证 Session/桌面/进程路径 → UIA2/UIA3 ControlView/RawView 与本机端口诊断 → 选择已识别的发布导航 → 标准文件选择器 → 固定安全 MP4 → 一个可见在线账号 → 固定标题/简介（通用及账号字段） → 所有文字再次回读 → 识别“一键分发” → STOP。没有调用最终按钮的实现。每次动作前重新校验 `real_publish_enabled=false`，配置改成 true 也拒绝。

测试文件限定为 `auto_remake/tests/test_videos/合成 参考视频.mp4`，不扫描素材库，不上传生产素材，不选择其它文件。本轮文件 MPEG4/mp4v 编码不支持小V猫预览，但已经出现视频控件及测试封面；不能据此保证平台接受此文件。

日志/控件树/截图都写入 `xiaovcat_adapter/results/desktop_worker_v03/run_<时间>/`，不覆盖历史 run。关键截图为 `01_main`、`02_publish_page`、`03_video_loaded`、`04_account_selected`、`05_text_filled`、`06_before_submit`。`report.json` 是机器报告；`worker.jsonl` 记录状态迁移。账号数据来自可见 UI，不读取密码/Cookie/token/session 存储。

## 可选测试启动器

当前小V猫原进程无测试参数，本轮没有关闭或重启它。UIA 已经可用，因此无需为主流程重启。

如果专门想验证启动参数，先自行正常退出小V猫，再双击项目根目录 `启动小V猫-自动化测试.bat`。只在确认没有现有进程、9223 未占用时启动原 EXE：

```
--force-renderer-accessibility
--remote-debugging-address=127.0.0.1
--remote-debugging-port=9223
```

测试启动器只启动，不操作表单；之后运行普通测试 Runner。现有进程存在时会说明需自行关闭，绝不杀进程。原 EXE、配置、快捷方式保持不变。CDP 只允许属于当前 Session 小V猫进程、仅回环监听的 `/json/version`、`/json/list` 元数据读取，不读 storage/cookies/页面私有接口。任何非回环绑定/归属不明端口直接拒绝。远程调试具有本机访问风险，仅供测试，不建议日常带参数运行。

## 通道边界与停止策略

Chromium 会延迟生成 Accessibility 页面树：本轮首次只拿到 10/14 个节点，激活真实窗口后复测拿到 Chrome 页面的按钮/输入/树节点。这里只能证明“本机直连 + 激活 + 重探测有效”，不能单独归因给某一次激活调用或启动参数。本轮 `--force-renderer-accessibility` 效果未验证；9223 无监听，不等于 Electron 不支持 CDP。

UIA 不完整/超时、焦点丢失、账号结构变化、已有草稿、启用自动提取、原生未知弹窗、页面未知对话框、更新/登录失效/上传失败提示都停止。只有“选择账号”的已知模态结构在账号步骤中允许，只有归属验证的标准打开文件对话框在选文件步骤中允许。已知面板关闭动画期间轮询确认消失；不能盲点继续。未知提示真实出现的覆盖尚待扩大，当前有模拟安全回归。

Keyboard fallback 只对已验证的空白标题/简介字段先设置焦点并比较实际焦点，再 Unicode SendInput，最后 UIA 回读。它不发送 Enter/Space，不读写剪贴板，不提供通用点击或任意键序列。主通道无法提供字段定位/回读时 fallback 也会停止；不退化为坐标脚本。`vision_fallback.py` 仅导出证据截图，不启用视觉控制。

本轮普通窗口、移动后窗口、最大化下都成功重新定位四个文字字段及最终按钮，并恢复原位置。当前 DPI=96（100%）；未切换系统 DPI，不声称其它缩放比例已验证。

## 回归

用项目配置中的 Python 执行：

```
python -m unittest discover -s xiaovcat_adapter/desktop_worker/tests -v
python -m unittest discover -s xiaovcat_adapter/tests -v
python -m xiaovcat_adapter.desktop_worker.worker --probe-only
```

前两项是模拟/临时数据测试，无桌面点击。第三项只做实际桌面探测，不改表单（若无进程会按测试参数启动）。布局验证仅用于已经完成本轮测试表单的窗口：`python -m xiaovcat_adapter.desktop_worker.verify_layout --output <已存在的run目录>`。日常操作不调用布局验证。

不接 operations.db 队列，不开发批量发布、发布中心、手机端或真实发布，不改检索/合成/分析系统。
