"""無障礙驗收（ROADMAP 4.1 第 9 點、5.4「D」）：走過每一頁，每個可以取得焦點的元件都要有名稱；
QScrollArea 不吃 Tab；側邊欄和分段控制可以用方向鍵切換。

「有名稱」用朗讀程式實際拿到的值判斷：QAccessible 介面的 Name（按鈕文字、accessibleName、
setBuddy 的標籤都算），不是只看有沒有呼叫 setAccessibleName。
"""
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", "C:/Windows/Fonts" if os.name == "nt" else "")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QCoreApplication, QElapsedTimer, QSettings, Qt
from PySide6.QtGui import QAccessible
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractScrollArea, QScrollArea, QWidget

import native_app as na
import native_common as nc
import native_options


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    # 介面會存 QSettings：寫到暫存的 ini 檔，不要動到這台電腦的真實設定
    ini = str(tmp_path_factory.mktemp("qsettings") / "native.ini")
    native_options.QSettings = nc.QSettings = lambda *a, **k: QSettings(ini, QSettings.IniFormat)
    a, _ = na.create_app()
    return a


class FakeApi:
    """不連引擎：只記下請求，不回應。"""

    def __init__(self):
        self.calls = []

    def post(self, path, body=None, ok=None, err=None, timeout_ms=0):
        self.calls.append(("POST", path))

    def get(self, path, ok=None, err=None, timeout_ms=0):
        self.calls.append(("GET", path))

    def delete(self, path, ok=None, err=None, timeout_ms=0):
        self.calls.append(("DELETE", path))

    def image(self, url, ok, timeout_ms=0):
        self.calls.append(("IMG", url))


VIDEO = {
    "type": "video", "title": "Big Buck Bunny", "id": "aqz-KE-bpKQ",
    "webpage_url": "https://www.youtube.com/watch?v=aqz-KE-bpKQ", "duration": 634, "heights": [1080, 720],
    "thumbnail": None, "uploader": "Blender",
    "audio_tracks": [{"lang": "en", "label": "English", "original": True}],
    "subtitles": [{"lang": "en", "name": "English"}], "auto_captions": [{"lang": "ja", "name": "Japanese"}],
    "chapters": [{"title": "Intro", "start": 0, "end": 60}],
}
PLAYLIST = {
    "type": "playlist", "title": "清單", "uploader": "頻道",
    "entries": [{"index": i, "title": f"影片 {i}", "duration": 60 + i, "uploader": "頻道"} for i in range(1, 6)],
}
JOBS = [
    {"id": "1", "url": "https://youtu.be/a", "title": "下載中", "status": "downloading", "progress": 40},
    {"id": "2", "url": "https://youtu.be/b", "title": "失敗", "status": "error", "progress": 0,
     "error": "這是私人影片", "error_code": "private_video", "error_detail": "ERROR: Private video",
     "error_action": "open_cookie_settings", "error_faq": "err-private-video"},
    {"id": "3", "url": "https://youtu.be/c", "title": "完成", "status": "done", "progress": 100,
     "files": [{"name": "c.mp4", "size": 1024}], "warnings": ["字幕下載失敗"]},
    {"id": "4", "url": "https://youtu.be/d", "title": "暫停", "status": "paused", "progress": 10},
]


def wait(ms=50):
    t = QElapsedTimer()
    t.start()
    while t.elapsed() < ms:
        QCoreApplication.processEvents()


@pytest.fixture
def win(app):
    w = na.MainWindow(FakeApi(), lambda: False)
    w.resize(1000, 700)
    w.show()
    wait()
    yield w
    w.close()
    w.deleteLater()


def accessible_name(w: QWidget) -> str:
    iface = QAccessible.queryAccessibleInterface(w)
    return (iface.text(QAccessible.Name) if iface is not None else "") or ""


def unnamed_focusables(root: QWidget) -> list[str]:
    """root 底下看得到、可以用 Tab 取得焦點、但朗讀程式念不出名稱的元件。"""
    missing = []
    for w in root.findChildren(QWidget):
        if not w.isVisible() or not (w.focusPolicy() & Qt.TabFocus) or not w.isEnabled():
            continue
        if not accessible_name(w).strip():
            parent = w.parentWidget()
            missing.append(f"{type(w).__name__} objectName={w.objectName()!r} "
                           f"in {type(parent).__name__ if parent else None}")
    return missing


def tab_scroll_areas(root: QWidget) -> list[str]:
    return [f"{type(w).__name__} {w.objectName()!r}" for w in root.findChildren(QScrollArea)
            if w.isVisible() and w.focusPolicy() & Qt.TabFocus]


def expand_advanced(win):
    adv = win.download.advanced
    for s in adv.sections.values():
        s.set_expanded(True)
    adv.cookie_exists = True
    adv._on_changed()


# --------------------------------------------------------------------------- 每一頁都有名稱

def test_download_page_empty(win):
    win.go(0)
    wait()
    assert unnamed_focusables(win) == []


def test_download_page_video_with_all_advanced_options(win):
    win.go(0)
    win.download.url.setText(VIDEO["webpage_url"])
    win.download.on_info(VIDEO)
    expand_advanced(win)
    for mode in win.download.mode.buttons:  # 每種下載模式顯示的列不一樣
        win.download.mode.buttons[mode].click()
        wait()
        assert unnamed_focusables(win) == [], mode


def test_download_page_playlist(win):
    win.go(0)
    win.download.url.setText("https://www.youtube.com/playlist?list=PL1")
    win.download.on_info(PLAYLIST)
    win.download.playlist.select_none()  # 「一部都沒選」時多出來的修正連結也要有名稱
    wait()
    assert unnamed_focusables(win) == []


def test_queue_page(win):
    win.go(1)
    win.queue.render(JOBS)
    wait()
    assert unnamed_focusables(win) == []
    from PySide6.QtWidgets import QPushButton
    for b in win.queue.findChildren(QPushButton):  # 展開錯誤詳細資訊後出現的按鈕也要有名稱
        if b.isVisible() and b.text() == "詳細資訊":
            b.click()
    wait()
    assert unnamed_focusables(win) == []


def test_settings_page(win):
    win.go(2)
    wait()
    assert unnamed_focusables(win) == []


def test_main_window_scroll_areas_do_not_take_tab(win):
    """QScrollArea 本身不是 Tab 停留點（看不到焦點）；清單這類可操作的捲動元件不算。"""
    win.download.on_info(VIDEO)
    expand_advanced(win)
    win.queue.render(JOBS)
    for i in range(3):
        win.go(i)
        wait()
        assert tab_scroll_areas(win) == [], i
    # 其他捲動元件（QListView、QTextEdit…）可以取得焦點，但一定要有名稱
    for w in win.findChildren(QAbstractScrollArea):
        if w.isVisible() and w.focusPolicy() & Qt.TabFocus and not isinstance(w, QScrollArea):
            assert accessible_name(w), type(w).__name__


# --------------------------------------------------------------------------- 方向鍵

def test_sidebar_arrow_keys_switch_pages(win):
    win.go(0)
    win.nav[0].setFocus()
    wait()
    QTest.keyClick(win.nav[0], Qt.Key_Down)
    wait()
    assert win.stack.currentIndex() == 1 and win.nav[1].hasFocus()
    QTest.keyClick(win.nav[1], Qt.Key_Down)
    wait()
    assert win.stack.currentIndex() == 2
    QTest.keyClick(win.nav[2], Qt.Key_Up)
    wait()
    assert win.stack.currentIndex() == 1


def test_download_mode_segmented_arrow_keys(win):
    win.go(0)
    win.download.on_info(VIDEO)
    seg = win.download.mode
    keys = list(seg.buttons)
    seg.buttons[keys[0]].click()
    seg.buttons[keys[0]].setFocus()
    wait()
    QTest.keyClick(seg.buttons[keys[0]], Qt.Key_Right)
    wait()
    assert seg.value() == keys[1] and seg.buttons[keys[1]].hasFocus()


# --------------------------------------------------------------------------- 檢查工具本身

def test_checker_catches_unnamed_widget(app):
    from PySide6.QtWidgets import QLineEdit, QPushButton, QVBoxLayout
    root = QWidget()
    lay = QVBoxLayout(root)
    named = QLineEdit()
    named.setAccessibleName("網址")
    bare = QLineEdit()
    lay.addWidget(named)
    lay.addWidget(bare)
    lay.addWidget(QPushButton("確定"))
    sc = QScrollArea()
    sc.setFocusPolicy(Qt.StrongFocus)
    lay.addWidget(sc)
    root.show()
    wait()
    missing = unnamed_focusables(root)
    assert any("QLineEdit" in m for m in missing) and not any("QPushButton" in m for m in missing)
    assert tab_scroll_areas(root)
    root.close()
