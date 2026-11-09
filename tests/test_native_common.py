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

from PySide6.QtCore import QCoreApplication, QElapsedTimer, QSettings
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
@pytest.fixture
def html_server():
    """一個不是引擎的本機服務：所有網址都回 200 的 HTML。"""
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<html>not the engine</html>")

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def test_api_treats_non_json_reply_as_error(app, html_server):
    import shiboken6
    from PySide6.QtCore import QEvent, QObject
    owner = QObject()  # 和 App 一樣把網路元件掛在一個父物件下，測試結束就釋放
    api = nc.Api(html_server, owner)
    got = {}
    try:
        api.get("/api/meta", lambda p: got.setdefault("ok", p), lambda m: got.setdefault("err", m))
        assert wait_until(lambda: got)
        assert got == {"err": nc.NOT_ENGINE}
    finally:
        # 不能留到程序結束才讓 Python 回收：macOS 上 QNetworkAccessManager 在 QApplication 之後才被刪會當掉
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        shiboken6.delete(owner)


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
