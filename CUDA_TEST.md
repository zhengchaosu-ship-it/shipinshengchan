# P1-1：独立 CUDA 环境验证

日期：2026-09-26。范围：仅验证环境、原 embedding 模型和 100 张合成图片；任务已完成并停止。

## 结论

RTX 3060 已在独立测试环境中实际执行 CUDA 张量运算和 MobileNetV2 推理。生产环境保持 CPU 版，网页与录入脚本没有切换解释器或修改推理逻辑。本次不代表完整项目已迁移至 GPU。

## 当前环境与问题分析

| 项目 | 原生产环境 | 独立测试环境 |
|---|---|---|
| Python | 3.14.7，Windows x64 | 同一个基础解释器创建的独立 venv |
| PyTorch | 2.14.0+cpu | 2.11.0+cu128 |
| torchvision | 0.29.0+cpu | 0.26.0+cu128 |
| torch.version.cuda | null | 12.8 |
| torch.cuda.is_available() | False | True |
| GPU | 驱动识别 RTX 3060，但 CPU 版 torch 不可用 | NVIDIA GeForce RTX 3060，约 12 GiB，计算能力 8.6 |
| 驱动 | 616.92 | 原驱动不变 |
| NumPy / Pillow / OpenCV | 2.5.3 / 12.3.0 / 5.0.0.93 | 与生产一致 |

`nvidia-smi` 报告 CUDA UMD Version 13.4，表示驱动侧信息，不能当作 PyTorch 的 CUDA runtime 版本或本机 Toolkit 安装版本。未在 PATH 找到 nvcc，也未发现 CUDA_PATH 或常见 Toolkit 安装目录；本次没有安装系统 CUDA Toolkit、更新驱动或修改系统 PATH。测试使用 PyTorch 官方 CUDA 12.8 wheel 自带的运行库。

当前直接原因是生产 PyTorch 为 CPU 构建。旧文档关于“Python 3.14 装不了 CUDA PyTorch / CUDA 版最高支持 Python 3.12”的结论已过时：本次从官方索引确认并安装了 Windows cp314 的 CUDA 包。

来源：[PyTorch 安装说明](https://pytorch.org/get-started/locally/)、[torch CUDA 12.8 包索引](https://download.pytorch.org/whl/cu128/torch/)、[torchvision CUDA 12.8 包索引](https://download.pytorch.org/whl/cu128/torchvision/)。版本选择依据实际官方包索引，本次未使用第三方 CUDA wheel。

## 隔离方案与复测

- 环境路径：项目内 `.venv-cuda-test/`，`include-system-site-packages = false`。
- 原解释器和全部生产包原地保留，作为继续运行和回退环境；没有复制整套解释器，也没有向原环境安装或卸载包。
- 未修改 `config.json`、启动脚本、项目 `requirements.txt`。
- 仅安装验证需要的 torch、torchvision、OpenCV 等依赖；没有安装整套项目依赖。
- venv 仍依赖原基础 Python 的标准库；不要删除或移动基础解释器。它不是独立可搬运发行包。

在项目根目录用 PowerShell 复测，无需激活环境：

```powershell
& ./.venv-cuda-test/Scripts/python.exe -X utf8 -B test_gpu.py --output gpu_test_results/cuda-benchmark.json --reference gpu_test_results/production-cpu.npy
```

生产 CPU 基线复测（不安装任何包）：

```powershell
$taskPython = (Get-Content config.json -Raw | ConvertFrom-Json).paths.python_executable
& $taskPython -X utf8 -B test_gpu.py --cpu-only --output gpu_test_results/production-cpu.json
```

环境创建及实际安装命令记录（仅在重建独立测试环境时使用）：

```powershell
$taskPython = (Get-Content config.json -Raw | ConvertFrom-Json).paths.python_executable
& $taskPython -m venv .venv-cuda-test
& ./.venv-cuda-test/Scripts/python.exe -m pip --isolated install --no-cache-dir --index-url https://download.pytorch.org/whl/cu128 'torch==2.11.0+cu128' 'torchvision==0.26.0+cu128'
& ./.venv-cuda-test/Scripts/python.exe -m pip --isolated install --no-cache-dir --index-url https://pypi.org/simple 'opencv-python==5.0.0.93' 'numpy==2.5.3'
```

首次 venv 创建时，受限执行器对 ensurepip 临时目录报权限错误；在授权提升的进程中运行测试 venv 的 `-m ensurepip --default-pip` 后成功。安装过程未更改生产 Python。完整依赖版本及下载来源分别记录在 `gpu_test_results/cuda-requirements.txt` 与两个 `*-install-report.json` / `install-report.json` 中。

## 测试方法

使用固定随机种子生成 100 张不同的 640×360 BGR 合成图片，图片只驻留内存。三轮重复处理同一组图片，每个设备先预热 5 张。没有读取生产视频、数据库、FAISS 或历史帧。

使用同一份既有 `mobilenet_v2-7ebf99e0.pth` 权重，SHA256 为 `7ebf99e03e254b273379b23edca7ec0da9f48273b23a332b93c1c99d49e86e8f`。保留 MobileNetV2 去分类头、AdaptiveAvgPool2d(1)、1280 维 FP32 和 L2 归一化。脚本从 `video_search.py` 的 AST 读取原预处理表达式，不导入或执行主程序；BGR→RGB、PIL、Resize、ToTensor、Normalize 均保持原流程。

逐张推理，batch size 1，CPU 10 线程。GPU 关闭 TF32，不使用 AMP、半精度、模型编译或批量优化。计时包含图片预处理、前向、CPU/GPU 传输及 NumPy L2 归一化；排除生成图片、加载模型和预热。CUDA 计时前后同步，每张结果返回 CPU。

## 测试结果

| 环境 / 设备 | 第1轮（秒） | 第2轮（秒） | 第3轮（秒） | 中位数（秒/100张） |
|---|---:|---:|---:|---:|
| 原生产环境 CPU | 2.3539 | 2.2429 | 2.1414 | 2.2429 |
| 测试环境 CPU | 2.6596 | 2.5162 | 2.6825 | 2.6596 |
| 测试环境 RTX 3060 | 1.1872 | 1.1258 | 0.8266 | 1.1258 |

同一测试环境 CPU/GPU 中位耗时比为 **2.36 倍**。相对原生产 CPU 中位数约为 1.99 倍，但跨环境比较包含 PyTorch/torchvision 版本差异，不能全部归因于 GPU。

- CUDA 张量矩阵乘法：通过，与 CPU 结果符合容差。
- 模型参数设备：`cuda:0`；GPU 支持架构包含 `sm_86`。
- 特征形状：100×1280，float32，全部有限、L2 范数约为 1。
- 测试环境 CPU 与原生产 CPU 特征：本组合成样本逐元素相同。
- GPU 与两组 CPU 特征最大绝对差：`1.6540289e-6`，最小余弦相似度 `0.99999988`。
- 数值容差 `rtol=1e-4, atol=1e-5`：通过。FP32 在不同设备间不是逐字节相同。
- PyTorch 报告的峰值张量分配约 27.34 MiB；不包含 CUDA 上下文、驱动及其他程序显存，不能视为总显存占用。
- `pip check`、新脚本语法检查通过；原环境的 21 项项目测试全部通过。

这是小样本环境与数值验证。GPU 三轮有时钟/系统负载波动，结果不能外推为生产搜索整体加速、字幕转写加速或全量建库速度，也不是截图检索准确率验收。

## 文件与完整性

新增：`test_gpu.py`、`CUDA_TEST.md`、`.venv-cuda-test/`、`gpu_test_results/`（原始报告、100×1280 基线特征、依赖清单、安装记录和完整性检查）。修改：`HANDOFF.md`、`KNOWN_ISSUES.md`、`ENVIRONMENT.md`，均在修改前备份为 `.cuda-test-20260926.bak`。

生产代码/配置的 SHA256、生产包清单、MobileNetV2 权重 SHA256 在前后核对中一致；生产数据库和两个 FAISS 文件的大小、修改时间一致。未对数十 GB 数据执行全文件哈希，检查不宣称已完成全量内容校验。本任务没有写入这些数据文件。

## 后续建议（本次不执行）

保留测试 venv；生产继续使用原解释器。若后续要求接入 GPU，应单独安排小规模真实截图的检索一致性验证和完整依赖兼容测试，再提供显式 CPU/GPU 选择及 CPU 回退。本次不切换生产、不重建索引、不重算历史特征、不做缩略图优化。
