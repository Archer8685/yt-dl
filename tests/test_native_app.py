"""native_app.py（主視窗、工具列、啟動流程）的行為測試；用 offscreen 平台，不需要螢幕。"""
import os
import sys
import threading
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", "C:/Windows/Fonts" if os.name == "nt" else "")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QCoreApplication, QElapsedTimer, QSettings

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
    api.last("/api/info")[3](video_info("T", "typing"))  # 解析完成後，已解析的網址可以被新的連結取代
    win.paste_link("https://youtu.be/jNQXAC9IVRw")
    assert page.url.text() == "https://youtu.be/jNQXAC9IVRw"


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
    """回傳 run(box)：記下對話框，按下指定文字的按鈕。"""
    def run(box):
        if seen is not None:
            seen.append(box)
        next(b for b in box.buttons() if b.text() == text).click()
    return run


def test_disclaimer_asked_on_first_run_then_remembered(fresh_disclaimer):
    seen = []
    assert nc.disclaimer_needed()
    assert nc.confirm_disclaimer(None, press("我了解並同意", seen))
    assert len(seen) == 1
    assert nc.DISCLAIMER_URL in seen[0].informativeText() and "有權" in seen[0].informativeText()
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
