"""App 介面的多語系（英文介面）基礎。

字串怎麼寫見 docs/I18N.md。這個模組只負責：
- 語言設定（system／zh_TW／en）存在 QSettings("YTDownloader", "NativeApp") 的 ui/language。
- 啟動時 install(app)：依設定安裝 App 自己的 yt_dl_<lang>.qm 和 Qt 內建的 qtbase_<lang>.qm。
- current_language()：目前介面實際使用的語言（"zh_TW" 或 "en"）。
- guide_url(anchor)：依語言回傳使用說明（USER_GUIDE.md／USER_GUIDE.en.md）的網址。

切換語言後要重新啟動 App 才生效（不做即時切換），所以 current_language() 回傳的是
install() 當時套用的語言，不是剛存進去的設定。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QLibraryInfo, QLocale, QSettings, QTranslator

SETTINGS_ORG = "YTDownloader"
SETTINGS_APP = "NativeApp"
SETTINGS_KEY = "ui/language"

SYSTEM = "system"
ZH_TW = "zh_TW"
EN = "en"
SETTINGS_CHOICES = (SYSTEM, ZH_TW, EN)  # 設定可以存的值
LANGUAGES = (ZH_TW, EN)  # 介面實際會用的語言
SOURCE_LANGUAGE = ZH_TW  # 原文是繁體中文，這個語言不需要 App 自己的翻譯檔
FALLBACK_LANGUAGE = EN  # 系統語言既不是中文也不是英文時用英文

QM_PREFIX = "yt_dl"  # App 翻譯檔：i18n/yt_dl_<lang>.qm

REPO_BLOB_URL = "https://github.com/Archer8685/yt-dl/blob/main/"
GUIDE_FILES = {ZH_TW: "USER_GUIDE.md", EN: "USER_GUIDE.en.md"}

# QLocale.setDefault 用的地區（影響數字、日期格式）
_LOCALE_NAMES = {ZH_TW: "zh_TW", EN: "en_US"}

_current: str | None = None  # install() 套用的語言
_translators: list[QTranslator] = []  # 要一直留著參照，否則被回收後翻譯就失效


def _settings() -> QSettings:
    return QSettings(SETTINGS_ORG, SETTINGS_APP)


def get_setting() -> str:
    """回傳使用者設定的語言："system"、"zh_TW" 或 "en"。沒設定或值不認得時當成 "system"。"""
    value = _settings().value(SETTINGS_KEY, SYSTEM)
    return value if value in SETTINGS_CHOICES else SYSTEM


def set_language(setting: str) -> None:
    """儲存語言設定（"system"、"zh_TW"、"en"）。下次啟動 App 才生效。"""
    if setting not in SETTINGS_CHOICES:
        raise ValueError(f"unknown language setting: {setting!r}")
    s = _settings()
    s.setValue(SETTINGS_KEY, setting)
    s.sync()


def language_from_locales(ui_languages) -> str:
    """從系統的介面語言清單（偏好順序，例如 ["zh-Hant-TW", "en-US"]）挑出 App 要用的語言。

    第一個認得的語言勝出：中文（不分繁簡）用 zh_TW，英文用 en；都不認得就用英文。
    """
    for name in ui_languages or ():
        tag = str(name).replace("_", "-").lower()
        if tag == "zh" or tag.startswith("zh-"):
            return ZH_TW
        if tag == "en" or tag.startswith("en-"):
            return EN
    return FALLBACK_LANGUAGE


def resolve_language(setting: str | None = None) -> str:
    """把設定換成實際語言（"zh_TW" 或 "en"）。setting 省略時讀目前的設定。"""
    if setting is None:
        setting = get_setting()
    if setting in LANGUAGES:
        return setting
    return language_from_locales(QLocale.system().uiLanguages())


def current_language() -> str:
    """目前介面使用的語言："zh_TW" 或 "en"。

    install() 之後回傳安裝時套用的語言（改設定要重新啟動才生效）；還沒 install 時依設定推算。
    """
    return _current if _current is not None else resolve_language()


def accept_language() -> str:
    """給引擎 API 的 Accept-Language 標頭值（"zh-TW" 或 "en"）。"""
    return "en" if current_language() == EN else "zh-TW"


def _bundle_dir() -> Path | None:
    """PyInstaller 打包版的資料夾（sys._MEIPASS），原始碼執行時是 None。"""
    meipass = getattr(sys, "_MEIPASS", None)
    return Path(meipass) if meipass else None


def app_translation_dirs() -> list[Path]:
    """找 App 翻譯檔（yt_dl_<lang>.qm）的資料夾，依序嘗試。"""
    dirs = []
    bundle = _bundle_dir()
    if bundle is not None:
        dirs.append(bundle / "i18n")
    dirs.append(Path(__file__).resolve().parent / "i18n")
    return dirs


def qt_translation_dirs() -> list[Path]:
    """找 Qt 內建翻譯檔（qtbase_<lang>.qm）的資料夾，依序嘗試。"""
    dirs = []
    bundle = _bundle_dir()
    if bundle is not None:
        dirs += [bundle / "PySide6" / "translations", bundle / "PySide6" / "Qt" / "translations"]
    qt_path = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    if qt_path:
        dirs.append(Path(qt_path))
    return dirs


def _load_first(name: str, dirs) -> QTranslator | None:
    """在 dirs 裡依序找 <name>.qm，第一個載入成功的就回傳。"""
    for d in dirs:
        path = Path(d) / f"{name}.qm"
        if not path.is_file():
            continue
        translator = QTranslator()
        if translator.load(os.fspath(path)):
            return translator
    return None


def uninstall() -> None:
    """移除 install() 裝的翻譯（測試用；App 執行中不切換語言）。"""
    global _current
    for translator in _translators:
        QCoreApplication.removeTranslator(translator)
    _translators.clear()
    _current = None


def install(app: QCoreApplication | None = None, setting: str | None = None) -> str:
    """依語言設定安裝翻譯，回傳實際套用的語言（"zh_TW" 或 "en"）。

    要在 QApplication 建立之後、建立任何視窗之前呼叫。找不到翻譯檔時不會出錯，介面就維持原文。
    setting 省略時讀使用者設定。
    """
    global _current
    if app is None:
        app = QCoreApplication.instance()
    if app is None:
        raise RuntimeError("i18n.install() needs a QApplication")
    uninstall()
    lang = resolve_language(setting)
    QLocale.setDefault(QLocale(_LOCALE_NAMES[lang]))
    candidates = []
    if lang != SOURCE_LANGUAGE:
        candidates.append((f"{QM_PREFIX}_{lang}", app_translation_dirs()))
    candidates.append((f"qtbase_{lang}", qt_translation_dirs()))
    for name, dirs in candidates:
        translator = _load_first(name, dirs)
        if translator is not None and app.installTranslator(translator):
            _translators.append(translator)
    _current = lang
    return lang


def installed_translations() -> list[str]:
    """目前裝上的翻譯檔路徑（除錯與測試用）。"""
    return [t.filePath() for t in _translators]


def guide_url(anchor: str = "", lang: str | None = None) -> str:
    """使用說明的網址；anchor 是章節錨點（例如 "err-private"，前面的 # 可省略）。

    中英文版的 FAQ 錨點完全相同，所以同一個 anchor 兩種語言都能用。lang 省略時用目前介面語言。
    """
    if lang is None:
        lang = current_language()
    url = REPO_BLOB_URL + GUIDE_FILES.get(lang, GUIDE_FILES[ZH_TW])
    anchor = (anchor or "").lstrip("#").strip()
    return f"{url}#{anchor}" if anchor else url
