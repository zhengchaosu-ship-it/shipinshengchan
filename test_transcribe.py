# -*- coding: utf-8 -*-
from config import PATHS, configure_runtime_paths
import whisper
import os
from pathlib import Path

# 配置本地ffmpeg路径
FFMPEG_DIR = str(PATHS.ffmpeg_executable.parent)
configure_runtime_paths()

TEST_VIDEO = str(PATHS.sample_video("transcribe"))

print("加载Whisper base模型...")
model = whisper.load_model("base", download_root=str(PATHS.models_dir))

print(f"开始转写测试视频: {TEST_VIDEO}")
result = model.transcribe(TEST_VIDEO, language="zh", verbose=True)

print("\n===== 转写结果前10段 =====")
for i, seg in enumerate(result["segments"][:10]):
    m, s = divmod(int(seg["start"]), 60)
    print(f"[{m:02d}:{s:02d}] {seg['text']}")

print("\n测试完成！")
