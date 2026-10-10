# -*- coding: utf-8 -*-
import os
import json
import sqlite3
import whisper
import cv2
import numpy as np
import torch
from torchvision import models, transforms
from PIL import Image
from pathlib import Path
import streamlit as st
from rapidocr_onnxruntime import RapidOCR
from opencc import OpenCC
import faiss
import pickle
from database import DB_FILE, connect_database
from config import PATHS, CONFIG_FILE, load_settings, resolve_path, configure_runtime_paths
from query_device import select_query_device

configure_runtime_paths()

cc = OpenCC('t2s')  # 繁体转简体

# ========== 配置文件 ==========
WHISPER_MODEL = "base"
VIDEO_EXTS = [".mp4", ".mov", ".mkv", ".avi", ".flv", ".webm", ".ts"]
FRAME_INTERVAL = 10


def load_config():
    """读取配置文件"""
    return load_settings()


def save_config(cfg):
    """保存配置文件"""
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


CONFIG = load_config()
QUERY_DEVICE = select_query_device(CONFIG)
VIDEO_FOLDER = str(resolve_path(CONFIG["video_folder"])) if CONFIG.get("video_folder") else ""

FFMPEG_DIR = str(PATHS.ffmpeg_executable.parent)


@st.cache_resource
def load_ocr_model():
    return RapidOCR()


@st.cache_resource
def load_whisper_model():
    return whisper.load_model(WHISPER_MODEL, download_root=str(PATHS.models_dir))


# 人脸检测+人脸识别模型初始化
face_detector = None
face_recognizer = None
def init_face_models():
    global face_detector, face_recognizer
    if face_detector is not None:
        return
    det_path = str(PATHS.face_detection_model)
    rec_path = str(PATHS.face_recognition_model)
    face_detector = cv2.FaceDetectorYN_create(det_path, '', (320, 320), 0.7)
    face_recognizer = cv2.FaceRecognizerSF_create(rec_path, '')

def extract_face_feature(img_bgr):
    """提取图片中最大人脸的128维特征"""
    init_face_models()
    h, w = img_bgr.shape[:2]
    face_detector.setInputSize((w, h))
    _, faces = face_detector.detect(img_bgr)
    if faces is None or len(faces) == 0:
        return None
    # 选最大的人脸
    areas = [(f[2]*f[3], f) for f in faces]
    areas.sort(reverse=True)
    x,y,w_box,h_box = areas[0][1][:4]
    aligned = face_recognizer.alignCrop(img_bgr, areas[0][1])
    feat = face_recognizer.feature(aligned)
    return feat

def match_face(feat1, feat2):
    """比对两个人脸特征相似度，>0.4就是同一个人"""
    return face_recognizer.match(feat1, feat2, cv2.FaceRecognizerSF_FR_COSINE)

def load_feature_model():
    device = QUERY_DEVICE
    mnet = models.mobilenet_v2(weights=models.MobileNet_V2_Weights.DEFAULT)
    layers = list(mnet.children())[:-1]
    layers.append(torch.nn.AdaptiveAvgPool2d(1))
    mnet = torch.nn.Sequential(*layers)
    mnet.eval()
    mnet.to(device)
    preprocess = transforms.Compose([
        transforms.Resize((224, 224)),
        transforms.ToTensor(),
        transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
    ])
    return mnet, preprocess, device


FAISS_INDEX = None
FAISS_META = None

@st.cache_resource
def load_faiss_index():
    """加载FAISS向量索引和元数据"""
    global FAISS_INDEX, FAISS_META
    index_path = PATHS.faiss_index
    meta_path = PATHS.faiss_meta
    if index_path.exists() and meta_path.exists():
        FAISS_INDEX = faiss.read_index(str(index_path))
        with open(meta_path, 'rb') as f:
            FAISS_META = pickle.load(f)
        print(f"FAISS索引加载完成: {FAISS_INDEX.ntotal} 个向量")
    else:
        print("FAISS索引文件不存在，将使用遍历方式搜索")
    return FAISS_INDEX, FAISS_META


def green_ratio(img_bgr):
    # 计算画面里绿色像素占比，用来找绿衣服
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    lower_green = np.array([35, 40, 40])
    upper_green = np.array([77, 255, 255])
    mask = cv2.inRange(hsv, lower_green, upper_green)
    return np.sum(mask > 0) / mask.size

def red_ratio(img_bgr):
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    lower_red1 = np.array([0,40,40])
    upper_red1 = np.array([10,255,255])
    lower_red2 = np.array([160,40,40])
    upper_red2 = np.array([180,255,255])
    mask1 = cv2.inRange(hsv, lower_red1, upper_red1)
    mask2 = cv2.inRange(hsv, lower_red2, upper_red2)
    mask = mask1 + mask2
    return np.sum(mask>0)/mask.size

def calc_phash(img_bgr, size=32):
    """感知哈希：精确匹配你自己截的原图"""
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, (size, size))
    dct = cv2.dct(np.float32(gray))
    dct_low = dct[:8, :8]
    median = np.median(dct_low[1:])
    return (dct_low > median).flatten()

def hamming_dist(h1, h2):
    return np.count_nonzero(h1 != h2)

def calc_color_hist(img_bgr):
    """HSV颜色直方图：专门识别衣服颜色、背景颜色，区分红/蓝/白/黑衣服"""
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0,1], None, [12,8], [0,180,0,256])
    cv2.normalize(hist, hist)
    return hist.flatten()

# ORB局部特征匹配初始化（对镜像、裁剪、换背景、加特效都鲁棒）
orb = cv2.ORB_create(nfeatures=500, scaleFactor=1.2, nlevels=8)
bf_matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)

# 缩略图目录
THUMBNAIL_DIR = PATHS.thumbnails_dir

def load_frame_for_matching(file_path, timestamp, video_id=None):
    from raw_assets import CachedFrameProvider
    if video_id is None:
        with connect_database(DB_FILE) as conn:
            row = conn.execute('SELECT id FROM videos WHERE file_path=?', (file_path,)).fetchone()
        conn.close()
        video_id = row[0] if row else None
    if video_id is None:
        return None
    cached = CachedFrameProvider(legacy=THUMBNAIL_DIR).get(video_id, timestamp, prefer_legacy=True)
    return cv2.imdecode(np.frombuffer(cached.jpeg, np.uint8), cv2.IMREAD_COLOR) if cached else None

def match_orb_features(img1, img2, min_good=6):
    """用ORB局部特征点匹配两张图，返回好的匹配点数量"""
    kp1, des1 = orb.detectAndCompute(img1, None)
    kp2, des2 = orb.detectAndCompute(img2, None)
    if des1 is None or des2 is None or len(des1) < 5 or len(des2) < 5:
        return 0
    matches = bf_matcher.match(des1, des2)
    if not matches:
        return 0
    matches = sorted(matches, key=lambda x: x.distance)
    # 距离小于50的算好匹配
    good = [m for m in matches if m.distance < 50]
    return len(good)

query_color_frame = None
def extract_image_features(img_bgr):
    mnet, preprocess, device = load_feature_model()
    img = Image.fromarray(cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB))
    img_tensor = preprocess(img).unsqueeze(0).to(device)
    with torch.no_grad():
        feat = mnet(img_tensor)
        feat = feat.view(feat.size(0), -1).cpu().numpy()[0]
    feat = feat / np.linalg.norm(feat)
    # 保存原始截图供ORB匹配使用
    global query_color_frame
    query_color_frame = img_bgr
    phash = calc_phash(img_bgr)
    color_hist = calc_color_hist(img_bgr)
    return feat, phash, color_hist


def search_similar_frames(query_feat, query_phash, query_color, top_k=20):
    # 第一步：用FAISS向量检索快速取前40候选（毫秒级）
    faiss_index, faiss_meta = load_faiss_index()
    candidates = []
    
    if faiss_index is not None and faiss_meta is not None:
        query_vec = query_feat.reshape(1, -1).astype(np.float32)
        scores, indices = faiss_index.search(query_vec, 20)
        for i, idx in enumerate(indices[0]):
            if idx >= 0 and idx < len(faiss_meta):
                file_path, file_name, timestamp = faiss_meta[idx]
                candidates.append({
                    "file_path": file_path,
                    "file_name": file_name,
                    "timestamp": timestamp,
                    "sim_mobi": float(scores[0][i])
                })
    else:
        # FAISS不可用时回退到分批遍历
        conn = connect_database(DB_FILE)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        BATCH_SIZE = 5000
        offset = 0
        all_candidates = []
        while True:
            rows = cur.execute("""
                SELECT v.file_path, v.file_name, f.timestamp, f.features
                FROM frames f JOIN videos v ON f.video_id = v.id
                LIMIT ? OFFSET ?
            """, (BATCH_SIZE, offset)).fetchall()
            if not rows:
                break
            batch_results = []
            for r in rows:
                full_feat = np.frombuffer(r["features"], dtype=np.float32)
                mobi_feat = full_feat[:1280]
                if len(mobi_feat) < 1280:
                    continue
                sim_mobi = float(np.dot(query_feat, mobi_feat))
                batch_results.append({
                    "file_path": r["file_path"],
                    "file_name": r["file_name"],
                    "timestamp": r["timestamp"],
                    "sim_mobi": sim_mobi
                })
            batch_results.sort(key=lambda x: x["sim_mobi"], reverse=True)
            all_candidates.extend(batch_results[:20])
            offset += BATCH_SIZE
        conn.close()
        all_candidates.sort(key=lambda x: x["sim_mobi"], reverse=True)
        candidates = all_candidates[:20]

    # 第二步：只用持久缓存做ORB匹配，缺帧时降级，不读取原片。
    # 批量查询video_id
    conn_vid = connect_database(DB_FILE, timeout=30)
    cur_vid = conn_vid.cursor()
    path_to_vid = {}
    for r in candidates:
        if r["file_path"] not in path_to_vid:
            row = cur_vid.execute("SELECT id FROM videos WHERE file_path=?", (r["file_path"],)).fetchone()
            if row:
                path_to_vid[r["file_path"]] = row[0]
    conn_vid.close()
    
    final = []
    for r in candidates:
        try:
            vid = path_to_vid.get(r["file_path"])
            frame = load_frame_for_matching(r["file_path"], r["timestamp"], vid)
            if frame is not None and query_color_frame is not None:
                # 同时匹配原图和镜像翻转后的帧（对方镜像剪辑也能认）
                match_normal = match_orb_features(query_color_frame, frame)
                match_flip = match_orb_features(query_color_frame, cv2.flip(frame, 1))
                orb_score = max(match_normal, match_flip)
                # 辅助：pHash和颜色作为参考
                f_phash = calc_phash(frame)
                f_color = calc_color_hist(frame)
                phash_dist = hamming_dist(query_phash, f_phash)
                sim_phash = max(0, 1 - phash_dist / 64)
                sim_color = float(cv2.compareHist(query_color.astype(np.float32), f_color.astype(np.float32), cv2.HISTCMP_CORREL))
                # 综合得分：ORB权重最高（局部特征对变换鲁棒），然后pHash、颜色、语义
                total = min(orb_score / 30.0, 1.0) * 0.55 + sim_phash * 0.2 + sim_color * 0.15 + r["sim_mobi"] * 0.1
                r["similarity"] = total
                r["sim_detail"] = f"ORB特征点:{orb_score}个 | pHash:{sim_phash:.2f} | 颜色:{sim_color:.2f} | 场景:{r['sim_mobi']:.2f}"
                final.append(r)
            else:
                # 缺持久帧时保留已有召回，降级到场景分，不回原视频抽帧。
                r["similarity"] = r["sim_mobi"]
                r["sim_detail"] = "ORB_CACHE_MISS | 场景相似度降级"
                final.append(r)
        except Exception as e:
            r["similarity"] = r["sim_mobi"]
            r["sim_detail"] = f"场景:{r['sim_mobi']:.2f} (ORB匹配失败)"
            final.append(r)
    final.sort(key=lambda x: x["similarity"], reverse=True)
    return [r for r in final if r["similarity"] > 0.2][:top_k]


def init_db():
    conn = connect_database(DB_FILE, read_only=False)
    cur = conn.cursor()
    cur.execute('''CREATE TABLE IF NOT EXISTS videos
                   (id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_path TEXT UNIQUE,
                    file_name TEXT,
                    processed_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
    cur.execute('''CREATE TABLE IF NOT EXISTS subtitles
                   (id INTEGER PRIMARY KEY AUTOINCREMENT,
                    video_id INTEGER,
                    start REAL,
                    end REAL,
                    text TEXT,
                    FOREIGN KEY(video_id) REFERENCES videos(id))''')
    cur.execute('''CREATE TABLE IF NOT EXISTS frames
                   (id INTEGER PRIMARY KEY AUTOINCREMENT,
                    video_id INTEGER,
                    timestamp REAL,
                    features BLOB,
                    FOREIGN KEY(video_id) REFERENCES videos(id))''')
    cur.execute("CREATE INDEX IF NOT EXISTS idx_sub_text ON subtitles(text)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_frames_video ON frames(video_id)")
    conn.commit()
    conn.close()


def search_by_keyword(keyword):
    conn = connect_database(DB_FILE)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    sql = '''
    SELECT v.file_path, v.file_name, s.start, s.end, s.text
    FROM subtitles s JOIN videos v ON s.video_id = v.id
    WHERE s.text LIKE ? ORDER BY v.file_path, s.start
    '''
    rows = cur.execute(sql, (f"%{keyword}%",)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def ocr_image(img_bytes):
    ocr = load_ocr_model()
    nparr = np.frombuffer(img_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    result, _ = ocr(img)
    if not result:
        return []
    return [item[1] for item in result]


def fix_old_paths(old_prefix, new_prefix):
    """批量修复旧路径：把数据库里所有以old_prefix开头的路径替换成new_prefix"""
    conn = connect_database(DB_FILE, read_only=False)
    cur = conn.cursor()
    # 更新videos表
    cur.execute("UPDATE videos SET file_path = REPLACE(file_path, ?, ?)", (old_prefix, new_prefix))
    updated = cur.rowcount
    conn.commit()
    conn.close()
    return updated


def get_thumbnail_for_time(video_path, timestamp):
    """只读持久化缩略图；兼容旧返回路径协议，内嵌JPEG返回BytesIO。"""
    from io import BytesIO
    from raw_assets import PersistentThumbnailStore
    conn = connect_database(DB_FILE)
    try:
        row = conn.execute('SELECT id FROM videos WHERE file_path=?', (video_path,)).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    cached = PersistentThumbnailStore().get(row[0], timestamp)
    return BytesIO(cached.jpeg) if cached else None


def format_time(seconds):
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"{m:02d}:{s:02d}"


def show_text_results(results):
    if not results:
        st.warning("未找到匹配片段")
        return
    st.success(f"找到 {len(results)} 条匹配片段")
    for r in results:
        with st.expander(f"📹 {r['file_name']} | {format_time(r['start'])} - {format_time(r['end'])}"):
            col1, col2 = st.columns([1, 2])
            with col1:
                thumb_path = get_thumbnail_for_time(r["file_path"], r["start"])
                if thumb_path:
                    try:
                        img = Image.open(thumb_path)
                        st.image(img, caption="对应时间点画面", width=240)
                    except Exception as e:
                        st.info(f"图片加载失败: {e}")
                else:
                    st.info("暂无缩略图")
            with col2:
                st.write(f"**时间：** {format_time(r['start'])} ~ {format_time(r['end'])}")
                st.write(f"**台词：** {r['text']}")
                with st.expander("查看完整视频路径"):
                    st.code(r["file_path"])
            output_path = PATHS.export_dir / f'clip_{Path(r["file_name"]).stem}_{int(r["start"])}.mp4'
            cmd = f'"{PATHS.ffmpeg_executable}" -ss {r["start"]:.1f} -to {r["end"]+2:.1f} -i "{r["file_path"]}" -c copy "{output_path}"'
            st.code(cmd, language="bash")


# ========== Streamlit 页面 ==========
st.set_page_config(page_title="陶老师直播素材检索", layout="wide", page_icon="🎥")
st.title("🎥 陶老师直播素材检索工具")

if not DB_FILE.is_file():
    st.error(f"主数据库不存在：{DB_FILE}。请检查项目位置和数据库文件，不会自动创建空库或切换到旧库。")
    st.stop()

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(["⚙️ 设置", "📊 索引状态", "🔍 文字搜索", "🖼️ 以图搜视频", "📝 截图OCR", "🧑 找这个人"])

# Tab1: 设置（修改素材路径）
with tab1:
    st.header("⚙️ 素材库设置")
    st.subheader("1. 设置素材根目录")
    st.write("所有视频都从这个目录递归扫描，新加的视频只要放到这个目录下，重新跑批量处理就会自动识别。")
    new_folder = st.text_input("素材文件夹路径", value=VIDEO_FOLDER)
    if st.button("保存路径设置"):
        CONFIG["video_folder"] = new_folder
        save_config(CONFIG)
        st.success(f"✅ 已保存素材路径：{new_folder}")
        st.rerun()

    st.divider()
    st.subheader("2. 旧素材换文件夹后，一键修复路径")
    st.write("如果整个素材文件夹移动了位置（比如从E盘移到D盘，或者改了文件夹名），不用重新索引，直接在这里批量替换路径：")
    old_prefix = st.text_input("旧素材目录的完整路径")
    new_prefix = st.text_input("新素材目录的完整路径")
    if st.button("一键修复所有旧路径", type="primary") and old_prefix and new_prefix:
        cnt = fix_old_paths(old_prefix, new_prefix)
        st.success(f"✅ 已修复 {cnt} 个视频的路径，所有搜索和裁剪命令现在都指向新位置了。")

    st.divider()
    st.subheader("3. 旧字幕一键转简体")
    st.write("如果之前转写的字幕是繁体，点这个按钮一键全部转成简体，不用重新转写视频。")
    if st.button("🔄 一键把所有繁体字幕转成简体"):
        conn = connect_database(DB_FILE, read_only=False)
        cur = conn.cursor()
        cur.execute("SELECT id, text FROM subtitles")
        rows = cur.fetchall()
        cnt = 0
        for sid, old_text in rows:
            new_text = cc.convert(old_text)
            if new_text != old_text:
                cur.execute("UPDATE subtitles SET text=? WHERE id=?", (new_text, sid))
                cnt += 1
        conn.commit()
        conn.close()
        st.success(f"✅ 转换完成！共转换 {cnt} 条繁体字幕为简体。")

    st.divider()
    st.subheader("4. 怎么加新素材？")
    st.write("""
    1. 把新视频（.ts/.mp4等格式）直接放到上面设置的素材文件夹里（可以新建子文件夹，自动递归扫描）
    2. 重新跑一次批量处理脚本（batch_transcribe.py）
    3. 已经处理过的旧视频会自动跳过，只处理新添加的视频
    4. 处理完直接在网页上搜索就行，不用重启服务
    """)

# Tab2: 索引状态
with tab2:
    st.header("📊 素材索引状态")
    st.write(f"当前素材目录：`{VIDEO_FOLDER}`")
    if DB_FILE.exists():
        conn = connect_database(DB_FILE)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM videos")
        v_cnt = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM subtitles")
        s_cnt = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM frames")
        f_cnt = cur.fetchone()[0]
        conn.close()
        c1, c2, c3 = st.columns(3)
        c1.metric("已处理视频", v_cnt)
        c2.metric("字幕片段", s_cnt)
        c3.metric("画面帧特征", f_cnt)
        st.info("后台批量脚本会自动增量处理：已经处理过的视频自动跳过，新加的视频自动识别。")

# Tab3: 文字搜索
with tab3:
    st.header("🔍 按台词关键词搜索")
    keyword = st.text_input("输入要找的台词/关键词", placeholder="例如：手法、位置、穴位...")
    if st.button("搜索", type="primary") and keyword.strip():
        show_text_results(search_by_keyword(keyword.strip()))

# Tab4: 以图搜视频
with tab4:
    st.header("🖼️ 上传截图，找相似画面")
    st.write("上传一张画面截图（动作、场景、人物），自动在所有直播视频中找到最相似的片段。")
    uploaded = st.file_uploader("选择截图", type=["png", "jpg", "jpeg"], key="img_search")
    if uploaded is not None:
        st.image(uploaded, caption="已上传截图", width=400)
        if st.button("🎯 查找相似画面", type="primary"):
            with st.spinner("正在分析截图特征（识别人物、衣服颜色）..."):
                img_bytes = uploaded.read()
                nparr = np.frombuffer(img_bytes, np.uint8)
                img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                query_feat, query_phash, query_color = extract_image_features(img)
            with st.spinner("正在视频库中精确匹配（含原图校验、颜色识别）..."):
                results = search_similar_frames(query_feat, query_phash, query_color, top_k=10)
            if not results:
                st.warning("还没有画面特征数据，等视频抽帧完成后再试。")
            else:
                st.success(f"找到最相似的 {len(results)} 个时间点：")
                cols = st.columns(2)
                for i, r in enumerate(results):
                    with cols[i % 2]:
                        st.subheader(f"#{i+1} 综合得分 {r['similarity']:.2f}")
                        st.caption(r["sim_detail"])
                        thumb_path = get_thumbnail_for_time(r["file_path"], r["timestamp"])
                        if thumb_path:
                            try:
                                img = Image.open(thumb_path)
                                st.image(img, caption=f"{r['file_name']} | {format_time(r['timestamp'])}", width=280)
                            except:
                                st.info("图片加载失败")
                        st.write(f"**时间：** {format_time(r['timestamp'])}（约 {r['timestamp']:.0f} 秒处）")
                        with st.expander("查看视频完整路径"):
                            st.code(r["file_path"])
                        output_path = PATHS.export_dir / f'scene_{i+1}_{int(r["timestamp"])}.mp4'
                        cmd = f'"{PATHS.ffmpeg_executable}" -ss {max(0, r["timestamp"]-5):.1f} -to {r["timestamp"]+15:.1f} -i "{r["file_path"]}" -c copy "{output_path}"'
                        st.code(cmd, language="bash")

# Tab5: 截图OCR
with tab5:
    st.header("📝 截图文字识别搜索")
    st.write("如果截图里有文字（比如弹幕、标题、字幕），自动识别文字后搜索对应片段。")
    uploaded_ocr = st.file_uploader("选择带文字的截图", type=["png", "jpg", "jpeg"], key="ocr_search")
    if uploaded_ocr is not None:
        st.image(uploaded_ocr, caption="已上传截图", width=400)
        if st.button("📸 识别文字并搜索", type="primary"):
            with st.spinner("正在识别截图文字..."):
                img_bytes = uploaded_ocr.read()
                texts = ocr_image(img_bytes)
            if not texts:
                st.warning("没有识别到文字")
            else:
                st.write("识别到的文字：", " | ".join(texts))
                all_res = []
                seen = set()
                for t in texts:
                    t = t.strip()
                    if len(t) < 2:
                        continue
                    for r in search_by_keyword(t):
                        k = (r['file_path'], r['start'], r['end'])
                        if k not in seen:
                            seen.add(k)
                            all_res.append(r)
                show_text_results(all_res)

st.divider()
# Tab6: 找同一个人
with tab6:
    st.header("🧑 上传一张人脸，找这个人所有出现的片段")
    st.write("不管这个人在什么场景、穿什么衣服，只要是同一张脸，全部找出来。")
    uploaded_face = st.file_uploader("上传这个人的人脸截图", type=["png","jpg","jpeg"], key="face_search")
    if uploaded_face is not None:
        st.image(uploaded_face, caption="已上传人脸", width=300)
        if st.button("🔍 开始找这个人", type="primary"):
            with st.spinner("正在提取上传人脸特征..."):
                img_bytes = uploaded_face.read()
                nparr = np.frombuffer(img_bytes, np.uint8)
                img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                query_feat = extract_face_feature(img)
                if query_feat is None:
                    st.error("没在你上传的截图里检测到人脸，请换一张正面清晰的人脸图")
                else:
                    st.success("人脸特征提取完成，开始全库扫描...")
                    # 从数据库拿所有帧的候选
                    conn = connect_database(DB_FILE)
                    conn.row_factory = sqlite3.Row
                    cur = conn.cursor()
                    rows = cur.execute("""SELECT v.file_path, v.file_name, f.timestamp FROM frames f JOIN videos v ON f.video_id=v.id""").fetchall()
                    conn.close()
                    found = []
                    progress = st.progress(0)
                    for i, r in enumerate(rows):
                        try:
                            frame = load_frame_for_matching(r["file_path"], r["timestamp"])
                            if frame is not None:
                                f_feat = extract_face_feature(frame)
                                if f_feat is not None:
                                    sim = match_face(query_feat, f_feat)
                                    if sim > 0.45:
                                        found.append({
                                            "file_path": r["file_path"],
                                            "file_name": r["file_name"],
                                            "timestamp": r["timestamp"],
                                            "sim": sim
                                        })
                        except:
                            pass
                        progress.progress(int((i+1)/len(rows)*100))
                    found.sort(key=lambda x:x["sim"], reverse=True)
                    if not found:
                        st.warning("没在视频库里找到和这个人相似的人脸")
                    else:
                        st.success(f"找到这个人出现 {len(found)} 次！")
                        for i, r in enumerate(found[:20]):
                            with st.expander(f"#{i+1} 相似度 {r['sim']:.2f} | {r['file_name']} | {format_time(r['timestamp'])}"):
                                thumb = get_thumbnail_for_time(r["file_path"], r["timestamp"])
                                if thumb:
                                    try:
                                        st.image(Image.open(thumb), width=240)
                                    except: pass
                                st.code(r["file_path"])

st.caption("所有处理都在本机完成，素材不上传服务器。")

