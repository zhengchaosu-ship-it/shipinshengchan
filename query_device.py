# -*- coding: utf-8 -*-
"""仅选择查询 embedding 的推理设备，不修改录入流程或 FAISS 设备。"""
import sys

import torch


def select_query_device(settings):
    """旧配置默认 CPU；显式 CUDA 不可用时直接报错，保留配置回滚路径。"""
    requested = settings.get("query_device", "cpu")
    if requested not in ("cpu", "cuda"):
        raise ValueError("query_device 仅支持 cpu 或 cuda；删除该项时默认 cpu")
    device = torch.device("cpu")
    if requested == "cuda":
        if not torch.cuda.is_available():
            raise RuntimeError(
                "query_device=cuda，但当前 Python 的 CUDA 不可用。"
                "请使用已验证的 CUDA 环境启动，或将 query_device 改回 cpu 并重启。"
                f"当前 Python：{sys.executable}；PyTorch：{torch.__version__}"
            )
        # 保持已通过一致性测试的 FP32 设置，不启用 TF32 或混合精度。
        torch.backends.cuda.matmul.allow_tf32 = False
        torch.backends.cudnn.allow_tf32 = False
        torch.backends.cudnn.benchmark = False
        device = torch.device("cuda:0")
    gpu_name = f"；GPU={torch.cuda.get_device_name(device)}" if requested == "cuda" else ""
    print(f"[query_embedding] device={device}；PyTorch={torch.__version__}"
          f"；Python={sys.executable}{gpu_name}", flush=True)
    return device
