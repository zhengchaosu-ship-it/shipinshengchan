# 查询 embedding 的 CPU / CUDA 配置

本轮仅增加查询设备开关。当前 `config.json` 保持 `query_device: cpu`，生产解释器未切换。FAISS仍在CPU检索，未改写索引、数据库、模型、1280维输出、预处理、L2归一化或评分逻辑。

## 配置行为

- `"query_device": "cpu"`：保持原查询CPU逻辑。
- 不提供 `query_device`：默认为CPU，兼容旧配置。
- `"query_device": "cuda"`：查询模型和输入使用 `cuda:0`（本机 RTX 3060）；结果仍返回CPU上的1280维float32 NumPy向量供原有FAISS检索。
- CUDA使用已验证的FP32路径，禁用TF32，不使用AMP或半精度。
- 值无效或显式CUDA不可用时明确报错，不静默回退。回滚为CPU后重启即可。
- 配置由查询端读取，不改变录入脚本的设备选择逻辑。修改配置后需重启服务。

页面初始化会在服务标准输出打印设备、PyTorch版本和解释器；CUDA模式另打印GPU名称。例如：

```text
[query_embedding] device=cpu；PyTorch=2.14.0+cpu；Python=...
[query_embedding] device=cuda:0；PyTorch=2.11.0+cu128；Python=...；GPU=NVIDIA GeForce RTX 3060
```

Streamlit页面重运行时可能再次输出该日志；服务启动后首次打开页面即可看到实际查询设备。

## 切换至 GPU（本轮未执行生产切换）

原生产 PyTorch 是CPU版，因此必须同时选择CUDA解释器。在现有 `config.json` 中只修改下面两个字段，保留其余内容：

```json
{
  "query_device": "cuda",
  "paths": {
    "python_executable": ".venv-cuda-test/Scripts/python.exe"
  }
}
```

停止原服务，然后用原来的 `启动工具.bat` 启动。不要在同一端口同时启动两份服务。打开页面后核对日志包含 `device=cuda:0` 和 `NVIDIA GeForce RTX 3060`。

独立 `.venv-cuda-test` 已补齐页面所需依赖，并通过隔离启动验证；生产Python未安装或升级任何包。保留 PyTorch 2.11.0+cu128、torchvision 0.26.0+cu128，以及原有NumPy/Pillow/OpenCV版本。

如果以后重建该虚拟环境，只在该环境中运行：

```powershell
& ./.venv-cuda-test/Scripts/python.exe -m pip --isolated install --index-url https://pypi.org/simple -r requirements-query-cuda.txt
```

不要在CUDA环境运行原生产 `requirements.txt` 的整体安装；其torch/torchvision固定为另一套生产版本。实际安装后的完整依赖列表位于 `gpu_test_results/query-runtime-requirements.txt`。

## 回滚

1. 将 `query_device` 改回 `cpu`（或删除该键）。
2. 将 `paths.python_executable` 恢复为 `config.json.query-device-20260926.bak` 中原来的值，恢复原生产Python环境。
3. 停止GPU服务并用原启动工具重启；检查日志为 `device=cpu` 和 `PyTorch=2.14.0+cpu`。

无需修改数据库或重建FAISS。原生产环境一直保留；本轮涉及的旧文件均有 `.query-device-20260926.bak` 备份。若回滚整份配置，先确认备份后没有其他需要保留的配置改动。

## 测试结果

- 生产CPU环境：26项测试中25项通过，1项真实CUDA测试因CPU构建而跳过；原有21项均通过。
- CUDA环境：5项设备专项测试全部通过，覆盖默认CPU、无效配置、CUDA不可用时报错与回滚提示、CPU前后完全一致及真实CPU/GPU同图输出。
- 同图测试直接调用 `video_search.py` 当前的 `load_feature_model()` / `extract_image_features()`，不以复制版测试模型代替生产函数。
- 默认CPU结果与修改前函数逐元素相同（embedding、pHash、颜色直方图）。
- 同图CPU/GPU embedding最大绝对差 **9.23871994×10⁻⁷**，通过 `rtol=1e-4, atol=1e-5`；输出1280维、float32、有限值、L2范数约1。pHash与颜色直方图完全相同。
- 3个合成短视频的既有隔离流程通过，覆盖原图搜、文字搜索及Streamlit页面；仅构建6条测试向量的临时索引，未重建生产索引。
- CPU/CUDA各自的临时空库页面、文字搜索UI、启动日志检查和本机HTTP健康检查均通过（HTTP 200）。临时服务已停止、临时数据已清理。记录见 `gpu_test_results/query-device-cpu-smoke.json` / `query-device-cuda-smoke.json`。
- 原生产包清单未变。AST检查确认模型构造、预处理、特征提取、排序及其他原有函数不变；生产库和索引的大小/修改时间不变，模型权重哈希不变。完整性记录见 `gpu_test_results/query-device-preservation.json`。

专项复测：

```powershell
& ./.venv-cuda-test/Scripts/python.exe -X utf8 -B -m unittest discover -s tests -p test_query_device.py -v
& ./.venv-cuda-test/Scripts/python.exe -X utf8 -B tests/run_query_device_smoke.py --device cuda
```

## 文件清单

修改：`video_search.py`（导入设备选择、读取启动配置、替换硬编码CPU三处）、`config.json`（新增默认cpu）、`tests/run_path_smoke.py`（测试命名空间补入设备）、`HANDOFF.md`（本次记录）。

新增：`query_device.py`、`tests/test_query_device.py`、`tests/run_query_device_smoke.py`、`requirements-query-cuda.txt`、本说明；另有 `gpu_test_results/` 内的本轮安装/环境/验证记录。独立CUDA环境补充依赖，生产依赖不变。
