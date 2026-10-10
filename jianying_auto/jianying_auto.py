# -*- coding: utf-8 -*-
"""
剪映自动化合成脚本
==================
需求：素材库1 取前 2 段视频 + 素材库2 取后 3 段视频，按顺序拼成一条竖屏片子，
      并自动识别字幕（用本地 Whisper 转写 -> 生成 SRT -> 直接写进剪映草稿）。

原理：剪映专业版的工程就是本地文件夹里的 draft_content.json。
      本脚本用 pyJianYingDraft 直接生成这个草稿，你打开剪映就能看到拼好的片子和现成字幕。
      剪映自带的“智能字幕”没有公开接口，无法从外部脚本点它；这里用 faster-whisper
      在本地把语音转成带时间轴的字幕，效果等价且完全无人值守。

依赖：
      pip install pyjianyingdraft faster-whisper
      （首次运行会自动下载 Whisper 模型，small 约 460MB；CPU 即可）

用法：
      1. 改下面【配置区】的两个素材库路径和草稿名
      2. python jianying_auto.py
      3. 打开剪映专业版 -> 草稿里就能看到“自动合成_xxx”，检查后导出
"""

import os
# 即使旧常驻Planner已缓存适配器，独立草稿子进程也在native库导入前限制线程。
for _thread_key in ('MKL_NUM_THREADS', 'OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[_thread_key] = '1'
import re
import sys
import glob
import json
import random
import datetime
import subprocess
import time

try:
    from .source_catalog import (CONFIG_FILE as SOURCE_FOLDERS_CONFIG,
                                 VIDEO_EXTENSIONS, load_source_folders, scan_videos)
except ImportError:
    from source_catalog import (CONFIG_FILE as SOURCE_FOLDERS_CONFIG,
                                VIDEO_EXTENSIONS, load_source_folders, scan_videos)

import pyJianYingDraft as d
from pyJianYingDraft.video_segment import MixMode
from pymediainfo import MediaInfo

# ======================== 配置区（按你的实际情况改） ========================
LIB1 = r"E:\备份\精简"            # 坐诊模式素材
GREEN_DIR = r"E:\备份\起号手法\手法绿幕"   # 手法模式素材（绿幕）
PULL_DIR = r"E:\备份\起号手法\引流话术"     # 流量手法开头素材
SHOUWEI_DIR = r"E:\备份\起号手法\收尾"       # 收尾素材
LIB2 = r"E:\备份\起号手法\4.20素材"  # （旧逻辑保留，新模式不再使用）

# 拼接模式：命令行第一个参数指定  手法 / 流量手法 / 坐诊
#   手法   = 手法绿幕随机2段
#   流量手法 = 引流话术随机1段 + 手法绿幕随机1段
#   坐诊   = 精简随机2段
# 不传参时默认坐诊
RUN_MODE = sys.argv[1] if len(sys.argv) > 1 else "坐诊"

NEW_DRAFT_NAME = "自动合成"        # 草稿名（会自动加时间戳，避免重名）

W, H, FPS = 1080, 1920, 30       # 9:16 竖屏；横屏改成 1920x1080
WHISPER_MODEL = "small"           # 可选 tiny/base/small/medium；中文 small 够准
LANGUAGE = "zh"                   # 语音语言

# 绿幕色度抠图（只作用于“素材库1”取进来的片段）
GREEN_SCREEN = True               # True=对库1片段做去绿幕
GREEN_COLOR = "#00FE04FF"         # 绿幕关键色（按实际幕布采样为#00FE04）；偏蓝/偏黄幕布可改这里
CHROMA_INTENSITY = 40.0           # 抠像强度 0-100（绿抠不掉就调高）
CHROMA_SHADOW = 0.0               # 阴影 0-100
CHROMA_EDGE_SMOOTH = 0.0          # 边缘羽化 0-100
CHROMA_EDGE = 6.0                 # 边缘清晰 0-100（你要的数值 6）

# 背景图片：随机从该文件夹取一张，铺在最底层，时长=整条片子
BG_DIR = r"E:\备份\背景素材"
USE_RANDOM_BG = True
BG_EXT = (".jpg", ".jpeg", ".png", ".webp", ".bmp")

# 字幕敏感词替换表（长词自动优先，且长词结果不再被单字规则二次替换）
SENSITIVE_MAP = {
    # 多字词（会先替换、加保护）
    "膀胱": "嗙咣", "脾胃": "睥渭", "失眠": "矢眠", "睡眠": "娷眠",
    "结节": "节节", "肺结节": "沛节节", "荨麻疹": "寻嘛袗", "富贵包": "富贵咆",
    "帕金森": "怕金森", "痔疮": "寺仓", "腰椎间盘突出": "腰盘盘凸凸",
    "腰间盘突出": "喓尖盘凸凸", "腰椎管狭窄": "腰管管窄窄", "腰间盘膨出": "腰盘盘膨出",
    "坐骨神经": "坐嗗神径", "高血压": "髙压压", "静脉曲张": "静麦曲帐",
    "腱鞘": "健峭", "肩周炎": "肩舟焱", "面瘫": "面摊", "面肌痉挛": "面机经栾",
    "脑梗": "恼埂", "溃疡": "馈炀", "手术": "动叨子",
    # 单字词
    "穴": "茓", "肾": "胥", "腰": "喓", "肩": "掮", "胃": "胄", "筋": "肋",
    "血": "桖", "脾": "卑", "脑": "脳", "椎": "惟", "肘": "月寸", "腺": "月泉",
    "乳": "汝", "骨": "嗗", "痛": "嗵", "疼": "藤", "病": "寎", "炎": "焱",
    "状": "壮", "眠": "目民", "睡": "目垂", "湿": "濕", "尿": "脲", "虚": "嘘",
    "胀": "帐", "损": "損", "麻": "蔴", "医": "翳", "疗": "疒", "疹": "疒",
    "瘫": "滩", "药": "箹", "膏": "髙", "神": "訷", "经": "泾", "高": "髙",
    "鸣": "口鸟", "男": "侽", "钱": "餞", "万": "澫", "码": "马", "死": "亖",
    "命": "椧",
}

# 字幕样式（黄字黑边榜楷体，居中）
SUB_FONT = d.FontType.三极榜楷简体   # 榜楷体
SUB_SIZE = 14                       # 字号
SUB_COLOR = (1.0, 1.0, 0.0)         # 黄色字
SUB_BORDER_COLOR = (0.0, 0.0, 0.0)  # 黑色描边
SUB_BORDER_WIDTH = 25.0              # 黑边粗细
SUB_Y = -500                       # Y 轴心位置（剪映像素值，向上为负）

# 贴纸：从"贴纸"草稿的素材索引随机抽 N 个，随机位置放大铺满，滤色混合
STICKER_KEY_VALUE = r"D:\JianyingPro Drafts\贴纸\key_value.json"
STICKER_COUNT = 6                  # 随机抽几个贴纸
STICKER_MIX_MODE = d.MixModeType.滤色  # 混合模式
STICKER_SCALE = (3.5, 6.0)         # 放大范围（铺满屏幕）
STICKER_POS = 0.55                 # 随机位置范围（归一化，画面内）
STICKER_ROTATE = True              # 每个贴纸随机旋转
STICKER_ALPHA = 0.01              # 不透明度（0.01=1%）
STICKER_COMBINATION = True         # True=全部贴纸打包成一个复合片段，再整体滤色+1%

# 特效+滤镜：从"特效滤镜"草稿按名称匹配枚举，随机抽 N 个
EFFECT_FILTER_KV = r"D:\JianyingPro Drafts\特效滤镜\key_value.json"
EFFECT_COUNT = 3                   # 随机抽几个特效
FILTER_COUNT = 3                   # 随机抽几个滤镜
EFFECT_INTENSITY = 1               # 特效强度（0-100，1=1%）
FILTER_INTENSITY = 1              # 滤镜强度（0-100）

# 扫光消重素材：随机 N 条视频轨道铺满全程，滤色叠加
SWEEP_DIR = r"E:\备份\Y148-抖音快手扫光棒消重短视频去重素材粒子剪辑防搬运教程过原创方法\1.扫光消重素材"
SWEEP_TRACKS = 3                   # 几条扫光轨道
SWEEP_SCALE = (1.5, 3.2)          # 每条轨道随机放大范围（横屏素材铺满竖屏）
SWEEP_ROTATE = True               # 每条轨道随机旋转
SWEEP_ALPHA = 0.05                # 不透明度（0.05=5%）
SWEEP_MIX_MODE = d.MixModeType.滤色  # 混合模式

# 粒子消重背景：与扫光同样规则
PARTICLE_DIR = r"E:\备份\Y148-抖音快手扫光棒消重短视频去重素材粒子剪辑防搬运教程过原创方法\粒子消重背景"
PARTICLE_TRACKS = 3                # 几条粒子轨道
PARTICLE_SCALE = (1.5, 3.2)
PARTICLE_ALPHA = 0.01             # 不透明度（0.01=1%）
PARTICLE_MIX_MODE = d.MixModeType.滤色

# 直播去重：分8条轨道叠加在最顶，每条随机位移/旋转/缩放铺满画面，全部滤色+1%
LIVE_DIR = r"E:\备份\去重直播\鲁绒其扎_668820QZ"
LIVE_SCALE = (1.0, 2.2)           # 随机放大缩小范围（≥1 保证铺满竖屏）
LIVE_POS = 0.35                  # 随机位移范围（归一化，画面内）
LIVE_ROTATE = True                # 随机旋转
LIVE_ALPHA = 0.01                 # 不透明度（1%）
LIVE_MIX = d.MixModeType.滤色

# 剪映草稿根目录（一般不用改，脚本会自动探测；探测不到时手动填这里）
# 常见：C:\Users\<你>\AppData\Local\JianyingPro\User Data\Projects\com.lveditor.draft
JIANYING_DRAFT_DIR = None

# ---------- 从同目录 config.json 覆盖路径（分发给别人时，只改这一个文件） ----------
_CFG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
if os.path.exists(_CFG_PATH):
    try:
        with open(_CFG_PATH, encoding="utf-8") as f:
            _cfg = json.load(f)
        LIB1 = _cfg.get("lib1", LIB1)
        GREEN_DIR = _cfg.get("green_dir", GREEN_DIR)
        PULL_DIR = _cfg.get("pull_dir", PULL_DIR)
        SHOUWEI_DIR = _cfg.get("shouwei_dir", SHOUWEI_DIR)
        LIB2 = _cfg.get("lib2", LIB2)
        BG_DIR = _cfg.get("bg_dir", BG_DIR)
        STICKER_KEY_VALUE = _cfg.get("sticker_key_value", STICKER_KEY_VALUE)
        STICKER_COMBINATION = bool(_cfg.get("sticker_combination", STICKER_COMBINATION))
        EFFECT_FILTER_KV = _cfg.get("effect_filter_kv", EFFECT_FILTER_KV)
        SWEEP_DIR = _cfg.get("sweep_dir", SWEEP_DIR)
        PARTICLE_DIR = _cfg.get("particle_dir", PARTICLE_DIR)
        LIVE_DIR = _cfg.get("live_dir", LIVE_DIR)
        WHISPER_MODEL = _cfg.get("whisper_model", WHISPER_MODEL)
        if _cfg.get("jianying_draft_dir"):
            JIANYING_DRAFT_DIR = _cfg["jianying_draft_dir"]
        print("[配置] 已加载 config.json")
    except Exception as e:
        print("[配置] config.json 读取失败，用脚本内置默认路径:", e)

# 相对路径一律基于“脚本所在目录”解析，方便整包拷给别人
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
def _abs(p):
    if p and not os.path.isabs(p):
        return os.path.join(_SCRIPT_DIR, p)
    return p
LIB1 = _abs(LIB1); GREEN_DIR = _abs(GREEN_DIR); PULL_DIR = _abs(PULL_DIR); SHOUWEI_DIR = _abs(SHOUWEI_DIR)
LIB2 = _abs(LIB2); BG_DIR = _abs(BG_DIR)
STICKER_KEY_VALUE = _abs(STICKER_KEY_VALUE); EFFECT_FILTER_KV = _abs(EFFECT_FILTER_KV)
SWEEP_DIR = _abs(SWEEP_DIR); PARTICLE_DIR = _abs(PARTICLE_DIR); LIVE_DIR = _abs(LIVE_DIR)
WHISPER_MODEL = _abs(WHISPER_MODEL)

# 起号4类素材以独立JSON为唯一可编辑入口；文件缺失时才回退旧config字段。
if SOURCE_FOLDERS_CONFIG.is_file():
    _source_folders = load_source_folders(SOURCE_FOLDERS_CONFIG)
    PULL_DIR = str(_source_folders["引流"])
    GREEN_DIR = str(_source_folders["手法"])
    LIB1 = str(_source_folders["坐诊"])
    SHOUWEI_DIR = str(_source_folders["收尾"])
    print("[配置] 已加载 jianying_source_folders.json")
# ========================================================================== 

VIDEO_EXT = VIDEO_EXTENSIONS


def natural_sort_key(path):
    """按文件名里的数字自然排序，让 2 排在 10 前面。"""
    name = os.path.basename(path)
    return [int(t) if t.isdigit() else t.lower()
            for t in re.split(r"(\d+)", name)]


def list_videos(folder):
    files = [f for f in glob.glob(os.path.join(folder, "*"))
             if f.lower().endswith(VIDEO_EXT)]
    files.sort(key=natural_sort_key)
    return files


def list_source_videos(folder):
    """4类起号素材允许递归；扫描边界由source_catalog保证。"""
    return [str(path) for path in scan_videos(folder)]


def list_images(folder):
    if not os.path.isdir(folder):
        return []
    return [f for f in glob.glob(os.path.join(folder, "*"))
            if f.lower().endswith(BG_EXT)]


def apply_sensitive_mask(text):
    """按 SENSITIVE_MAP 替换敏感字。多字词先替换并加占位保护，
    避免其结果里的字又被单字规则二次替换。"""
    if not text:
        return text
    # 1) 多字词按长度降序替换成占位符
    long_words = sorted([k for k in SENSITIVE_MAP if len(k) > 1], key=len, reverse=True)
    holders = {}
    for i, w in enumerate(long_words):
        if w in text:
            ph = "\ue000%d\ue001" % i
            holders[ph] = SENSITIVE_MAP[w]
            text = text.replace(w, ph)
    # 2) 单字词替换
    for k, v in SENSITIVE_MAP.items():
        if len(k) == 1:
            text = text.replace(k, v)
    # 3) 还原多字词（不再被单字规则碰）
    for ph, v in holders.items():
        text = text.replace(ph, v)
    return text


def load_sticker_pool():
    """从贴纸草稿的 key_value.json 读取去重后的贴纸池 [(id, 名称)]。"""
    if not os.path.exists(STICKER_KEY_VALUE):
        return []
    with open(STICKER_KEY_VALUE, encoding="utf-8") as f:
        j = json.load(f)
    seen = {}
    for v in j.values():
        if v.get("materialCategory") == "sticker":
            seen[v["materialId"]] = v.get("materialName", "贴纸")
    return list(seen.items())


def load_effect_filter_pool():
    """从特效滤镜草稿按名称匹配库枚举，返回 [(名,特效枚举)] 和 [(名,滤镜枚举)]。"""
    if not os.path.exists(EFFECT_FILTER_KV):
        return [], []
    with open(EFFECT_FILTER_KV, encoding="utf-8") as f:
        j = json.load(f)
    eff = {e.value.name: e for e in d.VideoSceneEffectType}
    filt = {e.value.name: e for e in d.FilterType}
    e_pool, f_pool, seen_e, seen_f = [], [], set(), set()
    for v in j.values():
        n = v.get("materialName")
        cat = v.get("materialCategory")
        if cat == "effect" and n in eff and n not in seen_e:
            e_pool.append((n, eff[n])); seen_e.add(n)
        if cat == "filter" and n in filt and n not in seen_f:
            f_pool.append((n, filt[n])); seen_f.add(n)
    return e_pool, f_pool


def load_sweep_pool():
    """扫光素材目录里所有视频路径。"""
    if not os.path.isdir(SWEEP_DIR):
        return []
    return [f for f in glob.glob(os.path.join(SWEEP_DIR, "*"))
            if f.lower().endswith((".mp4", ".mov", ".avi", ".webm", ".mkv"))]


def load_particle_pool():
    if not os.path.isdir(PARTICLE_DIR):
        return []
    return [f for f in glob.glob(os.path.join(PARTICLE_DIR, "*"))
            if f.lower().endswith((".mp4", ".mov", ".avi", ".webm", ".mkv"))]


def load_live_video():
    """直播去重素材：优先用转好的 mp4（.ts 剪映解码不稳定）。"""
    mp4 = r"E:\备份\去重直播\live_sample.mp4"
    if os.path.exists(mp4):
        return mp4
    if not os.path.isdir(LIVE_DIR):
        return None
    vids = [f for f in glob.glob(os.path.join(LIVE_DIR, "*"))
            if f.lower().endswith((".mp4", ".mov", ".ts", ".flv", ".mkv"))]
    return random.choice(vids) if vids else None


def extract_live_audio(path):
    """从直播视频提取纯音频（库 AudioMaterial 不接受带视频流的文件），缓存为 m4a。"""
    out = os.path.splitext(path)[0] + "_audio.m4a"
    if os.path.exists(out):
        return out
    import imageio_ffmpeg
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    cmd = [ff, "-y", "-i", path, "-vn", "-acodec", "copy", out]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if not os.path.exists(out):   # copy 失败则重编码 aac
        cmd = [ff, "-y", "-i", path, "-vn", "-ac", "2", "-c:a", "aac", "-b:a", "128k", out]
        subprocess.run(cmd, capture_output=True, text=True)
    return out if os.path.exists(out) else None


def build_live_mask_tracks(script, cursor, path):
    """同一直播素材分8条轨道叠加在最顶，每条取不同时间切片；
    随机位移/旋转/缩放铺满画面，全部滤色+1%不透明度。
    返回直播轨道名列表，便于 save 后调整层级到最顶端。"""
    mat = d.VideoMaterial(path)
    vh = mat.duration
    seg_len = min(vh, cursor)
    live_names = []
    max_off = max(0, vh - seg_len)
    audio_pick = set(random.sample(range(8), 3))   # 随机挑3条分离音频
    audio_jobs = []

    for i in range(8):
        off = random.randint(0, max_off) if max_off > 0 else 0
        tr_name = "直播-%d" % (i + 1)
        tr = script.append_track(d.TrackSpec(d.TrackType.video, name=tr_name))
        live_names.append(tr_name)

        sx = random.uniform(*LIVE_SCALE)
        tx = random.uniform(-LIVE_POS, LIVE_POS)
        ty = random.uniform(-LIVE_POS, LIVE_POS)
        rot = random.uniform(-180, 180) if LIVE_ROTATE else 0.0
        vs = d.VideoSegment(mat,
                            source_timerange=d.Timerange(off, seg_len),
                            target_timerange=d.Timerange(0, seg_len),
                            clip_settings=d.ClipSettings(scale_x=sx, scale_y=sx,
                                                          transform_x=tx, transform_y=ty,
                                                          rotation=rot, alpha=LIVE_ALPHA))
        # 全部滤色混合模式
        mix_inst = MixMode(LIVE_MIX.value)
        vs.extra_material_refs.append(mix_inst.global_id)
        script.materials.mix_modes.append(mix_inst)
        vs.volume = 0.0   # 8条直播视频全部静音
        script.add_segment(vs, track=tr)
        print("[直播] 轨道%d 缩放%.1f 位移(%.2f,%.2f) 旋转%.0f° 偏移%.1fs"
              % (i + 1, sx, tx, ty, rot, off / 1e6))
        if i in audio_pick:
            audio_jobs.append((off, seg_len))

    # 挑中的3条：把音频分离到独立音频轨，音量 -46dB（各占一条音轨叠加播放）
    if audio_jobs:
        apath = extract_live_audio(path)
        if apath:
            for k, (off, dur) in enumerate(audio_jobs):
                atr = script.append_track(d.TrackSpec(d.TrackType.audio, name="直播原声%d" % (k + 1)))
                am = d.AudioMaterial(apath)
                aseg = d.AudioSegment(am,
                                      source_timerange=d.Timerange(off, dur),
                                      target_timerange=d.Timerange(0, dur))
                aseg.volume = -46.0
                script.add_segment(aseg, track=atr)
            print("[直播原声] 已分离 %d 条音频，各占一轨，音量 -46dB（%s）" % (len(audio_jobs), os.path.basename(apath)))
        else:
            print("[直播原声] 警告：音频提取失败，跳过音频分离")
    return live_names


def build_overlay_tracks(script, cursor, pool, prefix, count, scale_range, alpha, mix_mode, muted=False):
    """每条轨道铺满全程；轨道内每一段都从 pool 随机抽一个新素材，不重复用同一段循环。muted=True 时整条轨道静音。"""
    mat_cache = {}
    def get_mat(path):
        if path not in mat_cache:
            mat_cache[path] = d.VideoMaterial(path)
        return mat_cache[path]

    for ti, _ in enumerate(range(min(count, len(pool)))):
        scale = random.uniform(*scale_range)
        rot = random.uniform(-180, 180)
        tr = script.append_track(
            d.TrackSpec(d.TrackType.video, name="%s-随机叠加%d" % (prefix, ti + 1)))
        cc = d.ClipSettings(scale_x=scale, scale_y=scale, rotation=rot, alpha=alpha)
        cur = 0
        nseg = 0
        while cur < cursor:
            path = random.choice(pool)
            mat = get_mat(path)
            vlen = mat.duration
            seg_len = min(vlen, cursor - cur)
            vs = d.VideoSegment(mat,
                                source_timerange=d.Timerange(0, seg_len),
                                target_timerange=d.Timerange(cur, seg_len),
                                clip_settings=cc)
            if muted:
                vs.volume = 0.0
            mix_inst = MixMode(mix_mode.value)
            vs.extra_material_refs.append(mix_inst.global_id)
            script.add_segment(vs, track=tr)
            script.materials.mix_modes.append(mix_inst)
            cur += seg_len
            nseg += 1
        print("[%s] 随机轨道 放大%.1f 旋转%.0f° 不透明%.0f%% 共%d段随机素材 铺满%.1fs"
              % (prefix, scale, rot, alpha * 100, nseg, cursor / 1000000))


def media_duration_sec(path):
    """读取视频时长（秒）。"""
    mi = MediaInfo.parse(path)
    for t in mi.tracks:
        if t.track_type == "Video":
            return (t.duration or 0) / 1000.0
    raise RuntimeError("该文件没有视频轨：%s" % path)


def find_jianying_draft_dir():
    global STICKER_KEY_VALUE, EFFECT_FILTER_KV
    if JIANYING_DRAFT_DIR:
        draft_dir = JIANYING_DRAFT_DIR
    else:
        cands = [
            os.path.expandvars(r"%LOCALAPPDATA%\JianyingPro\User Data\Projects\com.lveditor.draft"),
            os.path.expandvars(r"%LOCALAPPDATA%\CapCut\User Data\Projects\com.lveditor.draft"),
            os.path.expandvars(r"%USERPROFILE%\Documents\JianyingPro Drafts"),
        ]
        draft_dir = None
        for c in cands:
            if os.path.isdir(c):
                draft_dir = c
                break
        if not draft_dir:
            raise RuntimeError(
                "没找到剪映草稿目录，请在 config.json 的 jianying_draft_dir 填上。\n"
                "打开剪映 -> 右上角草稿设置，能看到草稿保存路径。")
    # 贴纸/特效索引：config 给的路径不存在时，自动从剪映草稿目录拼
    if not os.path.exists(STICKER_KEY_VALUE):
        auto = os.path.join(draft_dir, "贴纸", "key_value.json")
        if os.path.exists(auto):
            STICKER_KEY_VALUE = auto
    if not os.path.exists(EFFECT_FILTER_KV):
        auto = os.path.join(draft_dir, "特效滤镜", "key_value.json")
        if os.path.exists(auto):
            EFFECT_FILTER_KV = auto
    return draft_dir


def srt_timestamp(sec):
    """秒 -> SRT 时间戳 HH:MM:SS,mmm"""
    td = datetime.timedelta(seconds=max(0.0, sec))
    total = td.total_seconds()
    h = int(total // 3600)
    m = int((total % 3600) // 60)
    s = int(total % 60)
    ms = int(round((total - int(total)) * 1000))
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def build_srt_with_whisper(clips, srt_path):
    """逐段转写，把后一段字幕时间轴叠加前面片段的总时长，合并成一个 SRT。"""
    try:
        from .memory_safety import require_draft_budget
    except ImportError:
        from memory_safety import require_draft_budget
    require_draft_budget(minimum=1024 ** 3)  # native导入后仍保留1GiB；父进程启动前要求2GiB。
    from faster_whisper import WhisperModel
    if not os.path.isdir(WHISPER_MODEL):
        raise RuntimeError("本地 Whisper 模型目录不存在: %s" % WHISPER_MODEL)
    print("[字幕] 加载本地 Whisper 模型 %s..." % WHISPER_MODEL)
    model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8",
                         local_files_only=True, cpu_threads=1, num_workers=1)

    offset = 0.0          # 当前片段在整条片子里的起点（秒）
    items = []             # (start, end, text)
    for i, p in enumerate(clips, 1):
        dur = media_duration_sec(p)
        print("[字幕] 转写第 %d/%d 段: %s" % (i, len(clips), os.path.basename(p)))
        segments, _ = model.transcribe(p, language=LANGUAGE, vad_filter=True)
        for seg in segments:
            text = apply_sensitive_mask(seg.text.strip())
            if text:
                s = seg.start + offset
                e = min(seg.end + offset, offset + dur)   # 不超出本片结束边界
                if e - s > 0.15:                          # 丢弃过短残句
                    items.append((s, e, text))
        offset += dur

    # 全局清洗：按时间排序，相邻字幕若重叠，把前一条结尾收到后一条开头，避免剪映报重叠
    items.sort(key=lambda x: x[0])
    cleaned = []
    for s, e, t in items:
        if cleaned and s < cleaned[-1][1]:
            ps, pe, pt = cleaned[-1]
            cleaned[-1] = (ps, max(ps + 0.15, s), pt)     # 前一条 end = 后一条 start
        if not cleaned or s >= cleaned[-1][1]:
            cleaned.append((s, e, t))
    items = cleaned

    with open(srt_path, "w", encoding="utf-8") as f:
        for idx, (s, e, text) in enumerate(items, 1):
            f.write(f"{idx}\n{srt_timestamp(s)} --> {srt_timestamp(e)}\n{text}\n\n")
    print("[字幕] 共 %d 条字幕 -> %s" % (len(items), srt_path))


def pick_clips_by_mode(mode):
    """按模式选拼接段。
    1) 自由组合：引流1+手法2+坐诊3（旧“流量”仍映射为引流；N=递归自然排序第N个）
    2) 整模式：手法 / 流量手法 / 坐诊（随机选段）。
    返回 (clips, 描述, 草稿命名前缀)。"""
    ALIAS_DIR = {"流量": PULL_DIR, "引流": PULL_DIR, "手法": GREEN_DIR,
                 "坐诊": LIB1, "收尾": SHOUWEI_DIR}

    # 自由组合模式；单个带编号Token用于网页的1段生成。
    is_indexed_single = re.fullmatch(r"(流量|引流|手法|坐诊|收尾)[1-9]\d*", mode)
    if "+" in mode or is_indexed_single:
        clips, desc_parts = [], []
        used_by_folder = {}
        for token in mode.split("+"):
            token = token.strip()
            m = re.match(r"^(流量|引流|手法|坐诊|收尾)(\d*)$", token)
            if not m:
                raise SystemExit("无法解析拼接项「%s」（应为 引流N/手法N/坐诊N/收尾N；旧流量N仍兼容）" % token)
            alias, idx_str = m.group(1), m.group(2)
            folder = ALIAS_DIR[alias]
            pool = list_source_videos(folder)
            if not pool:
                raise SystemExit("%s 素材目录为空: %s" % (alias, folder))
            if idx_str == "":
                used = used_by_folder.setdefault(folder, set())
                available = [path for path in pool if path not in used]
                pick = random.choice(available or pool)
                used.add(pick)
            else:
                idx = int(idx_str)
                if idx < 1 or idx > len(pool):
                    raise SystemExit("%s 第%d个不存在，该目录共%d个素材" % (alias, idx, len(pool)))
                pick = pool[idx - 1]
            clips.append(pick)
            desc_parts.append("%s=%s" % (alias, os.path.basename(pick)))
        return clips, "自由组合 %s" % mode, "组合"

    # 整模式（随机选段）
    g = list_source_videos(GREEN_DIR)
    p = list_source_videos(PULL_DIR)
    z = list_source_videos(LIB1)
    if mode == "手法":
        if len(g) < 2:
            raise SystemExit("手法绿幕素材不足2个: %s" % GREEN_DIR)
        return random.sample(g, 2), "手法（手法绿幕×2）", "手法"
    if mode == "流量手法":
        if not p or not g:
            raise SystemExit("引流话术或手法绿幕素材为空")
        return [random.choice(p), random.choice(g)], "流量手法（引流话术1 + 手法绿幕1）", "流量手法"
    # 默认坐诊
    if len(z) < 2:
        raise SystemExit("精简素材不足2个: %s" % LIB1)
    return random.sample(z, 2), "坐诊（精简×2）", "坐诊"


def categories_for_mode(mode):
    """返回与实际拼接顺序一致的标准分类名，用于Web展示。"""
    if "+" in mode or re.fullmatch(r"(流量|引流|手法|坐诊|收尾)[1-9]\d*", mode):
        categories = []
        for token in mode.split("+"):
            matched = re.match(r"^(流量|引流|手法|坐诊|收尾)", token.strip())
            if not matched:
                return []
            category = matched.group(1)
            categories.append("引流" if category == "流量" else category)
        return categories
    if mode == "手法":
        return ["手法", "手法"]
    if mode == "流量手法":
        return ["引流", "手法"]
    return ["坐诊", "坐诊"]


def next_draft_name(draft_dir, mode):
    """按类型递增编号命名：手法1-自动合成 / 流量手法3-自动合成 / 坐诊2-自动合成。
    扫描草稿目录下已有同名前缀，取下一个编号。"""
    prefix = re.escape(mode)
    nums = []
    if os.path.isdir(draft_dir):
        for entry in os.listdir(draft_dir):
            m = re.match(r"^%s(\d+)-自动合成$" % prefix, entry)
            if m:
                nums.append(int(m.group(1)))
    n = (max(nums) + 1) if nums else 1
    return "%s%d-自动合成" % (mode, n)


def _combination_video_material(material_id, cursor_us):
    """构造剪映复合片段使用的虚拟视频素材。

    复合片段不能直接把 materials.drafts 的 ID 当作 segment.material_id；
    外层片段必须指向一个独立的 video material，再通过 extra_material_refs
    关联 drafts material。字段取自本机剪映 11.5 保存后的实际复合片段结构。
    """
    return {
        "aigc_history_id": "",
        "aigc_item_id": "",
        "aigc_type": "none",
        "audio_fade": None,
        "category_id": "",
        "category_name": "",
        "check_flag": 62978047,
        "crop": {
            "lower_left_x": 0.0, "lower_left_y": 1.0,
            "lower_right_x": 1.0, "lower_right_y": 1.0,
            "upper_left_x": 0.0, "upper_left_y": 0.0,
            "upper_right_x": 1.0, "upper_right_y": 0.0,
        },
        "crop_ratio": "free",
        "crop_scale": 1.0,
        "duration": cursor_us,
        "extra_type_option": 2,
        "has_audio": False,
        "has_sound_separated": False,
        "height": H,
        "id": material_id,
        "local_id": "",
        "local_material_from": "",
        "local_material_id": "",
        "material_id": "",
        "material_name": "贴纸复合片段",
        "material_url": "",
        "media_path": "",
        "path": "",
        "picture_from": "none",
        "source": 0,
        "source_platform": 0,
        "type": "video",
        "width": W,
    }


def wrap_stickers_as_combination(j, cursor_us, draft_path):
    """把所有 sticker 轨道打包成复合片段：
    在草稿目录下建 subdraft/<UUID>/，写独立子草稿文件；主草稿用一个 video 段引用，
    type=combination，外层挂滤色+1% 不透明度。"""
    import uuid
    def U():
        return str(uuid.uuid4()).upper()

    skel_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "combo_skeleton.json")
    if not os.path.exists(skel_path):
        print("[复合片段] 缺少 combo_skeleton.json，跳过")
        return
    with open(skel_path, encoding="utf-8") as f:
        skel = json.load(f)
    mats = j["materials"]

    sticker_tracks = [t for t in j["tracks"] if t.get("type") == "sticker"]
    if len(sticker_tracks) < 2:
        print("[复合片段] 贴纸轨道不足2，跳过")
        return

    smat_ids = set()
    for t in sticker_tracks:
        for s in t["segments"]:
            smat_ids.add(s["material_id"])
    smats = [m for m in mats.get("stickers", []) if m["id"] in smat_ids]

    # 内嵌贴纸保持100%不透明且不单独滤色；透明度和滤色只施加在外层。
    old_sticker_refs = set()
    for t in sticker_tracks:
        for s in t["segments"]:
            old_sticker_refs.update(s.get("extra_material_refs", []))
            s["extra_material_refs"] = []
            if s.get("clip"):
                s["clip"]["alpha"] = 1.0

    # 子草稿 UUID 与目录
    sub_id = U()
    sub_dir = os.path.join(draft_path, "subdraft", sub_id)
    os.makedirs(sub_dir, exist_ok=True)

    # 子草稿 draft_content.json：以主草稿为骨架，只留贴纸轨道与贴纸素材
    sub_content = dict(j)
    sub_content["tracks"] = sticker_tracks
    sub_mats = {"stickers": smats}
    for k in mats.keys():
        sub_mats.setdefault(k, [])
    sub_mats["stickers"] = smats
    sub_content["materials"] = sub_mats
    sub_content["duration"] = cursor_us
    sub_content["name"] = "复合片段"
    sub_content["id"] = sub_id
    with open(os.path.join(sub_dir, "draft_content.json"), "w", encoding="utf-8") as f:
        json.dump(sub_content, f, ensure_ascii=False)

    # 子草稿配置文件
    now_ms = int(datetime.datetime.now().timestamp() * 1000)
    sub_config = {
        "audio_path": "", "cover_height": 320, "cover_path": "draft_cover.jpg",
        "cover_width": 180, "create_time": now_ms // 1000, "draft_json_file": "draft_content.json",
        "id": sub_id, "import_time_ms": now_ms, "is_from_multi_timeline": False,
        "is_from_sub_draft": True, "material_color_tag": "", "name": "复合片段",
        "project_id": sub_id, "rough_cut_duration": cursor_us, "rough_cut_start": 0,
        "source": "timeline", "type": "video",
    }
    with open(os.path.join(sub_dir, "sub_draft_config.json"), "w", encoding="utf-8") as f:
        json.dump(sub_config, f, ensure_ascii=False)

    # drafts 复合片段素材（指向真实子草稿文件）
    draft_ref_id = U()
    drafts_mat = dict(skel["drafts_top"])
    drafts_mat["id"] = draft_ref_id
    drafts_mat["type"] = "combination"
    drafts_mat["combination_id"] = U()
    drafts_mat["combination_type"] = "none"
    drafts_mat["name"] = "复合片段"
    drafts_mat["draft_file_path"] = sub_dir.replace("\\", "/") + "/draft_content.json"
    drafts_mat["draft_config_path"] = sub_dir.replace("\\", "/") + "/sub_draft_config.json"
    drafts_mat["draft_cover_path"] = ""
    drafts_mat["draft"] = sub_content   # 部分版本会读内嵌字段
    mats.setdefault("drafts", []).append(drafts_mat)

    # 外层片段必须指向独立的虚拟 video material；drafts ID 只作为额外引用。
    video_material_id = U()
    mats.setdefault("videos", []).append(
        _combination_video_material(video_material_id, cursor_us))

    # 移除主草稿的贴纸轨道与贴纸素材（已移入子草稿）
    j["tracks"] = [t for t in j["tracks"] if t.get("type") != "sticker"]
    mats["stickers"] = [m for m in mats.get("stickers", []) if m["id"] not in smat_ids]
    if old_sticker_refs:
        mats["effects"] = [m for m in mats.get("effects", [])
                           if m.get("id") not in old_sticker_refs]

    # 标配空 companion 素材
    speed_id, canvas_id, color_id = U(), U(), U()
    ph_id, snd_id, voc_id = U(), U(), U()
    mats.setdefault("speeds", []).append({"id": speed_id, "mode": 0, "speed": 1.0, "type": "speed"})
    mats.setdefault("canvases", []).append({"id": canvas_id, "album_image": "", "blur": 0.0,
                                             "color": "", "image": "", "image_id": "", "image_name": "",
                                             "source_platform": 0, "team_id": "", "type": "canvas_color"})
    mats.setdefault("material_colors", []).append({"id": color_id, "gradient_angle": 90.0,
                                                    "gradient_colors": [], "gradient_percents": [],
                                                    "height": 0.0, "is_color_clip": False,
                                                    "is_gradient": False, "solid_color": "", "width": 0.0})
    mats.setdefault("placeholder_infos", []).append({"id": ph_id, "error_path": "", "error_text": "",
                                                     "meta_type": "none", "res_path": "", "res_text": "",
                                                     "type": "placeholder_info"})
    mats.setdefault("sound_channel_mappings", []).append({"id": snd_id, "audio_channel_mapping": 0,
                                                          "is_config_open": False, "type": ""})
    mats.setdefault("vocal_separations", []).append({"id": voc_id, "choice": 0, "enter_from": "",
                                                     "final_algorithm": "", "production_path": "",
                                                     "removed_sounds": [], "time_range": None,
                                                     "type": "vocal_separation"})

    # 滤色混合模式
    mix = MixMode(d.MixModeType.滤色.value)
    mats.setdefault("effects", []).append(mix.export_json())
    mix_id = mix.global_id

    # 外层段（深拷贝骨架，换 ID / 时长 / 透明度）
    seg = json.loads(json.dumps(skel["outer_segment"]))
    seg["id"] = U()
    seg["material_id"] = video_material_id
    seg["source_timerange"] = {"start": 0, "duration": cursor_us}
    seg["target_timerange"] = {"start": 0, "duration": cursor_us}
    seg["render_timerange"] = {"start": 0, "duration": cursor_us}
    seg["clip"]["alpha"] = STICKER_ALPHA
    seg["extra_material_refs"] = [draft_ref_id, speed_id, canvas_id, ph_id,
                                  snd_id, color_id, voc_id, mix_id]
    seg["volume"] = 1.0
    seg["speed"] = 1.0
    seg["visible"] = True

    j["tracks"].append({"id": U(), "type": "video", "name": "贴纸复合片段", "segments": [seg]})
    print("[复合片段] 已把 %d 个贴纸打包成复合片段(subdraft)，外层滤色+%.0f%%"
          % (len(sticker_tracks), STICKER_ALPHA * 100))
    return {
        "subdraft_id": sub_id,
        "draft_material_id": draft_ref_id,
        "video_material_id": video_material_id,
        "segment_id": seg["id"],
    }


def main():
    # 账号入口在创建任何草稿前冻结并核验视觉层；未绑定绝不随机借用其它背景。
    business_id = os.environ.get('XUNFRAME_BUSINESS_ACCOUNT_ID')
    background = None
    if business_id:
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from account_visuals.storage import validate_snapshot
        from account_visuals.draft_layer import add_background
        background = validate_snapshot(json.loads(os.environ['XUNFRAME_ACCOUNT_BACKGROUND']), business_id)
    # 1) 选素材（按运行模式）
    composition_file = os.environ.get('XUNFRAME_COMPOSITION_MANIFEST')
    if composition_file:
        import hashlib
        with open(composition_file, encoding='utf-8') as handle:
            composition = json.load(handle)
        selections = composition['selections']
        if not 1 <= len(selections) <= 20:
            raise ValueError('INVALID_CONFIRMED_SLOT_COUNT')
        clips = []
        for material in selections:
            path = os.path.abspath(material['path'])
            if not os.path.isfile(path) or path.startswith(('\\\\', '//')):
                raise ValueError('CONFIRMED_LOCAL_MATERIAL_REQUIRED')
            sha = hashlib.sha256()
            with open(path, 'rb') as media:
                for block in iter(lambda: media.read(1024 * 1024), b''):
                    sha.update(block)
            if sha.hexdigest() != material['media_sha256']:
                raise ValueError('CONFIRMED_MATERIAL_SHA_CHANGED')
            clips.append(path)
        mode_desc, draft_prefix = '用户确认的账号模板', '起号托管'
    else:
        clips, mode_desc, draft_prefix = pick_clips_by_mode(RUN_MODE)
    n_chroma = len(clips)   # 新模式：所有拼接段都做绿幕抠像

    print("=" * 50)
    print("拼接模式: %s  [运行参数: %s]" % (mode_desc, RUN_MODE))
    print("最终拼接顺序（共 %d 段，全部抠绿幕）:" % len(clips))
    categories = [s['module_type'] for s in selections] if composition_file else categories_for_mode(RUN_MODE)
    selected_payload = []
    for i, c in enumerate(clips, 1):
        print("   %d. %s  (%.2fs)" % (i, os.path.basename(c), media_duration_sec(c)))
        selected_payload.append({
            "index": i,
            "category": categories[i - 1] if i <= len(categories) else "未知",
            "file_name": os.path.basename(c),
            "path": os.path.abspath(c),
        })
    print("[选中素材JSON] " + json.dumps(selected_payload, ensure_ascii=False))
    print("=" * 50)

    if len(clips) < 1:
        raise SystemExit("没有选到任何视频，请检查素材库路径和选取数量。")

    # 2) 建草稿并把视频按顺序铺到主轨
    draft_dir = find_jianying_draft_dir()
    print("[草稿] 草稿根目录:", draft_dir)
    draft_name = os.environ.get('XUNZHEN_RESERVED_DRAFT_NAME') or next_draft_name(draft_dir, draft_prefix)
    if os.environ.get('XUNZHEN_RESERVED_DRAFT_NAME'):
        if re.search(r'[\\/:*?"<>|\x00-\x1f]', draft_name) or draft_name.endswith(('.', ' ')):
            raise ValueError('UNSAFE_DRAFT_NAME')
        if os.path.exists(os.path.join(draft_dir, draft_name)):
            raise FileExistsError('DRAFT_ALREADY_EXISTS_NO_OVERWRITE')
    stamp = datetime.datetime.now().strftime("%H%M%S")

    folder = d.DraftFolder(draft_dir)
    script = folder.create_draft(draft_name, W, H, FPS, allow_replace=not bool(os.environ.get('XUNZHEN_RESERVED_DRAFT_NAME')))
    if os.environ.get('XUNZHEN_RESERVED_DRAFT_NAME'):
        import uuid
        script.content['id'] = str(uuid.uuid4()).upper()  # 库模板的顶层id固定，新生产草稿不能复用。
    vtrack = script.append_track(d.TrackSpec(d.TrackType.video, name="主视频"))

    cursor = 0  # 微秒
    for idx, p in enumerate(clips):
        dur_us = int(round(media_duration_sec(p) * d.SEC))
        seg = d.VideoMaterial(p)
        vseg = d.VideoSegment(
            seg,
            target_timerange=d.Timerange(cursor, dur_us),   # 时间轴上的位置
            source_timerange=d.Timerange(0, dur_us),         # 从素材头取整段
        )
        # 所有拼接段都做绿幕色度抠像
        if GREEN_SCREEN:
            vseg.add_chroma(
                GREEN_COLOR,
                intensity=CHROMA_INTENSITY,
                shadow=CHROMA_SHADOW,
                edge_smooth=CHROMA_EDGE_SMOOTH,
                spill=CHROMA_EDGE,        # 边缘清除/去溢色 = 6
            )
            print("[抠像] 已加绿幕抠像(边缘清除=%g): %s"
                  % (CHROMA_EDGE, os.path.basename(p)))
        script.add_segment(vseg, track=vtrack)
        cursor += dur_us
    print("[草稿] 视频已顺序拼接，总时长 %.2f 秒" % (cursor / d.SEC))

    # 2.5) 业务账号背景属于独立视觉层；保留旧无账号CLI的兼容路径。
    if business_id:
        background = add_background(script, vtrack, background, cursor, d, width=W, height=H)
        with open(os.path.join(draft_dir, draft_name, 'account_visual_layer.json'), 'w', encoding='utf-8') as audit:
            json.dump(background, audit, ensure_ascii=False, indent=2)
        print('[账号背景] ' + (background.get('filename', '已绑定') if background['enabled'] else '尚未设置账号背景'))
    elif USE_RANDOM_BG:
        bg_imgs = list_images(BG_DIR)
        if bg_imgs:
            bg_path = random.choice(bg_imgs)
            bg_track = script.insert_track(
                d.TrackSpec(d.TrackType.video, name="背景"), under_track=vtrack)
            bg_mat = d.VideoMaterial(bg_path)
            bg_seg = d.VideoSegment(
                bg_mat,
                target_timerange=d.Timerange(0, cursor),     # 从0铺到结尾
                source_timerange=d.Timerange(0, cursor),
            )
            script.add_segment(bg_seg, track=bg_track)
            print("[背景] 随机背景图: %s（时长 %.2fs，垫在最底层）"
                  % (os.path.basename(bg_path), cursor / d.SEC))
        else:
            print("[背景] %s 里没找到图片，跳过背景" % BG_DIR)

    # 3) 自动识别字幕：本地 Whisper -> SRT -> 导入字幕轨
    srt_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"sub_{stamp}.srt")
    build_srt_with_whisper(clips, srt_path)

    # 构造字幕样式模板：榜楷体 + 黄字 + 黑边 + Y轴位置
    sub_template = d.TextSegment(
        "样式模板",
        d.Timerange(0, 1_000_000),
        font=SUB_FONT,
        style=d.TextStyle(size=SUB_SIZE, color=SUB_COLOR, align=1, auto_wrapping=True),
        border=d.TextBorder(color=SUB_BORDER_COLOR, width=SUB_BORDER_WIDTH),
        clip_settings=d.ClipSettings(transform_y=SUB_Y / 960.0),   # 960=画布半高
    )
    script.import_srt(srt_path, track_name="字幕",
                      style_reference=sub_template, clip_settings=None)

    # 3.2) 固定标题文本（顶部：黄字两行+白字红边一行，全程显示）
    TITLE_Y = 2134  # 剪映位置面板Y值
    title_track = script.append_track(d.TrackSpec(d.TrackType.text, name="标题-黄"))
    # 黄字两行：黄字黑边，字号17，字间距3，行间距3
    title_yellow = d.TextSegment(
        "陶氏非遗手法\n学到就是赚到",
        d.Timerange(0, cursor),
        font=SUB_FONT,
        style=d.TextStyle(size=17, color=(1.0, 1.0, 0.0), align=1, bold=True,
                          letter_spacing=3, line_spacing=3),
        border=d.TextBorder(color=(0.0, 0.0, 0.0), width=20.0),
        clip_settings=d.ClipSettings(transform_y=725 / 960.0),
    )
    script.add_segment(title_yellow, track=title_track)
    # 白字红边一行：字号15，Y=550
    title_track2 = script.append_track(d.TrackSpec(d.TrackType.text, name="标题-红"))
    title_red = d.TextSegment(
        "（自己在家做）",
        d.Timerange(0, cursor),
        font=SUB_FONT,
        style=d.TextStyle(size=15, color=(1.0, 1.0, 1.0), align=1, bold=True,
                          letter_spacing=3, line_spacing=3),
        border=d.TextBorder(color=(1.0, 0.0, 0.0), width=20.0),
        clip_settings=d.ClipSettings(transform_y=550 / 960.0),
    )
    script.add_segment(title_red, track=title_track2)
    print("[标题] 已加顶部固定标题（黄字17黑边+白字15红边）")

    # 3.5) 随机抽 N 个贴纸：各一条轨道，随机位置 + 放大铺满 + 滤色 + 不透明
    if STICKER_COUNT > 0:
        pool = load_sticker_pool()
        n = min(STICKER_COUNT, len(pool))
        for mid, name in random.sample(pool, n):
            sticker_track = script.append_track(
                d.TrackSpec(d.TrackType.sticker, name="贴纸-%s" % name[:8]))
            sx = random.uniform(*STICKER_SCALE)
            tx = random.uniform(-STICKER_POS, STICKER_POS)
            ty = random.uniform(-STICKER_POS, STICKER_POS)
            rot = random.uniform(-180, 180) if STICKER_ROTATE else 0.0
            st = d.StickerSegment(
                mid,
                d.Timerange(0, cursor),
                clip_settings=d.ClipSettings(scale_x=sx, scale_y=sx,
                                              transform_x=tx, transform_y=ty,
                                              rotation=rot,
                                              alpha=1.0 if STICKER_COMBINATION else STICKER_ALPHA),
            )
            # 复合片段模式下，滤色与1%透明度统一挂在外层；关闭时保持旧的逐贴纸行为。
            mix_inst = None
            if not STICKER_COMBINATION:
                mix_inst = MixMode(STICKER_MIX_MODE.value)
                st.extra_material_refs.append(mix_inst.global_id)
            script.add_segment(st, track=sticker_track)
            if mix_inst is not None:
                script.materials.mix_modes.append(mix_inst)
            alpha_desc = "复合片段内100%" if STICKER_COMBINATION else "不透明%.0f%%" % (STICKER_ALPHA * 100)
            print("[贴纸] %s 位置(%.2f,%.2f) 放大%.1f 旋转%.0f° %s"
                  % (name, tx, ty, sx, rot, alpha_desc))

    # 3.6) 随机抽 特效 + 滤镜，各自独立轨道，全屏覆盖
    if EFFECT_COUNT > 0 or FILTER_COUNT > 0:
        e_pool, f_pool = load_effect_filter_pool()
        for name, enum in random.sample(e_pool, min(EFFECT_COUNT, len(e_pool))):
            tname = "特效-" + name[:8]
            script.append_track(d.TrackSpec(d.TrackType.effect, name=tname))
            # 每个特效把它的全部参数(0~100)统一设为 EFFECT_INTENSITY
            nparam = len(enum.value.params)
            script.add_effect(enum, d.Timerange(0, cursor), track_name=tname,
                              params=[float(EFFECT_INTENSITY)] * nparam)
            print("[特效] %s 强度%d(%d参数)" % (name, EFFECT_INTENSITY, nparam))
        for name, enum in random.sample(f_pool, min(FILTER_COUNT, len(f_pool))):
            tname = "滤镜-" + name[:8]
            script.append_track(d.TrackSpec(d.TrackType.filter, name=tname))
            script.add_filter(enum, d.Timerange(0, cursor),
                              track_name=tname, intensity=FILTER_INTENSITY)
            print("[滤镜] %s 强度%d" % (name, FILTER_INTENSITY))

    # 3.7) 扫光 + 粒子消重素材：随机 N 条视频轨道铺满全程，滤色叠加
    if SWEEP_TRACKS > 0:
        build_overlay_tracks(script, cursor, load_sweep_pool(), "扫光",
                             SWEEP_TRACKS, SWEEP_SCALE, SWEEP_ALPHA, SWEEP_MIX_MODE)
    if PARTICLE_TRACKS > 0:
        build_overlay_tracks(script, cursor, load_particle_pool(), "粒子",
                             PARTICLE_TRACKS, PARTICLE_SCALE, PARTICLE_ALPHA, PARTICLE_MIX_MODE,
                             muted=True)

    # 3.8) 直播去重：同一素材8层蒙版叠加
    live_path = load_live_video()
    live_names = []
    if live_path:
        live_names = build_live_mask_tracks(script, cursor, live_path)
        print("[直播] 素材: %s" % os.path.basename(live_path))

    # 4) 保存
    script.save()

    # 4.1) 按指定层级重排轨道（数组越靠上=越在顶层）：
    #      背景→主视频→字幕→贴纸→特效→滤镜→扫光→粒子→直播
    def _layer(t):
        n = t.get("name", "")
        ty = t.get("type")
        if "背景" in n: return 0
        if ty == "text": return 2
        if n.startswith("贴纸"): return 3
        if n.startswith("特效"): return 4
        if n.startswith("滤镜"): return 5
        if n.startswith("扫光"): return 6
        if n.startswith("粒子"): return 7
        if n.startswith("直播"): return 8
        if ty == "video": return 1   # 主视频
        return 9
    dc_path = os.path.join(draft_dir, draft_name, "draft_content.json")
    with open(dc_path, encoding="utf-8") as f:
        j = json.load(f)
    if STICKER_COMBINATION:
        wrap_stickers_as_combination(j, cursor, os.path.join(draft_dir, draft_name))
    j["tracks"] = sorted(j["tracks"], key=_layer)
    # 新版剪映读 materials.common_masks（库写的是旧字段 masks，需同步过去）
    if j["materials"].get("masks"):
        j["materials"]["common_masks"] = j["materials"]["masks"]
    with open(dc_path, "w", encoding="utf-8") as f:
        json.dump(j, f, ensure_ascii=False)
    print("[排序] 轨道已按层级重排；蒙版已同步到 common_masks")

    # 4.2) 补全 draft_meta_info.json（库默认写空，剪映列表读不到草稿）
    meta_path = os.path.join(draft_dir, draft_name, "draft_meta_info.json")
    try:
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
    except Exception:
        meta = {}
    draft_root_fwd = draft_dir.replace("\\", "/")
    draft_fold_fwd = os.path.join(draft_dir, draft_name).replace("\\", "/")
    now_us = int(time.time() * 1000000)
    meta["draft_name"] = draft_name
    if os.environ.get('XUNZHEN_RESERVED_DRAFT_NAME'):
        meta['draft_id'] = str(uuid.uuid4()).upper()
    meta["draft_fold_path"] = draft_fold_fwd
    meta["draft_root_path"] = draft_root_fwd
    meta["draft_new_version"] = "164.0.0"
    meta["draft_is_invisible"] = False
    if not meta.get("tm_draft_create"):
        meta["tm_draft_create"] = now_us
    meta["tm_draft_modified"] = now_us
    meta["tm_duration"] = cursor
    if not meta.get("draft_cover"):
        meta["draft_cover"] = ""
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False)
    print("[meta] 已补全草稿 meta（名称/路径/时长）")

    print("=" * 50)
    print("完成！打开剪映专业版，草稿名: %s" % draft_name)
    print("（字幕若没显示样式，关了草稿再重开一次，剪映会加载字体）")


if __name__ == "__main__":
    from memory_safety import execute_with_logs
    execute_with_logs(main)
