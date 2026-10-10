# -*- coding: utf-8 -*-
"""读取现有搜索函数，跳过Streamlit页面和维护入口；不复制或调整算法。"""
import ast
from contextlib import closing
from functools import lru_cache
import hashlib
from pathlib import Path
import pickle
import sqlite3

import cv2
import numpy as np
from PIL import Image
import torch
from torchvision import models, transforms

from config import PATHS, configure_runtime_paths, load_settings
from database import DB_FILE, connect_database
from query_device import select_query_device

ROOT = Path(__file__).resolve().parents[1]


class ProductionSearch:
    def __init__(self):
        configure_runtime_paths()
        for path in (PATHS.database, PATHS.faiss_index, PATHS.faiss_meta):
            if not path.is_file():
                raise FileNotFoundError(f"缺少生产文件，停止评估，不创建或重建：{path}")
        weights = PATHS.torch_home / "hub/checkpoints" / models.MobileNet_V2_Weights.DEFAULT.url.rsplit("/", 1)[-1]
        if not weights.is_file():
            raise FileNotFoundError(f"缺少现有模型缓存，不下载模型：{weights}")
        import faiss
        source = (ROOT / "video_search.py").read_text(encoding="utf-8-sig")
        tree = ast.parse(source)
        functions = {"load_feature_model", "extract_image_features", "load_faiss_index",
                     "calc_phash", "calc_color_hist", "hamming_dist", "match_orb_features",
                     "load_frame_for_matching", "search_similar_frames"}
        assignments = {"FAISS_INDEX", "FAISS_META", "THUMBNAIL_DIR", "query_color_frame", "orb", "bf_matcher"}
        nodes = []
        found = set()
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name in functions:
                node.decorator_list = []
                nodes.append(node)
                found.add(node.name)
            elif isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in assignments for t in node.targets):
                nodes.append(node)
        if found != functions:
            raise RuntimeError(f"生产函数接口变化，需检查适配层：{functions - found}")
        self.device = select_query_device(load_settings())
        self.space = dict(cv2=cv2, np=np, Image=Image, torch=torch, models=models, transforms=transforms,
                          faiss=faiss, pickle=pickle, sqlite3=sqlite3, PATHS=PATHS, DB_FILE=DB_FILE,
                          connect_database=connect_database, QUERY_DEVICE=self.device)
        exec(compile(ast.Module(body=nodes, type_ignores=[]), "video_search.py", "exec"), self.space)
        # 对应原st.cache_resource的索引缓存语义，防止每个case重复加载7.6GB索引。
        self.space["load_faiss_index"] = lru_cache(maxsize=1)(self.space["load_faiss_index"])
        self.weights = weights
        self.faiss = faiss
        self.video_ids = {}
        with closing(connect_database(DB_FILE)) as conn:
            self.video_ids = {path: vid for vid, path in conn.execute("SELECT id, file_path FROM videos")}

    def search(self, image_path):
        image = cv2.imdecode(np.frombuffer(Path(image_path).read_bytes(), dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError(f"无法解码查询图片：{image_path}")
        features = self.space["extract_image_features"](image)
        results = self.space["search_similar_frames"](*features, top_k=10)
        return [dict(row, video_id=self.video_ids.get(row["file_path"])) for row in results]

    def provenance(self):
        return {"device": str(self.device), "torch": torch.__version__, "faiss": self.faiss.__version__,
                "source_sha256": hashlib.sha256((ROOT / "video_search.py").read_bytes()).hexdigest(),
                "weights_sha256": hashlib.sha256(self.weights.read_bytes()).hexdigest(),
                "production_files": {str(p): {"size": p.stat().st_size, "mtime_ns": p.stat().st_mtime_ns}
                                     for p in (PATHS.database, PATHS.faiss_index, PATHS.faiss_meta)},
                "matching_cache": str(PATHS.thumbnails_dir)}
