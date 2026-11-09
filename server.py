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

from flask import Flask, abort, has_request_context, jsonify, request, send_file, send_from_directory

import engine_messages as em
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
from yt_dlp.utils import DownloadCancelled, download_range_func, parse_duration, prepend_extension

try:  # 「連同檔案刪除」改成移到資源回收筒（macOS 是垃圾桶）
    from send2trash import send2trash
except ImportError:  # pragma: no cover — requirements 有列；沒裝時刪除 API 會回報錯誤，不會永久刪檔
    send2trash = None

SETTINGS_FILE = ROOT / "settings.json"
# 剩餘空間低於此值就停止下載，保護系統碟（預設 2 GB）
MIN_FREE_BYTES = int(float(os.environ.get("YTDL_MIN_FREE_GB", "2")) * 1024**3)


def _read_json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _load_settings() -> dict:
    """settings.json 壞掉時改用上一次成功寫入的備份，不要悄悄換回預設的下載資料夾。"""
    data = _read_json(SETTINGS_FILE)
    if data is None and SETTINGS_FILE.exists():
        data = _read_json(SETTINGS_FILE.with_name(SETTINGS_FILE.name + ".bak"))
    return data or {}


def _save_settings(settings: dict):
    """原子寫入：先寫暫存檔再 os.replace，寫到一半當機也不會留下空檔；另存一份 .bak 備用。"""
    text = json.dumps(settings, ensure_ascii=False, indent=2)
    for path in (SETTINGS_FILE, SETTINGS_FILE.with_name(SETTINGS_FILE.name + ".bak")):
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)


def get_download_dir() -> Path:
    """下載位置：環境變數 > settings.json > 專案內 downloads/。

    資料夾建立失敗（例如外接硬碟拔掉、磁碟代號不存在）時不丟例外，照樣回傳路徑；
    要不要擋下動作由 download_dir_problem() 決定，App 才打得開、也能提示使用者更換位置。
    """
    raw = os.environ.get("YTDL_DOWNLOAD_DIR") or _load_settings().get("download_dir")
    d = Path(raw).expanduser() if raw else DEFAULT_DOWNLOAD_DIR
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return d


def download_dir_problem(d: Path | None = None) -> str | None:
    """下載資料夾目前無法使用時回傳原因（作業系統的原文），可以用時回傳 None。"""
    d = d or get_download_dir()
    try:
        d.mkdir(parents=True, exist_ok=True)
        if not d.is_dir():
            raise NotADirectoryError(str(d))
    except OSError as e:
        return f"{d}: {e.strerror or e.__class__.__name__}"
    return None


def download_dir_status(d: Path, lang: str | None = None) -> dict:
    """給 /api/meta、/api/settings：download_dir_error（依語言的說明或 None）與原因原文。只檢查資料夾一次。"""
    problem = download_dir_problem(d)
    text = render_error("download_dir_unavailable", error_params(problem, location=d),
                        lang or req_lang())["error"] if problem else None
    return {"download_dir_error": text, "download_dir_error_detail": problem}


def disk_info(path: Path) -> dict:
    try:
        u = shutil.disk_usage(path)
        return {"path": str(path), "free": u.free, "total": u.total}
    except OSError:
        return {"path": str(path), "free": None, "total": None}


# 不在匯入時建立下載資料夾：磁碟不存在時 import server 會失敗，App 就完全打不開（R1）
COOKIES_FILE = ROOT / "cookies.txt"
HOST = os.environ.get("YTDL_HOST", "127.0.0.1")
PORT = int(os.environ.get("YTDL_PORT", "8765"))
CHANNEL = "nightly" if os.environ.get("YTDL_CHANNEL", "").lower() == "nightly" else "stable"
ALLOWED_ORIGINS = {o.strip().rstrip("/") for o in os.environ.get(
    "YTDL_ALLOWED_ORIGINS", "https://archer8685.github.io").split(",") if o.strip()}

app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024  # cookies.txt 上傳上限


def _server_bind_without_fqdn(self):
    """http.server 的 server_bind 會用 socket.getfqdn() 反查本機的完整主機名稱，只為了填 server_name。
    macOS 上這個查詢會跳出「允許尋找區域網路上的裝置」的詢問，並一直卡到使用者回答為止，
    引擎就沒辦法開始服務（App 有視窗時才會發生）；公司網路的 DNS 慢時 Windows 也會白等。
    本機引擎用不到主機名稱，直接用綁定的位址。"""
    import socketserver
    socketserver.TCPServer.server_bind(self)
    self.server_name, self.server_port = self.server_address[:2]


import http.server

http.server.HTTPServer.server_bind = _server_bind_without_fqdn


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
        return api_error("unknown", 403, msg="origin_forbidden", action=None)


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
#  錯誤物件與處理階段文字（第 5.5 節）
#  錯誤代碼與一般訊息來自 engine_messages（E2）；含數字的詳細說明、操作限制等引擎自己的訊息放在 ENGINE_TEXT。
#  工作只存「代碼＋參數」，回應時才依請求的 Accept-Language 組成文字（en 開頭用英文，其他與沒帶標頭用中文），
#  所以切換語言後舊工作的訊息也會跟著變。
# --------------------------------------------------------------------------- #
ENGINE_TEXT: dict[str, dict[str, str]] = {
    "origin_forbidden": {"zh": "此來源未被允許",
                         "en": "This website isn't allowed to control the downloader."},
    "not_found": {"zh": "找不到指定的工作或檔案", "en": "The job or file wasn't found."},
    "too_large": {"zh": "上傳的檔案太大", "en": "The uploaded file is too large."},
    "http_error": {"zh": "無法處理這個要求（{http}）", "en": "The request couldn't be handled ({http})."},
    "youtube_incomplete": {"zh": "YouTube 網址不完整，請複製完整的影片網址",
                           "en": "This YouTube link is incomplete. Copy the full video link."},
    "range_format": {"zh": "時間範圍格式錯誤：{chunk}（例：1:30-2:45）",
                     "en": "Invalid time range: {chunk} (example: 1:30-2:45)"},
    "range_invalid": {"zh": "時間範圍無效：{chunk}", "en": "Invalid time range: {chunk}"},
    "options_invalid": {"zh": "下載選項有誤，請檢查進階選項", "en": "Some download options are invalid. Check Advanced options."},
    "pause_not_allowed": {"zh": "只有下載中或排隊中的工作可以暫停",
                          "en": "Only downloading or queued jobs can be paused."},
    "resume_not_allowed": {"zh": "只有失敗、中斷或暫停的工作可以繼續",
                           "en": "Only failed, interrupted or paused jobs can be resumed."},
    "retry_failed_none": {"zh": "這個工作沒有可以重試的失敗項目", "en": "This job has no failed items to retry."},
    "delete_files_param": {"zh": "files 參數只能是 keep 或 trash", "en": "The files parameter must be keep or trash."},
    "job_busy": {"zh": "工作進行中，請先暫停或取消", "en": "This job is still running. Pause or cancel it first."},
    "trash_unavailable": {"zh": "這台電腦無法使用資源回收筒，檔案沒有刪除",
                          "en": "The Recycle Bin isn't available on this computer. No files were deleted."},
    "trash_failed": {"zh": "無法把檔案移到資源回收筒，檔案沒有刪除",
                     "en": "Couldn't move the files to the Recycle Bin. No files were deleted."},
    "parallel_range": {"zh": "同時下載數要介於 {lo} 到 {hi} 之間",
                       "en": "Simultaneous downloads must be between {lo} and {hi}."},
    "dir_env_locked": {"zh": "儲存位置由環境變數 YTDL_DOWNLOAD_DIR 指定，無法在這裡修改",
                       "en": "The download location is set by the YTDL_DOWNLOAD_DIR environment variable "
                             "and can't be changed here."},
    "dir_not_absolute": {"zh": "請輸入完整路徑，例如 D:\\Videos\\yt", "en": "Enter a full path, for example D:\\Videos\\yt"},
    "settings_save_failed": {"zh": "無法儲存設定", "en": "Couldn't save the settings."},
    "update_running": {"zh": "更新進行中", "en": "An update is already running."},
    "update_busy": {"zh": "有下載工作進行中，請完成後再更新", "en": "Downloads are in progress. Update after they finish."},
    "cookie_source_missing": {"zh": "尚未設定 Cookie 來源", "en": "No cookie source is set."},
    "browser_cookies_locked": {
        "zh": "無法讀取 {browser} 的 Cookie：Windows 上新版 Chromium 系瀏覽器會加密／鎖定 Cookie。"
              "請完全關閉該瀏覽器再試，或改用 Firefox，或改用 cookies.txt 方式。",
        "en": "Can't read {browser}'s cookies: recent Chromium-based browsers on Windows encrypt or lock them. "
              "Close the browser completely and try again, or use Firefox or a cookies.txt file instead."},
    "browser_cookies_not_found": {
        "zh": "找不到 {browser} 的 Cookie 資料庫，請確認已安裝並登入過 YouTube。",
        "en": "Couldn't find {browser}'s cookie database. Make sure it's installed and you've signed in to YouTube."},
    "disk_full_download": {
        "zh": "磁碟空間不足：{anchor} 只剩 {free}（保留 {reserve} 給系統）。已停止下載，已完成的檔案會保留。"
              "請到「設定 → 儲存位置」改到空間較大的磁碟，或降低畫質、減少清單項目。",
        "en": "Not enough disk space: only {free} left on {anchor} ({reserve} is kept free for the system). "
              "The download stopped; finished files were kept. Choose a drive with more space in "
              "Settings → Storage location, or pick a lower quality or fewer playlist items."},
    "disk_full_download_need": {
        "zh": "磁碟空間不足：{anchor} 只剩 {free}，這個檔案還需要約 {need}（保留 {reserve} 給系統）。"
              "已停止下載，已完成的檔案會保留。請到「設定 → 儲存位置」改到空間較大的磁碟，或降低畫質、減少清單項目。",
        "en": "Not enough disk space: only {free} left on {anchor}, and this file still needs about {need} "
              "({reserve} is kept free for the system). The download stopped; finished files were kept. "
              "Choose a drive with more space in Settings → Storage location, or pick a lower quality "
              "or fewer playlist items."},
    "disk_full_start": {
        "zh": "磁碟空間不足：{anchor} 只剩 {free}，未開始下載。請清出空間，或到「設定 → 儲存位置」更換。",
        "en": "Not enough disk space: only {free} left on {anchor}, so the download didn't start. "
              "Free up space or change the location in Settings → Storage location."},
    "disk_full_pp": {
        "zh": "磁碟空間不足：「{step}」需要約 {need}，{anchor} 只剩 {free}（保留 {reserve} 給系統）。"
              "已下載的部分會保留，清出空間或到「設定 → 儲存位置」更換後按「繼續下載」。",
        "en": "Not enough disk space: “{step}” needs about {need}, but only {free} is left on {anchor} "
              "({reserve} is kept free for the system). The downloaded data was kept. Free up space or change "
              "the location in Settings → Storage location, then click “Resume”."},
    "disk_full_generic": {
        "zh": "磁碟空間不足（{anchor} 只剩 {free}），下載已停止。請到「設定 → 儲存位置」改到空間較大的磁碟，"
              "或降低畫質、減少清單項目。",
        "en": "Not enough disk space (only {free} left on {anchor}), so the download stopped. Choose a drive "
              "with more space in Settings → Storage location, or pick a lower quality or fewer playlist items."},
    "files_kept": {"zh": "已保留完成的 {n} 個檔案。", "en": "{n} finished file(s) were kept."},
    "interrupted": {
        "zh": "下載引擎在下載途中被關閉，工作已中斷。按「繼續下載」會從中斷處接著下載。",
        "en": "The download engine was closed during the download, so the job was interrupted. "
              "Click “Resume” to continue where it stopped."},
    "interrupted_size": {
        "zh": "下載引擎在下載途中被關閉，工作已中斷。按「繼續下載」會從中斷處接著下載（已下載 {size}）。",
        "en": "The download engine was closed during the download, so the job was interrupted. "
              "Click “Resume” to continue where it stopped ({size} already downloaded)."},
    "playlist_all_failed": {"zh": "清單中的 {n} 部影片都無法下載：{reason}",
                            "en": "None of the {n} videos in the playlist could be downloaded: {reason}"},
    "no_media": {"zh": "下載失敗：沒有產生影片或音訊檔，可以展開「詳細資訊」查看原因",
                 "en": "The download failed: no video or audio file was produced. Open “Details” to see why."},
    "no_subs": {"zh": "下載失敗：沒有產生字幕檔（這部影片可能沒有所選語言的字幕）",
                "en": "The download failed: no subtitle file was produced "
                      "(the video may not have subtitles in the selected languages)."},
    "no_thumb": {"zh": "下載失敗：沒有產生縮圖", "en": "The download failed: no thumbnail was produced."},
    "done_partial": {"zh": "完成 {done}/{total}，{n} 部無法下載",
                     "en": "Done {done}/{total}; {n} couldn't be downloaded"},
    "items_failed": {"zh": "{n} 部無法下載", "en": "{n} couldn't be downloaded"},
    "steps_failed": {"zh": "部分步驟失敗：{reason}", "en": "Some steps failed: {reason}"},
}

STAGE_CODES = em.STAGE_CODES
# 第一階段（e11a991）存在 job.json 的階段代碼 → 現在的代碼
_STAGE_ALIASES = {"error": "failed", "done_warnings": "done_with_warnings", "downloaded": "download_finished",
                  "processing": "postprocessing", "downloading_format": "downloading"}
_ZH_STAGE_TO_CODE = {em.stage_text(c, "zh"): c for c in em.STAGE_CODES if "{" not in em.stage_text(c, "zh")}
_NO_ACTION = "__default__"


def req_lang() -> str:
    """這個請求要用的語言：Accept-Language 以 en 開頭 → "en"；其他或沒帶 → "zh"。

    瀏覽器一定會自動帶 Accept-Language，網頁版（中文介面）卻要維持中文（第 5.3 節第 4 點），
    所以瀏覽器發出的請求（有 Sec-Fetch-* 標頭）一律用中文；桌面 App 的 Qt 網路元件不會送這些標頭。
    """
    if not has_request_context():
        return "zh"
    if request.headers.get("Sec-Fetch-Mode") or request.headers.get("Sec-Fetch-Site"):
        return "zh"
    return em.normalize_lang(request.headers.get("Accept-Language"))


def update_available() -> bool:
    """有比目前更新的 yt-dlp（已下載好或 PyPI 上有）：HTTP 403 的建議動作改成更新 yt-dlp（ERR3）。"""
    if UPDATE_STATE["ready"]:
        return True
    latest = _LATEST["version"]
    return bool(latest) and _vtuple(latest) > _vtuple(yt_dlp.version.__version__)


def engine_text(key: str, lang: str = "zh", **args) -> str:
    """ENGINE_TEXT 的訊息。參數 step（yt-dlp 後處理名稱）、reason_code（錯誤代碼）會換成該語言的文字。"""
    lang = em.normalize_lang(lang)
    if "step" in args:
        args["step"] = em.pp_label(args["step"], lang)
    if "reason_code" in args:
        args["reason"] = em.error_payload(args.pop("reason_code"), lang)["message"]
    entry = ENGINE_TEXT.get(key)
    if entry is None:
        return key
    try:
        return entry[lang].format(**args)
    except (KeyError, IndexError, ValueError):
        return entry[lang]


def render_stage(code: str, params: dict | None, lang: str = "zh") -> str:
    return em.stage_text(code, lang, **(params or {}))


def render_error(code: str, params: dict | None, lang: str = "zh") -> dict:
    """代碼＋參數 → 第 5.5 節的錯誤欄位（依語言）。

    params：detail（原文）、msg（ENGINE_TEXT 的鍵，覆寫一般訊息）、args（msg 的參數）、
    location（儲存位置，只顯示磁碟代號）、kept（已保留的檔案數）、action（覆寫建議動作，可以是 None）。
    """
    p = params or {}
    lang = em.normalize_lang(lang)
    detail = p.get("detail") or ""
    payload = em.error_payload(code, lang, detail, update_available=update_available(), location=p.get("location"))
    if p.get("msg"):
        payload["message"] = engine_text(p["msg"], lang, **(p.get("args") or {}))
    elif code == "live_not_started" and detail:
        fe = em.friendly_error(detail, lang)  # 從原文解析「預計 N 分鐘後」
        if fe["code"] == code:
            payload["message"] = fe["message"]
    if p.get("kept"):
        payload["message"] += ("\n" if lang == "zh" else " ") + engine_text("files_kept", lang, n=p["kept"])
    if "action" in p:
        payload["action"] = p["action"]
    return {"error": payload["message"], "error_code": payload["code"], "error_detail": detail or payload["message"],
            "error_action": payload["action"], "error_faq": payload["faq"]}


def error_params(detail: str | None = None, msg: str | None = None, location=None, kept: int = 0,
                 action=_NO_ACTION, **args) -> dict:
    p: dict = {"detail": detail or ""}
    if msg:
        p["msg"] = msg
    if args:
        p["args"] = args
    if location:
        p["location"] = str(location)
    if kept:
        p["kept"] = kept
    if action != _NO_ACTION:
        p["action"] = action
    return p


def api_error(code: str, status: int, **kw):
    """依代碼回傳錯誤 JSON；kw 同 error_params（msg、detail、location、action、訊息參數）。"""
    return jsonify(render_error(code, error_params(**kw), req_lang())), status


def api_exception(e: BaseException, status: int = 400, location=None):
    """yt-dlp 或其他例外 → 看得懂的錯誤 JSON（原文放在 error_detail）。"""
    fe = em.friendly_error(e, req_lang(), update_available=update_available(), location=location)
    return jsonify(error=fe["message"], error_code=fe["code"], error_detail=fe["detail"],
                   error_action=fe["action"], error_faq=fe["faq"]), status


class OptionError(ValueError):
    """下載選項有誤（例如時間範圍格式）：str() 是中文訊息，key／args 用來組成其他語言的訊息。"""

    def __init__(self, key: str, **args):
        self.key, self.args_ = key, args
        super().__init__(engine_text(key, "zh", **args))


def _engine_log(text: str):
    """寫進 engine.log（打包版的 stdout 已導到紀錄檔；原始碼版印在主控台）。"""
    try:
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {text}", flush=True)
    except (OSError, ValueError, AttributeError):
        pass


@app.errorhandler(Exception)
def _json_errors(e):
    """所有錯誤都回傳 JSON：App 不會再拿到 Flask 的 HTML 500 頁，也不會誤報「連接埠被佔用」。"""
    from werkzeug.exceptions import HTTPException
    if isinstance(e, HTTPException):
        key = {404: "not_found", 413: "too_large"}.get(e.code, "http_error")
        return api_error("unknown", e.code or 500, msg=key, http=e.code, detail=f"{e.code} {e.name}", action=None)
    import traceback
    _engine_log(f"未處理的錯誤 {request.method} {request.path}\n{traceback.format_exc()}")
    return api_error("engine_internal", 500, detail=f"{e.__class__.__name__}: {e}")


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


_LATEST_REFRESH = threading.Lock()


def cached_latest_version() -> str | None:
    """不等網路：回傳目前快取的最新版（可能是 None），過期時在背景重新查詢，下一次 /api/meta 就拿得到。
    公司網路把 PyPI 連線吃掉時，同步查詢會讓設定頁和引擎檢查卡十幾秒（PERF1）。"""
    if time.time() - _LATEST["checked"] >= 6 * 3600 and _LATEST_REFRESH.acquire(blocking=False):
        def work():
            try:
                latest_version()
            finally:
                _LATEST_REFRESH.release()
        threading.Thread(target=work, daemon=True).start()
    return _LATEST["version"]


def _verify_ytdlp(path: Path) -> bool:
    """在另一個程序實際載入新版 yt-dlp，確認能用才切換（打包版用 App 本身的 --check-ytdlp）。"""
    cmd = [sys.executable] if FROZEN else [sys.executable, str(BUNDLE / "native_app.py")]
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


# 桌面 App 設定的重新啟動方式：handler(cmd, env) 要讓介面先正常關閉，再啟動 cmd。
# 沒設定（純引擎）時直接啟動新程序並結束。
RESTART_HANDLER = None


def restart_process():
    """以相同參數重新啟動自己（載入新版 yt-dlp）。"""
    env = {**os.environ, "YTDL_JUST_UPDATED": "1"}
    # 打包版 sys.argv[0] 就是 App 本身；原始碼版要再帶上 server.py / native_app.py
    args = sys.argv[1:] if FROZEN else sys.argv
    cmd = [sys.executable, *args]
    if RESTART_HANDLER is not None:
        RESTART_HANDLER(cmd, env)
        return
    subprocess.Popen(cmd, env=env, cwd=str(ROOT))
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


# 繼承 DownloadCancelled：播放清單模式（ignoreerrors）下 yt-dlp 會吞掉一般例外繼續下一部，
# 只有 DownloadCancelled 會直接中止，暫停／取消／磁碟滿才不會被當成「這一部失敗」
class Cancelled(DownloadCancelled):
    msg = "已取消"


class DiskFull(DownloadCancelled):
    pass


class DownloadDirUnavailable(Exception):
    def __init__(self, location: Path, detail: str):
        self.location, self.detail = location, detail
        super().__init__(detail)


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


_YT_ID = re.compile(r"[A-Za-z0-9_-]{11}")


def url_problem(url: str) -> str | None:
    """網址明顯不完整時回傳原因（"invalid_url" 或 ENGINE_TEXT 的鍵），沒問題時回傳 None。
    R14：`watch?v=` 空 id 會被 yt-dlp 當成「recommended」清單。"""
    from urllib.parse import parse_qs, urlsplit
    if not re.match(r"^https?://", url):
        return "invalid_url"
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
    except ValueError:
        return "invalid_url"
    if not host:
        return "invalid_url"
    if host == "youtu.be":
        if not _YT_ID.fullmatch(parts.path.strip("/").split("/")[0]):
            return "youtube_incomplete"
    elif re.fullmatch(r"(?:www\.|m\.|music\.)?youtube(?:-nocookie)?\.com", host):
        path = parts.path.rstrip("/")
        if path in ("", "/watch"):
            q = parse_qs(parts.query)
            vid = (q.get("v") or [""])[0]
            if not _YT_ID.fullmatch(vid) and not (q.get("list") or [""])[0]:
                return "youtube_incomplete"
        elif re.fullmatch(r"/(?:shorts|live|embed|v)", path):
            return "youtube_incomplete"
    return None


@app.post("/api/info")
def api_info():
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    problem = url_problem(url)
    if problem:
        return api_error("invalid_url", 400, detail=url, msg=None if problem == "invalid_url" else problem)
    opts = {**BASE_OPTS, "skip_download": True, "extract_flat": "in_playlist",
            "noplaylist": bool(data.get("noplaylist", True))}
    _apply_network_opts(opts, data.get("network") or {})
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:  # noqa: BLE001
        return api_exception(e, 400)

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
            raise OptionError("range_format", chunk=chunk)
        start = parse_duration(m.group(1))
        end_raw = m.group(2)
        end = float("inf") if end_raw in (None, "inf", "end") else parse_duration(end_raw)
        if start is None or end is None or end <= start:
            raise OptionError("range_invalid", chunk=chunk)
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
RESUMABLE = ("error", "paused")  # 可以按「繼續下載」的狀態
FINISHED = ("done", "error", "cancelled", "paused")  # 不會再變動、檔案列表可以快取的狀態
AUTO_RESUME = 3  # 下載途中斷線時自動續傳的次數（每次都會重新取得串流網址）
RESUME_DELAY = 5
# 網路類錯誤（DNS 失敗、逾時、5xx、429）即使還沒下載到資料也重試，每次等待的秒數（R10）
NET_BACKOFF = (5, 15, 60)
NET_CODES = ("network_dns", "network_timeout", "rate_limited")
LOG_TAIL = 30  # 工作失敗時寫進 engine.log 的紀錄行數

# 判斷「真的下載到了」：影片／音訊容器（字幕模式看字幕檔、縮圖模式看圖片），縮圖和字幕不算主檔（R2）
MEDIA_EXTS = {"mp4", "mkv", "webm", "mov", "avi", "flv", "m4v", "3gp", "ts", "mp3", "m4a", "aac", "opus", "ogg",
              "oga", "flac", "wav", "alac", "mka", "weba"}
SUB_EXTS = {"srt", "vtt", "ass", "ssa", "lrc", "ttml", "srv1", "srv2", "srv3", "json3"}
IMAGE_EXTS = {"jpg", "jpeg", "png", "webp"}


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
        self.status = "queued"  # queued / downloading / processing / done / error / cancelled / paused
        self.progress = 0.0
        self.speed = None
        self.eta = None
        self.downloaded = 0
        self.total = None
        # 階段與錯誤只存代碼＋參數，回應時才依語言組成文字（第 5.3 節第 4 點）
        self.stage_code = "queued"
        self.stage_params: dict = {}
        self.item = None  # 播放清單第幾部
        self.error_code: str | None = None
        self.error_params: dict | None = None
        self.warnings: list = []  # {"key", "args"}（ENGINE_TEXT）；舊版 job.json 是字串
        self.failed_items: list[dict] = []  # 播放清單裡無法下載的項目：index、title、id、error_code、error_detail
        self.done_count = self.total_count = None
        self.log: deque[str] = deque(maxlen=200)
        self.cancel_flag = threading.Event()
        self.stop_reason = None  # "pause" / "cancel"：cancel_flag 被設定的原因
        self.run_token = 0  # 每次開始（或重新開始）加一；舊的執行緒看到不一樣就自行結束
        self.running = False  # 有執行緒正在下載或收尾（狀態可能已經是 done/error/paused）
        self.retry_indices: list[int] | None = None  # 「重試失敗的項目」只跑這幾部
        self.rate = RateMeter()
        self.pp_out: Path | None = None  # 目前後處理步驟正在寫出的暫存檔
        self.pp_total = 0  # 預計寫出的大小（輸入檔總和）
        self.pp_started = 0.0
        self.created = time.time()
        self.finished = None
        self._files_cache: list[dict] | None = None
        self._partial_cache: int | None = None
        self._run_failures: list[dict] = []
        self._cur_entry: dict | None = None
        self._autonumber = None
        self._last_error = None

    # ---------- 狀態 ----------
    def set_stage(self, code: str, **params):
        self.stage_code = code
        self.stage_params = params

    def fail(self, code: str, detail: str | None = None, **kw):
        """記下錯誤代碼與參數（kw 同 error_params：msg、location、kept、action、訊息參數）。"""
        self.error_code = code
        self.error_params = error_params(detail, **kw)

    def clear_error(self):
        self.error_code = self.error_params = None
        self.disk_error = None

    # 中文版本：寫紀錄檔、測試與舊程式碼用；API 回應用 view(lang)
    @property
    def stage(self) -> str:
        return render_stage(self.stage_code, self.stage_params, "zh")

    @property
    def error(self) -> str | None:
        return self.view("zh")["error"]

    @property
    def error_action(self):
        return self.view("zh")["error_action"]

    @property
    def error_detail(self):
        return self.view("zh")["error_detail"]

    def warning_texts(self, lang: str = "zh") -> list[str]:
        return [w if isinstance(w, str) else engine_text(w.get("key", ""), lang, **(w.get("args") or {}))
                for w in self.warnings]

    def view(self, lang: str = "zh") -> dict:
        """依語言組成的階段、錯誤、警告文字。"""
        d = {"stage": render_stage(self.stage_code, self.stage_params, lang)}
        if self.error_code:
            d.update(render_error(self.error_code, self.error_params, lang))
        else:
            d.update(error=None, error_code=None, error_detail=None, error_action=None, error_faq=None)
        d["warnings"] = self.warning_texts(lang)
        if self.status == "done" and d["warnings"] and not d["error"]:
            d["error"] = "；".join(d["warnings"]) if em.normalize_lang(lang) == "zh" else "; ".join(d["warnings"])
        items = []
        for f in self.failed_items:
            code = f.get("error_code") or em.classify(f.get("error_detail") or f.get("error") or "")
            detail = f.get("error_detail") or f.get("error") or ""
            r = render_error(code, {"detail": detail}, lang)
            items.append({"index": f.get("index"), "title": f.get("title"), "id": f.get("id"),
                          "error_code": code, "error": r["error"], "error_detail": detail})
        d["failed_items"] = items
        return d

    def invalidate_cache(self):
        self._files_cache = self._partial_cache = None

    # ---------- 檔案 ----------
    def files(self):
        """下載好的檔案（不含暫存資料夾與工作紀錄）；磁碟拔掉時回傳空清單。"""
        out = []
        try:
            if not self.dir.exists():
                return []
            for p in sorted(self.dir.rglob("*")):
                if not p.is_file() or ".tmp" in p.relative_to(self.dir).parts:
                    continue
                if p.name.endswith(TEMP_SUFFIXES) or p.name in (JOB_META, JOB_META + ".tmp"):
                    continue
                out.append({"name": p.relative_to(self.dir).as_posix(), "size": p.stat().st_size})
        except OSError:
            return []
        return out

    def cached_files(self):
        """已結束的工作檔案不會再變，只掃一次資料夾（Q7：/api/jobs 每 0.7 秒輪詢一次）。"""
        if self.status not in FINISHED:
            return self.files()
        if self._files_cache is None:
            self._files_cache = self.files()
        return self._files_cache

    def partial_bytes(self) -> int:
        """可接著用的暫存資料大小：下載到一半的 .part，以及已下載完、還沒合併的串流（<檔名>.f<格式>.<副檔名>）。
        縮圖、字幕不算；合併到一半的 <檔名>.temp.<副檔名> 也不算，重跑時 FFmpeg 會整個重寫。"""
        tmp = self.dir / ".tmp"
        try:
            if not tmp.exists():
                return 0
            total = 0
            for p in tmp.rglob("*"):
                try:
                    if p.is_file() and (".part" in p.name or STREAM_RE.search(p.name)):
                        total += p.stat().st_size
                except OSError:
                    pass
        except OSError:
            return 0
        return total

    def cached_partial(self) -> int:
        if self.status not in FINISHED:
            return self.partial_bytes()
        if self._partial_cache is None:
            self._partial_cache = self.partial_bytes()
        return self._partial_cache

    def has_main_media(self) -> bool:
        mode = self.options.get("mode") or "av"
        want = SUB_EXTS if mode == "subs" else IMAGE_EXTS if mode == "thumb" else MEDIA_EXTS
        for f in self.files():
            name = f["name"]
            if name.rsplit(".", 1)[-1].lower() in want and not STREAM_RE.search(name):
                return True
        return False

    # ---------- 輸出 ----------
    def to_dict(self, with_log=False, lang: str | None = None):
        """API 回傳的工作物件；文字依 lang（沒給就用目前請求的 Accept-Language）組成。"""
        lang = lang or req_lang()
        d = {k: getattr(self, k) for k in (
            "id", "url", "title", "status", "progress", "speed", "eta", "downloaded", "total", "item",
            "created", "finished", "stage_code", "stage_params", "error_params", "done_count", "total_count")}
        d.update(self.view(lang))
        d["mode"] = self.options.get("mode")
        if self.status in ("done", "error", "cancelled", "paused"):
            d["files"] = self.cached_files()
        if self.status in RESUMABLE:
            d["partial"] = self.cached_partial()
        if self.status == "queued":
            d["queue_position"] = SCHED.position(self)
        if with_log:
            d["log"] = list(self.log)
        return d

    def save(self):
        """寫入 job.json（原子寫入），引擎被關掉後重開仍能接續；紀錄也一起存，重開後還看得到失敗原因。
        stage、error 另存一份中文文字，給舊版引擎（降版）讀。"""
        data = {k: getattr(self, k) for k in (
            "id", "url", "options", "title", "status", "stage_code", "stage_params", "error_code", "error_params",
            "warnings", "failed_items", "done_count", "total_count", "progress", "created", "finished")}
        data["stage"], data["error"] = self.stage, self.error
        data["log"] = list(self.log)
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            tmp = self.dir / (JOB_META + ".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self.dir / JOB_META)
        except OSError:
            pass

    @classmethod
    def load(cls, meta: Path) -> Job:
        """讀 job.json；v1.2 以前（只有中文 stage／error）與第一階段（stage_code 舊代碼、error_detail）的紀錄也讀得懂。"""
        d = json.loads(meta.read_text(encoding="utf-8"))
        job = cls(d["url"], d.get("options") or {}, d.get("title"), job_id=meta.parent.name, job_dir=meta.parent)
        job.created = d.get("created") or meta.stat().st_mtime
        job.finished = d.get("finished")
        job.progress = d.get("progress") or 0.0
        job.log.extend(str(x) for x in (d.get("log") or [])[-job.log.maxlen:])
        job.warnings = list(d.get("warnings") or [])
        job.failed_items = [dict(f) for f in d.get("failed_items") or [] if isinstance(f, dict)]
        job.done_count, job.total_count = d.get("done_count"), d.get("total_count")
        if d.get("status") in ACTIVE:
            # 上次引擎在下載途中被關閉（關掉視窗、重開機、當機）
            _mark_interrupted(job)
            return job
        job.status = d.get("status") or "error"
        code = d.get("stage_code")
        code = _STAGE_ALIASES.get(code, code)
        if code not in STAGE_CODES:
            code = _ZH_STAGE_TO_CODE.get(d.get("stage") or "") or \
                {"done": "done", "cancelled": "cancelled", "paused": "paused"}.get(job.status, "failed")
        params = d.get("stage_params")
        if params is None and code == "done_partial":  # 第一階段沒存參數
            params = {"done": job.done_count, "total": job.total_count}
        job.set_stage(code, **(params or {}))
        if "error_params" in d:
            job.error_code, job.error_params = d.get("error_code"), d.get("error_params")
        elif d.get("error") and job.status == "done":
            if not job.warnings:
                job.warnings = [d["error"]]  # 舊版「完成（有警告）」把警告放在 error
        elif code == "interrupted" and job.status == "error":
            _mark_interrupted(job)
        elif d.get("error"):
            raw = d.get("error_detail") or d["error"]
            job.fail(d.get("error_code") or em.classify(raw), raw)
        return job


def _mark_interrupted(job: Job):
    part = job.partial_bytes()
    job.status = "error"
    job.set_stage("interrupted")
    if part:
        job.fail("unknown", msg="interrupted_size", size=_gb(part), action="resume")
    else:
        job.fail("unknown", msg="interrupted", action="resume")
    job.finished = job.finished or time.time()


class Scheduler:
    """可調整上限的排程器（取代 threading.Semaphore，SET8）：先進先出，上限改了立刻生效。"""

    def __init__(self, limit: int):
        self.limit = limit
        self.running = 0
        self.waiting: list[tuple[Job, int]] = []
        self.cond = threading.Condition()

    def set_limit(self, n: int):
        with self.cond:
            self.limit = n
            self.cond.notify_all()

    def acquire(self, job: Job, token: int) -> bool:
        """輪到這個工作時回傳 True；排隊中被暫停、取消或被新的一輪取代時回傳 False。"""
        entry = (job, token)
        with self.cond:
            self.waiting.append(entry)
            try:
                while True:
                    if job.cancel_flag.is_set() or job.run_token != token:
                        return False
                    if self.waiting[0] is entry and self.running < self.limit:
                        self.running += 1
                        return True
                    self.cond.wait(0.5)
            finally:
                self.waiting.remove(entry)
                self.cond.notify_all()

    def release(self):
        with self.cond:
            self.running -= 1
            self.cond.notify_all()

    def wake(self):
        with self.cond:
            self.cond.notify_all()

    def position(self, job: Job) -> int | None:
        """排隊中的第幾位（1 起算）；執行緒還沒進到排隊時回傳 None。"""
        with self.cond:
            # 已被暫停／取代、還沒醒來離開的舊項目不算
            live = [j for j, t in self.waiting if j.run_token == t and not j.cancel_flag.is_set()]
        for i, j in enumerate(live):
            if j is job:
                return i + 1
        return None


PARALLEL_RANGE = (1, 5)


def _initial_parallel() -> int:
    """同時下載數：設定頁（settings.json）> 環境變數 YTDL_PARALLEL > 3。"""
    raw = _load_settings().get("parallel")
    if raw is not None:
        return _int(raw, 3, *PARALLEL_RANGE)
    return _int(os.environ.get("YTDL_PARALLEL"), 3, 1, 16)


JOBS: dict[str, Job] = {}
JOBS_LOCK = threading.Lock()
SCHED = Scheduler(_initial_parallel())


def load_jobs():
    """引擎啟動時從下載資料夾恢復之前的工作（含被中斷、可續傳的）。磁碟不存在時略過。"""
    roots = {get_download_dir().resolve(), DEFAULT_DOWNLOAD_DIR.resolve()}
    for root in roots:
        try:
            metas = list(root.glob(f"*/{JOB_META}"))
        except OSError:
            continue
        for meta in metas:
            try:
                job = Job.load(meta)
            except (OSError, ValueError, KeyError, TypeError):
                continue
            with JOBS_LOCK:
                JOBS.setdefault(job.id, job)
            if job.stage_code == "interrupted":
                job.save()


class JobLogger:
    def __init__(self, job: Job, collect_failures: bool = False):
        self.job = job
        self.collect = collect_failures

    def debug(self, msg):
        if not msg.startswith("[debug]"):
            self.info(msg)

    def info(self, msg):
        self.job.log.append(msg)
        # 清單總數未知時 yt-dlp 會印 NA / None，第幾部仍然要記，失敗項目才收得到
        m = re.match(r"\[download\] Downloading item (\d+) of (\S+)", _strip_ansi(msg))
        if m:
            job = self.job
            job.item = f"{m.group(1)}/{m.group(2)}" if m.group(2).isdigit() else m.group(1)
            job._autonumber = int(m.group(1))
            if not job.retry_indices and m.group(2).isdigit():
                job.total_count = int(m.group(2))

    def warning(self, msg):
        self.job.log.append(f"⚠ {msg}")

    def error(self, msg):
        self.job.log.append(f"✖ {msg}")
        self.job._last_error = msg
        if self.collect and self.job._autonumber is not None:
            _record_failure(self.job, msg)


def _strip_ansi(s: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", s)


def _record_failure(job: Job, msg: str):
    """播放清單模式：記下這一部為什麼無法下載（第幾部、標題、代碼、原文）。"""
    raw = re.sub(r"^ERROR:\s*", "", _strip_ansi(msg)).strip()
    entry = job._cur_entry or {}
    if entry.get("autonumber") not in (None, job._autonumber):
        entry = {}  # 這一部沒經過 match_filter（例如網站沒標成單一影片），不要沿用上一部的標題
    index = entry.get("index")
    if index is None:
        n = job._autonumber
        index = job.retry_indices[n - 1] if job.retry_indices and n and n <= len(job.retry_indices) else n
    m = re.match(r"\[[\w:.-]+\]\s+([\w-]+):", raw)
    vid = entry.get("id") or (m.group(1) if m else None)
    if any(f["index"] == index for f in job._run_failures):
        return  # 同一部只記第一個錯誤
    # 只存代碼與原文；給使用者看的訊息在 to_dict() 依語言組成
    job._run_failures.append({"index": index, "title": entry.get("title") or vid, "id": vid,
                              "error_code": em.classify(raw), "error_detail": raw})


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


def _disk_full(job: Job, msg: str, **args) -> DiskFull:
    """記下空間不足的原因（ENGINE_TEXT 的鍵＋參數），回傳要丟出的例外。"""
    args = {"anchor": job.dir.anchor or str(job.dir), "reserve": _gb(MIN_FREE_BYTES), **args}
    job.disk_error = {"msg": msg, "args": args}
    return DiskFull(engine_text(msg, "zh", **args))


def _pp_disk_full(job: Job, free: int) -> DiskFull:
    return _disk_full(job, "disk_full_pp", step=job.stage_params.get("name"), need=_gb(job.pp_total), free=_gb(free))


def _check_pp_disk(job: Job):
    """後處理（合併、轉檔、寫入中繼資料）要再寫出一份接近原檔大小的檔案，開始前先確認空間（R11）。"""
    if not job.pp_total:
        return
    free = disk_info(job.dir)["free"]
    if free is not None and free - job.pp_total < MIN_FREE_BYTES:
        raise _pp_disk_full(job, free)


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
    job.rate.update(("pp", job.stage_code, out.name), done, total)
    job.speed, job.eta = job.rate.speed, job.rate.eta


def _watch_pp_disk(job: Job):
    """後處理期間每 3 秒看一次剩餘空間；快用完時先記下原因，FFmpeg 失敗時才回報得出「空間不足」。"""
    if job.status != "processing" or not job.pp_total:
        return
    now = time.time()
    if now - job._disk_checked < 3:
        return
    job._disk_checked = now
    free = disk_info(job.dir)["free"]
    if free is not None and free < MIN_FREE_BYTES // 4 and not job.disk_error:
        _pp_disk_full(job, free)  # 只記下原因，不能從這個執行緒中斷 FFmpeg


def _trim_length(job_dir: Path) -> int:
    """檔名長度上限：下載中的完整路徑是 <工作資料夾>\\.tmp\\<檔名>.f137.mp4.part，
    要留在 Windows 260 字元以內（R13）。"""
    return max(32, min(150, 240 - len(str(job_dir)) - 30))


def _is_network_err(e) -> bool:
    """網路類錯誤（DNS、逾時、429）與伺服器暫時錯誤（HTTP 5xx）：就算沒進度也值得等一下再試。"""
    return em.classify(e) in NET_CODES or bool(re.search(r"HTTP Error 5\d\d", str(e)))


def _clean_err(e: BaseException) -> str:
    msg = _strip_ansi(str(e))
    return re.sub(r"^ERROR:\s*", "", msg).strip() or e.__class__.__name__


def _is_disk_err(msg: str) -> bool:
    return "Errno 28" in msg or "No space left" in msg


def _finish_stopped(job: Job):
    """排隊中就被暫停或取消（執行緒還沒開始下載）。"""
    if job.stop_reason == "pause":
        job.status = "paused"
        job.set_stage("paused")
    else:
        job.status = "cancelled"
        job.set_stage("cancelled")
        shutil.rmtree(job.dir / ".tmp", ignore_errors=True)
    job.speed = job.eta = None
    job.finished = job.finished or time.time()
    job.invalidate_cache()
    job.save()


def run_job(job: Job, token: int | None = None):
    token = job.run_token if token is None else token
    granted = SCHED.acquire(job, token)
    with JOBS_LOCK:
        # 拿到名額的同一瞬間也可能剛好被暫停／取消（_stop 會換 token），在鎖裡確認後才標成下載中
        current = job.run_token == token
        start = granted and current and not job.cancel_flag.is_set()
        if start:
            job.running = True
            job.status = "downloading"
            job.set_stage("preparing")
    if not start:
        if granted:
            SCHED.release()
        if current:  # 排隊中被暫停或取消；被新的一輪取代時什麼都不做
            _finish_stopped(job)
        return
    try:
        _run_job(job)
    finally:
        with JOBS_LOCK:
            job.running = False  # 收尾（存檔、清暫存）做完才允許繼續、重試、刪除
        SCHED.release()


def _run_job(job: Job):
    job.invalidate_cache()
    job.item = job._autonumber = job._cur_entry = job._last_error = None
    job._run_failures = []
    playlist = bool(job.options.get("playlist"))
    try:
        opts = build_opts(job.options, job.dir)
    except Exception as e:  # noqa: BLE001
        job.status = "error"
        job.set_stage("config_error")
        if isinstance(e, OptionError):
            job.fail("unknown", str(e), msg=e.key, action=None, **e.args_)
        else:
            job.fail("unknown", _clean_err(e), msg="options_invalid", action=None)
        job.finished = time.time()
        job.save()
        return
    if job.retry_indices:
        opts["playlist_items"] = ",".join(str(i) for i in job.retry_indices)
    if playlist:
        # 清單裡有一部無法下載（私人、已刪除、地區限制）時記下來、繼續下一部（R3）
        opts["ignoreerrors"] = "only_download"
    opts["trim_file_name"] = _trim_length(job.dir)

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
            if need:
                raise _disk_full(job, "disk_full_download_need", free=_gb(free), need=_gb(need))
            raise _disk_full(job, "disk_full_download", free=_gb(free))

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
            if job.stage_code == "pausing":
                pass
            elif fid:
                job.set_stage("downloading", format_id=fid)
            else:
                job.set_stage("downloading")
            job.downloaded, job.total = done, total
            if total:
                job.progress = round(min(100.0, done * 100 / total), 1)
            elif d.get("fragment_count"):
                job.progress = round((d.get("fragment_index") or 0) * 100 / d["fragment_count"], 1)
            job.rate.update(d.get("filename"), done, total)
            job.speed, job.eta = job.rate.speed, job.rate.eta
        elif st == "finished":
            job.progress = 100.0
            job.set_stage("download_finished")
            job.speed = job.eta = None

    def pp_hook(d):
        if job.cancel_flag.is_set():
            raise Cancelled()
        if d.get("status") == "started":
            _pp_start(job, d.get("info_dict") or {})
            job.progress, job.downloaded, job.total = 0.0, 0, None  # 不沿用下載階段的 100%
            job.speed = job.eta = None
            job.set_stage("postprocessing", name=d.get("postprocessor"))
            job.status = "processing"
            _check_pp_disk(job)
        elif d.get("status") == "finished":
            job.pp_out = None

    def match_filter(info, incomplete=False):
        """播放清單每一部開始前都會經過這裡：記下第幾部和標題，失敗時才知道是哪一部。
        不回傳值（None）＝照常下載，不會過濾掉任何項目。"""
        if info.get("playlist_index") is not None:
            prev = job._cur_entry or {}
            same = prev.get("index") == info.get("playlist_index")
            job._cur_entry = {"index": info.get("playlist_index"), "autonumber": info.get("playlist_autonumber"),
                              "id": info.get("id"), "title": info.get("title") or (prev.get("title") if same else None)}

    opts["logger"] = JobLogger(job, collect_failures=playlist)
    opts["progress_hooks"] = [hook]
    opts["postprocessor_hooks"] = [pp_hook]
    if playlist:
        opts["match_filter"] = match_filter
    watching = threading.Event()

    def watch_pp():
        while not watching.wait(1):
            _pp_progress(job)
            _watch_pp_disk(job)

    try:
        dir_err = download_dir_problem(job.dir)
        if dir_err:
            raise DownloadDirUnavailable(job.dir, dir_err)
        job.save()
        threading.Thread(target=watch_pp, daemon=True).start()
        free = disk_info(job.dir)["free"]
        if free is not None and free < MIN_FREE_BYTES:
            raise _disk_full(job, "disk_full_start", free=_gb(free))
        _download_with_retries(job, opts, playlist)
        _finish_success(job, playlist)
    except Cancelled:
        if job.stop_reason == "pause":
            job.status = "paused"
            job.set_stage("paused")
        else:
            job.status = "cancelled"
            job.set_stage("cancelled")
    except DownloadDirUnavailable as e:
        job.status = "error"
        job.set_stage("download_dir_unavailable")
        job.fail("download_dir_unavailable", e.detail, location=e.location)
    except BaseException as e:  # noqa: BLE001 — yt-dlp 會把 hook 例外包成 DownloadError
        _finish_failure(job, e)
    finally:
        watching.set()
        job.pp_out = None
        # 失敗、暫停時保留 .tmp 裡的暫存檔，才能按「繼續下載」從中斷處接著下載
        if job.status in ("done", "cancelled"):
            shutil.rmtree(job.dir / ".tmp", ignore_errors=True)
        job.speed = job.eta = None
        job.finished = time.time()
        job.retry_indices = None
        job.invalidate_cache()
        if job.status == "error":
            tail = "\n".join(f"    {line}" for line in list(job.log)[-LOG_TAIL:])
            v = job.view("zh")
            _engine_log(f"工作 {job.id} 失敗（{job.error_code}）：{job.title}\n  {v['error']}\n  原文：{v['error_detail']}"
                        f"\n  最後 {LOG_TAIL} 行紀錄：\n{tail}")
        job.save()


def _download_with_retries(job: Job, opts: dict, playlist: bool):
    """下載；斷線時自動續傳，網路類錯誤就算沒進度也退避重試（R10）。"""
    attempt = net_attempt = 0
    while True:
        before = job.partial_bytes()
        job._run_failures = []
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                code = ydl.download([job.url])
            if playlist and code and job._autonumber is None and job._last_error:
                # 清單模式（ignoreerrors）連清單本身都讀不到（例如一開始就斷線）時不會丟例外，這裡補丟出來
                raise yt_dlp.utils.DownloadError(job._last_error)
            return
        except (Cancelled, DiskFull):
            raise
        except Exception as e:
            # 大檔案下載數小時，常遇到網路中斷或串流網址過期（HTTP 403）。
            # 這一輪確實有下載到資料才重新解析網址、從中斷處續傳；網路類錯誤就算沒進度也等一下再試；
            # 其他沒進度的錯誤（格式不存在等）直接回報。
            if job.cancel_flag.is_set():
                raise Cancelled() from None
            msg = _clean_err(e)
            if job.disk_error or em.classify(e) == "disk_full":
                raise
            if attempt < AUTO_RESUME and job.partial_bytes() > before:
                attempt += 1
                delay = RESUME_DELAY
                job.log.append(f"⟳ 下載中斷：{msg}")
                job.log.append(f"⟳ {delay} 秒後自動續傳（第 {attempt}/{AUTO_RESUME} 次）")
                job.set_stage("reconnecting", attempt=attempt, max=AUTO_RESUME)
            elif _is_network_err(e) and net_attempt < len(NET_BACKOFF):
                delay = NET_BACKOFF[net_attempt]
                net_attempt += 1
                job.log.append(f"⟳ 網路錯誤：{msg}")
                job.log.append(f"⟳ {delay} 秒後重試（第 {net_attempt}/{len(NET_BACKOFF)} 次）")
                job.set_stage("waiting_network", s=delay, attempt=net_attempt, max=len(NET_BACKOFF))
            else:
                raise
            job.status, job.speed, job.eta = "downloading", None, None
            if job.cancel_flag.wait(delay):
                raise Cancelled() from None


def _merge_failures(job: Job):
    """這一輪的失敗項目併進工作：重試失敗項目時，只換掉這次重跑的那幾部。"""
    if job.retry_indices:
        retried = set(job.retry_indices)
        job.failed_items = [f for f in job.failed_items if f["index"] not in retried] + job._run_failures
    else:
        job.failed_items = list(job._run_failures)
    job.failed_items.sort(key=lambda f: (f["index"] is None, f["index"] or 0))
    if job.total_count:
        job.done_count = max(0, job.total_count - len(job.failed_items))


def _finish_success(job: Job, playlist: bool):
    """yt-dlp 正常結束：確認真的有主要媒體檔（R2）、整理播放清單的失敗項目（R3）。"""
    if job.cancel_flag.is_set():
        raise Cancelled()
    if playlist:
        _merge_failures(job)
    job.warnings = []
    if not job.has_main_media():
        job.status = "error"
        job.set_stage("failed")
        if job.failed_items:
            first = job.failed_items[0]
            job.fail(first["error_code"], first["error_detail"], msg="playlist_all_failed",
                     n=len(job.failed_items), reason_code=first["error_code"])
            return
        detail = _clean_err(Exception(job._last_error)) if job._last_error else ""
        mode = job.options.get("mode")
        job.fail(em.classify(detail) if detail else "unknown", detail,
                 msg="no_subs" if mode == "subs" else "no_thumb" if mode == "thumb" else "no_media")
        return
    job.status, job.progress = "done", 100.0
    job.clear_error()
    if job.failed_items:
        n = len(job.failed_items)
        if job.total_count:
            job.warnings = [{"key": "done_partial", "args": {"done": job.done_count, "total": job.total_count, "n": n}}]
            job.set_stage("done_partial", done=job.done_count, total=job.total_count)
        else:
            job.warnings = [{"key": "items_failed", "args": {"n": n}}]
            job.set_stage("done_with_warnings")
    else:
        job.set_stage("done")
        if playlist and job.total_count:
            job.done_count = job.total_count


def _finish_failure(job: Job, e: BaseException):
    msg = _clean_err(e)
    if job.cancel_flag.is_set():
        job.status = "paused" if job.stop_reason == "pause" else "cancelled"
        job.set_stage(job.status)
        return
    if job.options.get("playlist"):
        _merge_failures(job)
    code = em.classify(e)
    if not job.disk_error and code == "ffmpeg_failed" and job.pp_total:
        free = disk_info(job.dir)["free"]
        if free is not None and free < job.pp_total:  # FFmpeg 寫到一半空間用完，錯誤訊息不一定有 Errno 28
            _pp_disk_full(job, free)
    if job.disk_error or code == "disk_full":
        job.status = "error"
        job.set_stage("disk_full")
        de = job.disk_error or {"msg": "disk_full_generic", "args": {
            "anchor": job.dir.anchor or str(job.dir), "free": _gb(disk_info(job.dir)["free"])}}
        job.fail("disk_full", msg, msg=de["msg"], kept=len(job.files()), **de["args"])
    elif job.has_main_media():
        # 主檔已下載，只有後製步驟失敗 → 視為完成並附上警告（原文留在紀錄裡）
        job.status, job.progress = "done", 100.0
        job.clear_error()
        job.set_stage("done_with_warnings")
        # detail 不出現在訊息裡（ENGINE_TEXT 用不到的參數會被忽略），留給之後的「詳細資訊」
        job.warnings = [{"key": "steps_failed", "args": {"reason_code": code, "detail": msg}}]
        job.log.append(f"⚠ 部分步驟失敗：{msg}")
    else:
        job.status = "error"
        job.set_stage("failed")
        job.fail(code, msg)


def _start(job: Job, token: int):
    threading.Thread(target=run_job, args=(job, token), daemon=True).start()


@app.post("/api/download")
def api_download():
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    problem = url_problem(url)
    if problem:
        return api_error("invalid_url", 400, detail=url, msg=None if problem == "invalid_url" else problem)
    options = data.get("options") or {}
    try:
        build_opts(options, DEFAULT_DOWNLOAD_DIR / "_validate")  # 先驗證，錯誤立刻回報
    except OptionError as e:
        return api_error("unknown", 400, detail=str(e), msg=e.key, action=None, **e.args_)
    except Exception as e:  # noqa: BLE001
        return api_error("unknown", 400, detail=_clean_err(e), msg="options_invalid", action=None)
    d = get_download_dir()
    problem = download_dir_problem(d)
    if problem:
        return api_error("download_dir_unavailable", 503, detail=problem, location=d)
    job = Job(url, options, data.get("title"))
    with JOBS_LOCK:
        JOBS[job.id] = job
    job.save()
    _start(job, job.run_token)
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


def _stop(job: Job, reason: str) -> bool:
    """暫停或取消；呼叫時要持有 JOBS_LOCK。回傳 False 表示這個狀態不能這樣做。"""
    if job.running and job.status not in ACTIVE:
        return False  # 執行緒還在收尾，狀態馬上就會定下來
    if reason == "pause" and job.status not in ACTIVE:
        return False
    if reason == "cancel" and job.status not in (*ACTIVE, "paused"):
        return False
    job.stop_reason = reason
    job.cancel_flag.set()
    if job.status in ("queued", "paused"):
        # 還沒開始下載：直接改狀態並存檔（R7：重開 App 時不會「復活」成已中斷）
        job.run_token += 1  # 還在排隊的執行緒看到 token 變了就自行結束
        _finish_stopped(job)
    elif reason == "pause":
        job.set_stage("pausing")  # 等 yt-dlp 走到下一個進度回報點才會真的停下
    SCHED.wake()
    return True


@app.post("/api/jobs/<job_id>/cancel")
def api_cancel(job_id):
    """取消＝不要了：停止並刪除暫存檔。想之後接著下載請用 pause。"""
    job = _get_job(job_id)
    with JOBS_LOCK:
        _stop(job, "cancel")
    return jsonify(job.to_dict())


@app.post("/api/jobs/<job_id>/pause")
def api_pause(job_id):
    """暫停：下載中或排隊中都可以，暫存檔保留，之後用 resume 從原本的位置接著下載（R4）。"""
    job = _get_job(job_id)
    with JOBS_LOCK:
        ok = _stop(job, "pause")
    if not ok:
        return api_error("unknown", 409, msg="pause_not_allowed", action=None)
    return jsonify(job.to_dict())


def _restart(job: Job, retry_indices: list[int] | None = None) -> int:
    """把工作放回佇列；呼叫時要持有 JOBS_LOCK，回傳這一輪的 token。"""
    job.status = "queued"
    job.set_stage("queued")
    job.clear_error()
    job.speed = job.eta = job.finished = None
    job.cancel_flag.clear()
    job.stop_reason = None
    job.retry_indices = retry_indices
    job.invalidate_cache()
    if not retry_indices:
        job.warnings, job.failed_items = [], []
        job.done_count = job.total_count = None
        # 沒有可續傳資料也沒有完成檔時，改用目前的儲存位置（例如磁碟滿了、換到別顆磁碟後重試）
        try:
            movable = not job.partial_bytes() and not job.files()
        except OSError:
            movable = True
        if movable:
            new_dir = get_download_dir() / job.id
            if new_dir != job.dir:
                shutil.rmtree(job.dir, ignore_errors=True)
                job.dir = new_dir
    job.run_token += 1
    return job.run_token


def _failed_indices(job: Job) -> list[int]:
    return sorted({f["index"] for f in job.failed_items if isinstance(f.get("index"), int)})


def _requeue(job: Job, statuses, retry: bool = False) -> bool:
    """繼續下載（retry=False）或只重試失敗的項目（retry=True）；不符合條件時回傳 False。
    上一輪的執行緒還在收尾時不能重新開始，否則它的收尾會蓋掉新一輪的狀態。"""
    with JOBS_LOCK:
        indices = _failed_indices(job) if retry else None
        if job.running or job.status not in statuses or (retry and not indices):
            return False
        token = _restart(job, indices)
    job.log.append(f"⟳ 重試失敗的項目：{', '.join(map(str, indices))}" if retry else "⟳ 繼續下載")
    job.save()
    _start(job, token)
    return True


@app.post("/api/jobs/<job_id>/resume")
def api_resume(job_id):
    """失敗、中斷或暫停的工作用同一個資料夾重跑；yt-dlp 會偵測 .part 從中斷處續傳。"""
    job = _get_job(job_id)
    if not _requeue(job, RESUMABLE):
        return api_error("unknown", 409, msg="resume_not_allowed", action=None)
    return jsonify(job.to_dict())


@app.post("/api/jobs/<job_id>/retry_failed")
def api_retry_failed(job_id):
    """播放清單：只重新下載失敗的那幾部（R3）。"""
    job = _get_job(job_id)
    if not _requeue(job, ("done", "error"), retry=True):
        return api_error("unknown", 409, msg="retry_failed_none", action=None)
    return jsonify(job.to_dict())


def _bulk(pick, act) -> list[dict]:
    with JOBS_LOCK:
        targets = [j for j in JOBS.values() if pick(j)]
    done = [j for j in sorted(targets, key=lambda j: j.created) if act(j)]
    return [j.to_dict() for j in done]


@app.post("/api/jobs/pause_all")
def api_pause_all():
    def act(j):
        with JOBS_LOCK:
            return _stop(j, "pause")
    jobs = _bulk(lambda j: j.status in ACTIVE, act)
    return jsonify(ok=True, count=len(jobs), jobs=jobs)


@app.post("/api/jobs/resume_all")
def api_resume_all():
    jobs = _bulk(lambda j: j.status == "paused", lambda j: _requeue(j, ("paused",)))
    return jsonify(ok=True, count=len(jobs), jobs=jobs)


@app.post("/api/jobs/retry_all")
def api_retry_all():
    """全部重試：失敗的工作重新下載；完成但有部分項目失敗的播放清單只重試失敗的項目。"""
    def act(j):
        return _requeue(j, ("error",)) if j.status == "error" else _requeue(j, ("done",), retry=True)
    jobs = _bulk(lambda j: j.status == "error" or (j.status == "done" and _failed_indices(j)), act)
    return jsonify(ok=True, count=len(jobs), jobs=jobs)


def _forget(job: Job):
    """只從清單移除：刪掉工作紀錄與暫存檔，下載好的檔案留在原地；資料夾空了就一併移除。"""
    for name in (JOB_META, JOB_META + ".tmp"):
        try:
            (job.dir / name).unlink(missing_ok=True)
        except OSError:
            pass
    shutil.rmtree(job.dir / ".tmp", ignore_errors=True)
    try:
        job.dir.rmdir()  # 只有空資料夾才刪得掉
    except OSError:
        pass


@app.delete("/api/jobs/<job_id>")
def api_delete(job_id):
    """files=keep（預設）：只從清單移除，檔案保留；files=trash：連同檔案移到資源回收筒（R5）。"""
    job = _get_job(job_id)
    mode = request.args.get("files", "keep")
    if mode not in ("keep", "trash"):
        return api_error("unknown", 400, msg="delete_files_param", action=None)
    if job.status in ACTIVE or job.running:
        return api_error("unknown", 409, msg="job_busy", action=None)
    if mode == "trash":
        if job.dir.exists():
            if send2trash is None:
                return api_error("engine_internal", 500, msg="trash_unavailable", action=None)
            try:
                send2trash(str(job.dir))
            except Exception as e:  # noqa: BLE001 — send2trash 在各平台丟出的例外類別不同
                return api_error("engine_internal", 500, msg="trash_failed",
                                 detail=f"{e.__class__.__name__}: {e}", action=None)
    else:
        _forget(job)
    with JOBS_LOCK:
        JOBS.pop(job_id, None)
    return jsonify(ok=True, files=mode)


@app.post("/api/jobs/clear")
def api_clear():
    """清除已完成：從清單移除所有已完成的工作，不動檔案。"""
    with JOBS_LOCK:
        done = [j for j in JOBS.values() if j.status == "done" and not j.running]
        for j in done:
            JOBS.pop(j.id, None)
    for j in done:
        _forget(j)
    return jsonify(ok=True, count=len(done), ids=[j.id for j in done])


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
    d = get_download_dir()
    return jsonify(version=yt_dlp.version.__version__, latest=cached_latest_version(), channel=CHANNEL,
                   frozen=FROZEN, update_ready=UPDATE_STATE["ready"],
                   ffmpeg=bool(shutil.which("ffmpeg")), cookies_file=COOKIES_FILE.is_file(),
                   disk=disk_info(d), min_free=MIN_FREE_BYTES,
                   download_dir=str(d), **download_dir_status(d), parallel=SCHED.limit,
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
                   min_free=MIN_FREE_BYTES, disk=disk_info(d), **download_dir_status(d),
                   parallel=SCHED.limit, parallel_range=list(PARALLEL_RANGE),
                   # 列磁碟可能碰到離線的網路磁碟而變慢，只在明確要求時才列
                   drives=list_drives() if request.args.get("drives") == "1" else None)


@app.post("/api/settings")
def api_settings_save():
    """可以只送要改的欄位：download_dir（儲存位置）、parallel（同時下載數 1–5，立即生效）。"""
    body = request.get_json(silent=True) or {}
    settings = _load_settings()
    if "parallel" in body:
        try:
            n = int(body["parallel"])
        except (TypeError, ValueError):
            n = 0
        if not PARALLEL_RANGE[0] <= n <= PARALLEL_RANGE[1]:
            return api_error("unknown", 400, msg="parallel_range", lo=PARALLEL_RANGE[0], hi=PARALLEL_RANGE[1],
                             action=None)
        settings["parallel"] = n
    if "download_dir" in body or "parallel" not in body:  # 舊版只送 download_dir（空字串＝改回預設）
        if os.environ.get("YTDL_DOWNLOAD_DIR"):
            return api_error("unknown", 409, msg="dir_env_locked", action=None)
        raw = str(body.get("download_dir") or "").strip().strip('"')
        if not raw:
            target = DEFAULT_DOWNLOAD_DIR
        else:
            target = Path(raw).expanduser()
            if not target.is_absolute():
                return api_error("unknown", 400, msg="dir_not_absolute", action=None)
        try:
            target.mkdir(parents=True, exist_ok=True)
            probe = target / f".ytdl-write-test-{uuid.uuid4().hex[:6]}"
            probe.write_bytes(b"ok")
            probe.unlink()
        except OSError as e:
            return api_error("download_dir_unavailable", 400, detail=str(e), location=target)
        settings["download_dir"] = "" if target == DEFAULT_DOWNLOAD_DIR else str(target.resolve())
    try:
        _save_settings(settings)
    except OSError as e:
        return api_error("engine_internal", 500, msg="settings_save_failed", detail=str(e))
    if "parallel" in settings:
        SCHED.set_limit(settings["parallel"])
    return api_settings()


@app.post("/api/update")
def api_update():
    """手動更新 yt-dlp；沒有進行中的工作時自動重啟套用。打包版若已在背景下載好，直接重新啟動。"""
    if UPDATE_STATE["running"]:
        return api_error("unknown", 409, msg="update_running", action=None)
    if _busy():
        return api_error("unknown", 409, msg="update_busy", action=None)

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
        return api_error("cookies_invalid", 400, detail="not a Netscape format cookies file")
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


def _auth_hint(err: str, browser: str | None) -> str | None:
    """瀏覽器 Cookie 讀取失敗時更具體的說明（ENGINE_TEXT 的鍵）；沒有更具體的說明時回傳 None。"""
    low = err.lower()
    if browser in ("chrome", "edge", "brave", "opera", "vivaldi", "chromium") and (
            "dpapi" in low or "decrypt" in low or "could not copy" in low or "permission" in low):
        return "browser_cookies_locked"
    if "could not find" in low and "cookies database" in low:
        return "browser_cookies_not_found"
    return None


@app.post("/api/auth/test")
def api_auth_test():
    """測試目前的 Cookie 設定：是否登入 YouTube、是否偵測到 Premium。"""
    net = (request.get_json(silent=True) or {}).get("network") or {}
    opts = {**BASE_OPTS, "skip_download": True, "verbose": True, "noplaylist": True}
    _apply_network_opts(opts, net)
    if "cookiefile" not in opts and "cookiesfrombrowser" not in opts:
        return api_error("unknown", 400, msg="cookie_source_missing", action="open_cookie_settings")
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
        raw = _clean_err(e)
        browser = net.get("cookies_browser")
        hint = _auth_hint(raw, browser)
        if hint:
            return api_error("cookie_browser_locked", 400, detail=raw, msg=hint, browser=str(browser).title())
        return api_exception(e, 400)
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
        # 本機上有程式在聽時 1 ms 內就會連上；沒有時 Windows 不會立刻拒絕而是重試到逾時，
        # 所以逾時設短一點，不要讓每次啟動 App 都白等半秒
        s.settimeout(0.2)
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
