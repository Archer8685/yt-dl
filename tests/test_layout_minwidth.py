"""最小視窗（Windows 720×520、macOS 800×520，見 native_app.MIN_WINDOW_WIDTH）時，
中文和英文介面每一頁的內容都不能比可視寬度寬（驗收第 13 點：英文較長時版面不破）。

英文用已編譯的 i18n/yt_dl_en.qm；測試結束後 i18n.uninstall() 換回原文，不影響其他測試。
"""
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", "C:/Windows/Fonts" if os.name == "nt" else "")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QCoreApplication, QElapsedTimer, QSettings
from PySide6.QtWidgets import QScrollArea

import i18n
import native_app as na
import native_common as nc
import native_options
from tests.test_accessibility import JOBS, PLAYLIST, VIDEO, FakeApi


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    ini = str(tmp_path_factory.mktemp("qsettings") / "native.ini")
    native_options.QSettings = nc.QSettings = lambda *a, **k: QSettings(ini, QSettings.IniFormat)
    a, _ = na.create_app()
    return a


def wait(ms=80):
    t = QElapsedTimer()
    t.start()
    while t.elapsed() < ms:
        QCoreApplication.processEvents()


@pytest.fixture(params=["zh_TW", "en"])
def win(app, request):
    lang = i18n.install(app, request.param)
    assert lang == request.param
    w = na.MainWindow(FakeApi(), lambda: False)
    w.resize(w.minimumWidth(), 700)
    w.show()
    wait()
    yield w
    w.close()
    w.deleteLater()
    i18n.uninstall()


def overflow(page) -> list[str]:
    """頁面捲動區的內容最小寬度比可視寬度寬多少（沒超出回傳空清單）。"""
    out = []
    for area in page.findChildren(QScrollArea):
        inner = area.widget()
        if inner is None or not area.isVisible():
            continue
        need, have = inner.minimumSizeHint().width(), area.viewport().width()
        if need > have:
            out.append(f"{type(page).__name__}: 內容 {need}px > 可視 {have}px")
    return out


def test_download_page_fits(win):
    d = win.download
    d.on_info(VIDEO)
    for s in d.advanced.sections.values():
        s.set_expanded(True)
    for mode in d.mode.buttons:
        d.mode.buttons[mode].click()
        wait()
        assert overflow(d) == [], mode
    d.on_info(PLAYLIST)
    wait()
    assert overflow(d) == []


def test_queue_page_fits(win):
    """I2 截圖：狀態文字和 4 個批次按鈕在同一行時，中英文都超出（中文 718px、英文 794px）。"""
    q = win.queue
    q._timer.stop()
    jobs = JOBS + [{"id": "5", "url": "https://youtu.be/e", "title": "清單", "status": "done", "progress": 100,
                    "files": [{"name": "a.mp4", "size": 1}], "done_count": 4, "total_count": 5,
                    "failed_items": [{"index": 3, "title": "x", "error": "私人影片", "error_code": "private_video"}]}]
    q.render(jobs)
    win.go(1)
    wait()
    assert overflow(q) == []


def test_settings_page_fits(win):
    win.go(2)
    wait()
    assert overflow(win.settings) == []


@pytest.mark.parametrize("is_mac, width", [(True, 800), (False, 720)])
def test_minimum_window_width_per_platform(is_mac, width):
    """macOS 的系統字型較寬，英文介面在 720 寬時會撐出橫向捲軸：macOS 最小寬度 800，其他平台 720。"""
    assert na.min_window_width(is_mac) == width
    assert na.MIN_WINDOW_WIDTH == na.min_window_width(nc.IS_MAC)


def test_window_uses_minimum_size(win):
    assert (win.minimumWidth(), win.minimumHeight()) == (na.MIN_WINDOW_WIDTH, na.MIN_WINDOW_HEIGHT)


# --------------------------------------------------------------------------- 個別修正

def test_job_row_actions_wrap_when_narrow_and_come_back(app):
    import native_queue as nq
    row = nq.JobRow(FakeApi(), lambda *a: None)
    row.update_job({"id": "p", "url": "u", "title": "t", "status": "done", "progress": 100,
                    "files": [{"name": "a.mp4", "size": 1}], "done_count": 4, "total_count": 5,
                    "failed_items": [{"index": 3, "title": "x", "error": "e"}]})
    row.resize(900, 120)
    row.show()
    wait()
    assert not row._wrapped and row._top.indexOf(row.actions_box) >= 0
    row.resize(380, 160)
    wait()
    assert row._wrapped and row._wrap_row.indexOf(row.actions_box) >= 0
    assert row.minimumSizeHint().width() < 380
    row.resize(900, 120)
    wait()
    assert not row._wrapped and row._top.indexOf(row.actions_box) >= 0
    row.close()


def test_popup_width_is_capped(app):
    from native_common import PopUp
    short = PopUp([("a", "A"), ("b", "B")])
    long = PopUp([("a", "A"), ("b", "x" * 120)])
    assert short.sizeHint().width() < long.sizeHint().width() <= long._cap()
    assert long.minimumSizeHint().width() <= long._cap()


def test_disclaimer_keeps_line_break_between_sentences(app):
    """「…無任何關聯。」和「請只下載…」不能直接接起來：英文會變成「…Google.Only download…」。"""
    from native_settings import SettingsPage
    page = SettingsPage(FakeApi(), lambda *a, **k: None)
    assert "\n" in page.disclaimer_text.text()
    page.deleteLater()


def test_block_row_hint_wraps_on_its_own_line(app):
    from PySide6.QtWidgets import QLabel, QLineEdit

    from native_options import block_row
    row = block_row("標題", QLineEdit(), "很長的說明 " * 20)
    hints = [lb for lb in row.findChildren(QLabel) if lb.objectName() == "hint"]
    assert hints and hints[0].wordWrap()
    assert row.minimumSizeHint().width() < 400
