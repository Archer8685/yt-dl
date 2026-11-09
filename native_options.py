"""原生介面的「進階選項」面板（PySide6），對應網頁版 index.html 的進階功能。

用法（在 DownloadPage 裡）：

    self.advanced = AdvancedOptions(api, toast)
    lay.addWidget(self.advanced)
    ...
    self.advanced.set_info(info)                       # 解析完成後
    self.advanced.set_mode(mode)                       # 切換下載模式時
    options = self.advanced.apply(self.options())      # 送出下載前
    body["network"] = self.advanced.network()          # 呼叫 /api/info 時

`apply()` 產生的鍵名和網頁版 buildOptions() / server.build_opts() 完全一致。
"""
from __future__ import annotations

import copy
import html
import inspect
import re
from pathlib import Path

from PySide6.QtCore import (
    QT_TRANSLATE_NOOP,
    QCoreApplication,
    QEasingCurve,
    QPoint,
    QPointF,
    QRect,
    QRectF,
    QSettings,
    QSize,
    Qt,
    QTimer,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import QColor, QFontMetrics, QGuiApplication, QIntValidator, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QAbstractButton,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from native_common import Card, PopUp, Segmented, form_row, hairline, label, tokens

_tr = QCoreApplication.translate  # 名稱固定是 _tr（tools/i18n_update.py 只認得這個）
_CTX = "native_options"  # 模組層級字串（選項清單）的翻譯 context，見 docs/I18N.md 2.6

# --------------------------------------------------------------------------- #
#  選項清單（值與 server.py 的允許值一致）。中文標籤用 QT_TRANSLATE_NOOP 標記，顯示時才翻譯（_items）
# --------------------------------------------------------------------------- #
VCODECS = [("", QT_TRANSLATE_NOOP("native_options", "自動")), ("av01", "AV1"), ("vp9", "VP9"),
           ("h264", "H.264"), ("h265", "H.265")]
FPS_LIMITS = [("", QT_TRANSLATE_NOOP("native_options", "不限")), ("60", "≤ 60 fps"), ("30", "≤ 30 fps"),
              ("25", "≤ 25 fps")]
HDR = [("", QT_TRANSLATE_NOOP("native_options", "自動")), ("hdr", QT_TRANSLATE_NOOP("native_options", "偏好 HDR")),
       ("sdr", QT_TRANSLATE_NOOP("native_options", "僅 SDR"))]
ACODEC_PREFER = [("", QT_TRANSLATE_NOOP("native_options", "自動")), ("opus", "Opus"), ("aac", "AAC")]
SUB_FORMATS = [("best", QT_TRANSLATE_NOOP("native_options", "原始")), ("srt", "SRT"), ("vtt", "VTT"),
               ("ass", "ASS"), ("lrc", "LRC")]
THUMB_FORMATS = [("jpg", "JPG"), ("png", "PNG"), ("webp", "WebP")]
SPONSOR = [("sponsor", QT_TRANSLATE_NOOP("native_options", "贊助")),
           ("intro", QT_TRANSLATE_NOOP("native_options", "片頭")),
           ("outro", QT_TRANSLATE_NOOP("native_options", "片尾")),
           ("selfpromo", QT_TRANSLATE_NOOP("native_options", "自我宣傳")),
           ("preview", QT_TRANSLATE_NOOP("native_options", "預告/回顧")),
           ("filler", QT_TRANSLATE_NOOP("native_options", "離題閒聊")),
           ("interaction", QT_TRANSLATE_NOOP("native_options", "訂閱提醒")),
           ("music_offtopic", QT_TRANSLATE_NOOP("native_options", "非音樂片段")),
           ("poi_highlight", QT_TRANSLATE_NOOP("native_options", "精華")),
           ("chapter", QT_TRANSLATE_NOOP("native_options", "章節"))]
SPONSOR_NO_REMOVE = ("poi_highlight", "chapter")  # 這兩類只能標記，不能移除（同網頁版）
TEMPLATES = [("%(title)s [%(id)s].%(ext)s", QT_TRANSLATE_NOOP("native_options", "標題 [ID]")),
             ("%(title)s.%(ext)s", QT_TRANSLATE_NOOP("native_options", "標題")),
             ("%(uploader)s - %(title)s.%(ext)s", QT_TRANSLATE_NOOP("native_options", "作者 - 標題")),
             ("%(upload_date>%Y-%m-%d)s %(title)s.%(ext)s", QT_TRANSLATE_NOOP("native_options", "日期 標題")),
             ("%(playlist_index|)s %(title)s.%(ext)s", QT_TRANSLATE_NOOP("native_options", "清單序號 標題")),
             ("%(uploader)s/%(title)s.%(ext)s", QT_TRANSLATE_NOOP("native_options", "作者資料夾/標題")),
             ("custom", QT_TRANSLATE_NOOP("native_options", "自訂…"))]
COOKIE_SOURCES = [("", QT_TRANSLATE_NOOP("native_options", "不使用")),
                  ("file", QT_TRANSLATE_NOOP("native_options", "cookies.txt 檔案")),
                  ("browser", QT_TRANSLATE_NOOP("native_options", "從瀏覽器讀取"))]
BROWSERS = [("chrome", "Chrome"), ("edge", "Edge"), ("firefox", "Firefox"), ("brave", "Brave"),
            ("opera", "Opera"), ("vivaldi", "Vivaldi"), ("chromium", "Chromium"), ("safari", "Safari")]
DEFAULT_TEMPLATE = TEMPLATES[0][0]

# 預設值與網頁版 index.html 一致（嵌入中繼資料 / 章節 / 封面、嵌入並保留字幕、SRT）
DEFAULTS: dict[str, object] = {
    "codec": "", "max_fps": "", "hdr": "", "recode": False, "prefer_size": False, "premium": False,
    "prefer_acodec": "", "allow_drc": False,
    "sub_format": "srt", "sub_embed": True, "sub_keep": True, "sub_all": False,
    "split_chapters": False, "force_keyframes": False, "live_from_start": False,
    "sponsor_remove": [], "sponsor_mark": [],
    "embed_metadata": True, "embed_chapters": True, "embed_thumbnail": True, "write_thumbnail": False,
    "thumb_format": "jpg", "write_description": False, "write_infojson": False, "write_comments": False,
    "keep_original": False, "template": DEFAULT_TEMPLATE, "restrict_filenames": False,
    "cookie_source": "", "browser": "chrome", "proxy": "", "rate_limit": "", "geo": "",
    "fragments": 4, "retries": 10,
}
SETTINGS_GROUP = "advanced"
_UNSAVED = object()  # save_settings：還沒存過的值
# reveal_section() 接受的名稱：分組本身的 key，加上給其他頁面用的別名
SECTION_ALIASES = {"subtitles": "subs", "sponsorblock": "sponsor", "metadata": "files", "cookies": "network"}
# 自己畫的元件（開關、標籤、箭頭、標題列滑過）用的顏色；AdvancedOptions.apply_theme() 會更新
THEME: dict[str, str] = dict(tokens(False))


def _ts(sec) -> str:
    """秒數 → 1:05 / 1:02:03（0 秒也要顯示，章節常從 0 開始）。"""
    sec = int(sec or 0)
    h, m, s = sec // 3600, sec % 3600 // 60, sec % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


_RANGE_CHUNK = re.compile(r"^\s*([\d:.]+)\s*[-~到]\s*([\d:.]+|inf|end)?\s*$")  # 同 server._parse_ranges


def range_error(text: str) -> str:
    """檢查時間範圍文字；正確回傳空字串。

    用引擎的解析器判斷（規則和下載時完全一致），但訊息在 App 端依介面語言重組：
    引擎的訊息只有中文，而且這裡是直接呼叫函式，不是走 API。
    """
    from server import _parse_ranges  # 延遲匯入：只在真的要檢查時才載入引擎模組
    try:
        _parse_ranges(text)
        return ""
    except ValueError:
        pass
    for chunk in re.split(r"[,\n;]+", text or ""):  # 找出是哪一段錯了
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            _parse_ranges(chunk)
        except ValueError:
            if _RANGE_CHUNK.match(chunk):
                return _tr(_CTX, "時間範圍「{chunk}」無效：請確認時間寫法正確，而且結束時間比開始時間晚").format(
                    chunk=chunk)
            return _tr(_CTX, "看不懂時間範圍「{chunk}」，例如：0:30-1:45, 3:00-end").format(chunk=chunk)
    return _tr(_CTX, "時間範圍格式不正確，例如：0:30-1:45, 3:00-end")


def _items(items) -> list[tuple[str, str]]:
    """選項清單 → 依目前介面語言翻譯好的 (值, 顯示文字)。品牌、格式名稱（AV1、SRT）沒標記，原樣回傳。"""
    return [(k, _tr(_CTX, v)) for k, v in items]


def _focus_ring(p: QPainter, rect: QRectF, radius: float):
    """自繪元件統一的焦點環：2 px、系統強調色（比原本 1.5 px 的淡色明顯，鍵盤操作時看得到）。"""
    p.save()
    p.setPen(QPen(_color(THEME["accent"]), 2))
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(rect.adjusted(1, 1, -1, -1), max(0.0, radius - 1), max(0.0, radius - 1))
    p.restore()


def _unique(items) -> list:
    return list(dict.fromkeys(i for i in items if i))


def _to_bool(v) -> bool:
    """QSettings 的 ini 後端會把 bool 存成字串 "true"/"false"。"""
    return v.lower() == "true" if isinstance(v, str) else bool(v)


# --------------------------------------------------------------------------- #
#  元件
# --------------------------------------------------------------------------- #
_RGBA = re.compile(r"rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*(?:,\s*([\d.]+)\s*)?\)")


def _color(value: str) -> QColor:
    """tokens() 的顏色字串 → QColor。QColor 看不懂 CSS 的 rgba(r,g,b,0.08)，要自己解析。"""
    m = _RGBA.fullmatch(value.strip())
    if m:
        r, g, b = (int(float(x)) for x in m.group(1, 2, 3))
        c = QColor(r, g, b)
        c.setAlphaF(float(m.group(4)) if m.group(4) is not None else 1.0)
        return c
    return QColor(value)


def _hint(text: str = "", wrap: bool = False) -> QLabel:
    """灰色、小一號的說明文字。顏色與字級由 native_app.stylesheet() 的 #hint 決定，會跟著深淺色與文字大小設定。"""
    return label(text, "hint", wrap)


class Switch(QAbstractButton):
    """macOS 風格的切換開關（38×22 膠囊軌道＋白色圓鈕，開啟為系統藍，切換時滑動）。

    Qt 沒有原生的 switch，所以兩個平台都用這個自己畫的版本；顏色取自 THEME（native_app.tokens()）。
    title 是給朗讀程式念的名稱（開關本身沒有文字）；放進 switch_row() 時會自動用該列的標題。
    朗讀程式另外會念「核取方塊、已勾選／未勾選」（QAbstractButton 的 checkable 狀態）。
    """

    def __init__(self, checked: bool = False, title: str = ""):
        super().__init__()
        self.setCheckable(True)
        self.setChecked(checked)
        if title:
            self.setAccessibleName(title)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.TabFocus)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self._pos = 1.0 if checked else 0.0
        self._anim = QVariantAnimation(self, duration=140, easingCurve=QEasingCurve.InOutCubic)
        self._anim.valueChanged.connect(self._set_pos)
        self.toggled.connect(self._animate)

    def sizeHint(self) -> QSize:
        # 一般字級（字高 ≤ 17 px）維持 macOS 的 38×22；文字放大（App 的「文字大小」設定）時跟著字高等比放大
        h = max(22, round(self.fontMetrics().height() * 1.25))
        return QSize(round(h * 38 / 22), h)

    def _set_pos(self, v):
        self._pos = float(v)
        self.update()

    def _animate(self, checked: bool):
        self._anim.stop()
        if not self.isVisible():
            self._set_pos(1.0 if checked else 0.0)
            return
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        h = r.height()
        c = _color(THEME["track"])
        on = _color(THEME["accent"])
        c.setRedF(c.redF() + (on.redF() - c.redF()) * self._pos)
        c.setGreenF(c.greenF() + (on.greenF() - c.greenF()) * self._pos)
        c.setBlueF(c.blueF() + (on.blueF() - c.blueF()) * self._pos)
        c.setAlphaF(c.alphaF() + (on.alphaF() - c.alphaF()) * self._pos)  # 關閉時的軌道是半透明色
        if not self.isEnabled():
            c.setAlphaF(c.alphaF() * 0.45)
        p.setPen(Qt.NoPen)
        p.setBrush(c)
        p.drawRoundedRect(r, h / 2, h / 2)
        d = h - 4
        x = r.left() + 2 + (r.width() - d - 4) * self._pos
        knob = QRectF(x, r.top() + 2, d, d)
        p.setBrush(QColor(0, 0, 0, 40))
        p.drawEllipse(knob.translated(0, 0.8))
        p.setBrush(QColor("#FFFFFF"))
        p.drawEllipse(knob)
        if self.hasFocus():
            _focus_ring(p, QRectF(self.rect()), self.height() / 2)
        p.end()


class FlowLayout(QLayout):
    """自動換行的版面（標籤／晶片用）。"""

    def __init__(self, parent=None, spacing: int = 6):
        super().__init__(parent)
        self._items = []
        self._space = spacing
        self._hfw: dict[int, int] = {}  # 寬度 → 高度；Qt 每次調整大小會問好幾十次，幾百個標籤時要快取
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self._items.append(item)
        self._hfw.clear()

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        self._hfw.clear()
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def invalidate(self):  # 子元件顯示／隱藏、文字改變時 Qt 會呼叫
        self._hfw.clear()
        super().invalidate()

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        if w not in self._hfw:
            self._hfw[w] = self._do(QRect(0, 0, w, 0), True)
        return self._hfw[w]

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        s = QSize()
        for it in self._items:
            s = s.expandedTo(it.minimumSize())
        return s

    def _do(self, rect, test):
        x, y, line = rect.x(), rect.y(), 0
        for it in self._items:
            if it.widget() and not it.widget().isVisibleTo(it.widget().parentWidget()):
                continue
            hint = it.sizeHint()
            if x + hint.width() > rect.right() + 1 and line > 0:
                x, y, line = rect.x(), y + line + self._space, 0
            if not test:
                it.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self._space
            line = max(line, hint.height())
        return y + line - rect.y()


class _HoverRepaint:
    """滑鼠進出時重畫（自己畫的元件不會自動因 hover 重畫）。"""

    def enterEvent(self, e):
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self.update()
        super().leaveEvent(e)


class Chip(_HoverRepaint, QAbstractButton):
    """膠囊標籤（macOS 的 token 樣式）：自己畫，不依賴 QSS，在原生 macOS 樣式下外觀也一致。

    可複選的標籤是 checkable 按鈕，朗讀程式會念出「已勾選／未勾選」；name 是朗讀用的完整名稱
    （例如章節標籤畫面上的標題會截短）。
    """

    H = 22  # 最小高度；實際高度依字高計算

    def __init__(self, text: str, checkable: bool = True, name: str = ""):
        super().__init__()
        self.setText(text)
        self.setCheckable(checkable)
        self.setAccessibleName(name or text)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.TabFocus)
        self.setAttribute(Qt.WA_Hover)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    def sizeHint(self) -> QSize:
        fm = self.fontMetrics()  # 用字型量寬高：英文標籤較長、文字放大時都不會被切掉
        h = max(self.H, fm.height() + 6)
        return QSize(fm.horizontalAdvance(self.text()) + max(20, h - 2), h)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        on = self.isChecked()
        p.setPen(QPen(_color(THEME["border"]), 1) if self.underMouse() and not on else Qt.NoPen)
        p.setBrush(_color(THEME["accent"] if on else THEME["seg"]))
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        if self.hasFocus():
            # 選中的標籤底色就是強調色，焦點環改用文字色才看得出來
            if on:
                p.setPen(QPen(_color(THEME["text"]), 2))
                p.setBrush(Qt.NoBrush)
                p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), r.height() / 2 - 1, r.height() / 2 - 1)
            else:
                _focus_ring(p, QRectF(self.rect()), r.height() / 2)
        p.setPen(_color(THEME["accent_text"] if on else THEME["text"]))
        p.drawText(self.rect(), Qt.AlignCenter, self.text())
        p.end()


class ChipGroup(QWidget):
    """可複選的膠囊標籤群（自動換行）。"""
    changed = Signal()

    def __init__(self, items: list[tuple[str, str]] = (), empty: str = ""):
        super().__init__()
        self.flow = FlowLayout(self)
        self.chips: dict[str, Chip] = {}
        self.empty = _hint(empty)
        self.flow.addWidget(self.empty)
        self.set_items(items)

    def set_items(self, items, selected=()):
        for b in self.chips.values():
            self.flow.removeWidget(b)
            b.deleteLater()
        self.chips = {}
        for key, text in items:
            b = Chip(text)
            b.setChecked(key in selected)
            b.setToolTip(key)
            b.toggled.connect(lambda *_: self.changed.emit())
            self.flow.addWidget(b)
            self.chips[key] = b
        self.empty.setVisible(not self.chips and bool(self.empty.text()))
        self.updateGeometry()

    def values(self) -> list[str]:
        return [k for k, b in self.chips.items() if b.isChecked()]

    def set_values(self, values):
        for k, b in self.chips.items():
            b.blockSignals(True)
            b.setChecked(k in values)
            b.blockSignals(False)
        self.changed.emit()

    def filter(self, text: str):
        text = text.strip().lower()
        for k, b in self.chips.items():
            b.setVisible(not text or text in k.lower() or text in b.text().lower())
        self.flow.invalidate()
        self.updateGeometry()

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        return self.flow.heightForWidth(w)

    def sizeHint(self):
        return QSize(300, self.flow.heightForWidth(max(self.width(), 300)))


class FitScroll(QScrollArea):
    """內容不多時只佔內容的高度，超過 max_h 才固定高度並捲動。

    QScrollArea 預設的建議高度和內容無關：只有兩個標籤也會撐到上限，下面留一大塊空白。
    """

    def __init__(self, max_h: int):
        super().__init__()
        self.max_h = max_h
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)

    def _content_height(self) -> int:
        w = self.widget()
        if w is None:
            return 0
        width = self.viewport().width() if self.viewport().width() > 50 else 300
        return w.heightForWidth(width) if w.hasHeightForWidth() else w.sizeHint().height()

    def sizeHint(self):
        return QSize(super().sizeHint().width(), min(self.max_h, self._content_height() + 2 * self.frameWidth()))

    def minimumSizeHint(self):
        return QSize(0, min(self.max_h, self._content_height() + 2 * self.frameWidth()))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if e.oldSize().width() != e.size().width():  # 寬度改變會換行，高度要跟著重算
            self.updateGeometry()


class Icon(QWidget):
    """系統設定那種彩色圓角方塊圖示（自己畫的線條符號）。"""

    def __init__(self, kind: str, color: str):
        super().__init__()
        self.kind, self.color = kind, QColor(color)
        self.setFixedSize(24, 24)
        self.setFocusPolicy(Qt.NoFocus)  # 純裝飾：不能取得焦點

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(self.color)
        p.drawRoundedRect(QRectF(0, 0, 24, 24), 6, 6)
        p.setPen(QPen(QColor("white"), 1.7, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(Qt.NoBrush)
        k = self.kind
        if k == "video":
            p.drawRoundedRect(QRectF(4.5, 7.5, 10, 9), 2, 2)
            p.drawPolygon([QPointF(15, 10.5), QPointF(19.5, 8), QPointF(19.5, 16), QPointF(15, 13.5)])
        elif k == "audio":
            p.drawLine(QPointF(10, 16.5), QPointF(10, 6.5))
            p.drawLine(QPointF(10, 6.5), QPointF(17, 5))
            p.drawLine(QPointF(17, 5), QPointF(17, 15))
            p.drawEllipse(QRectF(6, 14.5, 4, 3.5))
            p.drawEllipse(QRectF(13, 13, 4, 3.5))
        elif k == "subs":
            p.drawRoundedRect(QRectF(4, 6, 16, 12), 2.5, 2.5)
            p.drawLine(QPointF(7.5, 11), QPointF(11, 11))
            p.drawLine(QPointF(13.5, 11), QPointF(16.5, 11))
            p.drawLine(QPointF(7.5, 14.5), QPointF(16.5, 14.5))
        elif k == "clip":
            p.drawEllipse(QRectF(4.5, 14, 5, 5))
            p.drawEllipse(QRectF(14.5, 14, 5, 5))
            p.drawLine(QPointF(8.6, 14.6), QPointF(17, 4.5))
            p.drawLine(QPointF(15.4, 14.6), QPointF(7, 4.5))
        elif k == "skip":
            p.drawPolygon([QPointF(5, 7), QPointF(11.5, 12), QPointF(5, 17)])
            p.drawPolygon([QPointF(11.5, 7), QPointF(18, 12), QPointF(11.5, 17)])
            p.drawLine(QPointF(19.5, 7), QPointF(19.5, 17))
        elif k == "file":
            path = QPainterPath()
            path.moveTo(7, 4.5)
            path.lineTo(14, 4.5)
            path.lineTo(18, 8.5)
            path.lineTo(18, 19.5)
            path.lineTo(7, 19.5)
            path.closeSubpath()
            p.drawPath(path)
            p.drawLine(QPointF(9.5, 12), QPointF(15.5, 12))
            p.drawLine(QPointF(9.5, 15.5), QPointF(15.5, 15.5))
        elif k == "globe":
            p.drawEllipse(QRectF(4.5, 4.5, 15, 15))
            p.drawEllipse(QRectF(9, 4.5, 6, 15))
            p.drawLine(QPointF(4.5, 12), QPointF(19.5, 12))
        p.end()


class Chevron(QWidget):
    """展開／收合的箭頭（收合時朝右，展開時朝下）。"""

    def __init__(self):
        super().__init__()
        self.setFixedSize(14, 14)
        self.setFocusPolicy(Qt.NoFocus)  # 純裝飾：展開狀態由 SectionHeader 的 accessibleDescription 回報
        self.expanded = False

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(_color(THEME["tertiary"]), 1.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        if self.expanded:
            p.drawPolyline([QPointF(3, 5), QPointF(7, 9), QPointF(11, 5)])
        else:
            p.drawPolyline([QPointF(5, 3), QPointF(9, 7), QPointF(5, 11)])
        p.end()


class SectionHeader(_HoverRepaint, QWidget):
    """分組標題列：可點擊、滑過時淡淡加深（自己畫，不是 QPushButton，所以不吃按鈕樣式）。

    朗讀程式念 accessibleName（分組名稱）和 accessibleDescription（已展開／已收合），
    由 Section.set_expanded() 更新。
    """
    clicked = Signal()

    def __init__(self, title: str = ""):
        super().__init__()
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover)
        self.setFocusPolicy(Qt.TabFocus)
        if title:
            self.setAccessibleName(title)
        self.open = False
        self.set_open(False)

    def set_open(self, on: bool):
        self.open = on
        self.setAccessibleDescription(self.tr("已展開") if on else self.tr("已收合，按空白鍵展開"))
        self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit()

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter):
            self.clicked.emit()
        else:
            super().keyPressEvent(e)

    def paintEvent(self, _):
        if not (self.underMouse() or self.hasFocus()):
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, 0 if self.open else -1)
        path = QPainterPath()
        rad = 11
        if self.open:  # 展開時只有上方兩角是圓的
            path.moveTo(r.left(), r.bottom())
            path.lineTo(r.left(), r.top() + rad)
            path.quadTo(r.left(), r.top(), r.left() + rad, r.top())
            path.lineTo(r.right() - rad, r.top())
            path.quadTo(r.right(), r.top(), r.right(), r.top() + rad)
            path.lineTo(r.right(), r.bottom())
            path.closeSubpath()
        else:
            path.addRoundedRect(r, rad, rad)
        p.fillPath(path, _color(THEME["hover"]))
        if self.hasFocus():
            p.setPen(QPen(_color(THEME["accent"]), 2))
            p.setBrush(Qt.NoBrush)
            p.drawPath(path)
        p.end()


class Section(QFrame):
    """可收合的分組卡片（像 macOS 系統設定）：標題列（圖示＋名稱＋摘要＋箭頭），點一下展開設定列。"""
    toggled = Signal(bool)

    def __init__(self, key: str, title: str, icon: str, color: str):
        super().__init__()
        self.key = key
        self.setObjectName("card")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.header = SectionHeader(title)
        self.header.clicked.connect(lambda: self.set_expanded(not self.body.isVisible()))
        hl = QHBoxLayout(self.header)
        hl.setContentsMargins(12, 8, 14, 8)
        hl.setSpacing(10)
        hl.addWidget(Icon(icon, color))
        self.title = label(title, "rowTitle")
        hl.addWidget(self.title)
        hl.addStretch()
        self.summary = label("", "subtitle")
        hl.addWidget(self.summary)
        self.chevron = Chevron()
        hl.addWidget(self.chevron)
        lay.addWidget(self.header)
        self.line = hairline()
        lay.addWidget(self.line)
        self.body = Card()
        self.body.setObjectName("sectionBody")  # 外層已經是卡片，內層不要再畫邊框
        lay.addWidget(self.body)
        self.body.setVisible(False)
        self.line.setVisible(False)

    def add(self, widget: QWidget) -> QWidget:
        return self.body.add(widget)

    def set_row_visible(self, widget: QWidget, visible: bool):
        self.body.set_row_visible(widget, visible)

    def set_expanded(self, on: bool):
        self.body.setVisible(on)
        self.chevron.expanded = on
        self.chevron.update()
        self.line.setVisible(on)
        self.header.set_open(on)
        self.toggled.emit(on)

    def expanded(self) -> bool:
        return self.body.isVisibleTo(self)


def _name(widget: QWidget, title: str, hint: str = ""):
    """把列的標題設成控制項的無障礙名稱（說明文字當描述）；已經有名稱的不覆蓋。"""
    if not widget.accessibleName():
        widget.setAccessibleName(title)
    if hint and not widget.accessibleDescription():
        widget.setAccessibleDescription(hint)


def labeled_row(title: str, widget: QWidget) -> QWidget:
    """native_common.form_row() 再加上無障礙名稱：朗讀程式念「畫面更新率上限，下拉式方塊」而不只是選項值。

    分段控制的每顆按鈕本身有文字，名稱設在外框上，按鈕的描述寫上所屬的標題。
    """
    _name(widget, title)
    if isinstance(widget, Segmented):
        for b in widget.buttons.values():
            b.setAccessibleDescription(title)
    return form_row(title, widget)


def switch_row(title: str, sw: Switch, hint: str = "") -> QWidget:
    """一列：左邊標題（可加灰色說明），右邊開關。標題會設成開關的無障礙名稱、說明設成描述。"""
    _name(sw, title, hint)
    w = QWidget()
    w.setObjectName("row")
    lay = QHBoxLayout(w)
    lay.setContentsMargins(14, 8, 14, 8)
    text = QVBoxLayout()
    text.setSpacing(1)
    text.addWidget(label(title))
    if hint:
        text.addWidget(_hint(hint, wrap=True))
    lay.addLayout(text, 1)
    lay.addWidget(sw, 0, Qt.AlignVCenter)
    # 點整列也能切換（同系統設定），只回應左鍵
    w.mousePressEvent = lambda e: e.button() == Qt.LeftButton and sw.isEnabled() and sw.toggle()
    return w


def block_row(title: str, widget: QWidget, hint: str = "", extra: QWidget | None = None) -> QWidget:
    """一列：上方標題，下方是較寬的內容（標籤群、輸入框）。標題會設成內容的無障礙名稱。

    內容是容器（例如輸入框＋提示的組合）時，名稱也設給裡面第一個可輸入的元件。
    """
    _name(widget, title, hint)
    if not widget.focusPolicy() & Qt.TabFocus:
        for child in widget.findChildren(QLineEdit):
            _name(child, title, hint)
            break
    w = QWidget()
    w.setObjectName("row")
    lay = QVBoxLayout(w)
    lay.setContentsMargins(14, 8, 14, 10)
    lay.setSpacing(6)
    head = QHBoxLayout()
    head.addWidget(label(title))
    if hint:
        head.addWidget(_hint(hint))
    head.addStretch()
    if extra is not None:
        head.addWidget(extra)
    lay.addLayout(head)
    lay.addWidget(widget)
    return w


def link_button(text: str, name: str = "link") -> QPushButton:
    b = QPushButton(text)
    b.setObjectName(name)
    b.setCursor(Qt.PointingHandCursor)
    return b


class IntField(QLineEdit):
    """整數輸入框（取代 QSpinBox：輸入框的樣式由 native_app 統一決定，QSpinBox 的箭頭則沒有）。"""

    def __init__(self, lo: int, hi: int, default: int):
        super().__init__(str(default))
        self.lo, self.hi, self.default = lo, hi, default
        self.setValidator(QIntValidator(lo, hi, self))
        self.setFixedWidth(_text_width(self, "8888", 70))
        self.setAlignment(Qt.AlignRight)
        self.editingFinished.connect(lambda: self.setValue(self.value()))  # 空白或超出範圍時改回合法值

    def value(self) -> int:
        try:
            return max(self.lo, min(self.hi, int(self.text())))
        except ValueError:
            return self.default

    def setValue(self, v: int):
        v = str(max(self.lo, min(self.hi, int(v))))
        if self.text() != v:
            self.setText(v)


def _text_width(w: QWidget, text: str, minimum: int) -> int:
    """輸入框要放得下 text 的寬度（字型量出來的，加上內距與清除鈕的空間），至少 minimum。

    提示文字會翻成英文（通常比中文長），不能只寫死像素寬度。
    """
    return max(minimum, QFontMetrics(w.font()).horizontalAdvance(text) + 32)


def _field(placeholder: str, width: int = 0, mono: bool = True) -> QLineEdit:
    e = QLineEdit()
    e.setPlaceholderText(placeholder)
    if width:
        e.setFixedWidth(_text_width(e, placeholder, width))
    if mono:
        # 等寬字由 native_app.stylesheet() 的 QLineEdit[mono="true"] 決定字型，字級跟著 App 的文字大小設定
        e.setProperty("mono", True)
    return e


# --------------------------------------------------------------------------- #
#  進階選項面板
# --------------------------------------------------------------------------- #
class AdvancedOptions(QWidget):
    """進階選項：可收合的分組卡片。任何變更都會發出 changed 並自動存進 QSettings。"""
    changed = Signal()

    def __init__(self, api=None, toast=None, settings: QSettings | None = None):
        super().__init__()
        self.api, self.toast = api, toast or (lambda *_a, **_k: None)
        self.settings = settings if settings is not None else QSettings("YTDownloader", "NativeApp")
        self.info: dict | None = None
        self.mode = "av"
        self._restoring = False
        self._saved: dict = {}  # 上次寫進 QSettings 的值（只寫有變動的）
        self._before_reset: dict | None = None  # 「恢復預設」前的值，給「復原」用
        self._reset_values: dict = {}  # 剛恢復預設後的值；之後值變了就不再提供復原
        self.cookie_exists = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        head = QHBoxLayout()
        head.addWidget(label(self.tr("進階選項"), "sectionHeader"))
        head.addStretch()
        # 「恢復預設」之後在原位顯示提示＋「復原」，直到再改任何選項或 15 秒後
        self.reset_note = label(self.tr("已恢復預設"), "subtitle")
        self.undo_btn = link_button(self.tr("復原"))
        self.undo_btn.setAccessibleName(self.tr("復原進階選項"))
        self.undo_btn.clicked.connect(self.undo_reset)
        self._undo_timer = QTimer(self, singleShot=True, interval=15000)
        self._undo_timer.timeout.connect(self._drop_undo)
        # 範圍寫在按鈕上：設定頁另有「重設所有偏好」，兩個不要搞混
        self.reset_btn = link_button(self.tr("進階選項恢復預設"))
        self.reset_btn.setToolTip(self.tr("只重設下面這些進階選項，不影響畫質、格式和設定頁的偏好；可以復原"))
        self.reset_btn.clicked.connect(self.reset)
        for w in (self.reset_note, self.undo_btn, self.reset_btn):
            head.addWidget(w)
        self.reset_note.hide()
        self.undo_btn.hide()
        lay.addLayout(head)

        self.sections: dict[str, Section] = {}
        self._build_video()
        self._build_audio()
        self._build_subs()
        self._build_clip()
        self._build_sponsor()
        self._build_files()
        self._build_network()
        for s in self.sections.values():
            lay.addWidget(s)
            s.toggled.connect(lambda on, k=s.key: self._save_expanded(k, on))

        self.restore_settings()
        self.apply_theme(tokens(QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark))
        self.changed.connect(self._on_changed)
        self._on_changed()
        self.fetch_cookie_status()

    def fetch_cookie_status(self, attempt: int = 0):
        """查詢 cookies.txt 是否已上傳。App 剛開時引擎可能還沒開始聽連接埠：失敗就每 0.5 秒重試，最多 30 次。"""
        if self.api is None:
            return

        def retry(_msg):
            if attempt < 30:
                QTimer.singleShot(500, lambda: self.fetch_cookie_status(attempt + 1))

        self.api.get("/api/cookies", self._on_cookie_status, retry)

    # ---------- 建立各分組 ----------
    def _section(self, key, title, icon, color) -> Section:
        s = Section(key, title, icon, color)
        self.sections[key] = s
        return s

    def _switch(self, key: str) -> Switch:
        sw = Switch(bool(DEFAULTS[key]))
        sw.toggled.connect(self.changed)
        return sw

    def _seg(self, items) -> Segmented:
        # 方向鍵切換：Qt 的 QAbstractButton 在同一個 QButtonGroup 裡本來就支援（tests 有鎖住）
        seg = Segmented(_items(items))
        seg.changed.connect(lambda *_: self.changed.emit())
        return seg

    def _pop(self, items) -> PopUp:
        pop = PopUp(_items(items))
        pop.currentIndexChanged.connect(lambda *_: self.changed.emit())
        return pop

    def _build_video(self):
        s = self._section("video", self.tr("影片"), "video", "#FF3B30")
        self.codec = self._seg(VCODECS)
        self.max_fps = self._pop(FPS_LIMITS)
        self.hdr = self._seg(HDR)
        self.recode = self._switch("recode")
        self.prefer_size = self._switch("prefer_size")
        self.premium = self._switch("premium")
        s.add(labeled_row(self.tr("編碼偏好"), self.codec))
        s.add(labeled_row(self.tr("畫面更新率上限"), self.max_fps))
        s.add(labeled_row(self.tr("動態範圍"), self.hdr))
        s.add(switch_row(self.tr("一律轉檔成選擇的格式"), self.recode,
                         self.tr("原始影片的格式不相容時重新轉檔，比較慢，但一定是你選的格式")))
        s.add(switch_row(self.tr("偏好較小檔案"), self.prefer_size, self.tr("同條件下優先選擇檔案最小者")))
        s.add(switch_row(self.tr("YouTube Premium 高位元率"), self.premium,
                         self.tr("優先下載 Premium 專屬的 1080p 高位元率串流（需在「網路」設定 Premium 帳號的 Cookie）")))

    def _build_audio(self):
        s = self._section("audio", self.tr("音訊"), "audio", "#FF2D55")
        self.tracks = ChipGroup(empty=self.tr("解析影片後顯示可用的音軌"))
        self.tracks.changed.connect(self.changed)
        self.prefer_acodec = self._seg(ACODEC_PREFER)
        self.allow_drc = self._switch("allow_drc")
        self.r_tracks = s.add(block_row(self.tr("音軌語言"), self.tracks,
                                        self.tr("可複選，多選會一併合併進影片（建議 MKV）")))
        self.r_prefer_acodec = s.add(labeled_row(self.tr("合併時音訊編碼偏好"), self.prefer_acodec))
        s.add(switch_row(self.tr("允許 DRC 音軌"), self.allow_drc, self.tr("動態範圍壓縮版本（音量較平均）")))

    def _build_subs(self):
        s = self._section("subs", self.tr("字幕"), "subs", "#FF9500")
        self.subs = ChipGroup(empty=self.tr("解析影片後顯示上傳者字幕"))
        self.subs.changed.connect(self.changed)
        self.autos = ChipGroup(empty=self.tr("解析影片後顯示自動字幕"))
        self.autos.changed.connect(self.changed)
        self.auto_search = _field(self.tr("搜尋語言，例：中文、zh、Japanese…"), mono=False)
        self.auto_search.setAccessibleName(self.tr("搜尋自動字幕語言"))
        self.auto_search.textChanged.connect(self.autos.filter)
        autos_box = QWidget()
        al = QVBoxLayout(autos_box)
        al.setContentsMargins(0, 0, 0, 0)
        al.setSpacing(8)
        al.addWidget(self.auto_search)
        self.autos_scroll = FitScroll(150)
        self.autos_scroll.setWidgetResizable(True)
        self.autos_scroll.setFrameShape(QFrame.NoFrame)
        self.autos_scroll.setFocusPolicy(Qt.NoFocus)  # 捲動區本身不是 Tab 停留點（看不到焦點）
        self.autos_scroll.setWidget(self.autos)
        self.autos_scroll.viewport().setAutoFillBackground(False)  # 透明，露出卡片底色
        self.autos.setAutoFillBackground(False)
        self.autos_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.auto_search.textChanged.connect(lambda *_: self.autos_scroll.updateGeometry())
        al.addWidget(self.autos_scroll)
        quick = QWidget()
        ql = QHBoxLayout(quick)
        ql.setContentsMargins(0, 0, 0, 0)
        ql.setSpacing(2)
        for text, name, fn in (
                (self.tr("中文"), self.tr("選擇中文字幕"), lambda: self.quick_pick(r"^zh(-Hant|-TW|-HK|-Hans|-CN)?$")),
                (self.tr("英文"), self.tr("選擇英文字幕"), lambda: self.quick_pick(r"^en(-[A-Z]{2})?$|^en-orig$")),
                (self.tr("清除"), self.tr("清除字幕選擇"), self.clear_subs)):
            b = link_button(text)
            b.setAccessibleName(name)
            b.clicked.connect(fn)
            ql.addWidget(b)
        self.sub_format = self._seg(SUB_FORMATS)
        self.sub_embed = self._switch("sub_embed")
        self.sub_keep = self._switch("sub_keep")
        self.sub_all = self._switch("sub_all")
        s.add(block_row(self.tr("上傳者字幕"), self.subs, self.tr("可複選"), quick))
        s.add(block_row(self.tr("自動字幕／自動翻譯"), autos_box, self.tr("可複選")))
        s.add(labeled_row(self.tr("字幕格式"), self.sub_format))
        self.r_sub_embed = s.add(switch_row(self.tr("嵌入影片"), self.sub_embed,
                                            self.tr("寫入 MP4 / MKV / WebM 字幕軌")))
        self.r_sub_keep = s.add(switch_row(self.tr("同時另存字幕檔"), self.sub_keep, self.tr("嵌入後仍輸出獨立字幕檔")))
        s.add(switch_row(self.tr("下載所有上傳者字幕"), self.sub_all, self.tr("忽略上方的選擇")))

    def _build_clip(self):
        s = self._section("clip", self.tr("剪輯"), "clip", "#AF52DE")
        self.sections_edit = _field(self.tr("例：0:30-1:45, 3:00-end"))
        self.sections_edit.textChanged.connect(lambda *_: self.changed.emit())
        self.range_hint = label("", wrap=True)  # 紅字用 rich text（app 的 QSS 會蓋過 palette 顏色）
        self.range_hint.setTextFormat(Qt.RichText)
        self.chapters = QWidget()
        self.chapter_flow = FlowLayout(self.chapters)
        box = QWidget()
        bl = QVBoxLayout(box)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(6)
        bl.addWidget(self.sections_edit)
        bl.addWidget(self.range_hint)
        self.chapter_hint = _hint(self.tr("點章節即可加入範圍："))
        bl.addWidget(self.chapter_hint)
        bl.addWidget(self.chapters)
        clear = link_button(self.tr("清除"))
        clear.setAccessibleName(self.tr("清除時間範圍"))
        clear.clicked.connect(self.sections_edit.clear)
        self.split_chapters = self._switch("split_chapters")
        self.force_keyframes = self._switch("force_keyframes")
        self.live_from_start = self._switch("live_from_start")
        s.add(block_row(self.tr("時間範圍"), box, self.tr("只下載這些片段，可多段、逗號分隔"), clear))
        s.add(switch_row(self.tr("依章節切割成多個檔案"), self.split_chapters))
        s.add(switch_row(self.tr("切點強制關鍵影格"), self.force_keyframes, self.tr("切割更精準（需重新編碼，較慢）")))
        s.add(switch_row(self.tr("直播從頭下載"), self.live_from_start))
        self._render_chapters()

    def _build_sponsor(self):
        s = self._section("sponsor", "SponsorBlock", "skip", "#34C759")
        self.sb_remove = ChipGroup(_items((k, v) for k, v in SPONSOR if k not in SPONSOR_NO_REMOVE))
        self.sb_mark = ChipGroup(_items(SPONSOR))
        self.sb_remove.changed.connect(self.changed)
        self.sb_mark.changed.connect(self.changed)
        s.add(block_row(self.tr("移除片段"), self.sb_remove, self.tr("從影片中剪掉社群標記的片段")))
        s.add(block_row(self.tr("標記為章節"), self.sb_mark, self.tr("保留片段，但加上章節標記")))

    def _build_files(self):
        s = self._section("files", self.tr("中繼資料與檔案"), "file", "#5856D6")
        self.embed_metadata = self._switch("embed_metadata")
        self.embed_chapters = self._switch("embed_chapters")
        self.embed_thumbnail = self._switch("embed_thumbnail")
        self.write_thumbnail = self._switch("write_thumbnail")
        self.thumb_format = self._seg(THUMB_FORMATS)
        self.write_description = self._switch("write_description")
        self.write_infojson = self._switch("write_infojson")
        self.write_comments = self._switch("write_comments")
        self.keep_original = self._switch("keep_original")
        self.template_preset = self._pop(TEMPLATES)
        self.template_preset.currentIndexChanged.connect(self._on_preset)
        self.template = _field(DEFAULT_TEMPLATE)
        self.template.textChanged.connect(self._sync_preset)
        self.template.textChanged.connect(lambda *_: self.changed.emit())
        self.restrict_filenames = self._switch("restrict_filenames")
        s.add(switch_row(self.tr("嵌入中繼資料"), self.embed_metadata, self.tr("標題、作者、日期、描述")))
        s.add(switch_row(self.tr("嵌入章節"), self.embed_chapters))
        s.add(switch_row(self.tr("嵌入封面縮圖"), self.embed_thumbnail))
        s.add(switch_row(self.tr("另存縮圖檔"), self.write_thumbnail))
        self.r_thumb_format = s.add(labeled_row(self.tr("縮圖格式"), self.thumb_format))
        s.add(switch_row(self.tr("另存影片說明"), self.write_description, self.tr(".description 文字檔")))
        s.add(switch_row(self.tr("另存完整資訊"), self.write_infojson, ".info.json"))
        s.add(switch_row(self.tr("下載留言"), self.write_comments, self.tr("寫入 info.json；留言多時會很慢")))
        s.add(switch_row(self.tr("保留合併前原始檔"), self.keep_original))
        self.template_preset.setAccessibleName(self.tr("常用檔名範本"))
        s.add(block_row(self.tr("檔名範本"), self.template, self.tr("用 %(title)s 這類代號組出檔名"),
                        self.template_preset))
        s.add(switch_row(self.tr("限制檔名字元"), self.restrict_filenames, self.tr("只用英數字，移除空白與特殊字元")))

    def _build_network(self):
        s = self._section("network", self.tr("網路"), "globe", "#007AFF")
        self.cookie_source = self._pop(COOKIE_SOURCES)
        self.cookie_status = label("", "subtitle")
        choose = link_button(self.tr("選擇檔案…"))
        choose.setAccessibleName(self.tr("選擇 cookies.txt 檔案"))
        choose.clicked.connect(self.choose_cookies)
        self.cookie_remove = link_button(self.tr("移除"), "destructiveLink")
        self.cookie_remove.setAccessibleName(self.tr("移除已上傳的 cookies.txt"))
        self.cookie_remove.clicked.connect(self.remove_cookies)
        cbox = QWidget()
        cl = QHBoxLayout(cbox)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(6)
        cl.addWidget(self.cookie_status)
        cl.addWidget(choose)
        cl.addWidget(self.cookie_remove)
        self.browser = self._pop(BROWSERS)
        self.proxy = _field("socks5://127.0.0.1:1080", 260)
        self.rate_limit = _field(self.tr("例：5M"), 110)
        self.geo = _field("TW", 70)
        self.geo.setMaxLength(2)
        self.fragments = QSlider(Qt.Horizontal)
        self.fragments.setRange(1, 16)
        self.fragments.setFixedWidth(170)
        self.fragments_value = label("4", "subtitle")
        self.fragments_value.setMinimumWidth(self.fragments_value.fontMetrics().horizontalAdvance("16") + 2)
        fbox = QWidget()
        fl = QHBoxLayout(fbox)
        fl.setContentsMargins(0, 0, 0, 0)
        fl.addWidget(self.fragments)
        fl.addWidget(self.fragments_value)
        self.fragments.valueChanged.connect(lambda v: self.fragments_value.setText(str(v)))
        self.fragments.valueChanged.connect(lambda *_: self.changed.emit())
        self.retries = IntField(0, 50, 10)
        self.retries.textChanged.connect(lambda *_: self.changed.emit())
        for e in (self.proxy, self.rate_limit, self.geo):
            e.textChanged.connect(lambda *_: self.changed.emit())
        s.add(labeled_row(self.tr("Cookie 來源"), self.cookie_source))
        self.r_cookie_file = s.add(form_row("cookies.txt", cbox))
        self.r_browser = s.add(labeled_row(self.tr("瀏覽器"), self.browser))
        s.add(labeled_row(self.tr("代理伺服器"), self.proxy))
        s.add(labeled_row(self.tr("限速（每秒）"), self.rate_limit))
        s.add(labeled_row(self.tr("地區（國碼）"), self.geo))
        _name(self.fragments, self.tr("同時下載的分段數"))
        s.add(form_row(self.tr("並行分段"), fbox))
        s.add(labeled_row(self.tr("重試次數"), self.retries))

    # ---------- 解析結果 / 模式 ----------
    def set_info(self, info: dict | None):
        """依解析結果更新可選的音軌、字幕、章節（換影片時清掉上一部的選擇）。"""
        self.info = info or {}
        tracks = self.info.get("audio_tracks") or []
        self.tracks.set_items([(t["lang"], self.tr("{track}（原音）").format(track=t.get("label", t["lang"]))
                                if t.get("original") else t.get("label", t["lang"])) for t in tracks])
        self.subs.set_items([(x["lang"], x.get("name") or x["lang"]) for x in self.info.get("subtitles") or []])
        self.autos.set_items([(x["lang"], x.get("name") or x["lang"]) for x in self.info.get("auto_captions") or []])
        self.auto_search.clear()
        self.autos_scroll.updateGeometry()
        self.sections_edit.clear()
        self._render_chapters()
        self.changed.emit()

    def set_mode(self, mode: str):
        """依下載模式隱藏用不到的分組／設定列（對應網頁版 applyMode）。"""
        self.mode = mode
        video = mode in ("av", "video")
        media = mode in ("av", "video", "audio")
        self.sections["video"].setVisible(video)
        self.sections["audio"].setVisible(mode in ("av", "audio"))
        self.sections["audio"].set_row_visible(self.r_prefer_acodec, mode == "av")
        self.sections["subs"].setVisible(mode != "thumb")
        self.sections["subs"].set_row_visible(self.r_sub_embed, video)
        self.sections["subs"].set_row_visible(self.r_sub_keep, video)
        self.sections["clip"].setVisible(media)
        self.sections["sponsor"].setVisible(media)
        self._on_changed()

    def reveal_section(self, key: str, focus: bool = False) -> bool:
        """展開分組並捲到它（例如切到字幕模式時、摘要的錯誤連結點下去時）。

        key：分組名稱 video／audio／subs／clip／sponsor／files／network，或別名 subtitles、sponsorblock、
        metadata、cookies。focus=True 時把焦點移到該分組最主要的輸入元件（例如剪輯的時間範圍），
        沒有就移到分組標題。分組因目前的下載模式被隱藏時不會強制顯示，回傳 False；不認得的 key 也回傳 False。
        """
        s = self.sections.get(SECTION_ALIASES.get(key, key))
        if s is None:
            return False
        if not s.expanded():
            s.set_expanded(True)  # 會發出 toggled → 記住展開狀態
        if s.isHidden():
            return False
        if focus:
            target = {"clip": self.sections_edit, "network": self.cookie_source,
                      "subs": self.auto_search if not self.subs.chips else None}.get(s.key)
            (target if target is not None and target.isVisible() else s.header).setFocus(Qt.OtherFocusReason)
        # 展開後版面要等下一輪事件才會算好，捲動要延後
        QTimer.singleShot(0, self, lambda: self._scroll_to(s))  # context=self：面板被刪掉時不會再呼叫
        return True

    def _scroll_to(self, s: Section):
        w = self.parentWidget()
        while w is not None and not isinstance(w, QScrollArea):
            w = w.parentWidget()
        if w is None or not s.isVisible():
            return
        w.ensureWidgetVisible(s, 0, 12)  # 盡量整個分組都看得到
        w.ensureWidgetVisible(s.header, 0, 12)  # 分組比畫面高時，至少標題要在畫面上方

    def _render_chapters(self):
        while self.chapter_flow.count():
            w = self.chapter_flow.takeAt(0).widget()
            w and w.deleteLater()
        chapters = (self.info or {}).get("chapters") or []
        for c in chapters[:40]:
            title = (c.get("title") or "")
            start = _ts(c.get("start"))
            b = Chip(f"{start}  {title[:18]}", checkable=False,
                     name=self.tr("加入章節 {start} {title}").format(start=start, title=title))
            b.setToolTip(title)
            b.clicked.connect(lambda _=False, ch=c: self.add_chapter(ch))
            self.chapter_flow.addWidget(b)
        self.chapter_hint.setVisible(bool(chapters))
        self.chapters.setVisible(bool(chapters))

    def add_chapter(self, ch: dict):
        end = ch.get("end")
        seg = f"{_ts(ch.get('start'))}-{_ts(end) if end else 'end'}"
        cur = self.sections_edit.text().strip().rstrip(",").strip()
        self.sections_edit.setText(f"{cur}, {seg}" if cur else seg)

    def quick_pick(self, pattern: str):
        rx = re.compile(pattern, re.IGNORECASE)
        subs = [k for k in self.subs.chips if rx.search(k)]
        if subs:
            self.subs.set_values(set(self.subs.values()) | set(subs))
        else:  # 沒有上傳者字幕時改選自動字幕
            self.autos.set_values(set(self.autos.values()) | {k for k in self.autos.chips if rx.search(k)})

    def clear_subs(self):
        self.subs.set_values(())
        self.autos.set_values(())

    # ---------- 輸出 ----------
    def network(self) -> dict:
        """網路選項（/api/info 與下載都要帶）。"""
        src = self.cookie_source.currentData()
        return {"proxy": self.proxy.text().strip(),
                "cookies_browser": self.browser.currentData() if src == "browser" else "",
                "geo_country": self.geo.text().strip(),
                "cookies_file": src == "file"}

    def apply(self, options: dict) -> dict:
        """把進階選項合併進 DownloadPage.options() 的結果，回傳新的 dict（不改動傳入的）。

        音軌／字幕語言與基本選項取聯集；其餘進階欄位覆寫基本選項的同名欄位。
        """
        o = copy.deepcopy(options or {})
        v = o.setdefault("video", {})
        v.update(codec=self.codec.value(), max_fps=self.max_fps.currentData(), hdr=self.hdr.value(),
                 recode=self.recode.isChecked(), prefer_size=self.prefer_size.isChecked(),
                 premium=self.premium.isChecked())
        a = o.setdefault("audio", {})
        a["languages"] = _unique([*(a.get("languages") or []), *self.tracks.values()])
        a.update(prefer_codec=self.prefer_acodec.value(), allow_drc=self.allow_drc.isChecked())
        s = o.setdefault("subs", {})
        s["languages"] = _unique([*(s.get("languages") or []), *self.subs.values()])
        s["auto_languages"] = _unique([*(s.get("auto_languages") or []), *self.autos.values()])
        s.update(format=self.sub_format.value(), embed=self.sub_embed.isChecked(),
                 keep_files=self.sub_keep.isChecked(), all=self.sub_all.isChecked())
        x = o.setdefault("extras", {})
        x.update(
            embed_metadata=self.embed_metadata.isChecked(), embed_chapters=self.embed_chapters.isChecked(),
            embed_thumbnail=self.embed_thumbnail.isChecked(), write_thumbnail=self.write_thumbnail.isChecked(),
            thumb_format=self.thumb_format.value(),
            sections=self.sections_edit.text().strip(), split_chapters=self.split_chapters.isChecked(),
            force_keyframes=self.force_keyframes.isChecked(), live_from_start=self.live_from_start.isChecked(),
            sponsor_remove=self.sb_remove.values(), sponsor_mark=self.sb_mark.values(),
            write_description=self.write_description.isChecked(), write_infojson=self.write_infojson.isChecked(),
            write_comments=self.write_comments.isChecked(), keep_original=self.keep_original.isChecked(),
            template=self.template.text().strip() or DEFAULT_TEMPLATE,
            restrict_filenames=self.restrict_filenames.isChecked(),
            rate_limit=self.rate_limit.text().strip(), fragments=self.fragments.value(),
            retries=self.retries.value(),
        )
        o["network"] = self.network()
        return o

    def error(self) -> str:
        """送出前檢查：有錯誤（例如時間範圍格式不對）回傳訊息，沒有回傳空字串。"""
        return range_error(self.sections_edit.text())

    # ---------- 狀態更新 ----------
    def _on_changed(self, *_):
        src = self.cookie_source.currentData()
        net = self.sections["network"]
        net.set_row_visible(self.r_cookie_file, src == "file")
        net.set_row_visible(self.r_browser, src == "browser")
        self.cookie_remove.setVisible(self.cookie_exists)
        self.cookie_status.setText(self.tr("已上傳") if self.cookie_exists else self.tr("尚未上傳"))
        self.sections["files"].set_row_visible(
            self.r_thumb_format, self.write_thumbnail.isChecked() or self.embed_thumbnail.isChecked())
        self.sections["audio"].set_row_visible(self.r_tracks, bool(self.tracks.chips) or not self.info)
        self._render_range_hint()
        self._update_summaries()
        if not self._restoring:
            vals = self._values()
            if self._before_reset is not None and vals != self._reset_values:
                self._drop_undo()  # 恢復預設之後又改了選項：不再提供復原（避免蓋掉新的修改）
            self.save_settings(vals)

    def _render_range_hint(self):
        err = self.error()
        self.range_hint.setText(f'<span style="color:{THEME["red"]}">{html.escape(err)}</span>' if err else "")
        self.range_hint.setVisible(bool(err))

    def _update_summaries(self):
        def join(*bits):
            return " · ".join(b for b in bits if b)
        sm = self.sections
        sm["video"].summary.setText(join(self.codec.buttons[self.codec.value()].text() if self.codec.value() else "",
                                         self.max_fps.currentData() and self.max_fps.currentText(),
                                         self.hdr.value() and self.hdr.buttons[self.hdr.value()].text(),
                                         "Premium" if self.premium.isChecked() else ""))
        n_tracks = len(self.tracks.values())
        sm["audio"].summary.setText(_tr("AdvancedOptions", "%n 條音軌", None, n_tracks) if n_tracks else "")
        n_subs = len(self.subs.values()) + len(self.autos.values())
        sm["subs"].summary.setText(join(self.tr("全部上傳者字幕") if self.sub_all.isChecked()
                                        else (_tr("AdvancedOptions", "%n 種語言", None, n_subs) if n_subs else ""),
                                        self.sub_format.buttons[self.sub_format.value()].text()
                                        if n_subs or self.sub_all.isChecked() else ""))
        n_ranges = len([c for c in re.split(r"[,\n;]+", self.sections_edit.text()) if c.strip()])
        sm["clip"].summary.setText(join(_tr("AdvancedOptions", "%n 段", None, n_ranges) if n_ranges else "",
                                        self.tr("依章節切割") if self.split_chapters.isChecked() else ""))
        sb = len(self.sb_remove.values()), len(self.sb_mark.values())
        sm["sponsor"].summary.setText(join(_tr("AdvancedOptions", "移除 %n 類", None, sb[0]) if sb[0] else "",
                                           _tr("AdvancedOptions", "標記 %n 類", None, sb[1]) if sb[1] else ""))
        src = self.cookie_source.currentData()
        rate = self.rate_limit.text().strip()
        sm["network"].summary.setText(join("cookies.txt" if src == "file" else
                                           (self.browser.currentText() if src == "browser" else ""),
                                           self.tr("代理") if self.proxy.text().strip() else "",
                                           self.tr("限速 {rate}").format(rate=rate) if rate else ""))
        sm["files"].summary.setText("")
        for s in sm.values():  # 朗讀程式念分組標題時一併念出摘要（例如「字幕，2 種語言 · SRT」）
            s.header.setAccessibleName(
                self.tr("{title}，{summary}").format(title=s.title.text(), summary=s.summary.text())
                if s.summary.text() else s.title.text())

    def _on_preset(self, *_):
        v = self.template_preset.currentData()
        if v == "custom":
            self.template.setFocus()
        elif v and self.template.text() != v:
            self.template.setText(v)

    def _sync_preset(self, text: str):
        idx = self.template_preset.findData(text)
        self.template_preset.blockSignals(True)
        self.template_preset.setCurrentIndex(idx if idx >= 0 else self.template_preset.findData("custom"))
        self.template_preset.blockSignals(False)

    # ---------- Cookie ----------
    def _on_cookie_status(self, r):
        self.cookie_exists = bool((r or {}).get("exists"))
        if not self.cookie_exists and self.cookie_source.currentData() == "file":
            self.cookie_source.setCurrentIndex(self.cookie_source.findData(""))
        self._on_changed()

    def choose_cookies(self):
        path, _ = QFileDialog.getOpenFileName(self, self.tr("選擇 cookies.txt"), "",
                                              self.tr("Cookie 檔 (*.txt);;所有檔案 (*)"))
        if path:
            self.upload_cookies(Path(path))

    def upload_cookies(self, path: Path, done=None):
        """上傳 cookies.txt 並改用它；成功後呼叫 done()（例如設定頁接著重新檢查 Premium 狀態）。"""
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            self.toast(self.tr("無法讀取檔案：{error}").format(error=e), error=True)
            return
        if self.api is None:
            return

        def ok(r):
            self._on_cookie_status(r)
            self.cookie_source.setCurrentIndex(self.cookie_source.findData("file"))
            self.toast(self.tr("已上傳 cookies.txt"))
            if done:
                done()

        self.api.post("/api/cookies", {"text": text}, ok,
                      lambda m: self.toast(self.tr("上傳失敗：{error}").format(error=m), error=True))

    def remove_cookies(self):
        if self.api is None:
            return
        self.api.delete("/api/cookies", self._on_cookie_status,
                        lambda m: self.toast(self.tr("移除失敗：{error}").format(error=m), error=True))

    # ---------- 外觀 ----------
    def apply_theme(self, t: dict[str, str]):
        """跟著主視窗切換淺色／深色（主視窗的 apply_theme 裡呼叫）。

        面板本身不寫 QSS：按鈕／選單／輸入框的樣式全由 native_app.stylesheet() 決定（macOS 上是系統原生樣式），
        這裡只更新自己畫的元件（開關、標籤、箭頭、標題列）用的顏色。
        """
        THEME.update(t)
        for w in self.findChildren(QWidget):
            if isinstance(w, (Switch, Chip, Chevron, SectionHeader)):
                w.update()
        self._render_range_hint()  # 重畫錯誤訊息的紅字（只換顏色，不用重新存設定）

    # ---------- 設定儲存 / 還原 ----------
    def _values(self) -> dict:
        return {
            "codec": self.codec.value(), "max_fps": self.max_fps.currentData(), "hdr": self.hdr.value(),
            "recode": self.recode.isChecked(), "prefer_size": self.prefer_size.isChecked(),
            "premium": self.premium.isChecked(), "prefer_acodec": self.prefer_acodec.value(),
            "allow_drc": self.allow_drc.isChecked(), "sub_format": self.sub_format.value(),
            "sub_embed": self.sub_embed.isChecked(), "sub_keep": self.sub_keep.isChecked(),
            "sub_all": self.sub_all.isChecked(), "split_chapters": self.split_chapters.isChecked(),
            "force_keyframes": self.force_keyframes.isChecked(), "live_from_start": self.live_from_start.isChecked(),
            "sponsor_remove": self.sb_remove.values(), "sponsor_mark": self.sb_mark.values(),
            "embed_metadata": self.embed_metadata.isChecked(), "embed_chapters": self.embed_chapters.isChecked(),
            "embed_thumbnail": self.embed_thumbnail.isChecked(), "write_thumbnail": self.write_thumbnail.isChecked(),
            "thumb_format": self.thumb_format.value(), "write_description": self.write_description.isChecked(),
            "write_infojson": self.write_infojson.isChecked(), "write_comments": self.write_comments.isChecked(),
            "keep_original": self.keep_original.isChecked(), "template": self.template.text().strip(),
            "restrict_filenames": self.restrict_filenames.isChecked(),
            "cookie_source": self.cookie_source.currentData(), "browser": self.browser.currentData(),
            "proxy": self.proxy.text().strip(), "rate_limit": self.rate_limit.text().strip(),
            "geo": self.geo.text().strip(), "fragments": self.fragments.value(), "retries": self.retries.value(),
        }

    def _set_values(self, vals: dict):
        def pick(seg_or_pop, value, items):
            keys = [k for k, _ in items]
            value = value if value in keys else keys[0]
            if isinstance(seg_or_pop, Segmented):
                seg_or_pop.set_value(value)
            else:
                seg_or_pop.setCurrentIndex(seg_or_pop.findData(value))

        def ints(v, default, lo, hi):
            try:
                return max(lo, min(hi, int(v)))
            except (TypeError, ValueError):
                return default

        def lst(v):
            if isinstance(v, str):
                return [v] if v else []
            return list(v or [])

        self._restoring = True
        try:
            pick(self.codec, vals["codec"], VCODECS)
            pick(self.max_fps, vals["max_fps"], FPS_LIMITS)
            pick(self.hdr, vals["hdr"], HDR)
            pick(self.prefer_acodec, vals["prefer_acodec"], ACODEC_PREFER)
            pick(self.sub_format, vals["sub_format"], SUB_FORMATS)
            pick(self.thumb_format, vals["thumb_format"], THUMB_FORMATS)
            pick(self.cookie_source, vals["cookie_source"], COOKIE_SOURCES)
            pick(self.browser, vals["browser"], BROWSERS)
            for key in ("recode", "prefer_size", "premium", "allow_drc", "sub_embed", "sub_keep", "sub_all",
                        "split_chapters", "force_keyframes", "live_from_start", "embed_metadata", "embed_chapters",
                        "embed_thumbnail", "write_thumbnail", "write_description", "write_infojson",
                        "write_comments", "keep_original", "restrict_filenames"):
                getattr(self, key).setChecked(_to_bool(vals[key]))
            self.sb_remove.set_values(lst(vals["sponsor_remove"]))
            self.sb_mark.set_values(lst(vals["sponsor_mark"]))
            self.template.setText(str(vals["template"] or DEFAULT_TEMPLATE))
            self._sync_preset(self.template.text())
            self.proxy.setText(str(vals["proxy"] or ""))
            self.rate_limit.setText(str(vals["rate_limit"] or ""))
            self.geo.setText(str(vals["geo"] or ""))
            self.fragments.setValue(ints(vals["fragments"], 4, 1, 16))
            self.fragments_value.setText(str(self.fragments.value()))
            self.retries.setValue(ints(vals["retries"], 10, 0, 50))
        finally:
            self._restoring = False

    def save_settings(self, vals: dict | None = None):
        """只寫有變動的值：每個按鍵、每次切換都會呼叫，Windows 上每個值都是一次登錄檔寫入。"""
        vals = self._values() if vals is None else vals
        changed = {k: v for k, v in vals.items() if self._saved.get(k, _UNSAVED) != v}
        if not changed:
            return
        st = self.settings
        st.beginGroup(SETTINGS_GROUP)
        for k, v in changed.items():
            st.setValue(k, v)
        st.endGroup()
        self._saved = vals

    def restore_settings(self):
        st = self.settings
        st.beginGroup(SETTINGS_GROUP)
        vals = {k: st.value(k, d) for k, d in DEFAULTS.items()}
        expanded = {k: _to_bool(st.value(f"open_{k}", False)) for k in self.sections}
        st.endGroup()
        self._set_values(vals)
        self._saved = self._values()  # 剛讀出來的值不用再寫回去
        for k, on in expanded.items():
            self.sections[k].blockSignals(True)
            self.sections[k].set_expanded(on)
            self.sections[k].blockSignals(False)

    def _save_expanded(self, key: str, on: bool):
        self.settings.beginGroup(SETTINGS_GROUP)
        self.settings.setValue(f"open_{key}", on)
        self.settings.endGroup()

    def reset(self):
        """進階選項恢復預設（不動目前影片的音軌／字幕／時間範圍選擇），之後可以 undo_reset() 復原。"""
        before = self._values()
        defaults = dict(DEFAULTS)
        self._set_values(defaults)
        after = self._values()
        if after == before:
            self.toast(self.tr("進階選項已經是預設值"))
            return
        self._before_reset, self._reset_values = before, after
        self.changed.emit()  # 會觸發 _on_changed：更新畫面並存檔
        had_focus = self.reset_btn.hasFocus()
        self.reset_note.show()
        self.undo_btn.show()
        self.reset_btn.hide()
        if had_focus:
            self.undo_btn.setFocus(Qt.OtherFocusReason)  # 鍵盤操作的人可以直接按空白鍵復原
        self._undo_timer.start()
        self._toast_with_undo(self.tr("已將進階選項恢復預設"))

    def undo_reset(self) -> bool:
        """復原上一次「進階選項恢復預設」；沒有可以復原的就回傳 False。"""
        before = self._before_reset
        if before is None:
            return False
        self._drop_undo()
        self._set_values(before)
        self.changed.emit()
        self.toast(self.tr("已復原進階選項"))
        return True

    def can_undo_reset(self) -> bool:
        return self._before_reset is not None

    def _drop_undo(self):
        self._before_reset = None
        self._undo_timer.stop()
        had_focus = self.undo_btn.hasFocus()
        self.reset_note.hide()
        self.undo_btn.hide()
        self.reset_btn.show()
        if had_focus:
            self.reset_btn.setFocus(Qt.OtherFocusReason)  # 焦點不要掉到看不見的按鈕上

    def _toast_with_undo(self, text: str):
        """主視窗的 toast 支援 actions 參數（C1 加的）時附上「復原」；舊版只顯示文字（標題列旁也有復原鈕）。"""
        try:
            params = inspect.signature(self.toast).parameters
        except (TypeError, ValueError):
            params = {}
        if "actions" in params or any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()):
            self.toast(text, actions=[(self.tr("復原"), self.undo_reset)])
        else:
            self.toast(text)
