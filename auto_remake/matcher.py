"""通用 matcher 协议；V0.2 的显式实现位于 dino_matcher.py。"""
from typing import Protocol

from .models import Shot


class ShotMatcher(Protocol):
    def match_shot(self, shot: Shot) -> list[dict]:
        """实现自行绑定 analysis 目录以解析 image_path，并返回候选。"""
        ...


def match_shot(shot: Shot) -> list[dict]:
    raise NotImplementedError("请显式构造 DinoMatcher 后调用其 match_shot；无默认全局检索器")
