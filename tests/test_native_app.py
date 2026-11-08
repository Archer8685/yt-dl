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
    api = na.Api(html_server)
    got = {}
    api.get("/api/meta", lambda p: got.setdefault("ok", p), lambda m: got.setdefault("err", m))
    assert wait_until(lambda: got)
    assert got == {"err": na.NOT_ENGINE}


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


def test_basic_choices_are_remembered(app):
    page = na.DownloadPage(FakeApi(), lambda *a, **k: None)
    page.on_info(video_info("V", "v", heights=(2160, 1080, 720)))
    page.mode.set_value("audio")
    page.mode.changed.emit("audio")
    page.acodec.select("flac")
    page.mode.set_value("av")
    page.mode.changed.emit("av")
    page.quality.select(720)
    again = na.DownloadPage(FakeApi(), lambda *a, **k: None)
    assert again.mode.value() == "av" and again.acodec.currentData() == "flac"
    again.on_info(video_info("W", "w", heights=(1080, 720)))
    assert again.quality.currentData() == 720


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
