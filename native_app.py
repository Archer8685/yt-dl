"""YT 下載器原生介面（Qt / PySide6），外觀參照 macOS。

介面直接用系統元件繪製（不是網頁），同一個程序在背景執行原本的下載引擎（server.py）。
介面透過引擎的本機 API 操作，所以下載、續傳、合併進度、yt-dlp 自動更新都和網頁版共用同一套引擎。

    python native_app.py [網址或 ytdl://add?url=… …]

同一個使用者只會有一個 App 在執行：再開一次（或從瀏覽器的書籤小工具開 ytdl:// 連結）時，
新的程序把參數交給已經在執行的 App 後就結束（single_instance.py），網址會送進「新增下載」。
"""
from __future__ import annotations

import os
import re
import socket
import sys
import time
from pathlib import Path

import shiboken6
from PySide6.QtCore import (
    QT_TRANSLATE_NOOP,
    QByteArray,
    QCoreApplication,
    QEvent,
    QObject,
    QSize,
    Qt,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import QColor, QDesktopServices, QGuiApplication, QIcon, QKeySequence, QPalette, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

import i18n
import native_common
import url_handoff

# 共用部分與三個頁面拆到 native_common / native_download / native_queue / native_settings。
# 這裡全部 re-export，原本 `import native_app` 的程式（打包、截圖工具、native_options、native_playlist、
# 測試）不用改
from native_common import *
from native_common import (
    BUNDLE,
    FONT_SCALE,
    IS_MAC,
    NOT_ENGINE,
    TITLE,
    Api,
    Banner,
    ClipboardWatcher,
    app_title,
    auto_paste_enabled,
    confirm_disclaimer,
    label,
    rounded,
    settings_store,
    stylesheet,
    symbol,
    tokens,
    ui_font,
    ui_prefs,
)
from native_download import DownloadPage
from native_queue import JobRow, QueuePage  # noqa: F401 — JobRow 只是 re-export
from native_settings import SettingsPage

_tr = QCoreApplication.translate  # 名稱固定是 _tr（docs/I18N.md 2.2）

# --------------------------------------------------------------------------- #
#  主視窗
# --------------------------------------------------------------------------- #
SIDEBAR_W = 200
TOOLBAR_H = 52  # macOS 有工具列的視窗，標題列與工具列合併後的高度
PAGES = [(QT_TRANSLATE_NOOP("native_app", "新增下載"), "download",
          QT_TRANSLATE_NOOP("native_app", "貼上 YouTube 或其他影片網站的網址")),
         (QT_TRANSLATE_NOOP("native_app", "下載佇列"), "list",
          QT_TRANSLATE_NOOP("native_app", "關閉視窗後，下次開啟可以接著下載")),
         (QT_TRANSLATE_NOOP("native_app", "設定"), "gear", "")]
GEOMETRY_KEY = "ui/window_geometry"  # SET9：視窗大小、位置
# 視窗最小尺寸。macOS 的系統字型較寬，英文介面在 720 寬時「新增下載」「設定」頁會被撐出橫向捲軸
# （CI 實測內容 547／577px > 可視 502px），所以 macOS 放寬到 800；其他平台維持 720。
def min_window_width(is_mac: bool = IS_MAC) -> int:
    return 800 if is_mac else 720


MIN_WINDOW_WIDTH = min_window_width()
MIN_WINDOW_HEIGHT = 520
TRAY_HINT_KEY = "ui/tray_hint_shown"  # 第一次縮到系統匣時的通知只顯示一次
TOAST_MS, TOAST_ACTION_MS = 4000, 10000  # 一般提示幾秒後自動消失；有按鈕的久一點。錯誤要手動關閉（ERR8）
# 每分鐘看一次 /api/meta：儲存位置還能不能用（執行中拔掉外接硬碟）、yt-dlp 有沒有新版（引擎在背景下載）
STORAGE_CHECK_MS = 60_000


def page_title(i: int) -> str:
    return _tr("native_app", PAGES[i][0])


class Toolbar(QFrame):
    """內容區頂端的工具列：顯示目前頁面的標題（macOS 的標題在工具列裡，不在內容區放大字）。
    macOS 上標題列是透明的、內容延伸到最上面，所以要自己處理拖曳視窗。"""

    def __init__(self):
        super().__init__()
        self.setObjectName("toolbar")
        self.setFixedHeight(TOOLBAR_H)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 0, 20, 0)
        lay.setSpacing(0)
        lay.addStretch()
        self.title = label("", "toolbarTitle")
        self.subtitle = label("", "toolbarSubtitle")
        lay.addWidget(self.title)
        lay.addWidget(self.subtitle)
        lay.addStretch()

    def set_title(self, title: str, subtitle: str):
        self.title.setText(title)
        self.subtitle.setText(subtitle)
        self.subtitle.setVisible(bool(subtitle))

    # 只有 macOS 毛玻璃模式的標題列是透明、被工具列蓋住的；其他情況有原生標題列，工具列就是一般內容
    def mousePressEvent(self, e):
        if native_common.VIBRANCY and e.button() == Qt.LeftButton and self.window().windowHandle():
            self.window().windowHandle().startSystemMove()
        else:
            super().mousePressEvent(e)

    def mouseDoubleClickEvent(self, e):
        if native_common.VIBRANCY:  # 跟系統標題列一樣：連按兩下縮放視窗
            w = self.window()
            w.showNormal() if w.isMaximized() else w.showMaximized()
        else:
            super().mouseDoubleClickEvent(e)


def drop_items(mime) -> list[str]:
    """拖放進來的內容 → 交給 DownloadPage.accept_urls() 的清單：網址、本機檔案路徑（.txt）或整段文字。"""
    if mime is None:
        return []
    if mime.hasUrls():
        items = [u.toLocalFile() if u.isLocalFile() else u.toString() for u in mime.urls()]
        items = [i for i in items if i]
        if items:
            return items
    if mime.hasText() and (mime.text() or "").strip():
        return [mime.text()]
    return []


def looks_like_link(arg: str) -> bool:
    """命令列參數看起來是不是一個連結（有「協定:」開頭，但不是 Windows 的 C:\\ 路徑、也不是 --參數）。"""
    arg = (arg or "").strip()
    return (bool(re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", arg)) and not re.match(r"^[A-Za-z]:[\\/]", arg)
            and not arg.startswith("-"))


class MainWindow(QMainWindow):
    def __init__(self, api: Api, busy, engine_hint: str = "", *, log_path: Path | None = None, restart=None):
        super().__init__()
        self.api, self.busy = api, busy
        self.engine_hint = engine_hint  # 連到的程式不是引擎時的說明（連接埠）
        self.log_path = Path(log_path) if log_path else None  # 引擎的紀錄檔（engine.log）
        self.restart_app = restart  # 「重新啟動 App」：main() 傳入；沒有時不顯示這個按鈕
        self.quit_on_close = False  # main() 設成 True：主視窗真的關閉時結束 App（App 設了不在最後一個視窗關閉時自動結束）
        self.tray = None  # TrayController（attach_tray）
        self._quitting = False
        self._offline = False
        self._app_update: dict | None = None  # C2：App 有新版
        self._ytdlp_update = False
        self.setWindowTitle(app_title())
        self.resize(1000, 700)
        self.setMinimumSize(MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)
        self.setAcceptDrops(True)  # F4：網址文字、.txt 檔拖到視窗任何地方都可以
        root = QWidget()
        h = QHBoxLayout(root)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)

        side = QFrame()
        side.setObjectName("sidebar")
        side.setFixedWidth(SIDEBAR_W)
        sl = QVBoxLayout(side)
        sl.setSpacing(1)
        icon_path = BUNDLE / "assets" / "icon-128.png"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))
        if IS_MAC:
            # 紅黃綠按鈕在側邊欄左上角，下面直接接導覽列（macOS App 不在側邊欄重複 App 名稱）
            sl.setContentsMargins(10, TOOLBAR_H, 10, 12)
        else:
            sl.setContentsMargins(10, 14, 10, 12)
            brand = QHBoxLayout()
            brand.setContentsMargins(6, 0, 0, 0)
            icon = QLabel()
            if icon_path.exists():
                icon.setPixmap(rounded(QPixmap(str(icon_path)), 22, 22, 5))
            brand.addWidget(icon)
            brand.addWidget(label(app_title(), "rowTitle"))
            brand.addStretch()
            sl.addLayout(brand)
            sl.addSpacing(14)

        self.stack = QStackedWidget()
        self.download = DownloadPage(api, self.toast)
        self.queue = QueuePage(api, self.toast)
        self.settings = SettingsPage(api, self.toast, self.download.advanced)
        self.nav: list[QPushButton] = []
        self.nav_group = QButtonGroup(self)  # 互斥群組：側邊欄可以用方向鍵切換（A11Y2）
        for i, ((_, sym, _sub), page) in enumerate(zip(PAGES, (self.download, self.queue, self.settings))):
            b = QPushButton(page_title(i))
            b.setObjectName("navButton")
            b.setCheckable(True)
            b.setIconSize(QSize(16, 16))
            # 只用鍵盤（Tab）取得焦點：滑鼠點了不會留下焦點框，切到「新增下載」時焦點才能直接到網址欄
            b.setFocusPolicy(Qt.TabFocus)
            b.setAccessibleName(page_title(i))
            b.setToolTip(self.tr("{page}（{key}）").format(page=page_title(i), key=self._key_text(f"Ctrl+{i + 1}")))
            b._sym = sym
            b.clicked.connect(lambda _=False, i=i: self.go(i))
            self.nav_group.addButton(b, i)
            self.nav.append(b)
            sl.addWidget(b)
            self.stack.addWidget(page)
        sl.addStretch()
        self.engine = label("", "subtitle", wrap=True)
        self.engine.setContentsMargins(8, 0, 8, 0)
        sl.addWidget(self.engine)

        content = QWidget()
        content.setObjectName("content")
        cl = QVBoxLayout(content)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        self.toolbar = Toolbar()
        cl.addWidget(self.toolbar)
        # 頁面上方：引擎離線（ERR6）與儲存位置無法存取（R1）。問題解決前一直顯示，不能關閉
        self.engine_banner = Banner()
        self.storage_banner = Banner()
        for b in (self.engine_banner, self.storage_banner):
            row = QHBoxLayout()
            row.setContentsMargins(28, 12, 28, 0)
            row.addWidget(b)
            cl.addLayout(row)
        cl.addWidget(self.stack, 1)
        self.banner = Banner()  # toast：頁面下方
        bl = QHBoxLayout()
        bl.setContentsMargins(28, 0, 28, 16)
        bl.addWidget(self.banner)
        cl.addLayout(bl)
        h.addWidget(side)
        h.addWidget(content, 1)
        self.setCentralWidget(root)

        self.download.queued.connect(lambda: (self.queue.refresh(), self.go(1)))
        self.download.url.installEventFilter(self)  # 網址欄自己也收拖放：網址一樣交給 accept_urls
        self.queue.counts.connect(self.on_counts)
        self.queue.online.connect(self.on_online)
        self.queue.job_finished.connect(self.on_job_finished)
        self.settings.meta_changed.connect(self.on_meta)
        self.settings.defaults_changed.connect(self.download.apply_defaults)
        self.settings.update_available.connect(self.on_app_update)  # C2: App new version badge
        self.clipboard = ClipboardWatcher(self)
        self.clipboard.found.connect(self.paste_link, Qt.QueuedConnection)
        self._last_clip = None  # 處理過的剪貼簿內容：同一段只處理一次
        self._toast_timer = QTimer(self)
        self._toast_timer.setSingleShot(True)
        self._toast_timer.timeout.connect(self.banner.dismiss)
        self.banner.closed.connect(self._toast_timer.stop)
        self._storage_timer = QTimer(self)
        self._storage_timer.timeout.connect(self.check_meta)
        self._install_shortcuts()
        self.go(0)

    # ---------- 啟動 ----------
    def start(self):
        """視窗顯示後開始和引擎溝通：確認引擎已啟動、開始更新下載佇列。"""
        self.queue.start()
        self.check_engine()
        self._storage_timer.start(STORAGE_CHECK_MS)
        if auto_paste_enabled():
            ClipboardWatcher.warm_up()
        QTimer.singleShot(300, self.check_clipboard)  # 開啟時剪貼簿裡已經有影片連結：直接貼上
        if self.stack.currentIndex() == 0:
            self.download.focus_url()  # DL7：開啟後可以直接貼上網址

    # ---------- 快捷鍵（DL8） ----------
    @staticmethod
    def _key_text(keys: str) -> str:
        return QKeySequence(keys).toString(QKeySequence.NativeText)

    def _install_shortcuts(self):
        self.shortcuts: dict[str, QShortcut] = {}

        def add(keys: str, fn):
            sc = QShortcut(QKeySequence(keys), self)
            sc.setContext(Qt.WindowShortcut)
            sc.activated.connect(fn)
            self.shortcuts[keys] = sc

        add("Ctrl+L", self.focus_url)
        add("Ctrl+Return", self.start_download)
        add("Ctrl+Enter", self.start_download)  # 數字鍵盤的 Enter
        for i in range(len(PAGES)):
            add(f"Ctrl+{i + 1}", lambda i=i: self.go(i))
        add("Ctrl+,", lambda: self.open_settings())  # macOS 是 ⌘,（Qt 的 Ctrl 在 macOS 對應 ⌘）

    def focus_url(self):
        self.go(0)
        self.download.focus_url()

    def start_download(self):
        if self.stack.currentIndex() == 0:
            self.download.start_download()

    def keyPressEvent(self, e):
        # Esc：取消解析。焦點在「新增下載」頁裡時頁面自己會處理；焦點在側邊欄等其他地方時由這裡處理。
        # 不用 QShortcut：會把整個視窗的 Esc 都吃掉（對話框、選單以外的地方也需要 Esc）
        if e.key() == Qt.Key_Escape and self.stack.currentIndex() == 0 and getattr(self.download, "_analyzing", False):
            self.download.cancel_analyze()
            e.accept()
            return
        super().keyPressEvent(e)

    # ---------- 拖放（F4） ----------
    def dragEnterEvent(self, e):
        if drop_items(e.mimeData()):
            e.acceptProposedAction()
        else:
            e.ignore()

    def dragMoveEvent(self, e):
        self.dragEnterEvent(e)

    def dropEvent(self, e):
        items = drop_items(e.mimeData())
        if not items:
            e.ignore()
            return
        e.acceptProposedAction()
        self.accept_dropped(items)

    def accept_dropped(self, items: list[str]):
        self.go(0)
        self.download.accept_urls(items)
        self.activateWindow()

    def eventFilter(self, obj, e):
        # 網址欄（QLineEdit）預設會把拖進來的文字插進游標位置；網址和檔案改成和視窗其他地方一樣處理
        if obj is self.download.url and e.type() in (QEvent.DragEnter, QEvent.DragMove, QEvent.Drop):
            mime = e.mimeData()
            items = drop_items(mime) if mime is not None and mime.hasUrls() else []
            if items:
                e.acceptProposedAction()
                if e.type() == QEvent.Drop:
                    self.accept_dropped(items)
                return True
        # 引擎離線時「解析」已停用；網址欄按 Enter 也不要送出（不然只會再多一個錯誤）
        if (obj is self.download.url and self._offline and e.type() == QEvent.KeyPress
                and e.key() in (Qt.Key_Return, Qt.Key_Enter) and not e.modifiers() & Qt.ControlModifier):
            self.toast(self.tr("下載引擎沒有回應，暫時無法解析。請先按上方的「重試」。"), level="error")
            return True
        return super().eventFilter(obj, e)

    # ---------- 自動貼上剪貼簿裡的影片連結 ----------
    def changeEvent(self, e):
        super().changeEvent(e)
        # 在瀏覽器複製網址後切回 App：再看一次剪貼簿
        if e.type() == QEvent.ActivationChange and self.isActiveWindow():
            self.check_clipboard()

    def check_clipboard(self):
        if not auto_paste_enabled():
            return
        text = (QGuiApplication.clipboard().text() or "").strip()
        if not text or text == self._last_clip or "\n" in text or len(text) > 2000:
            return
        self._last_clip = text
        self.clipboard.check(text)

    def paste_link(self, url: str):
        """剪貼簿裡的連結：交給「新增下載」頁。已經是這個網址就不動作；畫面上已有影片、正在解析、
        或使用者正在輸入別的網址時，頁面會改成顯示「偵測到新連結」讓使用者決定，不會直接蓋掉（DL5）。"""
        page = self.download
        if self._offline or url in (page.url.text().strip(), page._analyzed_url):
            return  # 引擎離線時不能解析：不要自動貼上，免得多一個錯誤
        self.go(0)
        page.accept_urls([url])
        if page.new_link.isHidden():  # 真的填入並開始解析了（沒有改成提示）
            self.toast(self.tr("已自動貼上剪貼簿裡的影片連結（可在「設定」關閉）"))

    # ---------- 引擎狀態（R1、ERR6、ERR7） ----------
    def check_engine(self, attempt: int = 0, max_attempts: int = 30):
        """引擎剛啟動可能還沒開始聽連接埠：最多等 15 秒；連不上或對方不是引擎就顯示原因。"""
        def ok(m):
            if not isinstance(m, dict) or "version" not in m:
                return fail(_tr("native_common", NOT_ENGINE), final=True, not_engine=True)
            self.set_online(True)
            self.settings.on_meta(m)  # → meta_changed → on_meta（儲存位置、更新徽章）
            if m.get("just_updated"):
                self.toast(self.tr("yt-dlp 已更新至 {version}").format(version=m.get("version")))

        def fail(msg, final=False, not_engine=False):
            if not final and attempt < max_attempts:
                QTimer.singleShot(500, self, lambda: self.check_engine(attempt + 1, max_attempts))
                return
            body = str(msg)
            if not_engine and self.engine_hint:
                body = self.tr("{reason}。{hint}").format(reason=body, hint=self.engine_hint)
            self.show_offline(self.tr("無法連到下載引擎"), body)

        self.api.get("/api/meta", ok, fail, timeout_ms=30_000)

    def retry_engine(self):
        self.engine_banner.body.setText(self.tr("正在重新連線…"))
        self.check_engine(0, 3)
        self.queue.refresh()

    def show_offline(self, title: str, reason: str):
        """引擎離線：說明＋「重試」「開啟紀錄檔」「重新啟動 App」，並停用「解析」（不能解析就不要讓人按了才報錯）。"""
        body = self.tr("{reason}\n下載和解析暫時無法使用。可以按「重試」；一直無法連線時請重新啟動 App，"
                       "或開啟紀錄檔查看原因。").format(reason=reason) if reason else ""
        actions = [(self.tr("重試"), self.retry_engine)]
        if self.log_path is not None:
            actions.append((self.tr("開啟紀錄檔"), self.open_log))
        if self.restart_app is not None:
            actions.append((self.tr("重新啟動 App"), self.restart_app))
        self.engine_banner.show_message(body, title, error=True, actions=actions, copyable=True, closable=False)
        self.set_online(False)

    def set_online(self, online: bool):
        page = self.download
        if online:
            self.engine_banner.hide()
            if self._offline and not getattr(page, "_analyzing", False):
                page.analyze_btn.setEnabled(True)
                page.analyze_btn.setToolTip("")
        else:
            page.analyze_btn.setEnabled(False)
            page.analyze_btn.setToolTip(self.tr("下載引擎沒有回應，暫時無法解析"))
        self._offline = not online

    def on_online(self, ok: bool, msg: str):
        if ok:  # 佇列拿到引擎的工作清單：引擎正常
            if self._offline:
                self.set_online(True)
            return
        self.show_offline(self.tr("與下載引擎的連線中斷了"),
                          self.tr("畫面上的進度可能不是最新的。（{reason}）").format(reason=msg))

    def open_log(self):
        path = self.log_path
        if path is None:
            return
        target = path if path.exists() else path.parent
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(target))):
            self.toast(self.tr("無法開啟紀錄檔：{path}").format(path=str(path)), level="error")

    def check_meta(self):
        self.api.get("/api/meta", self.settings.on_meta, timeout_ms=30_000)

    def on_meta(self, m: dict):
        if not isinstance(m, dict):
            return
        self._ytdlp_update = SettingsPage.ytdlp_update_available(m)
        self._update_settings_badge()
        if "download_dir_error" in m:
            self.show_storage_problem(m)

    def on_app_update(self, info: dict | None = None):
        """C2：App 有新版（SettingsPage.update_available）時在側邊欄「設定」顯示徽章。"""
        self._app_update = info if info else None
        self._update_settings_badge()

    def _update_settings_badge(self):
        has_update = self._ytdlp_update or bool(self._app_update)
        self.nav[2].setText(self.tr("設定　有更新") if has_update else page_title(2))

    def show_storage_problem(self, m: dict):
        """R1：儲存位置無法存取（外接硬碟沒接、磁碟代號不存在）時顯示完整路徑和「更換位置」「重試」。"""
        problem = m.get("download_dir_error")
        if not problem:
            self.storage_banner.hide()
            return
        path = m.get("download_dir") or ""
        title = (self.tr("儲存位置 {path} 目前無法存取").format(path=path) if path
                 else self.tr("儲存位置目前無法存取"))
        body = self.tr("可能是外接硬碟、隨身碟或網路磁碟沒有連上。接上後按「重試」，或更換儲存位置。")
        self.storage_banner.show_message(body, title, error=True, closable=False, actions=[
            (self.tr("更換位置"), self.choose_storage), (self.tr("重試"), self.check_meta)])
        self.storage_banner.setToolTip(str(m.get("download_dir_error_detail") or problem))

    def choose_storage(self):
        """選新的下載資料夾並馬上套用，不用重開 App。"""
        current = self.settings.folder.full_text()
        path = QFileDialog.getExistingDirectory(self, self.tr("選擇下載資料夾"), current)
        if path:
            self.set_storage(path)

    def set_storage(self, path: str):
        def ok(s):
            if isinstance(s, dict):
                self.settings.on_settings(s)
                if s.get("download_dir_error"):
                    self.show_storage_problem(s)
                    return
            self.storage_banner.hide()
            self.toast(self.tr("已變更儲存位置：{path}").format(path=(s or {}).get("download_dir") or path))
            self.check_meta()

        self.api.post("/api/settings", {"download_dir": path}, ok,
                      lambda e: self.toast(str(e), level="error"))

    def open_settings(self, section: str = ""):
        """切到設定頁並捲到指定的分組（C2 的 focus_section；"storage"、"cookies"、"language"、"about"…）。"""
        self.go(2)
        if section:
            self.settings.focus_section(section)

    # ---------- 外觀、頁面 ----------
    def apply_theme(self, t: dict[str, str]):
        for b in self.nav:
            b.setIcon(symbol(b._sym, t["accent"]))
        self.download.apply_theme(t)
        self.queue.apply_theme(t)

    def go(self, i: int):
        self.nav[i].setChecked(True)
        self.stack.setCurrentIndex(i)
        self.toolbar.set_title(page_title(i), _tr("native_app", PAGES[i][2]) if PAGES[i][2] else "")
        if i == 0 and QApplication.focusWidget() not in self.nav:
            # DL7：切回「新增下載」時焦點到網址欄。用鍵盤在側邊欄切換時不搶焦點，方向鍵才能繼續切
            self.download.focus_url()
        if i == 2:
            self.settings.refresh()

    def on_counts(self, active: int):
        self.nav[1].setText(self.tr("下載佇列　{count}").format(count=active) if active else page_title(1))
        self.engine.setText(_tr("MainWindow", "%n 個下載進行中", None, active) if active else "")
        self.update_tray()

    # ---------- 提示（ERR8） ----------
    def toast(self, text: str, error: bool = False, level: str | None = None, actions=None):
        """頁面下方的提示。level="error"（或舊的 error=True）：不會自動消失、可以複製；
        actions=[(按鈕文字, 函式), …]：按了執行並關閉提示。舊的 toast(text) / toast(text, error=True) 照常可用。"""
        is_error = (level or ("error" if error else "info")) == "error"
        self.banner.show_message(str(text), error=is_error, actions=actions or (), copyable=is_error,
                                 dismiss_on_action=True)
        if is_error:
            self._toast_timer.stop()
        else:
            self._toast_timer.start(TOAST_ACTION_MS if actions else TOAST_MS)

    # ---------- 系統匣與通知（F2、F3） ----------
    def attach_tray(self, tray):
        self.tray = tray
        tray.show_requested.connect(self.bring_to_front)
        tray.pause_all_requested.connect(self.queue.pause_all)
        tray.resume_all_requested.connect(self.queue.resume_all)
        tray.quit_requested.connect(self.request_quit)
        tray.notification_clicked.connect(self.show_job)
        self.update_tray()

    def update_tray(self):
        if self.tray is None:
            return
        s = self.queue.summary()
        self.tray.set_summary(s.get("text") or "", s.get("progress"))

    def in_foreground(self) -> bool:
        return (self.isVisible() and not self.isMinimized()
                and QGuiApplication.applicationState() == Qt.ApplicationActive)

    @staticmethod
    def job_notice(job: dict) -> tuple[str, str]:
        """工作完成／失敗時系統通知的標題與內文。"""
        name = str(job.get("title") or job.get("url") or "")
        if job.get("status") == "error":
            reason = str(job.get("error") or "")
            title = _tr("MainWindow", "下載失敗")
            body = _tr("MainWindow", "{name}\n{reason}").format(name=name, reason=reason) if reason else name
            return title, body.strip()
        if job.get("failed_items") or job.get("warnings"):
            return _tr("MainWindow", "下載完成，但有部分項目沒有成功"), name
        return _tr("MainWindow", "下載完成"), name

    def on_job_finished(self, job: dict):
        if not isinstance(job, dict):
            return
        if job.get("error_code") == "download_dir_unavailable":
            self.check_meta()  # 執行中拔掉磁碟：馬上顯示儲存位置的提示
        if self.in_foreground():
            return  # App 在前景時佇列頁自己會顯示，不跳系統通知
        title, body = self.job_notice(job)
        if self.tray is not None and self.tray.notify(title, body, str(job.get("id") or "")):
            return
        self.toast(self.tr("{title}：{body}").format(title=title, body=body.replace("\n", " ")),
                   level="error" if job.get("status") == "error" else "info")

    def show_job(self, job_id: str = ""):
        """點通知：叫回視窗、切到佇列並標示該工作。"""
        self.bring_to_front()
        self.go(1)
        if job_id:
            self.queue.show_job(job_id)

    def bring_to_front(self):
        if self.isHidden():
            self.show()
        if self.isMinimized():
            self.setWindowState((self.windowState() & ~Qt.WindowMinimized) | Qt.WindowActive)
        self.raise_()
        self.activateWindow()

    def close_action(self) -> str:
        """關閉視窗時要做什麼（C2 的設定）："quit" 結束 App、"tray" 縮到系統匣。"""
        try:
            value = self.settings.close_action()
        except Exception:  # noqa: BLE001 — 讀不到設定就照預設，不能讓視窗關不掉
            value = "quit"
        return value if value in ("quit", "tray") else "quit"

    def can_hide_to_tray(self) -> bool:
        return self.tray is not None and self.tray.is_available()

    def hide_to_tray(self):
        self.save_geometry()
        self.hide()
        st = settings_store()
        if str(st.value(TRAY_HINT_KEY, "") or "") != "1":
            body = (self.tr("App 會在背景繼續下載，從選單列圖示可以叫回視窗或結束") if IS_MAC
                    else self.tr("App 會在背景繼續下載，從系統匣圖示可以叫回視窗或結束"))
            if self.tray.notify(self.tr("YT 下載器仍在執行"), body):
                st.setValue(TRAY_HINT_KEY, "1")  # 真的顯示了才記住；系統不支援通知時下次再試

    def confirm_quit(self) -> bool:
        """有下載進行中時先詢問；沒有下載或使用者按「結束」回傳 True。"""
        if not self.busy():
            return True
        box = QMessageBox(self if self.isVisible() else None)
        box.setIcon(QMessageBox.Question)
        box.setWindowTitle(app_title())
        box.setText(self.tr("要結束 YT 下載器嗎？"))
        box.setInformativeText(self.tr("還有下載正在進行。結束後工作會暫停，下次開啟時按「繼續下載」就能接著下載。"))
        quit_btn = box.addButton(self.tr("結束"), QMessageBox.DestructiveRole)
        box.setDefaultButton(box.addButton(self.tr("取消"), QMessageBox.RejectRole))
        box.exec()
        ok = box.clickedButton() is quit_btn
        shiboken6.delete(box)
        return ok

    def request_quit(self):
        """系統匣選單的「結束」：不管「關閉視窗時」的設定，真的結束（有下載時先詢問）。"""
        if not self.confirm_quit():
            return
        self._quitting = True
        if self.isVisible():
            self.save_geometry()
        self.close()
        if self.quit_on_close:
            QApplication.quit()

    def closeEvent(self, e):
        if not self._quitting and self.close_action() == "tray" and self.can_hide_to_tray():
            e.ignore()  # 縮到系統匣，下載繼續
            self.hide_to_tray()
            return
        if not self._quitting and not self.confirm_quit():
            e.ignore()
            return
        self.save_geometry()
        e.accept()
        if self.quit_on_close:
            QApplication.quit()

    # ---------- 記住視窗大小、位置（SET9） ----------
    def save_geometry(self):
        settings_store().setValue(GEOMETRY_KEY, self.saveGeometry())

    def restore_geometry(self) -> bool:
        data = settings_store().value(GEOMETRY_KEY)
        if isinstance(data, (QByteArray, bytes)) and len(data):
            return bool(self.restoreGeometry(QByteArray(data)))  # 螢幕已不存在時 Qt 會把視窗移回看得到的地方
        return False

    # ---------- ytdl:// 與再次開啟 App（F7） ----------
    def handle_handoff(self, args: list[str]):
        """另一個程序（再開一次 App、瀏覽器開 ytdl:// 連結）或 macOS 的 QFileOpenEvent 送來的參數。
        一律喚醒視窗；合法的 http/https 網址交給「新增下載」（只填入並解析，絕不自動下載），
        其他協定（file:、javascript:…）拒絕並提示。"""
        args = [str(a) for a in (args or [])]
        urls = url_handoff.parse_handoff_args(args)
        rejected = [a for a in args if looks_like_link(a) and url_handoff.parse_handoff(a) is None]
        self.bring_to_front()
        if urls:
            self.go(0)
            self.download.accept_urls(urls)
        if rejected and all(url_handoff.rejected_as_local(a) for a in rejected):
            self.toast(self.tr("這個連結無法開啟：從瀏覽器送進來的網址不能指向這台電腦（localhost、127.0.0.1 等）。"),
                       level="error")
        elif rejected:
            self.toast(self.tr("這個連結無法開啟：App 只接受 http:// 或 https:// 開頭的影片網址。"), level="error")


class Handoff(QObject):
    """在主視窗準備好（同意免責聲明、顯示）之前收到的參數先存起來，準備好之後再一起交出去。"""
    received = Signal(list)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self.pending: list[list[str]] = []
        self.handler = None

    def add(self, args):
        args = [str(a) for a in (args or [])]
        if self.handler is None:
            self.pending.append(args)
        else:
            self.handler(args)

    def set_handler(self, handler):
        self.handler = handler
        pending, self.pending = self.pending, []
        for args in pending:
            handler(args)


class FileOpenFilter(QObject):
    """macOS：點 ytdl:// 連結時系統不是用命令列參數，而是送 QFileOpenEvent 給 QApplication（App 已開或剛啟動都一樣）。"""
    opened = Signal(list)

    def eventFilter(self, obj, e):
        if e.type() == QEvent.FileOpen:
            url = e.url()
            text = url.toString() if url.isValid() and url.scheme() and not url.isLocalFile() else e.file()
            if text:
                self.opened.emit([text])
            return True
        return False


def mac_window_setup(win: QMainWindow) -> bool:
    """macOS：標題列透明、內容延伸到視窗頂端（側邊欄接到紅黃綠按鈕下），側邊欄後面放系統的毛玻璃材質。
    只在真正的 Cocoa 視窗上做（offscreen 等平台的 winId() 不是 NSView，交給 PyObjC 會直接當掉）。
    需要 PyObjC；沒有或失敗時維持一般視窗與不透明側邊欄。"""
    global VIBRANCY
    if not IS_MAC or QGuiApplication.platformName() != "cocoa":
        return False
    try:
        import objc
        from AppKit import (
            NSColor,
            NSViewHeightSizable,
            NSVisualEffectBlendingModeBehindWindow,
            NSVisualEffectMaterialSidebar,
            NSVisualEffectStateFollowsWindowActiveState,
            NSVisualEffectView,
            NSWindowBelow,
            NSWindowTitleHidden,
        )
    except ImportError:
        return False
    try:
        # 都要在 winId() 建立原生視窗之前設定：
        # ExpandedClientAreaHint 讓內容延伸到標題列底下，而且 Qt 知道這件事（版面從視窗最上方開始排，
        # 自己改 NSWindow 的 styleMask 的話 Qt 不知道，標題列那一條會是空的黑帶）；
        # NoTitleBarBackgroundHint 讓標題列透明；WA_TranslucentBackground 讓毛玻璃透得出來
        win.setWindowFlag(Qt.ExpandedClientAreaHint, True)
        win.setWindowFlag(Qt.NoTitleBarBackgroundHint, True)
        win.setAttribute(Qt.WA_TranslucentBackground)
        # 頂層視窗預設會把標題列高度（安全區域）加進版面邊距，內容又被往下推、頂端留空。
        # 紅黃綠按鈕的位置已經由側邊欄的上邊距（TOOLBAR_H）避開，所以不要再加
        for w in (win, win.centralWidget()):
            if w is not None:
                w.setAttribute(Qt.WA_ContentsMarginsRespectsSafeArea, False)
        nswin = objc.objc_object(c_void_p=int(win.winId())).window()
        nswin.setTitleVisibility_(NSWindowTitleHidden)  # 標題改顯示在自己的工具列
        content = nswin.contentView()
        height = content.frame().size.height
        fx = NSVisualEffectView.alloc().initWithFrame_(((0, 0), (SIDEBAR_W, height)))
        fx.setMaterial_(NSVisualEffectMaterialSidebar)
        fx.setBlendingMode_(NSVisualEffectBlendingModeBehindWindow)
        fx.setState_(NSVisualEffectStateFollowsWindowActiveState)
        fx.setAutoresizingMask_(NSViewHeightSizable)
        # Qt 的內容畫在 contentView 上：視窗設為透明，毛玻璃放在 contentView 後面
        nswin.setOpaque_(False)
        nswin.setBackgroundColor_(NSColor.clearColor())
        content.superview().addSubview_positioned_relativeTo_(fx, NSWindowBelow, content)
    except Exception as e:  # noqa: BLE001 — 視窗外觀失敗不能讓 App 打不開
        print(f"macOS window appearance setup failed: {e}", flush=True)
        return False
    # 樣式表（native_common.stylesheet）與工具列讀的是 native_common 的值；本模組的同名變數一起更新
    native_common.VIBRANCY = VIBRANCY = True
    return True


def apply_theme(app: QApplication, win: MainWindow, chevron: str, dark: bool | None = None,
                scale: float | None = None):
    """套用深淺色與文字大小。dark / scale 未指定時用「設定 → 外觀」的選擇（主題選「跟隨系統」就看系統外觀）。"""
    theme, size = ui_prefs()
    if dark is None:
        dark = theme == "dark" if theme != "system" else app.styleHints().colorScheme() == Qt.ColorScheme.Dark
    if scale is None:
        scale = FONT_SCALE[size]
    app.setFont(ui_font(scale))
    t = tokens(dark)
    if not IS_MAC:  # macOS 的原生元件用系統自己的配色
        pal = app.palette()
        pal.setColor(QPalette.Window, QColor(t["bg"]))
        pal.setColor(QPalette.Base, QColor(t["field"]))
        pal.setColor(QPalette.Text, QColor(t["text"]))
        pal.setColor(QPalette.WindowText, QColor(t["text"]))
        pal.setColor(QPalette.ButtonText, QColor(t["text"]))
        pal.setColor(QPalette.Highlight, QColor(t["accent"]))
        pal.setColor(QPalette.PlaceholderText, QColor(t["tertiary"]))
        app.setPalette(pal)
    app.setStyleSheet(stylesheet(t, chevron, scale))
    win.apply_theme(t)


def apply_appearance(app: QApplication, win: MainWindow, chevron: str):
    """套用「設定 → 外觀」：指定淺色／深色時也告訴 Qt，macOS 的原生元件才會跟著變；選「跟隨系統」就交回給系統。"""
    theme, _ = ui_prefs()
    scheme = {"light": Qt.ColorScheme.Light, "dark": Qt.ColorScheme.Dark}.get(theme, Qt.ColorScheme.Unknown)
    # 一律設定：即使目前系統剛好也是淺色，也要鎖定成淺色，之後系統改成深色時原生元件才不會跟著變
    app.styleHints().setColorScheme(scheme)  # 有變化時會觸發 colorSchemeChanged → apply_theme
    apply_theme(app, win, chevron)


def start_engine():
    """在同一個程序裡啟動下載引擎（已經有程式在用連接埠就直接連過去）。回傳 (網址, 是否有工作進行中的函式)。"""
    import app_boot
    import server
    return app_boot.start_engine(server)


def create_app() -> tuple[QApplication, str]:
    """建立 QApplication 並套上平台樣式；回傳 (app, 彈出選單箭頭圖檔的路徑)。"""
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName(TITLE)
    if not IS_MAC:
        app.setStyle("Fusion")  # Windows：用中性的基底，再用樣式表畫成 macOS 的樣子
    app.setFont(ui_font())
    return app, (BUNDLE / "assets" / "chevron.png").as_posix()


class Restarter(QObject):
    """yt-dlp 更新後的重新啟動：引擎的背景執行緒發出要求，在主執行緒結束事件迴圈，
    main() 照正常流程釋放 Qt 後才啟動新程序（直接在背景執行緒 os._exit 會讓 Qt 當掉）。"""
    requested = Signal(list, dict)

    def __init__(self, app: QApplication):
        super().__init__()
        self.app = app
        self.pending: tuple[list, dict] | None = None
        self.requested.connect(self._on_requested, Qt.QueuedConnection)

    def __call__(self, cmd: list, env: dict):  # server.RESTART_HANDLER，在任何執行緒呼叫都可以
        self.requested.emit(cmd, env)

    def _on_requested(self, cmd: list, env: dict):
        self.pending = (cmd, env)
        self.app.exit(0)

    def launch(self, cwd: Path):
        if self.pending:
            import subprocess
            cmd, env = self.pending
            # 不重送網址（ytdl:// 開啟的 App 重開時不要再解析一次）；新程序先等這個程序放開連接埠（main()）
            cmd = [cmd[0], *[a for a in cmd[1:] if not looks_like_link(a)]]
            subprocess.Popen(cmd, env={**env, RESTARTED_ENV: "1"}, cwd=str(cwd))


RESTARTED_ENV = "YTDL_RESTARTED"  # 「重新啟動 App」開啟的新程序：先等舊程序放開連接埠


def restart_command(argv: list[str] | None = None, frozen: bool | None = None) -> list[str]:
    """重新啟動 App 的命令：只保留 -- 開頭的選項，不重送網址（已經送進來過了）。"""
    argv = list(sys.argv if argv is None else argv)
    frozen = getattr(sys, "frozen", False) if frozen is None else frozen
    opts = [a for a in argv[1:] if a.startswith("-") and a != "--smoke-test"]
    return [sys.executable, *opts] if frozen else [sys.executable, argv[0], *opts]


def wait_port_released(host: str, port: int, timeout: float = 15) -> bool:
    """等連接埠沒有程式在聽（重新啟動時舊程序還在收尾）。時間到仍被佔用回傳 False。"""
    end = time.monotonic() + timeout
    while True:
        try:
            with socket.create_connection((host, port), timeout=0.3):
                pass
        except OSError:
            return True
        if time.monotonic() >= end:
            return False
        time.sleep(0.2)


def instance_key(env=None) -> str:
    """單一實例的名稱。改了 YTDL_PORT 的 App（另一個引擎、測試用）算是另一個 App，不會被當成第二次開啟。"""
    env = os.environ if env is None else env
    port = str(env.get("YTDL_PORT", "") or "").strip()
    return "yt-dl" if port in ("", "8765") else "yt-dl-" + re.sub(r"[^0-9]", "", port)[:6]


def allow_foreground():
    """Windows：第二個程序是使用者剛開的（在前景），先允許第一個程序把視窗叫到最前面，否則只會在工作列閃爍。"""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.user32.AllowSetForegroundWindow(-1)  # ASFW_ANY
    except Exception:  # noqa: BLE001, S110 — 只影響視窗會不會跳到最前面
        pass


def hand_off_to_running_app(argv: list[str]):
    """F7：回傳 (是否已交給執行中的 App, SingleInstance 或 None)。第一個值是 True 時這個程序就該結束。
    要在 app_boot.boot() 之前呼叫：不能啟動第二個引擎。
    --server、--check-ytdlp 是給引擎自己用的指令，不經過判斷。"""
    if {"--server", "--check-ytdlp"} & set(argv[1:]):
        return False, None
    from single_instance import SingleInstance
    instance = SingleInstance(instance_key())
    if instance.is_primary():
        return False, instance
    allow_foreground()
    instance.send(argv[1:])  # 最多等 5 秒（第一個可能還在啟動）；送不出去也結束，不要開第二個引擎
    return True, instance


def main():
    import app_boot
    handed_off, instance = hand_off_to_running_app(sys.argv)
    if handed_off:
        sys.exit(0)
    if os.environ.pop(RESTARTED_ENV, "") == "1":  # 「重新啟動 App」：舊程序可能還沒放開連接埠
        wait_port_released(os.environ.get("YTDL_HOST", "127.0.0.1"), int(os.environ.get("YTDL_PORT", "8765")))
    server = app_boot.boot()  # --check-ytdlp / --server 在這裡處理並結束；沒有主控台時輸出寫到 engine.log
    app, chevron = create_app()
    i18n.install(app)  # 在建立任何視窗之前：介面語言（跟隨系統／中文／English）
    app.setQuitOnLastWindowClosed(False)  # 縮到系統匣時不能因為對話框關閉就結束；主視窗關閉時自己結束
    handoff = Handoff(app)
    if instance is not None:
        instance.listen()  # QApplication 建立之後才能開始接收
        instance.message_received.connect(handoff.add)
    file_open = FileOpenFilter(app)
    file_open.opened.connect(handoff.add)
    app.installEventFilter(file_open)
    restarter = Restarter(app)
    server.RESTART_HANDLER = restarter
    url, busy = app_boot.start_engine(server)
    log = server.ROOT / "engine.log"
    hint = _tr("native_app", "連接埠 {port} 可能被其他程式佔用，請關閉佔用的程式後重新啟動 App").format(port=server.PORT)
    win = MainWindow(Api(url, app), busy, hint, log_path=log,
                     restart=lambda: restarter(restart_command(), {k: v for k, v in os.environ.items() if k != "YTDL_JUST_UPDATED"}))
    win.quit_on_close = True
    win.restore_geometry()
    mac_window_setup(win)
    app.styleHints().colorSchemeChanged.connect(lambda *_: apply_theme(app, win, chevron))
    win.settings.appearance_changed.connect(lambda: apply_appearance(app, win, chevron))
    apply_appearance(app, win, chevron)  # 套用上次選的主題與文字大小
    # 第一次開啟：先同意免責聲明，按「離開」就結束。要在 win.show() 之前：
    # 視窗一顯示就會檢查剪貼簿、自動貼上並解析連結，不能在使用者同意前就送出請求
    require_disclaimer(app, win)
    from native_tray import TrayController
    tray = TrayController(app)
    win.attach_tray(tray)
    if IS_MAC:  # 縮到選單列後點 Dock 圖示：叫回視窗
        app.applicationStateChanged.connect(
            lambda state: win.bring_to_front() if state == Qt.ApplicationActive and win.isHidden() else None)
    win.show()
    win.start()
    if any(not a.startswith("-") for a in sys.argv[1:]):
        handoff.add(sys.argv[1:])  # 開啟 App 時就帶著網址（ytdl:// 連結開啟的第一個程序）
    handoff.set_handler(win.handle_handoff)  # 準備好了：交出等待中的參數，之後收到的直接處理
    app_boot.install_smoke_test(app)  # --smoke-test：CI 確認視窗能開啟後自動結束
    code = app.exec()
    tray.dispose()
    if instance is not None:
        instance.close()  # 先放開單一實例，重新啟動的新程序才不會以為 App 還開著
    shutdown(app, win)
    restarter.launch(server.ROOT)  # 更新 yt-dlp 後要求的重新啟動（新程序會等這裡釋放連接埠）
    os._exit(code)  # 結束背景的 Flask 與下載執行緒


def require_disclaimer(app: QApplication, win: QMainWindow, run=None, leave=None) -> bool:
    """顯示免責聲明（需要時）；按「離開」走正常的關閉流程（shutdown 釋放 Qt）後結束程序。
    在主視窗顯示之前呼叫，所以對話框不掛在 win 底下（掛在隱藏的視窗下 Windows 工作列不會出現它，
    容易被其他視窗蓋住找不到）；深淺色主題由 QApplication 的樣式表與調色盤套用。"""
    if confirm_disclaimer(None, run):
        return True
    (leave or (lambda: (shutdown(app, win), os._exit(0))))()
    return False


def shutdown(app: QApplication, win: QMainWindow):
    """先釋放視窗與 QApplication（連同掛在它底下的網路元件）再結束程序。
    Qt 物件還活著就 os._exit 時，Windows 卸載 Qt DLL 會隨機存取違規（約一半機率當掉，跳出錯誤回報）。"""
    shiboken6.delete(win)
    shiboken6.delete(app)


if __name__ == "__main__":
    # 以 native_app 模組身分執行：native_options / native_playlist 會 import native_app，
    # 直接用 __main__ 執行的話會載入第二份模組（兩套全域狀態）
    import native_app
    native_app.main()
