"""native_app.py（主視窗、工具列、啟動流程）的行為測試；用 offscreen 平台，不需要螢幕。"""
import os
import sys
import threading
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", "C:/Windows/Fonts" if os.name == "nt" else "")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QCoreApplication, QElapsedTimer, QEvent, QObject, QSettings, Qt, Signal
from PySide6.QtWidgets import QApplication

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
#  主題資源
# --------------------------------------------------------------------------- #
def test_chevron_asset_exists():
    from PySide6.QtGui import QImage
    path = na.create_app.__globals__["BUNDLE"] / "assets" / "chevron.png"
    assert path.is_file() and not QImage(str(path)).isNull()


# --------------------------------------------------------------------------- #
#  更新、重新啟動、引擎連線
# --------------------------------------------------------------------------- #
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
    QTimer.singleShot(0, lambda: threading.Thread(
        target=r, args=(["prog", "--x", "ytdl://add?url=https%3A%2F%2Fyoutu.be%2Fx"], {"A": "1"})).start())
    QTimer.singleShot(3000, lambda: app.exit(99))  # 保險：沒結束就讓測試失敗
    assert app.exec() == 0
    launched = {}
    import subprocess
    monkeypatch.setattr(subprocess, "Popen", lambda cmd, env, cwd: launched.update(cmd=cmd, env=env, cwd=cwd))
    r.launch(Path("C:/root"))
    # 不重送網址；新程序要先等這個程序放開連接埠（YTDL_RESTARTED）
    assert launched == {"cmd": ["prog", "--x"], "env": {"A": "1", na.RESTARTED_ENV: "1"}, "cwd": str(Path("C:/root"))}


def test_restarter_without_request_does_nothing(app, monkeypatch):
    import subprocess
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: pytest.fail("沒有要求重新啟動"))
    na.Restarter(app).launch(Path("."))


def banner_buttons(banner) -> list[str]:
    return [b.text() for b in banner.action_buttons]


def test_engine_offline_banner_explains_and_offers_actions(app, monkeypatch, tmp_path):
    """ERR6：引擎連不上時顯示標題＋說明＋「重試」「開啟紀錄檔」「重新啟動 App」，並停用「解析」。"""
    api = FakeApi()
    restarted = []
    win = na.MainWindow(api, lambda: False, "連接埠 8765 可能被其他程式佔用", log_path=tmp_path / "engine.log",
                        restart=lambda: restarted.append(True))
    monkeypatch.setattr(na.QTimer, "singleShot", lambda ms, fn: fn())  # 重試不用真的等
    win.check_engine(attempt=30)
    api.last("/api/meta")[4]("Connection refused")
    b = win.engine_banner
    assert not b.isHidden() and b.title.text() == "無法連到下載引擎" and "Connection refused" in b.text()
    assert "8765" not in b.text()  # 連不上不代表連接埠被佔用（ERR7）
    assert banner_buttons(b) == ["重試", "開啟紀錄檔", "重新啟動 App"]
    assert b.close_btn.isHidden()  # 問題解決前不能關掉
    assert not win.download.analyze_btn.isEnabled()
    b.action_buttons[2].click()
    assert restarted == [True]
    win.check_engine(attempt=30)
    api.last("/api/meta")[3]({"version": "2026.10.26", "latest": "2026.10.26", "ffmpeg": True})
    assert b.isHidden() and win.download.analyze_btn.isEnabled()
    win.close()


def test_engine_check_mentions_port_only_when_another_program_answers(app, monkeypatch):
    api = FakeApi()
    win = na.MainWindow(api, lambda: False, "連接埠 8765 可能被其他程式佔用")
    win.check_engine()
    api.last("/api/meta")[3]({"hello": "not the engine"})  # 有回應但不是引擎：不用重試，直接說明
    assert "8765" in win.engine_banner.text() and "不是 YT 下載器的下載引擎" in win.engine_banner.text()
    assert banner_buttons(win.engine_banner) == ["重試"]  # 沒有紀錄檔、重新啟動時不顯示那兩顆
    win.close()


def test_runtime_disconnect_uses_same_banner_and_recovers(app):
    api = FakeApi()
    win = na.MainWindow(api, lambda: False)
    win.on_online(False, "下載引擎沒有在執行")
    assert win.engine_banner.title.text() == "與下載引擎的連線中斷了"
    assert not win.download.analyze_btn.isEnabled()
    win.on_online(True, "")
    assert win.engine_banner.isHidden() and win.download.analyze_btn.isEnabled()
    win.close()


def test_retry_button_checks_engine_again(app):
    api = FakeApi()
    win = na.MainWindow(api, lambda: False)
    win.show_offline("無法連到下載引擎", "x")
    n = len([c for c in api.calls if c[1] == "/api/meta"])
    win.engine_banner.action_buttons[0].click()
    assert len([c for c in api.calls if c[1] == "/api/meta"]) == n + 1
    assert [c for c in api.calls if c[1] == "/api/jobs"]  # 佇列也馬上重新整理
    win.close()


def test_open_log_opens_log_file(app, monkeypatch, tmp_path):
    log = tmp_path / "engine.log"
    log.write_text("x", encoding="utf-8")
    opened = []
    monkeypatch.setattr(na.QDesktopServices, "openUrl", lambda url: opened.append(url.toLocalFile()) or True)
    win = na.MainWindow(FakeApi(), lambda: False, log_path=log)
    win.open_log()
    log.unlink()
    win.open_log()  # 紀錄檔還沒產生：開資料夾
    assert [Path(p) for p in opened] == [log, tmp_path]
    win.close()


# --------------------------------------------------------------------------- #
#  儲存位置無法存取（R1、驗收標準 1）
# --------------------------------------------------------------------------- #
def meta(**kw):
    return {"version": "2026.10.26", "latest": "2026.10.26", "ffmpeg": True, "download_dir": "D:\\yt",
            "download_dir_error": None, **kw}


def test_storage_banner_shows_full_path_and_change_location(app, monkeypatch):
    api = FakeApi()
    win = na.MainWindow(api, lambda: False)
    win.check_engine()
    api.last("/api/meta")[3](meta(download_dir="Z:\\nodrive\\yt", download_dir_error="儲存位置（Z:）目前無法存取",
                                  download_dir_error_detail="Z:\\nodrive\\yt: 系統找不到指定的路徑。"))
    b = win.storage_banner
    assert not b.isHidden() and b.title.text() == "儲存位置 Z:\\nodrive\\yt 目前無法存取"
    assert banner_buttons(b) == ["更換位置", "重試"]
    assert win.engine_banner.isHidden()  # 引擎是好的：只顯示儲存位置的問題，不說連接埠被佔用
    monkeypatch.setattr(na.QFileDialog, "getExistingDirectory", lambda *a: "E:\\new")
    b.action_buttons[0].click()
    method, _path, body, ok, _err = api.last("/api/settings")
    assert (method, body) == ("POST", {"download_dir": "E:\\new"})
    ok({"download_dir": "E:\\new", "default_dir": "C:\\d", "disk": {}, "download_dir_error": None})
    assert b.isHidden()  # 不用重開 App
    assert "E:\\new" in win.banner.text()
    assert api.calls[-1][1] == "/api/meta"  # 換好後再確認一次
    win.close()


def test_storage_banner_stays_when_new_location_also_unavailable(app, monkeypatch):
    api = FakeApi()
    win = na.MainWindow(api, lambda: False)
    win.on_meta(meta(download_dir="Z:\\a", download_dir_error="x"))
    win.set_storage("Y:\\b")
    api.last("/api/settings")[3]({"download_dir": "Y:\\b", "download_dir_error": "y"})
    assert not win.storage_banner.isHidden() and "Y:\\b" in win.storage_banner.title.text()
    win.close()


def test_storage_problem_found_when_disk_removed_while_running(app):
    """執行中拔掉磁碟：工作因為儲存位置失敗時馬上重新檢查，並定時檢查。"""
    api = FakeApi()
    win = na.MainWindow(api, lambda: False)
    win.start()
    assert win._storage_timer.isActive() and win._storage_timer.interval() <= 60_000
    n = len([c for c in api.calls if c[1] == "/api/meta"])
    win.on_job_finished({"id": "j1", "status": "error", "error_code": "download_dir_unavailable", "title": "T"})
    assert len([c for c in api.calls if c[1] == "/api/meta"]) == n + 1
    api.last("/api/meta")[3](meta(download_dir="Z:\\yt", download_dir_error="x"))
    assert not win.storage_banner.isHidden()
    api.last("/api/meta")[3](meta())  # 接回去之後
    assert win.storage_banner.isHidden()
    win.close()


# --------------------------------------------------------------------------- #
#  自動貼上剪貼簿裡的影片連結
# --------------------------------------------------------------------------- #
@pytest.fixture
def clip_win(app):
    api = FakeApi()
    win = na.MainWindow(api, lambda: False)
    checked = []
    win.clipboard.check = checked.append  # 不開背景執行緒：直接記下要判斷的文字
    nc.set_auto_paste(True)
    yield win, api, checked
    nc.set_auto_paste(True)
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
    assert nc.auto_paste_enabled() is False
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
    api.last("/api/info")[3](video_info("T", "typing"))
    # 解析完成後也不直接蓋掉（DL5）：改成「偵測到新連結」讓使用者決定
    win.paste_link("https://youtu.be/jNQXAC9IVRw")
    assert page.url.text() == "https://www.youtube.com/watch?v=typing"
    assert not page.new_link.isHidden() and "jNQXAC9IVRw" in page.new_link_text.text()
    assert "自動貼上" not in win.banner.text()  # 沒有真的貼上：不顯示「已自動貼上」
    page.new_link_go.click()
    assert page.url.text() == "https://youtu.be/jNQXAC9IVRw"
    assert api.last("/api/info")[2]["url"] == "https://youtu.be/jNQXAC9IVRw"


# --------------------------------------------------------------------------- #
#  免責聲明、關於
# --------------------------------------------------------------------------- #
@pytest.fixture
def fresh_disclaimer(app, monkeypatch):
    """模擬第一次開啟：沒有同意紀錄、不是 smoke test、沒有設 YTDL_ACCEPT_DISCLAIMER。"""
    monkeypatch.delenv("YTDL_ACCEPT_DISCLAIMER", raising=False)
    monkeypatch.setattr(sys, "argv", ["native_app.py"])
    nc.settings_store().remove(nc.DISCLAIMER_KEY)
    yield
    nc.settings_store().remove(nc.DISCLAIMER_KEY)


def press(text, seen=None):
    """回傳 run(box)：記下對話框的說明文字（對話框用完就刪了），按下指定文字的按鈕。"""
    def run(box):
        if seen is not None:
            seen.append(box.informativeText())
        next(b for b in box.buttons() if b.text() == text).click()
    return run


def test_disclaimer_asked_on_first_run_then_remembered(fresh_disclaimer):
    seen = []
    assert nc.disclaimer_needed()
    assert nc.confirm_disclaimer(None, press("我了解並同意", seen))
    assert len(seen) == 1
    assert nc.DISCLAIMER_URL in seen[0] and "有權" in seen[0]
    assert nc.settings_store().value(nc.DISCLAIMER_KEY) == nc.DISCLAIMER_VERSION
    # 同意後不再問
    assert not nc.disclaimer_needed()
    assert nc.confirm_disclaimer(None, press("我了解並同意", seen))
    assert len(seen) == 1


def test_disclaimer_asked_again_when_content_version_changes(fresh_disclaimer):
    nc.settings_store().setValue(nc.DISCLAIMER_KEY, "0")  # 同意的是舊版聲明
    assert nc.disclaimer_needed()


def test_leave_quits_through_shutdown_and_is_not_remembered(fresh_disclaimer):
    left = []
    assert not na.require_disclaimer(None, None, press("離開"), leave=lambda: left.append(True))
    assert left == [True]
    assert nc.disclaimer_needed()  # 沒有同意：下次開啟還會再問


def test_leave_default_runs_shutdown_then_exits(app, fresh_disclaimer, monkeypatch):
    calls = []
    monkeypatch.setattr(na, "shutdown", lambda a, w: calls.append(("shutdown", a, w)))
    monkeypatch.setattr(na.os, "_exit", lambda code: calls.append(("exit", code)))
    na.require_disclaimer(app, None, press("離開"))
    assert calls == [("shutdown", app, None), ("exit", 0)]


def test_disclaimer_shows_three_points_and_full_text_link(fresh_disclaimer):
    """SET11：三點條列；「查看完整聲明」在 App 裡開捲動的對話框，不是開瀏覽器。"""
    from PySide6.QtWidgets import QLabel
    box, _ = nc.disclaimer_box()
    text = box.informativeText()
    assert text.count("<li") == 3 and "查看完整聲明" in text
    info = box.findChild(QLabel, "qt_msgbox_informativelabel")
    assert info is not None and not info.openExternalLinks()
    import shiboken6
    shiboken6.delete(box)


def test_full_disclaimer_dialog_uses_bundled_file_by_language(app, monkeypatch, tmp_path):
    root = Path(__file__).resolve().parent.parent
    zh = nc.disclaimer_markdown("zh_TW", root / "DISCLAIMER.md")
    en = nc.disclaimer_markdown("en", root / "DISCLAIMER.md")
    assert "本軟體只是工具" in zh and "English version below" not in zh and "Disclaimer" not in zh
    assert "Disclaimer" in en and "本軟體" not in en
    shown = []
    monkeypatch.setattr(nc, "BUNDLE", root)
    assert nc.show_full_disclaimer(None, run=lambda d: shown.append(d.browser.toPlainText()))
    assert shown and "本軟體只是工具" in shown[0]
    opened = []
    monkeypatch.setattr(nc, "BUNDLE", tmp_path)  # 打包版沒有附 DISCLAIMER.md：改用瀏覽器開 GitHub 上的版本
    monkeypatch.setattr(nc.QDesktopServices, "openUrl", lambda url: opened.append(url.toString()) or True)
    assert not nc.show_full_disclaimer(None, run=lambda d: pytest.fail("不該開對話框"))
    assert opened == [nc.DISCLAIMER_URL]
    monkeypatch.setattr(nc.i18n, "current_language", lambda: "en")
    nc.show_full_disclaimer(None)
    assert opened[-1].endswith("#disclaimer-english")


def test_escape_or_closing_dialog_counts_as_leave(fresh_disclaimer):
    box, accept = nc.disclaimer_box()
    assert box.escapeButton().text() == "離開" and box.defaultButton() is accept


def test_accept_continues_without_leaving(fresh_disclaimer):
    left = []
    assert na.require_disclaimer(None, None, press("我了解並同意"), leave=lambda: left.append(True))
    assert left == []


def test_disclaimer_never_blocks_smoke_test_or_automation(fresh_disclaimer, monkeypatch):
    def fail(box):
        raise AssertionError("自動化流程不能顯示免責聲明對話框")

    monkeypatch.setattr(sys, "argv", ["native_app.py", "--smoke-test"])
    assert not nc.disclaimer_needed() and nc.confirm_disclaimer(None, fail)
    monkeypatch.setattr(sys, "argv", ["native_app.py"])
    monkeypatch.setenv("YTDL_ACCEPT_DISCLAIMER", "1")
    assert not nc.disclaimer_needed() and nc.confirm_disclaimer(None, fail)
    assert nc.settings_store().value(nc.DISCLAIMER_KEY) is None  # 跳過不算使用者同意


def test_main_asks_disclaimer_before_showing_window():
    """視窗一顯示就會檢查剪貼簿並自動解析連結：免責聲明一定要在 win.show() / win.start() 之前。"""
    import inspect
    lines = [ln.strip() for ln in inspect.getsource(na.main).splitlines()]
    assert lines.index("require_disclaimer(app, win)") < lines.index("win.show()") < lines.index("win.start()")


def test_ui_screenshot_skips_disclaimer():
    src = (Path(__file__).resolve().parent.parent / "tools" / "ui_screenshot.py").read_text(encoding="utf-8")
    assert 'os.environ.setdefault("YTDL_ACCEPT_DISCLAIMER", "1")' in src


def test_native_app_still_exports_what_other_files_use():
    """拆檔後 native_app 要繼續 re-export：截圖工具（只在 CI 跑）和 native_options / native_playlist 都從這裡取用。"""
    import ast
    root = Path(__file__).resolve().parent.parent
    used = set()
    shot = ast.parse((root / "tools" / "ui_screenshot.py").read_text(encoding="utf-8"))
    used |= {n.attr for n in ast.walk(shot)
             if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "na"}
    for f in ("native_options.py", "native_playlist.py"):
        tree = ast.parse((root / f).read_text(encoding="utf-8"))
        used |= {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module == "native_app"
                 for a in n.names}
    assert used and not [name for name in used if not hasattr(na, name)]


# --------------------------------------------------------------------------- #
#  toast（ERR8）
# --------------------------------------------------------------------------- #
@pytest.fixture
def win(app):
    api = FakeApi()
    w = na.MainWindow(api, lambda: False)
    w.api_fake = api
    yield w
    w._quitting = True
    w.close()


def test_toast_old_calls_still_work_and_info_hides_itself(win):
    win.toast("已加入")
    assert not win.banner.isHidden() and win.banner.text() == "已加入"
    assert win._toast_timer.isActive() and win.banner.copy_btn.isHidden()
    win._toast_timer.timeout.emit()
    assert win.banner.isHidden()
    win.toast("壞了", error=True)  # 舊寫法
    assert win.banner.property("error") is True and not win._toast_timer.isActive()


def test_error_toast_stays_until_closed_and_can_be_copied(win):
    from PySide6.QtGui import QGuiApplication
    win.toast("無法解析：HTTP Error 403", level="error")
    assert not win._toast_timer.isActive()  # 錯誤不自動消失
    assert not win.banner.copy_btn.isHidden()
    win.banner.copy_btn.click()
    assert QGuiApplication.clipboard().text() == "無法解析：HTTP Error 403"
    win.banner.close_btn.click()
    assert win.banner.isHidden()


def test_toast_actions_run_callback_and_close(win):
    seen = []
    win.toast("已恢復預設", actions=[("復原", lambda: seen.append("undo"))])
    assert banner_buttons(win.banner) == ["復原"]
    assert win._toast_timer.interval() == na.TOAST_ACTION_MS  # 有按鈕時久一點才消失
    win.banner.action_buttons[0].click()
    assert seen == ["undo"] and win.banner.isHidden()
    win.toast("下一則")  # 換成沒有按鈕的提示：上一則的按鈕要拿掉
    assert banner_buttons(win.banner) == []


def test_pages_detect_new_toast_signature(win):
    """A1、A2、B 用 inspect 判斷 toast 有沒有 level／actions 參數。"""
    import inspect
    params = inspect.signature(win.toast).parameters
    assert {"error", "level", "actions"} <= set(params)


# --------------------------------------------------------------------------- #
#  快捷鍵（DL8）、焦點（DL7）、Esc
# --------------------------------------------------------------------------- #
def test_shortcuts_switch_pages_and_focus(win):
    assert set(win.shortcuts) >= {"Ctrl+L", "Ctrl+Return", "Ctrl+Enter", "Ctrl+1", "Ctrl+2", "Ctrl+3", "Ctrl+,"}
    win.shortcuts["Ctrl+2"].activated.emit()
    assert win.stack.currentIndex() == 1
    win.shortcuts["Ctrl+,"].activated.emit()
    assert win.stack.currentIndex() == 2
    focused = []
    win.download.focus_url = lambda: focused.append(True)
    win.shortcuts["Ctrl+L"].activated.emit()
    assert win.stack.currentIndex() == 0 and focused


def test_ctrl_enter_downloads_only_on_download_page(win):
    started = []
    win.download.start_download = lambda: started.append(True)
    win.go(1)
    win.shortcuts["Ctrl+Return"].activated.emit()
    assert started == []
    win.go(0)
    win.shortcuts["Ctrl+Enter"].activated.emit()
    assert started == [True]


def test_ctrl_shortcut_reaches_window_from_url_field(win):
    """真的按鍵：焦點在網址欄時 Ctrl+2 也要切頁（不能被輸入框吃掉）。"""
    from PySide6.QtTest import QTest
    win.show()
    win.activateWindow()
    if not wait_until(win.isActiveWindow, 2000):
        pytest.skip("這個平台無法讓測試視窗成為作用中視窗")
    win.download.url.setFocus()
    QTest.keyClick(win.download.url, Qt.Key_2, Qt.ControlModifier)
    assert win.stack.currentIndex() == 1


def test_escape_cancels_analysis_from_anywhere_in_window(win):
    from PySide6.QtGui import QKeyEvent
    win.download.url.setText("https://youtu.be/jNQXAC9IVRw")
    win.download.analyze()
    assert win.download._analyzing
    win.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier))
    assert not win.download._analyzing and win.download.url.isEnabled()


def test_going_back_to_download_page_focuses_url(win):
    calls = []
    win.download.focus_url = lambda: calls.append(True)
    win.go(1)
    win.go(0)
    assert calls == [True]


def test_start_focuses_url(win):
    calls = []
    win.download.focus_url = lambda: calls.append(True)
    win.start()
    assert calls


# --------------------------------------------------------------------------- #
#  無障礙（A11Y1、A11Y2）
# --------------------------------------------------------------------------- #
def test_sidebar_arrow_keys_switch_pages(win):
    from PySide6.QtTest import QTest
    win.show()
    win.activateWindow()
    if not wait_until(win.isActiveWindow, 2000):
        pytest.skip("這個平台無法讓測試視窗成為作用中視窗")
    win.nav[0].setFocus(Qt.TabFocusReason)
    assert wait_until(lambda: QApplication.focusWidget() is win.nav[0], 1000)
    QTest.keyClick(win.nav[0], Qt.Key_Down)
    assert win.stack.currentIndex() == 1 and QApplication.focusWidget() is win.nav[1]
    QTest.keyClick(win.nav[1], Qt.Key_Down)
    assert win.stack.currentIndex() == 2
    QTest.keyClick(win.nav[2], Qt.Key_Up)
    QTest.keyClick(win.nav[1], Qt.Key_Up)
    assert win.stack.currentIndex() == 0
    assert QApplication.focusWidget() is win.nav[0]  # 用鍵盤切回「新增下載」時不把焦點搶到網址欄


def test_nav_buttons_have_names_and_scroll_areas_skip_tab(win):
    from PySide6.QtWidgets import QScrollArea
    assert [b.accessibleName() for b in win.nav] == ["新增下載", "下載佇列", "設定"]
    areas = win.findChildren(QScrollArea)
    assert areas and all(a.focusPolicy() == Qt.NoFocus for a in areas if a.objectName() != "qt_scrollarea_viewport"
                         and a.widget() is not None and a.widget().objectName() == "content")


def test_form_row_sets_buddy_and_accessible_name(app):
    from PySide6.QtWidgets import QLabel, QPushButton
    btn = QPushButton("變更…")
    row = nc.form_row("儲存位置", btn)
    title = row.findChildren(QLabel)[0]
    assert title.buddy() is btn and btn.accessibleName() == "儲存位置"
    named = QPushButton("x")
    named.setAccessibleName("自己的名稱")
    keep = nc.form_row("標題", named)  # noqa: F841 — 列被回收會連按鈕一起刪掉
    assert named.accessibleName() == "自己的名稱"  # 已經有名稱的不覆蓋


# --------------------------------------------------------------------------- #
#  拖放（F4）
# --------------------------------------------------------------------------- #
def drop(win, mime, target=None):
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QDropEvent
    e = QDropEvent(QPointF(10, 10), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    if target is None:
        win.dropEvent(e)
    else:
        win.eventFilter(target, e)
    return e


def test_dropping_urls_text_or_txt_file_goes_to_accept_urls(win, tmp_path):
    from PySide6.QtCore import QMimeData, QUrl
    got = []
    win.download.accept_urls = got.append
    win.go(2)
    m = QMimeData()
    m.setText("https://youtu.be/a\nhttps://youtu.be/b")
    assert drop(win, m).isAccepted()
    assert got[-1] == ["https://youtu.be/a\nhttps://youtu.be/b"] and win.stack.currentIndex() == 0
    txt = tmp_path / "list.txt"
    txt.write_text("https://youtu.be/c", encoding="utf-8")
    m = QMimeData()
    m.setUrls([QUrl.fromLocalFile(str(txt))])
    drop(win, m)
    assert Path(got[-1][0]) == txt
    m = QMimeData()
    m.setUrls([QUrl("https://www.youtube.com/watch?v=jNQXAC9IVRw")])
    drop(win, m, target=win.download.url)  # 拖到網址欄上也一樣
    assert got[-1] == ["https://www.youtube.com/watch?v=jNQXAC9IVRw"]


@pytest.mark.filterwarnings("ignore::DeprecationWarning")  # PySide6 只剩 QPoint 版本的建構子
def test_drag_enter_ignores_empty_payload(win):
    from PySide6.QtCore import QMimeData, QPoint
    from PySide6.QtGui import QDragEnterEvent
    mime = QMimeData()  # 要留著參照：事件不擁有 QMimeData
    e = QDragEnterEvent(QPoint(1, 1), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    win.dragEnterEvent(e)
    assert not e.isAccepted()
    assert win.acceptDrops()


# --------------------------------------------------------------------------- #
#  ytdl:// 與單一實例（F7）
# --------------------------------------------------------------------------- #
def test_handoff_fills_download_page_without_downloading(win):
    win.go(1)
    win.handle_handoff(["ytdl://add?url=https%3A%2F%2Fwww.youtube.com%2Fwatch%3Fv%3DjNQXAC9IVRw"])
    assert win.stack.currentIndex() == 0
    assert win.download.url.text() == "https://www.youtube.com/watch?v=jNQXAC9IVRw"
    info = [c for c in win.api_fake.calls if c[1] == "/api/info"]
    assert info and not [c for c in win.api_fake.calls if c[1] == "/api/download"]  # 只解析，不下載


@pytest.mark.parametrize("arg", ["ytdl://add?url=file%3A%2F%2F%2FC%3A%2Fx.txt", "ytdl://add?url=javascript%3Aalert(1)",
                                 "javascript:alert(1)", "file:///C:/Windows/win.ini"])
def test_handoff_rejects_non_http_links_with_message(win, arg):
    win.handle_handoff([arg])
    assert not [c for c in win.api_fake.calls if c[1] == "/api/info"]
    assert win.banner.property("error") is True and "http" in win.banner.text()


def test_handoff_to_this_computer_explains_why(win):
    """ytdl:// 帶本機位址被拒絕時，說明原因是「指向這台電腦」，不是說只接受 http（它本來就是 http）。"""
    win.handle_handoff(["ytdl://add?url=http%3A%2F%2F127.0.0.1%3A8765%2Fapi%2Fjobs"])
    assert not [c for c in win.api_fake.calls if c[1] == "/api/info"]
    assert win.banner.property("error") is True and "127.0.0.1" in win.banner.text()


def test_second_launch_without_url_just_wakes_window(win):
    win.hide()
    win.handle_handoff([])
    assert win.isVisible() and win.banner.isHidden()


def test_handoff_waits_until_window_ready():
    h = na.Handoff()
    h.add(["a"])
    h.add(["b"])
    got = []
    h.set_handler(got.append)
    h.add(["c"])
    assert got == [["a"], ["b"], ["c"]] and h.pending == []


def test_file_open_event_forwards_ytdl_url(app):
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QFileOpenEvent
    f = na.FileOpenFilter()
    got = []
    f.opened.connect(got.append)
    assert f.eventFilter(app, QFileOpenEvent(QUrl("ytdl://add?url=https%3A%2F%2Fyoutu.be%2Fx")))
    assert got == [["ytdl://add?url=https%3A%2F%2Fyoutu.be%2Fx"]]


@pytest.mark.parametrize("arg,link", [("ytdl://add?url=x", True), ("javascript:alert(1)", True),
                                      ("C:\\Users\\a.txt", False), ("--smoke-test", False), ("hello", False)])
def test_looks_like_link(arg, link):
    assert na.looks_like_link(arg) is link


def test_instance_key_separates_custom_port():
    assert na.instance_key({}) == na.instance_key({"YTDL_PORT": "8765"}) == "yt-dl"
    assert na.instance_key({"YTDL_PORT": "18999"}) == "yt-dl-18999"


def test_hand_off_skips_engine_commands_and_sends_args(monkeypatch):
    assert na.hand_off_to_running_app(["app", "--server"]) == (False, None)
    sent = []

    class Other:
        def __init__(self, key):
            self.key = key

        def is_primary(self):
            return False

        def send(self, args):
            sent.append(args)
            return True

    import single_instance
    monkeypatch.setattr(single_instance, "SingleInstance", Other)
    handed, _inst = na.hand_off_to_running_app(["app", "ytdl://add?url=x"])
    assert handed and sent == [["ytdl://add?url=x"]]


def test_main_checks_single_instance_before_boot_and_installs_translations():
    import inspect
    src = inspect.getsource(na.main)
    assert src.index("hand_off_to_running_app(sys.argv)") < src.index("app_boot.boot()")
    assert src.index("create_app()") < src.index("i18n.install(app)") < src.index("MainWindow(")
    assert src.index("instance.listen()") < src.index("app.exec()")
    assert src.index("instance.close()") < src.index("restarter.launch(")


def test_restart_command_keeps_options_not_urls():
    cmd = na.restart_command(["native_app.py", "--x", "ytdl://add?url=y", "--smoke-test"], frozen=False)
    assert cmd == [sys.executable, "native_app.py", "--x"]
    assert na.restart_command(["C:/app.exe", "https://a"], frozen=True) == [sys.executable]


# --------------------------------------------------------------------------- #
#  系統匣與通知（F2、F3）
# --------------------------------------------------------------------------- #
class FakeTray(QObject):
    show_requested = Signal()
    pause_all_requested = Signal()
    resume_all_requested = Signal()
    quit_requested = Signal()
    notification_clicked = Signal(str)

    def __init__(self, available=True, notify_ok=True):
        super().__init__()
        self.available, self.notify_ok = available, notify_ok
        self.notes, self.summaries = [], []

    def is_available(self):
        return self.available

    def notify(self, title, body, job_id=""):
        self.notes.append((title, body, job_id))
        return self.notify_ok

    def set_summary(self, text, progress=None):
        self.summaries.append((text, progress))


def test_tray_menu_wired_to_queue_and_window(win, monkeypatch):
    tray = FakeTray()
    calls = []
    monkeypatch.setattr(win.queue, "pause_all", lambda: calls.append("pause"))
    monkeypatch.setattr(win.queue, "resume_all", lambda: calls.append("resume"))
    win.attach_tray(tray)
    tray.pause_all_requested.emit()
    tray.resume_all_requested.emit()
    assert calls == ["pause", "resume"]
    win.hide()
    tray.show_requested.emit()
    assert win.isVisible()
    shown = []
    monkeypatch.setattr(win.queue, "show_job", shown.append)
    tray.notification_clicked.emit("job42")
    assert shown == ["job42"] and win.stack.currentIndex() == 1


def test_tray_summary_follows_queue(win):
    tray = FakeTray()
    win.attach_tray(tray)
    win.queue.render([{"id": "a", "status": "downloading", "progress": 40, "title": "A"}])
    assert tray.summaries[-1][1] == 40 and "1 個下載進行中" in tray.summaries[-1][0]


def test_finished_job_notifies_only_in_background(win, monkeypatch):
    tray = FakeTray()
    win.attach_tray(tray)
    monkeypatch.setattr(win, "in_foreground", lambda: True)
    win.on_job_finished({"id": "a", "status": "done", "title": "影片 A"})
    assert tray.notes == []
    monkeypatch.setattr(win, "in_foreground", lambda: False)
    win.on_job_finished({"id": "a", "status": "done", "title": "影片 A"})
    win.on_job_finished({"id": "b", "status": "error", "title": "影片 B", "error": "影片是私人影片"})
    win.on_job_finished({"id": "c", "status": "done", "title": "清單", "failed_items": [{"index": 2}]})
    assert tray.notes == [("下載完成", "影片 A", "a"), ("下載失敗", "影片 B\n影片是私人影片", "b"),
                          ("下載完成，但有部分項目沒有成功", "清單", "c")]


def test_notification_falls_back_to_toast_without_tray(win, monkeypatch):
    win.attach_tray(FakeTray(notify_ok=False))
    monkeypatch.setattr(win, "in_foreground", lambda: False)
    win.on_job_finished({"id": "b", "status": "error", "title": "影片 B", "error": "失敗原因"})
    assert "下載失敗" in win.banner.text() and win.banner.property("error") is True


def test_close_quits_by_default_and_hides_to_tray_when_set(win, monkeypatch):
    from PySide6.QtGui import QCloseEvent
    tray = FakeTray()
    win.attach_tray(tray)
    e = QCloseEvent()
    win.closeEvent(e)
    assert e.isAccepted()  # C2 還沒合併／預設：結束
    win.show()
    monkeypatch.setattr(win.settings, "close_action", lambda: "tray", raising=False)
    nc.settings_store().remove(na.TRAY_HINT_KEY)
    e = QCloseEvent()
    win.closeEvent(e)
    assert not e.isAccepted() and win.isHidden()  # 縮到系統匣，下載繼續
    assert len(tray.notes) == 1 and tray.notes[0][0] == "YT 下載器仍在執行"
    win.show()
    win.closeEvent(QCloseEvent())
    assert len(tray.notes) == 1  # 提示只顯示一次
    tray.available = False  # 沒有系統匣：退回結束
    e = QCloseEvent()
    win.closeEvent(e)
    assert e.isAccepted()


def test_tray_quit_asks_when_busy_and_bypasses_tray_setting(app, monkeypatch):
    busy = {"v": True}
    w = na.MainWindow(FakeApi(), lambda: busy["v"])
    w.attach_tray(FakeTray())
    monkeypatch.setattr(w.settings, "close_action", lambda: "tray", raising=False)
    answers = []
    monkeypatch.setattr(w, "confirm_quit", lambda: answers.append(1) or False)
    w.show()
    w.tray.quit_requested.emit()
    assert answers and w.isVisible()  # 按取消：不結束
    monkeypatch.setattr(w, "confirm_quit", lambda: True)
    w.tray.quit_requested.emit()
    assert not w.isVisible() and w._quitting


def test_close_action_falls_back_to_quit_for_bad_values(win, monkeypatch):
    assert win.close_action() == "quit"
    monkeypatch.setattr(win.settings, "close_action", lambda: "weird", raising=False)
    assert win.close_action() == "quit"
    monkeypatch.setattr(win.settings, "close_action", lambda: 1 / 0, raising=False)
    assert win.close_action() == "quit"


# --------------------------------------------------------------------------- #
#  設定頁、更新徽章、視窗位置（SET9）
# --------------------------------------------------------------------------- #
def test_open_settings_switches_and_focuses_section(win, monkeypatch):
    win.open_settings("storage")  # C2 還沒有 focus_section：只切到設定頁
    assert win.stack.currentIndex() == 2
    seen = []
    monkeypatch.setattr(win.settings, "focus_section", seen.append, raising=False)
    win.go(0)
    win.open_settings("cookies")
    assert win.stack.currentIndex() == 2 and seen == ["cookies"]


def test_settings_badge_for_ytdlp_and_app_updates(win):
    win.on_meta(meta(latest="2099.1.1"))
    assert win.nav[2].text() == "設定　有更新"
    win.on_meta(meta())
    assert win.nav[2].text() == "設定"
    win.on_app_update({"version": "9.9.9"})  # C2 的 update_available 訊號
    assert win.nav[2].text() == "設定　有更新"


def test_window_geometry_is_remembered(app):
    w = na.MainWindow(FakeApi(), lambda: False)
    w.resize(760, 560)
    w.move(40, 50)
    w.save_geometry()
    w._quitting = True
    w.close()
    w2 = na.MainWindow(FakeApi(), lambda: False)
    assert w2.size().width() == 1000  # 建立時是預設大小，main() 呼叫 restore_geometry 才套用
    assert w2.restore_geometry() and w2.size().width() == 760 and w2.size().height() == 560
    w2._quitting = True
    w2.close()


def test_secondary_text_contrast_is_at_least_4_5(app):
    from PySide6.QtGui import QColor

    def lum(c):
        def ch(v):
            v /= 255
            return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
        q = QColor(c)
        return 0.2126 * ch(q.red()) + 0.7152 * ch(q.green()) + 0.0722 * ch(q.blue())

    t = nc.tokens(False)
    for bg in (t["bg"], t["card"]):
        hi, lo = sorted((lum(t["secondary"]), lum(bg)), reverse=True)
        assert (hi + 0.05) / (lo + 0.05) >= 4.5


# --------------------------------------------------------------------------- #
#  引擎離線時不送出解析
# --------------------------------------------------------------------------- #
def test_offline_blocks_auto_paste_and_enter(win):
    from PySide6.QtGui import QKeyEvent
    win.show_offline("無法連到下載引擎", "x")
    win.paste_link("https://youtu.be/jNQXAC9IVRw")
    assert win.download.url.text() == ""
    win.download.url.setText("https://youtu.be/jNQXAC9IVRw")
    e = QKeyEvent(QEvent.KeyPress, Qt.Key_Return, Qt.NoModifier)
    assert win.eventFilter(win.download.url, e)  # 被攔下
    assert not [c for c in win.api_fake.calls if c[1] == "/api/info"]
    assert "無法解析" in win.banner.text()
    win.set_online(True)
    assert not win.eventFilter(win.download.url, QKeyEvent(QEvent.KeyPress, Qt.Key_Return, Qt.NoModifier))


def test_offline_banner_not_rebuilt_on_every_poll(win):
    win.on_online(False, "下載引擎沒有在執行")
    first = list(win.engine_banner.action_buttons)
    win.on_online(False, "下載引擎沒有在執行")
    assert win.engine_banner.action_buttons == first  # 同樣的內容：按鈕不換
    win.on_online(False, "下載引擎中斷了連線")
    assert win.engine_banner.action_buttons != first


def test_tray_hint_retried_when_notification_not_shown(win, monkeypatch):
    tray = FakeTray(notify_ok=False)
    win.attach_tray(tray)
    monkeypatch.setattr(win.settings, "close_action", lambda: "tray")
    nc.settings_store().remove(na.TRAY_HINT_KEY)
    win.show()
    win.close()
    win.show()
    win.close()
    assert len(tray.notes) == 2  # 沒顯示成功：下次再試
    assert nc.settings_store().value(na.TRAY_HINT_KEY) is None
