"""系統匣（macOS 是選單列）圖示、選單、進度提示與系統通知。

只透過訊號和外界溝通，不呼叫引擎 API、不碰主視窗；接線由 C1 在 native_app.py 做（見交接筆記）::

    tray = TrayController(app)
    tray.show_requested.connect(win.bring_to_front)
    tray.pause_all_requested.connect(win.queue.pause_all)
    tray.resume_all_requested.connect(win.queue.resume_all)
    tray.quit_requested.connect(win.request_quit)
    tray.notification_clicked.connect(win.show_job)
    tray.set_summary(TrayController.active_text(2), 45)    # 提示文字「2 個下載中 · 45%」
    tray.notify("下載完成", "影片標題", job_id)
"""
from __future__ import annotations

import sys
from pathlib import Path

import shiboken6
from PySide6.QtCore import QCoreApplication, QObject, Signal
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

_tr = QCoreApplication.translate  # 名稱固定是 _tr（docs/I18N.md 2.2）

IS_MAC = sys.platform == "darwin"
BUNDLE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))  # 打包版的資源在 _MEIPASS
TOOLTIP_LIMIT = 120  # Windows 系統匣提示最多 127 個字元，超過會被系統截掉
NOTIFY_MS = 8000


def default_icon() -> QIcon:
    """App 圖示。macOS 選單列比較適合單色的 template 圖示，C1 有準備的話可以從建構參數傳進來。"""
    for name in ("icon-128.png", "icon.png"):
        path = BUNDLE / "assets" / name
        if path.exists():
            return QIcon(str(path))
    return QIcon()


class TrayController(QObject):
    """系統匣圖示與選單。

    訊號：
    - `show_requested`：選單「顯示視窗」，或 Windows 上點一下／點兩下圖示
    - `pause_all_requested`、`resume_all_requested`：選單「暫停全部」「繼續全部」
    - `quit_requested`：選單「結束」（要不要先詢問由接收的一方決定）
    - `notification_clicked(str)`：點了 `notify()` 顯示的通知，參數是該通知的 job_id
    """

    show_requested = Signal()
    pause_all_requested = Signal()
    resume_all_requested = Signal()
    quit_requested = Signal()
    notification_clicked = Signal(str)

    def __init__(self, parent: QObject | None = None, icon: QIcon | None = None, *, visible: bool = True):
        super().__init__(parent)
        self._summary_text = ""
        self._progress: int | None = None
        self._last_job_id = ""

        self.tray = QSystemTrayIcon(icon if icon is not None and not icon.isNull() else default_icon(), self)
        self.menu = QMenu()  # QMenu 只能掛在 QWidget 底下；自己保留參照，dispose() 時刪掉
        self.show_action = QAction(self.tr("顯示視窗"), self.menu)
        self.progress_action = QAction(self.menu)
        self.progress_action.setEnabled(False)  # 只顯示進度，不能點
        self.pause_action = QAction(self.tr("暫停全部"), self.menu)
        self.resume_action = QAction(self.tr("繼續全部"), self.menu)
        self.quit_action = QAction(self.tr("結束"), self.menu)
        # macOS：「結束」放在應用程式選單的慣例位置會被移走；系統匣選單裡要留著
        self.quit_action.setMenuRole(QAction.MenuRole.NoRole)

        self.menu.addAction(self.show_action)
        self.menu.addSeparator()
        self.menu.addAction(self.progress_action)
        self.menu.addAction(self.pause_action)
        self.menu.addAction(self.resume_action)
        self.menu.addSeparator()
        self.menu.addAction(self.quit_action)
        self.tray.setContextMenu(self.menu)

        self.show_action.triggered.connect(self.show_requested)
        self.pause_action.triggered.connect(self.pause_all_requested)
        self.resume_action.triggered.connect(self.resume_all_requested)
        self.quit_action.triggered.connect(self.quit_requested)
        self.tray.activated.connect(self._on_activated)
        self.tray.messageClicked.connect(self._on_message_clicked)

        self._refresh()
        if visible:
            self.set_visible(True)

    # ------------------------------------------------------------------ #
    #  狀態
    # ------------------------------------------------------------------ #
    @staticmethod
    def is_available() -> bool:
        """這台電腦有沒有系統匣（某些 Linux 桌面、測試用的 offscreen 平台沒有）。"""
        return QSystemTrayIcon.isSystemTrayAvailable()

    def set_visible(self, visible: bool):
        """顯示或隱藏系統匣圖示（沒有系統匣時不做事）。"""
        if visible and not self.is_available():
            return
        self.tray.setVisible(visible)

    def is_visible(self) -> bool:
        return self.tray.isVisible()

    def set_summary(self, text: str, progress: float | None = None):
        """更新進度提示：`text` 例如 `TrayController.active_text(2)`（「2 個下載中」），
        `progress` 是整體進度 0–100（None 表示不顯示百分比）。text 空字串表示沒有進行中的下載。"""
        self._summary_text = (text or "").strip()
        if progress is None or self._summary_text == "":
            self._progress = None
        else:
            try:
                self._progress = max(0, min(100, round(float(progress))))
            except (TypeError, ValueError, OverflowError):
                self._progress = None
        self._refresh()

    def summary(self) -> str:
        """目前顯示在提示與選單裡的進度文字。"""
        if not self._summary_text:
            return self.tr("沒有進行中的下載")
        if self._progress is None:
            return self._summary_text
        return self.tr("{summary} · {percent}%").format(summary=self._summary_text, percent=self._progress)

    @staticmethod
    def active_text(count: int) -> str:
        """「N 個下載中」，給 set_summary 用（數量用 %n，英文會分單複數）。"""
        return _tr("TrayController", "%n 個下載中", None, int(count))

    def _refresh(self):
        line = self.summary()
        self.progress_action.setText(line)
        tip = self.tr("YT 下載器") + "\n" + line
        if len(tip) > TOOLTIP_LIMIT:
            tip = tip[:TOOLTIP_LIMIT - 1] + "…"
        self.tray.setToolTip(tip)

    # ------------------------------------------------------------------ #
    #  通知
    # ------------------------------------------------------------------ #
    def notify(self, title: str, body: str, job_id: str = "") -> bool:
        """顯示系統通知；使用者點通知時發出 `notification_clicked(job_id)`。

        系統只會記得最後一則通知，所以點的是較早的通知時也會回傳最後一則的 job_id。
        沒有系統匣或系統不支援通知時回傳 False（呼叫端可以改用 App 內的提示）。
        """
        if not self.is_available() or not QSystemTrayIcon.supportsMessages():
            return False
        if not self.tray.isVisible():
            self.tray.setVisible(True)  # Windows 要圖示顯示中才能跳通知
        self._last_job_id = str(job_id or "")
        self.tray.showMessage(title, body, QSystemTrayIcon.MessageIcon.Information, NOTIFY_MS)
        return True

    def _on_message_clicked(self):
        self.notification_clicked.emit(self._last_job_id)

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason):
        # Windows／Linux 點一下就喚醒（點兩下時系統會先送 Trigger 再送 DoubleClick，只認 Trigger 才不會喚醒兩次）；
        # macOS 點選單列圖示是打開選單，只有點兩下才喚醒
        wanted = QSystemTrayIcon.ActivationReason.DoubleClick if IS_MAC else QSystemTrayIcon.ActivationReason.Trigger
        if reason == wanted:
            self.show_requested.emit()

    def dispose(self):
        """App 結束前呼叫：移除系統匣圖示（Windows 不移除的話圖示會殘留到滑鼠移過去才消失），並馬上刪掉選單。

        不用 deleteLater：App 結束時事件迴圈已經停了，排程的刪除不會執行，沒有父物件的 QMenu 會活得比
        QApplication 久（Windows 上可能在結束時當掉）。重複呼叫沒關係。
        """
        if shiboken6.isValid(self.tray):
            self.tray.hide()
            self.tray.setContextMenu(None)
        if shiboken6.isValid(self.menu):
            shiboken6.delete(self.menu)
