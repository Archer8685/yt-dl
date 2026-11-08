"""原生播放清單選取元件的測試（offscreen，不連網）。"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import QApplication

import server
from native_playlist import PlaylistView, compress_indexes, parse_range

JOB = Path("downloads/_test")


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def fake_info(n=50, gaps=()):
    entries = []
    for i in range(1, n + 1):
        if i in gaps:
            continue
        kind = "Live" if i % 7 == 0 else "Studio"
        entries.append({"index": i, "id": f"id{i}", "title": f"{kind} 歌曲 {i}", "duration": 200 + i,
                        "url": f"https://example.com/{i}", "thumbnail": f"https://img.example/{i}.jpg",
                        "uploader": "測試頻道"})
    return {"type": "playlist", "title": "測試清單", "uploader": "測試頻道", "entries": entries}


class FakeLoader:
    def __init__(self):
        self.urls = []

    def __call__(self, url, ok):
        self.urls.append(url)
        pm = QPixmap(160, 90)
        pm.fill(QColor("#336699"))
        ok(pm)


@pytest.fixture
def view(qapp):
    v = PlaylistView(image_loader=FakeLoader())
    v.set_playlist(fake_info())
    return v


def opts(items):
    return server.build_opts({"mode": "av", "playlist": True, "playlist_items": items}, JOB)


# --------------------------------------------------------------------------- 純函式
@pytest.mark.parametrize("nums, expected", [
    ([], ""),
    ([5], "5"),
    ([1, 2, 3], "1-3"),
    ([3, 1, 2, 5, 7, 8, 8], "1-3,5,7-8"),
    ([1, 3, 5], "1,3,5"),
    ([10, 11, 12, 20, 21], "10-12,20-21"),
])
def test_compress_indexes(nums, expected):
    assert compress_indexes(nums) == expected


def test_parse_range_formats():
    valid = range(1, 51)
    assert parse_range("1-10, 15", valid) == set(range(1, 11)) | {15}
    assert parse_range(" 3 - 5，8、9 ", valid) == {3, 4, 5, 8, 9}
    assert parse_range("1~2 4:5", valid) == {1, 2, 4, 5}
    assert parse_range("2-2", valid) == {2}


@pytest.mark.parametrize("text, msg", [
    ("", "請輸入範圍"),
    ("abc", "看不懂「abc」"),
    ("1-", "看不懂"),
    ("10-5", "起點比終點大"),
    ("45-60", "超出範圍"),
    ("0", "超出範圍"),
])
def test_parse_range_errors(text, msg):
    with pytest.raises(ValueError, match=msg):
        parse_range(text, range(1, 51))


def test_parse_range_skips_missing_entries():
    assert parse_range("2-4", [1, 2, 4]) == {2, 4}
    with pytest.raises(ValueError, match="沒有影片"):
        parse_range("3", [1, 2, 4])


# --------------------------------------------------------------------------- 元件
def test_defaults_to_all_selected(view):
    assert view.selected_count() == 50
    assert view.playlist_items() == "1-50"
    assert "已選 50 / 50 部" in view.count.text()
    assert "共 50 部" in view.meta.text() and "測試頻道" in view.meta.text()
    assert opts(view.playlist_items())["playlist_items"] == "1-50"


def test_toggle_compresses_ranges_and_signals(view):
    seen = []
    view.selectionChanged.connect(seen.append)
    view.toggle_rows([2, 3, 9])  # 序號 3、4、10
    assert view.selected_count() == 47
    assert view.playlist_items() == "1-2,5-9,11-50"
    assert seen[-1] == 47
    view.select_none()
    assert view.playlist_items() == "" and seen[-1] == 0
    view.toggle_rows([0, 4, 5, 6, 49])
    assert view.playlist_items() == "1,5-7,50"
    r = opts(view.playlist_items())
    assert r["playlist_items"] == "1,5-7,50" and r["noplaylist"] is False


def test_select_all_after_search_only_selects_visible(view):
    view.select_none()
    view.search.setText("live")  # 不分大小寫，序號 7 的倍數
    assert view.proxy.rowCount() == 7
    view.select_all()
    assert view.playlist_items() == "7,14,21,28,35,42,49"
    assert "顯示 7 部符合" in view.count.text()
    view.invert()  # 也只作用在搜尋結果
    assert view.selected_count() == 0
    view.toggle_rows([6])
    view.search.setText("")
    view.invert()
    assert view.selected_count() == 49 and "7" not in view.playlist_items().split(",")
    assert opts(view.playlist_items())["playlist_items"] == "1-6,8-50"


def test_search_no_results_shows_placeholder(view):
    view.search.setText("不存在的字")
    assert view.proxy.rowCount() == 0
    assert view.empty.isVisibleTo(view) and "不存在的字" in view.empty.text()
    view.search.clear()
    assert not view.empty.isVisibleTo(view)


def test_range_input_replaces_selection(view):
    view.range.setText("1-10, 15")
    assert view.apply_range() is True
    assert view.playlist_items() == "1-10,15"
    assert not view.error.isVisibleTo(view)
    assert opts(view.playlist_items())["playlist_items"] == "1-10,15"


def test_range_input_error_keeps_selection(view):
    view.range.setText("1-10, 15")
    view.apply_range()
    view.range.setText("8-99")
    assert view.apply_range() is False
    assert view.error.isVisibleTo(view) and "超出範圍" in view.error.text()
    assert view.playlist_items() == "1-10,15"
    view.range.setText("abc")
    view.range.returnPressed.emit()
    assert "看不懂" in view.error.text()
    view.range.setText("20")
    view.range_btn.click()
    assert not view.error.isVisibleTo(view) and view.playlist_items() == "20"


def test_entry_index_gaps_use_real_playlist_index(qapp):
    v = PlaylistView(image_loader=FakeLoader())
    v.set_playlist(fake_info(10, gaps={3, 4}))
    assert v.playlist_items() == "1-2,5-10"
    v.range.setText("1-5")
    assert v.apply_range() and v.playlist_items() == "1-2,5"


def test_set_playlist_resets_state(view):
    view.search.setText("live")
    view.range.setText("x")
    view.apply_range()
    view.set_playlist(fake_info(5))
    assert view.search.text() == "" and view.range.text() == "" and not view.error.isVisibleTo(view)
    assert view.proxy.rowCount() == 5 and view.playlist_items() == "1-5"


def test_thumbnails_load_lazily(qapp):
    loader = FakeLoader()
    v = PlaylistView(image_loader=loader)
    v.set_playlist(fake_info(300))
    v.resize(720, 560)
    v.show()
    for _ in range(3):
        v.grab()
        qapp.processEvents()
    first = list(loader.urls)
    assert 0 < len(first) < 20, len(first)
    assert all(int(u.rsplit("/", 1)[1].split(".")[0]) <= 20 for u in first)
    sb = v.list.verticalScrollBar()
    sb.setValue(sb.maximum())
    for _ in range(3):
        v.grab()
        qapp.processEvents()
    later = loader.urls[len(first):]
    assert later and all(int(u.rsplit("/", 1)[1].split(".")[0]) > 280 for u in later)
    assert len(loader.urls) < 40 and len(set(loader.urls)) == len(loader.urls)
    v.close()


def test_apply_theme_uses_given_tokens_not_system(qapp):
    """主視窗指定深色時（即使系統是淺色）清單也要用深色的配色。"""
    import native_playlist
    from native_app import tokens
    v = PlaylistView(image_loader=FakeLoader())
    v.apply_theme(tokens(True))
    assert native_playlist._theme()["text"] == QColor(tokens(True)["text"])
    assert native_playlist._theme()["sep"].alpha() < 255  # #AARRGGBB 的透明度有讀到
    v.apply_theme(tokens(False))
    assert native_playlist._theme()["card"] == QColor(tokens(False)["card"])


def test_set_playlist_aborts_previous_thumbnail_requests(qapp):
    class Reply:
        def __init__(self):
            self.aborted = False

        def abort(self):
            self.aborted = True

    replies = []

    def loader(url, cb):
        replies.append(Reply())
        return replies[-1]

    v = PlaylistView(image_loader=loader)
    v.set_playlist(fake_info(30))
    v.resize(720, 560)
    v.show()
    for _ in range(20):
        QApplication.processEvents()
    assert replies and not any(r.aborted for r in replies)
    v.set_playlist(fake_info(5))
    assert all(r.aborted for r in replies[:6])
    v.close()


def test_thumbnail_load_does_not_signal_selection(qapp):
    v = PlaylistView(image_loader=FakeLoader())
    v.set_playlist(fake_info(30))
    seen = []
    v.selectionChanged.connect(seen.append)
    v.resize(720, 560)
    v.show()
    v.grab()
    qapp.processEvents()
    assert v.model.thumbs and seen == []
    v.close()


def test_click_toggles_but_drag_release_does_not(qapp):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    v = PlaylistView(image_loader=FakeLoader())
    v.set_playlist(fake_info(20))
    v.resize(720, 560)
    v.show()
    qapp.processEvents()
    vp = v.list.viewport()
    r0 = v.list.visualRect(v.proxy.index(0, 0)).center()
    r2 = v.list.visualRect(v.proxy.index(2, 0)).center()
    QTest.mouseClick(vp, Qt.LeftButton, Qt.NoModifier, r0)
    assert v.playlist_items() == "2-20"
    QTest.mouseClick(vp, Qt.LeftButton, Qt.ShiftModifier, r2)  # 第 1–3 列設成跟第 1 列一樣（未勾）
    assert v.playlist_items() == "4-20"
    QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier, r0)
    QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier, r2 + QPoint(0, 1))
    assert v.playlist_items() == "4-20"
    v.close()


def test_empty_playlist(qapp):
    v = PlaylistView(image_loader=FakeLoader())
    v.set_playlist({"type": "playlist", "title": "空", "entries": []})
    assert v.selected_count() == 0 and v.playlist_items() == ""
    assert v.empty.isVisibleTo(v)
    v.range.setText("1")
    assert v.apply_range() is False and "沒有影片" in v.error.text()
