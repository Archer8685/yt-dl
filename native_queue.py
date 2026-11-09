"""「下載佇列」頁：定時向引擎查詢工作清單，每個工作一列（JobRow）。

每列可以暫停／繼續、取消、從清單移除（或連同檔案移到資源回收筒）、開啟檔案、查看錯誤原文與紀錄；
頁面上方有「暫停全部／繼續全部／全部重試／清除已完成」。

給主視窗（C1）用的介面（ROADMAP 5.5）：
- `QueuePage.job_finished = Signal(dict)`：工作剛變成 done 或 error 時發出（第一次載入的舊工作不算）。
- `QueuePage.summary() -> dict`：進行中數量、整體進度，給系統匣顯示。
- `QueuePage.pause_all()`、`resume_all()`：給系統匣選單。
- `QueuePage.show_job(job_id)`：捲到該工作並短暫標示（點通知時用）。
- `QueuePage.apply_theme(tokens)`：主題改變時更新狀態圖示的顏色（沒呼叫時從調色盤判斷深淺色）。

引擎回傳的 `stage`、`error` 已依語言組好，直接顯示；判斷狀態一律用 `status`／`stage_code`／`error_code`。
舊版引擎沒有的欄位（`warnings`、`failed_items`、`error_action`…）不存在時退回原本的行為。
"""
from __future__ import annotations

import inspect
import time
from pathlib import Path

import shiboken6
from PySide6.QtCore import QT_TRANSLATE_NOOP, QCoreApplication, QEvent, QPointF, QRectF, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QFont,
    QGuiApplication,
    QPainter,
    QPalette,
    QPen,
    QPixmap,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

import i18n
from native_common import (
    ACTIVE,
    IS_MAC,
    Api,
    Card,
    app_title,
    fmt_bytes,
    fmt_eta,
    label,
    page_layout,
    settings_store,
    tokens,
)

_tr = QCoreApplication.translate

# 引擎的狀態 → 沒有 stage 文字時的顯示（引擎通常會給 stage，這是退路）
STATUS_TEXT = {
    "queued": QT_TRANSLATE_NOOP("native_queue", "排隊中"),
    "downloading": QT_TRANSLATE_NOOP("native_queue", "下載中"),
    "processing": QT_TRANSLATE_NOOP("native_queue", "處理中"),
    "paused": QT_TRANSLATE_NOOP("native_queue", "已暫停"),
    "done": QT_TRANSLATE_NOOP("native_queue", "已完成"),
    "error": QT_TRANSLATE_NOOP("native_queue", "失敗"),
    "cancelled": QT_TRANSLATE_NOOP("native_queue", "已取消"),
}
RUNNING = ("downloading", "processing")
RETRY_AFTER_UPDATE_KEY = "queue/retry_after_update"  # 「套用 yt-dlp 新版並重試」：重新啟動後要繼續的工作
RETRY_AFTER_UPDATE_TTL = 15 * 60  # 秒：超過這段時間才重新啟動，就當作沒有因為更新而重啟


def load_retry_after_update(store) -> list[str]:
    """讀「更新後要重試的工作」；格式是「時間戳|id,id」，過期或格式不對就當作沒有。"""
    raw = str(store.value(RETRY_AFTER_UPDATE_KEY, "") or "")
    stamp, _, ids = raw.partition("|")
    try:
        fresh = 0 <= time.time() - float(stamp) <= RETRY_AFTER_UPDATE_TTL
    except ValueError:
        fresh = False
    return [x for x in ids.split(",") if x] if fresh else []


def save_retry_after_update(store, ids: list[str]):
    if ids:
        store.setValue(RETRY_AFTER_UPDATE_KEY, f"{time.time()}|{','.join(ids)}")
    else:
        store.remove(RETRY_AFTER_UPDATE_KEY)


def status_text(status: str) -> str:
    text = STATUS_TEXT.get(status)
    return QCoreApplication.translate("native_queue", text) if text else (status or "")


def failed_items(job: dict) -> list[dict]:
    items = job.get("failed_items")
    return [i for i in items if isinstance(i, dict)] if isinstance(items, list) else []


def warnings_of(job: dict) -> list[str]:
    w = job.get("warnings")
    return [str(x) for x in w if x] if isinstance(w, list) else []


def kind_of(job: dict) -> str:
    """狀態圖示的種類：queued／downloading／processing／paused／done／warn／error／cancelled。"""
    st = job.get("status")
    if st == "done" and (warnings_of(job) or failed_items(job)):
        return "warn"
    if st in ACTIVE and job.get("stage_code") == "pausing":
        return "paused"
    return st if st in STATUS_TEXT else "error"


def notify(toast, text: str, level: str = "info", actions=None):
    """呼叫主視窗的 toast：新版是 toast(text, level=, actions=)，舊版只有 toast(text, error=)。"""
    if not callable(toast):
        return
    try:
        params = inspect.signature(toast).parameters
    except (TypeError, ValueError):
        params = {}
    takes_any = any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())
    if "level" in params:
        if actions and ("actions" in params or takes_any):
            toast(text, level=level, actions=actions)
        else:
            toast(text, level=level)
    elif "error" in params or takes_any:
        toast(text, error=level == "error")
    else:
        toast(text)


def status_pixmap(kind: str, t: dict[str, str], size: int = 16) -> QPixmap:
    """佇列每列左邊的狀態圖示（Q2）：形狀和顏色都不同，色盲也分得出來。"""
    color = {"downloading": t["accent"], "processing": t["accent"], "done": t["green"], "warn": t["orange"],
             "error": t["red"]}.get(kind, t["secondary"])
    dpr = 2.0
    pm = QPixmap(int(size * dpr), int(size * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    s = float(size)
    pen = QPen(QColor(color), s / 9, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.setPen(pen)
    circle = QRectF(s * .08, s * .08, s * .84, s * .84)

    def line(x1, y1, x2, y2):
        p.drawLine(QPointF(s * x1, s * y1), QPointF(s * x2, s * y2))

    if kind == "warn":  # 三角形＋驚嘆號
        p.drawPolygon([QPointF(s * .5, s * .1), QPointF(s * .93, s * .88), QPointF(s * .07, s * .88)])
        line(.5, .38, .5, .6)
        p.drawPoint(QPointF(s * .5, s * .75))
    else:
        p.drawEllipse(circle)
        if kind == "queued":  # 時鐘
            line(.5, .28, .5, .52)
            line(.5, .52, .68, .62)
        elif kind == "downloading":  # 向下箭頭
            line(.5, .27, .5, .7)
            p.drawPolyline([QPointF(s * .32, s * .53), QPointF(s * .5, s * .71), QPointF(s * .68, s * .53)])
        elif kind == "processing":  # 三個點
            for x in (.3, .5, .7):
                p.drawPoint(QPointF(s * x, s * .5))
        elif kind == "paused":  # 暫停的兩條線
            line(.4, .32, .4, .68)
            line(.6, .32, .6, .68)
        elif kind == "done":  # 打勾
            p.drawPolyline([QPointF(s * .3, s * .52), QPointF(s * .45, s * .66), QPointF(s * .71, s * .37)])
        elif kind == "error":  # 驚嘆號
            line(.5, .27, .5, .56)
            p.drawPoint(QPointF(s * .5, s * .72))
        else:  # cancelled：叉叉
            line(.35, .35, .65, .65)
            line(.65, .35, .35, .65)
    p.end()
    return pm


def palette_tokens(widget: QWidget) -> dict[str, str]:
    """主視窗還沒告訴我們主題時，用調色盤判斷深淺色。"""
    return tokens(widget.palette().color(QPalette.Window).lightness() < 128)


# --------------------------------------------------------------------------- #
#  紀錄視窗
# --------------------------------------------------------------------------- #
class LogDialog(QDialog):
    """「顯示紀錄」：工作的下載紀錄（引擎的 GET /api/jobs/<id> 會附上 log），可以全選複製。"""

    def __init__(self, parent: QWidget, title: str):
        super().__init__(parent)
        self.setWindowTitle(self.tr("下載紀錄"))
        self.resize(720, 460)
        lay = QVBoxLayout(self)
        head = label(title, "rowTitle", wrap=True, plain=True)
        lay.addWidget(head)
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setLineWrapMode(QPlainTextEdit.NoWrap)
        mono = QFont("Consolas" if not IS_MAC else "Menlo")
        mono.setStyleHint(QFont.Monospace)
        self.text.setFont(mono)
        self.text.setPlainText(self.tr("載入中…"))
        self.text.setAccessibleName(self.tr("下載紀錄"))
        lay.addWidget(self.text, 1)
        buttons = QHBoxLayout()
        buttons.addStretch()
        self.copy_btn = QPushButton(self.tr("複製全部"))
        self.copy_btn.clicked.connect(self.copy)
        self.copy_btn.setEnabled(False)
        buttons.addWidget(self.copy_btn)
        close = QPushButton(self.tr("關閉"))
        close.setDefault(True)
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        lay.addLayout(buttons)

    def set_lines(self, lines: list[str]):
        if lines:
            self.text.setPlainText("\n".join(str(x) for x in lines))
            self.copy_btn.setEnabled(True)
            self.text.moveCursor(QTextCursor.End)
        else:
            self.text.setPlainText(self.tr("這個工作沒有紀錄。"))

    def set_error(self, msg: str):
        self.text.setPlainText(self.tr("無法取得紀錄：{reason}").format(reason=msg))

    def copy(self):
        QGuiApplication.clipboard().setText(self.text.toPlainText())


# --------------------------------------------------------------------------- #
#  一個工作一列
# --------------------------------------------------------------------------- #
class _Actions(QWidget):
    """一列的動作連結。最小寬度回報 0：不讓它撐大整列的最小寬度，放不下時由 JobRow 換到下一行。"""

    def minimumSizeHint(self):
        return QSize(0, super().minimumSizeHint().height())


class JobRow(QWidget):
    def __init__(self, api: Api, on_change, toast=None):
        super().__init__()
        self.setObjectName("row")
        self.setAttribute(Qt.WA_StyledBackground, True)  # show_job() 標示時要畫背景
        self.api, self.on_change, self.job = api, on_change, {}
        self.toast = toast if callable(toast) else (lambda *_a, **_k: None)
        self.theme: dict[str, str] | None = None
        self._kind = None
        self._expanded = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(6)
        top = QHBoxLayout()
        top.setSpacing(8)
        self.icon = QLabel()
        self.icon.setFixedSize(16, 16)
        top.addWidget(self.icon, 0, Qt.AlignVCenter)
        self.title = label("", "rowTitle", plain=True)
        self.title.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        top.addWidget(self.title, 1)
        # 動作連結：放得下時在標題右邊；這一列太窄（最小視窗、英文較長、動作多）時移到標題下一行（_fit_actions）
        self.actions_box = _Actions()
        self.buttons = QHBoxLayout(self.actions_box)
        self.buttons.setContentsMargins(0, 0, 0, 0)
        self.buttons.setSpacing(6)
        top.addWidget(self.actions_box)
        self._top = top
        self.more = QToolButton()
        self.more.setText("⋯")
        self.more.setObjectName("link")
        self.more.setAutoRaise(True)
        self.more.setPopupMode(QToolButton.InstantPopup)
        self.more.setToolTip(self.tr("更多動作"))
        self.more.setAccessibleName(self.tr("更多動作"))
        self.menu = QMenu(self)
        self.more.setMenu(self.menu)
        self.more.setStyleSheet("QToolButton::menu-indicator { image: none; width: 0; }")
        top.addWidget(self.more)
        lay.addLayout(top)
        self._wrap_row = QHBoxLayout()  # 動作連結換到第二行時的位置（靠右，和原本的位置對齊）
        self._wrap_row.setContentsMargins(0, 0, 0, 0)
        self._wrap_row.addStretch()
        lay.addLayout(self._wrap_row)
        self._wrapped = False
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        lay.addWidget(self.bar)
        detail_row = QHBoxLayout()
        detail_row.setSpacing(6)
        self.detail = label("", "subtitle", wrap=True, plain=True)
        detail_row.addWidget(self.detail, 1)
        self.toggle = QPushButton()
        self.toggle.setObjectName("link")
        self.toggle.clicked.connect(lambda: self.set_expanded(not self._expanded))
        detail_row.addWidget(self.toggle, 0, Qt.AlignTop)
        lay.addLayout(detail_row)

        # 展開後的詳細資訊：錯誤原文、警告、播放清單失敗的項目
        self.panel = QWidget()
        pl = QVBoxLayout(self.panel)
        pl.setContentsMargins(24, 2, 0, 2)
        pl.setSpacing(6)
        self.panel_text = label("", "hint", wrap=True, plain=True)
        self.panel_text.setTextInteractionFlags(Qt.TextSelectableByMouse)  # 錯誤原文要能選取
        pl.addWidget(self.panel_text)
        links = QHBoxLayout()
        links.setSpacing(10)
        self.copy_btn = self._link(self.tr("複製錯誤訊息"), self.copy_error, links)
        self.retry_failed_btn = self._link(self.tr("重試失敗的項目"), self.retry_failed, links)
        self.log_btn = self._link(self.tr("顯示紀錄"), self.show_log, links)
        self.faq_btn = self._link(self.tr("常見問題"), self.open_faq, links)
        links.addStretch()
        pl.addLayout(links)
        self.panel.hide()
        lay.addWidget(self.panel)
        self._actions = None
        self._menu_key = None

    @staticmethod
    def _link(text: str, fn, lay: QHBoxLayout) -> QPushButton:
        b = QPushButton(text)
        b.setObjectName("link")
        b.clicked.connect(fn)
        lay.addWidget(b)
        return b

    # ---------- 按鈕 ----------
    def _set_actions(self, actions: list[tuple[str, str, object, str]]):
        key = tuple((a[0], a[1], a[3]) for a in actions)
        if key == self._actions:
            return
        self._actions = key
        while self.buttons.count():
            w = self.buttons.takeAt(0).widget()
            if w:
                w.setParent(None)  # 立刻離開這一列（deleteLater 要等事件迴圈）
                w.deleteLater()
        for text, style, fn, tip in actions:
            b = QPushButton(text)
            b.setObjectName(style)
            b.setToolTip(tip)
            b.clicked.connect(fn)
            self.buttons.addWidget(b)
        self._fit_actions()

    # ---------- 版面 ----------
    TITLE_MIN = 120  # 動作連結留在標題右邊時，標題至少要留的寬度

    def _fit_actions(self):
        """這一列放不下「標題＋動作連結」時，把動作連結移到標題下一行；放得下時移回來。"""
        if self.width() <= 0:
            return
        m = self.layout().contentsMargins()
        need = (m.left() + m.right() + self.icon.width() + self.TITLE_MIN + self.actions_box.sizeHint().width()
                + self.more.sizeHint().width() + 3 * self._top.spacing())
        wrap = self.width() < need
        if wrap == self._wrapped:
            return
        self._wrapped = wrap
        if wrap:
            self._top.removeWidget(self.actions_box)
            self._wrap_row.addWidget(self.actions_box)
        else:
            self._wrap_row.removeWidget(self.actions_box)
            self._top.insertWidget(self._top.indexOf(self.more), self.actions_box)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit_actions()

    def _set_menu(self):
        key = (bool(self.job.get("error") or self.job.get("error_detail")), self.job.get("status") in ACTIVE)
        if key == self._menu_key:  # 內容沒變就不重建（輪詢時選單可能正開著）
            return
        self._menu_key = key
        self.menu.clear()
        self.menu.addAction(self.tr("顯示紀錄"), self.show_log)
        self.menu.addAction(self.tr("複製網址"), self.copy_url)
        if self.job.get("error") or self.job.get("error_detail"):
            self.menu.addAction(self.tr("複製錯誤訊息"), self.copy_error)
        if self.job.get("status") not in ACTIVE:
            self.menu.addSeparator()
            self.menu.addAction(self.tr("從清單移除…"), self.remove)

    def _call(self, method: str, path: str, what: str, ok=None):
        """暫停／繼續／取消／刪除：成功立刻刷新清單，失敗顯示原因。"""
        def done(r):
            ok and ok(r)
            self.on_change()

        def err(msg):
            notify(self.toast, _tr("JobRow", "{action}失敗：{reason}").format(action=what, reason=msg), "error")
            self.on_change()
        if method == "DELETE":
            self.api.delete(path, done, err)
        else:
            self.api.post(path, {}, done, err)

    # ---------- 畫面 ----------
    def apply_theme(self, t: dict[str, str] | None):
        self.theme = t
        self._kind = None
        if self.job:
            self._update_icon()

    def _update_icon(self):
        kind = kind_of(self.job)
        if kind == self._kind:
            return
        self._kind = kind
        t = self.theme or palette_tokens(self)
        self.icon.setPixmap(status_pixmap(kind, t))
        # Q2：暫停中的進度條改成灰色，和下載中的藍條分得出來（macOS 用系統原生進度條，不套樣式）
        if not IS_MAC:
            self.bar.setStyleSheet(f"QProgressBar::chunk {{ background: {t['secondary']}; border-radius: 2px; }}"
                                   if kind == "paused" else "")
        desc = self.state_name()
        self.icon.setToolTip(desc)
        self.icon.setAccessibleName(desc)

    def state_name(self) -> str:
        kind = kind_of(self.job)
        if kind == "warn":
            return self.tr("已完成，但有部分步驟失敗")
        return status_text(kind)

    def _set_detail_style(self, name: str):
        if self.detail.objectName() != name:
            self.detail.setObjectName(name)
            self.detail.style().unpolish(self.detail)
            self.detail.style().polish(self.detail)

    def update_job(self, job: dict):
        self.job = job
        st = job.get("status")
        self.title.setText(job.get("title") or job.get("url") or "")
        self.title.setToolTip(job.get("title") or "")
        self._update_icon()
        pct = float(job.get("progress") or 0)
        running = st in RUNNING
        self.bar.setRange(0, 0 if running and pct <= 0 else 1000)
        self.bar.setValue(int(pct * 10))
        state = "error" if st == "error" else ""
        if self.bar.property("state") != state:
            self.bar.setProperty("state", state)
            self.bar.style().unpolish(self.bar)
            self.bar.style().polish(self.bar)
        # 排隊中不畫跑馬燈（之前和下載中都是藍條，看不出差別）；完成、取消不需要進度條
        self.bar.setVisible(running or (st in ("paused", "error") and pct > 0))

        files = job.get("files") or []
        fails, warns = failed_items(job), warnings_of(job)
        style = "subtitle"
        if running:
            text = self._progress_text(job, pct)
        elif st == "queued":
            text = self._queued_text(job)
        elif st == "done":
            text = self._done_text(job, files, fails, warns)
            if fails or warns:
                style = "warnText"
        elif st == "error":
            text = job.get("error") or self.tr("下載失敗")
            style = "errorText"
        elif st == "paused":
            text = job.get("stage") or status_text("paused")
            partial = job.get("partial") or 0
            if partial:
                text = self.tr("{stage} · 已下載 {size}，按「繼續」接著下載").format(stage=text, size=fmt_bytes(partial))
        else:
            text = job.get("stage") or status_text(st)
            if files:
                text = _tr("JobRow", "{stage} · 已保留 %n 個檔案", None, len(files)).format(stage=text)
        self._set_detail_style(style)
        # 只有錯誤訊息可以選取複製；可以選取的文字會吃掉雙擊，完成的工作要能雙擊開啟（Q1）
        self.detail.setTextInteractionFlags(Qt.TextSelectableByMouse if st == "error" else Qt.NoTextInteraction)
        self.detail.setText(text)
        self._update_panel(job, fails, warns)
        self._set_actions(self._build_actions(job, files, fails))
        self._set_menu()

    def _progress_text(self, job: dict, pct: float) -> str:
        parts = [job.get("stage") or status_text(job.get("status"))]
        if job.get("item"):
            parts.append(self.tr("第 {item} 部").format(item=job["item"]))
        parts.append(f"{pct:.1f}%")
        if job.get("total"):
            parts.append(f"{fmt_bytes(job.get('downloaded'))} / {fmt_bytes(job['total'])}")
        if job.get("speed"):
            parts.append(f"{fmt_bytes(job['speed'])}/s")
        parts.append(fmt_eta(job.get("eta")))
        return " · ".join(p for p in parts if p)

    def _queued_text(self, job: dict) -> str:
        """Q6：同時只下載幾個，其他的排隊；告訴使用者前面還有幾個。"""
        pos = job.get("queue_position")
        if isinstance(pos, int) and pos > 1:
            return _tr("JobRow", "排隊中（前面還有 %n 個）", None, pos - 1)
        if pos == 1:
            return self.tr("排隊中（下一個開始）")
        return job.get("stage") or status_text("queued")

    def _done_text(self, job: dict, files: list, fails: list, warns: list) -> str:
        size = fmt_bytes(sum(f.get("size") or 0 for f in files))
        count = _tr("JobRow", "%n 個檔案", None, len(files))
        total, done = job.get("total_count"), job.get("done_count")
        if fails and isinstance(total, int) and total:
            done = done if isinstance(done, int) else max(total - len(fails), 0)
            head = _tr("JobRow", "完成 {done}/{total}，%n 部無法下載", None, len(fails)).format(done=done,
                                                                                         total=total)
        elif fails:
            head = _tr("JobRow", "已完成，%n 部無法下載", None, len(fails))
        elif warns:
            head = self.tr("已完成，但有部分步驟失敗")
        else:
            head = status_text("done")
        return " · ".join(p for p in (head, count if files else "", size) if p)

    def _update_panel(self, job: dict, fails: list[dict], warns: list[str]):
        st = job.get("status")
        lines = []
        if st == "error":
            detail = job.get("error_detail")
            if detail and detail != job.get("error"):
                lines.append(self.tr("原始訊息：{detail}").format(detail=detail))
        for w in warns:
            lines.append("• " + w)
        for item in fails:
            lines.append(self._failed_line(item))
        has_error = st == "error" and bool(job.get("error") or job.get("error_detail"))
        can_expand = bool(lines) or has_error
        self.toggle.setVisible(can_expand)
        if not can_expand:
            self._expanded = False
        self.panel_text.setText("\n".join(lines))
        self.panel_text.setVisible(bool(lines))
        self.copy_btn.setVisible(has_error)
        self.retry_failed_btn.setVisible(bool(fails) and st in ("done", "error"))
        self.faq_btn.setVisible(bool(job.get("error_faq")) and st == "error")
        self._apply_expanded()

    def _failed_line(self, item: dict) -> str:
        reason = item.get("error") or item.get("error_detail") or self.tr("無法下載")
        index, title = item.get("index"), item.get("title")
        if index is not None and title:
            return self.tr("第 {index} 部「{title}」：{reason}").format(index=index, title=title, reason=reason)
        if index is not None:
            return self.tr("第 {index} 部：{reason}").format(index=index, reason=reason)
        return self.tr("「{title}」：{reason}").format(title=title or "", reason=reason)

    def set_expanded(self, on: bool):
        self._expanded = on
        self._apply_expanded()

    def _apply_expanded(self):
        on = self._expanded and self.toggle.isVisibleTo(self)
        self.panel.setVisible(on)
        self.toggle.setText(self.tr("隱藏詳細資訊") if on else self.tr("詳細資訊"))

    def _build_actions(self, job: dict, files: list, fails: list) -> list[tuple[str, str, object, str]]:
        st = job.get("status")
        jid = job["id"]
        actions = []
        if st in ACTIVE:
            if job.get("stage_code") != "pausing":
                actions.append((self.tr("暫停"), "link", self.pause,
                                self.tr("暫停下載，已下載的部分會保留，之後可以按「繼續」接著下載")))
            actions.append((self.tr("取消"), "destructiveLink", self.cancel,
                            self.tr("停止下載並捨棄還沒完成的部分")))
        elif st == "paused":
            actions.append((self.tr("繼續"), "link",
                            lambda: self._call("POST", f"/api/jobs/{jid}/resume", self.tr("繼續下載")),
                            self.tr("從暫停的地方接著下載")))
        elif st == "error":
            actions.extend(self._error_actions(job))
        if st == "done" and fails:
            actions.append((self.tr("重試失敗的項目"), "link", self.retry_failed,
                            self.tr("只重新下載沒有成功的那幾部")))
        if files and st == "done":
            actions.append((self.tr("開啟"), "link", self.open_file, self.tr("用預設的播放程式開啟（也可以雙擊這一列）")))
        if files:  # 已取消、空間不足而中止的工作也可能保留了完成的檔案
            reveal = self.tr("在 Finder 中顯示") if IS_MAC else self.tr("在檔案總管中顯示")
            actions.append((reveal, "link", self.reveal, self.tr("打開檔案所在的資料夾")))
        if st not in ACTIVE:
            actions.append((self.tr("移除"), "destructiveLink", self.remove,
                            self.tr("從清單移除；可以選擇保留或刪除已下載的檔案")))
        return actions

    def _error_actions(self, job: dict) -> list[tuple[str, str, object, str]]:
        """ERR1／ERR3：依引擎建議的下一步（error_action）顯示按鈕；一定有「繼續下載」或「重試」。"""
        jid = job["id"]
        act = job.get("error_action")
        resume_text = self.tr("繼續下載") if (job.get("partial") or act == "resume") else self.tr("重試")
        resume = (resume_text, "link", lambda: self._call("POST", f"/api/jobs/{jid}/resume", resume_text),
                  self.tr("從中斷處接著下載"))
        extra = {
            "open_cookie_settings": (self.tr("設定 Cookie"), lambda: self.go_settings("cookies"),
                                     self.tr("到「設定」登入帳號（Cookie）後再按「重試」")),
            "open_storage_settings": (self.tr("更換儲存位置"), lambda: self.go_settings("storage"),
                                      self.tr("到「設定」選擇其他儲存位置")),
            "open_network_settings": (self.tr("檢查 Proxy 設定"), self.open_network_settings,
                                      self.tr("檢查進階選項裡的 Proxy 設定")),
            "reanalyze": (self.tr("重新解析"), self.reanalyze, self.tr("重新解析網址，再選一次畫質或格式")),
            "update_ytdlp": (self.tr("套用 yt-dlp 新版並重試"), self.update_and_retry,
                             self.tr("更新 yt-dlp 後重新啟動 App，接著自動重試這個工作")),
        }.get(act)
        if not extra:
            return [resume]
        text, fn, tip = extra
        # 引擎建議的動作放第一個；格式已不存在時用同樣設定重試也沒用，就不再多一個「重試」
        return [(text, "link", fn, tip)] + ([] if act == "reanalyze" else [resume])

    # ---------- 動作 ----------
    def pause(self):
        self._call("POST", f"/api/jobs/{self.job['id']}/pause", self.tr("暫停"))

    def cancel(self):
        """R4：取消會刪掉暫存資料、不能再接著下載；已經下載了一部分時先問，並建議改用「暫停」。"""
        job = self.job
        jid = job["id"]
        has_progress = float(job.get("progress") or 0) > 0 or (job.get("partial") or 0) > 0
        if has_progress:
            box = QMessageBox(self.window())
            box.setIcon(QMessageBox.Warning)
            box.setWindowTitle(app_title())
            box.setText(self.tr("要取消「{title}」嗎？").format(title=job.get("title") or job.get("url") or ""))
            box.setInformativeText(self.tr("已下載的暫存資料會刪除，之後無法接著下載。如果只是想先停下來，請選「暫停」。"))
            stop = box.addButton(self.tr("取消下載"), QMessageBox.DestructiveRole)
            pause = box.addButton(self.tr("暫停"), QMessageBox.AcceptRole)
            box.setDefaultButton(box.addButton(self.tr("返回"), QMessageBox.RejectRole))
            box.exec()
            if box.clickedButton() is pause:
                return self.pause()
            if box.clickedButton() is not stop:
                return
        self._call("POST", f"/api/jobs/{jid}/cancel", self.tr("取消"))

    def retry_failed(self):
        self._call("POST", f"/api/jobs/{self.job['id']}/retry_failed", self.tr("重試失敗的項目"))

    def _largest(self) -> dict | None:
        files = self.job.get("files") or []
        return max(files, key=lambda f: f.get("size") or 0) if files else None

    def open_file(self):
        """Q1：用預設程式開啟最大的檔案（通常就是影片本身）。引擎和 App 在同一台電腦，直接開本機路徑。"""
        big = self._largest()
        if not big:
            return
        jid, name = self.job["id"], big["name"]

        def ok(s):
            folder = s.get("download_dir") if isinstance(s, dict) else None
            path = Path(folder) / jid / name if folder else None
            if path and path.is_file():
                if QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
                    return
                notify(self.toast, self.tr("沒有可以開啟這個檔案的程式，改為顯示檔案位置"), "error")
            self.reveal()  # 找不到本機路徑（例如剛換過儲存位置）：交給引擎在檔案總管中顯示

        self.api.get("/api/settings", ok, lambda _m: self.reveal())

    def reveal(self):
        big = self._largest()
        if not big:
            return
        self.api.post(f"/api/jobs/{self.job['id']}/reveal", {"name": big["name"]}, None,
                      lambda m: notify(self.toast, self.tr("無法打開資料夾：{reason}").format(reason=m), "error"))

    def mouseDoubleClickEvent(self, e):
        if self.job.get("status") == "done" and self.job.get("files"):
            self.open_file()
        else:
            super().mouseDoubleClickEvent(e)

    def remove(self):
        """R5：預設只從清單移除（檔案留著）；要連同檔案刪除時移到資源回收筒，不會永久刪除。"""
        job = self.job
        files = job.get("files") or []
        partial = job.get("partial") or 0
        title = job.get("title") or job.get("url") or ""
        mode = "keep"
        if files:
            box = QMessageBox(self.window())
            box.setIcon(QMessageBox.Question)
            box.setWindowTitle(app_title())
            box.setText(self.tr("要從清單移除「{title}」嗎？").format(title=title))
            size = fmt_bytes(sum(f.get("size") or 0 for f in files))
            if IS_MAC:
                info = _tr("JobRow", "已下載的 %n 個檔案（{size}）會留在電腦上。如果也不需要這些檔案，請選「連同檔案刪除」，檔案會移到垃圾桶。",
                           None, len(files))
            else:
                info = _tr("JobRow", "已下載的 %n 個檔案（{size}）會留在電腦上。如果也不需要這些檔案，請選「連同檔案刪除」，檔案會移到資源回收筒。",
                           None, len(files))
            info = info.format(size=size)
            if partial:
                info += "\n\n" + self.tr("另外，已下載 {size} 的暫存資料會刪除，之後就無法接著下載。").format(
                    size=fmt_bytes(partial))
            box.setInformativeText(info)
            keep = box.addButton(self.tr("從清單移除"), QMessageBox.AcceptRole)
            trash = box.addButton(self.tr("連同檔案刪除"), QMessageBox.DestructiveRole)
            box.addButton(self.tr("取消"), QMessageBox.RejectRole)
            box.setDefaultButton(keep)
            box.exec()
            clicked = box.clickedButton()
            if clicked is trash:
                mode = "trash"
            elif clicked is not keep:
                return
        elif partial:
            box = QMessageBox(self.window())
            box.setIcon(QMessageBox.Warning)
            box.setWindowTitle(app_title())
            box.setText(self.tr("要從清單移除「{title}」嗎？").format(title=title))
            box.setInformativeText(self.tr("已下載 {size} 的暫存資料會一起刪除，之後就無法接著下載。")
                                   .format(size=fmt_bytes(partial)))
            remove = box.addButton(self.tr("移除"), QMessageBox.DestructiveRole)
            box.setDefaultButton(box.addButton(self.tr("取消"), QMessageBox.RejectRole))
            box.exec()
            if box.clickedButton() is not remove:
                return
        what = self.tr("刪除檔案") if mode == "trash" else self.tr("移除")
        self._call("DELETE", f"/api/jobs/{job['id']}?files={mode}", what)

    def copy_error(self):
        """ERR1：錯誤訊息和原文一起複製，回報問題時貼上就好。"""
        job = self.job
        parts = [job.get("error") or ""]
        if job.get("error_detail") and job.get("error_detail") != job.get("error"):
            parts.append(job["error_detail"])
        if job.get("error_code"):
            parts.append(f"[{job['error_code']}]")
        QGuiApplication.clipboard().setText("\n".join(p for p in parts if p))
        notify(self.toast, self.tr("已複製錯誤訊息"))

    def copy_url(self):
        QGuiApplication.clipboard().setText(self.job.get("url") or "")
        notify(self.toast, self.tr("已複製網址"))

    def show_log(self):
        """ERR4：在 App 裡看這個工作的下載紀錄（引擎把紀錄存在 job.json，重開 App 也看得到）。"""
        dlg = LogDialog(self.window(), self.job.get("title") or self.job.get("url") or "")
        dlg.setAttribute(Qt.WA_DeleteOnClose)

        def ok(j):
            if shiboken6.isValid(dlg):  # 使用者可能已經關掉視窗
                dlg.set_lines((j.get("log") or []) if isinstance(j, dict) else [])

        def err(m):
            if shiboken6.isValid(dlg):
                dlg.set_error(m)
        dlg.show()
        self.api.get(f"/api/jobs/{self.job['id']}", ok, err)
        return dlg

    def open_faq(self):
        QDesktopServices.openUrl(QUrl(i18n.guide_url(self.job.get("error_faq") or "")))

    def go_settings(self, section: str):
        """主視窗有 open_settings（C1）就開到該區；沒有就告訴使用者去哪裡改。"""
        win = self.window()
        fn = getattr(win, "open_settings", None) if win is not self else None
        if callable(fn):
            fn(section)
            return
        where = {"cookies": self.tr("請到「設定 → Cookie」登入帳號後再重試"),
                 "storage": self.tr("請到「設定 → 儲存位置」更換位置後再重試")}.get(section, self.tr("請到「設定」修改"))
        notify(self.toast, where)

    def open_network_settings(self):
        """Proxy 在「新增下載」的進階選項裡（A2 的 reveal_section）；找不到時說明位置。"""
        win = self.window()
        adv = getattr(getattr(win, "download", None), "advanced", None)
        if callable(getattr(adv, "reveal_section", None)) and callable(getattr(win, "go", None)):
            win.go(0)
            adv.reveal_section("network")
            return
        notify(self.toast, self.tr("請到「新增下載 → 進階選項 → 網路」檢查 Proxy 設定"))

    def reanalyze(self):
        """格式已不存在：把網址交回「新增下載」重新解析（A1 的 accept_urls）；不能的話複製網址。"""
        url = self.job.get("url") or ""
        win = self.window()
        page = getattr(win, "download", None)
        if url and callable(getattr(page, "accept_urls", None)):
            if callable(getattr(win, "go", None)):
                win.go(0)
            page.accept_urls([url])
            return
        QGuiApplication.clipboard().setText(url)
        notify(self.toast, self.tr("已複製網址，請到「新增下載」貼上後重新解析"))

    def update_and_retry(self):
        """ERR3：套用 yt-dlp 新版（引擎會重新啟動 App），重新啟動後自動繼續這個工作。"""
        jid = self.job["id"]
        store = settings_store()
        pending = load_retry_after_update(store)
        if jid not in pending:
            pending.append(jid)
        save_retry_after_update(store, pending)

        def ok(_r):
            notify(self.toast, self.tr("正在更新 yt-dlp，完成後 App 會重新啟動並自動重試"))

        def err(m):
            save_retry_after_update(store, [x for x in load_retry_after_update(store) if x != jid])
            notify(self.toast, self.tr("無法更新 yt-dlp：{reason}").format(reason=m), "error")
        self.api.post("/api/update", {}, ok, err, timeout_ms=30_000)


# --------------------------------------------------------------------------- #
#  頁面
# --------------------------------------------------------------------------- #
class QueuePage(QWidget):
    counts = Signal(int)
    online = Signal(bool, str)  # 和引擎的連線狀態（連續兩次輪詢失敗才算斷線）
    job_finished = Signal(dict)  # 工作剛變成 done 或 error（F2 完成通知）

    def __init__(self, api: Api, toast=None):
        super().__init__()
        self.api, self.toast = api, toast
        self.theme: dict[str, str] | None = None
        lay = page_layout(self)
        self.scroll = self.findChild(QScrollArea)

        # 狀態文字一行（可換行）、批次按鈕另一行：放在同一行時最小視窗（720px）中英文都會超出右邊
        self.bulk = QWidget()
        vl = QVBoxLayout(self.bulk)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(6)
        self.summary_label = label("", "subtitle", wrap=True)
        vl.addWidget(self.summary_label)
        bl = QHBoxLayout()
        bl.setSpacing(8)
        vl.addLayout(bl)
        self.pause_all_btn = self._bulk_button(self.tr("暫停全部"), self.pause_all, bl)
        self.resume_all_btn = self._bulk_button(self.tr("繼續全部"), self.resume_all, bl)
        self.retry_all_btn = self._bulk_button(self.tr("全部重試"), self.retry_all, bl)
        self.clear_btn = self._bulk_button(self.tr("清除已完成"), self.clear_finished, bl)
        bl.addStretch()
        self.clear_btn.setToolTip(self.tr("從清單移除所有已完成的工作，檔案會留在原處"))
        self.bulk.hide()
        lay.addWidget(self.bulk)

        self.empty = label(self.tr("目前沒有下載。"), "subtitle")
        lay.addWidget(self.empty)
        self.card = Card()
        lay.addWidget(self.card)
        lay.addStretch()
        self.rows: dict[str, JobRow] = {}
        self.order: list[str] = []
        self.jobs: list[dict] = []
        self._statuses: dict[str, tuple] | None = None  # 上一次看到的（狀態, 結束時間）（None＝還沒載入過）
        self._pending_show: str | None = None
        self._scroll_target: str | None = None
        self._seq = 0        # 送出的請求編號
        self._applied = 0    # 畫面目前顯示的是哪一次請求的結果
        self._polling = False
        self._fails = 0
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._poll)

    @staticmethod
    def _bulk_button(text: str, fn, lay: QHBoxLayout) -> QPushButton:
        b = QPushButton(text)
        b.clicked.connect(lambda: fn())
        lay.addWidget(b)
        return b

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
        if self._scroll_target:  # show_job() 時頁面還沒顯示：顯示後再捲過去
            QTimer.singleShot(0, self._scroll_to_target)

    def _scroll_to_target(self):
        row = self.rows.get(self._scroll_target or "")
        if row is None or not shiboken6.isValid(row):
            self._scroll_target = None
            return
        if self.scroll and row.isVisible():
            self.scroll.ensureWidgetVisible(row, 0, 40)
            self._scroll_target = None

    def apply_theme(self, t: dict[str, str]):
        """主視窗套用主題時呼叫（C1）：狀態圖示跟著換顏色。"""
        self.theme = t
        for row in self.rows.values():
            row.apply_theme(t)

    def changeEvent(self, e):
        super().changeEvent(e)
        if self.theme is None and e.type() == QEvent.PaletteChange:  # 沒有主題資訊時，跟著調色盤換圖示顏色
            for row in self.rows.values():
                row.apply_theme(None)

    def render(self, jobs: list[dict]):
        self.jobs = jobs
        ids = [j["id"] for j in jobs]
        if ids != self.order:  # 工作增減或順序改變：只搬動列，不重建已有的列
            for jid in ids:
                if jid not in self.rows:
                    row = self.rows[jid] = JobRow(self.api, self.refresh, self.toast)
                    row.theme = self.theme
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
        self._update_bulk()
        self._emit_finished(jobs)
        self.counts.emit(sum(j.get("status") in ACTIVE for j in jobs))
        if self._pending_show in self.rows:
            self.show_job(self._pending_show)

    def _emit_finished(self, jobs: list[dict]):
        """F2：只通知「這次執行期間」才結束的工作；第一次載入看到的舊工作不通知。"""
        now = {j["id"]: (j.get("status"), j.get("finished")) for j in jobs}
        before = self._statuses
        self._statuses = now
        if before is None:
            self._retry_after_update(jobs)
            return
        for j in jobs:
            # 狀態變了，或狀態一樣但結束時間變了（按「重試」後在兩次輪詢之間又失敗）
            if j.get("status") in ("done", "error") and j["id"] in before and before[j["id"]] != now[j["id"]]:
                self.job_finished.emit(j)

    def _retry_after_update(self, jobs: list[dict]):
        """「套用 yt-dlp 新版並重試」：App 重新啟動後第一次拿到清單時，繼續那些工作。"""
        store = settings_store()
        pending = load_retry_after_update(store)
        store.remove(RETRY_AFTER_UPDATE_KEY)
        if not pending:
            return
        for j in jobs:
            if j["id"] in pending and j.get("status") in ("error", "paused"):
                self.api.post(f"/api/jobs/{j['id']}/resume", {}, self.refresh, None)

    def _update_bulk(self):
        jobs = self.jobs
        active = sum(j.get("status") in ACTIVE for j in jobs)
        paused = sum(j.get("status") == "paused" for j in jobs)
        retry = sum(j.get("status") == "error" or (j.get("status") == "done" and bool(failed_items(j)))
                    for j in jobs)
        done = sum(j.get("status") == "done" for j in jobs)
        self.bulk.setVisible(bool(jobs))
        self.pause_all_btn.setEnabled(bool(active))
        self.resume_all_btn.setEnabled(bool(paused))
        self.retry_all_btn.setEnabled(bool(retry))
        self.clear_btn.setEnabled(bool(done))
        self.summary_label.setText(self.summary()["text"])

    # ---------- 給主視窗、系統匣用 ----------
    def summary(self) -> dict:
        """進行中數量與整體進度（F3 系統匣）：active＝排隊＋下載＋處理中的數量；progress＝0–100，沒有進行中為 None。"""
        jobs = self.jobs
        active = [j for j in jobs if j.get("status") in ACTIVE]
        paused = sum(j.get("status") == "paused" for j in jobs)
        failed = sum(j.get("status") == "error" for j in jobs)
        progress = None
        if active:
            progress = sum(min(max(float(j.get("progress") or 0), 0.0), 100.0) for j in active) / len(active)
        parts = []
        if active:
            parts.append(_tr("QueuePage", "%n 個下載進行中", None, len(active)))
        if paused:
            parts.append(_tr("QueuePage", "%n 個已暫停", None, paused))
        if failed:
            parts.append(_tr("QueuePage", "%n 個失敗", None, failed))
        text = " · ".join(parts)
        if progress is not None:
            text = self.tr("{status}（整體 {percent}%）").format(status=text, percent=round(progress))
        return {"active": len(active), "progress": progress, "paused": paused, "failed": failed,
                "total": len(jobs), "text": text}

    def _bulk_call(self, path: str, what: str, empty: str, done_text):
        def ok(r):
            n = r.get("count", 0) if isinstance(r, dict) else 0
            notify(self.toast, done_text(n) if n else empty)
            self.refresh()

        def err(m):
            notify(self.toast, self.tr("{action}失敗：{reason}").format(action=what, reason=m), "error")
            self.refresh()
        self.api.post(path, {}, ok, err)

    def pause_all(self):
        self._bulk_call("/api/jobs/pause_all", self.tr("暫停全部"), self.tr("沒有進行中的下載"),
                        lambda n: _tr("QueuePage", "已暫停 %n 個下載", None, n))

    def resume_all(self):
        self._bulk_call("/api/jobs/resume_all", self.tr("繼續全部"), self.tr("沒有暫停中的下載"),
                        lambda n: _tr("QueuePage", "已繼續 %n 個下載", None, n))

    def retry_all(self):
        self._bulk_call("/api/jobs/retry_all", self.tr("全部重試"), self.tr("沒有需要重試的工作"),
                        lambda n: _tr("QueuePage", "已重試 %n 個工作", None, n))

    def clear_finished(self):
        self._bulk_call("/api/jobs/clear", self.tr("清除已完成"), self.tr("沒有已完成的工作"),
                        lambda n: _tr("QueuePage", "已從清單移除 %n 個已完成的工作，檔案仍在原處", None, n))

    def show_job(self, job_id: str):
        """點通知時用：捲到該工作並短暫標示。清單還沒載入到這個工作時，載入後再做。"""
        row = self.rows.get(job_id)
        if row is None:
            self._pending_show = job_id
            self.refresh()
            return
        self._pending_show = None
        self._scroll_target = job_id
        QTimer.singleShot(0, self._scroll_to_target)
        t = self.theme or palette_tokens(self)
        row.setStyleSheet(f"#row {{ background: {t['select']}; border-radius: 8px; }}")
        row.setProperty("highlighted", True)

        def clear():
            if shiboken6.isValid(row):
                row.setStyleSheet("")
                row.setProperty("highlighted", False)
        QTimer.singleShot(2500, clear)
