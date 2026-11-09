"""YT 下載器原生介面（Qt / PySide6），外觀參照 macOS。

介面直接用系統元件繪製（不是網頁），同一個程序在背景執行原本的下載引擎（server.py）。
介面透過引擎的本機 API 操作，所以下載、續傳、合併進度、yt-dlp 自動更新都和網頁版共用同一套引擎。

    python native_app.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QGuiApplication, QIcon, QPalette, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
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

import native_common

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
    ClipboardWatcher,
    auto_paste_enabled,
    confirm_disclaimer,
    label,
    rounded,
    stylesheet,
    symbol,
    tokens,
    ui_font,
    ui_prefs,
)
from native_download import DownloadPage
from native_queue import JobRow, QueuePage  # noqa: F401 — JobRow 只是 re-export
from native_settings import SettingsPage

# --------------------------------------------------------------------------- #
#  主視窗
# --------------------------------------------------------------------------- #
SIDEBAR_W = 200
TOOLBAR_H = 52  # macOS 有工具列的視窗，標題列與工具列合併後的高度
PAGES = [("新增下載", "download", "貼上 YouTube 或其他影片網站的網址"),
         ("下載佇列", "list", "關閉視窗後，下次開啟可以接著下載"),
         ("設定", "gear", "")]


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


class MainWindow(QMainWindow):
    def __init__(self, api: Api, busy, engine_hint: str = ""):
        super().__init__()
        self.api, self.busy = api, busy
        self.engine_hint = engine_hint  # 引擎啟動失敗時的說明（連接埠、紀錄檔位置）
        self.setWindowTitle(TITLE)
        self.resize(1000, 700)
        self.setMinimumSize(720, 520)
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
            brand.addWidget(label(TITLE, "rowTitle"))
            brand.addStretch()
            sl.addLayout(brand)
            sl.addSpacing(14)

        self.stack = QStackedWidget()
        self.download = DownloadPage(api, self.toast)
        self.queue = QueuePage(api, self.toast)
        self.settings = SettingsPage(api, self.toast, self.download.advanced)
        self.nav: list[QPushButton] = []
        group = QButtonGroup(self)
        for i, ((text, sym, _), page) in enumerate(zip(PAGES, (self.download, self.queue, self.settings))):
            b = QPushButton(text)
            b.setObjectName("navButton")
            b.setCheckable(True)
            b.setIconSize(QSize(16, 16))
            b._sym = sym
            b.clicked.connect(lambda _=False, i=i: self.go(i))
            group.addButton(b)
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
        self.engine_banner = self._banner(error=True)  # 引擎沒有回應：一直顯示到恢復為止
        eb = QHBoxLayout()
        eb.setContentsMargins(28, 12, 28, 0)
        eb.addWidget(self.engine_banner)
        cl.addLayout(eb)
        cl.addWidget(self.stack, 1)
        self.banner = self._banner()
        bl = QHBoxLayout()
        bl.setContentsMargins(28, 0, 28, 16)
        bl.addWidget(self.banner)
        cl.addLayout(bl)
        h.addWidget(side)
        h.addWidget(content, 1)
        self.setCentralWidget(root)

        self.download.queued.connect(lambda: (self.queue.refresh(), self.go(1)))
        self.queue.counts.connect(self.on_counts)
        self.queue.online.connect(self.on_online)
        self.settings.meta_changed.connect(self.on_meta)
        self.settings.defaults_changed.connect(self.download.apply_defaults)
        self.clipboard = ClipboardWatcher(self)
        self.clipboard.found.connect(self.paste_link, Qt.QueuedConnection)
        self._last_clip = None  # 處理過的剪貼簿內容：同一段只處理一次
        self._toast_timer = QTimer(self)
        self._toast_timer.setSingleShot(True)
        self._toast_timer.timeout.connect(self.banner.hide)
        self._meta_timer = QTimer(self)  # 每 30 分鐘看一次 yt-dlp 有沒有新版（引擎在背景下載）
        self._meta_timer.timeout.connect(self.check_meta)
        self.go(0)

    @staticmethod
    def _banner(error: bool = False) -> QLabel:
        b = label("", "banner", wrap=True, plain=True)
        b.setProperty("error", error)
        b.hide()
        return b

    def start(self):
        """視窗顯示後開始和引擎溝通：確認引擎已啟動、開始更新下載佇列。"""
        self.queue.start()
        self.check_engine()
        self._meta_timer.start(30 * 60 * 1000)
        if auto_paste_enabled():
            ClipboardWatcher.warm_up()
        QTimer.singleShot(300, self.check_clipboard)  # 開啟時剪貼簿裡已經有影片連結：直接貼上

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
        """貼上並解析。正在解析、已經是這個網址、或使用者正在輸入別的網址時不動作。"""
        page = self.download
        current = page.url.text().strip()
        if url == current or not page.analyze_btn.isEnabled():
            return
        if current and current != page._analyzed_url:  # 欄位裡是使用者打到一半、還沒解析的網址：不要蓋掉
            return
        self.go(0)
        page.url.setText(url)
        page.analyze()
        self.toast("已自動貼上剪貼簿裡的影片連結（可在「設定」關閉）")

    def check_engine(self, attempt: int = 0):
        """引擎剛啟動可能還沒開始聽連接埠：最多等 15 秒；連不上或對方不是引擎就顯示原因。"""
        def ok(m):
            if not isinstance(m, dict) or "version" not in m:
                return fail(NOT_ENGINE, final=True)
            self.engine_banner.hide()
            self.settings.on_meta(m)
            if m.get("just_updated"):
                self.toast(f"yt-dlp 已更新至 {m.get('version')}")

        def fail(msg, final=False):
            if not final and attempt < 30:
                QTimer.singleShot(500, lambda: self.check_engine(attempt + 1))
                return
            self.engine_banner.setText(f"無法連到下載引擎：{msg}。{self.engine_hint}".rstrip("。") + "。")
            self.engine_banner.show()

        self.api.get("/api/meta", ok, fail, timeout_ms=30_000)

    def check_meta(self):
        self.api.get("/api/meta", self.settings.on_meta, timeout_ms=30_000)

    def on_meta(self, m: dict):
        self.nav[2].setText("設定　有更新" if SettingsPage.update_available(m) else "設定")

    def on_online(self, ok: bool, msg: str):
        if ok:  # 佇列拿到引擎的工作清單：引擎正常
            self.engine_banner.hide()
            return
        self.engine_banner.setText(f"與下載引擎的連線中斷了（{msg}）。畫面上的進度可能不是最新的。")
        self.engine_banner.show()

    def apply_theme(self, t: dict[str, str]):
        for b in self.nav:
            b.setIcon(symbol(b._sym, t["accent"]))
        self.download.apply_theme(t)

    def go(self, i: int):
        self.nav[i].setChecked(True)
        self.stack.setCurrentIndex(i)
        self.toolbar.set_title(PAGES[i][0], PAGES[i][2])
        if i == 2:
            self.settings.refresh()

    def on_counts(self, active: int):
        self.nav[1].setText(f"下載佇列　{active}" if active else "下載佇列")
        self.engine.setText(f"{active} 個下載進行中" if active else "")

    def toast(self, text: str, error: bool = False):
        self.banner.setProperty("error", error)
        self.banner.style().unpolish(self.banner)
        self.banner.style().polish(self.banner)
        self.banner.setText(text)
        self.banner.show()
        self._toast_timer.start(6000 if error else 3500)

    def closeEvent(self, e):
        if self.busy():
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Question)
            box.setWindowTitle(TITLE)
            box.setText("要關閉 YT 下載器嗎？")
            box.setInformativeText("還有下載正在進行。關閉後工作會暫停，下次開啟時按「繼續下載」就能接著下載。")
            quit_btn = box.addButton("關閉", QMessageBox.DestructiveRole)
            box.setDefaultButton(box.addButton("取消", QMessageBox.RejectRole))
            box.exec()
            if box.clickedButton() is not quit_btn:
                e.ignore()
                return
        e.accept()


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
            subprocess.Popen(cmd, env=env, cwd=str(cwd))


def main():
    import app_boot
    server = app_boot.boot()  # --check-ytdlp / --server 在這裡處理並結束；沒有主控台時輸出寫到 engine.log
    app, chevron = create_app()
    restarter = Restarter(app)
    server.RESTART_HANDLER = restarter
    url, busy = app_boot.start_engine(server)
    hint = (f"連接埠 {server.PORT} 可能被其他程式佔用，請關閉佔用的程式後重新開啟 App，"
            f"或查看紀錄檔 {server.ROOT / 'engine.log'}")
    win = MainWindow(Api(url, app), busy, hint)
    mac_window_setup(win)
    app.styleHints().colorSchemeChanged.connect(lambda *_: apply_theme(app, win, chevron))
    win.settings.appearance_changed.connect(lambda: apply_appearance(app, win, chevron))
    apply_appearance(app, win, chevron)  # 套用上次選的主題與文字大小
    # 第一次開啟：先同意免責聲明，按「離開」就結束。要在 win.show() 之前：
    # 視窗一顯示就會檢查剪貼簿、自動貼上並解析連結，不能在使用者同意前就送出請求
    require_disclaimer(app, win)
    win.show()
    win.start()
    app_boot.install_smoke_test(app)  # --smoke-test：CI 確認視窗能開啟後自動結束
    code = app.exec()
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
    import shiboken6
    shiboken6.delete(win)
    shiboken6.delete(app)


if __name__ == "__main__":
    # 以 native_app 模組身分執行：native_options / native_playlist 會 import native_app，
    # 直接用 __main__ 執行的話會載入第二份模組（兩套全域狀態）
    import native_app
    native_app.main()
