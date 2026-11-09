"""「設定」頁：一般、外觀與語言、下載預設值、儲存位置、Cookie 與 YouTube Premium、下載元件、關於（含 App 新版提示）。

給主視窗（C1）用的介面：
- focus_section(section)：捲到某一區並把焦點放在第一個控制項；section 見 SettingsPage.SECTIONS。
- close_action() -> "quit" | "tray"：「關閉視窗時」的設定（系統不支援系統匣時一律 "quit"）。
- update_available = Signal(dict)：查到 App 新版時發出 app_update.parse_release() 的資料；
  沒有新版或使用者按「略過此版本」時發出空的 dict（主視窗用 bool(info) 決定要不要顯示徽章）。
- ytdlp_update_available(meta) -> bool：yt-dlp 有沒有新版（原本叫 update_available 的 staticmethod）。
"""
from __future__ import annotations

import json
import os
import platform
import sys
import threading
from pathlib import Path
from urllib.parse import urlencode

from PySide6.QtCore import QCoreApplication, QObject, QPoint, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

import app_update
import i18n
from native_common import (
    AUDIO_CODECS,
    AUDIO_QUALITY,
    CONTAINERS,
    DISCLAIMER_SHORT,
    DISCLAIMER_URL,
    DOWNLOAD_DEFAULTS,
    FILE_MANAGER,
    FONT_SIZES,
    MODES,
    QUALITIES,
    THEMES,
    TITLE,
    Api,
    Card,
    ElidedLabel,
    PopUp,
    Segmented,
    app_version,
    auto_paste_enabled,
    fmt_bytes,
    form_row,
    label,
    load_download_defaults,
    newer,
    page_layout,
    save_download_defaults,
    save_ui_prefs,
    set_auto_paste,
    settings_store,
    ui_prefs,
)

_tr = QCoreApplication.translate  # 名稱固定是 _tr（docs/I18N.md）

REPO_URL = "https://github.com/Archer8685/yt-dl"
LICENSE_URL = f"{REPO_URL}/blob/main/LICENSE"
THIRD_PARTY_URL = f"{REPO_URL}/blob/main/THIRD_PARTY_NOTICES.md"
ISSUE_URL = f"{REPO_URL}/issues/new"
ISSUE_TEMPLATE = "bug_report.yml"
# 回報問題表單（.github/ISSUE_TEMPLATE/bug_report.yml）下拉選單的選項：要和表單一字不差才會預先選好
ISSUE_LANGUAGES = {"zh_TW": "中文（繁體）", "en": "English"}
ISSUE_OS_OTHER = "其他（請在下方說明）/ Other (describe below)"

CLOSE_ACTION_KEY = "ui/close_action"
CLOSE_QUIT, CLOSE_TRAY = "quit", "tray"
PARALLEL_RANGE = (1, 5)


def _items(items):
    """native_common 的選項清單（原文是中文常數）顯示時再翻譯；context 和 native_common 標記的一樣。"""
    return [(key, _tr("native_common", text)) for key, text in items]


def tray_available() -> bool:
    return QSystemTrayIcon.isSystemTrayAvailable()


def auto_update_check_enabled() -> bool:
    """自動檢查 App 新版：自動化測試（offscreen）和環境變數 YTDL_APP_UPDATE_CHECK=0 時不連網路。"""
    return QGuiApplication.platformName() != "offscreen" and os.environ.get("YTDL_APP_UPDATE_CHECK", "1") != "0"


def issue_os() -> str:
    """回報問題表單「系統與晶片」的選項。"""
    if sys.platform == "win32":
        try:
            build = sys.getwindowsversion().build
        except AttributeError:
            return ISSUE_OS_OTHER
        return "Windows 11" if build >= 22000 else "Windows 10" if build >= 10240 else ISSUE_OS_OTHER
    if sys.platform == "darwin":
        try:
            major = int((platform.mac_ver()[0] or "0").split(".")[0])
        except ValueError:
            major = 0
        if platform.machine() == "arm64" and major in (14, 15):
            return f"macOS {major}（Apple 晶片 / Apple silicon）"
    return ISSUE_OS_OTHER


def issue_url(ytdlp_version: str = "", lang: str | None = None) -> str:
    """「回報問題」的網址：預先填好 App 版本、yt-dlp 版本、作業系統、介面語言。

    刻意不帶任何影片網址、檔案路徑或電腦使用者名稱（platform.platform() 只有系統名稱與版本號）。
    """
    lang = lang or i18n.current_language()
    extra = "\n".join([
        f"App: {app_version()}",
        f"yt-dlp: {ytdlp_version or '?'}",
        f"OS: {platform.platform()} ({platform.machine()})",
        f"UI: {lang}",
    ])
    query = {"template": ISSUE_TEMPLATE, "app_version": app_version(),
             "language": ISSUE_LANGUAGES.get(lang, ISSUE_LANGUAGES["zh_TW"]), "os": issue_os(), "extra": extra}
    return f"{ISSUE_URL}?{urlencode(query)}"


def log_dir() -> Path:
    """engine.log 所在的資料夾（打包版是使用者資料夾，原始碼執行時是專案資料夾）。"""
    server = sys.modules.get("server")
    root = getattr(server, "ROOT", None)
    return Path(root) if root else Path(__file__).resolve().parent


def engine_busy() -> bool:
    """引擎有沒有下載正在進行（引擎和 App 在同一個程序時才知道，否則當成沒有）。"""
    busy = getattr(sys.modules.get("server"), "_busy", None)
    try:
        return bool(busy()) if callable(busy) else False
    except Exception:  # noqa: BLE001
        return False


def restart_app() -> bool:
    """用更新 yt-dlp 後同一套重新啟動機制（server.RESTART_HANDLER，由 native_app 的 Restarter 處理）
    重新開啟 App。沒有這個機制時（例如測試、只有網頁版引擎）回傳 False，請使用者自己重開。"""
    server = sys.modules.get("server")
    handler = getattr(server, "RESTART_HANDLER", None)
    if handler is None:
        return False
    args = sys.argv[1:] if getattr(server, "FROZEN", False) else sys.argv
    env = {k: v for k, v in os.environ.items() if k != "YTDL_JUST_UPDATED"}  # 不是 yt-dlp 更新，不要顯示「已更新」
    handler([sys.executable, *args], env)
    return True


class _UpdateChecker(QObject):
    """在背景執行緒查 App 新版（app_update.check 會連網路），結果回到主執行緒。"""
    finished = Signal(object, bool)  # (info 或 None, 是否為使用者按的「檢查更新」)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.running = False

    def start(self, force: bool, manual: bool) -> bool:
        if self.running:
            return False
        self.running = True

        def work():
            try:
                info = app_update.check(force=force)
            except Exception:  # noqa: BLE001 — check 本身不丟例外；保險起見不讓執行緒把錯誤印出來
                info = None
            try:
                self.finished.emit(info, manual)
            except RuntimeError:  # 設定頁已經關掉（例如 App 正在結束）
                pass

        threading.Thread(target=work, daemon=True).start()
        return True


# --------------------------------------------------------------------------- #
#  頁面：設定
# --------------------------------------------------------------------------- #
class SettingsPage(QWidget):
    meta_changed = Signal(dict)
    appearance_changed = Signal()  # 外觀或文字大小改了：主程式重新套用樣式
    defaults_changed = Signal(dict)  # 下載預設值改了：「新增下載」頁立刻套用
    update_available = Signal(dict)  # App 新版（見模組說明）；空 dict 表示沒有要提示的新版

    # focus_section() 認得的區塊
    SECTIONS = ("general", "close", "parallel", "appearance", "language", "defaults", "storage", "cookies",
                "components", "about", "update")

    def __init__(self, api: Api, toast, advanced=None):
        super().__init__()
        self.api, self.toast = api, toast
        self.advanced = advanced  # 進階選項面板：Cookie 來源與「Premium 高位元率」開關在那裡
        self._meta: dict = {}
        self._settings: dict = {}
        self._parallel: int | None = None
        self._app_update: dict = {}
        self._manual_pending = False
        self._anchors: dict[str, tuple[QWidget, QWidget | None]] = {}
        lay = page_layout(self)
        self._scroll = self.findChild(QScrollArea)
        from native_options import Switch

        # ---------- 一般 ----------
        general_head = label(self.tr("一般"), "sectionHeader")
        lay.addWidget(general_head)
        general = Card()
        self.auto_paste = Switch(auto_paste_enabled())
        self.auto_paste.toggled.connect(set_auto_paste)
        general.add(form_row(self.tr("自動貼上剪貼簿裡的影片連結"), self.auto_paste))
        self.close_choice = PopUp([(CLOSE_QUIT, self.tr("結束 App")),
                                   (CLOSE_TRAY, self.tr("縮到系統匣，背景繼續下載"))])
        self.close_choice.select(self._saved_close_action())
        self.close_choice.currentIndexChanged.connect(self._close_action_changed)
        self.r_close = general.add(form_row(self.tr("關閉視窗時"), self.close_choice))
        if not tray_available():  # 只是顯示成「結束 App」，不改掉存著的設定
            self.close_choice.blockSignals(True)
            self.close_choice.select(CLOSE_QUIT)
            self.close_choice.blockSignals(False)
            self.close_choice.setEnabled(False)
            self.close_choice.setToolTip(self.tr("這台電腦的系統不支援系統匣圖示"))
        self.parallel = PopUp([(n, str(n)) for n in range(PARALLEL_RANGE[0], PARALLEL_RANGE[1] + 1)])
        self.parallel.currentIndexChanged.connect(self._parallel_changed)
        self.r_parallel = general.add(form_row(self.tr("同時下載數"), self.parallel))
        general.set_row_visible(self.r_parallel, False)  # 引擎回報支援（/api/settings 有 parallel）才顯示
        self.general = general
        lay.addWidget(general)
        lay.addWidget(label(self.tr("開啟 App 或切回視窗時，剪貼簿裡如果是 YouTube 等支援網站的影片連結，"
                                    "會自動貼到「新增下載」並開始解析；一般網頁連結不會。"), "hint", wrap=True))
        lay.addWidget(label(self.tr("選「縮到系統匣」時，關閉視窗後 App 會留在系統匣繼續下載；要完全結束請在"
                                    "系統匣圖示的選單按「結束」。同時下載數改了立刻生效，網路較慢時建議設 1 或 2。"),
                            "hint", wrap=True))
        self._anchors["general"] = (general_head, self.auto_paste)
        self._anchors["close"] = (general_head, self.close_choice)
        self._anchors["parallel"] = (general_head, self.parallel)

        # ---------- 外觀與語言 ----------
        lay.addSpacing(8)
        look_head = label(self.tr("外觀"), "sectionHeader")
        lay.addWidget(look_head)
        look = Card()
        theme, size = ui_prefs()
        self.theme = Segmented(_items(THEMES))
        self.theme.set_value(theme)
        self.font_size = Segmented(_items(FONT_SIZES))
        self.font_size.set_value(size)
        self.theme.changed.connect(self._appearance_changed)
        self.font_size.changed.connect(self._appearance_changed)
        look.add(form_row(self.tr("主題"), self.theme))
        look.add(form_row(self.tr("文字大小"), self.font_size))
        # 語言名稱用該語言自己的寫法（不翻譯），使用者在看不懂的介面裡也找得到自己的語言
        self.language = PopUp([(i18n.SYSTEM, self.tr("跟隨系統")),
                               (i18n.ZH_TW, self.tr("中文（繁體）", "語言名稱：請保留中文原文，不要翻譯")),
                               (i18n.EN, "English")])
        self.language.select(i18n.get_setting())
        self.language.currentIndexChanged.connect(self._language_changed)
        self.r_language = look.add(form_row(self.tr("語言"), self.language))
        lay.addWidget(look)
        lay.addWidget(label(self.tr("切換語言後要重新啟動 App 才會套用。"), "hint", wrap=True))
        self._anchors["appearance"] = (look_head, self.theme.buttons[self.theme.value()])
        self._anchors["language"] = (look_head, self.language)

        # ---------- 下載預設值：每次開啟 App，「新增下載」都從這些選項開始 ----------
        lay.addSpacing(8)
        head = QHBoxLayout()
        defaults_head = label(self.tr("下載預設值"), "sectionHeader")
        head.addWidget(defaults_head)
        head.addStretch()
        self.reset_all_btn = QPushButton(self.tr("重設所有偏好…"))
        self.reset_all_btn.setObjectName("link")
        self.reset_all_btn.clicked.connect(self.reset_all)
        head.addWidget(self.reset_all_btn)
        lay.addLayout(head)
        defaults = Card()
        self.def_mode = PopUp(_items(MODES))
        self.def_quality = PopUp([(None, self.tr("最佳畫質"))] + _items(QUALITIES))
        self.def_container = PopUp(_items(CONTAINERS))
        self.def_acodec = PopUp(_items(AUDIO_CODECS))
        self.def_aquality = PopUp(_items(AUDIO_QUALITY))
        self.def_playlist = Switch(False)
        for w in (self.def_mode, self.def_quality, self.def_container, self.def_acodec, self.def_aquality):
            w.setMinimumWidth(170)  # 同一張卡片裡的選單一樣寬，比較整齊
        defaults.add(form_row(self.tr("下載模式"), self.def_mode))
        defaults.add(form_row(self.tr("畫質"), self.def_quality))
        defaults.add(form_row(self.tr("影片格式"), self.def_container))
        defaults.add(form_row(self.tr("音訊格式（僅音訊時）"), self.def_acodec))
        defaults.add(form_row(self.tr("音質（MP3 / M4A 等）"), self.def_aquality))
        defaults.add(form_row(self.tr("網址含播放清單時下載整個清單"), self.def_playlist))
        lay.addWidget(defaults)
        lay.addWidget(label(self.tr("影片解析度比預設畫質低時會自動用最佳畫質。字幕、剪輯、中繼資料等進階選項"
                                    "在「新增下載 → 進階選項」調整，會記住上次的設定。"), "hint", wrap=True))
        self.show_defaults(load_download_defaults())
        for w in (self.def_mode, self.def_quality, self.def_container, self.def_acodec, self.def_aquality):
            w.currentIndexChanged.connect(self._defaults_changed)
        self.def_playlist.toggled.connect(self._defaults_changed)
        self._anchors["defaults"] = (defaults_head, self.def_mode)

        # ---------- 儲存位置 ----------
        lay.addSpacing(8)
        storage_head = label(self.tr("儲存位置"), "sectionHeader")
        lay.addWidget(storage_head)
        card = Card()
        self.folder = ElidedLabel("subtitle")
        self.disk = label("", "subtitle")
        self.dir_error = label("", "errorText", wrap=True, plain=True)
        self.dir_error.hide()
        self.change_btn = QPushButton(self.tr("變更…"))
        self.change_btn.clicked.connect(self.choose)
        self.reset = QPushButton(self.tr("改回預設資料夾"))
        self.reset.clicked.connect(lambda: self.save(""))
        self.open_btn = QPushButton(self.tr("在{app}中打開").format(app=_tr("native_common", FILE_MANAGER)))
        self.open_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(self.folder.full_text())))
        row = QWidget()
        rl = QVBoxLayout(row)
        rl.setContentsMargins(14, 10, 14, 10)
        rl.setSpacing(4)
        rl.addWidget(label(self.tr("下載資料夾")))
        rl.addWidget(self.folder)
        rl.addWidget(self.disk)
        rl.addWidget(self.dir_error)
        btns = QHBoxLayout()  # 按鈕放在路徑下方：視窗再窄也按得到
        btns.setContentsMargins(0, 6, 0, 0)
        btns.addWidget(self.change_btn)
        btns.addWidget(self.open_btn)
        btns.addWidget(self.reset)
        btns.addStretch()
        rl.addLayout(btns)
        self.env_note = label(self.tr("儲存位置由環境變數 YTDL_DOWNLOAD_DIR 指定，無法在這裡變更；"
                                      "要改請先移除這個環境變數再重新開啟 App。"), "hint", wrap=True)
        self.env_note.hide()
        rl.addWidget(self.env_note)
        card.add(row)
        lay.addWidget(card)
        self._anchors["storage"] = (storage_head, self.change_btn)

        # ---------- Cookie 與 YouTube Premium：檢查登入的帳號，Cookie 過期時可以直接上傳新的 ----------
        lay.addSpacing(8)
        cookies_head = label(self.tr("Cookie 與 YouTube Premium"), "sectionHeader")
        lay.addWidget(cookies_head)
        prem = Card()
        prow = QWidget()
        pl = QVBoxLayout(prow)
        pl.setContentsMargins(14, 10, 14, 10)
        pl.setSpacing(4)
        top = QHBoxLayout()
        top.addWidget(label(self.tr("帳號狀態")))
        top.addStretch()
        self.premium_status = label("", None, plain=True)
        top.addWidget(self.premium_status)
        pl.addLayout(top)
        self.premium_detail = label("", "hint", wrap=True, plain=True)
        pl.addWidget(self.premium_detail)
        pbtns = QHBoxLayout()
        pbtns.setContentsMargins(0, 6, 0, 0)
        self.premium_check = QPushButton(self.tr("重新檢查"))
        self.premium_check.clicked.connect(self.check_premium)
        self.premium_upload = QPushButton(self.tr("更新 cookies.txt…"))
        self.premium_upload.clicked.connect(self.update_cookies)
        self.cookie_delete = QPushButton(self.tr("刪除 cookies.txt…"))
        self.cookie_delete.clicked.connect(self.delete_cookies)
        pbtns.addWidget(self.premium_check)
        pbtns.addWidget(self.premium_upload)
        pbtns.addWidget(self.cookie_delete)
        pbtns.addStretch()
        pl.addLayout(pbtns)
        self.cookie_help = QPushButton(self.tr("如何匯出 cookies.txt"))
        self.cookie_help.setObjectName("link")
        self.cookie_help.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(i18n.guide_url("cookies"))))
        hrow = QHBoxLayout()
        hrow.setContentsMargins(0, 2, 0, 0)
        hrow.addWidget(self.cookie_help)
        hrow.addStretch()
        pl.addLayout(hrow)
        prem.add(prow)
        lay.addWidget(prem)
        lay.addWidget(label(self.tr("用瀏覽器匯出的 cookies.txt（或「新增下載 → 進階選項 → 網路」選的 Cookie 來源）"
                                    "檢查登入的帳號是否有 Premium。Cookie 過期時重新匯出、按「更新 cookies.txt…」即可。"
                                    "cookies.txt 等於你的帳號登入資料，不再需要時可以按「刪除 cookies.txt…」。"),
                            "hint", wrap=True))
        self.show_premium(self.saved_premium())
        self._anchors["cookies"] = (cookies_head, self.premium_upload)

        # ---------- 下載元件 ----------
        lay.addSpacing(8)
        comp_head = label(self.tr("下載元件"), "sectionHeader")
        lay.addWidget(comp_head)
        card2 = Card()
        self.version = label("", "subtitle")
        self.update_btn = QPushButton(self.tr("檢查更新"))
        self.update_btn.clicked.connect(self.update_ytdlp)
        card2.add(form_row("yt-dlp", self._pair(self.version, self.update_btn)))
        self.ffmpeg = label("", "subtitle")
        card2.add(form_row("FFmpeg", self.ffmpeg))
        lay.addWidget(card2)
        lay.addWidget(label(self.tr("yt-dlp 會在背景自動更新，YouTube 改版時通常不需要手動處理。"), "hint", wrap=True))
        self._anchors["components"] = (comp_head, self.update_btn)

        # ---------- 關於：版本、App 新版、說明與回報、授權、免責聲明 ----------
        lay.addSpacing(8)
        about_head = label(self.tr("關於"), "sectionHeader")
        lay.addWidget(about_head)
        about = Card()
        self.app_version = label(app_version(), "subtitle", plain=True)
        self.app_update_check = QPushButton(self.tr("檢查 App 更新"))
        self.app_update_check.clicked.connect(lambda: self.check_app_update(manual=True))
        about.add(form_row(_tr("native_common", TITLE), self._pair(self.app_version, self.app_update_check)))

        self.app_update_row = QWidget()
        ul = QVBoxLayout(self.app_update_row)
        ul.setContentsMargins(14, 10, 14, 10)
        ul.setSpacing(4)
        self.app_update_text = label("", "okText", wrap=True, plain=True)
        ul.addWidget(self.app_update_text)
        ul.addWidget(label(self.tr("下載後執行新的安裝檔即可更新，設定和下載的檔案都會保留。"), "hint", wrap=True))
        ubtns = QHBoxLayout()
        ubtns.setContentsMargins(0, 6, 0, 0)
        self.app_update_download = QPushButton(self.tr("下載"))
        self.app_update_download.setDefault(True)
        self.app_update_download.clicked.connect(lambda: self._open(self._app_update.get("download_url")))
        self.app_update_notes = QPushButton(self.tr("查看更新內容"))
        self.app_update_notes.clicked.connect(lambda: self._open(self._app_update.get("url")))
        self.app_update_skip = QPushButton(self.tr("略過此版本"))
        self.app_update_skip.setObjectName("link")
        self.app_update_skip.clicked.connect(self.skip_app_update)
        ubtns.addWidget(self.app_update_download)
        ubtns.addWidget(self.app_update_notes)
        ubtns.addWidget(self.app_update_skip)
        ubtns.addStretch()
        ul.addLayout(ubtns)
        about.add(self.app_update_row)
        about.set_row_visible(self.app_update_row, False)

        help_row = QWidget()
        hl = QHBoxLayout(help_row)
        hl.setContentsMargins(14, 8, 14, 8)
        self.guide_btn = QPushButton(self.tr("使用說明"))
        self.guide_btn.clicked.connect(lambda: self._open(i18n.guide_url()))
        self.logs_btn = QPushButton(self.tr("開啟紀錄資料夾"))
        self.logs_btn.clicked.connect(self.open_logs)
        self.report_btn = QPushButton(self.tr("回報問題"))
        self.report_btn.clicked.connect(self.report_issue)
        for b in (self.guide_btn, self.logs_btn, self.report_btn):
            hl.addWidget(b)
        hl.addStretch()
        about.add(help_row)

        legal = QWidget()
        ll = QVBoxLayout(legal)
        ll.setContentsMargins(14, 10, 14, 10)
        ll.setSpacing(4)
        self.license_text = label(self.tr("以 MIT 授權開放原始碼。也使用了 yt-dlp、FFmpeg、Qt（PySide6）等第三方軟體，"
                                          "各自依其授權條款提供。"), "hint", wrap=True)
        ll.addWidget(self.license_text)
        # 兩句之間保留換行：拿掉換行直接接起來，英文會變成「…Google.Only download…」（少了空白）
        self.disclaimer_text = label(_tr("native_common", DISCLAIMER_SHORT), "hint", wrap=True, plain=True)
        ll.addWidget(self.disclaimer_text)
        lrow = QHBoxLayout()
        lrow.setContentsMargins(0, 4, 0, 0)
        self.license_link = QPushButton(self.tr("授權條款（MIT）"))
        self.license_link.clicked.connect(lambda: self._open(LICENSE_URL))
        self.third_party_link = QPushButton(self.tr("第三方授權"))
        self.third_party_link.clicked.connect(lambda: self._open(THIRD_PARTY_URL))
        self.disclaimer_link = QPushButton(self.tr("查看完整免責聲明"))
        self.disclaimer_link.clicked.connect(lambda: self._open(DISCLAIMER_URL))
        for b in (self.license_link, self.third_party_link, self.disclaimer_link):
            b.setObjectName("link")
            lrow.addWidget(b)
        lrow.addStretch()
        ll.addLayout(lrow)
        about.add(legal)
        self.about = about
        lay.addWidget(about)
        lay.addStretch()
        self._anchors["about"] = (about_head, self.guide_btn)
        self._anchors["update"] = (about_head, self.app_update_check)

        self._checker = _UpdateChecker(self)
        self._checker.finished.connect(self._on_app_update)
        # 上次查到、還沒略過的新版：開啟 App 就看得到。訊號等下一輪事件再發，主視窗才來得及連接
        self._show_app_update(app_update.cached(), emit=False)
        if self._app_update:
            QTimer.singleShot(0, self, lambda: self.update_available.emit(dict(self._app_update)))

    def app_update_info(self) -> dict:
        """目前要提示的 App 新版（沒有時是空 dict），內容同 update_available 訊號。"""
        return dict(self._app_update)

    @staticmethod
    def _pair(a: QWidget, b: QWidget) -> QWidget:
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        lay.addWidget(a)
        lay.addWidget(b)
        return w

    @staticmethod
    def _open(url: str | None):
        if url:
            QDesktopServices.openUrl(QUrl(url))

    def _ask(self, text: str, info: str, ok_text: str, cancel_text: str | None = None,
             icon=QMessageBox.Question) -> bool:
        """詢問對話框；按了 ok_text 那個按鈕回傳 True。測試會換掉這個方法。"""
        box = QMessageBox(self.window())
        box.setIcon(icon)
        box.setWindowTitle(_tr("native_common", TITLE))
        box.setText(text)
        box.setInformativeText(info)
        ok = box.addButton(ok_text, QMessageBox.AcceptRole)
        box.setDefaultButton(box.addButton(cancel_text or self.tr("取消"), QMessageBox.RejectRole))
        box.exec()
        return box.clickedButton() is ok

    # ---------- 給主視窗的介面 ----------
    def focus_section(self, section: str) -> bool:
        """捲到 section 那一區並把焦點放到該區的主要控制項；不認得的 section 回傳 False。"""
        if section == "update" and not self._app_update:
            section = "about"
        target = self._anchors.get(section)
        if target is None:
            return False
        head, focus = target

        def go():
            sc = self._scroll
            if sc is not None and sc.widget() is not None:
                y = head.mapTo(sc.widget(), QPoint(0, 0)).y()
                sc.verticalScrollBar().setValue(max(0, y - 12))
            if focus is not None and focus.isEnabled() and focus.isVisibleTo(self):
                focus.setFocus(Qt.OtherFocusReason)

        go()
        QTimer.singleShot(0, go)  # 剛切到設定頁時版面可能還沒算好：下一輪事件再捲一次
        return True

    def _saved_close_action(self) -> str:
        value = str(settings_store().value(CLOSE_ACTION_KEY, CLOSE_QUIT) or CLOSE_QUIT)
        return value if value in (CLOSE_QUIT, CLOSE_TRAY) else CLOSE_QUIT

    def close_action(self) -> str:
        """關閉視窗時要 "quit"（結束 App，預設）還是 "tray"（縮到系統匣）。"""
        if not tray_available():
            return CLOSE_QUIT
        return self._saved_close_action()

    def _close_action_changed(self, *_):
        value = self.close_choice.currentData()
        settings_store().setValue(CLOSE_ACTION_KEY, value)

    # ---------- 同時下載數 ----------
    def _show_parallel(self, n):
        try:
            n = int(n)
        except (TypeError, ValueError):
            self.general.set_row_visible(self.r_parallel, False)
            return
        self._parallel = n
        self.parallel.blockSignals(True)
        self.parallel.select(n)
        self.parallel.blockSignals(False)
        self.general.set_row_visible(self.r_parallel, True)

    def _parallel_changed(self, *_):
        n = self.parallel.currentData()
        if n is None or n == self._parallel:
            return
        before = self._parallel

        def ok(s):
            self.on_settings(s)
            self.toast(_tr("SettingsPage", "同時下載數已改成 %n 個，立即生效", None, n))

        def err(msg):
            self._show_parallel(before)
            self.toast(self.tr("無法變更同時下載數：{error}").format(error=msg), error=True)

        self._parallel = n
        self.api.post("/api/settings", {"parallel": n}, ok, err)

    # ---------- 外觀與語言 ----------
    def _appearance_changed(self, *_):
        save_ui_prefs(self.theme.value(), self.font_size.value())
        self.appearance_changed.emit()

    def _language_changed(self, *_):
        setting = self.language.currentData()
        if setting is None or setting == i18n.get_setting():
            return
        i18n.set_language(setting)
        target = i18n.resolve_language(setting)
        if target == i18n.current_language():  # 例如改成「跟隨系統」而系統就是目前的語言：不用重新啟動
            self.toast(self.tr("已儲存語言設定"))
            return
        info = self.tr("介面語言會在重新啟動 App 後換成「{language}」。").format(
            language=self.language.itemText(self.language.findData(target)))
        if engine_busy():
            info += "\n\n" + self.tr("還有下載正在進行。重新啟動時下載會暫停，重新開啟後按「繼續」就能接著下載。")
        if not self._ask(self.tr("要立即重新啟動 App 嗎？"), info, self.tr("立即重新啟動"), self.tr("稍後")):
            self.toast(self.tr("下次開啟 App 時會套用新的語言"))
            return
        if not restart_app():
            self.toast(self.tr("請關閉 App 再重新開啟，就會套用新的語言"))

    # ---------- 下載預設值 ----------
    def show_defaults(self, d: dict):
        widgets = (self.def_mode, self.def_quality, self.def_container, self.def_acodec, self.def_aquality,
                   self.def_playlist)
        for w in widgets:
            w.blockSignals(True)
        self.def_mode.select(d["mode"])
        if not self.def_quality.select(d["quality"]):
            self.def_quality.setCurrentIndex(0)
        self.def_container.select(d["container"])
        self.def_acodec.select(d["acodec"])
        self.def_aquality.select(d["aquality"])
        self.def_playlist.setChecked(d["as_playlist"])
        for w in widgets:
            w.blockSignals(False)

    def current_defaults(self) -> dict:
        return {"mode": self.def_mode.currentData(), "quality": self.def_quality.currentData(),
                "container": self.def_container.currentData(), "acodec": self.def_acodec.currentData(),
                "aquality": self.def_aquality.currentData(), "as_playlist": self.def_playlist.isChecked()}

    def _defaults_changed(self, *_):
        d = self.current_defaults()
        save_download_defaults(d)
        self.defaults_changed.emit(d)

    def reset_all(self):
        """偏好設定全部改回剛安裝時的樣子（不動語言、同時下載數、儲存位置、cookies.txt 與下載的檔案）。"""
        if not self._ask(self.tr("要重設所有偏好嗎？"),
                         self.tr("自動貼上、關閉視窗時的動作、外觀、文字大小、下載預設值和進階選項會改回剛安裝時的設定。"
                                 "介面語言、同時下載數、儲存位置、cookies.txt 和已下載的檔案不受影響。"),
                         self.tr("恢復預設值")):
            return
        self.auto_paste.setChecked(True)  # toggled 會存進設定
        set_auto_paste(True)
        self.close_choice.select(CLOSE_QUIT)
        self._close_action_changed()
        self.theme.set_value("system")
        self.font_size.set_value("medium")
        self._appearance_changed()
        self.show_defaults(dict(DOWNLOAD_DEFAULTS))
        self._defaults_changed()
        if self.advanced is not None:
            self.advanced.reset()
        self.toast(self.tr("已重設所有偏好"))

    # ---------- Cookie 與 YouTube Premium ----------
    @staticmethod
    def saved_premium() -> dict:
        try:
            data = json.loads(settings_store().value("premium/status", "") or "{}")
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}

    def _cookie_file_exists(self) -> bool:
        """已上傳 cookies.txt：以引擎的 /api/meta 為準，還沒拿到時看進階選項面板。"""
        if "cookies_file" in self._meta:
            return bool(self._meta["cookies_file"])
        return bool(self.advanced is not None and self.advanced.cookie_exists)

    def _cookies_configured(self) -> bool:
        """有可以用的 Cookie：上傳過 cookies.txt，或在進階選項選了「從瀏覽器讀取」。"""
        if self._cookie_file_exists():
            return True
        return bool(self.advanced is not None and self.advanced.network().get("cookies_browser"))

    def show_premium(self, s: dict):
        """顯示 Cookie 與 Premium 狀態（上次檢查的結果，App 重新開啟也看得到）。"""
        style = "warnText"
        if not self._cookies_configured():
            text, style = self.tr("未設定"), "subtitle"
            detail = self.tr("還沒有設定 Cookie。只有下載會員限定、年齡限制或 Premium 高畫質影片時才需要："
                             "從瀏覽器匯出 cookies.txt 後按「更新 cookies.txt…」。")
            s = {}
        elif s.get("error"):
            text, detail, style = self.tr("無法檢查"), s["error"], "errorText"
        elif not s:
            text, style = self.tr("尚未檢查"), "subtitle"
            detail = self.tr("按「重新檢查」確認目前的 Cookie 是否登入、是否有 Premium。")
        elif s.get("expired"):
            text = self.tr("Cookie 已過期")
            detail = self.tr("請在瀏覽器重新登入 YouTube、重新匯出 cookies.txt 後按「更新 cookies.txt…」。")
        elif not s.get("logged_in"):
            text = self.tr("未登入")
            detail = self.tr("這組 Cookie 沒有登入 YouTube，請在登入狀態下重新匯出 cookies.txt。")
        elif s.get("premium"):
            text, style = self.tr("Premium ✓"), "okText"
            detail = self.tr("已偵測到 YouTube Premium，可以下載 Premium 專屬的高位元率畫質。")
        else:
            text, style = self.tr("已登入（非 Premium）"), "subtitle"
            detail = self.tr("已登入 YouTube，但這個帳號沒有 Premium。")
        if s.get("checked"):
            detail = self.tr("{detail}　上次檢查：{time}").format(detail=detail, time=s["checked"])
        self.premium_status.setObjectName(style)
        self.premium_status.style().unpolish(self.premium_status)
        self.premium_status.style().polish(self.premium_status)
        self.premium_status.setText(text)
        self.premium_detail.setText(detail)
        self.premium_check.setVisible(self._cookies_configured())
        self.cookie_delete.setVisible(self._cookie_file_exists())

    def _save_premium(self, s: dict):
        from datetime import datetime
        s = {**s, "checked": datetime.now().strftime("%Y/%m/%d %H:%M")}
        settings_store().setValue("premium/status", json.dumps(s, ensure_ascii=False))
        self.show_premium(s)

    def check_premium(self):
        adv = self.advanced
        if adv is None:
            return
        net = adv.network()
        if not (net.get("cookies_file") or net.get("cookies_browser")):
            if not adv.cookie_exists:
                self.show_premium({})  # 還沒有 Cookie：顯示「未設定」與匯出說明，不是錯誤
                return
            # 已經上傳過 cookies.txt 但沒選來源（例如從舊版升級）：檢查時直接用它
            adv.cookie_source.setCurrentIndex(adv.cookie_source.findData("file"))
            net = adv.network()
        self.premium_check.setEnabled(False)
        self.premium_check.setText(self.tr("檢查中…"))

        def done():
            self.premium_check.setEnabled(True)
            self.premium_check.setText(self.tr("重新檢查"))

        def ok(r):
            done()
            self._save_premium({"logged_in": bool(r.get("logged_in")), "premium": bool(r.get("premium")),
                                "expired": bool(r.get("expired"))})
            if r.get("premium") and not adv.premium.isChecked():
                adv.premium.setChecked(True)  # 和網頁版一樣：偵測到 Premium 就優先選高位元率
                self.toast(self.tr("已偵測到 YouTube Premium，已開啟「Premium 高位元率」"))

        def err(msg):
            done()
            self._save_premium({"error": msg})

        # 檢查要實際向 YouTube 讀一部影片，通常幾秒、慢的時候一兩分鐘
        self.api.post("/api/auth/test", {"network": net}, ok, err, timeout_ms=180_000)

    def update_cookies(self):
        if self.advanced is None:
            return
        path, _ = QFileDialog.getOpenFileName(self, self.tr("選擇 cookies.txt"), "",
                                              self.tr("Cookie 檔 (*.txt);;所有檔案 (*)"))
        if path:
            self.advanced.upload_cookies(Path(path), done=self._cookies_uploaded)

    def _cookies_uploaded(self):
        self._meta["cookies_file"] = True
        self.check_premium()

    def delete_cookies(self):
        """刪除已上傳的 cookies.txt（引擎的 DELETE /api/cookies）；從瀏覽器讀取的 Cookie 不受影響。"""
        if not self._ask(self.tr("要刪除 cookies.txt 嗎？"),
                         self.tr("刪除後，需要登入才能看的影片（會員限定、年齡限制、Premium 高畫質）就無法下載，"
                                 "之後可以再上傳新的 cookies.txt。從瀏覽器讀取 Cookie 的設定不受影響。"),
                         self.tr("刪除"), icon=QMessageBox.Warning):
            return

        def ok(r):
            if self.advanced is not None:
                self.advanced._on_cookie_status(r)  # 進階選項的狀態與「Cookie 來源」一起更新
            self._meta["cookies_file"] = bool((r or {}).get("exists"))
            settings_store().remove("premium/status")
            self.show_premium({})
            self.toast(self.tr("已刪除 cookies.txt"))

        self.api.delete("/api/cookies", ok,
                        lambda m: self.toast(self.tr("無法刪除 cookies.txt：{error}").format(error=m), error=True))

    # ---------- 儲存位置與引擎資訊 ----------
    def refresh(self):
        self.api.get("/api/settings", self.on_settings,
                     lambda m: self.toast(self.tr("無法讀取設定：{error}").format(error=m), error=True))
        self.api.get("/api/meta", self.on_meta, timeout_ms=30_000)  # 第一次會查 PyPI，可能要十幾秒

    def on_settings(self, s: dict):
        self._settings = s
        path = s.get("download_dir") or ""
        self.folder.set_full_text(path)
        disk = s.get("disk") or {}
        self.disk.setText(self.tr("剩餘 {size}").format(size=fmt_bytes(disk.get("free")))
                          if disk.get("free") is not None else "")
        locked = bool(s.get("env_locked"))
        self.change_btn.setEnabled(not locked)
        self.change_btn.setToolTip(self.tr("儲存位置由環境變數指定，無法在這裡變更") if locked else "")
        self.env_note.setVisible(locked)
        self.reset.setVisible(path != s.get("default_dir") and not locked)
        if s.get("download_dir_error"):
            self.dir_error.setText(self.tr("儲存位置 {path} 目前無法存取。請接上磁碟或網路磁碟機，"
                                           "或按「變更…」選別的資料夾。").format(path=path))
            self.dir_error.show()
            self.disk.setText("")
        else:
            self.dir_error.hide()
        self.disk.setVisible(bool(self.disk.text()))  # 沒有剩餘空間可顯示時不要留一行空白
        if "parallel" in s:
            self._show_parallel(s.get("parallel"))

    @staticmethod
    def ytdlp_update_available(m: dict) -> bool:
        """yt-dlp 有新版（已下載好待套用，或 PyPI 上有較新的版本）。"""
        return bool(m.get("update_ready")) or newer(m.get("latest"), m.get("version"))

    def on_meta(self, m: dict):
        self._meta = dict(m)
        ver = m.get("version") or ""
        latest = m.get("latest")
        if m.get("update_ready"):
            self.version.setText(self.tr("{version}（新版已下載）").format(version=ver))
            self.update_btn.setText(self.tr("重新啟動以套用"))
        elif newer(latest, ver):
            self.version.setText(self.tr("{version}（最新 {latest}）").format(version=ver, latest=latest))
            self.update_btn.setText(self.tr("更新至 {latest}").format(latest=latest))
        else:
            self.version.setText(self.tr("{version}（已是最新）").format(version=ver))
            self.update_btn.setText(self.tr("檢查更新"))
        self.ffmpeg.setText(self.tr("已安裝") if m.get("ffmpeg") else self.tr("找不到，無法合併影音"))
        self.show_premium(self.saved_premium())
        if auto_update_check_enabled() and app_update.due():
            self.check_app_update()  # 每天最多連線一次；快取的結果建立頁面時已經顯示
        self.meta_changed.emit(m)

    def choose(self):
        path = QFileDialog.getExistingDirectory(self, self.tr("選擇下載資料夾"), self.folder.full_text())
        if path:
            self.save(path)

    def save(self, path: str):
        self.api.post("/api/settings", {"download_dir": path},
                      lambda s: (self.on_settings(s), self.toast(self.tr("已變更儲存位置"))),
                      lambda e: self.toast(e, error=True))

    # ---------- yt-dlp 更新 ----------
    def update_ytdlp(self):
        """更新 yt-dlp。更新完成後引擎會自動重新啟動 App，所以先說明並詢問。"""
        ready = bool(self._meta.get("update_ready"))
        info = self.tr("App 會關閉再自動重新開啟，大約需要幾秒。有下載正在進行時無法更新，請等下載完成或先暫停；"
                       "暫停的工作在重新開啟後按「繼續」就能接著下載。")
        if ready:
            asked = self._ask(self.tr("要重新啟動 App 套用新版 yt-dlp 嗎？"), info, self.tr("重新啟動"))
        else:
            asked = self._ask(self.tr("要檢查並更新 yt-dlp 嗎？"),
                              self.tr("有新版時會下載並安裝。") + "\n\n" + info, self.tr("更新"))
        if not asked:
            return
        self.update_btn.setEnabled(False)
        self.update_btn.setText(self.tr("處理中…"))

        def fail(e):
            self.update_btn.setEnabled(True)
            self.toast(e, error=True)
            self.refresh()

        def poll(retries: int = 5):
            # /api/update 只是開始在背景更新；結果（已是最新、失敗）看 /api/meta 的 update_message。
            # 更新成功時引擎會要求重新啟動，App 會自己關閉再開啟。
            def got(m):
                if m.get("update_running"):
                    QTimer.singleShot(1500, poll)
                    return
                self.update_btn.setEnabled(True)
                msg = m.get("update_message") or ""
                self.toast(msg or self.tr("已是最新版本"), error=msg.startswith("更新失敗"))
                self.on_meta(m)

            def again(e):  # 查詢狀態偶爾逾時（引擎正在下載新版）：稍後再查，不要當成更新失敗
                if retries > 0:
                    QTimer.singleShot(2000, lambda: poll(retries - 1))
                else:
                    fail(e)
            self.api.get("/api/meta", got, again, timeout_ms=30_000)

        def started(_):
            self.toast(self.tr("正在更新 yt-dlp，完成後會自動重新啟動…"))
            QTimer.singleShot(1000, poll)

        self.api.post("/api/update", {}, started, fail)

    # ---------- App 新版 ----------
    def check_app_update(self, manual: bool = False) -> bool:
        """在背景查 App 新版。manual=True（按「檢查 App 更新」）時一定連線並回報結果。"""
        started = self._checker.start(force=manual, manual=manual)
        if manual:
            # 自動檢查正在連線：等它的結果，當成這次按鈕的結果回報
            self._manual_pending = not started
            self.app_update_check.setEnabled(False)
            self.app_update_check.setText(self.tr("檢查中…"))
        return started

    def _on_app_update(self, info, manual: bool):
        self._checker.running = False
        manual = manual or self._manual_pending
        self._manual_pending = False
        if manual and info and app_update.is_newer(info.get("version"), app_version()) \
                and app_update.vtuple(info.get("version")) == app_update.vtuple(app_update.skipped_version()):
            app_update.skip_version("")  # 使用者主動檢查：之前略過的版本再提示一次
        self.app_update_check.setEnabled(True)
        self.app_update_check.setText(self.tr("檢查 App 更新"))
        shown = self._show_app_update(info)
        if manual and not shown:
            if info:
                self.toast(self.tr("目前已是最新版本"))
            else:
                self.toast(self.tr("目前無法檢查更新，請確認網路後再試一次"))

    def _show_app_update(self, info, emit: bool = True) -> bool:
        """有要提示的新版時顯示「關於」的新版列並發出 update_available；回傳是否顯示。"""
        show = app_update.available(info)
        self._app_update = dict(info) if show else {}
        if show:
            self.app_update_text.setText(self.tr("有新版 {version} 可以下載").format(version=info["version"]))
        self.about.set_row_visible(self.app_update_row, show)
        if emit:
            self.update_available.emit(dict(self._app_update))
        return show

    def skip_app_update(self):
        version = self._app_update.get("version")
        if not version:
            return
        app_update.skip_version(version)
        self._show_app_update(None)
        self.toast(self.tr("已略過 {version}，有更新的版本時會再提示").format(version=version))

    # ---------- 說明與回報 ----------
    def open_logs(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(log_dir())))

    def report_issue(self):
        self._open(issue_url(self._meta.get("version") or ""))
