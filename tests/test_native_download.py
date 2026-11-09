"""native_download.py（新增下載頁）的行為測試；用 offscreen 平台，不需要螢幕。"""
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", "C:/Windows/Fonts" if os.name == "nt" else "")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QMessageBox

import native_app as na
import native_common as nc
import native_download as nd
import native_options


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    # 介面會存 QSettings：測試寫到暫存的 ini 檔，不要動到這台電腦的真實設定
    ini = str(tmp_path_factory.mktemp("qsettings") / "native.ini")
    native_options.QSettings = nc.QSettings = lambda *a, **k: QSettings(ini, QSettings.IniFormat)
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


def video_info(title, vid, heights=(1080, 720)):
    return {"type": "video", "title": title, "id": vid, "webpage_url": f"https://www.youtube.com/watch?v={vid}",
            "duration": 10, "heights": list(heights), "thumbnail": f"https://i.ytimg.com/{vid}.jpg",
            "audio_tracks": [], "subtitles": [], "auto_captions": []}


# --------------------------------------------------------------------------- #
#  新增下載
# --------------------------------------------------------------------------- #
def test_stale_info_response_is_ignored(app):
    api = FakeApi()
    page = nd.DownloadPage(api, lambda *a, **k: None)
    page.url.setText("https://www.youtube.com/watch?v=AAA")
    page.analyze()
    page.url.setText("https://www.youtube.com/watch?v=BBB")
    page.analyze()  # 第一次還沒回來又按 Enter
    first, second = [c for c in api.calls if c[1] == "/api/info"]
    second[3](video_info("B", "BBB"))
    first[3](video_info("A", "AAA"))  # 較慢回來的舊結果
    assert page.info["id"] == "BBB"
    assert page.title.text() == "B"
    first[4]("逾時")  # 舊請求的錯誤也不能蓋掉畫面
    assert "逾時" not in page.status.text()
    from PySide6.QtGui import QPixmap
    pm = QPixmap(4, 4)
    pm.fill()
    thumbs = [c for c in api.calls if c[0] == "IMG"]
    assert [c[1] for c in thumbs] == ["https://i.ytimg.com/BBB.jpg"]
    page.url.setText("https://www.youtube.com/watch?v=CCC")
    page.analyze()
    thumbs[0][3](pm)  # B 的縮圖在 C 解析期間才回來
    assert page.thumb.pixmap().isNull()


def test_playlist_switch_is_sent_and_reanalyzes(app):
    api = FakeApi()
    page = nd.DownloadPage(api, lambda *a, **k: None)
    page.as_playlist.setChecked(False)
    page.url.setText("https://www.bilibili.com/video/BV1xx")  # 不只 YouTube：交給 yt-dlp 依網站判斷
    page.analyze()
    assert api.last("/api/info")[2]["noplaylist"] is True
    api.last("/api/info")[3](video_info("P1", "BV1xx"))
    n = len([c for c in api.calls if c[1] == "/api/info"])
    page.as_playlist.setChecked(True)  # 解析後才切換：要用新設定重新解析
    infos = [c for c in api.calls if c[1] == "/api/info"]
    assert len(infos) == n + 1 and infos[-1][2]["noplaylist"] is False


def test_user_text_is_plain_not_html(app):
    page = nd.DownloadPage(FakeApi(), lambda *a, **k: None)
    page.on_info(video_info("Top 10 <b>NEW</b> &amp; more", "x"))
    assert page.title.textFormat() == Qt.PlainText and page.title.text() == "Top 10 <b>NEW</b> &amp; more"


def test_clip_range_only_blocks_media_modes(app):
    page = nd.DownloadPage(FakeApi(), lambda *a, **k: None)
    page.on_info(video_info("V", "v"))
    page.advanced.sections_edit.setText("abc")
    page.mode.set_value("av")
    page.update_rows()
    assert page.problem() and not page.download_btn.isEnabled()
    page.mode.set_value("thumb")  # 剪輯分組隱藏時，看不到的錯誤不能擋住下載
    page.update_rows()
    assert page.problem() == "" and page.download_btn.isEnabled()
    page.advanced.sections_edit.clear()


def test_download_defaults_from_settings(app, monkeypatch):
    """設定頁的「下載預設值」：存起來、立刻套用到新增下載頁，下次開啟也從這組選項開始。"""
    api = FakeApi()
    win = na.MainWindow(api, lambda: False)
    s, page = win.settings, win.download
    try:
        page.on_info(video_info("V", "v", heights=(2160, 1080, 720)))
        s.def_mode.select("audio")
        s.def_acodec.select("flac")
        s.def_quality.select(720)
        s.def_playlist.setChecked(True)
        assert page.mode.value() == "audio" and page.acodec.currentData() == "flac"  # 立刻套用
        assert page.quality.currentData() == 720 and page.as_playlist.isChecked()
        assert nc.load_download_defaults()["quality"] == 720
        fresh = nd.DownloadPage(FakeApi(), lambda *a, **k: None)  # 重新開啟 App
        assert fresh.mode.value() == "audio" and fresh.acodec.currentData() == "flac"
        fresh.on_info(video_info("W", "w", heights=(1080, 720)))
        assert fresh.quality.currentData() == 720
        low = nd.DownloadPage(FakeApi(), lambda *a, **k: None)
        low.on_info(video_info("L", "l", heights=(480,)))  # 影片沒有預設畫質：用最佳畫質
        assert low.quality.currentData() is None
        # 在新增下載頁臨時改選，不會改到預設值
        page.mode.set_value("av")
        page.mode.changed.emit("av")
        assert nc.load_download_defaults()["mode"] == "audio"
        # 恢復所有預設值（按下確認）
        monkeypatch.setattr(QMessageBox, "exec", lambda box: next(
            b for b in box.buttons() if b.text() == "恢復預設值").click())
        s.reset_all()
        assert nc.load_download_defaults() == nc.DOWNLOAD_DEFAULTS
        assert page.mode.value() == "av" and s.def_quality.currentData() is None
        assert nc.ui_prefs() == ("system", "medium")
    finally:
        nc.save_download_defaults(dict(nc.DOWNLOAD_DEFAULTS))
        win.close()
