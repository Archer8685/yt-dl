"""engine_messages：錯誤原文要分到正確代碼、訊息中英文都要有、訊息裡不能露出原文的危險內容。"""
import re
import sys
import traceback

import pytest
from yt_dlp.networking.exceptions import ProxyError, TransportError
from yt_dlp.utils import (
    DownloadError,
    ExtractorError,
    GeoRestrictedError,
    PostProcessingError,
    UnsupportedError,
)

import engine_messages as em
from engine_messages import ERROR_CODES, STAGE_CODES, error_payload, friendly_error, stage_text


def _wrapped(inner: BaseException) -> DownloadError:
    """模擬 YoutubeDL.extract_info / download 把內層例外包成 DownloadError 的樣子。"""
    try:
        raise inner
    except BaseException:  # noqa: BLE001
        info = sys.exc_info()
    msg = f"ERROR: {inner}"
    return DownloadError(msg, info)


# 每個代碼至少兩個真實原文（實測或取自 yt-dlp 原始碼，見 ux-audit-engine.md 第 3-2 節）。
SAMPLES: dict[str, list] = {
    "invalid_url": [
        "請輸入有效的網址（http/https）",
        ("ERROR: 'abc' is not a valid URL. Set --default-search \"ytsearch\" (or run  yt-dlp \"ytsearch:abc\" ) "
        "to search YouTube"),
        "Invalid URL 'htp//x': No scheme supplied",
    ],
    "unsupported_url": [
        "ERROR: Unsupported URL: https://example.com/",
        _wrapped(UnsupportedError("https://www.google.com/")),
        UnsupportedError("https://example.org/page"),
    ],
    "video_unavailable": [
        "ERROR: [youtube] aaaaaaaaaaa: This video is unavailable",
        "ERROR: [youtube] dQw4w9WgXcZ: Video unavailable. This video is not available",
        "ERROR: [youtube] abcdefghijk: Video unavailable. This video has been removed by the uploader",
    ],
    "private_video": [
        ("ERROR: [youtube] abcdefghijk: Private video. Sign in if you've been granted access to this video. "
        "Use --cookies-from-browser or --cookies for the authentication. See  "
        "https://github.com/yt-dlp/yt-dlp/wiki/FAQ#how-do-i-pass-cookies-to-yt-dlp  for how to manually pass "
        "cookies. Also see  https://github.com/yt-dlp/yt-dlp/wiki/Extractors#exporting-youtube-cookies  for tips"),
        _wrapped(ExtractorError("[iwara] abc: Private video. Login if you have permissions to watch", expected=True)),
    ],
    "age_restricted": [
        ("ERROR: [youtube] abcdefghijk: Sign in to confirm your age. This video may be inappropriate for some "
        "users. Use --cookies-from-browser or --cookies for the authentication. See  "
        "https://github.com/yt-dlp/yt-dlp/wiki/FAQ#how-do-i-pass-cookies-to-yt-dlp  for how to manually pass "
        "cookies."),
        "ERROR: [youtube] abcdefghijk: This video is age-restricted and only available on YouTube.",
    ],
    "members_only": [
        ("ERROR: [youtube] abcdefghijk: Join this channel to get access to members-only content like this video, "
        "and other exclusive perks."),
        ("ERROR: [youtube] abcdefghijk: This video is available to this channel's members on level: Supporter "
        "(or any higher level). Join this channel to get access to members-only content and other exclusive perks."),
    ],
    "geo_blocked": [
        ("ERROR: [youtube] abcdefghijk: Video unavailable. The uploader has not made this video available in "
        "your country"),
        GeoRestrictedError("This video is not available from your location due to geo restriction",
                           countries=["US"]),
        _wrapped(GeoRestrictedError("This video is not available in your country due to licensing restrictions")),
    ],
    "bot_check": [
        ("ERROR: [youtube] abcdefghijk: Sign in to confirm you're not a bot. Use --cookies-from-browser or "
        "--cookies for the authentication. See  https://github.com/yt-dlp/yt-dlp/wiki/FAQ  for how to manually "
        "pass cookies."),
        ("ERROR: [youtube] abcdefghijk: Sign in to confirm you’re not a bot. This helps protect our community. "
        "Learn more"),
    ],
    "live_not_started": [
        "ERROR: [youtube] abcdefghijk: This live event will begin in 30 minutes.",
        "ERROR: [youtube] abcdefghijk: Premieres in 2 hours",
        "ERROR: [youtube] abcdefghijk: This live event will begin in a few moments.",
    ],
    "http_403": [
        "ERROR: unable to download video data: HTTP Error 403: Forbidden",
        "ERROR: [download] Got error: HTTP Error 403: Forbidden. Giving up after 10 retries",
    ],
    "rate_limited": [
        ("ERROR: [youtube] abcdefghijk: Unable to download API page: HTTP Error 429: Too Many Requests "
        "(caused by <HTTPError 429: Too Many Requests>)"),
        "ERROR: unable to download video data: HTTP Error 429: Too Many Requests",
    ],
    "format_unavailable": [
        ("ERROR: [youtube] abcdefghijk: Requested format is not available. Use --list-formats for a list of "
        "available formats"),
        _wrapped(ExtractorError("Requested format is not available. Use --list-formats for a list of available "
                                "formats", expected=True)),
    ],
    "ffmpeg_failed": [
        "ERROR: Postprocessing: Conversion failed!",
        "ERROR: Postprocessing: ffmpeg exited with code 1",
        PostProcessingError("Conversion failed!"),
    ],
    "ffmpeg_missing": [
        ("ERROR: You have requested merging of multiple formats but ffmpeg is not installed. Aborting due to "
        "--abort-on-error"),
        ("ERROR: Postprocessing: ffprobe and ffmpeg not found. Please install or provide the path using "
        "--ffmpeg-location"),
        "ERROR: You have requested downloading the video partially, but ffmpeg is not installed. Aborting",
    ],
    "server_error": [
        ("ERROR: [youtube] abcdefghijk: Unable to download API page: HTTP Error 503: Service Unavailable "
        "(caused by <HTTPError 503: Service Unavailable>)"),
        "ERROR: unable to download video data: HTTP Error 502: Bad Gateway",
        ("ERROR: [generic] Unable to download webpage: HTTP Error 500: Internal Server Error "
        "(caused by <HTTPError 500: Internal Server Error>)"),
    ],
    "network_dns": [
        ("ERROR: [youtube] abcdefghijk: Unable to download webpage: HTTPSConnection(host='www.youtube.com', "
        "port=443): Failed to resolve 'www.youtube.com' ([Errno 11001] getaddrinfo failed) "
        "(caused by TransportError(\"HTTPSConnection(host='www.youtube.com', port=443): Failed to resolve "
        "'www.youtube.com' ([Errno 11001] getaddrinfo failed)\"))"),
        ("ERROR: [generic] Unable to download webpage: <urlopen error [Errno -2] Name or service not known> "
        "(caused by TransportError('<urlopen error [Errno -2] Name or service not known>'))"),
    ],
    "network_timeout": [
        ("ERROR: [youtube] abcdefghijk: Unable to download webpage: The read operation timed out "
        "(caused by TransportError('The read operation timed out'))"),
        ("ERROR: unable to download video data: ('Connection aborted.', ConnectionResetError(10054, "
        "'An existing connection was forcibly closed by the remote host', None, 10054, None))"),
        _wrapped(TransportError("Read timed out.")),
    ],
    "proxy_error": [
        ("ERROR: [youtube] abcdefghijk: Unable to download webpage: ('Unable to connect to proxy', "
        "ConnectTimeoutError(<urllib3.connection.HTTPSConnection object at 0x0000021F>, 'Connection to 10.0.0.1 "
        "timed out. (connect timeout=20.0)')) (caused by ProxyError(\"('Unable to connect to proxy', "
        "ConnectTimeoutError(...))\")); please report this issue on  https://github.com/yt-dlp/yt-dlp/issues"
        "?q= , filling out the appropriate issue template. Confirm you are on the latest version using  yt-dlp -U"),
        _wrapped(ProxyError("Tunnel connection failed: 407 Proxy Authentication Required")),
    ],
    "cookie_browser_locked": [
        ("ERROR: Could not copy Chrome cookie database. See  https://github.com/yt-dlp/yt-dlp/issues/7271  "
        "for more info"),
        "ERROR: Failed to decrypt with DPAPI. See  https://github.com/yt-dlp/yt-dlp/issues/10927  for more info",
        "ERROR: could not find edge cookies database in \"C:\\Users\\someone\\AppData\\Local\\Microsoft\\Edge\"",
    ],
    "cookies_invalid": [
        "ERROR: 'C:\\Users\\someone\\cookies.txt' does not look like a Netscape format cookies file",
        ("ERROR: Cookies file must be Netscape formatted, not JSON. See  "
        "https://github.com/yt-dlp/yt-dlp/wiki/FAQ#how-do-i-pass-cookies-to-yt-dlp"),
    ],
    "disk_full": [
        "ERROR: unable to write data: [Errno 28] No space left on device",
        OSError(28, "No space left on device"),
        "ERROR: unable to write data: [Errno 28] There is not enough space on the disk",
    ],
    "download_dir_unavailable": [
        FileNotFoundError(3, "The system cannot find the path specified", "D:\\yt-dl\\abc"),
        "[WinError 21] The device is not ready: 'E:\\'",
        PermissionError(13, "Permission denied", "/Volumes/USB/yt-dl"),
    ],
    "engine_internal": [
        KeyError("formats"),
        TypeError("'NoneType' object is not subscriptable"),
        "500 Internal Server Error: The server encountered an internal error",
    ],
    "unknown": [
        "ERROR: [youtube] abcdefghijk: Something completely unexpected happened",
        RuntimeError("下載失敗，請查看紀錄"),
        "",
    ],
}

_CASES = [(code, s) for code, samples in SAMPLES.items() for s in samples]

FORBIDDEN = ("--", "github.com", "please report", "http://", "https://", "yt-dlp -u", "\\users\\", "/users/",
             "c:\\", "d:\\yt-dl", "/volumes/", "proxy" + "error", "traceback", "errno")


def _assert_clean(text: str):
    low = text.lower()
    for bad in FORBIDDEN:
        assert bad not in low, f"訊息不能含 {bad!r}：{text}"
    assert not re.search(r"[A-Za-z]:\\[^\s]+\\", text), f"訊息不能含本機路徑：{text}"


def test_every_code_has_at_least_two_samples():
    assert set(SAMPLES) == set(ERROR_CODES)
    for code, samples in SAMPLES.items():
        assert len(samples) >= 2, code


@pytest.mark.parametrize("code,sample", _CASES, ids=[f"{c}-{i}" for i, (c, _) in enumerate(_CASES)])
@pytest.mark.parametrize("lang", ["zh", "en"])
def test_sample_classified(code, sample, lang):
    out = friendly_error(sample, lang)
    assert out["code"] == code, f"{sample!r} → {out['code']}"
    assert set(out) == {"code", "message", "detail", "action", "faq"}
    assert out["message"]
    _assert_clean(out["message"])
    assert out["faq"].startswith("err-")


@pytest.mark.parametrize("code,sample", _CASES, ids=[f"{c}-{i}" for i, (c, _) in enumerate(_CASES)])
def test_detail_keeps_original_without_prefix(code, sample):
    out = friendly_error(sample)
    raw = str(sample)
    if isinstance(sample, (KeyError, TypeError)):  # 引擎內部錯誤：補上類別名稱
        assert out["detail"] == f"{sample.__class__.__name__}: {raw}"
    elif raw.startswith("ERROR: "):
        assert out["detail"] == raw[len("ERROR: "):].strip()
    elif raw:
        assert out["detail"] == raw.strip()
    elif isinstance(sample, BaseException):
        assert out["detail"] == sample.__class__.__name__


def test_language_selection():
    assert em.normalize_lang("en-US") == "en"
    assert em.normalize_lang("EN_gb") == "en"
    assert em.normalize_lang("zh_TW") == "zh"
    assert em.normalize_lang(None) == "zh"
    assert em.normalize_lang("ja") == "zh"
    zh = friendly_error("ERROR: Unsupported URL: https://example.com/")["message"]
    en = friendly_error("ERROR: Unsupported URL: https://example.com/", "en-US")["message"]
    assert zh != en
    assert re.search(r"[\u4e00-\u9fff]", zh)
    assert not re.search(r"[\u4e00-\u9fff]", en)


@pytest.mark.parametrize("code", ERROR_CODES)
@pytest.mark.parametrize("lang", ["zh", "en"])
def test_every_code_has_text_in_both_languages(code, lang):
    out = error_payload(code, lang, detail="raw")
    assert out["code"] == code
    assert out["detail"] == "raw"
    assert out["message"].strip()
    _assert_clean(out["message"])
    has_cjk = bool(re.search(r"[\u4e00-\u9fff]", out["message"]))
    assert has_cjk == (lang == "zh"), out["message"]


def test_appendix_a_actions_and_anchors():
    expected = {
        "invalid_url": (None, "err-invalid-url"),
        "unsupported_url": (None, "err-unsupported-url"),
        "video_unavailable": (None, "err-video-unavailable"),
        "private_video": ("open_cookie_settings", "err-private-video"),
        "age_restricted": ("open_cookie_settings", "err-age-restricted"),
        "members_only": ("open_cookie_settings", "err-members-only"),
        "geo_blocked": (None, "err-geo-blocked"),
        "bot_check": ("open_cookie_settings", "err-bot-check"),
        "live_not_started": (None, "err-live-not-started"),
        "http_403": ("resume", "err-http-403"),
        "rate_limited": ("retry", "err-rate-limited"),
        "format_unavailable": ("reanalyze", "err-format-unavailable"),
        "ffmpeg_failed": (None, "err-ffmpeg-failed"),
        "ffmpeg_missing": (None, "err-ffmpeg-missing"),
        "server_error": ("retry", "err-network"),
        "network_dns": ("retry", "err-network"),
        "network_timeout": ("retry", "err-network"),
        "proxy_error": ("open_network_settings", "err-proxy"),
        "cookie_browser_locked": ("open_cookie_settings", "err-cookie-browser"),
        "cookies_invalid": ("open_cookie_settings", "err-cookies-invalid"),
        "disk_full": ("open_storage_settings", "err-disk-full"),
        "download_dir_unavailable": ("open_storage_settings", "err-download-dir"),
        "engine_internal": ("retry", "err-engine"),
        "unknown": ("retry", "err-unknown"),
    }
    assert set(expected) == set(ERROR_CODES)
    allowed = {"open_cookie_settings", "open_storage_settings", "open_network_settings", "reanalyze", "resume",
               "update_ytdlp", "retry", None}
    for code, (action, faq) in expected.items():
        out = error_payload(code)
        assert (out["action"], out["faq"]) == (action, faq), code
        assert out["action"] in allowed


def test_http_403_suggests_update_when_available():
    sample = "ERROR: unable to download video data: HTTP Error 403: Forbidden"
    assert friendly_error(sample)["action"] == "resume"
    assert friendly_error(sample, update_available=True)["action"] == "update_ytdlp"
    # 其他代碼不受影響
    assert friendly_error("HTTP Error 429: Too Many Requests", update_available=True)["action"] == "retry"


@pytest.mark.parametrize("lang", ["zh", "en"])
def test_geo_blocked_never_suggests_circumvention(lang):
    for sample in SAMPLES["geo_blocked"]:
        msg = friendly_error(sample, lang)["message"].lower()
        for word in ("proxy", "vpn", "代理", "地區設定", "region setting", "bypass", "繞過", "規避"):
            assert word not in msg, msg
    assert friendly_error(SAMPLES["geo_blocked"][0], lang)["action"] is None


def test_live_not_started_includes_eta():
    zh = friendly_error("ERROR: [youtube] x: This live event will begin in 30 minutes.")["message"]
    assert "30 分鐘" in zh
    en = friendly_error("ERROR: [youtube] x: Premieres in 2 hours", "en")["message"]
    assert "2 hours" in en
    en1 = friendly_error("This live event will begin in 1 minute.", "en")["message"]
    assert "1 minute)" in en1
    nofix = friendly_error("This live event will begin in a few moments.")["message"]
    assert "預計" not in nofix


def test_download_dir_shows_only_drive():
    out = friendly_error(FileNotFoundError(3, "The system cannot find the path specified", "D:\\yt-dl\\abc"),
                         location="D:\\yt-dl\\videos")
    assert "D:\\" in out["message"]
    assert "yt-dl" not in out["message"]
    # 非 Windows 路徑沒有磁碟代號時不顯示位置
    out = friendly_error(PermissionError(13, "Permission denied"), "en", location="/Volumes/USB/yt-dl")
    assert "/Volumes" not in out["message"]
    _assert_clean(out["message"])


def test_isinstance_beats_keywords_through_download_error():
    """DownloadError 的字串只有外層訊息時，仍要靠 exc_info 裡的例外類別判斷。"""
    inner = GeoRestrictedError("blocked")
    outer = DownloadError("ERROR: blocked", (type(inner), inner, None))
    assert friendly_error(outer)["code"] == "geo_blocked"
    inner2 = ProxyError("boom")
    outer2 = DownloadError("ERROR: boom", (type(inner2), inner2, None))
    assert friendly_error(outer2)["code"] == "proxy_error"


def test_yt_dlp_exception_classes_resolved():
    """類別都要真的拿到，否則 isinstance 判斷會靜默失效、只剩關鍵字。"""
    for name in ("HTTPError", "ProxyError", "TransportError", "DownloadError", "ExtractorError",
                 "GeoRestrictedError", "PostProcessingError", "UnavailableVideoError", "UnsupportedError"):
        assert getattr(em, name) is not em._Missing, name


def test_isinstance_without_keywords():
    assert friendly_error(GeoRestrictedError("blocked"))["code"] == "geo_blocked"
    assert friendly_error(UnsupportedError("x"))["code"] == "unsupported_url"
    assert friendly_error(PostProcessingError("oops"))["code"] == "ffmpeg_failed"
    assert friendly_error(_wrapped(ProxyError("boom")))["code"] == "proxy_error"
    assert friendly_error(_wrapped(TransportError("boom")))["code"] == "network_timeout"


def test_cause_chain_is_followed():
    try:
        try:
            raise TransportError("socket failure")
        except TransportError as e:
            raise RuntimeError("wrapper") from e
    except RuntimeError as e:
        assert friendly_error(e)["code"] == "network_timeout"
        traceback.clear_frames(e.__traceback__)


def test_exception_being_handled_does_not_leak_into_classification():
    """ExtractorError 會記下建立時正在處理的例外（exc_info），那不是錯誤原因，不能拿來判斷。"""
    try:
        raise TransportError("probe failed")
    except TransportError:
        unsupported = UnsupportedError("https://example.com/")
        removed = ExtractorError("[x] abc: something odd happened", expected=True)
    assert friendly_error(unsupported)["code"] == "unsupported_url"
    assert friendly_error(_wrapped(unsupported))["code"] == "unsupported_url"
    assert friendly_error(removed)["code"] == "unknown"
    try:
        raise KeyError("x")
    except KeyError:
        inner = ExtractorError("[x] abc: Unable to extract title", expected=False)
    assert friendly_error(_wrapped(inner))["code"] == "unknown"


def test_extractor_error_cause_is_followed():
    err = ExtractorError("Unable to download webpage", cause=TransportError("boom"))
    assert friendly_error(err)["code"] == "network_timeout"


def test_cookies_file_permission_is_not_storage_problem():
    out = friendly_error("ERROR: [Errno 13] Permission denied: 'C:\\Users\\someone\\cookies.txt'")
    assert out["code"] == "unknown"
    assert out["action"] != "open_storage_settings"


def test_internal_error_detail_has_type():
    assert friendly_error(KeyError("formats"))["detail"] == "KeyError: 'formats'"


def test_live_eta_spacing_consistent():
    direct = error_payload("live_not_started", "zh", eta="30 分鐘")["message"]
    parsed = friendly_error("This live event will begin in 30 minutes.")["message"]
    assert direct == parsed == "直播還沒開始（預計 30 分鐘後），開播後再下載"
    en = error_payload("live_not_started", "en", eta=" 2 hours ")["message"]
    assert "(expected in 2 hours)" in en


def test_ansi_and_prefix_removed_from_detail():
    out = friendly_error("\x1b[0;31mERROR:\x1b[0m [youtube] x: This video is unavailable")
    assert out["code"] == "video_unavailable"
    assert out["detail"] == "[youtube] x: This video is unavailable"


def test_unknown_code_payload_falls_back():
    out = error_payload("no_such_code", "en")
    assert out["code"] == "unknown"
    assert out["faq"] == "err-unknown"


# ---------------------------------------------------------------------------
# 處理階段文字
# ---------------------------------------------------------------------------

STAGE_PARAMS = {"reconnecting": {"attempt": 1, "max": 3}, "downloading_format": {"format_id": "137"},
                "waiting_network": {"s": 10, "attempt": 1, "max": 5}, "done_partial": {"done": 3, "total": 5}}


def test_new_stages_text():
    assert stage_text("waiting_network", s=10, attempt=2, max=5) == "網路中斷，10 秒後重試（2/5）"
    assert stage_text("waiting_network", "en", s=10, attempt=2, max=5) == "Connection lost, retrying in 10 s (2/5)"
    assert stage_text("done_partial", done=3, total=5) == "完成 3/5"
    assert stage_text("done_partial", "en", done=3, total=5) == "Done 3/5"
    assert stage_text("pausing") == "暫停中…"
    assert stage_text("pausing", "en") == "Pausing…"
    assert stage_text("download_dir_unavailable") == "儲存位置無法存取"
    assert stage_text("download_dir_unavailable", "en") == "Download location unavailable"


@pytest.mark.parametrize("code", STAGE_CODES)
@pytest.mark.parametrize("lang", ["zh", "en"])
def test_stage_without_params_never_shows_placeholder(code, lang):
    text = stage_text(code, lang)
    assert text.strip() and "{" not in text and "}" not in text


def test_bare_stage_texts_do_not_collide():
    """缺參數時的文字不能和別的階段一樣（server 用中文文字反查舊 job.json 的階段代碼）。"""
    for lang in ("zh", "en"):
        texts = [stage_text(c, lang) for c in STAGE_CODES if c != "downloading_format"]
        assert len(texts) == len(set(texts)), texts


@pytest.mark.parametrize("code", STAGE_CODES)
@pytest.mark.parametrize("lang", ["zh", "en"])
def test_every_stage_has_text_in_both_languages(code, lang):
    text = stage_text(code, lang, **STAGE_PARAMS.get(code, {}))
    assert text.strip()
    assert "{" not in text and "}" not in text
    has_cjk = bool(re.search(r"[\u4e00-\u9fff]", text))
    assert has_cjk == (lang == "zh"), text
    _assert_clean(text)


def test_stage_texts_match_current_engine_strings():
    """中文要和 server.py 現在寫死的文字一樣，E1 接線後畫面不會變。"""
    assert stage_text("queued") == "排隊中"
    assert stage_text("preparing") == "準備中"
    assert stage_text("downloading") == "下載中"
    assert stage_text("downloading", format_id="137") == "下載中 137"
    assert stage_text("download_finished") == "下載完成，處理中"
    assert stage_text("reconnecting", attempt=2, max=3) == "重新連線中（2/3）"
    assert stage_text("done") == "完成"
    assert stage_text("done_with_warnings") == "完成（有警告）"
    assert stage_text("cancelled") == "已取消"
    assert stage_text("failed") == "失敗"
    assert stage_text("interrupted") == "已中斷"
    assert stage_text("disk_full") == "磁碟空間不足"
    assert stage_text("config_error") == "設定錯誤"
    assert stage_text("paused") == "已暫停"
    assert stage_text("merging") == "合併影音軌"
    assert stage_text("writing_metadata") == "寫入中繼資料"


def test_stage_english():
    assert stage_text("reconnecting", "en", attempt=1, max=3) == "Reconnecting (1/3)"
    assert stage_text("downloading", "en-US", format_id="251") == "Downloading 251"
    assert stage_text("done_with_warnings", "en") == "Done (with warnings)"


def test_stage_missing_params_degrades_gracefully():
    assert stage_text("reconnecting") == "重新連線中"
    assert stage_text("reconnecting", "en") == "Reconnecting"


def test_unknown_stage_returned_as_is():
    assert stage_text("something_new", "en") == "something_new"


@pytest.mark.parametrize("name", list(em.PP_NAMES))
@pytest.mark.parametrize("lang", ["zh", "en"])
def test_postprocessor_names_both_languages(name, lang):
    text = stage_text("postprocessing", lang, name=name)
    assert text == em.PP_NAMES[name][lang]
    assert bool(re.search(r"[\u4e00-\u9fff]", text)) == (lang == "zh")


def test_postprocessor_lookup_like_server():
    assert em.pp_label("VideoRemuxer") == "重新封裝容器"  # 沒有 FFmpeg 前綴也查得到
    assert em.pp_label("Merger", "en") == "Merging video and audio"
    assert em.pp_label(None) == "後處理"
    assert em.pp_label("", "en") == "Processing"
    assert em.pp_label("SomethingNew") == "SomethingNew"


def test_module_does_not_import_server():
    import ast
    import pathlib

    tree = ast.parse(pathlib.Path(em.__file__).read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    assert "server" not in names


@pytest.mark.parametrize("lang", ["zh", "en"])
def test_update_text_is_bilingual_and_never_shows_placeholders(lang):
    assert em.update_text(None, lang) is None
    for code in em._UPDATE:
        assert "{" not in em.update_text(code, lang, detail="x")
        bare = em.update_text(code, lang)  # 缺參數時不能露出 {detail}
        assert bare and "{" not in bare
    assert em.update_text("failed", "en", detail="disk") == "Update failed: disk"
    assert em.update_text("failed", "zh") == "更新失敗"
    assert em.UPDATE_FAILED_CODES <= set(em._UPDATE)
