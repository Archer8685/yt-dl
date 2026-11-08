"""native_app.py（原生介面主程式）的行為測試；用 offscreen 平台，不需要螢幕。"""
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
from PySide6.QtWidgets import QMessageBox, QPushButton

import native_app as na
import native_options
import server


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    # 介面會存 QSettings：測試寫到暫存的 ini 檔，不要動到這台電腦的真實設定
    ini = str(tmp_path_factory.mktemp("qsettings") / "native.ini")
    native_options.QSettings = na.QSettings = lambda *a, **k: QSettings(ini, QSettings.IniFormat)
    a, _ = na.create_app()
    return a


def wait_until(cond, ms=3000):
    t = QElapsedTimer()
    t.start()
    while not cond() and t.elapsed() < ms:
        QCoreApplication.processEvents()
    return cond()


class FakeApi:
    """記下請求、由測試決定何時回應。"""

    def __init__(self):
        self.calls = []

    def _add(self, method, path, body, ok, err):
        self.calls.append((method, path, body, ok, err))

    def post(self, path, body=None, ok=None, err=None, timeout_ms=0):
        self._add("POST", path, body, ok, err)

    def get(self, path, ok=None, err=None, timeout_ms=0):
        self._add("GET", path, None, ok, err)

    def delete(self, path, ok=None, err=None, timeout_ms=0):
        self._add("DELETE", path, None, ok, err)

    def image(self, url, ok, timeout_ms=0):
        self._add("IMG", url, None, ok, None)

    def last(self, path):
        return [c for c in self.calls if c[1] == path][-1]


def video_info(title, vid, heights=(1080, 720)):
    return {"type": "video", "title": title, "id": vid, "webpage_url": f"https://www.youtube.com/watch?v={vid}",
            "duration": 10, "heights": list(heights), "thumbnail": f"https://i.ytimg.com/{vid}.jpg",
            "audio_tracks": [], "subtitles": [], "auto_captions": []}


# --------------------------------------------------------------------------- #
#  主題、常數
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("dark", [False, True])
def test_tokens_are_valid_qcolors(app, dark):
    """主題色要讓 QColor 直接讀得懂（自己畫的元件、調色盤都用 QColor）；半透明色要保留透明度。"""
    t = na.tokens(dark)
    assert all(QColor(v).isValid() for v in t.values()), [k for k, v in t.items() if not QColor(v).isValid()]
    assert QColor(t["sep"]).alpha() < 255


def test_constants_match_server():
    assert na.ACTIVE == server.ACTIVE
    assert {k for k, _ in na.CONTAINERS} <= set(server.VIDEO_CONTAINERS)
    assert {k for k, _ in na.AUDIO_CODECS} <= set(server.AUDIO_CODECS) | {"best"}
    assert [k for k, _ in native_options.SPONSOR] == list(server.SPONSOR_CATS)
    assert [k for k, _ in native_options.BROWSERS] == list(server.BROWSERS)
    assert {k for k, _ in native_options.SUB_FORMATS} - {"best"} == set(server.SUB_FORMATS)
    assert {k for k, _ in native_options.THUMB_FORMATS} == set(server.THUMB_FORMATS)


def test_newer_compares_versions_numerically():
    assert not na.newer("2026.9.5", "2026.09.05")  # PyPI 會把 09 寫成 9
    assert na.newer("2026.10.26", "2026.09.05")
    assert not na.newer(None, "2026.09.05")
    assert not na.newer("2026.09.05", "2026.10.26")


def test_chevron_asset_exists():
    from PySide6.QtGui import QImage
    path = na.create_app.__globals__["BUNDLE"] / "assets" / "chevron.png"
    assert path.is_file() and not QImage(str(path)).isNull()


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
    api = na.Api(html_server, owner)
    got = {}
    try:
        api.get("/api/meta", lambda p: got.setdefault("ok", p), lambda m: got.setdefault("err", m))
        assert wait_until(lambda: got)
        assert got == {"err": na.NOT_ENGINE}
    finally:
        # 不能留到程序結束才讓 Python 回收：macOS 上 QNetworkAccessManager 在 QApplication 之後才被刪會當掉
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        shiboken6.delete(owner)


# --------------------------------------------------------------------------- #
#  Card
# --------------------------------------------------------------------------- #
def test_card_separators_only_between_visible_rows(app):
    from PySide6.QtWidgets import QLabel
    card = na.Card()
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
#  新增下載
# --------------------------------------------------------------------------- #
def test_stale_info_response_is_ignored(app):
    api = FakeApi()
    page = na.DownloadPage(api, lambda *a, **k: None)
    page.url.setText("https://www.youtube.com/watch?v=AAA")
    page.analyze()
    page.url.setText("https://www.youtube.com/watch?v=BBB")
    page.analyze()  # 第一次還沒回來又按 Enter
    first, second = [c for c in api.calls if c[1] == "/api/info"]
    second[3](video_info("B", "BBB"))
    first[3](video_info("A", "AAA"))  # 較慢回來的舊結果
    assert page.info["id"] == "BBB"
    assert page.title.text() == "B"
    first[4]("逾時")  # 舊請求的錯誤也不能蓋掉畫面
    assert "逾時" not in page.status.text()
    from PySide6.QtGui import QPixmap
    pm = QPixmap(4, 4)
    pm.fill()
    thumbs = [c for c in api.calls if c[0] == "IMG"]
    assert [c[1] for c in thumbs] == ["https://i.ytimg.com/BBB.jpg"]
    page.url.setText("https://www.youtube.com/watch?v=CCC")
    page.analyze()
    thumbs[0][3](pm)  # B 的縮圖在 C 解析期間才回來
    assert page.thumb.pixmap().isNull()


def test_playlist_switch_is_sent_and_reanalyzes(app):
    api = FakeApi()
    page = na.DownloadPage(api, lambda *a, **k: None)
    page.as_playlist.setChecked(False)
    page.url.setText("https://www.bilibili.com/video/BV1xx")  # 不只 YouTube：交給 yt-dlp 依網站判斷
    page.analyze()
    assert api.last("/api/info")[2]["noplaylist"] is True
    api.last("/api/info")[3](video_info("P1", "BV1xx"))
    n = len([c for c in api.calls if c[1] == "/api/info"])
    page.as_playlist.setChecked(True)  # 解析後才切換：要用新設定重新解析
    infos = [c for c in api.calls if c[1] == "/api/info"]
    assert len(infos) == n + 1 and infos[-1][2]["noplaylist"] is False


def test_user_text_is_plain_not_html(app):
    page = na.DownloadPage(FakeApi(), lambda *a, **k: None)
    page.on_info(video_info("Top 10 <b>NEW</b> &amp; more", "x"))
    assert page.title.textFormat() == Qt.PlainText and page.title.text() == "Top 10 <b>NEW</b> &amp; more"


def test_clip_range_only_blocks_media_modes(app):
    page = na.DownloadPage(FakeApi(), lambda *a, **k: None)
    page.on_info(video_info("V", "v"))
    page.advanced.sections_edit.setText("abc")
    page.mode.set_value("av")
    page.update_rows()
    assert page.problem() and not page.download_btn.isEnabled()
    page.mode.set_value("thumb")  # 剪輯分組隱藏時，看不到的錯誤不能擋住下載
    page.update_rows()
    assert page.problem() == "" and page.download_btn.isEnabled()
    page.advanced.sections_edit.clear()


def test_download_defaults_from_settings(app, monkeypatch):
    """設定頁的「下載預設值」：存起來、立刻套用到新增下載頁，下次開啟也從這組選項開始。"""
    api = FakeApi()
    win = na.MainWindow(api, lambda: False)
    s, page = win.settings, win.download
    try:
        page.on_info(video_info("V", "v", heights=(2160, 1080, 720)))
        s.def_mode.select("audio")
        s.def_acodec.select("flac")
        s.def_quality.select(720)
        s.def_playlist.setChecked(True)
        assert page.mode.value() == "audio" and page.acodec.currentData() == "flac"  # 立刻套用
        assert page.quality.currentData() == 720 and page.as_playlist.isChecked()
        assert na.load_download_defaults()["quality"] == 720
        fresh = na.DownloadPage(FakeApi(), lambda *a, **k: None)  # 重新開啟 App
        assert fresh.mode.value() == "audio" and fresh.acodec.currentData() == "flac"
        fresh.on_info(video_info("W", "w", heights=(1080, 720)))
        assert fresh.quality.currentData() == 720
        low = na.DownloadPage(FakeApi(), lambda *a, **k: None)
        low.on_info(video_info("L", "l", heights=(480,)))  # 影片沒有預設畫質：用最佳畫質
        assert low.quality.currentData() is None
        # 在新增下載頁臨時改選，不會改到預設值
        page.mode.set_value("av")
        page.mode.changed.emit("av")
        assert na.load_download_defaults()["mode"] == "audio"
        # 恢復所有預設值（按下確認）
        monkeypatch.setattr(QMessageBox, "exec", lambda box: next(
            b for b in box.buttons() if b.text() == "恢復預設值").click())
        s.reset_all()
        assert na.load_download_defaults() == na.DOWNLOAD_DEFAULTS
        assert page.mode.value() == "av" and s.def_quality.currentData() is None
        assert na.ui_prefs() == ("system", "medium")
    finally:
        na.save_download_defaults(dict(na.DOWNLOAD_DEFAULTS))
        win.close()


# --------------------------------------------------------------------------- #
#  下載佇列
# --------------------------------------------------------------------------- #
def job(jid, status, **kw):
    return {"id": jid, "url": "u", "title": f"T{jid}", "status": status, "progress": 0, **kw}


def test_job_actions_refresh_without_type_error(app):
    api = FakeApi()
    calls = []
    row = na.JobRow(api, lambda *a: calls.append(a))
    row.update_job(job("1", "downloading"))
    next(b for b in row.findChildren(QPushButton) if b.text() == "取消").click()
    method, path, _b, ok, _err = api.calls[-1]
    assert (method, path) == ("POST", "/api/jobs/1/cancel")
    ok({"id": "1"})  # Api 呼叫成功回呼時會傳入回應內容
    assert calls == [()]


def test_delete_asks_before_removing_files(app, monkeypatch):
    api = FakeApi()
    row = na.JobRow(api, lambda *a: None)
    row.update_job(job("2", "done", files=[{"name": "v.mp4", "size": 5_000_000}]))
    seen = {}

    def answer(choice):
        def exec_(box):
            seen["text"] = box.informativeText()
            next(b for b in box.buttons() if b.text() == choice).click()
            return 0
        return exec_

    monkeypatch.setattr(QMessageBox, "exec", answer("取消"))
    delete = next(b for b in row.findChildren(QPushButton) if b.text() == "刪除")
    delete.click()
    assert not [c for c in api.calls if c[0] == "DELETE"]
    assert "永久刪除" in seen["text"]
    monkeypatch.setattr(QMessageBox, "exec", answer("刪除"))
    delete.click()
    assert [c[1] for c in api.calls if c[0] == "DELETE"] == ["/api/jobs/2"]


def test_cancelled_job_with_files_can_be_revealed(app):
    row = na.JobRow(FakeApi(), lambda *a: None)
    row.update_job(job("3", "cancelled", files=[{"name": "a.mp4", "size": 1}]))
    texts = [b.text() for b in row.findChildren(QPushButton)]
    assert f"在{na.FILE_MANAGER}中顯示" in texts and "刪除" in texts


def test_queue_ignores_older_snapshot(app):
    api = FakeApi()
    q = na.QueuePage(api)
    q.refresh()
    q.refresh()
    first, second = [c for c in api.calls if c[1] == "/api/jobs"]
    second[3]([job("b", "done")])
    first[3]([job("a", "downloading")])  # 較晚回來的舊結果
    assert q.order == ["b"]


def test_queue_reports_offline_after_two_failed_polls(app):
    api = FakeApi()
    q = na.QueuePage(api)
    states = []
    q.online.connect(lambda ok, msg: states.append(ok))
    q._poll()
    api.last("/api/jobs")[4]("Connection refused")
    assert states == []  # 一次失敗不算斷線
    q._poll()
    api.last("/api/jobs")[4]("Connection refused")
    assert states == [False]
    q._poll()
    api.last("/api/jobs")[3]([])
    assert states == [False, True]
    q._timer.stop()


def test_queue_does_not_stack_polls(app):
    api = FakeApi()
    q = na.QueuePage(api)
    q._poll()
    q._poll()  # 上一次還沒回來：不能再送
    assert len([c for c in api.calls if c[1] == "/api/jobs"]) == 1
    q._timer.stop()


# --------------------------------------------------------------------------- #
#  設定、更新、重新啟動
# --------------------------------------------------------------------------- #
def test_folder_dialog_starts_from_full_path(app, monkeypatch):
    page = na.SettingsPage(FakeApi(), lambda *a, **k: None)
    long_path = "D:\\" + "\\".join(["很長的資料夾名稱"] * 12)
    page.on_settings({"download_dir": long_path, "default_dir": "x", "disk": {}})
    page.folder.resize(200, 20)
    seen = {}
    from PySide6.QtWidgets import QFileDialog
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a: seen.setdefault("dir", a[2]) and "")
    page.choose()
    assert seen["dir"] == long_path and "…" in page.folder.text()


def test_restart_uses_handler_instead_of_exiting(monkeypatch):
    seen = {}
    monkeypatch.setattr(server, "RESTART_HANDLER", lambda cmd, env: seen.update(cmd=cmd, env=env))
    monkeypatch.setattr(server.subprocess, "Popen", lambda *a, **k: pytest.fail("不該直接啟動新程序"))
    monkeypatch.setattr(server.os, "_exit", lambda code: pytest.fail("不該直接結束程序"))
    server.restart_process()
    assert seen["cmd"][0] == sys.executable
    assert seen["env"]["YTDL_JUST_UPDATED"] == "1"


def test_restarter_exits_loop_then_launches(app, monkeypatch):
    from PySide6.QtCore import QTimer
    r = na.Restarter(app)
    QTimer.singleShot(0, lambda: threading.Thread(target=r, args=(["prog", "--x"], {"A": "1"})).start())
    QTimer.singleShot(3000, lambda: app.exit(99))  # 保險：沒結束就讓測試失敗
    assert app.exec() == 0
    launched = {}
    import subprocess
    monkeypatch.setattr(subprocess, "Popen", lambda cmd, env, cwd: launched.update(cmd=cmd, env=env, cwd=cwd))
    r.launch(Path("C:/root"))
    assert launched == {"cmd": ["prog", "--x"], "env": {"A": "1"}, "cwd": str(Path("C:/root"))}


def test_restarter_without_request_does_nothing(app, monkeypatch):
    import subprocess
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: pytest.fail("沒有要求重新啟動"))
    na.Restarter(app).launch(Path("."))


def test_update_button_reports_result_from_meta(app):
    api = FakeApi()
    toasts = []
    page = na.SettingsPage(api, lambda text, error=False: toasts.append((text, error)))
    page.update_ytdlp()
    post = api.calls[-1]
    assert post[1] == "/api/update"
    post[3]({"ok": True})
    assert "正在更新" in toasts[-1][0]
    assert wait_until(lambda: any(c[1] == "/api/meta" for c in api.calls))
    meta = api.last("/api/meta")
    meta[4]("Operation canceled")  # 查詢狀態逾時：稍後再查，不是更新失敗
    assert not page.update_btn.isEnabled()
    assert wait_until(lambda: len([c for c in api.calls if c[1] == "/api/meta"]) >= 2, 5000)
    api.last("/api/meta")[3]({"update_running": False, "update_message": "更新失敗：網路錯誤", "version": "1"})
    assert toasts[-1] == ("更新失敗：網路錯誤", True)
    assert page.update_btn.isEnabled()


def test_settings_offers_update_only_when_really_newer(app):
    page = na.SettingsPage(FakeApi(), lambda *a, **k: None)
    page.on_meta({"version": "2026.09.05", "latest": "2026.9.5", "ffmpeg": True})
    assert page.update_btn.text() == "檢查更新"
    page.on_meta({"version": "2026.09.05", "latest": "2026.10.26", "ffmpeg": True})
    assert page.update_btn.text() == "更新至 2026.10.26"


def test_engine_check_shows_hint_when_not_reachable(app, monkeypatch):
    api = FakeApi()
    win = na.MainWindow(api, lambda: False, "連接埠 8765 可能被其他程式佔用")
    monkeypatch.setattr(na.QTimer, "singleShot", lambda ms, fn: fn())  # 重試不用真的等
    win.check_engine(attempt=30)
    api.last("/api/meta")[4]("Connection refused")
    assert not win.engine_banner.isHidden() and "8765" in win.engine_banner.text()
    win.check_engine(attempt=30)
    api.last("/api/meta")[3]({"version": "2026.10.26", "latest": "2026.10.26", "ffmpeg": True})
    assert win.engine_banner.isHidden()
    win.close()


# --------------------------------------------------------------------------- #
#  外觀、文字大小
# --------------------------------------------------------------------------- #
def test_appearance_choice_is_saved_and_applied(app):
    from PySide6.QtGui import QPalette
    api = FakeApi()
    win = na.MainWindow(api, lambda: False)
    page = win.settings
    seen = []
    page.appearance_changed.connect(lambda: seen.append(na.ui_prefs()))
    try:
        page.theme.set_value("dark")
        page.theme.changed.emit("dark")
        page.font_size.set_value("large")
        page.font_size.changed.emit("large")
        assert seen[-1] == ("dark", "large")
        na.apply_theme(app, win, "")
        if not na.IS_MAC:
            assert app.font().pixelSize() == round(13 * na.FONT_SCALE["large"])
            assert app.palette().color(QPalette.Window) == QColor(na.tokens(True)["bg"])
        assert f"font-size: {round(15 * na.FONT_SCALE['large'])}px" in app.styleSheet()
        again = na.SettingsPage(api, lambda *a, **k: None)  # 重新開啟 App 時選項還在
        assert again.theme.value() == "dark" and again.font_size.value() == "large"
    finally:
        na.save_ui_prefs("system", "medium")
        na.apply_theme(app, win, "", dark=False)
        win.close()


# --------------------------------------------------------------------------- #
#  YouTube Premium
# --------------------------------------------------------------------------- #
@pytest.fixture
def premium_page(app):
    na.settings_store().remove("premium/status")
    api = FakeApi()
    adv = native_options.AdvancedOptions(api)
    toasts = []
    page = na.SettingsPage(api, lambda text, error=False: toasts.append(text), adv)
    yield page, api, adv, toasts
    na.settings_store().remove("premium/status")


def test_premium_check_uses_uploaded_cookies_and_enables_premium(premium_page):
    page, api, adv, toasts = premium_page
    assert page.premium_status.text() == "尚未檢查"
    adv.cookie_exists = True  # 已上傳 cookies.txt，但沒選 Cookie 來源（例如從舊版升級）
    adv.cookie_source.setCurrentIndex(adv.cookie_source.findData(""))
    adv.premium.setChecked(False)
    page.check_premium()
    call = api.last("/api/auth/test")
    assert call[2]["network"]["cookies_file"] is True
    assert not page.premium_check.isEnabled()
    call[3]({"logged_in": True, "premium": True, "expired": False})
    assert page.premium_status.text() == "Premium ✓" and page.premium_check.isEnabled()
    assert adv.premium.isChecked() and "Premium" in toasts[-1]
    again = na.SettingsPage(FakeApi(), lambda *a, **k: None, adv)  # 重新開啟也看得到上次的結果
    assert again.premium_status.text() == "Premium ✓" and "上次檢查" in again.premium_detail.text()


@pytest.mark.parametrize("reply,status", [
    ({"logged_in": True, "premium": False, "expired": False}, "已登入（非 Premium）"),
    ({"logged_in": False, "premium": False, "expired": True}, "Cookie 已過期"),
    ({"logged_in": False, "premium": False, "expired": False}, "未登入"),
])
def test_premium_status_texts(premium_page, reply, status):
    page, api, adv, _ = premium_page
    adv.cookie_exists = True
    page.check_premium()
    api.last("/api/auth/test")[3](reply)
    assert page.premium_status.text() == status


def test_premium_check_without_cookies_explains(premium_page):
    page, api, adv, _ = premium_page
    adv.cookie_exists = False
    adv.cookie_source.setCurrentIndex(adv.cookie_source.findData(""))
    page.check_premium()
    assert not [c for c in api.calls if c[1] == "/api/auth/test"]
    assert page.premium_status.text() == "無法檢查" and "cookies.txt" in page.premium_detail.text()


def test_premium_check_error_is_shown(premium_page):
    page, api, adv, _ = premium_page
    adv.cookie_exists = True
    page.check_premium()
    api.last("/api/auth/test")[4]("無法讀取 Chrome 的 Cookie")
    assert page.premium_status.text() == "無法檢查" and "Chrome" in page.premium_detail.text()
    assert page.premium_check.isEnabled()


def test_update_cookies_uploads_then_rechecks(premium_page, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    page, api, adv, _ = premium_page
    f = tmp_path / "cookies.txt"
    f.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(f), ""))
    page.update_cookies()
    up = api.last("/api/cookies")
    assert up[0] == "POST" and "Netscape" in up[2]["text"]
    up[3]({"exists": True})
    assert adv.network()["cookies_file"] is True
    assert api.last("/api/auth/test")  # 上傳成功後自動重新檢查


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
    assert na.is_supported_url(text) is ok


@pytest.fixture
def clip_win(app):
    api = FakeApi()
    win = na.MainWindow(api, lambda: False)
    checked = []
    win.clipboard.check = checked.append  # 不開背景執行緒：直接記下要判斷的文字
    na.set_auto_paste(True)
    yield win, api, checked
    na.set_auto_paste(True)
    win.close()


def test_clipboard_checked_once_per_content(clip_win):
    from PySide6.QtGui import QGuiApplication
    win, _api, checked = clip_win
    QGuiApplication.clipboard().setText("https://youtu.be/jNQXAC9IVRw")
    win.check_clipboard()
    win.check_clipboard()  # 同一段內容（例如切回視窗兩次）只處理一次
    assert checked == ["https://youtu.be/jNQXAC9IVRw"]
    QGuiApplication.clipboard().setText("第一行\n第二行")
    win.check_clipboard()
    assert len(checked) == 1


def test_clipboard_disabled_in_settings(clip_win):
    from PySide6.QtGui import QGuiApplication
    win, _api, checked = clip_win
    win.settings.auto_paste.setChecked(False)  # 設定頁關掉
    assert na.auto_paste_enabled() is False
    QGuiApplication.clipboard().setText("https://youtu.be/disabled0001")
    win.check_clipboard()
    assert checked == []


def test_paste_link_fills_and_analyzes(clip_win):
    win, api, _ = clip_win
    win.go(2)
    win.paste_link("https://youtu.be/jNQXAC9IVRw")
    assert win.stack.currentIndex() == 0  # 切到新增下載
    assert win.download.url.text() == "https://youtu.be/jNQXAC9IVRw"
    assert api.last("/api/info")[2]["url"] == "https://youtu.be/jNQXAC9IVRw"


def test_paste_link_does_not_clobber_typing_or_running_analysis(clip_win):
    win, api, _ = clip_win
    page = win.download
    page.url.setText("https://www.youtube.com/watch?v=typing")  # 使用者打到一半、還沒解析
    win.paste_link("https://youtu.be/jNQXAC9IVRw")
    assert page.url.text() == "https://www.youtube.com/watch?v=typing"
    assert not [c for c in api.calls if c[1] == "/api/info"]
    page.analyze()  # 正在解析中
    n = len([c for c in api.calls if c[1] == "/api/info"])
    win.paste_link("https://youtu.be/jNQXAC9IVRw")
    assert len([c for c in api.calls if c[1] == "/api/info"]) == n
    api.last("/api/info")[3](video_info("T", "typing"))  # 解析完成後，已解析的網址可以被新的連結取代
    win.paste_link("https://youtu.be/jNQXAC9IVRw")
    assert page.url.text() == "https://youtu.be/jNQXAC9IVRw"


def test_clipboard_watcher_finds_supported_link_in_background(app):
    w = na.ClipboardWatcher()
    found = []
    w.found.connect(found.append)
    w.check("https://youtu.be/jNQXAC9IVRw")
    w.check("https://www.google.com/")
    assert wait_until(lambda: found, 10_000)
    assert found == ["https://youtu.be/jNQXAC9IVRw"]


# --------------------------------------------------------------------------- #
#  免責聲明、關於
# --------------------------------------------------------------------------- #
@pytest.fixture
def fresh_disclaimer(app, monkeypatch):
    """模擬第一次開啟：沒有同意紀錄、不是 smoke test、沒有設 YTDL_ACCEPT_DISCLAIMER。"""
    monkeypatch.delenv("YTDL_ACCEPT_DISCLAIMER", raising=False)
    monkeypatch.setattr(sys, "argv", ["native_app.py"])
    na.settings_store().remove(na.DISCLAIMER_KEY)
    yield
    na.settings_store().remove(na.DISCLAIMER_KEY)


def press(text, seen=None):
    """回傳 run(box)：記下對話框，按下指定文字的按鈕。"""
    def run(box):
        if seen is not None:
            seen.append(box)
        next(b for b in box.buttons() if b.text() == text).click()
    return run


def test_disclaimer_asked_on_first_run_then_remembered(fresh_disclaimer):
    seen = []
    assert na.disclaimer_needed()
    assert na.confirm_disclaimer(None, press("我了解並同意", seen))
    assert len(seen) == 1
    assert na.DISCLAIMER_URL in seen[0].informativeText() and "有權" in seen[0].informativeText()
    assert na.settings_store().value(na.DISCLAIMER_KEY) == na.DISCLAIMER_VERSION
    # 同意後不再問
    assert not na.disclaimer_needed()
    assert na.confirm_disclaimer(None, press("我了解並同意", seen))
    assert len(seen) == 1


def test_disclaimer_asked_again_when_content_version_changes(fresh_disclaimer):
    na.settings_store().setValue(na.DISCLAIMER_KEY, "0")  # 同意的是舊版聲明
    assert na.disclaimer_needed()


def test_leave_quits_through_shutdown_and_is_not_remembered(fresh_disclaimer):
    left = []
    assert not na.require_disclaimer(None, None, press("離開"), leave=lambda: left.append(True))
    assert left == [True]
    assert na.disclaimer_needed()  # 沒有同意：下次開啟還會再問


def test_leave_default_runs_shutdown_then_exits(app, fresh_disclaimer, monkeypatch):
    calls = []
    monkeypatch.setattr(na, "shutdown", lambda a, w: calls.append(("shutdown", a, w)))
    monkeypatch.setattr(na.os, "_exit", lambda code: calls.append(("exit", code)))
    na.require_disclaimer(app, None, press("離開"))
    assert calls == [("shutdown", app, None), ("exit", 0)]


def test_escape_or_closing_dialog_counts_as_leave(fresh_disclaimer):
    box, accept = na.disclaimer_box()
    assert box.escapeButton().text() == "離開" and box.defaultButton() is accept


def test_accept_continues_without_leaving(fresh_disclaimer):
    left = []
    assert na.require_disclaimer(None, None, press("我了解並同意"), leave=lambda: left.append(True))
    assert left == []


def test_disclaimer_never_blocks_smoke_test_or_automation(fresh_disclaimer, monkeypatch):
    def fail(box):
        raise AssertionError("自動化流程不能顯示免責聲明對話框")

    monkeypatch.setattr(sys, "argv", ["native_app.py", "--smoke-test"])
    assert not na.disclaimer_needed() and na.confirm_disclaimer(None, fail)
    monkeypatch.setattr(sys, "argv", ["native_app.py"])
    monkeypatch.setenv("YTDL_ACCEPT_DISCLAIMER", "1")
    assert not na.disclaimer_needed() and na.confirm_disclaimer(None, fail)
    assert na.settings_store().value(na.DISCLAIMER_KEY) is None  # 跳過不算使用者同意


def test_main_asks_disclaimer_before_showing_window():
    """視窗一顯示就會檢查剪貼簿並自動解析連結：免責聲明一定要在 win.show() / win.start() 之前。"""
    import inspect
    lines = [ln.strip() for ln in inspect.getsource(na.main).splitlines()]
    assert lines.index("require_disclaimer(app, win)") < lines.index("win.show()") < lines.index("win.start()")


def test_ui_screenshot_skips_disclaimer():
    src = (Path(__file__).resolve().parent.parent / "tools" / "ui_screenshot.py").read_text(encoding="utf-8")
    assert 'os.environ.setdefault("YTDL_ACCEPT_DISCLAIMER", "1")' in src


def test_settings_about_shows_version_and_disclaimer_link(app, monkeypatch):
    page = na.SettingsPage(FakeApi(), lambda *a, **k: None)
    version = (Path(__file__).resolve().parent.parent / "VERSION").read_text(encoding="utf-8").strip()
    assert na.app_version() == version
    assert page.app_version.text() == version
    assert "有權" in page.disclaimer_text.text()
    opened = []
    monkeypatch.setattr(na.QDesktopServices, "openUrl", lambda u: opened.append(u.toString()))
    page.disclaimer_link.click()
    assert opened == [na.DISCLAIMER_URL]


def test_app_version_falls_back_when_file_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(na, "BUNDLE", tmp_path)
    assert na.app_version() == "開發版"
