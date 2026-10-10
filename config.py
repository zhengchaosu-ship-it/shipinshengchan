# -*- coding: utf-8 -*-
"""统一路径配置；只解析路径，不创建目录、不加载模型、不处理素材。"""
import json
import os
from pathlib import Path
import sys


PROJECT_DIR = Path(__file__).resolve().parent


def resolve_path(value, base=PROJECT_DIR):
    """配置中的相对路径始终相对于项目目录，不受当前工作目录影响。"""
    path = Path(os.path.expandvars(str(value))).expanduser()
    return (path if path.is_absolute() else Path(base) / path).resolve()


CONFIG_FILE = resolve_path(os.environ.get("VIDEO_SEARCH_CONFIG", "config.json"))


def load_settings(config_file=CONFIG_FILE):
    if not Path(config_file).exists():
        return {"video_folder": ""}
    with open(config_file, "r", encoding="utf-8-sig") as stream:
        settings = json.load(stream)
    if not isinstance(settings, dict):
        raise ValueError("配置文件必须是 JSON 对象")
    return settings


class ProjectPaths:
    def __init__(self, settings=None, project_dir=PROJECT_DIR):
        self.project_dir = Path(project_dir).resolve()
        self.settings = load_settings() if settings is None else settings
        values = self.settings.get("paths", {})
        if not isinstance(values, dict):
            raise ValueError("paths 必须是 JSON 对象")

        def path(name, default):
            return resolve_path(values.get(name) or default, self.project_dir)

        self.database = path("database", "video_index_fixed.db")
        self.legacy_database = path("legacy_database", "video_index.db")
        self.init_database = path("init_database", self.legacy_database)
        self.faiss_index = path("faiss_index", "faiss_index.bin")
        self.faiss_meta = path("faiss_meta", "faiss_meta.pkl")
        self.models_dir = path("models_dir", "models")
        self.face_detection_model = path("face_detection_model", self.models_dir / "face_detection_yunet.onnx")
        self.face_recognition_model = path("face_recognition_model", self.models_dir / "face_recognition_sface.onnx")
        self.ffmpeg_executable = path("ffmpeg_executable", "bin/ffmpeg.exe")
        self.thumbnails_dir = path("thumbnails_dir", "thumbnails")
        self.display_cache_dir = path("display_cache_dir", self.thumbnails_dir)
        self.log_file = path("log_file", "process_log.txt")
        self.completion_file = path("completion_file", "处理完成.txt")
        self.export_dir = path("export_dir", ".")
        self.python_executable = path("python_executable", sys.executable)
        # 保持 torch 现有缓存位置；仅在用户配置后覆盖，避免重新下载或替换权重。
        default_torch_home = os.environ.get("TORCH_HOME") or str(
            Path(os.environ.get("XDG_CACHE_HOME", "~/.cache")) / "torch"
        )
        self.torch_home = path("torch_home", default_torch_home)
        self.torch_home_explicit = bool(values.get("torch_home"))
        libraries = values.get("cuda_library_dirs")
        if libraries is None:
            site_packages = Path(sys.executable).parent / "Lib" / "site-packages"
            libraries = [site_packages / "nvidia" / package / "bin" for package in ("cublas", "cudnn")]
        if not isinstance(libraries, list):
            raise ValueError("cuda_library_dirs 必须是路径列表或 null")
        self.cuda_library_dirs = [resolve_path(item, self.project_dir) for item in libraries]

    def video_folder(self):
        value = self.settings.get("video_folder", "")
        if not value:
            raise ValueError("请在 config.json 的 video_folder 中配置素材目录")
        return resolve_path(value, self.project_dir)

    def material_folder(self):
        value = self.settings.get("material_folder")
        return resolve_path(value, self.project_dir) if value else self.video_folder()

    def sample_video(self, name):
        value = self.settings.get("sample_videos", {}).get(name)
        if not value:
            raise ValueError(f"请在 config.json 的 sample_videos.{name} 中配置测试视频")
        return resolve_path(value, self.video_folder())


PATHS = ProjectPaths()


def configure_runtime_paths(paths=PATHS):
    """为现有 FFmpeg、CUDA 动态库和 torch 缓存配置查找路径，不启用或安装 GPU。"""
    directories = [paths.ffmpeg_executable.parent] + paths.cuda_library_dirs
    current = os.environ.get("PATH", "").split(os.pathsep)
    selected = set()
    additions = []
    for directory in directories:
        value = str(directory)
        if directory.is_dir() and os.path.normcase(value) not in selected:
            additions.append(value)
            selected.add(os.path.normcase(value))
    os.environ["PATH"] = os.pathsep.join(additions + [item for item in current if os.path.normcase(item) not in selected])
    if paths.torch_home_explicit:
        os.environ["TORCH_HOME"] = str(paths.torch_home)
