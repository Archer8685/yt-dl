"""i18n.py 與 tools/i18n_update.py：語言設定、翻譯安裝、使用說明網址，以及「寫 tr → 抽字串 → 補英文 → 編譯 → 顯示英文」整條流程。"""
import importlib.util
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QCoreApplication, QLocale, QSettings
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import i18n_update

import i18n

GUIDE = "https://github.com/Archer8685/yt-dl/blob/main/USER_GUIDE.md"
GUIDE_EN = "https://github.com/Archer8685/yt-dl/blob/main/USER_GUIDE.en.md"


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch, qapp):
    """每個測試用自己的設定檔，結束後拿掉裝上的翻譯、還原預設地區。"""
    ini = tmp_path / "settings.ini"
    monkeypatch.setattr(i18n, "_settings", lambda: QSettings(str(ini), QSettings.IniFormat))
    locale = QLocale()
    i18n.uninstall()
    yield
    i18n.uninstall()
    QLocale.setDefault(locale)


def _have_qt_tools():
    try:
        i18n_update.find_tool("lupdate")
        i18n_update.find_tool("lrelease")
    except FileNotFoundError:
        return False
    return True


needs_tools = pytest.mark.skipif(not _have_qt_tools(), reason="沒有 PySide6 的 lupdate／lrelease")


def _write_ts(path: Path, messages):
    """寫一個最小的英文 .ts：messages 是 [(context, source, translation)]。"""
    ts = ET.Element("TS", version="2.1", language="en", sourcelanguage="zh_TW")
    for context, source, translation in messages:
        ctx = ET.SubElement(ts, "context")
        ET.SubElement(ctx, "name").text = context
        msg = ET.SubElement(ctx, "message")
        ET.SubElement(msg, "source").text = source
        ET.SubElement(msg, "translation").text = translation
    ET.ElementTree(ts).write(path, encoding="utf-8", xml_declaration=True)


# ---- 語言設定 ----

def test_setting_defaults_to_system():
    assert i18n.get_setting() == "system"


@pytest.mark.parametrize("value", ["system", "zh_TW", "en"])
def test_set_language_persists(value):
    i18n.set_language(value)
    assert i18n.get_setting() == value


def test_set_language_rejects_unknown_value():
    with pytest.raises(ValueError):
        i18n.set_language("fr")
    assert i18n.get_setting() == "system"


def test_unknown_stored_value_falls_back_to_system():
    i18n._settings().setValue(i18n.SETTINGS_KEY, "klingon")
    assert i18n.get_setting() == "system"


def test_settings_location_matches_app():
    """語言設定和 App 其他設定存在同一個地方。"""
    assert (i18n.SETTINGS_ORG, i18n.SETTINGS_APP, i18n.SETTINGS_KEY) == ("YTDownloader", "NativeApp", "ui/language")


@pytest.mark.parametrize("locales, expected", [
    (["zh-Hant-TW", "en-US"], "zh_TW"),
    (["zh-TW"], "zh_TW"),
    (["zh_HK"], "zh_TW"),
    (["zh-Hans-CN"], "zh_TW"),  # 只有繁中和英文，簡中使用者看繁中比英文好
    (["zh"], "zh_TW"),
    (["en-US", "zh-TW"], "en"),
    (["en"], "en"),
    (["ja-JP", "zh-TW"], "zh_TW"),  # 第一個認得的勝出
    (["ja-JP", "fr-FR"], "en"),  # 都不認得就用英文
    ([], "en"),
    (None, "en"),
    (["english"], "en"),  # 不是 en／en-… 標籤，不算認得；結果是英文是因為「都不認得就用英文」
    (["zhuang"], "en"),
])
def test_language_from_locales(locales, expected):
    assert i18n.language_from_locales(locales) == expected


def test_resolve_language_explicit_setting():
    assert i18n.resolve_language("zh_TW") == "zh_TW"
    assert i18n.resolve_language("en") == "en"


def test_resolve_language_system_uses_os_languages(monkeypatch):
    class FakeLocale:
        @staticmethod
        def system():
            return FakeLocale()

        def uiLanguages(self):
            return ["en-GB", "zh-TW"]

    monkeypatch.setattr(i18n, "QLocale", FakeLocale)
    assert i18n.resolve_language("system") == "en"
    i18n.set_language("system")
    assert i18n.resolve_language() == "en"


def test_current_language_before_install_follows_setting():
    i18n.set_language("en")
    assert i18n.current_language() == "en"
    i18n.set_language("zh_TW")
    assert i18n.current_language() == "zh_TW"


def test_current_language_after_install_needs_restart(qapp):
    """改設定要重新啟動才生效：install 之後 current_language 不跟著設定變。"""
    i18n.set_language("zh_TW")
    assert i18n.install(qapp) == "zh_TW"
    i18n.set_language("en")
    assert i18n.current_language() == "zh_TW"
    assert i18n.get_setting() == "en"


def test_accept_language():
    i18n.set_language("en")
    assert i18n.accept_language() == "en"
    i18n.set_language("zh_TW")
    assert i18n.accept_language() == "zh-TW"


# ---- 安裝翻譯 ----

def test_install_zh_tw_uses_qt_chinese(qapp):
    """中文介面不需要 App 翻譯檔，但要裝 Qt 的 qtbase_zh_TW.qm，標準按鈕才會是中文。"""
    assert i18n.install(qapp, "zh_TW") == "zh_TW"
    names = [Path(p).name for p in i18n.installed_translations()]
    assert names == ["qtbase_zh_TW.qm"]
    assert QCoreApplication.translate("QPlatformTheme", "Cancel") == "取消"
    assert QLocale().name() == "zh_TW"


def test_install_reads_saved_setting(qapp):
    i18n.set_language("zh_TW")
    assert i18n.install(qapp) == "zh_TW"
    assert i18n.current_language() == "zh_TW"


@needs_tools
def test_install_en_loads_app_translation(qapp, tmp_path, monkeypatch):
    _write_ts(tmp_path / "yt_dl_en.ts", [("Demo", "開始下載", "Start download")])
    i18n_update.run_lrelease(tmp_path / "yt_dl_en.ts")
    monkeypatch.setattr(i18n, "app_translation_dirs", lambda: [tmp_path / "missing", tmp_path])
    assert i18n.install(qapp, "en") == "en"
    assert QCoreApplication.translate("Demo", "開始下載") == "Start download"
    assert QCoreApplication.translate("QPlatformTheme", "Cancel") == "Cancel"
    assert Path(i18n.installed_translations()[0]) == tmp_path / "yt_dl_en.qm"
    assert QLocale().name() == "en_US"


def test_install_without_translation_files_keeps_source_text(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(i18n, "app_translation_dirs", lambda: [tmp_path])
    monkeypatch.setattr(i18n, "qt_translation_dirs", lambda: [tmp_path])
    assert i18n.install(qapp, "en") == "en"
    assert i18n.installed_translations() == []
    assert QCoreApplication.translate("Demo", "開始下載") == "開始下載"


def test_install_twice_replaces_translators(qapp):
    i18n.install(qapp, "zh_TW")
    i18n.install(qapp, "zh_TW")
    assert len(i18n.installed_translations()) == 1


def test_install_needs_application(monkeypatch):
    monkeypatch.setattr(i18n.QCoreApplication, "instance", staticmethod(lambda: None))
    with pytest.raises(RuntimeError):
        i18n.install()


def test_uninstall_restores_source_text(qapp):
    i18n.install(qapp, "zh_TW")
    i18n.uninstall()
    assert i18n.installed_translations() == []
    assert QCoreApplication.translate("QPlatformTheme", "Cancel") == "Cancel"


def test_frozen_app_looks_in_meipass(qapp, tmp_path, monkeypatch):
    """PyInstaller 打包版：App 翻譯檔在 _MEIPASS/i18n，Qt 翻譯檔在 _MEIPASS/PySide6/translations。"""
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert i18n.app_translation_dirs()[0] == tmp_path / "i18n"
    assert i18n.qt_translation_dirs()[0] == tmp_path / "PySide6" / "translations"
    if not _have_qt_tools():
        pytest.skip("沒有 lrelease")
    (tmp_path / "i18n").mkdir()
    _write_ts(tmp_path / "i18n" / "yt_dl_en.ts", [("Demo", "暫停", "Pause")])
    i18n_update.run_lrelease(tmp_path / "i18n" / "yt_dl_en.ts")
    i18n.install(qapp, "en")
    assert QCoreApplication.translate("Demo", "暫停") == "Pause"


def test_source_layout_dirs():
    assert ROOT / "i18n" in i18n.app_translation_dirs()
    assert any((d / "qtbase_zh_TW.qm").is_file() for d in i18n.qt_translation_dirs())


# ---- 使用說明網址 ----

@pytest.mark.parametrize("anchor, lang, expected", [
    ("", "zh_TW", GUIDE),
    ("", "en", GUIDE_EN),
    ("err-private", "zh_TW", GUIDE + "#err-private"),
    ("#err-private", "en", GUIDE_EN + "#err-private"),
    ("  ", "en", GUIDE_EN),
    ("#", "zh_TW", GUIDE),
    ("faq", "fr", GUIDE + "#faq"),  # 不認得的語言用中文版
])
def test_guide_url(anchor, lang, expected):
    assert i18n.guide_url(anchor, lang=lang) == expected


def test_guide_url_follows_current_language(qapp):
    i18n.set_language("en")
    assert i18n.guide_url("err-private") == GUIDE_EN + "#err-private"
    i18n.install(qapp, "zh_TW")
    assert i18n.guide_url() == GUIDE


# ---- 翻譯檔與工具 ----

def test_ui_sources_excludes_engine_files():
    names = {p.name for p in i18n_update.ui_sources()}
    assert {"native_app.py", "i18n.py"} <= names
    assert not names & i18n_update.EXCLUDE


def test_translation_file_header():
    root = ET.parse(ROOT / "i18n" / "yt_dl_en.ts").getroot()
    assert root.tag == "TS"
    assert root.get("language") == "en"
    assert root.get("sourcelanguage") == "zh_TW"


@needs_tools
def test_committed_qm_matches_ts(tmp_path):
    """i18n/yt_dl_en.qm 要是由目前的 .ts 編出來的（改了 .ts 忘了重新編譯會失敗）。"""
    qm = i18n_update.run_lrelease(ROOT / "i18n" / "yt_dl_en.ts", tmp_path / "fresh.qm")
    assert qm.read_bytes() == (ROOT / "i18n" / "yt_dl_en.qm").read_bytes(), "請執行 python tools/i18n_update.py --release-only"


def test_main_reports_missing_tool(monkeypatch, capsys):
    def missing(name):
        raise FileNotFoundError(f"找不到 {name}")

    monkeypatch.setattr(i18n_update, "find_tool", missing)
    assert i18n_update.main(["--release-only"]) == 1
    assert "找不到 lrelease" in capsys.readouterr().err


def test_main_reports_missing_ts(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(i18n_update, "I18N_DIR", tmp_path)
    assert i18n_update.main(["--release-only"]) == 1
    assert "請先抽字串" in capsys.readouterr().err


@needs_tools
def test_main_runs_lupdate_and_lrelease(monkeypatch, tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "panel.py").write_text('from PySide6.QtCore import QCoreApplication\n'
                                  'X = QCoreApplication.translate("panel", "儲存")\n', encoding="utf-8")
    (src / "server.py").write_text('from PySide6.QtCore import QCoreApplication\n'
                                   'X = QCoreApplication.translate("server", "引擎")\n', encoding="utf-8")
    monkeypatch.setattr(i18n_update, "ROOT", src)
    monkeypatch.setattr(i18n_update, "I18N_DIR", tmp_path / "out")
    assert i18n_update.main([]) == 0
    ts = (tmp_path / "out" / "yt_dl_en.ts").read_text(encoding="utf-8")
    assert "<source>儲存</source>" in ts
    assert "引擎" not in ts  # server.py 不抽
    assert (tmp_path / "out" / "yt_dl_en.qm").is_file()


# ---- 整條流程：寫 tr → 抽字串 → 補英文 → 編譯 → 切成 English 顯示英文 ----

DEMO_WIDGET = '''
from PySide6.QtCore import QCoreApplication, QT_TRANSLATE_NOOP
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

_tr = QCoreApplication.translate

KIND_TEXT = {
    "video": QT_TRANSLATE_NOOP("DemoPanel", "影片"),
}


class DemoPanel(QWidget):
    def __init__(self, title, count):
        super().__init__()
        layout = QVBoxLayout(self)
        self.heading = QLabel(_tr("DemoPanel", "「{title}」共有 %n 部", None, count).format(title=title))
        self.kind = QLabel(_tr("DemoPanel", KIND_TEXT["video"]))
        self.button = QPushButton(self.tr("開始下載"))
        self.clear = QPushButton(self.tr("清除", "清除已完成的工作"))
        self.plain = QLabel(QCoreApplication.translate("demo_widget", "全部完成"))
        for w in (self.heading, self.kind, self.button, self.clear, self.plain):
            layout.addWidget(w)

    @staticmethod
    def empty_text():
        return QCoreApplication.translate("DemoPanel", "清單是空的")


class SubPanel(DemoPanel):
    pass
'''

ENGLISH = {
    ("DemoPanel", "影片", None): "Video",
    ("DemoPanel", "開始下載", None): "Start download",
    ("DemoPanel", "清除", "清除已完成的工作"): "Clear finished",
    ("DemoPanel", "清單是空的", None): "The list is empty",
    ("demo_widget", "全部完成", None): "All done",
}
PLURAL = {("DemoPanel", "「{title}」共有 %n 部"): ("“{title}” has %n video", "“{title}” has %n videos")}


def _fill_english(ts_file: Path):
    """模擬 I2 補英文：照 ENGLISH／PLURAL 填翻譯並拿掉「未完成」標記。"""
    tree = ET.parse(ts_file)
    found = set()
    for ctx in tree.getroot().iter("context"):
        name = ctx.findtext("name")
        for msg in ctx.iter("message"):
            source, comment = msg.findtext("source"), msg.findtext("comment")
            translation = msg.find("translation")
            found.add((name, source, comment))
            if msg.get("numerus") == "yes":
                forms = translation.findall("numerusform")
                for form, text in zip(forms, PLURAL[(name, source)]):
                    form.text = text
            else:
                translation.text = ENGLISH[(name, source, comment)]
            translation.attrib.pop("type", None)
    tree.write(ts_file, encoding="utf-8", xml_declaration=True)
    return found


def _load_module(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@needs_tools
def test_full_pipeline_switches_demo_widget_to_english(qapp, tmp_path, monkeypatch):
    src = tmp_path / "demo_widget.py"
    src.write_text(DEMO_WIDGET, encoding="utf-8")
    out = tmp_path / "i18n"
    ts = out / "yt_dl_en.ts"

    # 1. 抽字串：self.tr、QCoreApplication.translate、_tr、QT_TRANSLATE_NOOP、%n、說明文字都要抽得到
    i18n_update.run_lupdate([src], ts, "en")
    found = _fill_english(ts)
    expected = {k for k in ENGLISH} | {(c, s, None) for c, s in PLURAL}
    assert found == expected

    # 2. 再跑一次抽字串，補好的翻譯要保留
    i18n_update.run_lupdate([src], ts, "en")
    assert 'type="unfinished"' not in ts.read_text(encoding="utf-8")

    # 3. 編譯，切成 English
    i18n_update.run_lrelease(ts)
    monkeypatch.setattr(i18n, "app_translation_dirs", lambda: [out])
    i18n.set_language("en")
    assert i18n.install(qapp) == "en"

    demo = _load_module(src)
    one = demo.DemoPanel("Song", 1)
    many = demo.SubPanel("Mix", 3)  # 子類別沿用父類別的翻譯（%n 要用 translate 寫明類別名，見 docs/I18N.md 2.4）
    try:
        assert one.heading.text() == "“Song” has 1 video"
        assert many.heading.text() == "“Mix” has 3 videos"
        assert one.kind.text() == "Video"
        assert one.button.text() == many.button.text() == "Start download"
        assert one.clear.text() == "Clear finished"
        assert one.plain.text() == "All done"
        assert demo.DemoPanel.empty_text() == "The list is empty"
    finally:
        one.deleteLater()
        many.deleteLater()

    # 4. 中文介面：顯示原文
    i18n.install(qapp, "zh_TW")
    zh = demo.DemoPanel("歌", 2)
    try:
        assert zh.heading.text() == "「歌」共有 2 部"
        assert zh.button.text() == "開始下載"
        assert zh.kind.text() == "影片"
    finally:
        zh.deleteLater()
