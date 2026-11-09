"""native_settings.py（設定頁）的行為測試；用 offscreen 平台，不需要螢幕。"""
import os
import sys
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
import native_settings as ns


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


# --------------------------------------------------------------------------- #
#  設定、更新、重新啟動
# --------------------------------------------------------------------------- #
def test_folder_dialog_starts_from_full_path(app, monkeypatch):
    page = ns.SettingsPage(FakeApi(), lambda *a, **k: None)
    long_path = "D:\\" + "\\".join(["很長的資料夾名稱"] * 12)
    page.on_settings({"download_dir": long_path, "default_dir": "x", "disk": {}})
    page.folder.resize(200, 20)
    seen = {}
    from PySide6.QtWidgets import QFileDialog
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a: seen.setdefault("dir", a[2]) and "")
    page.choose()
    assert seen["dir"] == long_path and "…" in page.folder.text()


def test_update_button_reports_result_from_meta(app):
    api = FakeApi()
    toasts = []
    page = ns.SettingsPage(api, lambda text, error=False: toasts.append((text, error)))
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
    page = ns.SettingsPage(FakeApi(), lambda *a, **k: None)
    page.on_meta({"version": "2026.09.05", "latest": "2026.9.5", "ffmpeg": True})
    assert page.update_btn.text() == "檢查更新"
    page.on_meta({"version": "2026.09.05", "latest": "2026.10.26", "ffmpeg": True})
    assert page.update_btn.text() == "更新至 2026.10.26"


# --------------------------------------------------------------------------- #
#  外觀、文字大小
# --------------------------------------------------------------------------- #
def test_appearance_choice_is_saved_and_applied(app):
    from PySide6.QtGui import QPalette
    api = FakeApi()
    win = na.MainWindow(api, lambda: False)
    page = win.settings
    seen = []
    page.appearance_changed.connect(lambda: seen.append(nc.ui_prefs()))
    try:
        page.theme.set_value("dark")
        page.theme.changed.emit("dark")
        page.font_size.set_value("large")
        page.font_size.changed.emit("large")
        assert seen[-1] == ("dark", "large")
        na.apply_theme(app, win, "")
        if not nc.IS_MAC:
            assert app.font().pixelSize() == round(13 * nc.FONT_SCALE["large"])
            assert app.palette().color(QPalette.Window) == QColor(nc.tokens(True)["bg"])
        assert f"font-size: {round(15 * nc.FONT_SCALE['large'])}px" in app.styleSheet()
        again = ns.SettingsPage(api, lambda *a, **k: None)  # 重新開啟 App 時選項還在
        assert again.theme.value() == "dark" and again.font_size.value() == "large"
    finally:
        nc.save_ui_prefs("system", "medium")
        na.apply_theme(app, win, "", dark=False)
        win.close()


# --------------------------------------------------------------------------- #
#  YouTube Premium
# --------------------------------------------------------------------------- #
@pytest.fixture
def premium_page(app):
    nc.settings_store().remove("premium/status")
    api = FakeApi()
    adv = native_options.AdvancedOptions(api)
    toasts = []
    page = ns.SettingsPage(api, lambda text, error=False: toasts.append(text), adv)
    yield page, api, adv, toasts
    nc.settings_store().remove("premium/status")


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
    again = ns.SettingsPage(FakeApi(), lambda *a, **k: None, adv)  # 重新開啟也看得到上次的結果
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
#  關於
# --------------------------------------------------------------------------- #
def test_settings_about_shows_version_and_disclaimer_link(app, monkeypatch):
    page = ns.SettingsPage(FakeApi(), lambda *a, **k: None)
    version = (Path(__file__).resolve().parent.parent / "VERSION").read_text(encoding="utf-8").strip()
    assert nc.app_version() == version
    assert page.app_version.text() == version
    assert "有權" in page.disclaimer_text.text()
    opened = []
    monkeypatch.setattr(ns.QDesktopServices, "openUrl", lambda u: opened.append(u.toString()))
    page.disclaimer_link.click()
    assert opened == [nc.DISCLAIMER_URL]
