"""native_common.py（主題、格式化工具、Api、共用元件、設定與免責聲明）的行為測試；用 offscreen 平台，不需要螢幕。"""
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", "C:/Windows/Fonts" if os.name == "nt" else "")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QCoreApplication, QElapsedTimer, QSettings, Qt
from PySide6.QtGui import QColor

import native_app as na
import native_common as nc
import native_options
import server


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    # 介面會存 QSettings：測試寫到暫存的 ini 檔，不要動到這台電腦的真實設定
    ini = str(tmp_path_factory.mktemp("qsettings") / "native.ini")
    native_options.QSettings = nc.QSettings = lambda *a, **k: QSettings(ini, QSettings.IniFormat)
    a, _ = na.create_app()
    return a


def wait_until(cond, ms=3000):
    t = QElapsedTimer()
    t.start()
    while not cond() and t.elapsed() < ms:
        QCoreApplication.processEvents()
    return cond()


# --------------------------------------------------------------------------- #
#  主題、常數
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("dark", [False, True])
def test_tokens_are_valid_qcolors(app, dark):
    """主題色要讓 QColor 直接讀得懂（自己畫的元件、調色盤都用 QColor）；半透明色要保留透明度。"""
    t = nc.tokens(dark)
    assert all(QColor(v).isValid() for v in t.values()), [k for k, v in t.items() if not QColor(v).isValid()]
    assert QColor(t["sep"]).alpha() < 255


def test_constants_match_server():
    assert nc.ACTIVE == server.ACTIVE
    assert {k for k, _ in nc.CONTAINERS} <= set(server.VIDEO_CONTAINERS)
    assert {k for k, _ in nc.AUDIO_CODECS} <= set(server.AUDIO_CODECS) | {"best"}
    assert [k for k, _ in native_options.SPONSOR] == list(server.SPONSOR_CATS)
    assert [k for k, _ in native_options.BROWSERS] == list(server.BROWSERS)
    assert {k for k, _ in native_options.SUB_FORMATS} - {"best"} == set(server.SUB_FORMATS)
    assert {k for k, _ in native_options.THUMB_FORMATS} == set(server.THUMB_FORMATS)


def test_newer_compares_versions_numerically():
    assert not nc.newer("2026.9.5", "2026.09.05")  # PyPI 會把 09 寫成 9
    assert nc.newer("2026.10.26", "2026.09.05")
    assert not nc.newer(None, "2026.09.05")
    assert not nc.newer("2026.09.05", "2026.10.26")


# --------------------------------------------------------------------------- #
#  Api
# --------------------------------------------------------------------------- #
class FakeEngine:
    """本機的假服務：依路徑回應 (狀態碼, Content-Type, 內容)，並記下收到的 Accept-Language。"""

    def __init__(self, routes):
        engine = self
        self.headers = []

        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                engine.headers.append(self.headers.get("Accept-Language"))
                status, ctype, body = routes.get(self.path, (404, "text/html", b"<html>404</html>"))
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        self.srv = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}"


@pytest.fixture
def engine():
    made = []

    def make(routes):
        made.append(FakeEngine(routes))
        return made[-1]
    yield make
    for e in made:
        e.srv.shutdown()


def call(base: str, path: str, ms: int = 3000) -> dict:
    """用真的 Api 送一個 GET，回傳 {"ok": payload} 或 {"err": 訊息}。"""
    import shiboken6
    from PySide6.QtCore import QEvent, QObject
    owner = QObject()  # 和 App 一樣把網路元件掛在一個父物件下，測試結束就釋放
    api = nc.Api(base, owner)
    got = {}
    try:
        api.get(path, lambda p: got.setdefault("ok", p), lambda m: got.setdefault("err", m))
        assert wait_until(lambda: got, ms)
        return got
    finally:
        # 不能留到程序結束才讓 Python 回收：macOS 上 QNetworkAccessManager 在 QApplication 之後才被刪會當掉
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        shiboken6.delete(owner)


def test_api_non_json_reply_does_not_blame_the_port(app, engine):
    """ERR7：引擎回了不是 JSON 的內容（當掉時的錯誤頁）不再說「連接埠被佔用」。"""
    e = engine({"/api/meta": (200, "text/html", b"<html>not the engine</html>"),
                "/api/jobs": (500, "text/html", b"<html>Internal Server Error</html>")})
    for path in ("/api/meta", "/api/jobs"):
        got = call(e.url, path)
        assert got["err"] == nc.NOT_JSON and "連接埠" not in got["err"]


def test_api_sends_accept_language_and_passes_error_payload(app, engine, monkeypatch):
    import json
    payload = {"error": "儲存位置（Z:）目前無法存取", "error_code": "download_dir_unavailable",
               "error_detail": "Z:\\yt: 找不到", "error_action": "open_storage_settings", "error_faq": "err-storage"}
    e = engine({"/api/download": (503, "application/json", json.dumps(payload).encode())})
    got = call(e.url, "/api/download")
    err = got["err"]
    assert isinstance(err, str) and err == payload["error"]  # 舊的呼叫者照樣當字串用
    assert isinstance(err, nc.ApiError) and err.payload == payload and err.code == "download_dir_unavailable"
    assert err.status == 503
    assert e.headers[-1] == "zh-TW"
    monkeypatch.setattr(nc.i18n, "current_language", lambda: "en")
    call(e.url, "/api/download")
    assert e.headers[-1] == "en"


def test_api_connection_refused_is_friendly(app):
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()  # 這個連接埠現在沒有程式在聽
    got = call(f"http://127.0.0.1:{port}", "/api/meta", 15_000)  # Windows 會重試連線幾秒
    assert got["err"] == "下載引擎沒有在執行" and got["err"].payload == {}


def test_api_error_keeps_str_behaviour():
    e = nc.ApiError("x", {"error": "x", "error_code": "c"}, 400)
    assert e == "x" and f"失敗：{e}" == "失敗：x" and e.code == "c"
    assert nc.ApiError("y").payload == {} and nc.ApiError("y").code == ""


# --------------------------------------------------------------------------- #
#  翻譯、共用元件
# --------------------------------------------------------------------------- #
def test_module_constants_are_translated_when_shown(app):
    """MODES、THEMES 等常數在 import 時只標記，Segmented／PopUp 建立時才翻譯（英文介面才不會殘留中文）。"""
    from PySide6.QtCore import QTranslator

    class En(QTranslator):
        def translate(self, ctx, src, disamb=None, n=-1):
            # 回傳 None 表示沒有翻譯（回傳空字串的話 Qt 會當成翻譯成空白）
            return {"影片＋音訊": "Video + audio", "最佳": "Best", "跟隨系統": "System"}.get(src) \
                if ctx == "native_common" else None

    tr = En()
    QCoreApplication.installTranslator(tr)
    try:
        seg = nc.Segmented(nc.MODES)
        assert seg.buttons["av"].text() == "Video + audio"
        pop = nc.PopUp(nc.AUDIO_QUALITY)
        assert pop.itemText(0) == "Best" and pop.itemText(1) == "320 kbps"
        assert nc.Segmented([("x", "別的模組已翻譯的字")]).buttons["x"].text() == "別的模組已翻譯的字"
    finally:
        QCoreApplication.removeTranslator(tr)
    assert nc.Segmented(nc.THEMES).buttons["system"].text() == "跟隨系統"


def test_fmt_eta_uses_translatable_text():
    assert nc.fmt_eta(None) == ""
    assert nc.fmt_eta(5) == "剩 5 秒"
    assert nc.fmt_eta(125) == "剩 2 分 5 秒"
    assert nc.fmt_eta(3725) == "剩 1 小時 2 分"


def test_app_title_and_file_manager(app):
    assert nc.app_title() == "YT 下載器"
    assert nc.file_manager() in ("Finder", "檔案總管")


def test_banner_title_body_actions_and_copy(app):
    from PySide6.QtGui import QGuiApplication
    b = nc.Banner()
    seen = []
    b.show_message("說明", "標題", error=True, actions=[("重試", lambda: seen.append(1))], copyable=True,
                   closable=False)
    assert b.text() == "標題\n說明" and b.property("error") is True and b.title.property("error") is True
    assert b.close_btn.isHidden() and not b.copy_btn.isHidden()
    b.action_buttons[0].click()
    assert seen == [1] and not b.isHidden()  # 不是 toast：按了不會關
    b.copy()
    assert QGuiApplication.clipboard().text() == "標題\n說明"
    b.show_message("只有說明")
    assert b.title.isHidden() and b.action_buttons == [] and b.property("error") is False


def test_page_scroll_does_not_take_tab_focus(app):
    from PySide6.QtWidgets import QWidget
    assert nc.page_scroll(QWidget()).focusPolicy() == Qt.NoFocus


# --------------------------------------------------------------------------- #
#  Card
# --------------------------------------------------------------------------- #
def test_card_separators_only_between_visible_rows(app):
    from PySide6.QtWidgets import QLabel
    card = nc.Card()
    rows = [card.add(QLabel(str(i))) for i in range(4)]
    lines = card._lines
    assert [lines[r].isHidden() for r in rows] == [True, False, False, False]
    card.set_row_visible(rows[0], False)  # 第一列隱藏：第二列上面不能有線
    card.set_row_visible(rows[2], False)
    assert [lines[r].isHidden() for r in rows] == [True, True, True, False]
    card.set_rows([rows[3], rows[1]])  # 重排並刪掉其他列
    assert card.rows == [rows[3], rows[1]] and set(card._lines) == {rows[3], rows[1]}
    assert [lines[r].isHidden() for r in card.rows] == [True, False]


# --------------------------------------------------------------------------- #
#  自動貼上剪貼簿裡的影片連結
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("text,ok", [
    ("https://www.youtube.com/watch?v=jNQXAC9IVRw", True),
    ("  https://youtu.be/jNQXAC9IVRw  ", True),
    ("https://www.bilibili.com/video/BV1xx411c7mD", True),
    ("https://vimeo.com/76979871", True),
    ("https://example.com/files/clip.mp4", True),       # 直接指向影音檔
    ("https://www.google.com/search?q=youtube", False),  # 一般網頁
    ("https://github.com/yt-dlp/yt-dlp", False),
    ("看這個 https://youtu.be/jNQXAC9IVRw", False),      # 不是單純的網址
    ("https://youtu.be/a\nhttps://youtu.be/b", False),
    ("ftp://example.com/a.mp4", False),
    ("", False),
])
def test_is_supported_url(text, ok):
    assert nc.is_supported_url(text) is ok


def test_clipboard_watcher_finds_supported_link_in_background(app):
    w = nc.ClipboardWatcher()
    found = []
    w.found.connect(found.append)
    w.check("https://youtu.be/jNQXAC9IVRw")
    w.check("https://www.google.com/")
    assert wait_until(lambda: found, 10_000)
    assert found == ["https://youtu.be/jNQXAC9IVRw"]


def test_app_version_falls_back_when_file_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(nc, "BUNDLE", tmp_path)
    assert nc.app_version() == "開發版"
