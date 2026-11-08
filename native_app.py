"""YT 下載器原生介面（Qt / PySide6），外觀參照 macOS。

介面直接用系統元件繪製（不是網頁），同一個程序在背景執行原本的下載引擎（server.py）。
介面透過引擎的本機 API 操作，所以下載、續傳、合併進度、yt-dlp 自動更新都和網頁版共用同一套引擎。

    python native_app.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from PySide6.QtCore import QByteArray, QObject, QPointF, QRectF, QSettings, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QFont,
    QGuiApplication,
    QIcon,
    QPainter,
    QPainterPath,
    QPalette,
    QPen,
    QPixmap,
)
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ytdlp_update import vtuple

TITLE = "YT 下載器"
IS_MAC = sys.platform == "darwin"
FILE_MANAGER = "Finder" if IS_MAC else "檔案總管"
BUNDLE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))  # 打包版的資源在 _MEIPASS
VIBRANCY = False  # macOS 毛玻璃側邊欄是否啟用（mac_window_setup 成功時設為 True）
SETTINGS_ORG, SETTINGS_APP = "YTDownloader", "NativeApp"

MODES = [("av", "影片＋音訊"), ("video", "僅影片"), ("audio", "僅音訊"), ("subs", "字幕"), ("thumb", "縮圖")]
QUALITIES = [(2160, "4K"), (1440, "1440p"), (1080, "1080p"), (720, "720p"), (480, "480p"), (360, "360p")]
CONTAINERS = [("mp4", "MP4"), ("mkv", "MKV"), ("webm", "WebM"), ("mov", "MOV")]
AUDIO_CODECS = [("mp3", "MP3"), ("m4a", "M4A"), ("opus", "Opus"), ("flac", "FLAC（無損）"), ("wav", "WAV（無損）"),
                ("best", "原始格式（不轉檔）")]
AUDIO_QUALITY = [("0", "最佳"), ("320k", "320 kbps"), ("256k", "256 kbps"), ("192k", "192 kbps"), ("128k", "128 kbps")]
STATUS_TEXT = {"queued": "排隊中", "downloading": "下載中", "processing": "處理中", "done": "已完成",
               "error": "失敗", "cancelled": "已取消"}
ACTIVE = ("queued", "downloading", "processing")  # 和 server.ACTIVE 相同（有測試確認）


# --------------------------------------------------------------------------- #
#  外觀：Apple 人機介面指南的系統色
# --------------------------------------------------------------------------- #
def tokens(dark: bool) -> dict[str, str]:
    """Apple 人機介面指南的系統色（macOS 淺色 / 深色外觀）。

    半透明色用 #AARRGGBB：QSS 和 QColor 都看得懂，自己畫的元件可以直接 QColor(t[...])。
    """
    if dark:
        return {"bg": "#1E1E1E", "sidebar": "#2A2A2C", "toolbar": "#1E1E1E", "card": "#2A2A2C", "field": "#1E1E1E",
                "text": "#FFFFFF", "secondary": "#98989D", "tertiary": "#636366", "sep": "#17FFFFFF",
                "border": "#29FFFFFF", "accent": "#0A84FF", "accent_hover": "#3A99FF", "accent_text": "#FFFFFF",
                "select": "#1AFFFFFF", "seg": "#14FFFFFF", "seg_on": "#636366", "track": "#1FFFFFFF",
                "red": "#FF453A", "green": "#30D158", "orange": "#FF9F0A", "hover": "#0FFFFFFF",
                "button": "#555558", "button_border": "#1AFFFFFF", "button_shadow": "#73000000",
                "button_pressed": "#68686C", "focus": "#8C0A84FF"}
    return {"bg": "#F5F5F7", "sidebar": "#EAEAEC", "toolbar": "#F5F5F7", "card": "#FFFFFF", "field": "#FFFFFF",
            "text": "#1D1D1F", "secondary": "#86868B", "tertiary": "#B0B0B5", "sep": "#17000000",
            "border": "#21000000", "accent": "#007AFF", "accent_hover": "#0068E0", "accent_text": "#FFFFFF",
            "select": "#14000000", "seg": "#0F000000", "seg_on": "#FFFFFF", "track": "#14000000",
            "red": "#FF3B30", "green": "#28CD41", "orange": "#FF9500", "hover": "#0A000000",
            "button": "#FFFFFF", "button_border": "#1C000000", "button_shadow": "#33000000",
            "button_pressed": "#EDEDED", "focus": "#80007AFF"}


def ui_font() -> QFont:
    """macOS：系統字型（SF Pro + 蘋方）13 pt。Windows：Segoe UI Variable + 微軟正黑體，換算成同樣的 13 px 視覺大小。"""
    f = QFont()
    if IS_MAC:
        f.setPointSizeF(13)
    else:
        f.setFamilies(["Segoe UI Variable Text", "Segoe UI", "Microsoft JhengHei UI", "Microsoft JhengHei"])
        f.setPixelSize(13)
    return f


def _controls_qss(t: dict[str, str], chevron: str) -> str:
    """Windows 用：把按鈕、彈出選單、輸入框、進度條畫成 macOS 的樣子。macOS 上改用系統原生元件，不套這段。"""
    return f"""
    QLineEdit {{ background: {t['field']}; border: 1px solid {t['border']}; border-radius: 6px;
                 padding: 4px 8px; min-height: 18px; selection-background-color: {t['accent']}; }}
    QLineEdit:focus {{ border: 2px solid {t['focus']}; padding: 3px 7px; }}
    QPushButton {{ background: {t['button']}; border: 1px solid {t['button_border']};
                   border-bottom: 1px solid {t['button_shadow']}; border-radius: 6px; padding: 3px 12px;
                   min-height: 18px; }}
    QPushButton:pressed {{ background: {t['button_pressed']}; }}
    QPushButton:disabled {{ color: {t['tertiary']}; }}
    #primary {{ background: {t['accent']}; color: {t['accent_text']}; border: 1px solid {t['accent']};
                border-bottom: 1px solid {t['accent_hover']}; padding: 3px 16px; }}
    #primary:pressed {{ background: {t['accent_hover']}; }}
    #primary:disabled {{ background: {t['track']}; color: {t['tertiary']}; border-color: transparent; }}
    QComboBox {{ background: {t['button']}; border: 1px solid {t['button_border']};
                 border-bottom: 1px solid {t['button_shadow']}; border-radius: 6px;
                 padding: 3px 26px 3px 9px; min-height: 18px; min-width: 96px; }}
    QComboBox::drop-down {{ subcontrol-origin: padding; subcontrol-position: center right; width: 16px; height: 16px;
                 margin-right: 3px; border: none; border-radius: 4px; background: {t['accent']}; }}
    QComboBox::down-arrow {{ image: url("{chevron}"); width: 10px; height: 10px; }}
    QComboBox QAbstractItemView {{ background: {t['card']}; border: 1px solid {t['border']}; padding: 5px;
                 selection-background-color: {t['accent']}; selection-color: white; outline: none; }}
    QProgressBar {{ background: {t['track']}; border: none; border-radius: 2px; max-height: 4px; min-height: 4px; }}
    QProgressBar::chunk {{ background: {t['accent']}; border-radius: 2px; }}
    QProgressBar[state="done"]::chunk {{ background: {t['green']}; }}
    QProgressBar[state="error"]::chunk {{ background: {t['orange']}; }}
    QScrollBar:vertical {{ background: transparent; width: 11px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {t['tertiary']}; border-radius: 3px; min-height: 30px; margin: 0 2px; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
    """


def stylesheet(t: dict[str, str], chevron: str) -> str:
    """版面與容器的樣式（兩個平台都用）；Windows 再加上模仿 macOS 的控制項樣式。"""
    base = f"""
    #content {{ background: {t['bg']}; }}
    QLabel {{ background: transparent; }}
    #sidebar {{ background: {"transparent" if VIBRANCY else t['sidebar']}; border-right: 1px solid {t['sep']}; }}
    #navButton {{ text-align: left; padding: 4px 8px; border: none; border-radius: 6px; background: transparent;
                  min-height: 20px; }}
    #navButton:checked {{ background: {t['select']}; }}
    #toolbar {{ background: {t['toolbar']}; border-bottom: 1px solid {t['sep']}; }}
    #toolbarTitle {{ font-size: 15px; font-weight: 700; }}
    #toolbarSubtitle {{ color: {t['secondary']}; font-size: 11px; }}
    #subtitle {{ color: {t['secondary']}; }}
    #errorText {{ color: {t['red']}; }}
    #sectionHeader {{ font-weight: 700; padding-left: 2px; }}
    #card {{ background: {t['card']}; border: 1px solid {t['sep']}; border-radius: 10px; }}
    #row {{ background: transparent; }}
    #hairline {{ background: {t['sep']}; max-height: 1px; min-height: 1px; border: none; }}
    #videoTitle {{ font-size: 15px; font-weight: 600; }}
    #rowTitle {{ font-weight: 600; }}
    #link {{ background: transparent; border: none; color: {t['accent']}; padding: 0 2px; min-height: 0; }}
    #destructiveLink {{ background: transparent; border: none; color: {t['red']}; padding: 0 2px; min-height: 0; }}
    #segmented {{ background: {t['seg']}; border-radius: 7px; }}
    #segment {{ background: transparent; border: none; border-radius: 5px; padding: 2px 12px; min-height: 18px; }}
    #segment:checked {{ background: {t['seg_on']}; border: 1px solid {t['button_border']};
                        border-bottom: 1px solid {t['button_shadow']}; }}
    QScrollArea {{ background: transparent; border: none; }}
    #banner {{ background: {t['card']}; border: 1px solid {t['sep']}; border-radius: 8px; padding: 8px 12px;
               color: {t['text']}; }}
    #banner[error="true"] {{ color: {t['red']}; }}
    """
    return base if IS_MAC else base + _controls_qss(t, chevron)


def symbol(name: str, color: str, size: int = 36) -> QIcon:
    """側邊欄用的線條圖示（類似 SF Symbols）。"""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(color), size / 13, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    s = size
    if name == "download":
        p.drawEllipse(QRectF(s * .12, s * .12, s * .76, s * .76))
        p.drawLine(QPointF(s * .5, s * .3), QPointF(s * .5, s * .66))
        p.drawPolyline([QPointF(s * .36, s * .53), QPointF(s * .5, s * .67), QPointF(s * .64, s * .53)])
    elif name == "list":
        for y in (.3, .5, .7):
            p.drawPoint(QPointF(s * .2, s * y))
            p.drawLine(QPointF(s * .34, s * y), QPointF(s * .82, s * y))
    elif name == "gear":
        p.drawEllipse(QRectF(s * .36, s * .36, s * .28, s * .28))
        path = QPainterPath()
        import math
        for i in range(16):
            r = s * (.38 if i % 2 == 0 else .3)
            a = math.pi * 2 * i / 16
            pt = QPointF(s * .5 + r * math.cos(a), s * .5 + r * math.sin(a))
            path.moveTo(pt) if i == 0 else path.lineTo(pt)
        path.closeSubpath()
        p.drawPath(path)
    p.end()
    return QIcon(pm)


def rounded(pm: QPixmap, w: int, h: int, radius: float) -> QPixmap:
    """縮圖裁成圓角（cover 填滿）。"""
    dpr = 2.0
    out = QPixmap(int(w * dpr), int(h * dpr))
    out.setDevicePixelRatio(dpr)
    out.fill(Qt.transparent)
    scaled = pm.scaled(int(w * dpr), int(h * dpr), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    scaled.setDevicePixelRatio(dpr)
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, w, h), radius, radius)
    p.setClipPath(path)
    p.drawPixmap(QPointF((w - scaled.width() / dpr) / 2, (h - scaled.height() / dpr) / 2), scaled)
    p.end()
    return out


def fmt_bytes(n) -> str:
    if not n:
        return ""
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024
    return ""


def fmt_duration(sec) -> str:
    if not sec:
        return ""
    sec = int(sec)
    h, m, s = sec // 3600, sec % 3600 // 60, sec % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def fmt_eta(sec) -> str:
    if sec is None:
        return ""
    sec = int(sec)
    if sec >= 3600:
        return f"剩 {sec // 3600} 小時 {sec % 3600 // 60} 分"
    if sec >= 60:
        return f"剩 {sec // 60} 分 {sec % 60} 秒"
    return f"剩 {sec} 秒"


def newer(latest: str | None, current: str | None) -> bool:
    """latest 是否比 current 新。用數字比較：PyPI 的 2026.9.5 和 yt-dlp 的 2026.09.05 是同一版。"""
    return bool(latest) and vtuple(latest) > vtuple(current)


# --------------------------------------------------------------------------- #
#  引擎 API
# --------------------------------------------------------------------------- #
NOT_ENGINE = "下載引擎沒有正確回應（連接埠可能被其他程式佔用）"


class Api:
    """非同步呼叫本機引擎（QNetworkAccessManager，不會卡住介面）。

    ok(payload) 只會收到 JSON；HTTP 錯誤、引擎回的 {"error": …}、不是 JSON 的回應都走 err(訊息)。
    timeout_ms=0 表示不限時間（例如解析很大的播放清單）。
    """

    def __init__(self, base: str, parent: QObject | None = None):
        self.base = base
        self.net = QNetworkAccessManager(parent)  # 掛在 QApplication 底下，關閉時一起釋放

    def _send(self, method: str, path: str, body, ok, err, timeout_ms: int):
        req = QNetworkRequest(QUrl(self.base + path))
        req.setTransferTimeout(timeout_ms)
        req.setHeader(QNetworkRequest.ContentTypeHeader, "application/json")
        data = QByteArray(json.dumps(body or {}).encode()) if method in ("POST", "DELETE") else None
        reply = self.net.sendCustomRequest(req, method.encode(), data) if data is not None else self.net.get(req)

        def done():
            raw = bytes(reply.readAll())
            failed = reply.error() != QNetworkReply.NoError
            message = reply.errorString()
            reply.deleteLater()
            try:
                payload = json.loads(raw) if raw else None
            except ValueError:
                payload = None
            if isinstance(payload, dict) and payload.get("error"):
                err and err(str(payload["error"]))
            elif failed:
                err and err(message)
            elif payload is None:
                err and err(NOT_ENGINE)
            else:
                ok and ok(payload)

        reply.finished.connect(done)
        return reply

    def get(self, path, ok=None, err=None, timeout_ms=10_000):
        return self._send("GET", path, None, ok, err, timeout_ms)

    def post(self, path, body=None, ok=None, err=None, timeout_ms=10_000):
        return self._send("POST", path, body, ok, err, timeout_ms)

    def delete(self, path, ok=None, err=None, timeout_ms=10_000):
        return self._send("DELETE", path, {}, ok, err, timeout_ms)

    def image(self, url: str, ok, timeout_ms: int = 20_000) -> QNetworkReply:
        """下載圖片，完成時呼叫 ok(QPixmap)（失敗或取消時是空的 QPixmap）。回傳 reply，可以 abort()。"""
        req = QNetworkRequest(QUrl(url))
        req.setTransferTimeout(timeout_ms)  # 卡住的縮圖不能一直佔著連線（播放清單同時最多載入 6 張）
        reply = self.net.get(req)

        def done():
            pm = QPixmap()
            if reply.error() == QNetworkReply.NoError:
                pm.loadFromData(bytes(reply.readAll()))
            reply.deleteLater()
            ok(pm)

        reply.finished.connect(done)
        return reply


# --------------------------------------------------------------------------- #
#  元件
# --------------------------------------------------------------------------- #
def label(text: str = "", name: str | None = None, wrap: bool = False, plain: bool = False) -> QLabel:
    """plain=True：一律當純文字顯示（影片標題這類外來文字可能含 < 或 &，不能被當成 HTML）。"""
    lb = QLabel(text)
    if name:
        lb.setObjectName(name)
    lb.setWordWrap(wrap)
    if plain:
        lb.setTextFormat(Qt.PlainText)
    return lb


class ElidedLabel(QLabel):
    """單行文字太長時中間以「…」省略，跟著目前寬度調整，不會把版面撐寬。full_text() 取得完整文字。"""

    def __init__(self, name: str | None = None):
        super().__init__()
        if name:
            self.setObjectName(name)
        self.setTextFormat(Qt.PlainText)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self._full = ""

    def set_full_text(self, text: str):
        self._full = text
        self.setToolTip(text)
        self._elide()

    def full_text(self) -> str:
        return self._full

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._elide()

    def _elide(self):
        self.setText(self.fontMetrics().elidedText(self._full, Qt.ElideMiddle, max(self.width(), 40)))


def hairline() -> QFrame:
    f = QFrame()
    f.setObjectName("hairline")
    return f


class Segmented(QFrame):
    """macOS 分段控制。"""
    changed = Signal(str)

    def __init__(self, items: list[tuple[str, str]]):
        super().__init__()
        self.setObjectName("segmented")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(2)
        self.group = QButtonGroup(self)
        self.buttons: dict[str, QPushButton] = {}
        for key, text in items:
            b = QPushButton(text)
            b.setObjectName("segment")
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, k=key: self.changed.emit(k))
            self.group.addButton(b)
            self.buttons[key] = b
            lay.addWidget(b)
        self.set_value(items[0][0])
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)

    def set_value(self, key: str):
        self.buttons[key].setChecked(True)

    def value(self) -> str:
        return next(k for k, b in self.buttons.items() if b.isChecked())


class PopUp(QComboBox):
    def __init__(self, items: list[tuple[object, str]] = ()):
        super().__init__()
        self.set_items(items)

    def set_items(self, items, prefer=None):
        """換選項；盡量保留原本選的值，沒有原本的值時改選 prefer，都沒有就選第一項。"""
        current = self.currentData()
        self.blockSignals(True)
        self.clear()
        for value, text in items:
            self.addItem(text, value)
        for want in (current, prefer):
            idx = self.findData(want) if want is not None else -1
            if idx >= 0:
                break
        self.setCurrentIndex(max(idx, 0))
        self.blockSignals(False)

    def select(self, value) -> bool:
        idx = self.findData(value)
        if idx >= 0:
            self.setCurrentIndex(idx)
        return idx >= 0


def form_row(title: str, widget: QWidget) -> QWidget:
    w = QWidget()
    w.setObjectName("row")
    lay = QHBoxLayout(w)
    lay.setContentsMargins(14, 7, 14, 7)
    lay.addWidget(label(title))
    lay.addStretch()
    lay.addWidget(widget)
    return w


class Card(QFrame):
    """iOS / macOS 設定畫面那種圓角分組：一列一列，中間細線分隔。

    分隔線由 Card 自己管理：只有前面還有看得到的列時才顯示（第一列上方、隱藏的列都不畫線）。
    """

    def __init__(self):
        super().__init__()
        self.setObjectName("card")
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(0)
        self.rows: list[QWidget] = []
        self._lines: dict[QWidget, QWidget] = {}

    @staticmethod
    def _separator() -> QWidget:
        holder = QWidget()
        hl = QHBoxLayout(holder)
        hl.setContentsMargins(14, 0, 0, 0)
        hl.addWidget(hairline())
        return holder

    def add(self, widget: QWidget) -> QWidget:
        line = self._lines[widget] = self._separator()
        self.lay.addWidget(line)
        self.lay.addWidget(widget)
        self.rows.append(widget)
        self._update_lines()
        return widget

    def set_row_visible(self, widget: QWidget, visible: bool):
        widget.setVisible(visible)
        self._update_lines()

    def set_rows(self, rows: list[QWidget]):
        """依新的順序重排列；不在新清單裡的列會被刪除，已經在的列直接搬動、不重建。"""
        self.setUpdatesEnabled(False)
        while self.lay.count():
            self.lay.takeAt(0)
        keep = set(rows)
        for r in self.rows:
            if r not in keep:
                self._lines.pop(r).deleteLater()
                r.deleteLater()
        self.rows = []
        for r in rows:
            if r not in self._lines:
                self._lines[r] = self._separator()
            self.lay.addWidget(self._lines[r])
            self.lay.addWidget(r)
            self.rows.append(r)
        self._update_lines()
        self.setUpdatesEnabled(True)

    def _update_lines(self):
        seen = False
        for r in self.rows:
            shown = not r.isHidden()
            self._lines[r].setVisible(shown and seen)
            seen = seen or shown


def page_scroll(inner: QWidget) -> QScrollArea:
    sc = QScrollArea()
    sc.setWidgetResizable(True)
    sc.setFrameShape(QFrame.NoFrame)
    sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)  # 內容跟著視窗寬度縮放，不左右捲動
    sc.setWidget(inner)
    inner.setObjectName("content")
    return sc


def page_layout(page: QWidget) -> QVBoxLayout:
    """在 page 裡放一個可上下捲動的內容區，回傳內容區的版面（標題顯示在主視窗的工具列）。"""
    inner = QWidget()
    lay = QVBoxLayout(inner)
    lay.setContentsMargins(28, 20, 28, 24)
    lay.setSpacing(10)
    outer = QVBoxLayout(page)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.addWidget(page_scroll(inner))
    return lay


def settings_store() -> QSettings:
    return QSettings(SETTINGS_ORG, SETTINGS_APP)


# --------------------------------------------------------------------------- #
#  頁面：新增下載
# --------------------------------------------------------------------------- #
class DownloadPage(QWidget):
    queued = Signal()
    PREFS = "basic"  # QSettings 群組：模式、畫質、格式等基本選項，下次開啟沿用

    def __init__(self, api: Api, toast):
        super().__init__()
        from native_options import AdvancedOptions, Switch
        from native_playlist import PlaylistView
        self.api, self.toast, self.info = api, toast, None
        self._request = 0
        self._analyzed_url = ""
        lay = page_layout(self)

        bar = QHBoxLayout()
        self.url = QLineEdit()
        self.url.setPlaceholderText("https://www.youtube.com/watch?v=…")
        self.url.setClearButtonEnabled(True)
        self.url.returnPressed.connect(self.analyze)
        self.analyze_btn = QPushButton("解析")
        self.analyze_btn.setObjectName("primary")
        self.analyze_btn.clicked.connect(self.analyze)
        paste = QPushButton("貼上")
        paste.clicked.connect(self.paste)
        bar.addWidget(self.url, 1)
        bar.addWidget(paste)
        bar.addWidget(self.analyze_btn)
        lay.addLayout(bar)

        # 和網頁版一樣一律顯示：哪些網址算播放清單由 yt-dlp 依網站判斷（YouTube、Bilibili 分 P…）
        list_row = QHBoxLayout()
        list_row.setContentsMargins(2, 0, 0, 0)
        self.as_playlist = Switch(False)
        self.as_playlist.toggled.connect(self._playlist_toggled)
        list_row.addWidget(self.as_playlist)
        list_row.addWidget(label("網址含播放清單時，下載整個清單", "subtitle"))
        list_row.addStretch()
        lay.addLayout(list_row)

        self.status = label("", "subtitle", wrap=True, plain=True)
        self.status.hide()
        lay.addWidget(self.status)

        # 影片資訊
        self.video = QFrame()
        self.video.setObjectName("card")
        vl = QHBoxLayout(self.video)
        vl.setContentsMargins(12, 12, 14, 12)
        vl.setSpacing(14)
        self.thumb = QLabel()
        self.thumb.setFixedSize(192, 108)
        vl.addWidget(self.thumb)
        meta = QVBoxLayout()
        meta.setSpacing(6)
        self.title = label("", "videoTitle", wrap=True, plain=True)
        self.uploader = label("", "subtitle", plain=True)
        self.details = label("", "subtitle", wrap=True, plain=True)
        meta.addWidget(self.title)
        meta.addWidget(self.uploader)
        meta.addWidget(self.details)
        meta.addStretch()
        vl.addLayout(meta, 1)
        lay.addWidget(self.video)

        # 播放清單（解析到播放清單時取代影片資訊卡）
        self.playlist = PlaylistView(image_loader=api.image)
        self.playlist.selectionChanged.connect(self.update_summary)
        self.playlist.hide()
        lay.addWidget(self.playlist)

        # 下載選項
        self.opts_header = label("下載選項", "sectionHeader")
        lay.addSpacing(6)
        lay.addWidget(self.opts_header)
        self.mode = Segmented(MODES)
        self.mode.changed.connect(self.update_rows)
        mode_holder = QHBoxLayout()
        mode_holder.addWidget(self.mode)
        mode_holder.addStretch()
        lay.addLayout(mode_holder)

        self.card = Card()
        self.quality = PopUp()
        self.container = PopUp(CONTAINERS)
        self.acodec = PopUp(AUDIO_CODECS)
        self.aquality = PopUp(AUDIO_QUALITY)
        self.r_quality = self.card.add(form_row("畫質", self.quality))
        self.r_container = self.card.add(form_row("檔案格式", self.container))
        self.r_acodec = self.card.add(form_row("音訊格式", self.acodec))
        self.r_aquality = self.card.add(form_row("音質", self.aquality))
        lay.addWidget(self.card)

        # 進階選項：音軌、字幕、剪輯、SponsorBlock、中繼資料、網路
        self.advanced = AdvancedOptions(api, toast)
        self.advanced.changed.connect(self.update_summary)
        lay.addWidget(self.advanced)

        foot = QHBoxLayout()
        self.summary = label("", "subtitle", plain=True)
        foot.addWidget(self.summary, 1)
        self.download_btn = QPushButton("下載")
        self.download_btn.setObjectName("primary")
        self.download_btn.clicked.connect(self.download)
        foot.addWidget(self.download_btn)
        lay.addLayout(foot)
        lay.addStretch()

        self._saved_quality = None
        self.restore_prefs()
        for w in (self.quality, self.container, self.acodec, self.aquality):
            w.currentIndexChanged.connect(self.update_rows)
        self.mode.changed.connect(self.save_prefs)
        for w in (self.quality, self.container, self.acodec, self.aquality):
            w.currentIndexChanged.connect(self.save_prefs)
        self.as_playlist.toggled.connect(self.save_prefs)
        self.set_loaded(False)

    # ---------- 基本選項的儲存 ----------
    def restore_prefs(self):
        st = settings_store()
        st.beginGroup(self.PREFS)
        mode = st.value("mode", "av")
        if mode in self.mode.buttons:
            self.mode.set_value(mode)
        self.container.select(st.value("container", "mp4"))
        self.acodec.select(st.value("acodec", "mp3"))
        self.aquality.select(st.value("aquality", "0"))
        q = st.value("quality", "")
        self._saved_quality = int(q) if str(q).isdigit() else None
        pl = st.value("as_playlist", False)
        self.as_playlist.blockSignals(True)
        self.as_playlist.setChecked(pl.lower() == "true" if isinstance(pl, str) else bool(pl))
        self.as_playlist.blockSignals(False)
        st.endGroup()

    def save_prefs(self, *_):
        if self.quality.count():  # 還沒解析過時畫質選單是空的，不要蓋掉上次的選擇
            self._saved_quality = self.quality.currentData()
        st = settings_store()
        st.beginGroup(self.PREFS)
        st.setValue("mode", self.mode.value())
        st.setValue("quality", self._saved_quality or "")
        st.setValue("container", self.container.currentData())
        st.setValue("acodec", self.acodec.currentData())
        st.setValue("aquality", self.aquality.currentData())
        st.setValue("as_playlist", self.as_playlist.isChecked())
        st.endGroup()

    def apply_theme(self, t: dict[str, str]):
        self.advanced.apply_theme(t)
        self.playlist.apply_theme(t)

    def set_status(self, text: str, error: bool = False):
        self.status.setObjectName("errorText" if error else "subtitle")
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)
        self.status.setText(text)
        self.status.setVisible(bool(text))

    def _playlist_toggled(self, *_):
        # 解析後才切換：用新的設定重新解析，避免畫面顯示單一影片、實際卻要下載整個清單（或相反）
        if self._analyzed_url and self.url.text().strip() == self._analyzed_url:
            self.analyze()

    def paste(self):
        self.url.setText(QGuiApplication.clipboard().text().strip())
        self.analyze()

    def is_playlist(self) -> bool:
        return bool(self.info) and self.info.get("type") == "playlist"

    def set_loaded(self, loaded: bool):
        for w in (self.opts_header, self.mode, self.card, self.advanced, self.download_btn, self.summary):
            w.setVisible(loaded)
        self.video.setVisible(loaded and not self.is_playlist())
        self.playlist.setVisible(loaded and self.is_playlist())
        # macOS 的原生按鈕只有「預設按鈕」是藍色：解析前是「解析」，解析後換成「下載」
        self.analyze_btn.setDefault(not loaded)
        self.download_btn.setDefault(loaded)

    def analyze(self):
        url = self.url.text().strip()
        if not url:
            self.url.setFocus()
            return
        self.analyze_btn.setEnabled(False)
        self.analyze_btn.setText("解析中…")
        self.set_status("正在讀取影片資訊，可能需要幾秒鐘；很長的播放清單會需要比較久…")
        self.info = None
        self._analyzed_url = url
        self.set_loaded(False)
        # 解析中又按 Enter 會再送一次：只採用最後一次的結果，先送出但較慢回來的舊結果直接丟掉
        self._request += 1
        req = self._request
        body = {"url": url, "noplaylist": not self.as_playlist.isChecked(), "network": self.advanced.network()}
        # 不限時間：大型播放清單、頻道可能要解析好幾分鐘（網頁版也不限）
        self.api.post("/api/info", body, lambda info: req == self._request and self.on_info(info),
                      lambda msg: req == self._request and self.on_info_error(msg), timeout_ms=0)

    def _reset_button(self):
        self.analyze_btn.setEnabled(True)
        self.analyze_btn.setText("解析")

    def on_info_error(self, msg: str):
        self._reset_button()
        self.set_status(f"無法解析：{msg}", error=True)

    def on_info(self, info: dict):
        req = self._request
        self._reset_button()
        self.set_status("")
        self.info = info
        if info.get("type") == "playlist":
            self.playlist.set_playlist(info)
            heights = []
        else:
            self.title.setText(info.get("title") or "")
            self.uploader.setText(info.get("uploader") or "")
            heights = info.get("heights") or []
            bits = [fmt_duration(info.get("duration"))]
            if heights:
                bits.append(f"最高 {heights[0]}p")
            if info.get("view_count"):
                bits.append(f"{info['view_count']:,} 次觀看")
            if info.get("extractor"):
                bits.append(info["extractor"])
            self.details.setText(" · ".join(b for b in bits if b))
            self.thumb.setPixmap(QPixmap())
            if info.get("thumbnail"):
                self.api.image(info["thumbnail"], lambda pm: pm.isNull() or req != self._request
                               or self.thumb.setPixmap(rounded(pm, 192, 108, 8)))
        # 播放清單沒有各部影片的畫質資訊，列出全部（超過來源畫質時 yt-dlp 會自動選最接近的）
        self.quality.set_items([(None, "最佳畫質")] + [(h, name) for h, name in QUALITIES
                                                      if not heights or h <= heights[0]],
                               prefer=self._saved_quality)
        self.advanced.set_info(info)
        self.set_loaded(True)
        self.update_rows()

    def update_rows(self, *_):
        m = self.mode.value()
        video = m in ("av", "video")
        self.card.set_row_visible(self.r_quality, video)
        self.card.set_row_visible(self.r_container, video)
        self.card.set_row_visible(self.r_acodec, m == "audio")
        self.card.set_row_visible(self.r_aquality, m == "audio" and self.acodec.currentData() not in ("flac", "wav", "best"))
        self.card.setVisible(bool(self.info) and m in ("av", "video", "audio"))
        self.advanced.set_mode(m)
        self.update_summary()

    def options(self) -> dict:
        """基本選項；進階面板的設定由 AdvancedOptions.apply() 合併進來。"""
        o = {
            "mode": self.mode.value(),
            "video": {"max_height": self.quality.currentData() or "", "container": self.container.currentData()},
            "audio": {"languages": [], "codec": self.acodec.currentData(), "quality": self.aquality.currentData()},
            "subs": {"languages": [], "auto_languages": []},
        }
        o = self.advanced.apply(o)
        if self.is_playlist():
            o["playlist"] = True
            o["playlist_items"] = self.playlist.playlist_items()
        return o

    def problem(self) -> str:
        """目前選項不能送出的原因（空字串表示可以下載）。"""
        if not self.info:
            return "請先解析網址"
        if self.is_playlist() and self.playlist.selected_count() == 0:
            # playlist_items 為空時引擎會下載整個清單，所以一定要擋下來
            return "請至少選擇一部影片"
        mode = self.mode.value()
        if mode == "subs":
            s = self.advanced.apply({"mode": mode, "subs": {"languages": [], "auto_languages": []}})["subs"]
            if not (s.get("languages") or s.get("auto_languages") or s.get("all")):
                return "請在「字幕」選擇至少一種語言"
        if mode in ("av", "video", "audio"):  # 時間範圍只有影音模式會用到（其他模式時剪輯分組是隱藏的）
            return self.advanced.error() or ""
        return ""

    def update_summary(self, *_):
        if not self.info:
            return
        m = self.mode.value()
        if m in ("av", "video"):
            text = f"{self.quality.currentText()} · {self.container.currentText()}"
            if m == "video":
                text += " · 不含聲音"
        elif m == "audio":
            text = self.acodec.currentText()
        elif m == "subs":
            text = "只下載字幕"
        else:
            text = "只下載封面圖"
        if self.is_playlist():
            text += f" · {self.playlist.selected_count()} 部影片"
        problem = self.problem()
        self.summary.setText(problem or text)
        self.download_btn.setEnabled(not problem)

    def download(self):
        problem = self.problem()
        if problem:
            self.toast(problem, error=True)
            return
        self.download_btn.setEnabled(False)
        title = self.info.get("title")

        def ok(_):
            self.download_btn.setEnabled(True)
            self.toast(f"已加入下載佇列：{title}")
            self.queued.emit()

        def err(msg):
            self.download_btn.setEnabled(True)
            self.toast(f"無法開始下載：{msg}", error=True)

        self.api.post("/api/download", {"url": self.info.get("webpage_url") or self._analyzed_url,
                                        "title": title, "options": self.options()}, ok, err)


# --------------------------------------------------------------------------- #
#  頁面：下載佇列
# --------------------------------------------------------------------------- #
class JobRow(QWidget):
    def __init__(self, api: Api, on_change, toast=None):
        super().__init__()
        self.setObjectName("row")
        self.api, self.on_change, self.job = api, on_change, {}
        self.toast = toast or (lambda *_a, **_k: None)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(6)
        top = QHBoxLayout()
        self.title = label("", "rowTitle", plain=True)
        self.title.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        top.addWidget(self.title, 1)
        self.buttons = QHBoxLayout()
        self.buttons.setSpacing(6)
        top.addLayout(self.buttons)
        lay.addLayout(top)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        lay.addWidget(self.bar)
        self.detail = label("", "subtitle", wrap=True, plain=True)
        lay.addWidget(self.detail)
        self._actions = None

    def _set_actions(self, actions: list[tuple[str, str, object, str]]):
        key = tuple(a[0] for a in actions)
        if key == self._actions:
            return
        self._actions = key
        while self.buttons.count():
            w = self.buttons.takeAt(0).widget()
            w and w.deleteLater()
        for text, style, fn, tip in actions:
            b = QPushButton(text)
            b.setObjectName(style)
            b.setToolTip(tip)
            b.clicked.connect(fn)
            self.buttons.addWidget(b)

    def _call(self, method: str, path: str, what: str):
        """取消／繼續／刪除：成功立刻刷新清單，失敗顯示原因。"""
        def err(msg):
            self.toast(f"{what}失敗：{msg}", error=True)
            self.on_change()
        if method == "DELETE":
            self.api.delete(path, lambda _r: self.on_change(), err)
        else:
            self.api.post(path, {}, lambda _r: self.on_change(), err)

    def update_job(self, job: dict):
        self.job = job
        st = job.get("status")
        self.title.setText(job.get("title") or job.get("url") or "")
        self.title.setToolTip(job.get("title") or "")
        pct = float(job.get("progress") or 0)
        self.bar.setRange(0, 0 if st == "queued" or (st in ("downloading", "processing") and pct <= 0) else 1000)
        self.bar.setValue(int(pct * 10))
        state = "done" if st == "done" else "error" if st in ("error", "cancelled") else ""
        if self.bar.property("state") != state:
            self.bar.setProperty("state", state)
            self.bar.style().unpolish(self.bar)
            self.bar.style().polish(self.bar)
        self.bar.setVisible(st != "done")

        files = job.get("files") or []
        if st in ("downloading", "processing"):
            parts = [job.get("stage") or STATUS_TEXT[st]]
            if job.get("item"):
                parts.append(f"第 {job['item']} 部")
            parts.append(f"{pct:.1f}%")
            if job.get("total"):
                parts.append(f"{fmt_bytes(job.get('downloaded'))} / {fmt_bytes(job['total'])}")
            if job.get("speed"):
                parts.append(f"{fmt_bytes(job['speed'])}/s")
            parts.append(fmt_eta(job.get("eta")))
            text = " · ".join(p for p in parts if p)
        elif st == "done":
            size = sum(f.get("size") or 0 for f in files)
            text = f"已完成 · {len(files)} 個檔案 · {fmt_bytes(size)}"
        elif st == "error":
            text = job.get("error") or "下載失敗"
        else:
            text = job.get("stage") or STATUS_TEXT.get(st, st or "")
            if files:
                text += f" · 已保留 {len(files)} 個檔案"
        self.detail.setText(text)

        jid = job["id"]
        actions = []
        if st in ACTIVE:
            actions.append(("取消", "destructiveLink", lambda: self._call("POST", f"/api/jobs/{jid}/cancel", "取消"),
                            "停止下載（已下載的部分會保留，可以再繼續）"))
        if st == "error":
            actions.append(("繼續下載", "link", lambda: self._call("POST", f"/api/jobs/{jid}/resume", "繼續下載"),
                            "從中斷處接著下載"))
        if files:  # 已取消、空間不足而中止的工作也可能保留了完成的檔案
            actions.append((f"在{FILE_MANAGER}中顯示", "link", self.reveal, "打開檔案所在的資料夾"))
        if st not in ACTIVE:
            actions.append(("刪除", "destructiveLink", self.remove, "刪除工作與已下載的檔案"))
        self._set_actions(actions)

    def reveal(self):
        files = self.job.get("files") or []
        if not files:
            return
        big = max(files, key=lambda f: f.get("size") or 0)
        self.api.post(f"/api/jobs/{self.job['id']}/reveal", {"name": big["name"]}, None,
                      lambda m: self.toast(f"無法打開資料夾：{m}", error=True))

    def remove(self):
        """刪除工作：引擎會把整個工作資料夾（含下載好的檔案、可續傳的暫存）永久刪除，所以先確認。"""
        job = self.job
        files = job.get("files") or []
        partial = job.get("partial") or 0
        title = job.get("title") or job.get("url") or ""
        if files or partial:
            box = QMessageBox(self.window())
            box.setIcon(QMessageBox.Warning)
            box.setWindowTitle(TITLE)
            box.setText(f"要刪除「{title}」嗎？")
            if files:
                size = fmt_bytes(sum(f.get("size") or 0 for f in files))
                info = f"已下載的 {len(files)} 個檔案（{size}）會從電腦上永久刪除，不會放到資源回收筒，無法復原。"
            else:
                info = f"已下載 {fmt_bytes(partial)} 的暫存資料會一起刪除，之後就無法接著下載。"
            box.setInformativeText(info)
            delete = box.addButton("刪除", QMessageBox.DestructiveRole)
            box.setDefaultButton(box.addButton("取消", QMessageBox.RejectRole))
            box.exec()
            if box.clickedButton() is not delete:
                return
        self._call("DELETE", f"/api/jobs/{job['id']}", "刪除")


class QueuePage(QWidget):
    counts = Signal(int)
    online = Signal(bool, str)  # 和引擎的連線狀態（連續兩次輪詢失敗才算斷線）

    def __init__(self, api: Api, toast=None):
        super().__init__()
        self.api, self.toast = api, toast
        lay = page_layout(self)
        self.empty = label("目前沒有下載。", "subtitle")
        lay.addWidget(self.empty)
        self.card = Card()
        lay.addWidget(self.card)
        lay.addStretch()
        self.rows: dict[str, JobRow] = {}
        self.order: list[str] = []
        self.jobs: list[dict] = []
        self._seq = 0        # 送出的請求編號
        self._applied = 0    # 畫面目前顯示的是哪一次請求的結果
        self._polling = False
        self._fails = 0
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._poll)

    def start(self):
        self._timer.start(0)

    def _poll(self):
        """定時輪詢：上一次回來才排下一次，不會同時有多個請求堆積。"""
        if self._polling:
            return
        self._polling = True
        self._request(periodic=True)

    def refresh(self, *_):
        """立刻刷新（新增、取消、刪除之後）；可以直接當成 Api 的成功回呼。"""
        self._request(periodic=False)

    def _request(self, periodic: bool):
        self._seq += 1
        seq = self._seq
        self.api.get("/api/jobs", lambda jobs: self._on_jobs(seq, jobs, periodic),
                     lambda msg: self._on_error(msg, periodic))

    def _on_jobs(self, seq: int, jobs, periodic: bool):
        if periodic:
            self._polling = False
        if seq > self._applied:  # 比畫面上的還舊的結果（較晚回來）就丟掉
            self._applied = seq
            self._fails = 0
            self.online.emit(True, "")
            self.render(jobs if isinstance(jobs, list) else [])
        if periodic or not self._polling:
            self._schedule()

    def _on_error(self, msg: str, periodic: bool):
        if not periodic:
            return
        self._polling = False
        self._fails += 1
        if self._fails >= 2:
            self.online.emit(False, msg)
        self._schedule()

    def _schedule(self):
        """有下載進行中而且看得到佇列時 0.7 秒更新一次；其他時候放慢，減少引擎掃描資料夾。"""
        active = any(j.get("status") in ACTIVE for j in self.jobs)
        win = self.window()
        shown = self.isVisible() and not (win.windowState() & Qt.WindowMinimized)
        if self._fails:
            ms = 2000
        elif active:
            ms = 700 if shown else 2000
        else:
            ms = 4000
        self._timer.start(ms)

    def showEvent(self, e):
        super().showEvent(e)
        self.refresh()

    def render(self, jobs: list[dict]):
        self.jobs = jobs
        ids = [j["id"] for j in jobs]
        if ids != self.order:  # 工作增減或順序改變：只搬動列，不重建已有的列
            for jid in ids:
                if jid not in self.rows:
                    self.rows[jid] = JobRow(self.api, self.refresh, self.toast)
            for jid in set(self.rows) - set(ids):
                self.rows.pop(jid)
            self.card.set_rows([self.rows[jid] for jid in ids])
            self.order = ids
        for j in jobs:
            row = self.rows[j["id"]]
            if row.job != j:
                row.update_job(j)
        self.empty.setVisible(not jobs)
        self.card.setVisible(bool(jobs))
        self.counts.emit(sum(j.get("status") in ACTIVE for j in jobs))


# --------------------------------------------------------------------------- #
#  頁面：設定
# --------------------------------------------------------------------------- #
class SettingsPage(QWidget):
    meta_changed = Signal(dict)

    def __init__(self, api: Api, toast):
        super().__init__()
        self.api, self.toast = api, toast
        lay = page_layout(self)
        lay.addWidget(label("儲存位置", "sectionHeader"))
        card = Card()
        self.folder = ElidedLabel("subtitle")
        self.disk = label("", "subtitle")
        change = QPushButton("變更…")
        change.clicked.connect(self.choose)
        self.reset = QPushButton("恢復預設")
        self.reset.clicked.connect(lambda: self.save(""))
        open_btn = QPushButton(f"在{FILE_MANAGER}中打開")
        open_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(self.folder.full_text())))
        row = QWidget()
        rl = QVBoxLayout(row)
        rl.setContentsMargins(14, 10, 14, 10)
        rl.setSpacing(4)
        rl.addWidget(label("下載資料夾"))
        rl.addWidget(self.folder)
        rl.addWidget(self.disk)
        btns = QHBoxLayout()  # 按鈕放在路徑下方：視窗再窄也按得到
        btns.setContentsMargins(0, 6, 0, 0)
        btns.addWidget(change)
        btns.addWidget(open_btn)
        btns.addWidget(self.reset)
        btns.addStretch()
        rl.addLayout(btns)
        card.add(row)
        lay.addWidget(card)

        lay.addSpacing(8)
        lay.addWidget(label("下載元件", "sectionHeader"))
        card2 = Card()
        self.version = label("", "subtitle")
        self.update_btn = QPushButton("檢查更新")
        self.update_btn.clicked.connect(self.update_ytdlp)
        card2.add(form_row("yt-dlp", self._pair(self.version, self.update_btn)))
        self.ffmpeg = label("", "subtitle")
        card2.add(form_row("FFmpeg", self.ffmpeg))
        lay.addWidget(card2)
        note = label("yt-dlp 會在背景自動更新，YouTube 改版時通常不需要手動處理。", "subtitle", wrap=True)
        lay.addWidget(note)
        lay.addStretch()

    @staticmethod
    def _pair(a: QWidget, b: QWidget) -> QWidget:
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        lay.addWidget(a)
        lay.addWidget(b)
        return w

    def refresh(self):
        self.api.get("/api/settings", self.on_settings, lambda m: self.toast(f"無法讀取設定：{m}", error=True))
        self.api.get("/api/meta", self.on_meta, timeout_ms=30_000)  # 第一次會查 PyPI，可能要十幾秒

    def on_settings(self, s: dict):
        self.folder.set_full_text(s.get("download_dir") or "")
        disk = s.get("disk") or {}
        self.disk.setText(f"剩餘 {fmt_bytes(disk.get('free'))}" if disk.get("free") is not None else "")
        self.reset.setVisible(s.get("download_dir") != s.get("default_dir") and not s.get("env_locked"))

    @staticmethod
    def update_available(m: dict) -> bool:
        return bool(m.get("update_ready")) or newer(m.get("latest"), m.get("version"))

    def on_meta(self, m: dict):
        ver = m.get("version") or ""
        latest = m.get("latest")
        if m.get("update_ready"):
            self.version.setText(f"{ver}（新版已下載）")
            self.update_btn.setText("重新啟動以套用")
        elif newer(latest, ver):
            self.version.setText(f"{ver}（最新 {latest}）")
            self.update_btn.setText(f"更新至 {latest}")
        else:
            self.version.setText(f"{ver}（已是最新）")
            self.update_btn.setText("檢查更新")
        self.ffmpeg.setText("已安裝" if m.get("ffmpeg") else "找不到，無法合併影音")
        self.meta_changed.emit(m)

    def choose(self):
        path = QFileDialog.getExistingDirectory(self, "選擇下載資料夾", self.folder.full_text())
        if path:
            self.save(path)

    def save(self, path: str):
        self.api.post("/api/settings", {"download_dir": path}, lambda s: (self.on_settings(s), self.toast("已變更儲存位置")),
                      lambda e: self.toast(e, error=True))

    def update_ytdlp(self):
        self.update_btn.setEnabled(False)
        self.update_btn.setText("處理中…")

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
                self.toast(msg or "已是最新版本", error=msg.startswith("更新失敗"))
                self.on_meta(m)

            def again(e):  # 查詢狀態偶爾逾時（引擎正在下載新版）：稍後再查，不要當成更新失敗
                if retries > 0:
                    QTimer.singleShot(2000, lambda: poll(retries - 1))
                else:
                    fail(e)
            self.api.get("/api/meta", got, again, timeout_ms=30_000)

        def started(_):
            self.toast("正在更新 yt-dlp，完成後會自動重新啟動…")
            QTimer.singleShot(1000, poll)

        self.api.post("/api/update", {}, started, fail)


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
        if VIBRANCY and e.button() == Qt.LeftButton and self.window().windowHandle():
            self.window().windowHandle().startSystemMove()
        else:
            super().mousePressEvent(e)

    def mouseDoubleClickEvent(self, e):
        if VIBRANCY:  # 跟系統標題列一樣：連按兩下縮放視窗
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
        self.settings = SettingsPage(api, self.toast)
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
    VIBRANCY = True
    return True


def apply_theme(app: QApplication, win: MainWindow, chevron: str, dark: bool | None = None):
    """套用深淺色；dark 未指定時跟隨系統外觀。"""
    if dark is None:
        dark = app.styleHints().colorScheme() == Qt.ColorScheme.Dark
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
    app.setStyleSheet(stylesheet(t, chevron))
    win.apply_theme(t)


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
    apply_theme(app, win, chevron)
    app.styleHints().colorSchemeChanged.connect(lambda *_: apply_theme(app, win, chevron))
    win.show()
    win.start()
    app_boot.install_smoke_test(app)  # --smoke-test：CI 確認視窗能開啟後自動結束
    code = app.exec()
    shutdown(app, win)
    restarter.launch(server.ROOT)  # 更新 yt-dlp 後要求的重新啟動（新程序會等這裡釋放連接埠）
    os._exit(code)  # 結束背景的 Flask 與下載執行緒


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
