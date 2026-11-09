"""「新增下載」頁：貼上網址、解析影片資訊、選擇格式後加入下載佇列。

給其他工作包呼叫的介面（ROADMAP 第 5.5 節）：
- `DownloadPage.focus_url()`：把焦點放到網址欄（開啟 App、切回這一頁時）。
- `DownloadPage.accept_urls(urls)`：從拖放、`ytdl://`、剪貼簿送進來的網址或 .txt 檔。
  一個網址 → 填入並解析（已經有解析好的影片時改成提示，不直接蓋掉）；多個 → 批次新增。
- `DownloadPage.cancel_analyze()`：取消解析（Esc）。
- `DownloadPage.start_download()`：加入下載佇列（Ctrl+Enter）。
"""
from __future__ import annotations

import html
import inspect
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

from PySide6.QtCore import QCoreApplication, QPointF, QRectF, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QGuiApplication,
    QKeySequence,
    QPainter,
    QPainterPath,
    QPalette,
    QPixmap,
    QPolygonF,
)
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

import i18n
from native_common import (
    AUDIO_CODECS,
    AUDIO_QUALITY,
    CONTAINERS,
    MODES,
    QUALITIES,
    Api,
    Card,
    PopUp,
    Segmented,
    fmt_duration,
    form_row,
    hairline,
    label,
    load_download_defaults,
    page_scroll,
    rounded,
)

_tr = QCoreApplication.translate  # 名稱固定是 _tr（docs/I18N.md 2.2）

BATCH_LIMIT = 100           # 批次新增一次最多幾個網址（F1）
TXT_LIMIT = 1_000_000       # 拖放或選擇的 .txt 最多讀多少位元組
SLOW_HINT_MS = 15_000       # 解析超過這麼久就說明「很長的清單會比較久」
THUMB_LARGE = QSize(192, 108)
THUMB_SMALL = QSize(128, 72)
NARROW_WIDTH = 640          # 頁面比這個窄時縮圖縮小（DL15）

# 網址到空白、引號或全形標點（，。、；（）「」）為止：中文句子裡的網址常常直接接著標點
_URL_IN_TEXT = re.compile(r"https?://[^\s<>\"'`，。、；（）「」]+", re.IGNORECASE)
_VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}")
_DOMAIN = re.compile(r"(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}(?::\d{1,5})?(?:[/?#]\S*)?")
_TRAILING = ".,;:!?)]}>，。、；"  # 網址後面黏著的標點（含全形逗號、句號）
_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")


# --------------------------------------------------------------------------- #
#  網址整理（DL6、F1）
# --------------------------------------------------------------------------- #
def normalize_url(text: str) -> str | None:
    """把使用者輸入整理成網址：補上 https://、11 碼影片 ID 轉成 YouTube 網址。認不出來回傳 None。"""
    t = (text or "").strip().strip("<>\"'`")
    if not t or any(c.isspace() for c in t) or len(t) > 2048:
        return None
    low = t.lower()
    if low.startswith(("http://", "https://")):
        return t if len(t) > len("https://") else None
    if _SCHEME.match(t) and not _DOMAIN.fullmatch(t):  # file:、javascript:、data: 這類一律不收
        return None
    if _VIDEO_ID.fullmatch(t):
        return f"https://www.youtube.com/watch?v={t}"
    if _DOMAIN.fullmatch(t):
        return "https://" + t
    return None


def extract_urls(text: str) -> tuple[list[str], int]:
    """逐行抽出網址（去掉重複），回傳（網址清單, 認不出網址的行數）。空白行和 # 開頭的行不算。"""
    urls: list[str] = []
    invalid = 0
    for line in (text or "").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        found = [u.rstrip(_TRAILING) for u in _URL_IN_TEXT.findall(s)]
        if not found:
            one = normalize_url(s)
            found = [one] if one else []
        if not found:
            invalid += 1
        for u in found:
            if u not in urls:
                urls.append(u)
    return urls, invalid


def _local_txt(item: str) -> Path | None:
    """拖放進來的 .txt：可能是 file:// 網址或本機路徑。"""
    s = (item or "").strip()
    if s.lower().startswith("file:"):
        s = QUrl(s).toLocalFile() or unquote(urlsplit(s).path)
    if not s.lower().endswith(".txt") or "\n" in s:
        return None
    try:
        p = Path(s)
        return p if p.is_file() else None
    except (OSError, ValueError):
        return None


def read_txt(path: Path) -> str:
    with open(path, "rb") as f:
        raw = f.read(TXT_LIMIT)
    # 只有開頭有 BOM 才當 UTF-16（任何偶數長度的位元組都能硬解成 UTF-16，Big5 檔會變亂碼）；
    # 其他編碼（例如 Big5）用 UTF-8 加取代字元讀：網址都是 ASCII，照樣抽得出來
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16", errors="replace")
    return raw.decode("utf-8-sig", errors="replace")


def expand_items(items: list[str]) -> str:
    """accept_urls 收到的東西（網址、整段文字、.txt 檔）合併成一段文字，交給 extract_urls。"""
    parts = []
    for it in items or []:
        if not isinstance(it, str):
            continue
        txt = _local_txt(it)
        if txt:
            try:
                parts.append(read_txt(txt))
            except OSError:
                parts.append(it)
        else:
            parts.append(it)
    return "\n".join(parts)


# --------------------------------------------------------------------------- #
#  小元件
# --------------------------------------------------------------------------- #
class ClickLabel(QLabel):
    """可以點的文字：和開關放在一起，點文字也能切換（DL13）。"""
    clicked = Signal()

    def __init__(self, text: str = "", name: str | None = None):
        super().__init__(text)
        if name:
            self.setObjectName(name)
        self.setWordWrap(True)
        self.setCursor(Qt.PointingHandCursor)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(e)


class UrlEdit(QLineEdit):
    """網址欄：貼上多行網址時改走批次新增（QLineEdit 本身會把換行吃掉）。"""
    multi_pasted = Signal(str)

    def keyPressEvent(self, e):
        if e.matches(QKeySequence.Paste):
            text = QGuiApplication.clipboard().text() or ""
            if len(extract_urls(text)[0]) > 1:
                self.multi_pasted.emit(text)
                e.accept()
                return
        super().keyPressEvent(e)


def placeholder_thumb(size: QSize, t: dict[str, str] | None = None) -> QPixmap:
    """縮圖還沒載入（或沒有縮圖）時的佔位圖：圓角底色＋播放符號（DL15）。"""
    t = t or {}
    pm = QPixmap(size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, size.width(), size.height()), 8, 8)
    p.fillPath(path, QColor(t.get("track", "#E5E5EA")))
    s = size.height() * 0.28
    cx, cy = size.width() / 2, size.height() / 2
    tri = QPolygonF()
    for x, y in ((cx - s * 0.4, cy - s * 0.5), (cx - s * 0.4, cy + s * 0.5), (cx + s * 0.55, cy)):
        tri.append(QPointF(x, y))
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(t.get("tertiary", "#AEAEB2")))
    p.drawPolygon(tri)
    p.end()
    return pm


# --------------------------------------------------------------------------- #
#  批次新增（F1）
# --------------------------------------------------------------------------- #
class BatchDialog(QDialog):
    """貼上多行網址或選擇 .txt，列成可勾選的清單，一行一個工作。"""

    def __init__(self, parent: QWidget | None = None, text: str = "", options_text: str = ""):
        super().__init__(parent)
        self.setWindowTitle(self.tr("批次新增"))
        self.setMinimumSize(520, 460)
        lay = QVBoxLayout(self)
        lay.setSpacing(8)
        intro = label(_tr("BatchDialog", "每行一個網址，一次最多 %n 個。也可以選擇 .txt 檔。", None, BATCH_LIMIT),
                      "subtitle", wrap=True)
        lay.addWidget(intro)

        self.text = QPlainTextEdit()
        self.text.setPlaceholderText(self.tr("在這裡貼上網址，每行一個"))
        self.text.setTabChangesFocus(True)
        self.text.setAccessibleName(self.tr("網址清單"))
        self.text.setMinimumHeight(110)
        lay.addWidget(self.text, 2)

        row = QHBoxLayout()
        self.file_btn = QPushButton(self.tr("選擇 .txt 檔…"))
        self.file_btn.clicked.connect(self.choose_file)
        row.addWidget(self.file_btn)
        row.addStretch()
        self.all_btn = self._link(self.tr("全選"), lambda: self._check_all(True))
        self.none_btn = self._link(self.tr("全不選"), lambda: self._check_all(False))
        row.addWidget(self.all_btn)
        row.addWidget(self.none_btn)
        lay.addLayout(row)

        self.info = label("", "subtitle", wrap=True)
        lay.addWidget(self.info)
        self.list = QListWidget()
        self.list.setAccessibleName(self.tr("要加入的網址"))
        self.list.setMinimumHeight(120)
        self.list.itemChanged.connect(lambda *_: self._update_count())
        lay.addWidget(self.list, 3)

        self.opts = label(self.tr("會套用目前的下載選項：{options}").format(options=options_text)
                          if options_text else "", "hint", wrap=True, plain=True)
        self.opts.setVisible(bool(options_text))
        lay.addWidget(self.opts)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        self.add_btn = self.buttons.addButton(self.tr("加入佇列"), QDialogButtonBox.AcceptRole)
        self.add_btn.setObjectName("primary")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        lay.addWidget(self.buttons)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self.reparse)
        self.text.textChanged.connect(self._timer.start)
        self.text.setPlainText(text)
        self.reparse()

    @staticmethod
    def _link(text: str, slot) -> QPushButton:
        b = QPushButton(text)
        b.setObjectName("link")
        b.setCursor(Qt.PointingHandCursor)
        b.clicked.connect(slot)
        return b

    def choose_file(self):
        path, _ = QFileDialog.getOpenFileName(self, self.tr("選擇網址清單"), "", self.tr("文字檔 (*.txt)"))
        if path:
            self.add_file(path)

    def add_file(self, path: str):
        try:
            content = read_txt(Path(path))
        except OSError as e:
            self.info.setText(self.tr("無法讀取這個檔案：{reason}").format(reason=e.strerror or str(e)))
            return
        cur = self.text.toPlainText().rstrip("\n")
        self.text.setPlainText((cur + "\n" if cur else "") + content)
        self.reparse()

    def reparse(self):
        self._timer.stop()
        urls, invalid = extract_urls(self.text.toPlainText())
        self.total = len(urls)
        self.invalid = invalid
        self.list.blockSignals(True)
        self.list.clear()
        for u in urls[:BATCH_LIMIT]:
            it = QListWidgetItem(u)
            it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable | Qt.ItemIsSelectable)
            it.setCheckState(Qt.Checked)
            it.setToolTip(u)
            self.list.addItem(it)
        self.list.blockSignals(False)
        self._update_count()

    def _check_all(self, on: bool):
        self.list.blockSignals(True)
        for i in range(self.list.count()):
            self.list.item(i).setCheckState(Qt.Checked if on else Qt.Unchecked)
        self.list.blockSignals(False)
        self._update_count()

    def selected_urls(self) -> list[str]:
        return [self.list.item(i).text() for i in range(self.list.count())
                if self.list.item(i).checkState() == Qt.Checked]

    def _update_count(self):
        n = len(self.selected_urls())
        bits = [_tr("BatchDialog", "找到 %n 個網址", None, self.total)]
        if self.invalid:
            bits.append(_tr("BatchDialog", "%n 行不是網址，已略過", None, self.invalid))
        if self.total > BATCH_LIMIT:
            bits.append(_tr("BatchDialog", "超過上限，只列出前 %n 個", None, BATCH_LIMIT))
        self.info.setText(" · ".join(bits) if self.total or self.invalid else self.tr("還沒有網址"))
        self.add_btn.setText(_tr("BatchDialog", "加入佇列（%n 個）", None, n) if n else self.tr("加入佇列"))
        self.add_btn.setEnabled(n > 0)
        has = self.list.count() > 0
        self.all_btn.setVisible(has)
        self.none_btn.setVisible(has)


# --------------------------------------------------------------------------- #
#  頁面：新增下載
# --------------------------------------------------------------------------- #
class DownloadPage(QWidget):
    queued = Signal()

    def __init__(self, api: Api, toast):
        super().__init__()
        # 不要移到檔案最上面：native_options 目前還從 native_app 匯入，會變成循環 import（WP-0 交接）
        from native_options import AdvancedOptions, Switch
        from native_playlist import PlaylistView
        self.api, self.toast, self.info = api, toast, None
        self._request = 0
        self._analyzed_url = ""
        self._analyzing = False
        self._reply = None
        self._pending_url = ""
        self._theme: dict[str, str] = {}
        self._thumb_src = QPixmap()
        self._thumb_size = QSize(THUMB_LARGE)
        self._batch: BatchDialog | None = None
        self._problem_target = ""

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        # 上方固定：網址列、開關、「偵測到新連結」、解析狀態。捲到下面設定選項時也看得到
        self.header = QWidget()
        self.header.setObjectName("content")
        lay = QVBoxLayout(self.header)
        lay.setContentsMargins(28, 20, 28, 8)
        lay.setSpacing(10)
        outer.addWidget(self.header)
        inner = QWidget()
        body = QVBoxLayout(inner)
        body.setContentsMargins(28, 4, 28, 20)
        body.setSpacing(10)
        self.scroll = page_scroll(inner)
        outer.addWidget(self.scroll, 1)

        # ---------- 網址列 ----------
        bar = QHBoxLayout()
        self.url = UrlEdit()
        self.url.setPlaceholderText(self.tr("貼上影片或播放清單網址，例如 https://www.youtube.com/watch?v=…"))
        self.url.setAccessibleName(self.tr("影片網址"))
        self.url.setClearButtonEnabled(True)
        self.url.returnPressed.connect(self.analyze)
        self.url.multi_pasted.connect(self.open_batch)
        self.paste_btn = QPushButton(self.tr("貼上"))
        self.paste_btn.clicked.connect(self.paste)
        self.batch_btn = QPushButton(self.tr("批次新增…"))
        self.batch_btn.setToolTip(self.tr("一次加入多個網址，或從 .txt 檔匯入"))
        self.batch_btn.clicked.connect(lambda: self.open_batch(""))
        self.analyze_btn = QPushButton(self.tr("解析"))
        self.analyze_btn.setObjectName("primary")
        self.analyze_btn.clicked.connect(self.analyze)
        # 解析中換成「取消」：用另一個按鈕放在同一個位置，寬度一樣，畫面不會跳動（DL3）
        self.cancel_btn = QPushButton(self.tr("取消"))
        self.cancel_btn.setToolTip(self.tr("停止解析（Esc）"))
        self.cancel_btn.clicked.connect(self.cancel_analyze)
        self.cancel_btn.hide()
        fm = self.analyze_btn.fontMetrics()
        texts = (self.analyze_btn.text(), self.cancel_btn.text())
        w = max(max(fm.horizontalAdvance(t) for t in texts), fm.averageCharWidth() * 9) + 36
        for b in (self.analyze_btn, self.cancel_btn):
            b.setMinimumWidth(w)
        bar.addWidget(self.url, 1)
        bar.addWidget(self.paste_btn)
        bar.addWidget(self.batch_btn)
        bar.addWidget(self.analyze_btn)
        bar.addWidget(self.cancel_btn)
        lay.addLayout(bar)

        # ---------- 「下載整個清單」開關：開關和文字是同一個可點元件（DL13） ----------
        # 和網頁版一樣一律顯示：哪些網址算播放清單由 yt-dlp 依網站判斷（YouTube、Bilibili 分 P…）
        list_row = QHBoxLayout()
        list_row.setContentsMargins(2, 0, 0, 0)
        self.as_playlist = Switch(False)
        playlist_text = self.tr("網址含播放清單時，下載整個清單")
        self.as_playlist.setAccessibleName(playlist_text)
        self.as_playlist.toggled.connect(self._playlist_toggled)
        self.as_playlist_label = ClickLabel(playlist_text, "subtitle")
        self.as_playlist_label.clicked.connect(self.as_playlist.toggle)
        list_row.addWidget(self.as_playlist)
        list_row.addWidget(self.as_playlist_label, 1)
        lay.addLayout(list_row)

        # ---------- 偵測到新連結（DL5） ----------
        self.new_link = QFrame()
        self.new_link.setObjectName("card")
        nl = QHBoxLayout(self.new_link)
        nl.setContentsMargins(12, 6, 8, 6)
        self.new_link_text = label("", None, plain=True)
        self.new_link_text.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        nl.addWidget(self.new_link_text, 1)
        self.new_link_go = QPushButton(self.tr("解析"))
        self.new_link_go.clicked.connect(self._use_pending)
        self.new_link_skip = QPushButton(self.tr("忽略"))
        self.new_link_skip.clicked.connect(self.dismiss_pending)
        nl.addWidget(self.new_link_go)
        nl.addWidget(self.new_link_skip)
        self.new_link.hide()
        lay.addWidget(self.new_link)

        # ---------- 解析中：狀態文字＋不確定進度條（DL3） ----------
        self.status = label("", "subtitle", wrap=True, plain=True)
        self.status.hide()
        lay.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.setAccessibleName(self.tr("正在解析"))
        self.progress.hide()
        lay.addWidget(self.progress)
        self._slow_timer = QTimer(self)
        self._slow_timer.setSingleShot(True)
        self._slow_timer.timeout.connect(self._slow_hint)

        lay = body  # 以下放在可以捲動的內容區
        # ---------- 解析失敗（ERR1） ----------
        self.err_box = QFrame()
        self.err_box.setObjectName("card")
        el = QVBoxLayout(self.err_box)
        el.setContentsMargins(14, 10, 14, 10)
        el.setSpacing(6)
        self.err_text = label("", "errorText", wrap=True, plain=True)
        self.err_text.setTextInteractionFlags(Qt.TextSelectableByMouse)
        el.addWidget(self.err_text)
        err_row = QHBoxLayout()
        err_row.setSpacing(8)
        self.err_action_btn = QPushButton()
        self.err_action_btn.clicked.connect(self._run_error_action)
        self.err_detail_btn = BatchDialog._link(self.tr("詳細資訊"), self._toggle_detail)
        self.err_faq_btn = BatchDialog._link(self.tr("怎麼解決？"), self._open_faq)
        err_row.addWidget(self.err_action_btn)
        err_row.addWidget(self.err_faq_btn)
        err_row.addWidget(self.err_detail_btn)
        err_row.addStretch()
        el.addLayout(err_row)
        self.err_detail = label("", "hint", wrap=True, plain=True)
        self.err_detail.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.err_detail.hide()
        el.addWidget(self.err_detail)
        self.err_box.hide()
        lay.addWidget(self.err_box)
        self._err: dict = {}

        # ---------- 空狀態（DL9） ----------
        self.empty = self._build_empty()
        lay.addWidget(self.empty)

        # ---------- 影片資訊 ----------
        self.video = QFrame()
        self.video.setObjectName("card")
        vl = QHBoxLayout(self.video)
        vl.setContentsMargins(12, 12, 14, 12)
        vl.setSpacing(14)
        self.thumb = QLabel()
        self.thumb.setFixedSize(self._thumb_size)
        self.thumb.setAlignment(Qt.AlignCenter)
        vl.addWidget(self.thumb, 0, Qt.AlignTop)
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

        # 播放清單（解析到播放清單時取代影片資訊卡；高度填滿畫面剩下的空間，DL1）
        self.playlist = PlaylistView(image_loader=api.image)
        self.playlist.selectionChanged.connect(self.update_summary)
        self.playlist.hide()
        lay.addWidget(self.playlist)

        # ---------- 下載選項 ----------
        self.opts_header = label(self.tr("下載選項"), "sectionHeader")
        lay.addSpacing(6)
        lay.addWidget(self.opts_header)
        self.mode = Segmented(MODES)
        self.mode.changed.connect(self._mode_changed)
        mode_holder = QHBoxLayout()
        mode_holder.addWidget(self.mode)
        mode_holder.addStretch()
        lay.addLayout(mode_holder)

        self.card = Card()
        self.quality = PopUp()
        self.container = PopUp(CONTAINERS)
        self.acodec = PopUp(AUDIO_CODECS)
        self.aquality = PopUp(AUDIO_QUALITY)
        self.r_quality = self.card.add(form_row(self.tr("畫質"), self.quality))
        self.r_container = self.card.add(form_row(self.tr("檔案格式"), self.container))
        self.r_acodec = self.card.add(form_row(self.tr("音訊格式"), self.acodec))
        self.r_aquality = self.card.add(form_row(self.tr("音質"), self.aquality))
        lay.addWidget(self.card)

        # 進階選項：音軌、字幕、剪輯、SponsorBlock、中繼資料、網路
        self.advanced = AdvancedOptions(api, toast)
        self.advanced.changed.connect(self.update_summary)
        lay.addWidget(self.advanced)
        lay.addStretch()

        # ---------- 底部固定的動作列：摘要＋下載（DL1） ----------
        self.action_bar = QFrame()
        self.action_bar.setObjectName("content")
        ab = QVBoxLayout(self.action_bar)
        ab.setContentsMargins(0, 0, 0, 0)
        ab.setSpacing(0)
        ab.addWidget(hairline())
        foot = QHBoxLayout()
        foot.setContentsMargins(28, 10, 28, 12)
        self.summary = QLabel()
        self.summary.setObjectName("subtitle")
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(Qt.RichText)
        self.summary.setTextInteractionFlags(Qt.LinksAccessibleByMouse | Qt.LinksAccessibleByKeyboard)
        self.summary.linkActivated.connect(self._fix_problem)
        foot.addWidget(self.summary, 1)
        self.download_btn = QPushButton(self.tr("下載"))
        self.download_btn.setObjectName("primary")
        self.download_btn.setMinimumWidth(max(fm.horizontalAdvance(self.download_btn.text()),
                                              fm.averageCharWidth() * 9) + 36)
        self.download_btn.clicked.connect(self.download)
        foot.addWidget(self.download_btn)
        ab.addLayout(foot)
        outer.addWidget(self.action_bar)

        self._saved_quality = None
        self.apply_defaults()
        for w in (self.quality, self.container, self.acodec, self.aquality):
            w.currentIndexChanged.connect(self.update_rows)
        self.set_loaded(False)

    def _build_empty(self) -> QWidget:
        box = QFrame()
        box.setObjectName("card")
        v = QVBoxLayout(box)
        v.setContentsMargins(18, 14, 18, 16)
        v.setSpacing(8)
        v.addWidget(label(self.tr("三個步驟下載影片"), "rowTitle"))
        steps = (self.tr("1. 在瀏覽器複製影片、播放清單或頻道的網址"),
                 self.tr("2. 貼到上面的欄位，按「解析」（或 Enter）"),
                 self.tr("3. 選擇畫質或格式，按「下載」"))
        for s in steps:
            v.addWidget(label(s, None, wrap=True))
        v.addSpacing(4)
        v.addWidget(label(self.tr("支援 YouTube、Bilibili、X（Twitter）、Vimeo、SoundCloud 等上千個網站。"
                                  "也可以直接輸入 11 碼的 YouTube 影片 ID。"), "subtitle", wrap=True))
        tips = label(self.tr('小技巧：可以把網址或 .txt 檔拖進視窗；一次下載很多個請用「批次新增」；'
                             '安裝<a href="{url}">書籤小工具</a>後，在瀏覽器點一下就能把網址送進來。')
                     .format(url=html.escape(i18n.guide_url("bookmarklet"), quote=True)), "hint", wrap=True)
        tips.setTextFormat(Qt.RichText)
        tips.setOpenExternalLinks(True)
        self.tips = tips
        v.addWidget(tips)
        return box

    # ---------- 給主視窗呼叫的介面 ----------
    def focus_url(self):
        """把焦點放到網址欄並全選，可以直接 Ctrl+V、Enter（DL7）。"""
        self.url.setFocus(Qt.ShortcutFocusReason)
        self.url.selectAll()

    def accept_urls(self, urls: list[str]):
        """拖放、ytdl://、剪貼簿送進來的網址（F4／F7）。一個 → 填入並解析；多個 → 批次新增。"""
        text = expand_items(list(urls or []))
        found, invalid = extract_urls(text)
        if not found:
            self._notify(self.tr("沒有找到可以下載的網址"), error=True)
            return
        if len(found) > 1 or invalid:
            self.open_batch(text)
            return
        self.offer_url(found[0])

    def offer_url(self, url: str):
        """送進來一個網址：畫面上已經有影片、正在解析、或欄位裡有還沒解析的網址時先問，不直接蓋掉（DL5）。"""
        url = normalize_url(url) or url.strip()
        current = self.url.text().strip()
        if not url or url in (current, self._analyzed_url) and (self.info or self._analyzing):
            return
        typing = current and current not in (url, self._analyzed_url)
        if self.info or self._analyzing or typing:
            self._pending_url = url
            self.new_link_text.setText(self.tr("偵測到新連結：{url}").format(url=url))
            self.new_link_text.setToolTip(url)
            self.new_link.show()
            return
        self.dismiss_pending()
        self.url.setText(url)
        self.analyze()

    def dismiss_pending(self):
        self._pending_url = ""
        self.new_link.hide()

    def _use_pending(self):
        url = self._pending_url
        self.dismiss_pending()
        if url:
            self.url.setText(url)
            self.analyze()

    def start_download(self):
        """Ctrl+Enter：已解析時加入下載佇列。"""
        if self.info and self.download_btn.isEnabled():
            self.download()

    # ---------- 下載預設值（在「設定 → 下載預設值」調整） ----------
    def apply_defaults(self, d: dict | None = None):
        """套用預設的模式、畫質、格式：App 開啟時，以及在設定頁改了預設值時。"""
        d = d or load_download_defaults()
        if d["mode"] in self.mode.buttons:
            self.mode.set_value(d["mode"])
        self.container.select(d["container"])
        self.acodec.select(d["acodec"])
        self.aquality.select(d["aquality"])
        self._saved_quality = d["quality"]
        # 已經解析過影片：沒有這個畫質（影片解析度較低）時用最佳畫質
        if self.quality.count() and not self.quality.select(d["quality"]):
            self.quality.setCurrentIndex(0)
        self.as_playlist.blockSignals(True)
        self.as_playlist.setChecked(d["as_playlist"])
        self.as_playlist.blockSignals(False)
        if self.info:
            self.update_rows()

    def apply_theme(self, t: dict[str, str]):
        self._theme = dict(t)
        for w in (self.tips, self.summary):  # 文字裡的連結用主題色，不要預設的深藍色
            pal = w.palette()
            pal.setColor(QPalette.Link, QColor(t.get("accent", "#007AFF")))
            w.setPalette(pal)
        self.advanced.apply_theme(t)
        self.playlist.apply_theme(t)
        if self._thumb_src.isNull():
            self.thumb.setPixmap(placeholder_thumb(self._thumb_size, self._theme))

    def set_status(self, text: str, error: bool = False):
        self.status.setObjectName("errorText" if error else "subtitle")
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)
        self.status.setText(text)
        self.status.setVisible(bool(text))

    def _playlist_toggled(self, on: bool = False, *_):
        # 解析後才切換：用新的設定重新解析，避免畫面顯示單一影片、實際卻要下載整個清單（或相反）
        if self._analyzed_url and self.url.text().strip() == self._analyzed_url:
            self.analyze()
            self.set_status(self.tr("已改成下載整個播放清單，正在重新解析…") if on
                            else self.tr("已改成只下載這部影片，正在重新解析…"))

    def paste(self):
        text = (QGuiApplication.clipboard().text() or "").strip()
        if len(extract_urls(text)[0]) > 1:
            self.open_batch(text)
            return
        self.dismiss_pending()
        self.url.setText(text)
        self.analyze()

    def is_playlist(self) -> bool:
        return bool(self.info) and self.info.get("type") == "playlist"

    def set_loaded(self, loaded: bool):
        for w in (self.opts_header, self.mode, self.card, self.advanced, self.action_bar):
            w.setVisible(loaded)
        self.video.setVisible(loaded and not self.is_playlist())
        self.playlist.setVisible(loaded and self.is_playlist())
        self.empty.setVisible(not loaded and not self._analyzing)
        # 解析後「下載」才是主要按鈕，「解析」改成次要樣式（DL1）。macOS 原生按鈕只有「預設按鈕」是藍色
        self.analyze_btn.setObjectName("" if loaded else "primary")
        self.analyze_btn.style().unpolish(self.analyze_btn)
        self.analyze_btn.style().polish(self.analyze_btn)
        self.analyze_btn.setDefault(not loaded)
        self.download_btn.setDefault(loaded)
        if loaded and self.is_playlist():
            QTimer.singleShot(0, self._fit_playlist)

    # ---------- 解析 ----------
    def analyze(self):
        raw = self.url.text().strip()
        if not raw:
            self.url.setFocus()
            return
        url = normalize_url(raw) or raw  # 少了 https://、只有 11 碼 ID 都幫忙補上（DL6）
        if url != raw:
            self.url.setText(url)
        if self._analyzing:
            self._request += 1  # 先換序號：abort() 可能馬上觸發舊請求的錯誤回呼，要當成舊結果丟掉
            self._abort_reply()
        self.dismiss_pending()
        self._analyzing = True
        self.analyze_btn.setEnabled(False)
        self.analyze_btn.hide()
        self.cancel_btn.show()
        self.progress.show()
        self.set_status(self.tr("正在讀取影片資訊，通常只要幾秒鐘…"))
        self._slow_timer.start(SLOW_HINT_MS)
        self._clear_error()
        self.info = None
        self._analyzed_url = url
        self.set_loaded(False)
        self.scroll.verticalScrollBar().setValue(0)
        # 解析中又按 Enter 會再送一次：只採用最後一次的結果，先送出但較慢回來的舊結果直接丟掉
        self._request += 1
        req = self._request
        body = {"url": url, "noplaylist": not self.as_playlist.isChecked(), "network": self.advanced.network()}
        # 不限時間：大型播放清單、頻道可能要解析好幾分鐘（網頁版也不限）；可以按「取消」
        self._reply = self.api.post("/api/info", body, lambda info: req == self._request and self.on_info(info),
                                    lambda msg, *rest: req == self._request and self.on_info_error(msg, *rest),
                                    timeout_ms=0)

    def _abort_reply(self):
        reply, self._reply = self._reply, None
        if reply is not None and hasattr(reply, "abort"):
            try:
                reply.abort()
            except RuntimeError:  # 已經完成、物件被刪掉了
                pass

    def cancel_analyze(self):
        """取消解析：丟掉請求序號、中止連線，馬上恢復可以輸入（DL3）。"""
        if not self._analyzing:
            return
        self._request += 1  # 先換序號：abort() 觸發的錯誤回呼會被當成舊結果丟掉
        self._abort_reply()
        self._finish_analyzing()
        self._analyzed_url = ""
        self.set_loaded(False)
        self.set_status(self.tr("已取消解析"))
        self.focus_url()

    def _finish_analyzing(self):
        self._analyzing = False
        self._reply = None
        self._slow_timer.stop()
        self.progress.hide()
        self.cancel_btn.hide()
        self.analyze_btn.show()
        self.analyze_btn.setEnabled(True)

    def _slow_hint(self):
        if self._analyzing:
            self.set_status(self.tr("還在讀取中。播放清單或頻道很長時會比較久，不想等可以按「取消」。"))

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape and self._analyzing:
            self.cancel_analyze()
            e.accept()
            return
        super().keyPressEvent(e)

    # ---------- 解析失敗（ERR1） ----------
    def on_info_error(self, msg, payload: dict | None = None):
        """msg 是錯誤文字；引擎的錯誤物件（error_detail、error_action、error_faq）可能放在
        第二個參數、msg 本身（dict），或 msg.payload（Api 回傳的字串子類別）。都沒有就只顯示文字。"""
        payload = self._payload(msg, () if payload is None else (payload,))
        text =str(payload.get("error") or (msg if isinstance(msg, str) else "") or "")
        self._finish_analyzing()
        self.set_status("")
        self.set_loaded(False)
        self.show_error(text, payload)

    def show_error(self, message: str, payload: dict | None = None):
        p = payload or {}
        self._err = p
        # 引擎的 error 已依語言組好，不再翻譯（docs/I18N.md 2.7）；沒有錯誤物件時和以前一樣加上「無法解析」
        self.err_text.setText(message if p.get("error_code") else
                              self.tr("無法解析：{message}").format(message=message))
        detail = str(p.get("error_detail") or "").strip()
        self.err_detail.setText(detail)
        self.err_detail.hide()
        self.err_detail_btn.setText(self.tr("詳細資訊"))
        self.err_detail_btn.setVisible(bool(detail) and detail != message)
        self.err_faq_btn.setVisible(bool(p.get("error_faq")))
        actions = self._error_actions(p.get("error_action"))
        if actions:
            self.err_action_btn.setText(actions[0][0])
            self._err_callback = actions[0][1]
        self.err_action_btn.setVisible(bool(actions))
        self.err_box.show()

    def _clear_error(self):
        self._err = {}
        self.err_box.hide()

    def _toggle_detail(self):
        show = self.err_detail.isHidden()
        self.err_detail.setVisible(show)
        self.err_detail_btn.setText(self.tr("隱藏詳細資訊") if show else self.tr("詳細資訊"))

    def _open_faq(self):
        faq = str(self._err.get("error_faq") or "")
        QDesktopServices.openUrl(QUrl(i18n.guide_url(faq)))

    def _run_error_action(self):
        cb = getattr(self, "_err_callback", None)
        cb and cb()

    def _main_window(self):
        w = self.window()
        return None if w is self else w

    def _open_settings(self, section: str):
        """C1 的 MainWindow.open_settings(section)；還沒有時退回切到設定頁。"""
        w = self._main_window()
        if w is not None and hasattr(w, "open_settings"):
            w.open_settings(section)
        elif w is not None and hasattr(w, "go"):
            w.go(2)

    def _open_network_options(self, prefer_settings: str = ""):
        """Cookie、代理在「進階選項 → 網路」：解析前也會用到，所以解析失敗時也要能打開。"""
        w = self._main_window()
        if prefer_settings and w is not None and hasattr(w, "open_settings"):
            w.open_settings(prefer_settings)
            return
        self.advanced.show()
        self.reveal("network")

    def _error_actions(self, action) -> list[tuple[str, object]]:
        """依 error_action 決定按鈕（第 5.5 節的值）。不認得的值不顯示按鈕。"""
        table = {
            "open_cookie_settings": (self.tr("設定 Cookie"), lambda: self._open_network_options("cookies")),
            "open_storage_settings": (self.tr("更換儲存位置"), lambda: self._open_settings("storage")),
            "open_network_settings": (self.tr("網路設定"), lambda: self._open_network_options()),
            "update_ytdlp": (self.tr("更新 yt-dlp"), lambda: self._open_settings("about")),
            "reanalyze": (self.tr("重新解析"), self.analyze),
            "retry": (self.tr("重試"), self.analyze),
        }
        return [table[action]] if action in table else []

    # ---------- 解析完成 ----------
    def on_info(self, info: dict):
        req = self._request
        self._finish_analyzing()
        self.set_status("")
        self._clear_error()
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
                bits.append(self.tr("最高 {height}p").format(height=heights[0]))
            if info.get("view_count"):
                bits.append(_tr("DownloadPage", "%Ln 次觀看", None, int(info["view_count"])))
            if info.get("extractor"):
                bits.append(info["extractor"])
            self.details.setText(" · ".join(b for b in bits if b))
            self._thumb_src = QPixmap()
            self.thumb.setPixmap(placeholder_thumb(self._thumb_size, self._theme))
            if info.get("thumbnail"):
                self.api.image(info["thumbnail"], lambda pm: pm.isNull() or req != self._request
                               or self.set_thumb(pm))
        # 播放清單沒有各部影片的畫質資訊，列出全部（超過來源畫質時 yt-dlp 會自動選最接近的）
        self.quality.set_items([(None, self.tr("最佳畫質"))] + [(h, name) for h, name in QUALITIES
                                                              if not heights or h <= heights[0]],
                               prefer=self._saved_quality)
        self.advanced.set_info(info)
        self.set_loaded(True)
        self.update_rows()
        self.scroll.verticalScrollBar().setValue(0)  # 新的影片從最上面開始看

    def set_thumb(self, pm: QPixmap):
        self._thumb_src = pm
        self._render_thumb()

    def _render_thumb(self):
        s = self._thumb_size
        self.thumb.setFixedSize(s)
        if self._thumb_src.isNull():
            self.thumb.setPixmap(placeholder_thumb(s, self._theme))
        else:
            self.thumb.setPixmap(rounded(self._thumb_src, s.width(), s.height(), 8))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        size = THUMB_SMALL if self.width() < NARROW_WIDTH else THUMB_LARGE  # 窄視窗縮圖縮小，留空間給標題（DL15）
        if size != self._thumb_size:
            self._thumb_size = QSize(size)
            self._render_thumb()
        if self.playlist.isVisible():
            self._fit_playlist()

    def _fit_playlist(self):
        """播放清單填滿畫面剩下的高度：不用先捲動頁面才看得到清單（DL1）。"""
        if not self.playlist.isVisible():
            return
        avail = self.scroll.viewport().height() - self.playlist.y() - 12
        self.playlist.setFixedHeight(max(self.playlist.minimumSizeHint().height(), avail))

    # ---------- 選項 ----------
    def _mode_changed(self, mode: str):
        self.update_rows()
        if mode == "subs" and self.info:  # 字幕模式最重要的是選語言：自動展開「字幕」分組（DL2）
            self.reveal("subtitles")

    def reveal(self, key: str):
        """展開進階選項的某個分組並捲過去：用 A2 的 reveal_section，還沒有時自己展開。"""
        adv = self.advanced
        if hasattr(adv, "reveal_section"):
            adv.reveal_section(key)
            return
        sec = getattr(adv, "sections", {}).get({"subtitles": "subs"}.get(key, key))
        if sec is None:
            return
        if hasattr(sec, "set_expanded"):
            sec.set_expanded(True)
        QTimer.singleShot(0, lambda: sec.isVisible() and self.scroll.ensureWidgetVisible(sec, 0, 40))

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
        quality = self.quality.currentData() if self.quality.count() else self._saved_quality
        o = {
            "mode": self.mode.value(),
            "video": {"max_height": quality or "", "container": self.container.currentData()},
            "audio": {"languages": [], "codec": self.acodec.currentData(), "quality": self.aquality.currentData()},
            "subs": {"languages": [], "auto_languages": []},
        }
        o = self.advanced.apply(o)
        if self.is_playlist():
            o["playlist"] = True
            o["playlist_items"] = self.playlist.playlist_items()
        return o

    def _subs_missing(self) -> bool:
        s = self.advanced.apply({"mode": "subs", "subs": {"languages": [], "auto_languages": []}})["subs"]
        return not (s.get("languages") or s.get("auto_languages") or s.get("all"))

    def _problem(self) -> tuple[str, str]:
        """（不能送出的原因, 點了要去修正的地方）。可以下載時是 ("", "")。"""
        if not self.info:
            return self.tr("請先解析網址"), ""
        if self.is_playlist() and self.playlist.selected_count() == 0:
            # playlist_items 為空時引擎會下載整個清單，所以一定要擋下來
            return self.tr("請至少選擇一部影片"), "select_all"
        mode = self.mode.value()
        if mode == "subs" and self._subs_missing():
            return self.tr("請在「字幕」選擇至少一種語言"), "subtitles"
        if mode in ("av", "video", "audio"):  # 時間範圍只有影音模式會用到（其他模式時剪輯分組是隱藏的）
            err = self.advanced.error() or ""
            return err, ("clip" if err else "")
        return "", ""

    def problem(self) -> str:
        """目前選項不能送出的原因（空字串表示可以下載）。"""
        return self._problem()[0]

    def _problem_html(self, text: str, target: str) -> str:
        """摘要裡的錯誤做成可以點的連結，點了跳到要修正的地方（DL2）。"""
        if target == "select_all":
            return self.tr('請至少選擇一部影片（<a href="select_all">全選</a>）')
        if target == "subtitles":
            return self.tr('請在<a href="subtitles">「字幕」</a>選擇至少一種語言')
        return f'<a href="{target}">{html.escape(text)}</a>' if target else html.escape(text)

    def _fix_problem(self, target: str):
        if target == "select_all":
            self.playlist.select_all()
        elif target:
            self.reveal(target)

    def summary_text(self) -> str:
        """目前選項的一行摘要（也用在批次新增）。"""
        m = self.mode.value()
        if m in ("av", "video"):
            q = self.quality.currentText() if self.quality.count() else self.tr("最佳畫質")
            bits = [q, self.container.currentText()]
            if m == "video":
                bits.append(self.tr("不含聲音"))
        elif m == "audio":
            bits = [self.acodec.currentText()]
        elif m == "subs":
            bits = [self.tr("只下載字幕")]
        else:
            bits = [self.tr("只下載封面圖")]
        return " · ".join(b for b in bits if b)

    def update_summary(self, *_):
        if not self.info:
            return
        text = self.summary_text()
        if self.is_playlist():
            text += " · " + _tr("DownloadPage", "%n 部影片", None, self.playlist.selected_count())
        problem, target = self._problem()
        self._problem_target = target
        self.summary.setText(self._problem_html(problem, target) if problem else html.escape(text))
        self.summary.setObjectName("errorText" if problem else "subtitle")
        self.summary.style().unpolish(self.summary)
        self.summary.style().polish(self.summary)
        self.download_btn.setEnabled(not problem)

    # ---------- 下載 ----------
    def _notify(self, text: str, error: bool = False, actions: list | None = None):
        """C1 的 toast(text, level=, actions=)；舊版 toast(text, error=) 也能用。"""
        try:
            params = inspect.signature(self.toast).parameters
        except (TypeError, ValueError):
            params = {}
        if "level" in params:
            kw = {"level": "error" if error else "info"}
            if actions and "actions" in params:
                kw["actions"] = actions
            self.toast(text, **kw)
        elif error:
            self.toast(text, error=True)
        else:
            self.toast(text)

    @staticmethod
    def _payload(msg, rest) -> dict:
        p = rest[0] if rest else (msg if isinstance(msg, dict) else getattr(msg, "payload", None))
        return p if isinstance(p, dict) else {}

    def download(self):
        problem, target = self._problem()
        if problem:
            self._notify(problem, error=True)
            self._fix_problem(target)
            return
        self.download_btn.setEnabled(False)
        title = self.info.get("title") or ""

        def ok(_):
            self.download_btn.setEnabled(True)
            self._notify(self.tr("已加入下載佇列：{title}").format(title=title))
            self.queued.emit()

        def err(msg, *rest):
            self.download_btn.setEnabled(True)
            p = self._payload(msg, rest)
            text = str(p.get("error") or msg)
            actions = [(lbl, cb) for lbl, cb in self._error_actions(p.get("error_action"))
                       if cb not in (self.analyze,)]
            self._notify(self.tr("無法開始下載：{message}").format(message=text), error=True, actions=actions)

        self.api.post("/api/download", {"url": self.info.get("webpage_url") or self._analyzed_url,
                                        "title": title, "options": self.options()}, ok, err)

    # ---------- 批次新增（F1） ----------
    def open_batch(self, text: str = ""):
        if self._batch is not None:
            self._batch.close()
        dlg = BatchDialog(self, text, self.summary_text())
        dlg.accepted.connect(lambda: self.queue_batch(dlg.selected_urls()))
        dlg.finished.connect(lambda *_: dlg.deleteLater())
        self._batch = dlg
        dlg.destroyed.connect(lambda *_: setattr(self, "_batch", None) if self._batch is dlg else None)
        dlg.open()
        return dlg

    def _batch_problem(self) -> str:
        mode = self.mode.value()
        if mode == "subs" and self._subs_missing():
            return self.tr("字幕模式要先在「字幕」選擇語言，才能批次新增")
        if mode in ("av", "video", "audio"):
            return self.advanced.error() or ""
        return ""

    def batch_options(self) -> dict:
        """批次新增套用目前的選項；每個網址一個工作。播放清單照「下載整個清單」開關。"""
        o = self.options()
        o.pop("playlist_items", None)
        o["playlist"] = self.as_playlist.isChecked()
        return o

    def queue_batch(self, urls: list[str]):
        urls = list(dict.fromkeys(u for u in urls if u))[:BATCH_LIMIT]
        if not urls:
            return
        problem = self._batch_problem()
        if problem:
            self._notify(problem, error=True)
            return
        options = self.batch_options()
        state = {"ok": 0, "failed": [], "left": list(urls)}
        self.batch_btn.setEnabled(False)

        def next_one():
            if not state["left"]:
                return finish()
            url = state["left"].pop(0)

            def ok(_):
                state["ok"] += 1
                next_one()

            def err(msg, *rest):
                p = self._payload(msg, rest)
                state["failed"].append((url, str(p.get("error") or msg)))
                next_one()

            # 一個一個送：佇列順序和清單一樣
            self.api.post("/api/download", {"url": url, "options": options}, ok, err)

        def finish():
            self.batch_btn.setEnabled(True)
            if state["ok"]:
                self.queued.emit()
            failed = state["failed"]
            if failed:
                self._notify(_tr("DownloadPage", "有 %n 個網址無法加入佇列，例如：{message}", None, len(failed))
                             .format(message=failed[0][1]) + " " +
                             _tr("DownloadPage", "其他 %n 個已加入。", None, state["ok"]), error=True)
            else:
                self._notify(_tr("DownloadPage", "已加入 %n 個下載", None, state["ok"]))

        next_one()
