"""app_boot：桌面 App 共用的啟動流程。"""
from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

import app_boot


class FakeServer(SimpleNamespace):
    def __init__(self, busy_checks: int):
        super().__init__(HOST="127.0.0.1", PORT=1, checks=0, busy_checks=busy_checks)

    def _port_in_use(self, host, port):
        self.checks += 1
        return self.checks <= self.busy_checks


def test_wait_port_free_skips_when_not_just_updated(monkeypatch):
    monkeypatch.delenv("YTDL_JUST_UPDATED", raising=False)
    srv = FakeServer(busy_checks=99)
    assert app_boot.wait_port_free(srv) is True
    assert srv.checks == 0  # 一般啟動不浪費時間探測連接埠


def test_wait_port_free_waits_until_released(monkeypatch):
    monkeypatch.setenv("YTDL_JUST_UPDATED", "1")
    monkeypatch.setattr(app_boot.time, "sleep", lambda s: None)
    srv = FakeServer(busy_checks=3)
    assert app_boot.wait_port_free(srv, timeout=5) is True
    assert srv.checks == 4


def test_wait_port_free_gives_up_after_timeout(monkeypatch):
    monkeypatch.setenv("YTDL_JUST_UPDATED", "1")
    monkeypatch.setattr(app_boot.time, "sleep", lambda s: None)
    assert app_boot.wait_port_free(FakeServer(busy_checks=10**9), timeout=0) is False


def test_redirect_output_noop_with_console(monkeypatch, tmp_path):
    monkeypatch.setattr(app_boot, "NO_CONSOLE", False)
    before = sys.stdout
    app_boot.redirect_output(tmp_path)
    assert sys.stdout is before
    assert not (tmp_path / "engine.log").exists()


def test_redirect_output_writes_engine_log(monkeypatch, tmp_path):
    monkeypatch.setattr(app_boot, "NO_CONSOLE", True)
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    app_boot.redirect_output(None)  # 資料夾確定前：丟掉輸出
    devnull = sys.stdout
    app_boot.redirect_output(tmp_path)
    assert devnull.closed
    print("你好")
    sys.stdout.close()
    assert (tmp_path / "engine.log").read_text(encoding="utf-8") == "你好\n"


def test_redirect_output_rotates_big_log(monkeypatch, tmp_path):
    monkeypatch.setattr(app_boot, "NO_CONSOLE", True)
    monkeypatch.setattr(app_boot, "LOG_MAX", 10)
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    (tmp_path / "engine.log").write_text("x" * 20, encoding="utf-8")
    app_boot.redirect_output(tmp_path)
    sys.stdout.close()
    assert (tmp_path / "engine.log.old").read_text(encoding="utf-8") == "x" * 20


def test_redirect_output_survives_locked_log(monkeypatch, tmp_path):
    """另一個執行中的 App 開著紀錄檔、無法換新檔時，照樣啟動（接著寫在原檔）。"""
    monkeypatch.setattr(app_boot, "NO_CONSOLE", True)
    monkeypatch.setattr(app_boot, "LOG_MAX", 10)
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    (tmp_path / "engine.log").write_text("x" * 20, encoding="utf-8")

    def locked(self, target):
        raise PermissionError(32, "being used by another process")

    monkeypatch.setattr(app_boot.Path, "replace", locked)
    app_boot.redirect_output(tmp_path)
    print("ok")
    sys.stdout.close()
    assert (tmp_path / "engine.log").read_text(encoding="utf-8") == "x" * 20 + "ok\n"


def test_check_ytdlp_ignored_without_flag(monkeypatch):
    monkeypatch.setattr(app_boot.os, "_exit", lambda code: pytest.fail("不該結束"))
    app_boot.handle_check_ytdlp(["app", "--server"])
    app_boot.handle_check_ytdlp(["app", "--check-ytdlp"])  # 少了資料夾參數


def test_check_ytdlp_exits_with_result(monkeypatch, tmp_path):
    import ytdlp_update

    monkeypatch.setattr(ytdlp_update, "check", lambda path: 0 if path == str(tmp_path) else 9)
    codes = []
    monkeypatch.setattr(app_boot.os, "_exit", codes.append)
    app_boot.handle_check_ytdlp(["app", "--check-ytdlp", str(tmp_path)])
    assert codes == [0]


def test_check_ytdlp_broken_version_exits_1_instead_of_raising(monkeypatch, tmp_path):
    """新版載入失敗時不能讓例外跑出去（打包版會跳出錯誤視窗卡住背景更新），要回報結束碼 1。"""
    import ytdlp_update

    def broken(path):
        raise ImportError("broken yt-dlp")

    monkeypatch.setattr(ytdlp_update, "check", broken)
    codes = []
    monkeypatch.setattr(app_boot.os, "_exit", codes.append)
    app_boot.handle_check_ytdlp(["app", "--check-ytdlp", str(tmp_path)])
    assert codes == [1]


def test_safe_streams_replaces_unencodable_text(monkeypatch):
    """CI 的 Windows 主控台是 cp1252：印中文不能讓程式當掉。"""
    import io
    raw = io.BytesIO()
    out = io.TextIOWrapper(raw, encoding="cp1252")
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", out)
    app_boot.safe_streams()
    print("引擎啟動於 http://127.0.0.1:8765")
    out.flush()
    assert b"http://127.0.0.1:8765" in raw.getvalue()


def test_smoke_test_requested():
    assert app_boot.smoke_test_requested(["app", "--smoke-test"])
    assert not app_boot.smoke_test_requested(["app", "--server"])


def test_install_smoke_test_noop_without_flag(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["app"])
    assert app_boot.install_smoke_test(object()) is False


def test_smoke_test_prints_ascii_and_exits_on_cp1252_console(monkeypatch):
    """CI 從這行判斷結果：主控台是 cp1252 時也要印得出來，而且一定要結束事件迴圈。"""
    import io
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QWidget
    app = QApplication.instance() or QApplication([])
    raw = io.BytesIO()
    monkeypatch.setattr(sys, "stdout", io.TextIOWrapper(raw, encoding="cp1252"))
    monkeypatch.setattr(sys, "argv", ["app", "--smoke-test"])
    w = QWidget()
    w.setWindowTitle("YT 下載器")
    w.show()
    assert app_boot.install_smoke_test(app, seconds=0.05)
    QTimer.singleShot(5000, lambda: app.exit(99))  # 保險：沒結束就讓測試失敗
    assert app.exec() == 0
    sys.stdout.flush()
    assert b"smoke test: 1 window(s) shown" in raw.getvalue()
    w.close()


def test_build_spec_prints_ascii_only():
    """spec 在 PyInstaller 子程序裡執行，CI 的主控台是 cp1252：spec 裡印出的文字只能是 ASCII。"""
    import build_app
    prints = [line for line in build_app.SPEC.splitlines() if "print(" in line]
    assert prints and all(line.isascii() for line in prints)


def test_start_engine_attaches_when_port_taken(monkeypatch):
    fake = SimpleNamespace(PORT=8765, HOST="127.0.0.1", _port_in_use=lambda h, p: True,
                           load_jobs=lambda: pytest.fail("連過去時不該載入工作"))
    url, busy = app_boot.start_engine(fake)
    assert url == "http://127.0.0.1:8765" and busy() is False


def test_installer_requires_accepting_disclaimer(tmp_path, monkeypatch):
    """Windows 安裝精靈有授權／聲明頁，內容是 DISCLAIMER.md 的純文字版。"""
    import build_app
    assert "LicenseFile={license}" in build_app.INNO_SCRIPT
    monkeypatch.setattr(build_app, "BUILD", tmp_path)
    raw = build_app.license_file().read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")  # Inno Setup 要 UTF-8 BOM 才讀得懂中文
    text = raw.decode("utf-8-sig")
    assert text.startswith("免責與合法使用聲明")
    assert "https://github.com/Archer8685/yt-dl/issues" in text and "Disclaimer (English)" in text
    for junk in ("**", "](", "<a ", "\n#", "English version below"):
        assert junk not in text


def test_access_log_is_quiet_but_warnings_still_logged():
    """engine.log 不再被 GET /api/jobs 洗版（werkzeug 的存取紀錄是 INFO），警告和錯誤照樣寫入。"""
    import logging
    log = logging.getLogger("werkzeug")
    old = log.level
    try:
        log.setLevel(logging.NOTSET)
        app_boot.quiet_access_log()
        assert not log.isEnabledFor(logging.INFO)
        assert log.isEnabledFor(logging.WARNING)
    finally:
        log.setLevel(old)


def test_start_engine_quiets_access_log(monkeypatch):
    calls = []
    monkeypatch.setattr(app_boot, "quiet_access_log", lambda: calls.append(1))
    fake = SimpleNamespace(HOST="127.0.0.1", PORT=1, _port_in_use=lambda h, p: False, load_jobs=lambda: None,
                           start_background_updates=lambda: None, app=SimpleNamespace(run=lambda **kw: None),
                           YTDLP_OVERLAY=None, yt_dlp=SimpleNamespace(version=SimpleNamespace(__version__="x")),
                           _busy=lambda: False)
    app_boot.start_engine(fake)
    assert calls == [1]


def test_bundled_app_version_follows_build_version(tmp_path, monkeypatch):
    import build_app
    monkeypatch.setattr(build_app, "BUILD", tmp_path)
    monkeypatch.setattr(build_app, "VERSION", "9.9.9")
    assert build_app.version_file().read_text(encoding="utf-8") == "9.9.9"

