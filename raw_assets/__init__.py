"""原片身份、独立检索帧及离线源状态；不修改生产搜索库或向量索引。"""
from .store import CachedFrameProvider, PersistentThumbnailStore, SourceCatalog

__all__ = ['CachedFrameProvider', 'PersistentThumbnailStore', 'SourceCatalog']
