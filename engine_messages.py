"""引擎訊息：把 yt-dlp／引擎的錯誤翻成一般使用者看得懂的中英文訊息，並提供處理階段文字。

對外介面（見 docs/ROADMAP.md 第 5.5 節與附錄 A）：

- ``friendly_error(exc_or_message, lang="zh") -> {"code", "message", "detail", "action", "faq"}``
- ``error_payload(code, lang="zh", detail="") -> 同上``（引擎已經知道代碼時直接組出訊息）
- ``stage_text(stage_code, lang="zh", **params) -> str``
- ``pp_label(name, lang="zh") -> str``（yt-dlp 後處理步驟名稱）

``message`` 只放給使用者看的說明，不含本機完整路徑、命令列參數、GitHub 連結或「please report」；
yt-dlp 原文一律放在 ``detail``。地區限制的訊息不建議使用 Proxy 或其他規避方式（DISCLAIMER.md 第 3 點）。

這個模組不 import ``server``，可以單獨測試。
"""
from __future__ import annotations

import re
from pathlib import PureWindowsPath


class _Missing(Exception):
    """yt-dlp（或某個例外類別）不存在時的佔位類別，isinstance 永遠不成立，只剩關鍵字比對。"""


def _yt_class(module: str, name: str) -> type:
    """逐一取 yt-dlp 的例外類別：某一版改名或搬家時，只影響那一個類別，不會讓全部 isinstance 失效。"""
    try:
        mod = __import__(module, fromlist=[name])
    except ImportError:  # pragma: no cover — 引擎一定有 yt-dlp
        return _Missing
    cls = getattr(mod, name, None)
    return cls if isinstance(cls, type) and issubclass(cls, BaseException) else _Missing


HTTPError = _yt_class("yt_dlp.networking.exceptions", "HTTPError")
ProxyError = _yt_class("yt_dlp.networking.exceptions", "ProxyError")
TransportError = _yt_class("yt_dlp.networking.exceptions", "TransportError")
DownloadError = _yt_class("yt_dlp.utils", "DownloadError")
ExtractorError = _yt_class("yt_dlp.utils", "ExtractorError")
GeoRestrictedError = _yt_class("yt_dlp.utils", "GeoRestrictedError")
PostProcessingError = _yt_class("yt_dlp.utils", "PostProcessingError")
UnavailableVideoError = _yt_class("yt_dlp.utils", "UnavailableVideoError")
UnsupportedError = _yt_class("yt_dlp.utils", "UnsupportedError")

__all__ = [
    "ERROR_CODES",
    "PP_NAMES",
    "STAGE_CODES",
    "error_payload",
    "friendly_error",
    "normalize_lang",
    "pp_label",
    "stage_text",
]


def normalize_lang(lang: str | None) -> str:
    """``en`` 開頭（en、en-US、en_GB）回傳 ``"en"``，其他一律 ``"zh"``。"""
    return "en" if (lang or "").strip().lower().startswith("en") else "zh"


# ---------------------------------------------------------------------------
# 錯誤代碼（附錄 A）。代碼與 faq 錨點不能改，USER_GUIDE 與 D 工作包的測試會比對。
# ---------------------------------------------------------------------------

_ERRORS: dict[str, dict] = {
    "invalid_url": {
        "zh": "請輸入有效的網址（http 或 https 開頭）",
        "en": "Please enter a valid web address (starting with http or https).",
        "action": None, "faq": "err-invalid-url",
    },
    "unsupported_url": {
        "zh": "不支援這個網站，或這個網頁裡沒有影片",
        "en": "This website isn't supported, or there is no video on this page.",
        "action": None, "faq": "err-unsupported-url",
    },
    "video_unavailable": {
        "zh": "找不到這部影片，可能已被刪除或網址打錯",
        "en": "This video can't be found. It may have been removed, or the link may be wrong.",
        "action": None, "faq": "err-video-unavailable",
    },
    "private_video": {
        "zh": "這是私人影片，需要用有權限的帳號登入（設定 → Cookie）",
        "en": "This is a private video. Sign in with an account that has access (Settings → Cookies).",
        "action": "open_cookie_settings", "faq": "err-private-video",
    },
    "age_restricted": {
        "zh": "這部影片有年齡限制，請在「設定 → Cookie」登入自己的帳號後再試",
        "en": "This video is age-restricted. Sign in with your own account in Settings → Cookies, then try again.",
        "action": "open_cookie_settings", "faq": "err-age-restricted",
    },
    "members_only": {
        "zh": "這是頻道會員限定影片，需要登入有會員資格的帳號",
        "en": "This video is for channel members only. Sign in with an account that has a membership.",
        "action": "open_cookie_settings", "faq": "err-members-only",
    },
    "geo_blocked": {
        "zh": "這部影片在你所在的地區無法觀看",
        "en": "This video isn't available in your region.",
        "action": None, "faq": "err-geo-blocked",
    },
    "bot_check": {
        "zh": "YouTube 要求驗證，請設定 Cookie 登入後再試",
        "en": "YouTube is asking for verification. Sign in using Cookies in Settings, then try again.",
        "action": "open_cookie_settings", "faq": "err-bot-check",
    },
    "live_not_started": {
        "zh": "直播還沒開始，開播後再下載",
        "en": "This live stream hasn't started yet. Download it after it begins.",
        "zh_eta": "直播還沒開始（預計 {eta}後），開播後再下載",
        "en_eta": "This live stream hasn't started yet (expected in {eta}). Download it after it begins.",
        "action": None, "faq": "err-live-not-started",
    },
    "http_403": {
        "zh": "伺服器拒絕下載（連結可能過期），請按「繼續下載」；一直出現的話請更新 yt-dlp",
        "en": "The server refused the download (the link may have expired). Click “Resume”. "
              "If this keeps happening, update yt-dlp.",
        "action": "resume", "faq": "err-http-403",
    },
    "rate_limited": {
        "zh": "短時間內請求太多次，請過幾分鐘再試",
        "en": "Too many requests in a short time. Please wait a few minutes and try again.",
        "action": "retry", "faq": "err-rate-limited",
    },
    "format_unavailable": {
        "zh": "指定的畫質或格式已不存在，請重新解析後再選一次",
        "en": "The selected quality or format is no longer available. Analyze the link again and choose again.",
        "action": "reanalyze", "faq": "err-format-unavailable",
    },
    "ffmpeg_failed": {
        "zh": "下載完成，但「合併影音軌」等後製步驟失敗；原始檔已保留",
        "en": "The download finished, but a processing step such as merging video and audio failed. "
              "The original files were kept.",
        "action": None, "faq": "err-ffmpeg-failed",
    },
    "ffmpeg_missing": {
        "zh": "找不到 FFmpeg，請到「設定」查看狀態",
        "en": "FFmpeg can't be found. Check its status in Settings.",
        "action": None, "faq": "err-ffmpeg-missing",
    },
    "server_error": {
        "zh": "網站暫時無法回應（伺服器錯誤），請過幾分鐘再試",
        "en": "The website isn't responding right now (server error). Please try again in a few minutes.",
        "action": "retry", "faq": "err-network",
    },
    "network_dns": {
        "zh": "無法連線到網站，請確認網路連線",
        "en": "Can't reach the website. Please check your internet connection.",
        "action": "retry", "faq": "err-network",
    },
    "network_timeout": {
        "zh": "網路連線逾時，請確認網路後再試",
        "en": "The network connection timed out. Check your connection and try again.",
        "action": "retry", "faq": "err-network",
    },
    "proxy_error": {
        "zh": "連不上你設定的 Proxy，請檢查進階選項裡的 Proxy 設定",
        "en": "Can't connect to the proxy you set. Check the proxy setting in Advanced options.",
        "action": "open_network_settings", "faq": "err-proxy",
    },
    "cookie_browser_locked": {
        "zh": "無法讀取瀏覽器的 Cookie（Chrome／Edge 開著時會被鎖住）。請關閉瀏覽器再試，或改用 Firefox 或 cookies.txt",
        "en": "Can't read the browser's cookies (Chrome and Edge lock them while open). "
              "Close the browser and try again, or use Firefox or a cookies.txt file instead.",
        "action": "open_cookie_settings", "faq": "err-cookie-browser",
    },
    "cookies_invalid": {
        "zh": "cookies.txt 格式不正確，請重新匯出",
        "en": "The cookies.txt file isn't in the right format. Please export it again.",
        "action": "open_cookie_settings", "faq": "err-cookies-invalid",
    },
    "disk_full": {
        "zh": "磁碟空間不足，下載已停止，已完成的檔案會保留。請到「設定 → 儲存位置」改到空間較大的磁碟，或清出空間後再試",
        "en": "The disk is full, so the download stopped. Finished files were kept. "
              "Choose a drive with more space in Settings → Storage location, or free up space and try again.",
        "action": "open_storage_settings", "faq": "err-disk-full",
    },
    "download_dir_unavailable": {
        "zh": "儲存位置目前無法存取，請確認磁碟已接上，或到「設定 → 儲存位置」更換",
        "en": "The download location can't be accessed right now. Make sure the drive is connected, "
              "or change it in Settings → Storage location.",
        "zh_loc": "儲存位置（{loc}）目前無法存取，請確認磁碟已接上，或到「設定 → 儲存位置」更換",
        "en_loc": "The download location ({loc}) can't be accessed right now. Make sure the drive is connected, "
                  "or change it in Settings → Storage location.",
        "action": "open_storage_settings", "faq": "err-download-dir",
    },
    "engine_internal": {
        "zh": "下載引擎發生錯誤，請重試；一直發生的話請回報問題並附上紀錄檔",
        "en": "The download engine ran into an error. Try again; if it keeps happening, "
              "report the problem and attach the log file.",
        "action": "retry", "faq": "err-engine",
    },
    "unknown": {
        "zh": "下載失敗。可以展開「詳細資訊」查看原因，或回報問題",
        "en": "The download failed. Open “Details” to see why, or report the problem.",
        "action": "retry", "faq": "err-unknown",
    },
}

ERROR_CODES: tuple[str, ...] = tuple(_ERRORS)


# 依序比對：越具體、越容易被別的關鍵字誤判的放越前面。
# 例：Proxy 失敗的原文常含「timed out」，要排在 network_timeout 前；
# 「Sign in to confirm your age」也含「Sign in to confirm you」，年齡限制要排在機器人驗證前。
_RULES: list[tuple[str, tuple[type, ...], tuple[str | re.Pattern, ...]]] = [
    ("disk_full", (), ("errno 28", "no space left", "磁碟空間不足", "not enough space on the disk",
                       "there is not enough space")),
    ("cookies_invalid", (), ("netscape format", "netscape formatted", "cookies file must be")),
    ("cookie_browser_locked", (), ("cookie database", "cookies database", "dpapi", "failed to decrypt",
                                   "app-bound encryption", "cookie_decrypt", "unable to get key for cookie")),
    ("proxy_error", (ProxyError,), ("unable to connect to proxy", "proxyerror", "tunnel connection failed",
                                    "proxy authentication required", "cannot connect to proxy")),
    ("ffmpeg_missing", (), ("ffmpeg is not installed", "ffmpeg not found", "ffprobe and ffmpeg not found",
                            "ffmpeg/avconv not found", "ffprobe/avprobe and ffmpeg/avconv not found",
                            "ffmpeg is not available")),
    ("ffmpeg_failed", (PostProcessingError,), ("conversion failed", "ffmpeg exited with code",
                                               "postprocessing:", "error merging", "error fixing")),
    ("live_not_started", (), ("live event will begin", "premieres in", "premiere will begin",
                              "this live event has not started", "scheduled to start")),
    ("age_restricted", (), ("confirm your age", "age-restricted", "age restricted", "inappropriate for some users")),
    ("bot_check", (), ("not a bot", "sign in to confirm you")),
    ("members_only", (), ("members-only", "members only", "join this channel", "channel's members",
                          "available to this channel")),
    ("private_video", (), ("private video", "this video is private", "video is private")),
    ("geo_blocked", (GeoRestrictedError,), ("not available in your country", "geo restriction", "geo-restrict",
                                            "georestrict", "not available from your location",
                                            "not available in your region", "available in your country")),
    ("format_unavailable", (), ("requested format is not available", "requested format not available",
                                "no video formats found")),
    ("rate_limited", (), ("http error 429", "too many requests")),
    ("http_403", (), ("http error 403", "403: forbidden", "403 forbidden")),
    # yt-dlp 的 HTTPError 一律寫成「HTTP Error 5xx: …」；不比對裸的「internal server error」，那是引擎自己的 Flask 500
    ("server_error", (), (re.compile(r"http error 5\d\d\b"), "503: service unavailable", "502: bad gateway")),
    ("network_dns", (), ("getaddrinfo failed", "failed to resolve", "name or service not known",
                         "nodename nor servname", "temporary failure in name resolution", "errno 11001",
                         "errno -2", "errno -3", "name resolution", "no address associated with hostname")),
    ("network_timeout", (TransportError,), ("timed out", "timeout", "transporterror", "connection reset",
                                            "connection aborted", "connection refused", "remotedisconnected",
                                            "incompleteread", "errno 10054", "errno 10060", "errno 104",
                                            "network is unreachable", "ssl: ")),
    ("unsupported_url", (UnsupportedError,), ("unsupported url",)),
    ("invalid_url", (), ("is not a valid url", "invalid url", "請輸入有效的網址", "no connection adapters")),
    ("video_unavailable", (UnavailableVideoError,), ("this video is unavailable", "video unavailable",
                                                     "this video has been removed", "no longer available",
                                                     "this video is not available", "video does not exist",
                                                     "http error 404", "404: not found")),
    ("download_dir_unavailable", (), ("winerror 3]", "winerror 21]", "device is not ready",
                                      "cannot find the path specified", "permission denied", "access is denied",
                                      "read-only file system", "errno 30]", "errno 13]", "winerror 5]")),
]

# 這些 Python 內建例外出現時，代表是引擎本身的程式錯誤（Flask 未處理的例外）
_INTERNAL_TYPES = (KeyError, TypeError, AttributeError, NameError, IndexError, AssertionError,
                   NotImplementedError, UnboundLocalError, ZeroDivisionError, RecursionError)
_INTERNAL_KEYWORDS = ("internal server error", "traceback (most recent call last)")

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_ERROR_PREFIX = re.compile(r"^(?:ERROR|WARNING):\s*", re.IGNORECASE)


def _clean(text: str) -> str:
    """去掉 ANSI 色碼與 ``ERROR:`` 前綴，給 ``detail`` 用（原文其餘部分保留）。"""
    return _ERROR_PREFIX.sub("", _ANSI.sub("", text)).strip()


def _exc_chain(exc: BaseException) -> list[BaseException]:
    """展開例外鏈：DownloadError.exc_info、ExtractorError.cause 與明確的 ``raise ... from``（__cause__）。

    刻意不追 ``__context__`` 與 ExtractorError.exc_info：這兩個記的是「建立例外時剛好正在處理的例外」，
    例如擷取器在 ``except TransportError`` 裡改丟「不支援的網址」，追下去就會被誤判成網路錯誤。
    """
    seen: list[BaseException] = []
    stack: list = [exc]
    while stack and len(seen) < 16:
        e = stack.pop()
        if not isinstance(e, BaseException) or any(e is s for s in seen):
            continue
        seen.append(e)
        if isinstance(e, DownloadError):
            info = getattr(e, "exc_info", None)
            if isinstance(info, tuple) and len(info) >= 2:
                stack.append(info[1])
        if isinstance(e, ExtractorError):
            stack.append(getattr(e, "cause", None))
        stack.append(e.__cause__)
    return seen


def _haystack(chain: list[BaseException]) -> str:
    parts: list[str] = []
    for e in chain:
        parts.append(e.__class__.__name__)
        parts.append(str(e))
        status = getattr(e, "status", None)
        if isinstance(e, HTTPError) and isinstance(status, int):
            parts.append(f"HTTP Error {status}")
    return _ANSI.sub("", " ".join(parts)).lower()


_ETA = re.compile(
    r"(?:begin|premieres?|start)\w*\s+in\s+(\d+)\s*(minute|min|hour|hr|day|second|sec)s?",
    re.IGNORECASE)
_ETA_ZH = {"minute": "分鐘", "min": "分鐘", "hour": "小時", "hr": "小時", "day": "天", "second": "秒", "sec": "秒"}
_ETA_EN = {"minute": "minute", "min": "minute", "hour": "hour", "hr": "hour", "day": "day",
           "second": "second", "sec": "second"}


def _live_eta(text: str, lang: str) -> str | None:
    m = _ETA.search(text)
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2).lower()
    if lang == "en":
        word = _ETA_EN[unit]
        return f"{n} {word}{'' if n == 1 else 's'}"
    return f"{n} {_ETA_ZH[unit]}"


def _location_label(location) -> str | None:
    """只顯示磁碟代號（例如 ``D:\\``）或網路磁碟的主機分享名稱，不顯示完整路徑。"""
    if not location:
        return None
    text = str(location)
    anchor = PureWindowsPath(text).anchor
    if anchor and anchor not in ("\\", "/"):
        return anchor
    return None


def _hit(keyword: str | re.Pattern, text: str) -> bool:
    return bool(keyword.search(text)) if isinstance(keyword, re.Pattern) else keyword in text


def classify(exc_or_message) -> str:
    """只回傳錯誤代碼（附錄 A）。"""
    if isinstance(exc_or_message, BaseException):
        chain = _exc_chain(exc_or_message)
    else:
        chain = []
    text = _haystack(chain) if chain else _ANSI.sub("", str(exc_or_message or "")).lower()

    for code, types, keywords in _RULES:
        if (types and any(isinstance(e, types) for e in chain)) or any(_hit(k, text) for k in keywords):
            if code == "download_dir_unavailable" and "cookie" in text:
                continue  # cookies.txt 讀不到不是儲存位置的問題；落到 unknown，原文留在 detail
            return code
    # 只看最外層：yt-dlp 內部處理過的 KeyError 等不代表引擎本身出錯
    if isinstance(exc_or_message, _INTERNAL_TYPES) or any(k in text for k in _INTERNAL_KEYWORDS):
        return "engine_internal"
    return "unknown"


def error_payload(code: str, lang: str = "zh", detail: str = "", *,
                  update_available: bool = False, location=None, eta: str | None = None) -> dict:
    """依代碼組出錯誤物件；引擎自己判斷出代碼（例如空間檢查、資料夾無法建立）時直接用這個。

    - ``update_available``：有新版 yt-dlp 可套用時，``http_403`` 的動作改成 ``update_ytdlp``。
    - ``location``：``download_dir_unavailable`` 時顯示的儲存位置（只會顯示磁碟代號）。
    - ``eta``：``live_not_started`` 時已格式化好的預計時間（通常由 ``friendly_error`` 從原文解析）。
    """
    lang = normalize_lang(lang)
    entry = _ERRORS.get(code) or _ERRORS["unknown"]
    code = code if code in _ERRORS else "unknown"
    message = entry[lang]
    if code == "live_not_started" and eta:
        message = entry[f"{lang}_eta"].format(eta=eta.strip())
    elif code == "download_dir_unavailable":
        loc = _location_label(location)
        if loc:
            message = entry[f"{lang}_loc"].format(loc=loc)
    action = entry["action"]
    if code == "http_403" and update_available:
        action = "update_ytdlp"
    return {"code": code, "message": message, "detail": detail, "action": action, "faq": entry["faq"]}


def friendly_error(exc_or_message, lang: str = "zh", *, update_available: bool = False, location=None) -> dict:
    """把例外或錯誤原文翻成 ``{"code", "message", "detail", "action", "faq"}``。

    ``exc_or_message`` 可以是例外（會用 isinstance 判斷 yt-dlp 例外類別，並展開 ``DownloadError.exc_info``）
    或字串（只做關鍵字比對）。``detail`` 是去掉色碼與 ``ERROR:`` 前綴的原文。
    """
    lang = normalize_lang(lang)
    if isinstance(exc_or_message, BaseException):
        detail = _clean(str(exc_or_message)) or exc_or_message.__class__.__name__
        if isinstance(exc_or_message, _INTERNAL_TYPES):  # KeyError('formats') 只有 "'formats'"，補上類別名稱
            detail = f"{exc_or_message.__class__.__name__}: {detail}"
    else:
        detail = _clean(str(exc_or_message or ""))
    code = classify(exc_or_message)
    eta = None
    if code == "live_not_started":
        source = detail
        if isinstance(exc_or_message, BaseException):
            source = " ".join(str(e) for e in _exc_chain(exc_or_message))
        eta = _live_eta(source, lang)
    return error_payload(code, lang, detail, update_available=update_available, location=location, eta=eta)


# ---------------------------------------------------------------------------
# 處理階段文字
# ---------------------------------------------------------------------------

# yt-dlp 後處理步驟名稱（原本在 server.py 的 PP_NAMES）
PP_NAMES: dict[str, dict[str, str]] = {
    "Merger": {"zh": "合併影音軌", "en": "Merging video and audio"},
    "FFmpegMerger": {"zh": "合併影音軌", "en": "Merging video and audio"},
    "FFmpegExtractAudio": {"zh": "轉換音訊", "en": "Converting audio"},
    "FFmpegVideoRemuxer": {"zh": "重新封裝容器", "en": "Changing container"},
    "FFmpegVideoConvertor": {"zh": "重新編碼影片", "en": "Re-encoding video"},
    "FFmpegEmbedSubtitle": {"zh": "嵌入字幕", "en": "Embedding subtitles"},
    "FFmpegSubtitlesConvertor": {"zh": "轉換字幕", "en": "Converting subtitles"},
    "FFmpegMetadata": {"zh": "寫入中繼資料", "en": "Writing metadata"},
    "EmbedThumbnail": {"zh": "嵌入封面", "en": "Embedding cover image"},
    "FFmpegThumbnailsConvertor": {"zh": "轉換縮圖", "en": "Converting thumbnails"},
    "SponsorBlock": {"zh": "查詢 SponsorBlock", "en": "Checking SponsorBlock"},
    "ModifyChapters": {"zh": "移除片段", "en": "Removing segments"},
    "FFmpegSplitChapters": {"zh": "依章節切割", "en": "Splitting by chapter"},
    "MoveFiles": {"zh": "整理檔案", "en": "Organizing files"},
    "FFmpegFixupM3u8": {"zh": "修正串流", "en": "Fixing stream"},
    "FFmpegFixupM4a": {"zh": "修正 M4A", "en": "Fixing M4A"},
}

_STAGES: dict[str, dict[str, str]] = {
    "queued": {"zh": "排隊中", "en": "Queued"},
    "preparing": {"zh": "準備中", "en": "Preparing"},
    "downloading": {"zh": "下載中", "en": "Downloading"},
    "downloading_format": {"zh": "下載中 {format_id}", "en": "Downloading {format_id}"},
    "download_finished": {"zh": "下載完成，處理中", "en": "Downloaded, processing"},
    "reconnecting": {"zh": "重新連線中（{attempt}/{max}）", "en": "Reconnecting ({attempt}/{max})"},
    "postprocessing": {"zh": "後處理", "en": "Processing"},
    "merging": {"zh": "合併影音軌", "en": "Merging video and audio"},
    "writing_metadata": {"zh": "寫入中繼資料", "en": "Writing metadata"},
    "done": {"zh": "完成", "en": "Done"},
    "done_with_warnings": {"zh": "完成（有警告）", "en": "Done (with warnings)"},
    "paused": {"zh": "已暫停", "en": "Paused"},
    "cancelled": {"zh": "已取消", "en": "Cancelled"},
    "failed": {"zh": "失敗", "en": "Failed"},
    "interrupted": {"zh": "已中斷", "en": "Interrupted"},
    "disk_full": {"zh": "磁碟空間不足", "en": "Disk full"},
    "config_error": {"zh": "設定錯誤", "en": "Settings error"},
    "waiting_network": {"zh": "網路中斷，{s} 秒後重試（{attempt}/{max}）",
                        "en": "Connection lost, retrying in {s} s ({attempt}/{max})"},
    "done_partial": {"zh": "完成 {done}/{total}", "en": "Done {done}/{total}"},
    "pausing": {"zh": "暫停中…", "en": "Pausing…"},
    "download_dir_unavailable": {"zh": "儲存位置無法存取", "en": "Download location unavailable"},
}

# 有參數的階段缺參數時顯示的文字（不能把 {done} 之類的佔位符露出來，也不能和別的階段撞字）
_STAGE_BARE: dict[str, dict[str, str]] = {
    "downloading_format": {"zh": "下載中", "en": "Downloading"},
    "reconnecting": {"zh": "重新連線中", "en": "Reconnecting"},
    "waiting_network": {"zh": "網路中斷，等待重試", "en": "Connection lost, waiting to retry"},
    "done_partial": {"zh": "部分完成", "en": "Partly done"},
}

STAGE_CODES: tuple[str, ...] = tuple(_STAGES)


def pp_label(name: str | None, lang: str = "zh") -> str:
    """yt-dlp 回報的後處理名稱有時沒有 FFmpeg 前綴（例如 VideoRemuxer），兩種都查；查不到就回傳原名。"""
    lang = normalize_lang(lang)
    if not name:
        return _STAGES["postprocessing"][lang]
    entry = PP_NAMES.get(name) or PP_NAMES.get(f"FFmpeg{name}")
    return entry[lang] if entry else name


def stage_text(stage_code: str, lang: str = "zh", **params) -> str:
    """處理階段文字。

    - ``downloading``：可帶 ``format_id``（例如 ``"137"``），有值時顯示「下載中 137」。
    - ``reconnecting``：需要 ``attempt`` 與 ``max``（例如 1、3 → 「重新連線中（1/3）」）。
    - ``waiting_network``：需要 ``s``（秒）、``attempt``、``max``。
    - ``done_partial``：需要 ``done``、``total``（例如 3、5 → 「完成 3/5」）。
    - ``postprocessing``：可帶 ``name``（yt-dlp 的後處理名稱，例如 ``"Merger"``），會換成中英文步驟名稱。
    - 缺參數時顯示不含數字的文字（``_STAGE_BARE``）；不認得的代碼原樣回傳。
    """
    lang = normalize_lang(lang)
    if stage_code == "postprocessing":
        return pp_label(params.get("name"), lang)
    if stage_code == "downloading" and params.get("format_id"):
        stage_code = "downloading_format"
    entry = _STAGES.get(stage_code)
    if entry is None:
        return stage_code
    template = entry[lang]
    try:
        return template.format(**params)
    except (KeyError, IndexError, ValueError):
        return _STAGE_BARE[stage_code][lang]
