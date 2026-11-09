"""「下載佇列」頁：定時向引擎查詢工作清單，每個工作一列（JobRow），可取消、續傳、刪除。"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QHBoxLayout, QMessageBox, QProgressBar, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from native_common import ACTIVE, FILE_MANAGER, STATUS_TEXT, TITLE, Api, Card, fmt_bytes, fmt_eta, label, page_layout


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
