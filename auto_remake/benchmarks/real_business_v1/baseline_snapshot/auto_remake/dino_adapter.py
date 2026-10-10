"""薄适配：原样复用正式寻帧 encoder、FAISS、metadata、去重和计时。"""
from dataclasses import asdict
import importlib.util
import os
from pathlib import Path
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "benchmark" / "experiments" / "dino_july_web"


def _load_file(name, path):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(name, None)
        raise
    return module


def load_official_adapter():
    # search_adapter 的既有裸 import search 需要临时绑定；不改生产源码，不污染同名模块。
    sys.dont_write_bytecode = True
    search = _load_file("auto_remake._official_dino_search", WEB / "search.py")
    old = sys.modules.get("search")
    try:
        sys.modules["search"] = search
        return _load_file("auto_remake._official_dino_adapter", WEB / "search_adapter.py")
    finally:
        if old is None:
            sys.modules.pop("search", None)
        else:
            sys.modules["search"] = old


class DinoBackend:
    def __init__(self, device="cpu"):
        if device not in ("cpu", "cuda"):
            raise ValueError("device 必须为 cpu 或 cuda")
        started = time.perf_counter()
        adapter_module = load_official_adapter()
        adapter = adapter_module.FormalV1RepairedAdapter()
        adapter.candidate_dedup = True
        self.catalog = asdict(adapter.summary())
        previous_device = os.environ.get("JULY_SEARCH_DEVICE")
        try:
            os.environ["JULY_SEARCH_DEVICE"] = device
            self.engine = adapter.image_engine()
        finally:
            if previous_device is None:
                os.environ.pop("JULY_SEARCH_DEVICE", None)
            else:
                os.environ["JULY_SEARCH_DEVICE"] = previous_device
        self.load_seconds = time.perf_counter() - started
        self.device = self.engine.device

    def search_with_timings(self, image, k=100):
        # 官方方法内部固定 FAISS Top500 → 每asset最多5帧/10秒 → 取前k。
        return self.engine.search_with_timings(image, k=k)
