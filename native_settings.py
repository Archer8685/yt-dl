"""「設定」頁：下載資料夾、外觀、下載預設值、yt-dlp 更新、YouTube Premium、關於。"""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QMessageBox, QPushButton, QVBoxLayout, QWidget

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


# --------------------------------------------------------------------------- #
#  頁面：設定
# --------------------------------------------------------------------------- #
class SettingsPage(QWidget):
    meta_changed = Signal(dict)
    appearance_changed = Signal()  # 外觀或文字大小改了：主程式重新套用樣式
    defaults_changed = Signal(dict)  # 下載預設值改了：「新增下載」頁立刻套用

    def __init__(self, api: Api, toast, advanced=None):
        super().__init__()
        self.api, self.toast = api, toast
        self.advanced = advanced  # 進階選項面板：Cookie 來源與「Premium 高位元率」開關在那裡
        lay = page_layout(self)
        from native_options import Switch

        # 一般
        lay.addWidget(label("一般", "sectionHeader"))
        general = Card()
        self.auto_paste = Switch(auto_paste_enabled())
        self.auto_paste.toggled.connect(set_auto_paste)
        general.add(form_row("自動貼上剪貼簿裡的影片連結", self.auto_paste))
        lay.addWidget(general)
        lay.addWidget(label("開啟 App 或切回視窗時，剪貼簿裡如果是 YouTube 等支援網站的影片連結，"
                            "會自動貼到「新增下載」並開始解析；一般網頁連結不會。", "hint", wrap=True))

        # 外觀
        lay.addSpacing(8)
        lay.addWidget(label("外觀", "sectionHeader"))
        look = Card()
        theme, size = ui_prefs()
        self.theme = Segmented(THEMES)
        self.theme.set_value(theme)
        self.font_size = Segmented(FONT_SIZES)
        self.font_size.set_value(size)
        self.theme.changed.connect(self._appearance_changed)
        self.font_size.changed.connect(self._appearance_changed)
        look.add(form_row("主題", self.theme))
        look.add(form_row("文字大小", self.font_size))
        lay.addWidget(look)

        # 下載預設值：每次開啟 App，「新增下載」都從這些選項開始
        lay.addSpacing(8)
        head = QHBoxLayout()
        head.addWidget(label("下載預設值", "sectionHeader"))
        head.addStretch()
        reset_all = QPushButton("恢復所有預設值")
        reset_all.setObjectName("link")
        reset_all.clicked.connect(self.reset_all)
        head.addWidget(reset_all)
        lay.addLayout(head)
        defaults = Card()
        self.def_mode = PopUp(MODES)
        self.def_quality = PopUp([(None, "最佳畫質")] + QUALITIES)
        self.def_container = PopUp(CONTAINERS)
        self.def_acodec = PopUp(AUDIO_CODECS)
        self.def_aquality = PopUp(AUDIO_QUALITY)
        self.def_playlist = Switch(False)
        for w in (self.def_mode, self.def_quality, self.def_container, self.def_acodec, self.def_aquality):
            w.setMinimumWidth(170)  # 同一張卡片裡的選單一樣寬，比較整齊
        defaults.add(form_row("下載模式", self.def_mode))
        defaults.add(form_row("畫質", self.def_quality))
        defaults.add(form_row("影片格式", self.def_container))
        defaults.add(form_row("音訊格式（僅音訊時）", self.def_acodec))
        defaults.add(form_row("音質（MP3 / M4A 等）", self.def_aquality))
        defaults.add(form_row("網址含播放清單時下載整個清單", self.def_playlist))
        lay.addWidget(defaults)
        lay.addWidget(label("影片解析度比預設畫質低時會自動用最佳畫質。字幕、剪輯、中繼資料等進階選項"
                            "在「新增下載 → 進階選項」調整，會記住上次的設定。", "hint", wrap=True))
        self.show_defaults(load_download_defaults())
        for w in (self.def_mode, self.def_quality, self.def_container, self.def_acodec, self.def_aquality):
            w.currentIndexChanged.connect(self._defaults_changed)
        self.def_playlist.toggled.connect(self._defaults_changed)

        lay.addSpacing(8)
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

        # YouTube Premium：用目前的 Cookie 檢查登入的帳號，Cookie 過期時可以直接上傳新的
        lay.addSpacing(8)
        lay.addWidget(label("YouTube Premium", "sectionHeader"))
        prem = Card()
        prow = QWidget()
        pl = QVBoxLayout(prow)
        pl.setContentsMargins(14, 10, 14, 10)
        pl.setSpacing(4)
        top = QHBoxLayout()
        top.addWidget(label("帳號狀態"))
        top.addStretch()
        self.premium_status = label("", None, plain=True)
        top.addWidget(self.premium_status)
        pl.addLayout(top)
        self.premium_detail = label("", "hint", wrap=True, plain=True)
        pl.addWidget(self.premium_detail)
        pbtns = QHBoxLayout()
        pbtns.setContentsMargins(0, 6, 0, 0)
        self.premium_check = QPushButton("重新檢查")
        self.premium_check.clicked.connect(self.check_premium)
        self.premium_upload = QPushButton("更新 cookies.txt…")
        self.premium_upload.clicked.connect(self.update_cookies)
        pbtns.addWidget(self.premium_check)
        pbtns.addWidget(self.premium_upload)
        pbtns.addStretch()
        pl.addLayout(pbtns)
        prem.add(prow)
        lay.addWidget(prem)
        lay.addWidget(label("用瀏覽器匯出的 cookies.txt（或「新增下載 → 進階選項 → 網路」選的 Cookie 來源）"
                            "檢查登入的帳號是否有 Premium。Cookie 過期時重新匯出、按「更新 cookies.txt…」即可。",
                            "hint", wrap=True))
        self.show_premium(self.saved_premium())

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

        # 關於：版本與免責聲明
        lay.addSpacing(8)
        lay.addWidget(label("關於", "sectionHeader"))
        about = Card()
        self.app_version = label(app_version(), "subtitle", plain=True)
        about.add(form_row(TITLE, self.app_version))
        legal = QWidget()
        ll = QVBoxLayout(legal)
        ll.setContentsMargins(14, 10, 14, 10)
        ll.setSpacing(4)
        self.disclaimer_text = label(DISCLAIMER_SHORT.replace("\n", ""), "hint", wrap=True, plain=True)
        ll.addWidget(self.disclaimer_text)
        self.disclaimer_link = QPushButton("查看完整免責聲明")
        self.disclaimer_link.setObjectName("link")
        self.disclaimer_link.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(DISCLAIMER_URL)))
        lrow = QHBoxLayout()
        lrow.setContentsMargins(0, 4, 0, 0)
        lrow.addWidget(self.disclaimer_link)
        lrow.addStretch()
        ll.addLayout(lrow)
        about.add(legal)
        lay.addWidget(about)
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

    # ---------- 外觀 ----------
    def _appearance_changed(self, *_):
        save_ui_prefs(self.theme.value(), self.font_size.value())
        self.appearance_changed.emit()

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
        """外觀、下載預設值、進階選項全部恢復成剛安裝時的設定（不動儲存位置、cookies.txt 與下載的檔案）。"""
        box = QMessageBox(self.window())
        box.setIcon(QMessageBox.Question)
        box.setWindowTitle(TITLE)
        box.setText("要恢復所有預設值嗎？")
        box.setInformativeText("自動貼上、外觀、文字大小、下載預設值和進階選項會恢復成剛安裝時的設定。"
                               "儲存位置、cookies.txt 和已下載的檔案不受影響。")
        ok = box.addButton("恢復預設值", QMessageBox.AcceptRole)
        box.setDefaultButton(box.addButton("取消", QMessageBox.RejectRole))
        box.exec()
        if box.clickedButton() is not ok:
            return
        self.auto_paste.setChecked(True)  # toggled 會存進設定
        set_auto_paste(True)
        self.theme.set_value("system")
        self.font_size.set_value("medium")
        self._appearance_changed()
        self.show_defaults(dict(DOWNLOAD_DEFAULTS))
        self._defaults_changed()
        if self.advanced is not None:
            self.advanced.reset()
        self.toast("已恢復所有預設值")

    # ---------- YouTube Premium ----------
    @staticmethod
    def saved_premium() -> dict:
        try:
            return json.loads(settings_store().value("premium/status", "") or "{}")
        except ValueError:
            return {}

    def show_premium(self, s: dict):
        """顯示上次檢查的結果（App 重新開啟也看得到）。"""
        style = "warnText"
        if s.get("error"):
            text, detail, style = "無法檢查", s["error"], "errorText"
        elif not s:
            text, detail, style = "尚未檢查", "按「重新檢查」確認目前的 Cookie 是否登入、是否有 Premium。", "subtitle"
        elif s.get("expired"):
            text, detail = "Cookie 已過期", "請在瀏覽器重新登入 YouTube、重新匯出 cookies.txt 後按「更新 cookies.txt…」。"
        elif not s.get("logged_in"):
            text, detail = "未登入", "這組 Cookie 沒有登入 YouTube，請在登入狀態下重新匯出 cookies.txt。"
        elif s.get("premium"):
            text, detail, style = "Premium ✓", "已偵測到 YouTube Premium，可以下載 Premium 專屬的高位元率畫質。", "okText"
        else:
            text, detail, style = "已登入（非 Premium）", "已登入 YouTube，但這個帳號沒有 Premium。", "subtitle"
        if s.get("checked"):
            detail += f"　上次檢查：{s['checked']}"
        self.premium_status.setObjectName(style)
        self.premium_status.style().unpolish(self.premium_status)
        self.premium_status.style().polish(self.premium_status)
        self.premium_status.setText(text)
        self.premium_detail.setText(detail)

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
                self.show_premium({"error": "還沒有 Cookie：請按「更新 cookies.txt…」上傳從瀏覽器匯出的 cookies.txt。"})
                return
            # 已經上傳過 cookies.txt 但沒選來源（例如從舊版升級）：檢查時直接用它
            adv.cookie_source.setCurrentIndex(adv.cookie_source.findData("file"))
            net = adv.network()
        self.premium_check.setEnabled(False)
        self.premium_check.setText("檢查中…")

        def done():
            self.premium_check.setEnabled(True)
            self.premium_check.setText("重新檢查")

        def ok(r):
            done()
            self._save_premium({"logged_in": bool(r.get("logged_in")), "premium": bool(r.get("premium")),
                                "expired": bool(r.get("expired"))})
            if r.get("premium") and not adv.premium.isChecked():
                adv.premium.setChecked(True)  # 和網頁版一樣：偵測到 Premium 就優先選高位元率
                self.toast("已偵測到 YouTube Premium，已開啟「Premium 高位元率」")

        def err(msg):
            done()
            self._save_premium({"error": msg})

        # 檢查要實際向 YouTube 讀一部影片，通常幾秒、慢的時候一兩分鐘
        self.api.post("/api/auth/test", {"network": net}, ok, err, timeout_ms=180_000)

    def update_cookies(self):
        if self.advanced is None:
            return
        path, _ = QFileDialog.getOpenFileName(self, "選擇 cookies.txt", "", "Cookie 檔 (*.txt);;所有檔案 (*)")
        if path:
            self.advanced.upload_cookies(Path(path), done=self.check_premium)

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
