"""原生介面的播放清單選取元件（PySide6），外觀沿用 native_app.py 的 Apple 風格。

清單用 QListView + model/delegate 繪製，數百部也不卡；縮圖只在該列實際畫到畫面上時才載入，
同時最多 6 個請求，捲走的列不會再去下載。

    view = PlaylistView(image_loader=api.image)
    view.set_playlist(info)              # /api/info 回傳的 {type: "playlist", ...}
    view.selectionChanged.connect(...)   # 已選幾部
    options["playlist"] = True
    options["playlist_items"] = view.playlist_items()   # 例如 "1-3,5,7-9"
"""
from __future__ import annotations

import re
from collections.abc import Callable, Iterable

from PySide6.QtCore import (
    QAbstractListModel,
    QEvent,
    QModelIndex,
    QPointF,
    QRect,
    QRectF,
    QSize,
    QSortFilterProxyModel,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPalette, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QListView,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from native_app import Api, fmt_duration, label, rounded, tokens

ImageLoader = Callable[[str, Callable[[QPixmap], None]], None]

ENTRY_ROLE = Qt.UserRole + 1
SEARCH_ROLE = Qt.UserRole + 2

ROW_H = 56
THUMB_W, THUMB_H, THUMB_R = 80, 45, 6
PAD, CHECK = 12, 20  # 列左右內距、勾選圈直徑
MAX_INFLIGHT = 6
SEARCH_DEBOUNCE_ROWS = 800  # 超過這個數量時，搜尋改成打字停一下才篩選


# --------------------------------------------------------------------------- #
#  序號 ↔ 文字
# --------------------------------------------------------------------------- #
def compress_indexes(indexes: Iterable[int]) -> str:
    """[1, 2, 3, 5, 7, 8] → "1-3,5,7-8"（yt-dlp 的 playlist_items 格式）。"""
    nums = sorted(set(indexes))
    parts: list[str] = []
    i = 0
    while i < len(nums):
        j = i
        while j + 1 < len(nums) and nums[j + 1] == nums[j] + 1:
            j += 1
        parts.append(str(nums[i]) if i == j else f"{nums[i]}-{nums[j]}")
        i = j + 1
    return ",".join(parts)


_DASH = r"[-–—~～:：]"


def parse_range(text: str, valid: Iterable[int]) -> set[int]:
    """「1-10, 15」→ {1..10, 15}。看不懂或超出清單範圍時丟 ValueError（訊息可直接給使用者看）。"""
    valid = set(valid)
    if not valid:
        raise ValueError("這個播放清單沒有影片")
    text = (text or "").strip()
    if not text:
        raise ValueError("請輸入範圍，例如 1-10, 15")
    text = re.sub(rf"\s*{_DASH}\s*", "-", text)
    picked: set[int] = set()
    top = max(valid)
    for tok in re.split(r"[,，、;；\s]+", text):
        if not tok:
            continue
        m = re.fullmatch(r"(\d+)(?:-(\d+))?", tok)
        if not m:
            raise ValueError(f"看不懂「{tok}」，請用像 1-10, 15 這樣的格式")
        a = int(m.group(1))
        b = int(m.group(2)) if m.group(2) else a
        if a > b:
            raise ValueError(f"「{tok}」的起點比終點大")
        if a < 1 or b > top:
            raise ValueError(f"「{tok}」超出範圍，這個清單只有 1–{top}")
        picked.update(n for n in range(a, b + 1) if n in valid)
    if not picked:
        raise ValueError("這個範圍裡沒有影片")
    return picked


# --------------------------------------------------------------------------- #
#  Model
# --------------------------------------------------------------------------- #
class PlaylistModel(QAbstractListModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.entries: list[dict] = []
        self.checked: list[bool] = []
        self.thumbs: dict[int, QPixmap] = {}

    def reset(self, entries: list[dict]):
        self.beginResetModel()
        self.entries = [e for e in entries if isinstance(e, dict)]
        self.checked = [True] * len(self.entries)
        self.thumbs = {}
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):  # noqa: B008
        return 0 if parent.isValid() else len(self.entries)

    def flags(self, index):
        if not index.isValid():
            return Qt.NoItemFlags
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        e = self.entries[index.row()]
        if role == Qt.DisplayRole:
            return e.get("title") or ""
        if role == Qt.CheckStateRole:
            return Qt.Checked if self.checked[index.row()] else Qt.Unchecked
        if role == ENTRY_ROLE:
            return e
        if role == SEARCH_ROLE:
            return f"{e.get('title') or ''}\n{e.get('uploader') or ''}"
        if role == Qt.ToolTipRole:
            return e.get("title") or ""
        return None

    def setData(self, index, value, role=Qt.EditRole):
        if role != Qt.CheckStateRole or not index.isValid():
            return False
        on = value in (Qt.Checked, Qt.Checked.value, True, 2)
        self.set_rows([index.row()], on)
        return True

    def set_rows(self, rows: Iterable[int], on: bool):
        rows = [r for r in rows if 0 <= r < len(self.entries) and self.checked[r] != on]
        for r in rows:
            self.checked[r] = on
        if rows:
            self.dataChanged.emit(self.index(min(rows)), self.index(max(rows)), [Qt.CheckStateRole])

    def set_exact(self, on_rows: set[int]):
        changed = [r for r in range(len(self.entries)) if self.checked[r] != (r in on_rows)]
        for r in changed:
            self.checked[r] = r in on_rows
        if changed:
            self.dataChanged.emit(self.index(min(changed)), self.index(max(changed)), [Qt.CheckStateRole])

    def set_thumb(self, row: int, pm: QPixmap):
        self.thumbs[row] = pm
        self.dataChanged.emit(self.index(row), self.index(row), [Qt.DecorationRole])


class FilterModel(QSortFilterProxyModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFilterRole(SEARCH_ROLE)
        self.setFilterCaseSensitivity(Qt.CaseInsensitive)


# --------------------------------------------------------------------------- #
#  Delegate：一列 = 勾選圈 · 序號 · 圓角縮圖 · 標題/上傳者 · 時長
# --------------------------------------------------------------------------- #
def _is_dark() -> bool:
    """跟著系統的深淺色（styleHints().colorScheme()）；平台回報 Unknown 時看調色盤亮度。"""
    app = QApplication.instance()
    scheme = app.styleHints().colorScheme() if app else Qt.ColorScheme.Unknown
    if scheme != Qt.ColorScheme.Unknown:
        return scheme == Qt.ColorScheme.Dark
    return QApplication.palette().color(QPalette.Window).lightness() < 128


def _scaled(font: QFont, factor: float) -> QFont:
    """字型縮放；字級可能是 px（例如 13px）也可能是 pt。"""
    f = QFont(font)
    if font.pixelSize() > 0:
        f.setPixelSize(max(1, round(font.pixelSize() * factor)))
    elif font.pointSizeF() > 0:
        f.setPointSizeF(font.pointSizeF() * factor)
    return f


_THEME: dict[str, QColor] = {}  # 目前的配色，由主視窗 apply_theme 設定（和整個 App 一致）


def set_theme(t: dict[str, str]):
    """tokens() 的色碼（#RRGGBB / #AARRGGBB）轉成 QColor 存起來。"""
    _THEME.clear()
    _THEME.update({k: QColor(v) for k, v in t.items()})


def _theme() -> dict[str, QColor]:
    if not _THEME:  # 單獨使用（測試、還沒套主題）時先跟著系統
        set_theme(tokens(_is_dark()))
    return _THEME


class PlaylistDelegate(QStyledItemDelegate):
    def __init__(self, owner: PlaylistView):
        super().__init__(owner)
        self.owner = owner
        self._anchor: int | None = None  # Shift 點選的起點（來源列）
        self._pressed: int | None = None  # 按下時的列，放開在同一列才算點擊

    def sizeHint(self, option, index):
        return QSize(option.rect.width(), ROW_H)

    @staticmethod
    def check_rect(r: QRect) -> QRect:
        return QRect(r.left() + PAD, r.top() + (r.height() - CHECK) // 2, CHECK, CHECK)

    def paint(self, p: QPainter, option: QStyleOptionViewItem, index: QModelIndex):
        t = _theme()
        src = self.owner.proxy.mapToSource(index)
        row = src.row()
        e = index.data(ENTRY_ROLE) or {}
        on = index.data(Qt.CheckStateRole) == Qt.Checked
        r = option.rect
        p.save()
        p.setRenderHint(QPainter.Antialiasing)

        if option.state & QStyle.State_Selected or option.state & QStyle.State_MouseOver:
            bg = QRectF(r.adjusted(4, 1, -4, -1))
            path = QPainterPath()
            path.addRoundedRect(bg, 8, 8)
            p.fillPath(path, QColor(t["select"] if option.state & QStyle.State_Selected else t["hover"]))

        # 勾選圈（照片 App 那種）
        cr = QRectF(self.check_rect(r)).adjusted(0.5, 0.5, -0.5, -0.5)
        if on:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(t["accent"]))
            p.drawEllipse(cr)
            pen = QPen(QColor(t["accent_text"]), 2.0, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            c = cr.center()
            p.drawPolyline([c + d for d in (QPointF(-5, 0.5), QPointF(-1.5, 4), QPointF(5, -3.5))])
        else:
            p.setPen(QPen(QColor(t["tertiary"]), 1.5))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(cr.adjusted(0.75, 0.75, -0.75, -0.75))

        x = r.left() + PAD + CHECK + 8
        base = QFont(option.font)
        small = _scaled(base, 0.9)

        # 序號
        p.setFont(small)
        p.setPen(QColor(t["secondary"]))
        num_w = max(22, QFontMetrics(small).horizontalAdvance(str(self.owner.max_index)) + 4)
        p.drawText(QRect(x, r.top(), num_w, r.height()), Qt.AlignVCenter | Qt.AlignRight, str(e.get("index", "")))
        x += num_w + 8

        # 縮圖
        tr = QRectF(x, r.top() + (r.height() - THUMB_H) / 2, THUMB_W, THUMB_H)
        pm = self.owner.model.thumbs.get(row)
        if pm is None:
            path = QPainterPath()
            path.addRoundedRect(tr, THUMB_R, THUMB_R)
            p.fillPath(path, QColor(t["track"]))
            if e.get("thumbnail"):
                self.owner.request_thumb(row)
        else:
            if not on:
                p.setOpacity(0.55)
            p.drawPixmap(tr.topLeft(), pm)
            p.setOpacity(1.0)
        x += THUMB_W + 10

        # 時長（靠右）
        dur = fmt_duration(e.get("duration"))
        dur_w = QFontMetrics(small).horizontalAdvance("00:00:00") + 4
        right = r.right() - PAD - 4
        if dur:
            p.setFont(small)
            p.setPen(QColor(t["secondary"]))
            p.drawText(QRect(right - dur_w, r.top(), dur_w, r.height()), Qt.AlignVCenter | Qt.AlignRight, dur)
        text_w = max(20, right - dur_w - 12 - x)

        # 標題 + 上傳者
        title_f = QFont(base)
        title_f.setWeight(QFont.DemiBold if on else QFont.Normal)
        fm, sfm = QFontMetrics(title_f), QFontMetrics(small)
        sub = e.get("uploader") or ""
        block = fm.height() + (sfm.height() + 2 if sub else 0)
        y = r.top() + (r.height() - block) // 2
        p.setFont(title_f)
        p.setPen(QColor(t["text"] if on else t["secondary"]))
        p.drawText(QRect(x, y, text_w, fm.height()), Qt.AlignVCenter | Qt.AlignLeft,
                   fm.elidedText(e.get("title") or "（沒有標題）", Qt.ElideRight, text_w))
        if sub:
            p.setFont(small)
            p.setPen(QColor(t["secondary"]))
            p.drawText(QRect(x, y + fm.height() + 2, text_w, sfm.height()), Qt.AlignVCenter | Qt.AlignLeft,
                       sfm.elidedText(sub, Qt.ElideRight, text_w))

        # 分隔細線（縮圖左緣開始，最後一列不畫）
        if index.row() < index.model().rowCount() - 1:
            p.setPen(QPen(QColor(t["sep"]), 1))
            p.drawLine(int(tr.left()), r.bottom(), r.right() - PAD, r.bottom())
        p.restore()

    def editorEvent(self, event, model, option, index):
        src = self.owner.proxy.mapToSource(index).row()
        if event.type() in (QEvent.MouseButtonPress, QEvent.MouseButtonDblClick):
            self._pressed = src if event.button() == Qt.LeftButton else None
            # 雙擊＝兩次單擊（各切換一次），不觸發其他預設行為
            return event.type() == QEvent.MouseButtonDblClick
        if event.type() == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
            if self._pressed != src:  # 從別列拖過來放開，不算點擊
                self._pressed = None
                return False
            self._pressed = None
            if event.modifiers() & Qt.ShiftModifier and self._anchor is not None:
                self.owner.toggle_span(self._anchor, src)
            else:
                self.owner.toggle_rows([src])
            self._anchor = src
            return True
        return False


class _List(QListView):
    """空白鍵切換目前列的勾選。"""

    def __init__(self, owner: PlaylistView):
        super().__init__()
        self.owner = owner

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter):
            rows = sorted({self.owner.proxy.mapToSource(i).row() for i in self.selectionModel().selectedIndexes()})
            if not rows and self.currentIndex().isValid():
                rows = [self.owner.proxy.mapToSource(self.currentIndex()).row()]
            if rows:
                self.owner.toggle_rows(rows)
            return
        super().keyPressEvent(e)


# --------------------------------------------------------------------------- #
#  元件
# --------------------------------------------------------------------------- #
class PlaylistView(QWidget):
    """播放清單選取：標題列、搜尋、範圍輸入、全選／全不選／反選，以及可勾選的清單。"""

    selectionChanged = Signal(int)

    def __init__(self, image_loader: ImageLoader | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.image_loader = image_loader or Api("").image  # 縮圖是完整網址，不需要 base
        self.info: dict = {}
        self.max_index = 0
        self._gen = 0
        self._queue: list[int] = []
        self._requested: set[int] = set()
        self._replies: dict = {}  # 載入中的縮圖（列 → QNetworkReply），換清單時取消
        self._inflight = 0
        self._pump_timer = QTimer(self)
        self._pump_timer.setSingleShot(True)
        self._pump_timer.timeout.connect(self._pump)

        self.model = PlaylistModel(self)
        self.proxy = FilterModel(self)
        self.proxy.setSourceModel(self.model)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        # 標題列
        head = QVBoxLayout()
        head.setSpacing(2)
        self.title = label("", "videoTitle", wrap=True, plain=True)  # 清單名稱是外來文字，不能當 HTML
        self.meta = label("", "subtitle", wrap=True, plain=True)
        head.addWidget(self.title)
        head.addWidget(self.meta)
        lay.addLayout(head)

        # 搜尋 + 範圍
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜尋標題或上傳者")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._search_changed)
        self._search_timer = QTimer(self)  # 很長的清單：打字停一下才篩選，不要每個字都卡一下
        self._search_timer.setSingleShot(True)
        self._search_timer.timeout.connect(lambda: self._on_search(self.search.text()))
        self.range = QLineEdit()
        self.range.setPlaceholderText("範圍，例如 1-10, 15")
        self.range.setClearButtonEnabled(True)
        self.range.setMinimumWidth(190)
        self.range.returnPressed.connect(self.apply_range)
        self.range.textEdited.connect(lambda _: self._set_error(""))
        self.range_btn = QPushButton("套用範圍")
        self.range_btn.setCursor(Qt.PointingHandCursor)
        self.range_btn.clicked.connect(self.apply_range)
        bar.addWidget(self.search, 3)
        bar.addWidget(self.range, 2)
        bar.addWidget(self.range_btn)
        lay.addLayout(bar)
        self.error = label("", "errorText", wrap=True)  # 紅字由 native_app.stylesheet() 的 #errorText 決定
        self.error.hide()
        lay.addWidget(self.error)

        # 已選幾部 + 全選／全不選／反選
        acts = QHBoxLayout()
        acts.setSpacing(4)
        self.count = label("", "subtitle")
        acts.addWidget(self.count, 1)
        self.btn_all, self.btn_none, self.btn_invert = (self._link(t, f) for t, f in (
            ("全選", self.select_all), ("全不選", self.select_none), ("反選", self.invert)))
        for b in (self.btn_all, self.btn_none, self.btn_invert):
            acts.addWidget(b)
        lay.addLayout(acts)

        # 清單
        self.card = QFrame()
        self.card.setObjectName("card")
        cl = QVBoxLayout(self.card)
        cl.setContentsMargins(0, 6, 0, 6)
        self.list = _List(self)
        self.list.setModel(self.proxy)
        self.delegate = PlaylistDelegate(self)
        self.list.setItemDelegate(self.delegate)
        self.list.setUniformItemSizes(True)
        self.list.setMouseTracking(True)
        self.list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.list.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.list.verticalScrollBar().setSingleStep(24)
        self.list.setFrameShape(QFrame.NoFrame)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # 透明底、不畫焦點框：用 palette／屬性，不寫 QSS（macOS 原生樣式下也一致）
        pal = self.list.palette()
        pal.setColor(QPalette.Base, Qt.transparent)
        self.list.setPalette(pal)
        self.list.setAttribute(Qt.WA_MacShowFocusRect, False)
        self.list.viewport().setAutoFillBackground(False)
        self.list.setMinimumHeight(ROW_H * 5 + 12)
        self.empty = label("", "subtitle")
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setMinimumHeight(ROW_H * 2)
        self.empty.hide()
        cl.addWidget(self.list)
        cl.addWidget(self.empty)
        lay.addWidget(self.card, 1)

        self.model.dataChanged.connect(
            lambda _a, _b, roles=(): (not roles or Qt.CheckStateRole in roles) and self._on_checks())
        self.model.modelReset.connect(self._on_checks)
        self.list.verticalScrollBar().valueChanged.connect(lambda _: self._schedule_pump())

    # ------------------------------------------------------------------ 公開 API
    def set_playlist(self, info: dict):
        """顯示 /api/info 回傳的播放清單，預設全選。"""
        self.info = info or {}
        self._gen += 1
        self._abort_thumbs()
        self.delegate._anchor = None
        self._queue.clear()
        self._requested.clear()
        self._inflight = 0
        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)
        self.proxy.setFilterFixedString("")
        self.range.clear()
        self._set_error("")
        self.model.reset(list(self.info.get("entries") or []))
        self.title.setText(self.info.get("title") or "播放清單")
        n = len(self.model.entries)
        self.max_index = max((e["index"] for e in self.model.entries if isinstance(e.get("index"), int)), default=n)
        bits =[self.info.get("uploader") or "", f"共 {n} 部"]
        total = self._total(range(n))
        if total:
            bits.append(f"總長 {total}")
        self.meta.setText(" · ".join(b for b in bits if b))
        self.list.scrollToTop()
        self._update_empty()

    def playlist_items(self) -> str:
        """已勾選的序號，連續的壓成範圍，例如 "1-3,5,7-9"；一部都沒選時回傳空字串。

        注意：server.build_opts 會忽略空的 playlist_items（等於下載整個清單），
        所以 selected_count() == 0 時呼叫端必須停用下載按鈕。
        """
        return compress_indexes(self._checked_indexes())

    def selected_count(self) -> int:
        return sum(self.model.checked)

    def select_all(self):
        """勾選目前看得到的列（有搜尋時只套用到搜尋結果）。"""
        self.model.set_rows(self._visible_rows(), True)

    def select_none(self):
        self.model.set_rows(self._visible_rows(), False)

    def invert(self):
        rows = self._visible_rows()
        on = [r for r in rows if not self.model.checked[r]]
        off = [r for r in rows if self.model.checked[r]]
        self.model.set_rows(off, False)
        self.model.set_rows(on, True)

    def apply_range(self) -> bool:
        """依範圍輸入框重新設定勾選（取代原本的選取）。格式錯誤時顯示提示並回傳 False。"""
        by_index = {e.get("index"): r for r, e in enumerate(self.model.entries)}
        try:
            picked = parse_range(self.range.text(), (i for i in by_index if isinstance(i, int)))
        except ValueError as exc:
            self._set_error(str(exc))
            return False
        self._set_error("")
        self.model.set_exact({by_index[i] for i in picked})
        return True

    # ------------------------------------------------------------------ 勾選
    def toggle_rows(self, rows: list[int]):
        on = [r for r in rows if not self.model.checked[r]]
        off = [r for r in rows if self.model.checked[r]]
        self.model.set_rows(off, False)
        self.model.set_rows(on, True)

    def toggle_span(self, a: int, b: int):
        """Shift 點選：把兩列之間（看得到的）設成跟 a 同樣的狀態。"""
        state = self.model.checked[a]
        pa = self.proxy.mapFromSource(self.model.index(a)).row()
        pb = self.proxy.mapFromSource(self.model.index(b)).row()
        if pa < 0 or pb < 0:
            self.toggle_rows([b])
            return
        lo, hi = sorted((pa, pb))
        self.model.set_rows([self.proxy.mapToSource(self.proxy.index(i, 0)).row() for i in range(lo, hi + 1)], state)

    def _checked_indexes(self) -> list[int]:
        return [e["index"] for e, on in zip(self.model.entries, self.model.checked, strict=True)
                if on and isinstance(e.get("index"), int)]

    def _visible_rows(self) -> list[int]:
        return [self.proxy.mapToSource(self.proxy.index(i, 0)).row() for i in range(self.proxy.rowCount())]

    def _total(self, rows) -> str:
        secs = [self.model.entries[r].get("duration") for r in rows]
        known = sum(s for s in secs if isinstance(s, int | float) and s > 0)
        if not known:
            return ""
        approx = any(not (isinstance(s, int | float) and s > 0) for s in secs)
        return ("約 " if approx else "") + fmt_duration(known)

    def _on_checks(self, *_):
        n = self.selected_count()
        total_n = len(self.model.entries)
        text = f"已選 {n} / {total_n} 部"
        dur = self._total([r for r, on in enumerate(self.model.checked) if on])
        if n and dur:
            text += f" · {dur}"
        if self.proxy.filterRegularExpression().pattern():
            text += f" · 顯示 {self.proxy.rowCount()} 部符合"
        self.count.setText(text)
        self.selectionChanged.emit(n)

    def _search_changed(self, text: str):
        if len(self.model.entries) > SEARCH_DEBOUNCE_ROWS:
            self._search_timer.start(150)
        else:
            self._on_search(text)

    def _on_search(self, text: str):
        self.proxy.setFilterFixedString(text.strip())
        self._update_empty()
        self._on_checks()
        hint = "只套用到搜尋結果" if text.strip() else ""
        for b in (self.btn_all, self.btn_none, self.btn_invert):
            b.setToolTip(hint)
        self._schedule_pump()

    def _update_empty(self):
        none = self.proxy.rowCount() == 0
        q = self.search.text().strip()
        self.empty.setText(f"沒有符合「{q}」的影片" if q else "這個播放清單沒有影片")
        self.empty.setVisible(none)
        self.list.setVisible(not none)

    def _set_error(self, msg: str):
        self.error.setText(msg)
        self.error.setVisible(bool(msg))

    def _link(self, text: str, slot) -> QPushButton:
        b = QPushButton(text)
        b.setObjectName("link")
        b.setCursor(Qt.PointingHandCursor)
        b.clicked.connect(slot)
        return b

    # ------------------------------------------------------------------ 縮圖延遲載入
    def request_thumb(self, row: int):
        """delegate 畫到某列時呼叫；只排進佇列，真的載入前會再確認該列還在畫面上。"""
        if row in self._requested or row in self.model.thumbs:
            return
        self._requested.add(row)
        self._queue.append(row)
        self._schedule_pump()

    def _schedule_pump(self):
        if not self._pump_timer.isActive():
            self._pump_timer.start(0)

    def _row_visible(self, row: int) -> bool:
        if not self.list.isVisible():
            return False
        pidx = self.proxy.mapFromSource(self.model.index(row))
        return pidx.isValid() and self.list.visualRect(pidx).intersects(self.list.viewport().rect())

    def _pump(self):
        while self._inflight < MAX_INFLIGHT and self._queue:
            row = self._queue.pop()  # 後進先出：最近畫到的優先
            if not self._row_visible(row):
                self._requested.discard(row)  # 捲走了，之後畫到再排
                continue
            url = self.model.entries[row].get("thumbnail")
            if not url:
                continue
            self._inflight += 1
            gen = self._gen
            reply = self.image_loader(url, lambda pm, row=row, gen=gen: self._on_thumb(gen, row, pm))
            if reply is not None and hasattr(reply, "abort"):
                self._replies[row] = reply

    def _abort_thumbs(self):
        """換清單時取消上一個清單還在載入的縮圖，讓出連線給新清單（Qt 對同一主機最多 6 條連線）。"""
        replies, self._replies = self._replies, {}
        for reply in replies.values():
            try:
                reply.abort()
            except RuntimeError:  # 已經完成並被刪除
                pass

    def _on_thumb(self, gen: int, row: int, pm: QPixmap):
        if gen != self._gen:
            return  # 舊清單的回應（或被取消）
        self._replies.pop(row, None)
        self._inflight = max(0, self._inflight - 1)
        if pm is not None and not pm.isNull():
            self.model.set_thumb(row, rounded(pm, THUMB_W, THUMB_H, THUMB_R))
        # 失敗的就留在 _requested 裡，不重試，保持灰色底
        self._schedule_pump()

    def apply_theme(self, t: dict[str, str]):
        """跟著主視窗的深淺色（主視窗指定的配色，而不是自己看系統設定）。"""
        set_theme(t)
        self._retheme()

    def _retheme(self):
        self.list.viewport().update()

    def changeEvent(self, e):
        if e.type() in (QEvent.PaletteChange, QEvent.StyleChange, QEvent.ApplicationPaletteChange):
            self._retheme()
        super().changeEvent(e)


__all__ = ["PlaylistView", "compress_indexes", "parse_range"]
