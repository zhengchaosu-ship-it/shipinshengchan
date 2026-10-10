"""启动前检查寻帧 Web 的实际 Python 与本地 DINO 依赖。"""
import json
import os
from pathlib import Path
import sys


HERE = Path(__file__).resolve().parent
RUNTIME = HERE / "runtime"
RUNTIME.mkdir(exist_ok=True)

# 与 Web 进程使用同一导入顺序；依赖只来自项目内已验证的离线目录。
DEPS = HERE.parent / "embedding_comparison" / "deps"
sys.path.insert(0, str(DEPS))

import torch
import transformers
from transformers import AutoImageProcessor


if not transformers.__file__:
    raise RuntimeError("transformers 被识别为空的 namespace package")

result = {
    "status": "READY",
    "pid": os.getpid(),
    "sys_executable": sys.executable,
    "transformers_file": str(Path(transformers.__file__).resolve()),
    "transformers_version": transformers.__version__,
    "auto_image_processor": "OK" if AutoImageProcessor else "MISSING",
    "torch_version": torch.__version__,
    "cuda_available": torch.cuda.is_available(),
    "cuda_device": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
}

output = RUNTIME / "web_environment.json"
output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(result, ensure_ascii=False, indent=2))
