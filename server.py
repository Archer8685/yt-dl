"""YT 影片下載器 — 本機 Flask 後端（包裝 yt-dlp）。

啟動：  start.bat（Windows）或 ./start.sh   然後開 http://127.0.0.1:8765
環境變數：
  YTDL_PORT / YTDL_HOST         監聽位址（預設 127.0.0.1:8765）
  YTDL_AUTO_UPDATE=0            關閉啟動時自動更新 yt-dlp
  YTDL_CHANNEL=nightly          使用 yt-dlp nightly（pre-release）版本
  YTDL_ALLOWED_ORIGINS          允許跨來源呼叫的網站（逗號分隔），預設含 GitHub Pages
"""
from __future__ import annotations

import io
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
import zipfile
from collections import deque
from pathlib import Path

from flask import Flask, abort, jsonify, request, send_file, send_from_directory

import ytdlp_update

APP_NAME = "YT-Downloader"
# PyInstaller 打包版（.exe / macOS）：程式本身解壓在暫存資料夾，設定與 cookies 改存使用者資料夾
FROZEN = bool(getattr(sys, "frozen", False))
BUNDLE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))


def _user_data_dir() -> Path:
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / APP_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / APP_NAME


if FROZEN:
    ROOT = _user_data_dir()
    # 不能和 macOS 解壓出來的執行檔 ~/Downloads/YT-Downloader 同名
    DEFAULT_DOWNLOAD_DIR = Path.home() / "Downloads" / "YT-Downloads"
    # 優先使用打包在裡面的 ffmpeg / ffprobe / deno（YouTube 需要 JS runtime）
    os.environ["PATH"] = os.pathsep.join([str(BUNDLE / "bin"), os.environ.get("PATH", "")])
else:
    ROOT = BUNDLE
    DEFAULT_DOWNLOAD_DIR = ROOT / "downloads"
ROOT.mkdir(parents=True, exist_ok=True)

# 打包版：使用者資料夾裡若有自動更新下載的較新 yt-dlp，優先載入；載入失敗就退回內建版本
YTDLP_OVERLAY = ytdlp_update.activate(ROOT, BUNDLE) if FROZEN else None
try:
    import yt_dlp
except Exception:
    if not YTDLP_OVERLAY:
        raise
    ytdlp_update.fallback(ROOT)
    YTDLP_OVERLAY = None
    import yt_dlp
from yt_dlp.utils import download_range_func, parse_duration, prepend_extension

SETTINGS_FILE = ROOT / "settings.json"
# 剩餘空間低於此值就停止下載，保護系統碟（預設 2 GB）
MIN_FREE_BYTES = int(float(os.environ.get("YTDL_MIN_FREE_GB", "2")) * 1024**3)


def _load_settings() -> dict:
    try:
        return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def get_download_dir() -> Path:
    """下載位置：環境變數 > settings.json > 專案內 downloads/。"""
    raw = os.environ.get("YTDL_DOWNLOAD_DIR") or _load_settings().get("download_dir")
    d = Path(raw).expanduser() if raw else DEFAULT_DOWNLOAD_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def disk_info(path: Path) -> dict:
    try:
        u = shutil.disk_usage(path)
        return {"path": str(path), "free": u.free, "total": u.total}
    except OSError:
        return {"path": str(path), "free": None, "total": None}


get_download_dir()  # 啟動時先建立下載資料夾
COOKIES_FILE = ROOT / "cookies.txt"
HOST = os.environ.get("YTDL_HOST", "127.0.0.1")
PORT = int(os.environ.get("YTDL_PORT", "8765"))
CHANNEL = "nightly" if os.environ.get("YTDL_CHANNEL", "").lower() == "nightly" else "stable"
ALLOWED_ORIGINS = {o.strip().rstrip("/") for o in os.environ.get(
    "YTDL_ALLOWED_ORIGINS", "https://archer8685.github.io").split(",") if o.strip()}

app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024  # cookies.txt 上傳上限


def _origin_allowed(origin: str) -> bool:
    if not origin:
        return False
    if origin.rstrip("/") in ALLOWED_ORIGINS:
        return True
    return bool(re.fullmatch(r"https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?", origin))


@app.before_request
def _cors_preflight():
    if request.method == "OPTIONS":
        return app.make_default_options_response()
    # 擋掉未允許網站的跨來源寫入（避免任意網頁操控本機下載器）
    origin = request.headers.get("Origin")
    if origin and request.method != "GET" and not _origin_allowed(origin) \
            and origin != request.host_url.rstrip("/"):
        return jsonify(error="此來源未被允許"), 403


@app.after_request
def _cors_headers(resp):
    origin = request.headers.get("Origin")
    if _origin_allowed(origin):
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Vary"] = "Origin"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
        resp.headers["Access-Control-Expose-Headers"] = "Content-Disposition"
        # Chrome Private/Local Network Access：允許公開網站（GitHub Pages）呼叫本機
        resp.headers["Access-Control-Allow-Private-Network"] = "true"
    return resp


# --------------------------------------------------------------------------- #
#  yt-dlp 自動更新
# --------------------------------------------------------------------------- #
_LATEST = {"version": None, "data": None, "checked": 0.0}
# ready：打包版已下載好、重新啟動後就會使用的 yt-dlp 版本
UPDATE_STATE = {"running": False, "message": None, "ready": None}
_vtuple = ytdlp_update.vtuple


def latest_version(force=False) -> str | None:
    """PyPI 上最新的 yt-dlp 版本（快取 6 小時；nightly 頻道包含 pre-release）。"""
    if not force and time.time() - _LATEST["checked"] < 6 * 3600:
        return _LATEST["version"]
    try:
        _LATEST["version"], _LATEST["data"] = ytdlp_update.latest(CHANNEL)
    except Exception:  # noqa: BLE001, S110 — 離線時忽略
        pass
    _LATEST["checked"] = time.time()
    return _LATEST["version"]


def _verify_ytdlp(path: Path) -> bool:
    """在另一個程序實際載入新版 yt-dlp，確認能用才切換（打包版用 App 本身的 --check-ytdlp）。"""
    cmd = [sys.executable] if FROZEN else [sys.executable, str(BUNDLE / "desktop.py")]
    try:
        p = subprocess.run([*cmd, "--check-ytdlp", str(path)], capture_output=True, timeout=120, check=False)
    except (OSError, subprocess.SubprocessError):
        return False
    return p.returncode == 0 and (path / "OK").is_file()


_UPGRADE_LOCK = threading.Lock()  # 背景自動更新與手動「更新」不能同時寫同一個暫存資料夾


def app_upgrade() -> tuple[bool, str]:
    """打包版沒有 pip：從 PyPI 下載新版 yt-dlp 放到使用者資料夾，重新啟動後生效。"""
    with _UPGRADE_LOCK:
        return _app_upgrade()


def _app_upgrade() -> tuple[bool, str]:
    latest = latest_version(force=True)
    if not latest or not _LATEST["data"]:
        return False, "無法連線到 PyPI"
    if _vtuple(latest) <= _vtuple(UPDATE_STATE["ready"] or yt_dlp.version.__version__):
        return True, "已是最新版"
    try:
        ytdlp_update.install(ROOT, latest, _LATEST["data"], _verify_ytdlp)
    except Exception as e:  # noqa: BLE001
        return False, str(e)
    UPDATE_STATE["ready"] = latest
    keep = {latest} | ({YTDLP_OVERLAY} if YTDLP_OVERLAY else set())
    ytdlp_update.cleanup(ROOT, keep)
    return True, f"yt-dlp {latest} 已下載，重新啟動後套用"


def upgrade() -> tuple[bool, str]:
    return app_upgrade() if FROZEN else pip_upgrade()


def pip_upgrade() -> tuple[bool, str]:
    cmd = [sys.executable, "-m", "pip", "install", "-U", "--disable-pip-version-check", "yt-dlp[default]"]
    if CHANNEL == "nightly":
        cmd.insert(4, "--pre")
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=300, check=False)
        return p.returncode == 0, (p.stdout + p.stderr)[-800:]
    except Exception as e:  # noqa: BLE001
        return False, str(e)


def restart_process():
    """以相同參數重新啟動自己（載入新版 yt-dlp）。"""
    env = {**os.environ, "YTDL_JUST_UPDATED": "1"}
    # 打包版 sys.argv[0] 就是 App 本身；原始碼版要再帶上 server.py / desktop.py
    args = sys.argv[1:] if FROZEN else sys.argv
    subprocess.Popen([sys.executable, *args], env=env, cwd=str(ROOT))
    os._exit(0)

# 啟用 deno 與 node（YouTube 需要 JS runtime 解 challenge）
BASE_OPTS = {
    "quiet": True,
    "no_warnings": False,
    "noprogress": True,
    "js_runtimes": {"deno": {"path": None}, "node": {"path": None}},
}

VIDEO_CONTAINERS = ("mp4", "mkv", "webm", "mov", "avi", "flv")
AUDIO_CODECS = ("mp3", "m4a", "aac", "opus", "vorbis", "flac", "wav", "alac")
SUB_FORMATS = ("srt", "vtt", "ass", "lrc")
THUMB_FORMATS = ("jpg", "png", "webp")
SPONSOR_CATS = ("sponsor", "intro", "outro", "selfpromo", "preview",
                "filler", "interaction", "music_offtopic", "poi_highlight", "chapter")
BROWSERS = ("chrome", "edge", "firefox", "brave", "opera", "vivaldi", "chromium", "safari")
TEMP_SUFFIXES = (".part", ".ytdl", ".temp", ".frag")
# yt-dlp 分開下載影像 / 音訊串流時的檔名：<檔名>.f<格式代號>.<副檔名>
STREAM_RE = re.compile(r"\.f[\w-]+\.(mp4|webm|m4a|mkv|mov|flv|3gp|mp3|opus|ogg|aac|ts)$", re.IGNORECASE)


class Cancelled(Exception):
    pass


class DiskFull(Exception):
    pass


def _gb(n) -> str:
    return f"{n / 1024**3:.1f} GB" if n is not None else "?"


# --------------------------------------------------------------------------- #
#  資訊擷取
# --------------------------------------------------------------------------- #
def _num(v):
    return v if isinstance(v, (int, float)) else None


def _fmt_summary(f: dict) -> dict:
    vcodec = f.get("vcodec") or "none"
    acodec = f.get("acodec") or "none"
    has_v = vcodec != "none"
    has_a = acodec != "none"
    kind = "av" if has_v and has_a else "video" if has_v else "audio" if has_a else "other"
    if f.get("format_note") == "storyboard" or f.get("ext") == "mhtml":
        kind = "other"
    return {
        "id": f.get("format_id"),
        "kind": kind,
        "ext": f.get("ext"),
        "width": _num(f.get("width")),
        "height": _num(f.get("height")),
        "resolution": f.get("resolution"),
        "fps": _num(f.get("fps")),
        "dynamic_range": f.get("dynamic_range"),
        "vcodec": vcodec if has_v else None,
        "acodec": acodec if has_a else None,
        "abr": _num(f.get("abr")),
        "vbr": _num(f.get("vbr")),
        "tbr": _num(f.get("tbr")),
        "asr": _num(f.get("asr")),
        "channels": _num(f.get("audio_channels")),
        "filesize": _num(f.get("filesize")) or _num(f.get("filesize_approx")),
        "approx": not f.get("filesize") and bool(f.get("filesize_approx")),
        "protocol": f.get("protocol"),
        "language": f.get("language"),
        "note": f.get("format_note"),
        "drc": "drc" in str(f.get("format_id", "")),
    }


def _subs_summary(subs: dict | None) -> list[dict]:
    out = []
    for lang, items in (subs or {}).items():
        if lang == "live_chat":
            continue
        items = items or []
        name = next((i.get("name") for i in items if i.get("name")), "") or lang
        out.append({"lang": lang, "name": name, "exts": sorted({i.get("ext") for i in items if i.get("ext")})})
    return sorted(out, key=lambda s: s["name"].lower())


def _audio_tracks(formats: list[dict]) -> list[dict]:
    """依語言分組的音軌（YouTube 多音軌影片會有多種 language）。"""
    tracks: dict[str, dict] = {}
    for f in formats:
        if f["kind"] != "audio" or not f.get("language"):
            continue
        lang = f["language"]
        note = f.get("note") or ""
        label = re.split(r",\s*(?:low|medium|high|ultralow|DRC)", note)[0].strip() or lang
        t = tracks.setdefault(lang, {"lang": lang, "label": label, "original": False, "count": 0})
        t["count"] += 1
        if "original" in note.lower():
            t["original"] = True
        if len(label) > len(t["label"]):
            t["label"] = label
    return sorted(tracks.values(), key=lambda t: (not t["original"], t["label"].lower()))


@app.post("/api/info")
def api_info():
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    if not re.match(r"^https?://", url):
        return jsonify(error="請輸入有效的網址（http/https）"), 400
    opts = {**BASE_OPTS, "skip_download": True, "extract_flat": "in_playlist",
            "noplaylist": bool(data.get("noplaylist", True))}
    _apply_network_opts(opts, data.get("network") or {})
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:  # noqa: BLE001
        return jsonify(error=_clean_err(e)), 400

    if info.get("_type") == "playlist":
        entries = []
        for i, e in enumerate(info.get("entries") or [], 1):
            if not e:
                continue
            thumbs = e.get("thumbnails") or []
            entries.append({
                "index": i, "id": e.get("id"), "title": e.get("title"),
                "duration": _num(e.get("duration")), "url": e.get("url") or e.get("webpage_url"),
                "thumbnail": thumbs[-1]["url"] if thumbs else None,
                "uploader": e.get("uploader") or e.get("channel"),
            })
        return jsonify(type="playlist", id=info.get("id"), title=info.get("title"),
                       uploader=info.get("uploader") or info.get("channel"),
                       webpage_url=info.get("webpage_url") or url, entries=entries)

    formats = [_fmt_summary(f) for f in info.get("formats") or []]
    formats = [f for f in formats if f["kind"] != "other"]
    heights = sorted({f["height"] for f in formats if f["kind"] in ("video", "av") and f["height"]}, reverse=True)
    return jsonify(
        type="video",
        id=info.get("id"),
        title=info.get("title"),
        uploader=info.get("uploader") or info.get("channel"),
        channel_url=info.get("channel_url") or info.get("uploader_url"),
        duration=_num(info.get("duration")),
        view_count=_num(info.get("view_count")),
        like_count=_num(info.get("like_count")),
        upload_date=info.get("upload_date"),
        description=(info.get("description") or "")[:2000],
        thumbnail=info.get("thumbnail"),
        webpage_url=info.get("webpage_url") or url,
        extractor=info.get("extractor_key"),
        is_live=bool(info.get("is_live")),
        chapters=[{"title": c.get("title"), "start": c.get("start_time"), "end": c.get("end_time")}
                  for c in info.get("chapters") or []],
        formats=formats,
        heights=heights,
        audio_tracks=_audio_tracks(formats),
        subtitles=_subs_summary(info.get("subtitles")),
        auto_captions=_subs_summary(info.get("automatic_captions")),
    )


# --------------------------------------------------------------------------- #
#  選項 → yt-dlp 參數
# --------------------------------------------------------------------------- #
def _pick(value, allowed, default=None):
    return value if value in allowed else default


def _int(v, default: int, lo: int, hi: int) -> int:
    """數字選項：空值用預設，0 是合法值（不能用 `or` 判斷）。"""
    try:
        n = int(v)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


def _safe_id(s: str) -> str:
    """format id / 語言碼只允許安全字元，避免注入 format 語法。"""
    return re.sub(r"[^A-Za-z0-9_.\-]", "", str(s))[:40]


def _safe_template(t: str) -> str:
    t = (t or "").strip() or "%(title)s [%(id)s].%(ext)s"
    t = t.replace("\\", "/")
    t = re.sub(r"^[A-Za-z]:", "", t)  # 先去掉磁碟代號再拆路徑段，避免留下開頭的 /
    parts = [p for p in t.split("/") if p not in ("", ".", "..")]
    t = "/".join(parts)
    if "%(ext)s" not in t:
        t += ".%(ext)s"
    return t[:250]


def _parse_ranges(text: str):
    ranges = []
    for chunk in re.split(r"[,\n;]+", text or ""):
        chunk = chunk.strip()
        if not chunk:
            continue
        m = re.match(r"^\s*([\d:.]+)\s*[-~到]\s*([\d:.]+|inf|end)?\s*$", chunk)
        if not m:
            raise ValueError(f"時間範圍格式錯誤：{chunk}（例：1:30-2:45）")
        start = parse_duration(m.group(1))
        end_raw = m.group(2)
        end = float("inf") if end_raw in (None, "inf", "end") else parse_duration(end_raw)
        if start is None or end is None or end <= start:
            raise ValueError(f"時間範圍無效：{chunk}")
        ranges.append((start, end))
    return ranges


def _apply_network_opts(opts: dict, net: dict):
    if net.get("proxy"):
        opts["proxy"] = str(net["proxy"]).strip()
    browser = _pick(net.get("cookies_browser"), BROWSERS)
    if net.get("cookies_file") and COOKIES_FILE.is_file():
        opts["cookiefile"] = str(COOKIES_FILE)  # 匯出的 cookies.txt（Premium / 會員 / 年齡限制）
    elif browser:
        opts["cookiesfrombrowser"] = (browser, None, None, None)
    if net.get("geo_country") and re.fullmatch(r"[A-Za-z]{2}", str(net["geo_country"])):
        opts["geo_bypass_country"] = str(net["geo_country"]).upper()


def build_opts(o: dict, job_dir: Path) -> dict:
    mode = _pick(o.get("mode"), ("av", "video", "audio", "subs", "thumb"), "av")
    v = o.get("video") or {}
    a = o.get("audio") or {}
    s = o.get("subs") or {}
    x = o.get("extras") or {}
    net = o.get("network") or {}

    opts = {**BASE_OPTS, "paths": {"home": str(job_dir), "temp": str(job_dir / ".tmp")},
            "outtmpl": {"default": _safe_template(x.get("template")),
                        "chapter": "%(title)s - %(section_number)03d %(section_title)s [%(id)s].%(ext)s"},
            "noplaylist": not o.get("playlist"),
            "windowsfilenames": True,
            "restrictfilenames": bool(x.get("restrict_filenames")),
            "overwrites": True,
            "retries": _int(x.get("retries"), 10, 0, 50),
            "fragment_retries": _int(x.get("retries"), 10, 0, 50),
            "concurrent_fragment_downloads": _int(x.get("fragments"), 4, 1, 16),
            "keepvideo": bool(x.get("keep_original"))}
    _apply_network_opts(opts, net)
    if x.get("rate_limit"):
        m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([KMG]?)\s*", str(x["rate_limit"]).upper())
        if m:
            opts["ratelimit"] = int(float(m.group(1)) * {"": 1, "K": 1024, "M": 1024**2, "G": 1024**3}[m.group(2)])
    if o.get("playlist") and o.get("playlist_items"):
        items = re.sub(r"[^\d,:\-]", "", str(o["playlist_items"]))
        if items:
            opts["playlist_items"] = items
    if x.get("live_from_start"):
        opts["live_from_start"] = True

    pps: list[dict] = []
    container = _pick(v.get("container"), VIDEO_CONTAINERS)
    manual_v = _safe_id(v.get("format_id") or "")
    manual_a = [_safe_id(i) for i in (a.get("format_ids") or []) if _safe_id(i)]
    langs = [_safe_id(lang) for lang in (a.get("languages") or []) if _safe_id(lang)]

    # ---------- 格式選擇 ----------
    if mode in ("av", "video"):
        sort = []
        h = v.get("max_height")
        if str(h).isdigit():
            sort.append(f"res:{int(h)}")
        codec = _pick(v.get("codec"), ("av01", "vp9", "h264", "h265"))
        if codec:
            sort.append(f"vcodec:{codec}")
        fps = v.get("max_fps")
        if str(fps).isdigit():
            sort.append(f"fps:{int(fps)}")
        hdr = v.get("hdr")
        if hdr == "sdr":
            sort.append("hdr:sdr")
        elif hdr == "hdr":
            sort.append("hdr")
        acodec = _pick(a.get("prefer_codec"), ("opus", "aac", "mp4a"))
        if acodec:
            sort.append(f"acodec:{acodec}")
        if v.get("prefer_size"):
            sort.insert(0, "+size")
        if sort:
            opts["format_sort"] = sort

        drc = "" if a.get("allow_drc") else "[format_id!*=drc]"
        if mode == "video":
            opts["format"] = manual_v or "bv*[acodec=none]/bv*"
        elif manual_v:
            opts["format"] = "+".join([manual_v, *manual_a]) if manual_a else f"{manual_v}+ba{drc}/{manual_v}"
            if len(manual_a) > 1:
                opts["allow_multiple_audio_streams"] = True
        elif manual_a:
            opts["format"] = "+".join(["bv*", *manual_a])
            opts["allow_multiple_audio_streams"] = len(manual_a) > 1
        elif langs:
            auds = "+".join(f"ba[language^={lang}]{drc}" for lang in langs)
            opts["format"] = f"bv*+{auds}/bv*+ba{drc}/b"
            opts["allow_multiple_audio_streams"] = len(langs) > 1
        else:
            opts["format"] = f"bv*+ba{drc}/bv*+ba/b"

        # YouTube Premium：優先選 Premium 高位元率影片串流（需 Premium 帳號 cookies）
        if v.get("premium") and not manual_v and mode in ("av", "video"):
            prem = "bv*[format_note*=Premium]"
            first = opts["format"].split("/")[0]
            opts["format"] = f"{first.replace('bv*', prem, 1)}/{opts['format']}"

        if container:
            # 多音軌時 mp4/mkv 都能裝；webm 也可（opus）。merge 後再 remux/轉檔確保容器一致
            opts["merge_output_format"] = container
            if v.get("recode"):
                pps.append({"key": "FFmpegVideoConvertor", "preferedformat": container})
            else:
                pps.append({"key": "FFmpegVideoRemuxer", "preferedformat": container})

    elif mode == "audio":
        drc = "" if a.get("allow_drc") else "[format_id!*=drc]"
        if manual_a:
            opts["format"] = ",".join(manual_a)  # 各自獨立輸出
        elif langs:
            opts["format"] = ",".join(f"ba[language^={lang}]{drc}/ba[language^={lang}]" for lang in langs)
        else:
            opts["format"] = f"ba{drc}/ba/b"
        if len(manual_a) > 1 or len(langs) > 1:
            t = opts["outtmpl"]["default"]
            opts["outtmpl"]["default"] = re.sub(r"\.%\(ext\)s$", " [%(format_id)s].%(ext)s", t)
        codec = _pick(a.get("codec"), AUDIO_CODECS + ("best",), "best")
        quality = str(a.get("quality") or "0")
        if not re.fullmatch(r"\d{1,3}[kK]?", quality):
            quality = "0"
        pps.append({"key": "FFmpegExtractAudio", "preferredcodec": codec,
                    "preferredquality": quality, "nopostoverwrites": False})
    else:
        opts["skip_download"] = True

    # ---------- 字幕 ----------
    sub_langs = [_safe_id(lang) for lang in (s.get("languages") or []) if _safe_id(lang)]
    auto_langs = [_safe_id(lang) for lang in (s.get("auto_languages") or []) if _safe_id(lang)]
    want_subs = bool(sub_langs or auto_langs) or (mode == "subs" and s.get("all"))
    if want_subs:
        opts["writesubtitles"] = bool(sub_langs) or bool(s.get("all"))
        opts["writeautomaticsub"] = bool(auto_langs)
        opts["subtitleslangs"] = ["all"] if s.get("all") else list(dict.fromkeys(sub_langs + auto_langs))
        sfmt = _pick(s.get("format"), SUB_FORMATS + ("best",), "best")
        opts["subtitlesformat"] = "best" if sfmt == "best" else f"{sfmt}/vtt/best"
        if sfmt != "best":
            pps.insert(0, {"key": "FFmpegSubtitlesConvertor", "format": sfmt, "when": "before_dl"})
        if s.get("embed") and mode in ("av", "video"):
            pps.append({"key": "FFmpegEmbedSubtitle", "already_have_subtitle": bool(s.get("keep_files"))})

    # ---------- 縮圖 ----------
    want_thumb = mode == "thumb" or (mode in ("av", "video", "audio")
                                     and (x.get("embed_thumbnail") or x.get("write_thumbnail")))
    if want_thumb:
        opts["writethumbnail"] = True
        tfmt = _pick(x.get("thumb_format"), THUMB_FORMATS, "jpg")
        pps.insert(0, {"key": "FFmpegThumbnailsConvertor", "format": tfmt, "when": "before_dl"})

    # ---------- SponsorBlock ----------
    sb_remove = [c for c in (x.get("sponsor_remove") or []) if c in SPONSOR_CATS]
    sb_mark = [c for c in (x.get("sponsor_mark") or []) if c in SPONSOR_CATS]
    if (sb_remove or sb_mark) and mode != "subs" and mode != "thumb":
        pps.insert(0, {"key": "SponsorBlock", "categories": list(dict.fromkeys(sb_remove + sb_mark)),
                       "api": "https://sponsor.ajay.app", "when": "after_filter"})
        pps.insert(1, {"key": "ModifyChapters", "remove_sponsor_segments": sb_remove,
                       "remove_chapters_patterns": [], "remove_ranges": [],
                       "sponsorblock_chapter_title": "[SponsorBlock]: %(category_names)l",
                       "force_keyframes": bool(x.get("force_keyframes"))})

    if mode in ("av", "video", "audio"):
        if x.get("embed_metadata") or x.get("embed_chapters"):
            pps.append({"key": "FFmpegMetadata", "add_chapters": bool(x.get("embed_chapters")),
                        "add_metadata": bool(x.get("embed_metadata")), "add_infojson": "if_exists"})
        # EmbedThumbnail 不支援 webm/avi/flv/wav/aac，這些情況略過避免整個工作失敗
        thumb_ok = not ((mode in ("av", "video") and container in ("webm", "avi", "flv"))
                        or (mode == "audio" and a.get("codec") in ("wav", "aac")))
        if x.get("embed_thumbnail") and thumb_ok:
            pps.append({"key": "EmbedThumbnail", "already_have_thumbnail": bool(x.get("write_thumbnail"))})
        if x.get("split_chapters"):
            pps.append({"key": "FFmpegSplitChapters", "force_keyframes": bool(x.get("force_keyframes"))})
        if x.get("sections"):
            opts["download_ranges"] = download_range_func(None, _parse_ranges(x["sections"]))
            opts["force_keyframes_at_cuts"] = bool(x.get("force_keyframes"))

    opts["writedescription"] = bool(x.get("write_description"))
    opts["writeinfojson"] = bool(x.get("write_infojson"))
    if x.get("write_comments"):
        opts["getcomments"] = True
        opts["writeinfojson"] = True
    opts["postprocessors"] = pps
    # yt-dlp 每次呼叫 FFmpeg 都加 -movflags +faststart：寫完輸出後，再把整個檔案往後挪一次，好把索引搬到檔頭。
    # 合併、寫入中繼資料各要多重寫一整份，索引在檔頭時嵌入封面又得再挪一次；100 GB 的 4K 因此多花一兩個小時。
    # 本機播放不需要 faststart：關掉後每個步驟只寫一次，索引留在檔尾，嵌入封面只改檔尾。
    opts["postprocessor_args"] = {"ffmpeg": ["-movflags", "-faststart"]}
    return opts


# --------------------------------------------------------------------------- #
#  下載工作
# --------------------------------------------------------------------------- #
JOB_META = "job.json"  # 每個工作資料夾內的工作紀錄，引擎重啟後用來恢復佇列與續傳
ACTIVE = ("queued", "downloading", "processing")
ST_FALLBACK = {"done": "完成", "error": "失敗", "cancelled": "已取消"}
AUTO_RESUME = 3  # 下載途中斷線時自動續傳的次數（每次都會重新取得串流網址）
RESUME_DELAY = 5


class RateMeter:
    """用最近 window 秒實際下載的位元組數算速率。

    yt-dlp 回報的是瞬間速率；YouTube 分段（chunk）傳送，每段開頭結尾會從幾 MB/s 跳到幾百 MB/s，
    剩餘時間跟著亂跳。改用滑動視窗平均，數字才穩定可信。
    """

    def __init__(self, window: float = 10.0, clock=time.monotonic):
        self.window, self.clock = window, clock
        self.samples: deque[tuple[float, int]] = deque()
        self.key = None
        self.speed = self.eta = None

    def update(self, key, done: int, total: int | None):
        now = self.clock()
        s = self.samples
        # 換到下一個檔案（影片→音軌）、位元組數倒退，或停頓超過一個視窗（斷線續傳）→ 重新計算
        if key != self.key or (s and (done < s[-1][1] or now - s[-1][0] > self.window)):
            s.clear()
            self.key = key
            self.speed = self.eta = None
        s.append((now, done))
        while len(s) > 2 and now - s[1][0] >= self.window:
            s.popleft()
        span = now - s[0][0]
        if span >= 1.0:
            self.speed = (done - s[0][1]) / span
            # total 可能只是估計值（total_bytes_estimate），已下載超過估計時不顯示負數
            self.eta = int((total - done) / self.speed) if total and total > done and self.speed > 0 else None


class Job:
    def __init__(self, url: str, options: dict, title: str | None,
                 job_id: str | None = None, job_dir: Path | None = None):
        self.id = job_id or uuid.uuid4().hex[:12]
        self.url = url
        self.options = options
        self.title = title or url
        self.dir = job_dir or get_download_dir() / self.id
        self.disk_error = None
        self._disk_checked = 0.0
        self.status = "queued"  # queued / downloading / processing / done / error / cancelled
        self.progress = 0.0
        self.speed = None
        self.eta = None
        self.downloaded = 0
        self.total = None
        self.stage = "排隊中"
        self.item = None  # 播放清單第幾部
        self.error = None
        self.log: deque[str] = deque(maxlen=200)
        self.cancel_flag = threading.Event()
        self.rate = RateMeter()
        self.pp_out: Path | None = None  # 目前後處理步驟正在寫出的暫存檔
        self.pp_total = 0  # 預計寫出的大小（輸入檔總和）
        self.pp_started = 0.0
        self.created = time.time()
        self.finished = None

    def files(self):
        if not self.dir.exists():
            return []
        out = []
        for p in sorted(self.dir.rglob("*")):
            if not p.is_file() or ".tmp" in p.relative_to(self.dir).parts:
                continue
            if p.name.endswith(TEMP_SUFFIXES) or p.name in (JOB_META, JOB_META + ".tmp"):
                continue
            out.append({"name": p.relative_to(self.dir).as_posix(), "size": p.stat().st_size})
        return out

    def partial_bytes(self) -> int:
        """可接著用的暫存資料大小：下載到一半的 .part，以及已下載完、還沒合併的串流（<檔名>.f<格式>.<副檔名>）。
        縮圖、字幕不算；合併到一半的 <檔名>.temp.<副檔名> 也不算，重跑時 FFmpeg 會整個重寫。"""
        tmp = self.dir / ".tmp"
        if not tmp.exists():
            return 0
        total = 0
        for p in tmp.rglob("*"):
            try:
                if p.is_file() and (".part" in p.name or STREAM_RE.search(p.name)):
                    total += p.stat().st_size
            except OSError:
                pass
        return total

    def to_dict(self, with_log=False):
        d = {k: getattr(self, k) for k in ("id", "url", "title", "status", "progress", "speed", "eta",
                                           "downloaded", "total", "stage", "item", "error", "created", "finished")}
        d["mode"] = self.options.get("mode")
        if self.status in ("done", "error", "cancelled"):
            d["files"] = self.files()
        if self.status == "error":
            d["partial"] = self.partial_bytes()
        if with_log:
            d["log"] = list(self.log)
        return d

    def save(self):
        """寫入 job.json（原子寫入），引擎被關掉後重開仍能接續。"""
        data = {k: getattr(self, k) for k in ("id", "url", "options", "title", "status", "stage",
                                              "error", "progress", "created", "finished")}
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            tmp = self.dir / (JOB_META + ".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self.dir / JOB_META)
        except OSError:
            pass

    @classmethod
    def load(cls, meta: Path) -> Job:
        d = json.loads(meta.read_text(encoding="utf-8"))
        job = cls(d["url"], d.get("options") or {}, d.get("title"), job_id=meta.parent.name, job_dir=meta.parent)
        job.created = d.get("created") or meta.stat().st_mtime
        job.finished = d.get("finished")
        job.progress = d.get("progress") or 0.0
        if d.get("status") in ACTIVE:
            # 上次引擎在下載途中被關閉（關掉視窗、重開機、當機）
            part = job.partial_bytes()
            job.status, job.stage = "error", "已中斷"
            job.error = ("下載引擎在下載途中被關閉，工作已中斷。按「繼續下載」會從中斷處接著下載"
                         + (f"（已下載 {_gb(part)}）。" if part else "。"))
            job.finished = job.finished or time.time()
        else:
            job.status = d.get("status") or "error"
            job.stage = d.get("stage") or ST_FALLBACK.get(job.status, "")
            job.error = d.get("error")
        return job


JOBS: dict[str, Job] = {}
JOBS_LOCK = threading.Lock()
MAX_PARALLEL = threading.Semaphore(int(os.environ.get("YTDL_PARALLEL", "3")))


def load_jobs():
    """引擎啟動時從下載資料夾恢復之前的工作（含被中斷、可續傳的）。"""
    roots = {get_download_dir().resolve(), DEFAULT_DOWNLOAD_DIR.resolve()}
    for root in roots:
        for meta in root.glob(f"*/{JOB_META}"):
            try:
                job = Job.load(meta)
            except (OSError, ValueError, KeyError, TypeError):
                continue
            with JOBS_LOCK:
                JOBS.setdefault(job.id, job)
            if job.stage == "已中斷":
                job.save()


class JobLogger:
    def __init__(self, job: Job):
        self.job = job

    def debug(self, msg):
        if not msg.startswith("[debug]"):
            self.info(msg)

    def info(self, msg):
        self.job.log.append(msg)
        m = re.match(r"\[download\] Downloading item (\d+) of (\d+)", msg)
        if m:
            self.job.item = f"{m.group(1)}/{m.group(2)}"

    def warning(self, msg):
        self.job.log.append(f"⚠ {msg}")

    def error(self, msg):
        self.job.log.append(f"✖ {msg}")


PP_NAMES = {
    "Merger": "合併影音軌", "FFmpegMerger": "合併影音軌", "FFmpegExtractAudio": "轉換音訊",
    "FFmpegVideoRemuxer": "重新封裝容器", "FFmpegVideoConvertor": "重新編碼影片",
    "FFmpegEmbedSubtitle": "嵌入字幕", "FFmpegSubtitlesConvertor": "轉換字幕",
    "FFmpegMetadata": "寫入中繼資料", "EmbedThumbnail": "嵌入封面", "FFmpegThumbnailsConvertor": "轉換縮圖",
    "SponsorBlock": "查詢 SponsorBlock", "ModifyChapters": "移除片段", "FFmpegSplitChapters": "依章節切割",
    "MoveFiles": "整理檔案", "FFmpegFixupM3u8": "修正串流", "FFmpegFixupM4a": "修正 M4A",
}


def _pp_label(name: str | None) -> str:
    """yt-dlp 回報的後處理名稱有時沒有 FFmpeg 前綴（例如 VideoRemuxer），兩種都查。"""
    if not name:
        return "後處理"
    return PP_NAMES.get(name) or PP_NAMES.get(f"FFmpeg{name}") or name


def _file_size(path) -> int:
    try:
        return os.path.getsize(path)
    except (OSError, TypeError):
        return 0


def _pp_start(job: Job, info: dict):
    """記下這個後處理步驟會寫出的暫存檔（yt-dlp 一律寫到 <檔名>.temp.<副檔名>）與預計大小。"""
    path = info.get("filepath")
    job.pp_out = Path(prepend_extension(path, "temp")) if path else None
    job.pp_total = sum(_file_size(f) for f in (info.get("__files_to_merge") or [path]))
    job.pp_started = time.time()


def _pp_progress(job: Job):
    """FFmpeg 合併 / 寫入中繼資料時不回報進度；以正在寫出的暫存檔大小估算，避免看起來像卡住。"""
    out, total = job.pp_out, job.pp_total
    if job.status != "processing" or not out or not total:
        return
    try:
        st = out.stat()
    except OSError:
        return
    if st.st_mtime < job.pp_started - 2:  # 上次中斷殘留的舊暫存檔，FFmpeg 還沒開始覆寫
        return
    done = st.st_size
    job.downloaded, job.total = done, total
    job.progress = round(min(100.0, done * 100 / total), 1)
    job.rate.update(("pp", job.stage, out.name), done, total)
    job.speed, job.eta = job.rate.speed, job.rate.eta


def run_job(job: Job):
    with MAX_PARALLEL:
        if job.cancel_flag.is_set():
            job.status, job.stage = "cancelled", "已取消"
            return
        job.status, job.stage = "downloading", "準備中"
        try:
            opts = build_opts(job.options, job.dir)
        except Exception as e:  # noqa: BLE001
            job.status, job.error, job.stage = "error", str(e), "設定錯誤"
            job.finished = time.time()
            return

        def check_disk(total, done):
            """空間不夠放下這個檔案、或剩餘空間低於保留值時立即停止，避免把磁碟塞爆。"""
            now = time.time()
            if now - job._disk_checked < 3:
                return
            job._disk_checked = now
            free = disk_info(job.dir)["free"]
            if free is None:
                return
            need = (total - done) if total else 0
            if free - need < MIN_FREE_BYTES:
                job.disk_error = (
                    f"磁碟空間不足：{job.dir.anchor or job.dir} 只剩 {_gb(free)}"
                    + (f"，這個檔案還需要約 {_gb(need)}" if need else "")
                    + f"（保留 {_gb(MIN_FREE_BYTES)} 給系統）。已停止下載，已完成的檔案會保留。"
                    "請改到空間較大的磁碟（下載佇列上方「儲存位置」），或降低畫質 / 減少清單項目。")
                raise DiskFull(job.disk_error)

        def hook(d):
            if job.cancel_flag.is_set():
                raise Cancelled()
            st = d.get("status")
            if st == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate")
                done = d.get("downloaded_bytes") or 0
                check_disk(total, done)
                job.status = "downloading"
                info = d.get("info_dict") or {}
                fid = info.get("format_id")
                job.stage = f"下載中 {fid}" if fid else "下載中"
                job.downloaded, job.total = done, total
                if total:
                    job.progress = round(min(100.0, done * 100 / total), 1)
                elif d.get("fragment_count"):
                    job.progress = round((d.get("fragment_index") or 0) * 100 / d["fragment_count"], 1)
                job.rate.update(d.get("filename"), done, total)
                job.speed, job.eta = job.rate.speed, job.rate.eta
            elif st == "finished":
                job.progress = 100.0
                job.stage = "下載完成，處理中"
                job.speed = job.eta = None

        def pp_hook(d):
            if job.cancel_flag.is_set():
                raise Cancelled()
            if d.get("status") == "started":
                _pp_start(job, d.get("info_dict") or {})
                job.progress, job.downloaded, job.total = 0.0, 0, None  # 不沿用下載階段的 100%
                job.speed = job.eta = None
                job.stage = _pp_label(d.get("postprocessor"))
                job.status = "processing"
            elif d.get("status") == "finished":
                job.pp_out = None

        opts["logger"] = JobLogger(job)
        opts["progress_hooks"] = [hook]
        opts["postprocessor_hooks"] = [pp_hook]
        job.dir.mkdir(parents=True, exist_ok=True)
        job.save()
        watching = threading.Event()

        def watch_pp():
            while not watching.wait(1):
                _pp_progress(job)

        threading.Thread(target=watch_pp, daemon=True).start()
        try:
            free = disk_info(job.dir)["free"]
            if free is not None and free < MIN_FREE_BYTES:
                job.disk_error = (f"磁碟空間不足：{job.dir.anchor or job.dir} 只剩 {_gb(free)}，未開始下載。"
                                  "請清出空間或更換儲存位置。")
                raise DiskFull(job.disk_error)
            attempt = 0
            while True:
                before = job.partial_bytes()
                try:
                    with yt_dlp.YoutubeDL(opts) as ydl:
                        code = ydl.download([job.url])
                    break
                except Exception as e:
                    # 大檔案下載數小時，常遇到網路中斷或串流網址過期（HTTP 403）。
                    # 這一輪確實有下載到資料才重新解析網址、從中斷處續傳；沒進度的錯誤（格式不存在等）直接回報。
                    msg = _clean_err(e)
                    if (job.cancel_flag.is_set() or job.disk_error or _is_disk_err(msg)
                            or attempt >= AUTO_RESUME or job.partial_bytes() <= before):
                        raise
                    attempt += 1
                    job.log.append(f"⟳ 下載中斷：{msg}")
                    job.log.append(f"⟳ {RESUME_DELAY} 秒後自動續傳（第 {attempt}/{AUTO_RESUME} 次）")
                    job.status, job.stage, job.speed, job.eta = "downloading", f"重新連線中（{attempt}/{AUTO_RESUME}）", None, None
                    if job.cancel_flag.wait(RESUME_DELAY):
                        raise Cancelled() from None
            if job.cancel_flag.is_set():
                raise Cancelled()
            if code and not job.files():
                raise RuntimeError("下載失敗，請查看紀錄")
            job.status, job.stage, job.progress = "done", "完成", 100.0
        except Cancelled:
            job.status, job.stage = "cancelled", "已取消"
        except BaseException as e:  # noqa: BLE001 — yt-dlp 會把 hook 例外包成 DownloadError
            msg = _clean_err(e)
            if job.cancel_flag.is_set():
                job.status, job.stage = "cancelled", "已取消"
            elif job.disk_error or _is_disk_err(msg):
                kept = len(job.files())
                job.status, job.stage = "error", "磁碟空間不足"
                job.error = job.disk_error or (
                    f"磁碟空間不足（{job.dir.anchor or job.dir} 只剩 {_gb(disk_info(job.dir)['free'])}），下載已停止。"
                    "請改到空間較大的磁碟（下載佇列上方「儲存位置」），或降低畫質 / 減少清單項目。")
                if kept:
                    job.error += f"\n已保留完成的 {kept} 個檔案。"
            elif job.files():
                # 主檔已下載，只有後製步驟失敗 → 視為完成並附上警告
                job.status, job.stage, job.progress = "done", "完成（有警告）", 100.0
                job.error = "部分步驟失敗：" + _clean_err(e)
            else:
                job.status, job.error, job.stage = "error", _clean_err(e), "失敗"
        finally:
            watching.set()
            job.pp_out = None
            # 失敗時保留 .tmp 裡的暫存檔，才能按「繼續下載」從中斷處接著下載
            if job.status != "error":
                shutil.rmtree(job.dir / ".tmp", ignore_errors=True)
            job.speed = job.eta = None
            job.finished = time.time()
            job.save()


def _is_disk_err(msg: str) -> bool:
    return "Errno 28" in msg or "No space left" in msg


def _clean_err(e: BaseException) -> str:
    msg = re.sub(r"\x1b\[[0-9;]*m", "", str(e))
    return re.sub(r"^ERROR:\s*", "", msg).strip() or e.__class__.__name__


@app.post("/api/download")
def api_download():
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    if not re.match(r"^https?://", url):
        return jsonify(error="網址無效"), 400
    options = data.get("options") or {}
    try:
        build_opts(options, DEFAULT_DOWNLOAD_DIR / "_validate")  # 先驗證，錯誤立刻回報
    except Exception as e:  # noqa: BLE001
        return jsonify(error=str(e)), 400
    job = Job(url, options, data.get("title"))
    with JOBS_LOCK:
        JOBS[job.id] = job
    job.save()
    threading.Thread(target=run_job, args=(job,), daemon=True).start()
    return jsonify(job.to_dict())


def _busy() -> bool:
    with JOBS_LOCK:
        jobs = list(JOBS.values())
    return any(j.status in ACTIVE for j in jobs)


def _get_job(job_id: str) -> Job:
    job = JOBS.get(job_id)
    if not job:
        abort(404)
    return job


@app.get("/api/jobs")
def api_jobs():
    with JOBS_LOCK:
        jobs = sorted(JOBS.values(), key=lambda j: j.created, reverse=True)
    return jsonify([j.to_dict() for j in jobs])


@app.get("/api/jobs/<job_id>")
def api_job(job_id):
    return jsonify(_get_job(job_id).to_dict(with_log=True))


@app.post("/api/jobs/<job_id>/cancel")
def api_cancel(job_id):
    job = _get_job(job_id)
    job.cancel_flag.set()
    if job.status == "queued":
        job.status, job.stage = "cancelled", "已取消"
    return jsonify(job.to_dict())


@app.post("/api/jobs/<job_id>/resume")
def api_resume(job_id):
    """失敗或中斷的工作用同一個資料夾重跑；yt-dlp 會偵測 .part 從中斷處續傳。"""
    job = _get_job(job_id)
    with JOBS_LOCK:
        if job.status != "error":
            return jsonify(error="只有失敗或中斷的工作可以繼續"), 409
        job.status, job.stage, job.error, job.disk_error = "queued", "排隊中", None, None
        job.speed = job.eta = job.finished = None
        job.cancel_flag.clear()
        # 沒有可續傳資料也沒有完成檔時，改用目前的儲存位置（例如磁碟滿了、換到別顆磁碟後重試）
        if not job.partial_bytes() and not job.files():
            new_dir = get_download_dir() / job.id
            if new_dir != job.dir:
                shutil.rmtree(job.dir, ignore_errors=True)
                job.dir = new_dir
    job.log.append("⟳ 繼續下載")
    job.save()
    threading.Thread(target=run_job, args=(job,), daemon=True).start()
    return jsonify(job.to_dict())


@app.delete("/api/jobs/<job_id>")
def api_delete(job_id):
    job = _get_job(job_id)
    if job.status in ACTIVE:
        return jsonify(error="工作進行中，請先取消"), 409
    shutil.rmtree(job.dir, ignore_errors=True)
    with JOBS_LOCK:
        JOBS.pop(job_id, None)
    return jsonify(ok=True)


@app.get("/api/jobs/<job_id>/file/<path:name>")
def api_file(job_id, name):
    job = _get_job(job_id)
    target = (job.dir / name).resolve()
    if job.dir.resolve() not in target.parents or not target.is_file():
        abort(404)
    return send_file(target, as_attachment=request.args.get("inline") != "1", download_name=target.name)


def _explorer_select_cmd(path: Path) -> str:
    return f'explorer /select,"{path}"'  # Windows 檔名不能含 "，不用跳脫


def reveal_in_file_manager(path: Path):
    """在檔案總管 / Finder 中顯示檔案（選取它）；資料夾則直接打開。"""
    if os.name == "nt":
        if path.is_file():
            # explorer 只認 /select,"路徑" 這種寫法；用 list 傳參數會把整段加引號，路徑有空白時就選不到檔案
            subprocess.Popen(_explorer_select_cmd(path))
        else:
            os.startfile(path)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(path)] if path.is_file() else ["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path if path.is_dir() else path.parent)])


@app.post("/api/jobs/<job_id>/reveal")
def api_reveal(job_id):
    """「開啟資料夾」：引擎和使用者在同一台電腦，直接叫出檔案總管，不必再下載一份。"""
    job = _get_job(job_id)
    name = str((request.get_json(silent=True) or {}).get("name") or "")
    base = job.dir.resolve()
    target = (base / name).resolve() if name else base
    if not target.exists() or (target != base and base not in target.parents):
        abort(404)
    reveal_in_file_manager(target)
    return jsonify(ok=True)


@app.get("/api/jobs/<job_id>/zip")
def api_zip(job_id):
    job = _get_job(job_id)
    files = job.files()
    if not files:
        abort(404)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
        for f in files:
            z.write(job.dir / f["name"], f["name"])
    buf.seek(0)
    safe = re.sub(r'[\\/:*?"<>|]+', "_", job.title)[:80] or job.id
    return send_file(buf, as_attachment=True, download_name=f"{safe}.zip", mimetype="application/zip")


@app.get("/api/meta")
def api_meta():
    return jsonify(version=yt_dlp.version.__version__, latest=latest_version(), channel=CHANNEL,
                   frozen=FROZEN, update_ready=UPDATE_STATE["ready"],
                   ffmpeg=bool(shutil.which("ffmpeg")), cookies_file=COOKIES_FILE.is_file(),
                   disk=disk_info(get_download_dir()), min_free=MIN_FREE_BYTES,
                   just_updated=os.environ.get("YTDL_JUST_UPDATED") == "1",
                   update_running=UPDATE_STATE["running"], update_message=UPDATE_STATE["message"])


def list_drives() -> list[dict]:
    """可用磁碟與剩餘空間（Windows 列磁碟代號；其他系統列家目錄所在磁碟）。"""
    if os.name == "nt":
        roots = [Path(f"{c}:\\") for c in "CDEFGHIJKLMNOPQRSTUVWXYZ" if os.path.exists(f"{c}:\\")]
    else:
        roots = [Path.home()]
    return [d for d in (disk_info(r) for r in roots) if d["free"] is not None]


@app.get("/api/settings")
def api_settings():
    d = get_download_dir()
    return jsonify(download_dir=str(d), default_dir=str(DEFAULT_DOWNLOAD_DIR),
                   env_locked=bool(os.environ.get("YTDL_DOWNLOAD_DIR")),
                   min_free=MIN_FREE_BYTES, disk=disk_info(d),
                   # 列磁碟可能碰到離線的網路磁碟而變慢，只在明確要求時才列
                   drives=list_drives() if request.args.get("drives") == "1" else None)


@app.post("/api/settings")
def api_settings_save():
    if os.environ.get("YTDL_DOWNLOAD_DIR"):
        return jsonify(error="儲存位置由環境變數 YTDL_DOWNLOAD_DIR 指定，無法在網頁修改"), 409
    raw = str((request.get_json(silent=True) or {}).get("download_dir") or "").strip().strip('"')
    if not raw:
        target = DEFAULT_DOWNLOAD_DIR
    else:
        target = Path(raw).expanduser()
        if not target.is_absolute():
            return jsonify(error="請輸入完整路徑，例如 D:\\Videos\\yt"), 400
    try:
        target.mkdir(parents=True, exist_ok=True)
        probe = target / f".ytdl-write-test-{uuid.uuid4().hex[:6]}"
        probe.write_bytes(b"ok")
        probe.unlink()
    except OSError as e:
        return jsonify(error=f"無法寫入這個資料夾：{e.strerror or e}"), 400
    settings = _load_settings()
    settings["download_dir"] = "" if target == DEFAULT_DOWNLOAD_DIR else str(target.resolve())
    SETTINGS_FILE.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
    return api_settings()


@app.post("/api/update")
def api_update():
    """手動更新 yt-dlp；沒有進行中的工作時自動重啟套用。打包版若已在背景下載好，直接重新啟動。"""
    if UPDATE_STATE["running"]:
        return jsonify(error="更新進行中"), 409
    if _busy():
        return jsonify(error="有下載工作進行中，請完成後再更新"), 409

    def work():
        UPDATE_STATE.update(running=True, message="更新中…")
        ok, out = (True, "") if UPDATE_STATE["ready"] else upgrade()
        if ok and FROZEN and not UPDATE_STATE["ready"]:  # PyPI 上沒有更新的版本
            UPDATE_STATE.update(running=False, message=out)
            return
        UPDATE_STATE.update(running=False, message="更新完成，重新啟動中" if ok else f"更新失敗：{out}")
        if ok:
            time.sleep(1.0)
            restart_process()

    threading.Thread(target=work, daemon=True).start()
    return jsonify(ok=True)


@app.get("/api/cookies")
def api_cookies_status():
    return jsonify(exists=COOKIES_FILE.is_file(),
                   size=COOKIES_FILE.stat().st_size if COOKIES_FILE.is_file() else 0)


@app.post("/api/cookies")
def api_cookies_upload():
    f = request.files.get("file")
    text = f.read().decode("utf-8", "replace") if f else (request.get_json(silent=True) or {}).get("text", "")
    if "\t" not in text or not re.search(r"(?m)^(#HttpOnly_)?\.?[\w.-]+\t(TRUE|FALSE)\t", text):
        return jsonify(error="不是 Netscape 格式的 cookies.txt"), 400
    if not text.startswith("# Netscape HTTP Cookie File") and not text.startswith("# HTTP Cookie File"):
        text = "# Netscape HTTP Cookie File\n" + text
    COOKIES_FILE.write_text(text, encoding="utf-8")
    return jsonify(exists=True, size=COOKIES_FILE.stat().st_size)


@app.delete("/api/cookies")
def api_cookies_delete():
    COOKIES_FILE.unlink(missing_ok=True)
    return jsonify(exists=False)


AUTH_TEST_URL = "https://www.youtube.com/watch?v=jNQXAC9IVRw"


class _CaptureLogger:
    def __init__(self):
        self.lines: list[str] = []

    def debug(self, msg):
        self.lines.append(msg)

    info = warning = error = debug


def _auth_hint(err: str, browser: str | None) -> str:
    low = err.lower()
    if browser in ("chrome", "edge", "brave", "opera", "vivaldi", "chromium") and (
            "dpapi" in low or "decrypt" in low or "could not copy" in low or "permission" in low):
        return (f"無法讀取 {browser.title()} 的 Cookie：Windows 上新版 Chromium 系瀏覽器會加密 / 鎖定 Cookie。"
                "請完全關閉該瀏覽器再試，或改用 Firefox，或改用 cookies.txt 方式。")
    if "could not find" in low and "cookies database" in low:
        return f"找不到 {browser} 的 Cookie 資料庫，請確認已安裝並登入過 YouTube。"
    return err


@app.post("/api/auth/test")
def api_auth_test():
    """測試目前的 Cookie 設定：是否登入 YouTube、是否偵測到 Premium。"""
    net = (request.get_json(silent=True) or {}).get("network") or {}
    opts = {**BASE_OPTS, "skip_download": True, "verbose": True, "noplaylist": True}
    _apply_network_opts(opts, net)
    if "cookiefile" not in opts and "cookiesfrombrowser" not in opts:
        return jsonify(error="尚未設定 Cookie 來源"), 400
    log = _CaptureLogger()
    opts["logger"] = log
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ie = ydl.get_info_extractor("Youtube")
            logged_in = bool(ie.is_authenticated)
            premium = False
            if logged_in:
                ydl.extract_info(AUTH_TEST_URL, download=False, process=False)
                premium = any("Detected YouTube Premium subscription" in m for m in log.lines)
    except Exception as e:  # noqa: BLE001
        return jsonify(error=_auth_hint(_clean_err(e), net.get("cookies_browser"))), 400
    expired = any("cookies are no longer valid" in m.lower() for m in log.lines)
    return jsonify(logged_in=logged_in and not expired, premium=premium, expired=expired)


def startup_update():
    """啟動時檢查 PyPI，有新版就 pip 升級並重啟（只做一次，避免迴圈）。打包版改用 auto_update_app。"""
    if FROZEN or os.environ.get("YTDL_AUTO_UPDATE", "1") == "0" or os.environ.get("YTDL_JUST_UPDATED") == "1":
        return
    current = yt_dlp.version.__version__
    latest = latest_version(force=True)
    if latest and _vtuple(latest) > _vtuple(current):
        print(f"發現 yt-dlp 新版 {latest}（目前 {current}），自動更新中…", flush=True)
        ok, out = pip_upgrade()
        if ok:
            print("更新完成，重新啟動…", flush=True)
            restart_process()
        print(f"更新失敗，繼續使用目前版本：{out}", flush=True)


def periodic_update_check():
    """每 6 小時檢查一次；有新版且沒有進行中的工作就自動更新重啟。"""
    while True:
        time.sleep(6 * 3600)
        if FROZEN or os.environ.get("YTDL_AUTO_UPDATE", "1") == "0":
            continue
        latest = latest_version(force=True)
        if latest and _vtuple(latest) > _vtuple(yt_dlp.version.__version__) and not _busy():
            ok, _ = pip_upgrade()
            if ok:
                restart_process()


def auto_update_app():
    """打包版：啟動時與每 6 小時在背景下載新版 yt-dlp。
    不自動重開視窗打斷使用者；下次開啟 App，或按介面上的「重新啟動以套用」時生效。"""
    while True:
        if os.environ.get("YTDL_AUTO_UPDATE", "1") != "0" and not UPDATE_STATE["running"]:
            _, msg = app_upgrade()
            print(f"yt-dlp 自動更新：{msg}", flush=True)
        time.sleep(6 * 3600)


def start_background_updates():
    if FROZEN:
        threading.Thread(target=auto_update_app, daemon=True).start()
    else:
        threading.Thread(target=periodic_update_check, daemon=True).start()


@app.get("/")
def index():
    return send_from_directory(BUNDLE, "index.html")


def _port_in_use(host: str, port: int) -> bool:
    import socket
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1" if host in ("0.0.0.0", "") else host, port)) == 0


def main():
    url = f"http://127.0.0.1:{PORT}"
    for stream in (sys.stdout, sys.stderr):  # 主控台編碼不支援的字元（例如影片標題的 emoji）不要讓程式當掉
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    startup_update()
    load_jobs()
    start_background_updates()
    print(f"YT 下載器： {url}   （yt-dlp {yt_dlp.version.__version__}{'，自動更新版' if YTDLP_OVERLAY else ''}）",
          flush=True)
    app.run(host=HOST, port=PORT, threaded=True, debug=False)


if __name__ == "__main__":
    main()
