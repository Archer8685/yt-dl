"""原生介面進階選項面板：apply() 產生的選項餵給 server.build_opts() 要得到正確的 yt-dlp 參數。"""
import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication

import server
from native_options import AdvancedOptions, range_error

JOB = Path("downloads/_test")
INFO = {
    "type": "video", "title": "t",
    "audio_tracks": [{"lang": "en-US", "label": "English", "original": True, "count": 3},
                     {"lang": "ja", "label": "日本語", "original": False, "count": 2}],
    "subtitles": [{"lang": "zh-TW", "name": "中文（台灣）", "exts": ["vtt"]},
                  {"lang": "en", "name": "English", "exts": ["vtt"]}],
    "auto_captions": [{"lang": "ja", "name": "Japanese", "exts": ["vtt"]},
                      {"lang": "zh-Hant", "name": "Chinese (Traditional)", "exts": ["vtt"]}],
    "chapters": [{"title": "Intro", "start": 0, "end": 65.0}, {"title": "Main", "start": 65.0, "end": 300.0},
                 {"title": "Outro", "start": 300.0, "end": None}],
}
# DownloadPage.options() 產生的基本選項（與 native_app.py 相同結構）
BASE = {"mode": "av", "video": {"max_height": 1080, "container": "mp4"},
        "audio": {"languages": [], "codec": "mp3", "quality": "0"},
        "subs": {"languages": [], "auto_languages": [], "format": "srt"},
        "extras": {"embed_chapters": True, "embed_thumbnail": True, "embed_metadata": False}}


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def settings(tmp_path):
    return QSettings(str(tmp_path / "s.ini"), QSettings.IniFormat)


@pytest.fixture
def adv(app, settings):
    w = AdvancedOptions(settings=settings)
    w.set_info(INFO)
    return w


def build(o):
    return server.build_opts(o, JOB)


def pps(opts):
    return {p["key"]: p for p in opts["postprocessors"]}


def test_defaults_match_web(adv):
    o = adv.apply(BASE)
    x, s = o["extras"], o["subs"]
    assert x["embed_metadata"] and x["embed_chapters"] and x["embed_thumbnail"]
    assert not x["write_thumbnail"] and not x["split_chapters"] and not x["keep_original"]
    assert x["template"] == "%(title)s [%(id)s].%(ext)s" and x["fragments"] == 4 and x["retries"] == 10
    assert s["format"] == "srt" and s["embed"] and s["keep_files"] and not s["all"]
    assert o["video"]["codec"] == "" and o["audio"]["allow_drc"] is False
    assert o["network"] == {"proxy": "", "cookies_browser": "", "geo_country": "", "cookies_file": False}
    r = build(o)
    assert r["format"] == "bv*+ba[format_id!*=drc]/bv*+ba/b"
    assert {"FFmpegMetadata", "EmbedThumbnail", "FFmpegThumbnailsConvertor"} <= set(pps(r))
    assert pps(r)["FFmpegMetadata"]["add_chapters"] is True


def test_apply_does_not_mutate_input(adv):
    base = {"mode": "av", "audio": {"languages": ["ja"]}}
    adv.tracks.set_values({"en-US"})
    adv.apply(base)
    assert base == {"mode": "av", "audio": {"languages": ["ja"]}}


def test_multi_audio_tracks(adv):
    adv.tracks.set_values({"en-US", "ja"})
    r = build(adv.apply(BASE))
    assert r["format"].startswith("bv*+ba[language^=en-US][format_id!*=drc]+ba[language^=ja]")
    assert r["allow_multiple_audio_streams"] is True


def test_tracks_union_with_basic_track(adv):
    adv.tracks.set_values({"ja"})
    o = adv.apply({**BASE, "audio": {"languages": ["en-US"]}})
    assert o["audio"]["languages"] == ["en-US", "ja"]


def test_audio_prefer_codec_and_drc(adv):
    adv.prefer_acodec.set_value("opus")
    adv.allow_drc.setChecked(True)
    r = build(adv.apply(BASE))
    assert "acodec:opus" in r["format_sort"]
    assert "drc" not in r["format"]


def test_video_codec_fps_hdr(adv):
    adv.codec.set_value("av01")
    adv.max_fps.setCurrentIndex(adv.max_fps.findData("30"))
    adv.hdr.set_value("sdr")
    r = build(adv.apply(BASE))
    assert r["format_sort"] == ["res:1080", "vcodec:av01", "fps:30", "hdr:sdr"]


def test_recode_and_premium(adv):
    adv.recode.setChecked(True)
    adv.premium.setChecked(True)
    r = build(adv.apply(BASE))
    assert pps(r)["FFmpegVideoConvertor"]["preferedformat"] == "mp4"
    assert r["format"].startswith("bv*[format_note*=Premium]")


def test_subtitles_languages_format_embed(adv):
    adv.subs.set_values({"zh-TW"})
    adv.autos.set_values({"ja"})
    adv.sub_format.set_value("ass")
    adv.sub_keep.setChecked(False)
    r = build(adv.apply(BASE))
    assert r["subtitleslangs"] == ["zh-TW", "ja"]
    assert r["writesubtitles"] is True and r["writeautomaticsub"] is True
    assert r["subtitlesformat"] == "ass/vtt/best"
    assert pps(r)["FFmpegSubtitlesConvertor"]["format"] == "ass"
    assert pps(r)["FFmpegEmbedSubtitle"]["already_have_subtitle"] is False


def test_subtitles_all_and_quick_pick(adv):
    adv.quick_pick(r"^zh(-Hant|-TW|-HK|-Hans|-CN)?$")
    assert adv.subs.values() == ["zh-TW"]
    adv.clear_subs()
    adv.sub_all.setChecked(True)
    r = build(adv.apply({**BASE, "mode": "subs"}))
    assert r["subtitleslangs"] == ["all"] and r["skip_download"] is True


def test_quick_pick_falls_back_to_auto_captions(app, settings):
    w = AdvancedOptions(settings=settings)
    w.set_info({**INFO, "subtitles": []})
    w.quick_pick(r"^zh(-Hant|-TW|-HK|-Hans|-CN)?$")
    assert w.autos.values() == ["zh-Hant"]


def test_sponsorblock(adv):
    adv.sb_remove.set_values({"sponsor", "selfpromo"})
    adv.sb_mark.set_values({"intro"})
    r = build(adv.apply(BASE))
    p = pps(r)
    assert set(p["SponsorBlock"]["categories"]) == {"sponsor", "selfpromo", "intro"}
    assert set(p["ModifyChapters"]["remove_sponsor_segments"]) == {"sponsor", "selfpromo"}
    assert "poi_highlight" not in adv.sb_remove.chips and "poi_highlight" in adv.sb_mark.chips


def test_sections_from_chapters_and_split(adv):
    adv.add_chapter(INFO["chapters"][0])
    adv.add_chapter(INFO["chapters"][2])
    assert adv.sections_edit.text() == "0:00-1:05, 5:00-end"
    adv.force_keyframes.setChecked(True)
    adv.split_chapters.setChecked(True)
    r = build(adv.apply(BASE))
    assert r["force_keyframes_at_cuts"] is True
    assert pps(r)["FFmpegSplitChapters"]["force_keyframes"] is True
    ranges = list(r["download_ranges"]({"duration": 400}, None))
    assert [(x["start_time"], x["end_time"]) for x in ranges] == [(0, 65), (300, float("inf"))]
    assert adv.error() == ""


def test_range_validation():
    assert range_error("0:30-1:45, 3:00-end") == ""
    assert range_error("1:00-0:30")
    assert range_error("abc")
    with pytest.raises(ValueError):
        server._parse_ranges("1:00-0:30")


def test_files_and_template(adv):
    adv.write_thumbnail.setChecked(True)
    adv.thumb_format.set_value("png")
    adv.write_description.setChecked(True)
    adv.write_comments.setChecked(True)
    adv.keep_original.setChecked(True)
    adv.restrict_filenames.setChecked(True)
    adv.template_preset.setCurrentIndex(adv.template_preset.findData("%(uploader)s - %(title)s.%(ext)s"))
    r = build(adv.apply(BASE))
    assert r["outtmpl"]["default"] == "%(uploader)s - %(title)s.%(ext)s"
    assert r["writedescription"] and r["writeinfojson"] and r["getcomments"]
    assert r["keepvideo"] and r["restrictfilenames"]
    assert pps(r)["FFmpegThumbnailsConvertor"]["format"] == "png"
    assert pps(r)["EmbedThumbnail"]["already_have_thumbnail"] is True
    adv.template.setText("%(id)s.%(ext)s")
    assert adv.template_preset.currentData() == "custom"


def test_network(adv, monkeypatch, tmp_path):
    adv.proxy.setText("socks5://127.0.0.1:1080")
    adv.geo.setText("tw")
    adv.rate_limit.setText("5M")
    adv.fragments.setValue(8)
    adv.retries.setValue(0)
    adv.cookie_source.setCurrentIndex(adv.cookie_source.findData("browser"))
    adv.browser.setCurrentIndex(adv.browser.findData("firefox"))
    assert adv.network() == {"proxy": "socks5://127.0.0.1:1080", "cookies_browser": "firefox",
                             "geo_country": "tw", "cookies_file": False}
    r = build(adv.apply(BASE))
    assert r["proxy"] == "socks5://127.0.0.1:1080" and r["geo_bypass_country"] == "TW"
    assert r["cookiesfrombrowser"][0] == "firefox"
    assert r["ratelimit"] == 5 * 1024 ** 2
    assert r["concurrent_fragment_downloads"] == 8 and r["retries"] == 0

    cookies = tmp_path / "cookies.txt"
    cookies.write_text("x")
    monkeypatch.setattr(server, "COOKIES_FILE", cookies)
    adv.cookie_source.setCurrentIndex(adv.cookie_source.findData("file"))
    assert adv.network()["cookies_file"] is True and adv.network()["cookies_browser"] == ""
    r = build(adv.apply(BASE))
    assert r["cookiefile"] == str(cookies) and "cookiesfrombrowser" not in r


def test_settings_roundtrip(app, settings):
    a = AdvancedOptions(settings=settings)
    a.codec.set_value("vp9")
    a.codec.changed.emit("vp9")  # Segmented 只在點擊時發出 changed
    a.embed_chapters.setChecked(False)
    a.sb_remove.set_values({"sponsor"})
    a.template.setText("%(title)s.%(ext)s")
    a.fragments.setValue(12)
    a.cookie_source.setCurrentIndex(a.cookie_source.findData("browser"))
    a.sections["network"].set_expanded(True)
    settings.sync()

    b = AdvancedOptions(settings=QSettings(settings.fileName(), QSettings.IniFormat))
    assert b.codec.value() == "vp9"
    assert b.embed_chapters.isChecked() is False and b.embed_thumbnail.isChecked() is True
    assert b.sb_remove.values() == ["sponsor"]
    assert b.template.text() == "%(title)s.%(ext)s" and b.template_preset.currentData() == "%(title)s.%(ext)s"
    assert b.fragments.value() == 12
    assert b.cookie_source.currentData() == "browser"
    assert b.sections["network"].expanded() is True and b.sections["video"].expanded() is False


def test_reset_restores_defaults(adv):
    adv.embed_metadata.setChecked(False)
    adv.retries.setValue(3)
    adv.sb_mark.set_values({"intro"})
    adv.reset()
    o = adv.apply(BASE)
    assert o["extras"]["embed_metadata"] is True and o["extras"]["retries"] == 10
    assert o["extras"]["sponsor_mark"] == []


def test_set_info_clears_previous_selection(adv):
    adv.tracks.set_values({"ja"})
    adv.sections_edit.setText("0:10-0:20")
    adv.set_info({"audio_tracks": [], "subtitles": [], "auto_captions": [], "chapters": []})
    o = adv.apply(BASE)
    assert o["audio"]["languages"] == [] and o["extras"]["sections"] == ""
    assert not adv.chapters.isVisibleTo(adv)


def test_set_mode_hides_sections(adv):
    adv.set_mode("audio")
    assert not adv.sections["video"].isVisibleTo(adv)
    assert adv.sections["audio"].isVisibleTo(adv)
    adv.set_mode("thumb")
    assert not adv.sections["subs"].isVisibleTo(adv) and not adv.sections["clip"].isVisibleTo(adv)


def test_switch_toggles(app):
    from native_options import Switch
    sw = Switch()
    assert not sw.isChecked()
    sw.click()
    assert sw.isChecked()
    assert (sw.sizeHint().width(), sw.sizeHint().height()) == (38, 22)  # macOS 開關尺寸


def test_hint_and_mono_follow_app_stylesheet(app):
    """說明文字與等寬輸入框不能自己寫死字型：要由 App 的樣式表決定，才會跟著「文字大小」設定。"""
    from native_options import _field, _hint
    h = _hint("x")
    assert h.objectName() == "hint" and not h.testAttribute(Qt.WA_SetFont)
    e = _field("p")
    assert e.property("mono") is True and not e.testAttribute(Qt.WA_SetFont)


def test_theme_colors_parse(app):
    """tokens() 裡的 CSS rgba() 字串要能轉成 QColor（不然自己畫的元件會變成黑色）。"""
    from native_app import tokens
    from native_options import _color
    for dark in (False, True):
        for key, value in tokens(dark).items():
            assert _color(value).isValid(), (key, value)
    c = _color("rgba(0,0,0,0.08)")
    assert (c.red(), c.green(), c.blue()) == (0, 0, 0) and abs(c.alphaF() - 0.08) < 0.01
    assert _color("#007AFF").name() == "#007aff"


def test_panel_has_no_own_stylesheet_and_follows_theme(adv):
    """樣式統一由 native_app.stylesheet() 決定：面板與子元件都不能自己 setStyleSheet。"""
    from PySide6.QtWidgets import QWidget

    import native_options
    from native_app import tokens
    assert adv.styleSheet() == ""
    assert all(w.styleSheet() == "" for w in adv.findChildren(QWidget))
    adv.apply_theme(tokens(True))
    assert native_options.THEME["accent"] == tokens(True)["accent"]
    adv.sections_edit.setText("2:00-1:00")
    assert tokens(True)["red"] in adv.range_hint.text()
    adv.apply_theme(tokens(False))


# --------------------------------------------------------------------------- v1.3：時間範圍訊息

def test_range_error_messages_name_the_bad_part_and_give_example():
    msg = range_error("0:30-1:00, abc")
    assert "abc" in msg and "例如：0:30-1:45, 3:00-end" in msg
    msg = range_error("0:10-0:20, 2:00-1:00")
    assert "2:00-1:00" in msg and "結束時間比開始時間晚" in msg
    # 引擎接受的 App 也要接受（規則用同一個解析器）
    for ok in ("0:30-1:45", "1:00-end", "10-20; 30-40", "1:00:00-1:30:00"):
        assert range_error(ok) == "", ok
        server._parse_ranges(ok)


# --------------------------------------------------------------------------- v1.3：reveal_section（DL2）

def _in_scroll(adv):
    from PySide6.QtWidgets import QScrollArea, QVBoxLayout, QWidget
    sc = QScrollArea()
    sc.setWidgetResizable(True)
    inner = QWidget()
    lay = QVBoxLayout(inner)
    filler = QWidget()
    filler.setFixedHeight(900)  # 進階選項在頁面下方，要捲才看得到
    lay.addWidget(filler)
    lay.addWidget(adv)
    sc.setWidget(inner)
    sc.resize(700, 500)
    sc.show()
    QApplication.processEvents()
    return sc


@pytest.mark.parametrize("key, section", [("subtitles", "subs"), ("subs", "subs"), ("clip", "clip"),
                                          ("network", "network"), ("cookies", "network"), ("video", "video")])
def test_reveal_section_expands_and_scrolls(adv, key, section):
    sc = _in_scroll(adv)
    s = adv.sections[section]
    s.set_expanded(False)
    assert sc.verticalScrollBar().value() == 0
    assert adv.reveal_section(key) is True
    assert s.expanded()
    QApplication.processEvents()  # 捲動延到下一輪事件
    top = s.header.mapTo(sc.widget(), s.header.rect().topLeft()).y()
    view_top = sc.verticalScrollBar().value()
    assert view_top <= top <= view_top + sc.viewport().height() - s.header.height()
    sc.close()


def test_reveal_section_remembers_expanded(adv, settings):
    adv.sections["clip"].set_expanded(False)
    adv.reveal_section("clip")
    settings.beginGroup("advanced")
    assert settings.value("open_clip") in (True, "true")
    settings.endGroup()


def test_reveal_section_focus_and_unknown_or_hidden(adv):
    sc = _in_scroll(adv)
    sc.activateWindow()
    assert adv.reveal_section("nope") is False
    adv.set_mode("thumb")  # 縮圖模式沒有剪輯分組
    assert adv.reveal_section("clip") is False
    adv.set_mode("av")
    assert adv.reveal_section("clip", focus=True) is True
    assert QApplication.focusWidget() is adv.sections_edit
    assert adv.reveal_section("files", focus=True) is True  # 沒有主要輸入元件的分組：焦點移到分組標題
    assert QApplication.focusWidget() is adv.sections["files"].header
    sc.close()


# --------------------------------------------------------------------------- v1.3：無障礙（A11Y1／A11Y2）

def _expanded(adv):
    for s in adv.sections.values():
        s.set_expanded(True)
    adv.cookie_exists = True
    adv._on_changed()
    adv.resize(720, 2400)
    adv.show()
    QApplication.processEvents()


def test_every_focusable_widget_has_a_name(adv):
    """驗收第 9 點：所有可以取得焦點的元件都要有文字或 accessibleName。"""
    from PySide6.QtWidgets import QAbstractButton, QWidget
    _expanded(adv)
    missing = []
    for w in adv.findChildren(QWidget):
        if not w.isVisibleTo(adv) or not (w.focusPolicy() & Qt.TabFocus):
            continue
        if w.objectName().startswith("qt_"):  # QLineEdit 的清除鈕這類 Qt 內部元件
            continue
        text = w.text() if isinstance(w, QAbstractButton) else ""
        if not (text or w.accessibleName()):
            missing.append(f"{type(w).__name__}:{w.objectName()}")
    adv.close()
    assert not missing, missing


def test_switches_and_rows_are_named(adv):
    from native_options import Switch
    switches = adv.findChildren(Switch)
    assert len(switches) >= 19 and all(sw.accessibleName() for sw in switches)
    assert adv.recode.accessibleName() == "一律轉檔成選擇的格式"
    assert "Premium" in adv.premium.accessibleDescription()
    assert adv.max_fps.accessibleName() == "畫面更新率上限"
    assert adv.codec.buttons["av01"].accessibleDescription() == "編碼偏好"
    assert adv.sections_edit.accessibleName() == "時間範圍"
    assert Switch(False, title="測試").accessibleName() == "測試"


def test_section_header_reports_name_and_state(adv):
    h = adv.sections["subs"].header
    adv.sections["subs"].set_expanded(False)
    assert h.accessibleName().startswith("字幕") and "收合" in h.accessibleDescription()
    adv.sections["subs"].set_expanded(True)
    assert h.accessibleDescription() == "已展開"
    adv.subs.set_values({"en"})
    assert "1 種語言" in h.accessibleName()  # 摘要也一起念


def test_chip_reports_checkable_state(adv):
    from PySide6.QtGui import QAccessible
    chip = adv.subs.chips["en"]
    iface = QAccessible.queryAccessibleInterface(chip)
    assert iface.text(QAccessible.Name) == "English"
    assert iface.state().checkable and not iface.state().checked
    chip.click()
    assert QAccessible.queryAccessibleInterface(chip).state().checked
    chapter = adv.chapter_flow.itemAt(0).widget()
    assert not chapter.isCheckable() and "Intro" in chapter.accessibleName()


def test_decorations_do_not_take_focus(adv):
    from native_options import Chevron, Icon
    for w in adv.findChildren(Icon) + adv.findChildren(Chevron):
        assert w.focusPolicy() == Qt.NoFocus
    assert adv.autos_scroll.focusPolicy() == Qt.NoFocus  # 捲動區不是看不見的 Tab 停留點


def test_segmented_arrow_keys(adv):
    """A11Y2：分段控制可以用方向鍵切換（Tab 只停在選中的那顆）。"""
    from PySide6.QtTest import QTest
    _expanded(adv)
    seen = []
    adv.changed.connect(lambda: seen.append(adv.codec.value()))
    adv.codec.buttons[""].setFocus()
    QTest.keyClick(adv.codec.buttons[""], Qt.Key_Right)
    assert adv.codec.value() == "av01" and adv.codec.buttons["av01"].hasFocus() and seen
    QTest.keyClick(adv.codec.buttons["av01"], Qt.Key_Left)
    assert adv.codec.value() == ""
    adv.close()


def test_custom_widgets_size_from_font_metrics(app):
    """英文較長、文字放大時，自己畫的標籤和開關要跟著變大，不能把字切掉。"""
    from PySide6.QtGui import QFont

    from native_options import Chip, Switch
    chip = Chip("Interaction reminder (subscribe)")
    assert chip.sizeHint().width() >= chip.fontMetrics().horizontalAdvance(chip.text()) + 20
    big = QFont()
    big.setPixelSize(32)
    chip.setFont(big)
    sw = Switch()
    sw.setFont(big)
    assert chip.sizeHint().height() > chip.fontMetrics().height()
    assert sw.sizeHint().height() > 22 and sw.sizeHint().width() > 38


def test_focus_rings_paint(adv):
    """自繪元件取得焦點時畫 2 px 焦點環（只確認畫得出來、不出錯）。"""
    _expanded(adv)
    for w in (adv.recode, adv.subs.chips["en"], adv.sections["video"].header):
        w.setFocus()
        assert not w.grab().isNull()
    adv.close()


# --------------------------------------------------------------------------- v1.3：恢復預設＋復原（DL12）

def test_reset_button_names_its_scope(adv):
    assert adv.reset_btn.text() == "進階選項恢復預設"


def test_reset_can_be_undone(adv):
    adv.embed_metadata.setChecked(False)
    adv.retries.setValue(3)
    adv.sb_mark.set_values({"intro"})
    before = adv.apply(BASE)
    adv.reset()
    assert adv.can_undo_reset() and adv.undo_btn.isVisibleTo(adv) and not adv.reset_btn.isVisibleTo(adv)
    assert adv.apply(BASE)["extras"]["retries"] == 10
    assert adv.undo_reset() is True
    assert adv.apply(BASE) == before
    assert not adv.can_undo_reset() and adv.reset_btn.isVisibleTo(adv) and not adv.undo_btn.isVisibleTo(adv)
    assert adv.undo_reset() is False


def test_keyboard_reset_moves_focus_to_undo(adv):
    adv.show()
    adv.activateWindow()
    adv.retries.setValue(3)
    adv.reset_btn.setFocus()
    QApplication.processEvents()
    assert QApplication.focusWidget() is adv.reset_btn
    adv.reset()
    assert QApplication.focusWidget() is adv.undo_btn
    adv.undo_reset()
    assert QApplication.focusWidget() is adv.reset_btn  # 復原鈕消失後焦點回到恢復預設
    adv.close()


def test_undo_is_dropped_after_a_new_change(adv):
    adv.retries.setValue(3)
    adv.reset()
    assert adv.can_undo_reset()
    adv.premium.setChecked(True)  # 恢復預設後又改了：不能再復原（會蓋掉新的修改）
    assert not adv.can_undo_reset() and adv.reset_btn.isVisibleTo(adv)


def test_undo_expires(adv):
    adv.retries.setValue(3)
    adv.reset()
    adv._undo_timer.timeout.emit()
    assert not adv.can_undo_reset()


def test_reset_when_already_default_offers_no_undo(app, settings):
    msgs = []
    w = AdvancedOptions(settings=settings, toast=lambda text, **_k: msgs.append(text))
    w.reset()
    assert not w.can_undo_reset() and msgs == ["進階選項已經是預設值"]


def test_reset_toast_has_undo_action_when_supported(app, settings):
    calls = []

    def toast(text, level="info", actions=None):
        calls.append((text, actions))

    w = AdvancedOptions(settings=settings, toast=toast)
    w.retries.setValue(3)
    w.reset()
    text, actions = calls[-1]
    assert text == "已將進階選項恢復預設" and actions and actions[0][0] == "復原"
    actions[0][1]()
    assert w.retries.value() == 3

    old = []
    w2 = AdvancedOptions(settings=settings, toast=lambda text, error=False: old.append(text))  # 舊版 toast
    w2.retries.setValue(4)
    w2.reset()
    assert old[-1] == "已將進階選項恢復預設"
