"""native_tray.TrayController：選單動作、進度提示、通知點擊都只透過訊號往外送。用 offscreen 平台，不需要螢幕。"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QTranslator
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

import native_tray
from native_tray import TrayController


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def tray(app):
    t = TrayController(visible=False)
    yield t
    t.dispose()


def record(signal):
    got = []
    signal.connect(lambda *a: got.append(a))
    return got


def test_menu_layout(tray):
    texts = [a.text() for a in tray.menu.actions() if not a.isSeparator()]
    assert texts == ["顯示視窗", "沒有進行中的下載", "暫停全部", "繼續全部", "結束"]
    assert tray.tray.contextMenu() is tray.menu
    assert tray.progress_action.isEnabled() is False


@pytest.mark.parametrize("action, signal", [
    ("show_action", "show_requested"),
    ("pause_action", "pause_all_requested"),
    ("resume_action", "resume_all_requested"),
    ("quit_action", "quit_requested"),
])
def test_menu_actions_emit_signals(tray, action, signal):
    got = record(getattr(tray, signal))
    getattr(tray, action).trigger()
    assert got == [()]


def test_summary_tooltip_and_menu(tray):
    tray.set_summary(TrayController.active_text(2), 45.4)
    assert tray.summary() == "2 個下載中 · 45%"
    assert tray.progress_action.text() == "2 個下載中 · 45%"
    assert tray.tray.toolTip() == "YT 下載器\n2 個下載中 · 45%"

    tray.set_summary("1 個下載中", None)
    assert tray.summary() == "1 個下載中"

    tray.set_summary("", 80)  # 沒有進行中的下載：不顯示百分比
    assert tray.summary() == "沒有進行中的下載"
    assert tray.tray.toolTip() == "YT 下載器\n沒有進行中的下載"


@pytest.mark.parametrize("progress, shown", [(-5, "0%"), (150, "100%"), (99.6, "100%"), ("37", "37%")])
def test_progress_is_clamped(tray, progress, shown):
    tray.set_summary("下載中", progress)
    assert tray.summary().endswith(shown)


@pytest.mark.parametrize("bad", ["abc", float("nan"), float("inf"), object()])
def test_bad_progress_is_ignored(tray, bad):
    tray.set_summary("下載中", bad)
    assert tray.summary() == "下載中"


def test_tooltip_is_truncated_for_windows(tray):
    tray.set_summary("很長" * 200, 10)
    tip = tray.tray.toolTip()
    assert len(tip) <= native_tray.TOOLTIP_LIMIT
    assert tip.endswith("…")


def test_active_text_uses_count():
    assert TrayController.active_text(3) == "3 個下載中"


def test_notify_without_system_tray_returns_false(tray, monkeypatch):
    monkeypatch.setattr(TrayController, "is_available", staticmethod(lambda: False))
    shown = []
    monkeypatch.setattr(tray.tray, "showMessage", lambda *a: shown.append(a))
    assert tray.notify("下載完成", "影片", "job1") is False
    assert shown == []


def test_notify_and_click_emits_job_id(tray, monkeypatch):
    monkeypatch.setattr(TrayController, "is_available", staticmethod(lambda: True))
    monkeypatch.setattr(QSystemTrayIcon, "supportsMessages", staticmethod(lambda: True))
    shown = []
    monkeypatch.setattr(tray.tray, "showMessage", lambda *a: shown.append(a))
    monkeypatch.setattr(tray.tray, "setVisible", lambda v: None)
    clicked = record(tray.notification_clicked)

    assert tray.notify("下載完成", "影片 A", "job-a") is True
    assert tray.notify("下載失敗", "影片 B", "job-b") is True
    assert [s[:2] for s in shown] == [("下載完成", "影片 A"), ("下載失敗", "影片 B")]
    tray.tray.messageClicked.emit()
    assert clicked == [("job-b",)]  # 系統只記得最後一則

    tray.notify("提示", "App 會在背景繼續下載")  # 沒有 job_id
    tray.tray.messageClicked.emit()
    assert clicked[-1] == ("",)


@pytest.mark.parametrize("reason, mac, expected", [
    (QSystemTrayIcon.ActivationReason.Trigger, False, 1),
    (QSystemTrayIcon.ActivationReason.DoubleClick, False, 0),  # Windows 點兩下會先送 Trigger，不要喚醒兩次
    (QSystemTrayIcon.ActivationReason.Trigger, True, 0),  # macOS 點選單列圖示是開選單
    (QSystemTrayIcon.ActivationReason.DoubleClick, True, 1),
    (QSystemTrayIcon.ActivationReason.Context, False, 0),
    (QSystemTrayIcon.ActivationReason.MiddleClick, False, 0),
])
def test_activation(tray, monkeypatch, reason, mac, expected):
    monkeypatch.setattr(native_tray, "IS_MAC", mac)
    got = record(tray.show_requested)
    tray.tray.activated.emit(reason)
    assert len(got) == expected


def test_dispose_is_idempotent_and_deletes_menu_now(app):
    import shiboken6

    t = TrayController(visible=False)
    menu = t.menu
    t.dispose()
    assert not shiboken6.isValid(menu)  # 不靠 deleteLater：App 結束時事件迴圈已經停了
    assert t.tray.contextMenu() is None
    t.dispose()


def test_visible_only_when_tray_available(app, monkeypatch):
    monkeypatch.setattr(TrayController, "is_available", staticmethod(lambda: False))
    t = TrayController(visible=True)
    try:
        assert t.is_visible() is False
    finally:
        t.dispose()


def test_icon_default_and_custom(app):
    assert not native_tray.default_icon().isNull()  # assets/icon-128.png
    pm = QPixmap(16, 16)
    pm.fill()
    custom = QIcon(pm)
    t = TrayController(icon=custom, visible=False)
    try:
        assert t.tray.icon().cacheKey() == custom.cacheKey()
    finally:
        t.dispose()
    t = TrayController(icon=QIcon(), visible=False)  # 空圖示退回 App 圖示
    try:
        assert not t.tray.icon().isNull()
    finally:
        t.dispose()


class FakeEnglish(QTranslator):
    """把 TrayController 的字串都換成英文樣子，確認每個字串都有包翻譯函式、context 正確。"""

    def translate(self, context, source, disambiguation=None, n=-1):
        if context != "TrayController":
            return None
        table = {
            "顯示視窗": "Show Window", "暫停全部": "Pause All", "繼續全部": "Resume All", "結束": "Quit",
            "沒有進行中的下載": "No active downloads", "YT 下載器": "YT Downloader",
            "{summary} · {percent}%": "{summary} - {percent}%", "%n 個下載中": "%n downloading",
        }
        return table.get(source)


def test_strings_are_translatable(app):
    tr = FakeEnglish()
    QCoreApplication.installTranslator(tr)
    try:
        t = TrayController(visible=False)
        try:
            texts = [a.text() for a in t.menu.actions() if not a.isSeparator()]
            assert texts == ["Show Window", "No active downloads", "Pause All", "Resume All", "Quit"]
            assert t.tray.toolTip() == "YT Downloader\nNo active downloads"
            t.set_summary(TrayController.active_text(2), 50)
            assert t.summary() == "2 downloading - 50%"
        finally:
            t.dispose()
    finally:
        QCoreApplication.removeTranslator(tr)
