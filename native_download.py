"""「新增下載」頁：貼上網址、解析影片資訊、選擇格式後加入下載佇列。"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QGuiApplication, QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

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
    label,
    load_download_defaults,
    page_layout,
    rounded,
)


# --------------------------------------------------------------------------- #
#  頁面：新增下載
# --------------------------------------------------------------------------- #
class DownloadPage(QWidget):
    queued = Signal()

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
        self.apply_defaults()
        for w in (self.quality, self.container, self.acodec, self.aquality):
            w.currentIndexChanged.connect(self.update_rows)
        self.set_loaded(False)

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
