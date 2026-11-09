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


class FakeReply:
    def __init__(self):
        self.aborted = False

    def abort(self):
        self.aborted = True


class FakeApi:
    """記下請求、由測試決定何時回應。"""

    def __init__(self):
        self.calls = []
        self.replies = []

    def _add(self, method, path, body, ok, err):
        self.calls.append((method, path, body, ok, err))

    def post(self, path, body=None, ok=None, err=None, timeout_ms=0):
        self._add("POST", path, body, ok, err)
        reply = FakeReply()
        self.replies.append(reply)
        return reply

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
    assert page._thumb_src.isNull()  # 只有佔位圖（DL15），沒有換成 B 的縮圖


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


# --------------------------------------------------------------------------- #
#  v1.3.0 A1：共用工具
# --------------------------------------------------------------------------- #
def wait_until(cond, ms=2000):
    from PySide6.QtCore import QCoreApplication, QElapsedTimer
    t = QElapsedTimer()
    t.start()
    while not cond() and t.elapsed() < ms:
        QCoreApplication.processEvents()
    return cond()


def playlist_info(n=5):
    return {"type": "playlist", "id": "PL1", "title": "清單", "uploader": "U",
            "webpage_url": "https://www.youtube.com/playlist?list=PL1",
            "entries": [{"index": i, "id": f"v{i}", "title": f"影片 {i}", "duration": 60,
                         "url": f"https://www.youtube.com/watch?v=v{i}", "thumbnail": None, "uploader": "U"}
                        for i in range(1, n + 1)]}


class Toasts:
    """舊版 toast(text, error=False) 的替身。"""

    def __init__(self):
        self.items = []

    def __call__(self, text, error=False):
        self.items.append((text, error))


def new_page(toast=None):
    api = FakeApi()
    return nd.DownloadPage(api, toast or (lambda *a, **k: None)), api


def info_calls(api):
    return [c for c in api.calls if c[1] == "/api/info"]


# --------------------------------------------------------------------------- #
#  DL6、F1：網址整理
# --------------------------------------------------------------------------- #
def test_normalize_url_adds_scheme_and_accepts_video_id():
    assert nd.normalize_url("youtube.com/watch?v=jNQXAC9IVRw") == "https://youtube.com/watch?v=jNQXAC9IVRw"
    assert nd.normalize_url("www.bilibili.com/video/BV1xx") == "https://www.bilibili.com/video/BV1xx"
    assert nd.normalize_url("jNQXAC9IVRw") == "https://www.youtube.com/watch?v=jNQXAC9IVRw"
    assert nd.normalize_url(" https://youtu.be/jNQXAC9IVRw ") == "https://youtu.be/jNQXAC9IVRw"
    for bad in ("", "hello world", "javascript:alert(1)", "file:///C:/x.mp4", "data:text/html,x", "abc", "https://"):
        assert nd.normalize_url(bad) is None, bad


def test_extract_urls_ten_lines_two_invalid():
    lines = [f"https://www.youtube.com/watch?v=video{i:06d}" for i in range(6)]
    lines += ["youtu.be/jNQXAC9IVRw", "dQw4w9WgXcQ", "這一行不是網址", "javascript:alert(1)", "", "# 註解"]
    urls, invalid = nd.extract_urls("\n".join(lines))
    assert len(urls) == 8 and invalid == 2
    assert urls[6] == "https://youtu.be/jNQXAC9IVRw" and urls[7] == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    # 一行裡有網址和其他文字、重複的網址、黏著標點
    urls, invalid = nd.extract_urls("看這個 https://youtu.be/aaaaaaaaaaa，很好看\nhttps://youtu.be/aaaaaaaaaaa")
    assert urls == ["https://youtu.be/aaaaaaaaaaa"] and invalid == 0


def test_analyze_fills_in_https(app):
    page, api = new_page()
    page.url.setText("youtube.com/watch?v=jNQXAC9IVRw")
    page.analyze()
    assert info_calls(api)[-1][2]["url"] == "https://youtube.com/watch?v=jNQXAC9IVRw"
    assert page.url.text() == "https://youtube.com/watch?v=jNQXAC9IVRw"
    page.url.setText("jNQXAC9IVRw")
    page.analyze()
    assert info_calls(api)[-1][2]["url"] == "https://www.youtube.com/watch?v=jNQXAC9IVRw"


# --------------------------------------------------------------------------- #
#  DL3：解析可以取消
# --------------------------------------------------------------------------- #
def test_cancel_analyze_restores_input_immediately(app):
    page, api = new_page()
    page.url.setText("https://www.youtube.com/watch?v=jNQXAC9IVRw")
    page.analyze()
    assert page.cancel_btn.isVisibleTo(page) and not page.analyze_btn.isVisibleTo(page)
    assert not page.analyze_btn.isEnabled()  # 主視窗的自動貼上靠這個判斷「正在解析」
    assert page.progress.isVisibleTo(page) and not page.empty.isVisibleTo(page)
    page._slow_hint()  # 超過 15 秒
    assert "比較久" in page.status.text()
    page.cancel_analyze()
    assert api.replies[-1].aborted
    assert not page._analyzing and page.analyze_btn.isEnabled() and page.analyze_btn.isVisibleTo(page)
    assert not page.cancel_btn.isVisibleTo(page) and not page.progress.isVisibleTo(page)
    assert page.status.text() == "已取消解析" and page.empty.isVisibleTo(page)
    info_calls(api)[-1][3](video_info("晚到", "late"))  # 取消後才回來的結果不能顯示
    info_calls(api)[-1][4]("Operation canceled")
    assert page.info is None and not page.err_box.isVisibleTo(page)


def test_escape_cancels_analyze(app):
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QKeyEvent
    page, api = new_page()
    page.url.setText("https://youtu.be/jNQXAC9IVRw")
    page.analyze()
    page.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier))
    assert not page._analyzing and api.replies[-1].aborted


def test_analyze_buttons_share_width(app):
    page, _ = new_page()
    assert page.analyze_btn.minimumWidth() == page.cancel_btn.minimumWidth() > 0
    fm = page.analyze_btn.fontMetrics()
    assert page.analyze_btn.minimumWidth() >= fm.horizontalAdvance("Analyze")  # 英文也放得下


# --------------------------------------------------------------------------- #
#  DL1：解析後「解析」改次要、底部動作列；DL2：字幕模式展開字幕分組、摘要錯誤可點
# --------------------------------------------------------------------------- #
def test_analyze_button_becomes_secondary_after_loading(app):
    page, _ = new_page()
    assert page.analyze_btn.objectName() == "primary" and not page.action_bar.isVisibleTo(page)
    page.on_info(video_info("V", "v"))
    assert page.analyze_btn.objectName() == "" and page.action_bar.isVisibleTo(page)
    assert page.download_btn.isDefault() and not page.analyze_btn.isDefault()


def test_subs_mode_reveals_subtitles_with_a2_api(app):
    page, _ = new_page()
    page.on_info(video_info("V", "v"))
    seen = []
    page.advanced.reveal_section = seen.append  # A2 合併後的介面
    page.mode.set_value("subs")
    page.mode.changed.emit("subs")
    assert seen == ["subtitles"]
    assert 'href="subtitles"' in page.summary.text() and not page.download_btn.isEnabled()
    page.summary.linkActivated.emit("subtitles")
    assert seen == ["subtitles", "subtitles"]
    page.mode.set_value("av")
    page.mode.changed.emit("av")


def test_subs_mode_fallback_expands_section_without_a2(app):
    page, _ = new_page()
    if hasattr(type(page.advanced), "reveal_section"):
        pytest.skip("A2 已提供 reveal_section")
    page.on_info(video_info("V", "v"))
    page.advanced.sections["subs"].set_expanded(False)
    page.mode.set_value("subs")
    page.mode.changed.emit("subs")
    assert page.advanced.sections["subs"].expanded()
    page.mode.set_value("av")
    page.mode.changed.emit("av")


def test_playlist_none_selected_link_selects_all(app):
    page, _ = new_page()
    page.on_info(playlist_info(4))
    page.playlist.select_none()
    assert 'href="select_all"' in page.summary.text() and not page.download_btn.isEnabled()
    page.summary.linkActivated.emit("select_all")
    assert page.playlist.selected_count() == 4 and page.download_btn.isEnabled()
    assert "4 部影片" in page.summary.text()


def test_summary_escapes_engine_text(app):
    page, _ = new_page()
    page.on_info(video_info("V", "v"))
    page.advanced.sections_edit.setText("<b>x</b>")
    page.update_rows()
    assert "<b>x</b>" not in page.summary.text() and 'href="clip"' in page.summary.text()
    page.advanced.sections_edit.clear()


# --------------------------------------------------------------------------- #
#  DL5、F4／F7：新連結不覆蓋、accept_urls
# --------------------------------------------------------------------------- #
def test_new_link_is_offered_not_replacing_loaded_video(app):
    page, api = new_page()
    page.url.setText("https://www.youtube.com/watch?v=AAAAAAAAAAA")
    page.analyze()
    info_calls(api)[-1][3](video_info("A", "AAAAAAAAAAA"))
    n = len(info_calls(api))
    page.accept_urls(["https://youtu.be/BBBBBBBBBBB"])
    assert page.new_link.isVisibleTo(page) and "BBBBBBBBBBB" in page.new_link_text.text()
    assert page.url.text() == "https://www.youtube.com/watch?v=AAAAAAAAAAA" and len(info_calls(api)) == n
    page.new_link_skip.click()
    assert not page.new_link.isVisibleTo(page) and page.info["id"] == "AAAAAAAAAAA"
    page.accept_urls(["https://youtu.be/BBBBBBBBBBB"])
    page.new_link_go.click()
    assert page.url.text() == "https://youtu.be/BBBBBBBBBBB" and info_calls(api)[-1][2]["url"].endswith("BBBBBBBBBBB")
    assert not page.new_link.isVisibleTo(page)


def test_accept_single_url_on_empty_page_analyzes(app):
    page, api = new_page()
    page.accept_urls(["dQw4w9WgXcQ"])
    assert page.url.text() == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    assert info_calls(api)[-1][2]["url"] == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    page.accept_urls(["https://www.youtube.com/watch?v=dQw4w9WgXcQ"])  # 同一個網址正在解析：不動作
    assert len(info_calls(api)) == 1 and not page.new_link.isVisibleTo(page)


def test_accept_urls_does_not_clobber_typing(app):
    page, api = new_page()
    page.url.setText("https://www.youtube.com/watch?v=typing")
    page.accept_urls(["https://youtu.be/CCCCCCCCCCC"])
    assert page.url.text() == "https://www.youtube.com/watch?v=typing" and not info_calls(api)
    assert page.new_link.isVisibleTo(page)


def test_accept_urls_rejects_nothing_useful(app):
    toasts = Toasts()
    page, api = new_page(toasts)
    page.accept_urls(["javascript:alert(1)", "file:///C:/Windows/win.ini"])
    assert toasts.items and toasts.items[-1][1] is True and not info_calls(api)


def test_accept_many_urls_opens_batch_and_queues_in_order(app):
    toasts = Toasts()
    page, api = new_page(toasts)
    queued = []
    page.queued.connect(lambda: queued.append(1))
    lines = [f"https://www.youtube.com/watch?v=video{i:06d}" for i in range(8)] + ["不是網址", "也不是"]
    page.accept_urls(["\n".join(lines)])
    dlg = page._batch
    assert dlg is not None and dlg.list.count() == 8 and dlg.invalid == 2
    assert "8 個網址" in dlg.info.text() and "2 行不是網址" in dlg.info.text()
    dlg.list.item(7).setCheckState(Qt.Unchecked)
    assert dlg.add_btn.text() == "加入佇列（7 個）"
    dlg.accept()
    downloads = [c for c in api.calls if c[1] == "/api/download"]
    assert len(downloads) == 1  # 一個一個送，佇列順序和清單一樣
    for i in range(7):
        downloads = [c for c in api.calls if c[1] == "/api/download"]
        assert downloads[i][2]["url"] == lines[i] and downloads[i][2]["options"]["playlist"] is False
        assert "playlist_items" not in downloads[i][2]["options"]
        (downloads[i][4]("網址不正確") if i == 3 else downloads[i][3]({"id": str(i)}))
    assert len([c for c in api.calls if c[1] == "/api/download"]) == 7
    assert queued == [1] and toasts.items[-1][1] is True and "1 個網址無法加入" in toasts.items[-1][0]
    assert page.batch_btn.isEnabled()


def test_batch_limit_100(app):
    page, _ = new_page()
    text = "\n".join(f"https://example.com/v/{i}" for i in range(130))
    dlg = page.open_batch(text)
    assert dlg.total == 130 and dlg.list.count() == 100 and "前 100 個" in dlg.info.text()
    dlg.reject()


def test_batch_from_txt_file(app, tmp_path):
    f = tmp_path / "urls.txt"
    f.write_text("https://youtu.be/aaaaaaaaaaa\r\nhttps://youtu.be/bbbbbbbbbbb\r\n", encoding="utf-8")
    page, _ = new_page()
    page.accept_urls([str(f)])
    assert page._batch.list.count() == 2
    page._batch.reject()
    page.accept_urls([f.as_uri()])  # 拖放進來的 file:// 網址
    assert page._batch.list.count() == 2
    page._batch.add_file(str(f))  # 「選擇 .txt 檔…」再加一次：重複的網址只列一次
    assert page._batch.list.count() == 2
    page._batch.reject()


def test_batch_txt_in_big5_and_utf16(app, tmp_path):
    big5 = tmp_path / "big5.txt"
    big5.write_bytes("我的清單\r\nhttps://youtu.be/aaaaaaaaaaa\r\n第二部 https://youtu.be/bbbbbbbbbbb\r\n".encode("cp950"))
    u16 = tmp_path / "u16.txt"
    u16.write_text("https://youtu.be/ccccccccccc\n", encoding="utf-16")
    assert nd.extract_urls(nd.read_txt(big5))[0] == ["https://youtu.be/aaaaaaaaaaa", "https://youtu.be/bbbbbbbbbbb"]
    assert nd.extract_urls(nd.read_txt(u16))[0] == ["https://youtu.be/ccccccccccc"]


def test_reanalyze_abort_error_is_treated_as_stale(app):
    """真的 QNetworkReply.abort() 會馬上觸發舊請求的錯誤回呼：不能被當成目前的結果。"""
    page, api = new_page()
    page.url.setText("https://youtu.be/aaaaaaaaaaa")
    page.analyze()
    first = info_calls(api)[-1]
    api.replies[-1].abort = lambda: first[4]("Operation canceled")
    page.url.setText("https://youtu.be/bbbbbbbbbbb")
    page.analyze()
    assert page._analyzing and not page.err_box.isVisibleTo(page) and page.cancel_btn.isVisibleTo(page)


def test_playlist_toggle_during_analysis_reanalyzes(app):
    page, api = new_page()
    page.as_playlist.setChecked(False)
    page.url.setText("https://www.youtube.com/watch?v=jNQXAC9IVRw&list=PL1")
    page.analyze()
    page.as_playlist.setChecked(True)  # 還在解析就切換：用新設定重新解析，結果才不會和開關不一致
    calls = info_calls(api)
    assert len(calls) == 2 and calls[-1][2]["noplaylist"] is False
    calls[0][3](video_info("舊", "jNQXAC9IVRw"))
    assert page.info is None


def test_multiline_paste_goes_to_batch(app):
    from PySide6.QtGui import QGuiApplication
    page, api = new_page()
    QGuiApplication.clipboard().setText("https://youtu.be/aaaaaaaaaaa\nhttps://youtu.be/bbbbbbbbbbb")
    page.paste()
    assert page._batch is not None and page._batch.list.count() == 2 and not info_calls(api)
    page._batch.reject()


def test_batch_blocks_subs_mode_without_language(app):
    toasts = Toasts()
    page, api = new_page(toasts)
    page.mode.set_value("subs")
    page.queue_batch(["https://youtu.be/aaaaaaaaaaa"])
    assert not [c for c in api.calls if c[1] == "/api/download"] and toasts.items[-1][1] is True
    page.mode.set_value("av")


# --------------------------------------------------------------------------- #
#  ERR1：解析失敗顯示引擎的錯誤物件
# --------------------------------------------------------------------------- #
ERR = {"error": "這部影片需要登入才能看", "error_code": "bot_check",
       "error_detail": "ERROR: [youtube] x: Sign in to confirm you're not a bot", "error_action": "open_cookie_settings",
       "error_faq": "err-bot-check"}


class ApiError(str):
    """C1 的 Api 可以用這種字串子類別把錯誤物件帶給 err 回呼。"""

    def __new__(cls, payload):
        s = super().__new__(cls, payload["error"])
        s.payload = payload
        return s


@pytest.mark.parametrize("deliver", ["second_arg", "str_subclass", "dict"])
def test_info_error_shows_engine_error_object(app, monkeypatch, deliver):
    opened = []
    monkeypatch.setattr(nd.QDesktopServices, "openUrl", lambda url: opened.append(url.toString()))
    page, api = new_page()
    page.url.setText("https://youtu.be/jNQXAC9IVRw")
    page.analyze()
    err = info_calls(api)[-1][4]
    {"second_arg": lambda: err(ERR["error"], dict(ERR)), "str_subclass": lambda: err(ApiError(dict(ERR))),
     "dict": lambda: err(dict(ERR))}[deliver]()
    assert page.err_box.isVisibleTo(page) and page.err_text.text() == ERR["error"]  # 引擎文字不加前綴、不翻譯
    assert page.err_action_btn.isVisibleTo(page) and page.err_action_btn.text() == "設定 Cookie"
    assert not page.err_detail.isVisibleTo(page)
    page.err_detail_btn.click()
    assert page.err_detail.isVisibleTo(page) and "not a bot" in page.err_detail.text()
    page.err_faq_btn.click()
    assert opened and opened[-1].endswith("#err-bot-check")
    assert page.analyze_btn.isEnabled() and not page._analyzing


def test_info_error_action_calls_open_settings(app):
    from PySide6.QtWidgets import QMainWindow

    class Win(QMainWindow):
        def __init__(self):
            super().__init__()
            self.opened = []

        def open_settings(self, section):
            self.opened.append(section)

    win = Win()
    page, _ = new_page()
    win.setCentralWidget(page)
    page.on_info_error(ERR["error"], dict(ERR, error_action="open_storage_settings"))
    assert page.err_action_btn.text() == "更換儲存位置"
    page.err_action_btn.click()
    page.on_info_error(ERR["error"], dict(ERR))
    page.err_action_btn.click()
    assert win.opened == ["storage", "cookies"]
    win.close()


def test_info_error_cookie_action_falls_back_to_network_section(app):
    page, _ = new_page()
    seen = []
    page.advanced.reveal_section = seen.append
    page.on_info_error(ERR["error"], dict(ERR))
    page.err_action_btn.click()  # 沒有主視窗的 open_settings：打開進階選項的「網路」（Cookie 在那裡）
    assert seen == ["network"] and page.advanced.isVisibleTo(page)


def test_info_error_without_error_object_keeps_old_text(app):
    page, _ = new_page()
    page.on_info_error("逾時")
    assert page.err_text.text() == "無法解析：逾時"
    assert not page.err_action_btn.isVisibleTo(page) and not page.err_faq_btn.isVisibleTo(page)
    assert not page.err_detail_btn.isVisibleTo(page)
    page.on_info_error(ERR["error"], dict(ERR, error_action="reanalyze", error_detail=ERR["error"]))
    assert page.err_action_btn.text() == "重新解析" and not page.err_detail_btn.isVisibleTo(page)


def test_download_error_uses_new_toast_with_actions(app):
    seen = []

    def toast(text, level="info", actions=None):
        seen.append((text, level, actions))

    page, api = new_page(toast)
    page.on_info(video_info("V", "v"))
    page.download()
    api.last("/api/download")[4]("儲存位置 D:\\ 目前無法存取",
                                 {"error": "儲存位置 D:\\ 目前無法存取", "error_code": "download_dir_unavailable",
                                  "error_action": "open_storage_settings", "error_faq": "err-download-dir"})
    text, level, actions = seen[-1]
    assert level == "error" and "D:\\" in text and [a[0] for a in actions] == ["更換儲存位置"]
    page.download()
    api.last("/api/download")[3]({"id": "1"})
    assert seen[-1][1] == "info" and "已加入下載佇列" in seen[-1][0]


def test_download_error_with_old_toast(app):
    toasts = Toasts()
    page, api = new_page(toasts)
    page.on_info(video_info("V", "v"))
    page.download()
    api.last("/api/download")[4]("磁碟已滿")
    assert toasts.items[-1] == ("無法開始下載：磁碟已滿", True)


# --------------------------------------------------------------------------- #
#  DL7、DL9、DL13、DL15
# --------------------------------------------------------------------------- #
def test_focus_url_and_empty_state(app):
    from PySide6.QtWidgets import QApplication
    page, _ = new_page()
    page.url.setText("abc")
    page.resize(1000, 700)
    page.show()
    page.activateWindow()
    page.focus_url()
    assert wait_until(lambda: QApplication.focusWidget() is page.url)
    assert page.url.selectedText() == "abc"
    assert page.empty.isVisible()
    page.on_info(video_info("V", "v"))
    assert not page.empty.isVisible()
    page.close()


def test_playlist_switch_label_toggles_and_explains_reanalyze(app):
    page, api = new_page()
    page.as_playlist.setChecked(False)
    page.as_playlist_label.clicked.emit()
    assert page.as_playlist.isChecked()
    page.url.setText("https://www.youtube.com/watch?v=jNQXAC9IVRw&list=PL1")
    page.analyze()
    info_calls(api)[-1][3](video_info("V", "jNQXAC9IVRw"))
    page.as_playlist_label.clicked.emit()  # 解析後才切換：重新解析並說明原因
    assert info_calls(api)[-1][2]["noplaylist"] is True
    assert "重新解析" in page.status.text()
    assert page.as_playlist.accessibleName()


def test_thumbnail_placeholder_and_narrow_size(app):
    from PySide6.QtGui import QPixmap
    page, api = new_page()
    page.resize(1000, 700)
    page.show()
    page.on_info(video_info("V", "v"))
    assert not page.thumb.pixmap().isNull() and page._thumb_src.isNull()  # 載入前有佔位圖
    assert page.thumb.size() == nd.THUMB_LARGE
    pm = QPixmap(320, 180)
    pm.fill()
    [c for c in api.calls if c[0] == "IMG"][-1][3](pm)
    assert not page._thumb_src.isNull()
    page.resize(560, 700)
    assert wait_until(lambda: page.thumb.size() == nd.THUMB_SMALL)
    assert page.thumb.pixmap().width() == nd.THUMB_SMALL.width()
    page.close()


# --------------------------------------------------------------------------- #
#  驗收第 8 點：1000×700 不用捲動就看得到「下載」鈕
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("kind", ["video", "subs", "playlist"])
def test_download_button_visible_without_scrolling(app, kind):
    win = na.MainWindow(FakeApi(), lambda: False)
    try:
        win.resize(1000, 700)
        win.show()
        page = win.download
        page.on_info(playlist_info(30) if kind == "playlist" else video_info("V", "v"))
        for s in page.advanced.sections.values():  # 最糟的情況：所有進階分組都展開
            s.set_expanded(True)
        if kind == "subs":
            page.mode.set_value("subs")
            page.mode.changed.emit("subs")
        assert wait_until(lambda: page.download_btn.isVisible())
        wait_until(lambda: False, 100)  # 讓版面算完
        top_left = page.download_btn.mapTo(win, page.download_btn.rect().topLeft())
        bottom_right = page.download_btn.mapTo(win, page.download_btn.rect().bottomRight())
        assert win.rect().contains(top_left) and win.rect().contains(bottom_right)
        if kind == "playlist":  # 清單填滿剩下的高度
            assert page.playlist.height() > 300
    finally:
        win.close()
