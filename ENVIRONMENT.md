# 环境配置文档 (ENVIRONMENT.md)

### 2026-10-07 17:49：2060独立真实发布追加验收PASS

`REAL_PROVIDER_PUBLISH_ON_2060_PASS`。用户新增最多1条正式任务授权后，实时核验夏禾OPEN/ONLINE，选择尚无PublishJob的READY成片 `STARTUP-94affa8d-6268-4e22-adaf-58f81f8d4929`。2060全片复验通过，新Export=0；新PublishJob `4026d43a-b45d-4ec2-9bae-b1564d3d350f` 由2060本地视频直接上传，视频/封面各1次、正式POST=1。官方scheduled/success，Task `6ac613e9799bed4c0357c33b`、Video ID `7693858927401848099`；Server已回写SCHEDULED_QUEUED，排期2026-10-08 09:08 +08，尚非公开PUBLISHED。

Server上传0且保持DISABLED；活动48次Mutex采样全持锁、最大执行并发1、无Render重叠；本轮没有同期Render，WAIT未重测。历史296条PublishJob/58条ProviderJob及6授权逐行未改，长期托管仍全部关闭；旧夏竹花开风险失败任务未重发。一次完成后停止真实测试，Worker READY、租约释放。详情及16项报告 `media_execution/runtime/real_provider_validation_20261007_additional/REPORT.md`，本条为最新状态，下方此前FAILED_ACCOUNT_RISK记录保留为上一次验收历史。


### 2026-10-07媒体执行部署环境

`RENDER_PUBLISH_2060S_EXECUTION_HANDOFF_READY`。正式执行节点WORKER-2060S-01 / DESKTOP-9VQ76D3 / 192.168.1.89，Jianying 5.9.0.11632及既有签名/SHA限定，Python 3.11，蚁小二CLI 3.2.26、本机客户端4.0。沿用 `D:\JianyingRenderWorker\venv\Scripts\python.exe`，代码 `D:\JianyingRenderWorker\Releases\2060-HANDOFF-20261007\code`，配置 `Resident\media_execution.config.json`，安装记录 `Resident\media_execution.install.json`，健康与Dry Run证据 `Resident\media_execution\`。XUNZHEN_RENDER_WORKER任务Running、心跳READY，旧独立Render/Publisher执行任务停用。

部署方式LOCAL_BOOTSTRAP_AND_REMOTE_FINALIZE；无需Server主动进入2060 SMB/WinRM。2060主动访问192.168.1.126:8766（现有IP白名单+本机DPAPI Bearer），主动读取/写入Server共享。安装包 `deploy/2060_handoff_release/` 同步到 `\\PC-20260617GEOP\RenderOutput\2060_handoff_release`，包含代码、迁移、依赖清单、配置模板、install/start/health/rollback脚本、manifest及SHA256SUMS；包中没有API凭据/生产库/生产素材。凭据仅按用户授权加密迁移至2060用户自己的.yxer/config.json，绑定2060本机clientId；不使用Server的clientId。

本机CLI doctor/schema、只读accounts及活跃客户端进程验证通过。现场网络为物理Realtek默认路由，无激活虚拟接口或代理，ONLINE/DIRECT_CONFIRMED；网络状态每次重新检查，未知/VPN/Proxy会封发布门，不修改网络规避验证。6个正式账号仍停用/待处理，缓存ONLINE不代表风险验证完成，`REAL_PROVIDER_PUBLISH_VALIDATION = FAILED_ACCOUNT_RISK`。

Server保留原8502、原生产Planner启动任务及LAN控制服务启动任务，角色CONTROL_PLANE；验收后Server Provider Upload=DISABLED，YIXIAOER_PUBLISH_WORKER_SERVER_01任务Disabled。2060单执行槽真机与恢复通过，最终节点代码68项回归通过。Windows交互登录与蚁小二客户端需要保持运行；本次验证的是Worker进程/Server服务重启，未验证整机重启。IMPLEMENTED/WIRED/DEPLOYED/VALIDATED均PASS，真实Provider发布已尝试1次但返回账号风险，未通过。完整记录 `media_execution/runtime/finalization_20261007/REPORT.md`。

本轮追加真实发布验收：用户指定“夏竹花开”并确认已完成官方验证。实时CLI核验稳定账号 `6ac4b574faa99a4ec8670bb3` 后，选用其尚未创建PublishJob或提交的既有成片 `STARTUP-3d90a6f4-5783-468f-80c3-d1d55c86b7af`（122.033秒），2060复验SHA/全片decode通过、与已有归档相同，新增Export=0。按原额度和时段创建唯一新PublishJob `f69e3602-e088-47ec-b9a5-6a27f92dd062`，计划10月8日09:18，未重新开启长期托管。

2060本机真实上传视频1次、封面1次，validate与LOCAL dry-run通过，正式POST恰好1次。Provider TaskSet `0ee25a0c-775a-4dc0-87d1-a6e3251ee82f`、Task `6ac607c1e888b10a7efba166` 返回新的官方账号风险失败：仍要求到创作者中心单独发布并完成验证。Job为FAILED、无Video ID、没有成功进入平台定时队列；不能将预定10月8日09:18描述为已经安排成功。收到失败回执时账号重新BLOCKED_RISK，原任务不重发；用户随后再次确认验证后的账号状态见下。**REAL_PROVIDER_PUBLISH_VALIDATION = FAILED_ACCOUNT_RISK**，执行交接状态仍为READY。

实测补齐客户端异步执行保护：CLI返回任务ID后，2060继续持有执行槽/Mutex/busy直到只读回执确认定时队列或失败；Worker中断后，Server对未确认结束的Provider执行保留重任务门，禁止另一个Render/Publish或Archive进入。只读终态确认后才释放；账号失败只封该账号。另修复单独手工确认的新计划不被旧托管暂停错误阻断，以及LocalOperator预览和已核验恢复门的保持。60项最终本机回归通过；最终代码部署到2060并重新校验297个代码文件SHA，节点专项结果见node-provider-final.stderr.txt。

真实验收前后逐行对比：原295条PublishJob、57条ProviderJob及6份长期授权完全相同；仅新增上述1个PublishJob/ProviderJob。最终计数PublishJob296、ProviderJob58、submit_attempt总51（新增1）；长期托管enabled=0。切换主体阶段旧后台曾更新21条Provider遥测/对账行，独立记录。最终证据 `media_execution/runtime/finalization_20261007/FINAL_AUDIT.json`；官方CLI证据 `outputs/lan_render/2060_acceptance_20261007_v2/real-provider-evidence/`。

用户随后再次明确“夏竹花开和夏禾，完成了验证”。2026-10-07 17:28（Asia/Shanghai），2060官方CLI doctor及账号查询通过：两者稳定ID匹配、ONLINE、未冻结/锁定。原后台只读恢复请求均CHECKED，账号门恢复OPEN；6份长期托管授权保持enabled=0、旧失败Job和POST=1保留。此次复查新增PublishJob/Upload/Submit均0，不把账号门OPEN描述为真实发布已成功。本轮最多1个新正式PublishJob的额度已使用；若另做真实验收，须有追加范围授权。证据 `two_accounts_recovery.json` 与 `FINAL_AUDIT.json`。

> 项目：视频素材检索工具
> 最后更新：2026-09-26

---

## 1. 当前开发环境

**P1-1 更新（2026-09-26）**：生产环境保持原样；新增隔离 `.venv-cuda-test`，已在 Python 3.14.7 + PyTorch 2.11.0+cu128 中验证 RTX 3060 和原 MobileNetV2 推理。未安装系统 CUDA Toolkit，未更新驱动或修改启动配置。后文关于“Python 3.14 无法安装 CUDA 版 / 最高支持 Python 3.12”的旧限制已失效，不能继续作为当前兼容性结论；本次只验证 embedding 所需依赖，未验证全项目 GPU 运行。详见 [CUDA_TEST.md](CUDA_TEST.md)。

### 硬件
- CPU: 14代 Intel i5
- GPU: NVIDIA GeForce RTX 3060 12GB (**当前未使用**)
- 内存: 32GB
- 系统: Windows

### 软件
- Python: 3.14.7 (豆包沙箱内置，路径见下)
- NVIDIA驱动: 616.92
- CUDA: 未安装（PyTorch是CPU版）

### Python解释器路径
现统一保存在 `config.json` 的 `paths.python_executable`。两个 BAT 入口通过 `launch.ps1` 读取，脚本不再写死解释器路径。
**注意**: 这是豆包沙箱的Python，不是系统Python。新电脑部署时应安装独立的Python 3.12。

---

## 2. 从零部署步骤（新Windows电脑）

### 2.1 安装Python 3.12

**必须用3.10~3.12，不要用3.13/3.14**（PyTorch CUDA版最高支持3.12，且部分依赖不兼容3.14）

1. 访问 https://www.python.org/downloads/release/python-3127/
2. 下载 Windows Installer (64-bit)
3. 安装时**务必勾选 "Add Python.exe to PATH"**
4. 验证: `python --version` 显示 3.12.x

### 2.2 （可选）安装CUDA（如果要用GPU）

当前项目用CPU版PyTorch，不强制需要CUDA。如果未来要GPU加速：
1. 安装 CUDA Toolkit 12.1 (cu121)
2. 安装对应版本的PyTorch: `pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121`
3. 验证: `python -c "import torch; print(torch.cuda.is_available())"` 输出True

### 2.3 复制项目文件

将 `video_search_tool` 文件夹复制到目标位置，例如 `D:\video_search_tool\`

**必须包含**:
- video_search.py
- config.json
- requirements.txt
- models/ 目录（317MB，含whisper和人脸模型）
- bin/ffmpeg.exe（84MB）
- 启动工具.bat

**不需要复制**（新素材从头建库）:
- video_index.db / video_index_fixed.db（30GB+）
- faiss_index.bin（7.6GB）
- faiss_meta.pkl（270MB）
- thumbnails/（生成中）

### 2.4 安装依赖

```cmd
cd /d D:\video_search_tool
pip install -r requirements.txt -i https://mirrors.huaweicloud.com/repository/pypi/simple/
```

依赖清单（requirements.txt）:
```
streamlit==1.64.0
opencv-python==5.0.0.93
torch==2.14.0
torchvision==0.29.0
pillow==12.3.0
numpy==2.5.3
faster-whisper==1.2.1
rapidocr-onnxruntime==1.2.3
opencc-python-reimplemented==0.1.7
faiss-cpu==1.15.1
imageio-ffmpeg==0.6.0
ImageIO==2.37.4
ctranslate2==4.8.2
onnxruntime==1.30.0
tokenizers==0.23.2
protobuf==7.36.2
PyYAML==6.0.3
tqdm==4.70.1
requests==2.34.2
altair==6.3.0
pandas==3.0.6
pyarrow==25.0.1
```

**注意**: torch==2.14.0在Python 3.12上可能没有对应版本。如果安装失败，改用:
```
pip install torch==2.4.0 torchvision==0.19.0 --index-url https://download.pytorch.org/whl/cpu
```
MobileNetV2特征提取不依赖特定PyTorch版本，2.x都可以。

### 2.5 配置素材路径

用记事本打开 `config.json`:
```json
{
  "video_folder": "D:\\你的素材目录"
}
```
路径用双反斜杠 `\\`。

### 2.6 初始化数据库（全新素材）

```cmd
cd /d D:\video_search_tool
python init_database.py
```

### 2.7 处理视频（抽帧+字幕）

```cmd
python add_new_videos.py
```
- 自动递归扫描素材目录
- 每秒抽1帧，提取MobileNetV2特征
- faster-whisper转写字幕
- 1小时视频约需6分钟（抽帧3分钟+转写3分钟）
- 可以中途停止，下次自动跳过已处理的

### 2.8 构建FAISS索引

```cmd
python build_faiss.py
```
- 从数据库加载所有帧特征
- 构建IndexFlatIP索引
- 159万帧约需5分钟，占用7.6GB内存

### 2.9 启动服务

```cmd
启动工具.bat
```
或:
```cmd
python -m streamlit run video_search.py --server.headless true --server.port 8501
```

浏览器打开: http://localhost:8501

---

## 3. 环境变量

正常启动不需要特殊环境变量。可选 `VIDEO_SEARCH_CONFIG` 指定隔离配置；相对路径仍按项目目录解析。所有配置项及隐藏依赖见 PATHS.md。

FFmpeg 通过统一配置加入 PATH：
```python
from config import configure_runtime_paths
configure_runtime_paths()
```
`paths.ffmpeg_executable` 默认是项目目录下的 `bin/ffmpeg.exe`。网页裁剪命令使用其完整路径；现场缩略图仍由 OpenCV 生成，算法未变。历史 openai-whisper 调用也依赖 PATH 中的 ffmpeg。

---

## 4. 模型文件说明

### models/ 目录内容

| 文件 | 大小 | 来源 | 用途 |
|------|------|------|------|
| model.bin | 138MB | faster-whisper base | 语音转字幕 |
| config.json | 2KB | faster-whisper | 模型配置 |
| tokenizer.json | 2.1MB | faster-whisper | 分词器 |
| vocabulary.txt | 449KB | faster-whisper | 词表 |
| base.pt | 138MB | openai-whisper base | 备用（实际未用） |
| face_detection_yunet.onnx | 227KB | OpenCV Zoo | 人脸检测 |
| face_recognition_sface.onnx | 37MB | OpenCV Zoo | 人脸识别 |

### MobileNetV2权重
- **不包含在models/目录中**
- 由torchvision首次运行时自动下载
- 当前权重缓存文件为 `mobilenet_v2-7ebf99e0.pth`（现有 DEFAULT/V2）。`paths.torch_home` 留空沿用用户原有 torch 缓存，配置后使用该目录下的 `hub/checkpoints/`。
- 离线环境需提前下载好放到缓存目录

### 下载地址
- faster-whisper base: https://huggingface.co/Systran/faster-whisper-base
- YuNet: https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet
- SFace: https://github.com/opencv/opencv_zoo/tree/main/models/face_recognition_sface

---

## 5. 验证部署

### 5.1 验证依赖
```cmd
python -c "import torch, cv2, faiss, streamlit, faster_whisper; print('所有依赖OK')"
```

### 5.2 验证GPU（如果装了CUDA版）
```cmd
python -c "import torch; print('CUDA可用:', torch.cuda.is_available())"
```

### 5.3 验证服务启动
```cmd
python -m streamlit run video_search.py --server.headless true --server.port 8501
```
看到 `Local URL: http://localhost:8501` 即成功。

### 5.4 验证搜索
1. 打开 http://localhost:8501
2. 切换到"索引状态"标签，确认有视频/帧/字幕数据
3. 上传一张截图测试以图搜视频

---

## 6. 常见环境问题

### Q: pip安装torch失败
A: Python版本太新（3.13/3.14），换Python 3.12。或用CPU版:
```
pip install torch==2.4.0 torchvision==0.19.0 --index-url https://download.pytorch.org/whl/cpu
```

### Q: 提示缺少ffmpeg
A: 确认bin/ffmpeg.exe存在。核心功能不依赖系统ffmpeg，只有导出裁剪命令时用到。

### Q: MobileNetV2下载失败
A: 先核对配置的 torch 缓存目录与现有 V2 权重文件 `mobilenet_v2-7ebf99e0.pth`，不要用 V1 权重替换已验证模型。此次路径清理没有下载或替换模型。

### Q: FAISS导入报错
A: faiss-cpu需要Visual C++ Redistributable。安装 https://aka.ms/vs/17/release/vc_redist.x64.exe

### Q: 内存不足
A: 32GB内存是最低要求。FAISS索引7.6GB + 系统 + 浏览器，16GB会频繁MemoryError。

### Q: 数据库只读错误
A: 复制一份数据库为新文件名使用（如video_index_fixed.db），并修改代码中的DB_FILE路径。
