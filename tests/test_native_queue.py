"""native_queue.py（下載佇列頁）的行為測試；用 offscreen 平台，不需要螢幕。"""
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", "C:/Windows/Fonts" if os.name == "nt" else "")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QEvent, QPointF, QSettings, Qt
from PySide6.QtGui import QGuiApplication, QMouseEvent
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton, QVBoxLayout, QWidget

import native_app as na
import native_common as nc
import native_options
import native_queue as nq


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    # 介面會存 QSettings：測試寫到暫存的 ini 檔，不要動到這台電腦的真實設定
    ini = str(tmp_path_factory.mktemp("qsettings") / "native.ini")
    store = lambda *a, **k: QSettings(ini, QSettings.IniFormat)
    native_options.QSettings = nc.QSettings = store  # native_queue 的 settings_store() 也讀 nc.QSettings
    a, _ = na.create_app()
    return a


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

    def paths(self, method):
        return [c[1] for c in self.calls if c[0] == method]


class Toasts(list):
    """新版 toast（level、actions）的替身。"""

    def __call__(self, text, level="info", actions=None):
        self.append((text, level))


# --------------------------------------------------------------------------- #
#  共用工具
# --------------------------------------------------------------------------- #
def job(jid, status, **kw):
    return {"id": jid, "url": "https://youtu.be/x", "title": f"T{jid}", "status": status, "progress": 0, **kw}


def buttons(row):
    """這一列右上角的動作按鈕（依顯示順序）。"""
    lay = row.buttons
    return [lay.itemAt(i).widget().text() for i in range(lay.count())]


def click(row, text):
    next(b for b in row.findChildren(QPushButton) if b.text() == text and b.isVisibleTo(row)).click()


def answer(choice, seen=None):
    """QMessageBox.exec 的替身：記下內容後按指定的按鈕。"""
    def exec_(box):
        if seen is not None:
            seen["text"] = box.text()
            seen["info"] = box.informativeText()
            seen["buttons"] = [b.text() for b in box.buttons()]
        next(b for b in box.buttons() if b.text() == choice).click()
        return 0
    return exec_


class FakeWindow(QWidget):
    """有 C1 介面（open_settings、go、download.accept_urls）的主視窗替身。"""

    def __init__(self, row):
        super().__init__()
        QVBoxLayout(self).addWidget(row)
        self.opened, self.pages, self.accepted = [], [], []
        win = self

        class Download:
            def accept_urls(self, urls):
                win.accepted.append(urls)
        self.download = Download()

    def open_settings(self, section):
        self.opened.append(section)

    def go(self, i):
        self.pages.append(i)


# --------------------------------------------------------------------------- #
#  基本動作
# --------------------------------------------------------------------------- #
def test_job_actions_refresh_without_type_error(app):
    api = FakeApi()
    calls = []
    row = nq.JobRow(api, lambda *a: calls.append(a))
    row.update_job(job("1", "queued"))
    click(row, "取消")  # 還沒下載任何東西：不用確認
    method, path, _b, ok, _err = api.calls[-1]
    assert (method, path) == ("POST", "/api/jobs/1/cancel")
    ok({"id": "1"})  # Api 呼叫成功回呼時會傳入回應內容
    assert calls == [()]


def test_pause_and_resume(app):
    """R4：下載中顯示「暫停」，paused 顯示「繼續」；暫停中（等 yt-dlp 停下）不再顯示暫停。"""
    api = FakeApi()
    row = nq.JobRow(api, lambda *a: None)
    row.update_job(job("p", "downloading", progress=40.0))
    assert "暫停" in buttons(row) and "取消" in buttons(row)
    click(row, "暫停")
    assert api.calls[-1][:2] == ("POST", "/api/jobs/p/pause")
    row.update_job(job("p", "downloading", progress=40.0, stage_code="pausing", stage="正在暫停…"))
    assert "暫停" not in buttons(row)
    assert row.detail.text().startswith("正在暫停…")
    row.update_job(job("p", "paused", progress=40.0, stage="已暫停", partial=3 * 1024 * 1024))
    assert "繼續" in buttons(row) and "移除" in buttons(row)
    assert "3.0 MB" in row.detail.text()
    click(row, "繼續")
    assert api.calls[-1][:2] == ("POST", "/api/jobs/p/resume")


def test_cancel_with_progress_offers_pause_instead(app, monkeypatch):
    api = FakeApi()
    row = nq.JobRow(api, lambda *a: None)
    row.update_job(job("c", "downloading", progress=12.5))
    seen = {}
    monkeypatch.setattr(QMessageBox, "exec", answer("返回", seen))
    click(row, "取消")
    assert not api.calls
    assert "暫存資料會刪除" in seen["info"] and "暫停" in seen["buttons"]
    monkeypatch.setattr(QMessageBox, "exec", answer("暫停"))
    click(row, "取消")
    assert api.calls[-1][:2] == ("POST", "/api/jobs/c/pause")
    monkeypatch.setattr(QMessageBox, "exec", answer("取消下載"))
    click(row, "取消")
    assert api.calls[-1][:2] == ("POST", "/api/jobs/c/cancel")


def test_action_failure_is_shown(app):
    api, toasts = FakeApi(), Toasts()
    row = nq.JobRow(api, lambda *a: None, toasts)
    row.update_job(job("f", "downloading", progress=1))
    click(row, "暫停")
    api.calls[-1][4]("工作進行中")
    assert toasts == [("暫停失敗：工作進行中", "error")]


# --------------------------------------------------------------------------- #
#  R5：移除
# --------------------------------------------------------------------------- #
def test_remove_keeps_files_by_default(app, monkeypatch):
    api = FakeApi()
    row = nq.JobRow(api, lambda *a: None)
    row.update_job(job("2", "done", files=[{"name": "v.mp4", "size": 5_000_000}]))
    seen = {}
    monkeypatch.setattr(QMessageBox, "exec", answer("取消", seen))
    click(row, "移除")
    assert not api.paths("DELETE")
    assert "留在電腦上" in seen["info"] and "永久" not in seen["info"]
    assert ("資源回收筒" in seen["info"]) != nc.IS_MAC
    assert seen["buttons"][:2] == ["從清單移除", "連同檔案刪除"] or set(seen["buttons"]) >= {"從清單移除", "連同檔案刪除"}
    monkeypatch.setattr(QMessageBox, "exec", answer("從清單移除"))
    click(row, "移除")
    monkeypatch.setattr(QMessageBox, "exec", answer("連同檔案刪除"))
    click(row, "移除")
    assert api.paths("DELETE") == ["/api/jobs/2?files=keep", "/api/jobs/2?files=trash"]


def test_remove_without_files(app, monkeypatch):
    api = FakeApi()
    row = nq.JobRow(api, lambda *a: None)
    row.update_job(job("n", "cancelled"))
    click(row, "移除")  # 沒有檔案也沒有暫存：直接移除
    row.update_job(job("m", "error", error="x", partial=2048))
    seen = {}
    monkeypatch.setattr(QMessageBox, "exec", answer("移除", seen))
    click(row, "移除")
    assert "暫存資料" in seen["info"]
    assert api.paths("DELETE") == ["/api/jobs/n?files=keep", "/api/jobs/m?files=keep"]


def test_cancelled_job_with_files_can_be_revealed(app):
    row = nq.JobRow(FakeApi(), lambda *a: None)
    row.update_job(job("3", "cancelled", files=[{"name": "a.mp4", "size": 1}]))
    texts = buttons(row)
    reveal = "在 Finder 中顯示" if nc.IS_MAC else "在檔案總管中顯示"
    assert reveal in texts and "移除" in texts and "開啟" not in texts
    assert row.icon.accessibleName() == "已取消"


def test_clear_finished(app):
    api, toasts = FakeApi(), Toasts()
    q = nq.QueuePage(api, toasts)
    q.render([job("a", "done"), job("b", "downloading")])
    assert q.clear_btn.isEnabled() and q.pause_all_btn.isEnabled()
    assert not q.resume_all_btn.isEnabled() and not q.retry_all_btn.isEnabled()
    q.clear_btn.click()
    assert api.calls[-1][:2] == ("POST", "/api/jobs/clear")
    api.calls[-1][3]({"ok": True, "count": 1, "ids": ["a"]})
    assert toasts[-1] == ("已從清單移除 1 個已完成的工作，檔案仍在原處", "info")
    assert api.calls[-1][1] == "/api/jobs"  # 接著刷新清單


# --------------------------------------------------------------------------- #
#  R2／R3／R6：有警告的完成、播放清單部分失敗
# --------------------------------------------------------------------------- #
def test_done_with_warnings_is_orange_and_expandable(app):
    row = nq.JobRow(FakeApi(), lambda *a: None)
    row.update_job(job("w", "done", files=[{"name": "v.mp4", "size": 1024}], warnings=["字幕下載失敗"]))
    assert row.detail.text().startswith("已完成，但有部分步驟失敗")
    assert row.detail.objectName() == "warnText"
    assert nq.kind_of(row.job) == "warn" and row.icon.toolTip() == "已完成，但有部分步驟失敗"
    assert not row.panel.isVisibleTo(row)
    click(row, "詳細資訊")
    assert row.panel.isVisibleTo(row) and "• 字幕下載失敗" in row.panel_text.text()
    click(row, "隱藏詳細資訊")
    assert not row.panel.isVisibleTo(row)


def test_playlist_partial_failure(app):
    api = FakeApi()
    row = nq.JobRow(api, lambda *a: None)
    fails = [{"index": 3, "title": "私人影片", "error_code": "private_video", "error": "這是私人影片",
              "error_detail": "ERROR: Private video"}]
    row.update_job(job("pl", "done", files=[{"name": f"{i}.mp4", "size": 1} for i in range(4)],
                       failed_items=fails, done_count=4, total_count=5))
    assert row.detail.text().startswith("完成 4/5，1 部無法下載")
    click(row, "詳細資訊")
    assert "第 3 部「私人影片」：這是私人影片" in row.panel_text.text()
    retry = [b for b in row.findChildren(QPushButton) if b.text() == "重試失敗的項目" and b.isVisibleTo(row)]
    assert len(retry) == 2  # 列上一個、展開區一個
    retry[0].click()
    assert api.calls[-1][:2] == ("POST", "/api/jobs/pl/retry_failed")


def test_old_engine_job_without_new_fields(app):
    """舊版引擎沒有 warnings、failed_items、error_action：退回原本的顯示。"""
    row = nq.JobRow(FakeApi(), lambda *a: None)
    row.update_job({"id": "o", "url": "u", "title": "舊", "status": "error", "progress": 0, "error": "下載失敗"})
    assert row.detail.text() == "下載失敗" and "重試" in buttons(row)
    row.update_job({"id": "o", "url": "u", "title": "舊", "status": "done", "progress": 100,
                    "files": [{"name": "a.mp4", "size": 2048}]})
    assert row.detail.text() == "已完成 · 1 個檔案 · 2 KB"
    assert not row.toggle.isVisibleTo(row)


# --------------------------------------------------------------------------- #
#  ERR1／ERR3／ERR4：錯誤訊息、建議動作、紀錄
# --------------------------------------------------------------------------- #
def test_error_detail_can_be_expanded_and_copied(app):
    toasts = Toasts()
    row = nq.JobRow(FakeApi(), lambda *a: None, toasts)
    row.update_job(job("e", "error", error="伺服器拒絕下載", error_code="http_403", error_action="resume",
                       error_detail="ERROR: HTTP Error 403: Forbidden", error_faq="err-http-403", partial=10))
    assert row.detail.text() == "伺服器拒絕下載" and row.detail.objectName() == "errorText"
    assert buttons(row)[:1] == ["繼續下載"]
    click(row, "詳細資訊")
    assert "HTTP Error 403" in row.panel_text.text()
    assert row.faq_btn.isVisibleTo(row) and row.log_btn.isVisibleTo(row)
    click(row, "複製錯誤訊息")
    assert QGuiApplication.clipboard().text() == "伺服器拒絕下載\nERROR: HTTP Error 403: Forbidden\n[http_403]"
    assert toasts[-1] == ("已複製錯誤訊息", "info")


def test_error_action_buttons_use_main_window(app):
    row = nq.JobRow(FakeApi(), lambda *a: None)
    win = FakeWindow(row)
    row.update_job(job("k", "error", error="需要登入", error_action="open_cookie_settings"))
    assert buttons(row)[:2] == ["設定 Cookie", "重試"]
    click(row, "設定 Cookie")
    row.update_job(job("k", "error", error="磁碟滿了", error_action="open_storage_settings"))
    click(row, "更換儲存位置")
    assert win.opened == ["cookies", "storage"]
    row.update_job(job("k", "error", error="格式不存在", error_action="reanalyze"))
    assert "重試" not in buttons(row)
    click(row, "重新解析")
    assert win.accepted == [["https://youtu.be/x"]] and win.pages == [0]


def test_error_action_falls_back_without_main_window(app):
    toasts = Toasts()
    row = nq.JobRow(FakeApi(), lambda *a: None, toasts)
    row.update_job(job("k2", "error", error="需要登入", error_action="open_cookie_settings"))
    click(row, "設定 Cookie")
    assert "設定 → Cookie" in toasts[-1][0]
    row.update_job(job("k2", "error", error="Proxy", error_action="open_network_settings"))
    click(row, "檢查 Proxy 設定")
    assert "Proxy" in toasts[-1][0]
    row.update_job(job("k2", "error", error="格式", error_action="reanalyze"))
    click(row, "重新解析")
    assert QGuiApplication.clipboard().text() == "https://youtu.be/x"


def test_update_ytdlp_then_retry_after_restart(app):
    api, toasts = FakeApi(), Toasts()
    row = nq.JobRow(api, lambda *a: None, toasts)
    row.update_job(job("u", "error", error="403", error_action="update_ytdlp"))
    assert buttons(row)[:2] == ["套用 yt-dlp 新版並重試", "重試"]
    click(row, "套用 yt-dlp 新版並重試")
    assert api.calls[-1][:2] == ("POST", "/api/update")
    api.calls[-1][3]({"ok": True})
    assert "重新啟動" in toasts[-1][0]
    # App 重新啟動後，第一次拿到清單就繼續這個工作（只做一次）
    api2 = FakeApi()
    q = nq.QueuePage(api2)
    q.render([job("u", "error", error="已中斷")])
    assert api2.paths("POST") == ["/api/jobs/u/resume"]
    q2 = nq.QueuePage(api2)
    q2.render([job("u", "error", error="已中斷")])
    assert api2.paths("POST") == ["/api/jobs/u/resume"]


def test_update_ytdlp_failure_forgets_retry(app):
    api, toasts = FakeApi(), Toasts()
    row = nq.JobRow(api, lambda *a: None, toasts)
    row.update_job(job("u2", "error", error="403", error_action="update_ytdlp"))
    click(row, "套用 yt-dlp 新版並重試")
    api.calls[-1][4]("有下載工作進行中，請完成後再更新")
    assert toasts[-1][1] == "error"
    q = nq.QueuePage(FakeApi())
    q.render([job("u2", "error")])
    assert not q.api.paths("POST")


def test_show_log(app):
    api = FakeApi()
    row = nq.JobRow(api, lambda *a: None)
    row.update_job(job("l", "done", files=[{"name": "a.mp4", "size": 1}]))
    dlg = row.show_log()
    assert api.calls[-1][:2] == ("GET", "/api/jobs/l")
    api.calls[-1][3]({"id": "l", "log": ["[youtube] 開始", "完成"]})
    assert dlg.text.toPlainText() == "[youtube] 開始\n完成" and dlg.copy_btn.isEnabled()
    dlg.close()
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    api.calls[-1][3]({"id": "l", "log": ["晚回來"]})  # 視窗已關：不能當掉


def test_log_menu_on_every_row(app):
    row = nq.JobRow(FakeApi(), lambda *a: None)
    row.update_job(job("m1", "downloading", progress=3))
    texts = [a.text() for a in row.menu.actions()]
    assert "顯示紀錄" in texts and "從清單移除…" not in texts
    menu = row.menu.actions()
    row.update_job(job("m1", "downloading", progress=4))
    assert row.menu.actions() == menu  # 內容沒變不重建（選單可能正開著）


# --------------------------------------------------------------------------- #
#  Q1：開啟、雙擊
# --------------------------------------------------------------------------- #
def test_open_largest_file(app, tmp_path, monkeypatch):
    folder = tmp_path / "o1"
    folder.mkdir()
    (folder / "big.mp4").write_bytes(b"x")
    opened = []
    monkeypatch.setattr(nq.QDesktopServices, "openUrl", lambda url: opened.append(url.toLocalFile()) or True)
    api = FakeApi()
    row = nq.JobRow(api, lambda *a: None)
    row.update_job(job("o1", "done", files=[{"name": "small.jpg", "size": 1}, {"name": "big.mp4", "size": 9}]))
    click(row, "開啟")
    api.last("/api/settings")[3]({"download_dir": str(tmp_path)})
    assert Path(opened[0]) == folder / "big.mp4"
    # 雙擊這一列也會開啟
    ev = QMouseEvent(QEvent.MouseButtonDblClick, QPointF(5, 5), QPointF(5, 5), Qt.LeftButton, Qt.LeftButton,
                     Qt.NoModifier)
    QApplication.sendEvent(row, ev)
    api.last("/api/settings")[3]({"download_dir": str(tmp_path)})
    assert len(opened) == 2


def test_open_falls_back_to_reveal(app, tmp_path):
    api = FakeApi()
    row = nq.JobRow(api, lambda *a: None)
    row.update_job(job("o2", "done", files=[{"name": "v.mp4", "size": 9}]))
    row.open_file()
    api.last("/api/settings")[3]({"download_dir": str(tmp_path)})  # 本機找不到（例如換過儲存位置）
    assert api.calls[-1][:3] == ("POST", "/api/jobs/o2/reveal", {"name": "v.mp4"})


# --------------------------------------------------------------------------- #
#  Q2／Q6：狀態圖示、排隊位置
# --------------------------------------------------------------------------- #
def test_status_icons_differ(app):
    t = nc.tokens(False)
    images = {k: nq.status_pixmap(k, t).toImage() for k in
              ("queued", "downloading", "processing", "paused", "done", "warn", "error", "cancelled")}
    assert all(not img.isNull() for img in images.values())
    assert len({bytes(img.constBits()) for img in images.values()}) == len(images)


def test_queue_position_text(app):
    row = nq.JobRow(FakeApi(), lambda *a: None)
    row.update_job(job("q", "queued", queue_position=3, stage="排隊中"))
    assert row.detail.text() == "排隊中（前面還有 2 個）"
    assert not row.bar.isVisibleTo(row)  # 排隊中不畫跑馬燈
    row.update_job(job("q", "queued", queue_position=1, stage="排隊中"))
    assert row.detail.text() == "排隊中（下一個開始）"
    row.update_job(job("q", "queued", stage="排隊中"))  # 舊版引擎沒有這個欄位
    assert row.detail.text() == "排隊中"


# --------------------------------------------------------------------------- #
#  Q5、F2／F3：批次動作、給主視窗的介面
# --------------------------------------------------------------------------- #
def test_bulk_actions(app):
    api, toasts = FakeApi(), Toasts()
    q = nq.QueuePage(api, toasts)
    q.render([job("a", "paused"), job("b", "error", error="x"),
              job("c", "done", failed_items=[{"index": 1, "error": "x"}])])
    assert q.resume_all_btn.isEnabled() and q.retry_all_btn.isEnabled() and not q.pause_all_btn.isEnabled()
    q.pause_all()
    api.calls[-1][3]({"ok": True, "count": 0, "jobs": []})
    assert toasts[-1] == ("沒有進行中的下載", "info")
    q.resume_all_btn.click()
    assert api.calls[-1][1] == "/api/jobs/resume_all"
    api.calls[-1][3]({"ok": True, "count": 1, "jobs": []})
    assert toasts[-1] == ("已繼續 1 個下載", "info")
    q.retry_all_btn.click()
    assert api.calls[-1][1] == "/api/jobs/retry_all"
    api.calls[-1][4]("引擎錯誤")
    assert toasts[-1] == ("全部重試失敗：引擎錯誤", "error")


def test_job_finished_only_for_new_transitions(app):
    q = nq.QueuePage(FakeApi())
    seen = []
    q.job_finished.connect(lambda j: seen.append((j["id"], j["status"])))
    q.render([job("old", "done"), job("a", "downloading"), job("b", "queued")])
    assert seen == []  # 第一次載入的舊工作不通知
    q.render([job("old", "done"), job("a", "done"), job("b", "downloading")])
    q.render([job("old", "done"), job("a", "done"), job("b", "error", error="x"), job("new", "done")])
    assert seen == [("a", "done"), ("b", "error")]


def test_summary(app):
    q = nq.QueuePage(FakeApi())
    assert q.summary()["active"] == 0 and q.summary()["progress"] is None
    q.render([job("a", "downloading", progress=50), job("b", "queued"), job("c", "paused"),
              job("d", "error", error="x"), job("e", "done")])
    s = q.summary()
    assert (s["active"], s["progress"], s["paused"], s["failed"], s["total"]) == (2, 25.0, 1, 1, 5)
    assert s["text"] == "2 個下載進行中 · 1 個已暫停 · 1 個失敗（整體 25%）"
    assert q.summary_label.text() == s["text"]


def test_show_job_scrolls_and_highlights(app):
    api = FakeApi()
    q = nq.QueuePage(api)
    q.show_job("later")  # 還沒載入：先記著，並刷新清單
    assert api.calls[-1][1] == "/api/jobs"
    q.render([job("x", "done"), job("later", "done")])
    assert q.rows["later"].property("highlighted") is True
    assert q.rows["x"].property("highlighted") is not True


def test_notify_supports_old_and_new_toast(app):
    old = []
    nq.notify(lambda text, error=False: old.append((text, error)), "壞了", "error")
    new = Toasts()
    nq.notify(new, "好了")
    nq.notify(None, "不會當掉")
    assert old == [("壞了", True)] and new == [("好了", "info")]


def test_apply_theme_updates_icons(app):
    q = nq.QueuePage(FakeApi())
    q.render([job("t", "done")])
    before = q.rows["t"].icon.pixmap().toImage()
    q.apply_theme(nc.tokens(True))
    assert q.rows["t"].icon.pixmap().toImage() != before


# --------------------------------------------------------------------------- #
#  輪詢
# --------------------------------------------------------------------------- #
def test_queue_ignores_older_snapshot(app):
    api = FakeApi()
    q = nq.QueuePage(api)
    q.refresh()
    q.refresh()
    first, second = [c for c in api.calls if c[1] == "/api/jobs"]
    second[3]([job("b", "done")])
    first[3]([job("a", "downloading")])  # 較晚回來的舊結果
    assert q.order == ["b"]


def test_queue_reports_offline_after_two_failed_polls(app):
    api = FakeApi()
    q = nq.QueuePage(api)
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
    q = nq.QueuePage(api)
    q._poll()
    q._poll()  # 上一次還沒回來：不能再送
    assert len([c for c in api.calls if c[1] == "/api/jobs"]) == 1
    q._timer.stop()


# --------------------------------------------------------------------------- #
#  code review 修正的回歸測試
# --------------------------------------------------------------------------- #
def test_double_click_on_detail_text_opens(app, tmp_path):
    """完成的說明文字不能被設成可選取，否則雙擊會被選字吃掉。"""
    api = FakeApi()
    row = nq.JobRow(api, lambda *a: None)
    row.update_job(job("d1", "done", files=[{"name": "v.mp4", "size": 9}]))
    assert row.detail.textInteractionFlags() == Qt.NoTextInteraction
    row.resize(600, 80)
    row.show()
    ev = QMouseEvent(QEvent.MouseButtonDblClick, QPointF(3, 3), row.detail.mapToGlobal(QPointF(3, 3)),
                     Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    QApplication.sendEvent(row.detail, ev)
    assert api.calls and api.calls[-1][1] == "/api/settings"
    row.update_job(job("d1", "error", error="壞了"))
    assert row.detail.textInteractionFlags() & Qt.TextSelectableByMouse
    row.close()


def test_remove_with_files_and_partial_warns_about_temp(app, monkeypatch):
    row = nq.JobRow(FakeApi(), lambda *a: None)
    row.update_job(job("pf", "paused", files=[{"name": "1.mp4", "size": 9}], partial=200 * 1024 * 1024))
    seen = {}
    monkeypatch.setattr(QMessageBox, "exec", answer("取消", seen))
    click(row, "移除")
    assert "留在電腦上" in seen["info"] and "暫存資料會刪除" in seen["info"]


def test_stale_retry_after_update_is_ignored(app):
    store = nc.settings_store()
    store.setValue(nq.RETRY_AFTER_UPDATE_KEY, "1|old")  # 很久以前的標記（沒有真的重新啟動）
    api = FakeApi()
    nq.QueuePage(api).render([job("old", "error", error="x")])
    assert not api.paths("POST")
    assert not store.contains(nq.RETRY_AFTER_UPDATE_KEY)


def test_job_finished_after_quick_retry_failure(app):
    q = nq.QueuePage(FakeApi())
    seen = []
    q.job_finished.connect(lambda j: seen.append(j["id"]))
    q.render([job("r", "error", error="x", finished=100.0)])
    q.render([job("r", "error", error="x", finished=100.0)])
    assert seen == []
    q.render([job("r", "error", error="又失敗", finished=200.0)])  # 兩次輪詢之間重試又失敗
    assert seen == ["r"]


def test_show_job_scrolls_after_page_is_shown(app):
    q = nq.QueuePage(FakeApi())
    q.render([job(str(i), "done") for i in range(30)])
    q.show_job("29")  # 頁面還沒顯示
    assert q._scroll_target == "29"
    q.resize(600, 300)
    q.show()
    for _ in range(3):
        QApplication.processEvents()
    assert q._scroll_target is None
    assert q.scroll.verticalScrollBar().value() > 0
    q.close()

