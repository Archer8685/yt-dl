"""原生介面的共用部分：主題與樣式、格式化工具、引擎 API（Api）、共用元件（Card、Segmented、form_row…）、
設定存取、下載預設值與免責聲明。各頁面（native_download / native_queue / native_settings）
與主視窗（native_app）都從這裡取用。
"""
from __future__ import annotations

import json
import os
import re
import sys
import threading
from pathlib import Path
from urllib.parse import urlsplit

from PySide6.QtCore import QByteArray, QObject, QPointF, QRectF, QSettings, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
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


THEMES = [("system", "跟隨系統"), ("light", "淺色"), ("dark", "深色")]
FONT_SIZES = [("small", "小"), ("medium", "中"), ("large", "大")]
FONT_SCALE = {"small": 0.88, "medium": 1.0, "large": 1.18}


def ui_prefs() -> tuple[str, str]:
    """外觀設定（主題、文字大小），存在 QSettings 的 ui 群組。"""
    st = settings_store()
    theme, size = st.value("ui/theme", "system"), st.value("ui/font", "medium")
    return (theme if theme in dict(THEMES) else "system", size if size in FONT_SCALE else "medium")


def save_ui_prefs(theme: str, size: str):
    st = settings_store()
    st.setValue("ui/theme", theme)
    st.setValue("ui/font", size)


def ui_font(scale: float = 1.0) -> QFont:
    """macOS：系統字型（SF Pro + 蘋方）13 pt。Windows：Segoe UI Variable + 微軟正黑體，換算成同樣的 13 px 視覺大小。
    scale：文字大小設定（小 / 中 / 大）。"""
    f = QFont()
    size = round(13 * scale)
    if IS_MAC:
        f.setPointSizeF(size)
    else:
        f.setFamilies(["Segoe UI Variable Text", "Segoe UI", "Microsoft JhengHei UI", "Microsoft JhengHei"])
        f.setPixelSize(size)
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


def stylesheet(t: dict[str, str], chevron: str, scale: float = 1.0) -> str:
    """版面與容器的樣式（兩個平台都用）；Windows 再加上模仿 macOS 的控制項樣式。scale：文字大小設定。"""
    def px(n: int) -> int:
        return round(n * scale)
    base = f"""
    #content {{ background: {t['bg']}; }}
    QLabel {{ background: transparent; }}
    #sidebar {{ background: {"transparent" if VIBRANCY else t['sidebar']}; border-right: 1px solid {t['sep']}; }}
    #navButton {{ text-align: left; padding: 4px 8px; border: none; border-radius: 6px; background: transparent;
                  min-height: 20px; }}
    #navButton:checked {{ background: {t['select']}; }}
    #toolbar {{ background: {t['toolbar']}; border-bottom: 1px solid {t['sep']}; }}
    #toolbarTitle {{ font-size: {px(15)}px; font-weight: 700; }}
    #toolbarSubtitle {{ color: {t['secondary']}; font-size: {px(11)}px; }}
    #subtitle {{ color: {t['secondary']}; }}
    #hint {{ color: {t['secondary']}; font-size: {px(11)}px; }}
    QLineEdit[mono="true"] {{ font-family: "SF Mono", "Menlo", "Cascadia Mono", "Consolas", monospace; }}
    #errorText {{ color: {t['red']}; }}
    #okText {{ color: {t['green']}; font-weight: 600; }}
    #warnText {{ color: {t['orange']}; font-weight: 600; }}
    #sectionHeader {{ font-weight: 700; padding-left: 2px; }}
    #card {{ background: {t['card']}; border: 1px solid {t['sep']}; border-radius: 10px; }}
    #row {{ background: transparent; }}
    #hairline {{ background: {t['sep']}; max-height: 1px; min-height: 1px; border: none; }}
    #videoTitle {{ font-size: {px(15)}px; font-weight: 600; }}
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


MEDIA_EXT = (".mp4", ".m4v", ".webm", ".mkv", ".mov", ".mp3", ".m4a", ".aac", ".flac", ".m3u8", ".mpd")
_EXTRACTORS: list | None = None
_EXTRACTORS_LOCK = threading.Lock()


def is_supported_url(text: str) -> bool:
    """剪貼簿裡的文字是不是「適合下載」的連結：yt-dlp 認得的網站（YouTube、Bilibili、X…），
    或直接指向影音檔的網址。一般網頁（搜尋結果、GitHub…）不算，免得每次複製網址都被拿去解析。

    第一次呼叫要載入 yt-dlp 的網站清單（約半秒），請在背景執行緒呼叫。
    """
    global _EXTRACTORS
    text = (text or "").strip()
    if not re.fullmatch(r"https?://\S{4,2000}", text):
        return False
    try:
        if urlsplit(text).path.lower().endswith(MEDIA_EXT):
            return True
    except ValueError:
        return False
    with _EXTRACTORS_LOCK:
        if _EXTRACTORS is None:
            try:
                from yt_dlp.extractor import gen_extractor_classes
                _EXTRACTORS = [ie for ie in gen_extractor_classes() if ie.ie_key() != "Generic"]
            except Exception:  # noqa: BLE001 — 判斷不了就當作不是，不影響 App
                _EXTRACTORS = []
    return any(ie.suitable(text) for ie in _EXTRACTORS)


def auto_paste_enabled() -> bool:
    v = settings_store().value("ui/auto_paste", True)
    return v.lower() == "true" if isinstance(v, str) else bool(v)


def set_auto_paste(on: bool):
    settings_store().setValue("ui/auto_paste", on)


class ClipboardWatcher(QObject):
    """在背景判斷剪貼簿的連結能不能下載（不卡住介面），可以的話發出 found(網址)。"""
    found = Signal(str)

    def check(self, text: str):
        def work():
            if is_supported_url(text):
                self.found.emit(text.strip())
        threading.Thread(target=work, daemon=True).start()

    @staticmethod
    def warm_up():
        """App 開啟後先在背景載入網站清單，第一次判斷時就不用等。"""
        threading.Thread(target=lambda: is_supported_url("https://www.youtube.com/watch?v=x"), daemon=True).start()


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
#  免責聲明與版本
# --------------------------------------------------------------------------- #
DISCLAIMER_URL = "https://github.com/Archer8685/yt-dl/blob/main/DISCLAIMER.md"
# 免責聲明內容有實質變更時把這個數字加一：已同意舊版的使用者下次開啟會再看到一次
DISCLAIMER_VERSION = "1"
DISCLAIMER_KEY = "legal/accepted_version"
DISCLAIMER_SHORT = ("YT 下載器只是下載工具，不提供、不託管任何影音內容，與 YouTube／Google 無任何關聯。\n"
                    "請只下載你有權使用的內容，並遵守著作權法與各平台服務條款；不得用於侵權、散布盜版，"
                    "或規避付費、DRM 等保護措施。使用者須自行承擔使用責任；本軟體以「現狀」提供，不提供任何保證。")


def app_version() -> str:
    """App 的版本：開發時讀專案的 VERSION，打包版讀 build_app.py 放進去的 VERSION。"""
    try:
        return (BUNDLE / "VERSION").read_text(encoding="utf-8").strip() or "開發版"
    except OSError:
        return "開發版"


def disclaimer_needed() -> bool:
    """第一次開啟（或聲明內容更新後）要先同意免責聲明。

    自動化流程一律跳過，不能被對話框卡住：--smoke-test（CI）、環境變數 YTDL_ACCEPT_DISCLAIMER=1（截圖、測試）。
    """
    import app_boot
    if app_boot.smoke_test_requested() or os.environ.get("YTDL_ACCEPT_DISCLAIMER") == "1":
        return False
    return str(settings_store().value(DISCLAIMER_KEY, "") or "") != DISCLAIMER_VERSION


def disclaimer_box(parent: QWidget | None = None) -> tuple[QMessageBox, QPushButton]:
    """第一次開啟時的免責聲明對話框；回傳 (對話框, 「我了解並同意」按鈕)。"""
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Information)
    box.setWindowTitle(f"{TITLE} — 使用聲明")
    box.setText("使用前請閱讀")
    box.setTextFormat(Qt.RichText)
    body = DISCLAIMER_SHORT.replace("\n", "<br><br>")
    # informative 標籤的連結 Qt 預設就可以點、用預設瀏覽器打開（openExternalLinks）
    box.setInformativeText(f"{body}<br><br><a href=\"{DISCLAIMER_URL}\">查看完整免責聲明</a>")
    accept = box.addButton("我了解並同意", QMessageBox.AcceptRole)
    leave = box.addButton("離開", QMessageBox.RejectRole)
    box.setDefaultButton(accept)
    box.setEscapeButton(leave)  # Esc 或關閉視窗都當成「離開」
    return box, accept


def confirm_disclaimer(parent: QWidget | None = None, run=None) -> bool:
    """需要時顯示免責聲明；同意（或不需要問）回傳 True 並記下同意的版本，按「離開」回傳 False。

    run(box) 負責顯示對話框（預設 box.exec()）；測試用它模擬按下按鈕。
    """
    if not disclaimer_needed():
        return True
    box, accept = disclaimer_box(parent)
    (run or (lambda b: b.exec()))(box)
    ok = box.clickedButton() is accept
    if ok:
        settings_store().setValue(DISCLAIMER_KEY, DISCLAIMER_VERSION)
    box.deleteLater()
    return ok


# 下載預設值：每次開啟 App 的「新增下載」都從這組選項開始（在「設定 → 下載預設值」修改）
DOWNLOAD_DEFAULTS = {"mode": "av", "quality": None, "container": "mp4", "acodec": "mp3", "aquality": "0",
                     "as_playlist": False}


def load_download_defaults() -> dict:
    st = settings_store()
    st.beginGroup("defaults")
    d = dict(DOWNLOAD_DEFAULTS)
    mode = st.value("mode", d["mode"])
    d["mode"] = mode if mode in dict(MODES) else d["mode"]
    q = st.value("quality", "")
    d["quality"] = int(q) if str(q).isdigit() and int(q) in dict(QUALITIES) else None
    for key, choices in (("container", CONTAINERS), ("acodec", AUDIO_CODECS), ("aquality", AUDIO_QUALITY)):
        v = st.value(key, d[key])
        d[key] = v if v in dict(choices) else d[key]
    pl = st.value("as_playlist", False)
    d["as_playlist"] = pl.lower() == "true" if isinstance(pl, str) else bool(pl)
    st.endGroup()
    return d


def save_download_defaults(d: dict):
    st = settings_store()
    st.beginGroup("defaults")
    for k, default in DOWNLOAD_DEFAULTS.items():
        v = d.get(k, default)
        st.setValue(k, "" if v is None else v)
    st.endGroup()
