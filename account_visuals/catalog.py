"""小型本地背景素材池；只扫描已配置背景目录，不扫描视频生产库。"""
from pathlib import Path
import json
import math
import subprocess

from .storage import ROOT, AccountBackgroundStore, file_hash, now

IMAGE_EXT = {'.png', '.jpg', '.jpeg', '.webp', '.bmp'}
VIDEO_EXT = {'.mp4', '.mov', '.mkv', '.avi', '.webm', '.m4v', '.gif'}


def background_root():
    config = json.loads((ROOT / 'jianying_auto/config.json').read_text('utf-8'))
    path = Path(config['bg_dir'])
    return (path if path.is_absolute() else ROOT / 'jianying_auto' / path).resolve()


def binary(name):
    config = json.loads((ROOT / 'config.json').read_text('utf-8'))['paths']
    configured = config.get(name + '_executable')
    path = Path(configured or Path(config['ffmpeg_executable']).with_name(name + '.exe'))
    path = path if path.is_absolute() else ROOT / path
    if not path.is_file() and name == 'ffprobe':
        adapter = json.loads((ROOT / 'xiaovcat_adapter/config.json').read_text('utf-8'))
        path = Path(adapter['executable_path']).parent / 'resources/app/ffprobe.exe'
    if not path.is_file():
        raise ValueError(name.upper() + '_UNAVAILABLE_NO_DOWNLOAD')
    return path


def hidden(args):
    startup = subprocess.STARTUPINFO() if hasattr(subprocess, 'STARTUPINFO') else None
    if startup is not None:
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = subprocess.SW_HIDE
    return subprocess.run([str(a) for a in args], capture_output=True, timeout=30, shell=False,
                          startupinfo=startup, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), check=True)


def inspect_asset(path, cache):
    from PIL import Image
    before = path.stat()
    sha = file_hash(path)
    kind = 'IMAGE' if path.suffix.lower() in IMAGE_EXT else 'VIDEO'
    thumb = cache / (sha + '.jpg')
    cache.mkdir(parents=True, exist_ok=True)
    if kind == 'IMAGE':
        with Image.open(path) as im:
            width, height = im.size
            if not thumb.exists():
                im = im.convert('RGB')
                im.thumbnail((360, 640))
                im.save(thumb, quality=85)
        duration = 0.0
    else:
        media = json.loads(hidden([binary('ffprobe'), '-v', 'error', '-show_entries',
            'format=duration:stream=codec_type,width,height,duration', '-of', 'json', path]).stdout)
        stream = next(s for s in media['streams'] if s.get('codec_type') == 'video')
        width, height = int(stream['width']), int(stream['height'])
        duration = float(media.get('format', {}).get('duration') or stream.get('duration') or 0)
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError('BACKGROUND_INVALID_DURATION')
        if not thumb.exists():
            hidden([binary('ffmpeg'), '-v', 'error', '-y', '-i', path, '-frames:v', '1',
                    '-vf', 'scale=360:640:force_original_aspect_ratio=decrease', thumb])
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError('BACKGROUND_CHANGED_DURING_SCAN')
    if width <= 0 or height <= 0:
        raise ValueError('BACKGROUND_INVALID_SIZE')
    return dict(background_asset_id='BG-' + sha, path=str(path), filename=path.name,
                hash=sha, width=width, height=height, duration=duration, type=kind, thumbnail_path=str(thumb))


def scan(store=None, *, root=None, cache=None):
    store = store or AccountBackgroundStore()
    root = Path(root or background_root()).resolve(strict=True)
    if str(root).startswith(('\\\\', '//')) or not root.is_dir():
        raise ValueError('BACKGROUND_LOCAL_DIRECTORY_REQUIRED')
    cache = Path(cache or ROOT / 'account_visuals/runtime/thumbnails')
    assets, errors = [], []
    for path in sorted(root.rglob('*')):
        if path.is_file() and path.suffix.lower() in IMAGE_EXT | VIDEO_EXT:
            try:
                resolved = path.resolve(strict=True)
                if not resolved.is_relative_to(root):
                    raise ValueError('BACKGROUND_OUTSIDE_CONFIGURED_ROOT')
                assets.append(inspect_asset(resolved, cache))
            except Exception as error:
                errors.append({'path': str(path), 'error': str(error)})
    store.migrate()
    stamp = now()
    with store.connect(write=True) as db:
        # 文件异常时保留上一次编目，避免一个读取错误清空整个池。
        if not errors:
            db.execute('UPDATE background_material_catalog SET available=0')
            db.execute('DELETE FROM background_material_aliases')
        unique = {}
        for asset in assets:
            unique.setdefault(asset['hash'], asset)
        for asset in unique.values():
            db.execute('''INSERT INTO background_material_catalog VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(hash) DO UPDATE SET path=excluded.path,filename=excluded.filename,
                thumbnail_path=excluded.thumbnail_path,available=1,updated_at=excluded.updated_at''',
                (*[asset[k] for k in ('background_asset_id','path','filename','hash','width','height','duration','type','thumbnail_path')], 1, stamp, stamp))
        for asset in assets:
            db.execute('INSERT INTO background_material_aliases VALUES(?,?) ON CONFLICT(path) DO UPDATE SET background_asset_id=excluded.background_asset_id',
                       (asset['path'], asset['background_asset_id']))
        result = dict(files=len(assets), unique=len(unique), errors=errors, root=str(root), scanned_at=stamp)
        db.execute('INSERT INTO background_catalog_state VALUES(1,?,?,?) ON CONFLICT(singleton) DO UPDATE SET root=excluded.root,scanned_at=excluded.scanned_at,result_json=excluded.result_json',
                   (str(root), stamp, json.dumps(result, ensure_ascii=False)))
    return result
