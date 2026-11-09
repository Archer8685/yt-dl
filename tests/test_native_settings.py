"""native_settings.py（設定頁）的行為測試；用 offscreen 平台，不需要螢幕。"""
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", "C:/Windows/Fonts" if os.name == "nt" else "")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QCoreApplication, QElapsedTimer, QSettings, QUrl
from PySide6.QtGui import QColor

import app_update
import i18n
import native_app as na
import native_common as nc
import native_options
import native_settings as ns


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    # 介面會存 QSettings：測試寫到暫存的 ini 檔，不要動到這台電腦的真實設定
    ini = str(tmp_path_factory.mktemp("qsettings") / "native.ini")
    native_options.QSettings = nc.QSettings = lambda *a, **k: QSettings(ini, QSettings.IniFormat)
    i18n._settings = lambda: QSettings(ini, QSettings.IniFormat)  # 語言設定也不要寫到真實設定
    a, _ = na.create_app()
    return a


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """測試不連 GitHub：App 新版一律用假的 fetch_latest。"""
    def fake():
        raise OSError("offline in tests")
    monkeypatch.setattr(app_update, "fetch_latest", fake)


def answer(page, monkeypatch, yes=True):
    """換掉詢問對話框：回答 yes，並記下問了什麼。"""
    asked = []
    monkeypatch.setattr(page, "_ask", lambda text, info, ok_text, cancel_text=None, **k:
                        asked.append((text, info, ok_text)) or yes)
    return asked


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


def test_update_ytdlp_asks_first_and_cancel_does_nothing(app, monkeypatch):
    api = FakeApi()
    page = ns.SettingsPage(api, lambda *a, **k: None)
    asked = answer(page, monkeypatch, yes=False)
    page.update_ytdlp()
    assert asked and "重新開啟" in asked[0][1] and "暫停" in asked[0][1]  # SET2：說明會重新啟動、下載會怎樣
    assert not [c for c in api.calls if c[1] == "/api/update"] and page.update_btn.isEnabled()
    page.on_meta({"version": "1", "update_ready": True})
    page.update_ytdlp()
    assert asked[-1][2] == "重新啟動"


def test_update_button_reports_result_from_meta(app, monkeypatch):
    api = FakeApi()
    toasts = []
    page = ns.SettingsPage(api, lambda text, error=False: toasts.append((text, error)))
    answer(page, monkeypatch)
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
    api.last("/api/meta")[3]({"update_running": False, "update_message": "Update failed: network error",
                              "update_failed": True, "version": "1"})
    assert toasts[-1] == ("Update failed: network error", True)  # 依 update_failed 判斷，不比對中文前綴
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
    adv.cookie_exists = True  # 已上傳 cookies.txt，但沒選 Cookie 來源（例如從舊版升級）
    adv.cookie_source.setCurrentIndex(adv.cookie_source.findData(""))
    page.show_premium(page.saved_premium())
    assert page.premium_status.text() == "尚未檢查"
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


def test_premium_check_without_cookies_explains(premium_page, monkeypatch):
    page, api, adv, _ = premium_page
    adv.cookie_exists = False
    adv.cookie_source.setCurrentIndex(adv.cookie_source.findData(""))
    page.check_premium()
    assert not [c for c in api.calls if c[1] == "/api/auth/test"]
    # SET4：沒有 Cookie 是中性的「未設定」（不是紅字錯誤），並有匯出說明的連結
    assert page.premium_status.text() == "未設定" and page.premium_status.objectName() == "subtitle"
    assert "cookies.txt" in page.premium_detail.text()
    assert page.premium_check.isHidden() and page.cookie_delete.isHidden()
    opened = []
    monkeypatch.setattr(ns.QDesktopServices, "openUrl", lambda u: opened.append(u.toString()))
    page.cookie_help.click()
    assert opened == [i18n.guide_url("cookies")]


def test_saved_premium_status_hidden_when_cookies_gone(premium_page):
    page, _api, _adv, _ = premium_page
    nc.settings_store().setValue("premium/status", '{"logged_in": true, "premium": true}')
    page.on_meta({"version": "1", "cookies_file": True})
    assert page.premium_status.text() == "Premium ✓" and not page.cookie_delete.isHidden()
    page.on_meta({"version": "1", "cookies_file": False})
    assert page.premium_status.text() == "未設定"


def test_delete_cookies_confirms_then_deletes(premium_page, monkeypatch):
    page, api, adv, toasts = premium_page
    nc.settings_store().setValue("premium/status", '{"logged_in": true, "premium": true}')
    page.on_meta({"version": "1", "cookies_file": True})
    asked = answer(page, monkeypatch, yes=False)
    page.delete_cookies()
    assert asked and not [c for c in api.calls if c[0] == "DELETE"]
    answer(page, monkeypatch, yes=True)
    page.delete_cookies()
    call = api.last("/api/cookies")
    assert call[0] == "DELETE"
    call[3]({"exists": False})
    assert page.premium_status.text() == "未設定" and page.cookie_delete.isHidden()
    assert page.saved_premium() == {} and adv.cookie_exists is False
    assert toasts[-1] == "已刪除 cookies.txt"


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
    shown = []  # 和第一次開啟的聲明對話框一樣：有打包 DISCLAIMER.md 就在 App 裡顯示，沒有才開 GitHub
    monkeypatch.setattr(ns, "show_full_disclaimer", lambda parent=None: shown.append(parent))
    page.disclaimer_link.click()
    assert shown == [page.window()]


# --------------------------------------------------------------------------- #
#  v1.3.0 C2：儲存位置（SET6、DL12）、同時下載數（SET8）
# --------------------------------------------------------------------------- #
def test_storage_texts_and_env_lock(app):
    page = ns.SettingsPage(FakeApi(), lambda *a, **k: None)
    assert page.reset.text() == "改回預設資料夾" and page.reset_all_btn.text() == "重設所有偏好…"
    page.on_settings({"download_dir": "D:\\yt", "default_dir": "C:\\dl", "disk": {"free": 10 * 1024 ** 3}})
    assert page.change_btn.isEnabled() and not page.reset.isHidden() and page.env_note.isHidden()
    page.on_settings({"download_dir": "D:\\yt", "default_dir": "C:\\dl", "disk": {}, "env_locked": True})
    assert not page.change_btn.isEnabled() and page.reset.isHidden()
    assert not page.env_note.isHidden() and "YTDL_DOWNLOAD_DIR" in page.env_note.text()


def test_unreachable_download_dir_shows_full_path(app):
    page = ns.SettingsPage(FakeApi(), lambda *a, **k: None)
    page.on_settings({"download_dir": "Z:\\nodrive\\yt", "default_dir": "C:\\dl", "disk": {"free": 1},
                      "download_dir_error": "Z: 目前無法存取"})
    assert not page.dir_error.isHidden() and "Z:\\nodrive\\yt" in page.dir_error.text()
    assert page.disk.text() == ""
    page.on_settings({"download_dir": "C:\\dl", "default_dir": "C:\\dl", "disk": {}, "download_dir_error": None})
    assert page.dir_error.isHidden()


def test_parallel_downloads_saved_immediately(app):
    api = FakeApi()
    toasts = []
    page = ns.SettingsPage(api, lambda text, error=False: toasts.append((text, error)))
    assert page.r_parallel.isHidden()  # 舊版引擎沒有 parallel：不顯示
    page.on_settings({"download_dir": "x", "default_dir": "x", "disk": {}, "parallel": 3})
    assert not page.r_parallel.isHidden() and page.parallel.currentData() == 3
    assert [page.parallel.itemData(i) for i in range(page.parallel.count())] == [1, 2, 3, 4, 5]
    assert not [c for c in api.calls if c[1] == "/api/settings"]  # 顯示目前值不會送出
    page.parallel.select(5)
    call = api.last("/api/settings")
    assert call[0] == "POST" and call[2] == {"parallel": 5}
    call[3]({"download_dir": "x", "default_dir": "x", "disk": {}, "parallel": 5})
    assert "5" in toasts[-1][0] and not toasts[-1][1]
    page.parallel.select(1)
    api.last("/api/settings")[4]("引擎錯誤")
    assert page.parallel.currentData() == 5 and toasts[-1][1]  # 失敗：改回原本的值


# --------------------------------------------------------------------------- #
#  關閉視窗時（F3）
# --------------------------------------------------------------------------- #
def test_close_action_default_quit_and_saved(app, monkeypatch):
    monkeypatch.setattr(ns, "tray_available", lambda: True)
    nc.settings_store().remove(ns.CLOSE_ACTION_KEY)
    page = ns.SettingsPage(FakeApi(), lambda *a, **k: None)
    try:
        assert page.close_action() == "quit" and page.close_choice.isEnabled()
        page.close_choice.select("tray")
        assert page.close_action() == "tray"
        assert ns.SettingsPage(FakeApi(), lambda *a, **k: None).close_action() == "tray"  # 重開 App 還在
        monkeypatch.setattr(ns, "tray_available", lambda: False)
        other = ns.SettingsPage(FakeApi(), lambda *a, **k: None)
        assert other.close_action() == "quit" and not other.close_choice.isEnabled()
        assert nc.settings_store().value(ns.CLOSE_ACTION_KEY) == "tray"  # 不支援時只顯示成結束，不改設定
    finally:
        nc.settings_store().remove(ns.CLOSE_ACTION_KEY)


def test_reset_all_preferences(app, monkeypatch):
    monkeypatch.setattr(ns, "tray_available", lambda: True)
    toasts = []
    page = ns.SettingsPage(FakeApi(), lambda text, error=False: toasts.append(text))
    page.close_choice.select("tray")
    asked = answer(page, monkeypatch, yes=False)
    page.reset_all()
    assert page.close_action() == "tray" and "語言" in asked[0][1]
    answer(page, monkeypatch, yes=True)
    page.reset_all()
    assert page.close_action() == "quit" and toasts[-1] == "已重設所有偏好"
    nc.settings_store().remove(ns.CLOSE_ACTION_KEY)


# --------------------------------------------------------------------------- #
#  語言（F13）
# --------------------------------------------------------------------------- #
@pytest.fixture
def lang_page(app, monkeypatch):
    i18n.set_language("system")
    monkeypatch.setattr(i18n, "current_language", lambda: "zh_TW")
    toasts = []
    page = ns.SettingsPage(FakeApi(), lambda text, error=False: toasts.append(text))
    yield page, toasts
    i18n.set_language("system")


def test_language_choices(lang_page):
    page, _ = lang_page
    assert [page.language.itemData(i) for i in range(page.language.count())] == ["system", "zh_TW", "en"]
    assert page.language.itemText(2) == "English" and page.language.currentData() == "system"


def test_language_change_offers_restart(lang_page, monkeypatch):
    page, toasts = lang_page
    restarted = []
    monkeypatch.setattr(ns, "restart_app", lambda: restarted.append(1) or True)
    asked = answer(page, monkeypatch, yes=False)
    page.language.select("en")
    assert i18n.get_setting() == "en" and asked and asked[0][2] == "立即重新啟動" and "English" in asked[0][1]
    assert not restarted and "下次開啟" in toasts[-1]
    asked = answer(page, monkeypatch, yes=True)
    page.language.select("zh_TW")  # 目前就是中文：不用重新啟動
    assert i18n.get_setting() == "zh_TW" and not asked
    page.language.select("en")
    assert restarted == [1]


def test_language_restart_without_handler_explains(lang_page, monkeypatch):
    page, toasts = lang_page
    monkeypatch.delitem(sys.modules, "server", raising=False)
    answer(page, monkeypatch, yes=True)
    page.language.select("en")
    assert "重新開啟" in toasts[-1]


def test_restart_app_uses_engine_restart_handler(monkeypatch):
    import types
    seen = []
    fake = types.SimpleNamespace(RESTART_HANDLER=lambda cmd, env: seen.append((cmd, env)), FROZEN=False)
    monkeypatch.setitem(sys.modules, "server", fake)
    monkeypatch.setenv("YTDL_JUST_UPDATED", "1")
    assert ns.restart_app() is True
    cmd, env = seen[0]
    assert cmd[0] == sys.executable and "YTDL_JUST_UPDATED" not in env


# --------------------------------------------------------------------------- #
#  focus_section（給主視窗）
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("section", ["storage", "cookies", "language", "about", "general", "update"])
def test_focus_section_scrolls_to_section(app, section):
    from PySide6.QtCore import QPoint
    page = ns.SettingsPage(FakeApi(), lambda *a, **k: None)
    page.resize(800, 400)
    page.show()
    try:
        QCoreApplication.processEvents()
        assert page.focus_section(section) is True
        QCoreApplication.processEvents()
        head = page._anchors["about" if section == "update" else section][0]
        sc = page._scroll
        y = head.mapTo(sc.viewport(), QPoint(0, 0)).y()
        assert 0 <= y < sc.viewport().height()  # 區塊標題捲進看得到的範圍
    finally:
        page.close()
    assert page.focus_section("nope") is False


# --------------------------------------------------------------------------- #
#  App 新版（SET1）
# --------------------------------------------------------------------------- #
INFO = {"version": "99.0.0", "tag": "v99.0.0", "url": "https://github.com/Archer8685/yt-dl/releases/tag/v99.0.0",
        "download_url": "https://github.com/Archer8685/yt-dl/releases/latest/download/YT-Downloader-Setup-Windows.exe",
        "asset": "YT-Downloader-Setup-Windows.exe"}


@pytest.fixture
def clean_update(app):
    for k in (app_update.KEY_CHECKED, app_update.KEY_LATEST, app_update.KEY_SKIPPED):
        nc.settings_store().remove(k)
    yield
    for k in (app_update.KEY_CHECKED, app_update.KEY_LATEST, app_update.KEY_SKIPPED):
        nc.settings_store().remove(k)


def test_app_update_shown_and_skippable(clean_update, monkeypatch):
    monkeypatch.setattr(app_update, "fetch_latest", lambda: dict(INFO))
    toasts = []
    page = ns.SettingsPage(FakeApi(), lambda text, error=False: toasts.append(text))
    seen = []
    page.update_available.connect(seen.append)
    assert page.app_update_row.isHidden()
    assert page.check_app_update(manual=True)
    assert wait_until(lambda: seen)
    assert seen[-1]["version"] == "99.0.0" and not page.app_update_row.isHidden()
    assert "99.0.0" in page.app_update_text.text() and page.app_update_info()["version"] == "99.0.0"
    opened = []
    monkeypatch.setattr(ns.QDesktopServices, "openUrl", lambda u: opened.append(u.toString()))
    page.app_update_download.click()
    page.app_update_notes.click()
    assert opened == [INFO["download_url"], INFO["url"]]  # 只開下載頁，不自動安裝
    page.app_update_skip.click()
    assert seen[-1] == {} and page.app_update_row.isHidden() and "99.0.0" in toasts[-1]
    assert app_update.skipped_version() == "99.0.0"
    again = ns.SettingsPage(FakeApi(), lambda *a, **k: None)  # 略過後重新開啟也不再提示
    assert again.app_update_row.isHidden()


def test_cached_update_emitted_after_construction(clean_update):
    nc.settings_store().setValue(app_update.KEY_LATEST, ns.json.dumps(INFO))
    page = ns.SettingsPage(FakeApi(), lambda *a, **k: None)
    seen = []
    page.update_available.connect(seen.append)  # 主視窗在建立之後才連接
    assert not page.app_update_row.isHidden()
    assert wait_until(lambda: seen) and seen[0]["version"] == "99.0.0"


def test_manual_check_failure_is_quiet_message(clean_update):
    toasts = []
    page = ns.SettingsPage(FakeApi(), lambda text, error=False: toasts.append((text, error)))
    page.check_app_update(manual=True)
    assert not page.app_update_check.isEnabled()
    assert wait_until(lambda: toasts)
    assert toasts[-1][1] is False and "無法檢查" in toasts[-1][0]
    assert page.app_update_check.isEnabled() and page.app_update_row.isHidden()


def test_no_auto_check_in_tests(clean_update, monkeypatch):
    calls = []
    monkeypatch.setattr(app_update, "fetch_latest", lambda: calls.append(1))
    page = ns.SettingsPage(FakeApi(), lambda *a, **k: None)
    page.on_meta({"version": "1"})
    QCoreApplication.processEvents()
    assert not ns.auto_update_check_enabled() and not calls


# --------------------------------------------------------------------------- #
#  關於：使用說明、紀錄、回報問題、授權（ERR4）
# --------------------------------------------------------------------------- #
def test_about_links(app, monkeypatch):
    page = ns.SettingsPage(FakeApi(), lambda *a, **k: None)
    opened = []
    monkeypatch.setattr(ns.QDesktopServices, "openUrl", lambda u: opened.append(u))
    page.guide_btn.click()
    page.license_link.click()
    page.third_party_link.click()
    page.logs_btn.click()
    assert opened[0].toString() == i18n.guide_url()
    assert opened[1].toString().endswith("/LICENSE") and opened[2].toString().endswith("THIRD_PARTY_NOTICES.md")
    assert opened[3].isLocalFile() and Path(opened[3].toLocalFile()) == ns.log_dir()
    assert "MIT" in page.license_link.text()


def test_report_issue_url_has_versions_but_no_private_data(app, monkeypatch):
    from urllib.parse import parse_qs, urlsplit
    page = ns.SettingsPage(FakeApi(), lambda *a, **k: None)
    page.on_settings({"download_dir": "D:\\秘密資料夾", "default_dir": "x", "disk": {}})
    page.on_meta({"version": "2026.10.26", "cookies_file": False})
    opened = []
    monkeypatch.setattr(ns.QDesktopServices, "openUrl", lambda u: opened.append(u.toString(QUrl.FullyEncoded)))
    page.report_btn.click()
    url = opened[0]
    assert url.startswith("https://github.com/Archer8685/yt-dl/issues/new?")
    q = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
    assert q["template"] == "bug_report.yml" and q["app_version"] == nc.app_version()
    assert q["language"] in ("中文（繁體）", "English") and q["os"]
    assert "yt-dlp: 2026.10.26" in q["extra"]
    decoded = " ".join(q.values())
    for private in ("秘密", "D:\\", "youtube.com/watch", os.path.expanduser("~"),
                    os.environ.get("USERNAME") or "@@"):
        assert private not in decoded


def test_issue_os_matches_form_options():
    form = Path(__file__).resolve().parent.parent / ".github" / "ISSUE_TEMPLATE" / "bug_report.yml"
    text = form.read_text(encoding="utf-8")
    assert ns.issue_os() in text and ns.ISSUE_OS_OTHER in text
    for name in ns.ISSUE_LANGUAGES.values():
        assert name in text
    for field in ("id: app_version", "id: language", "id: os", "id: extra"):
        assert field in text


def test_manual_check_shows_skipped_version_again(clean_update, monkeypatch):
    monkeypatch.setattr(app_update, "fetch_latest", lambda: dict(INFO))
    app_update.skip_version("99.0.0")
    page = ns.SettingsPage(FakeApi(), lambda *a, **k: None)
    page.check_app_update(manual=True)
    assert wait_until(lambda: not page.app_update_row.isHidden())
    assert app_update.skipped_version() == ""


def test_manual_click_during_auto_check_reports_result(clean_update, monkeypatch):
    toasts = []
    page = ns.SettingsPage(FakeApi(), lambda text, error=False: toasts.append(text))
    page._checker.running = True  # 自動檢查正在連線
    assert page.check_app_update(manual=True) is False
    assert not page.app_update_check.isEnabled()
    page._checker.finished.emit(None, False)  # 自動檢查的結果回來
    assert page.app_update_check.isEnabled() and toasts and "無法檢查" in toasts[-1]
