"""同一個使用者只開一個 App：第二次啟動時把命令列參數交給已經在執行的 App，然後自己結束。

用法（C1 接線，詳細見交接筆記）::

    instance = SingleInstance("yt-dl")
    if not instance.is_primary():          # 在 app_boot.boot() 之前判斷，不會啟動第二個引擎
        instance.send(sys.argv[1:])
        sys.exit(0)
    server = app_boot.boot()
    app, chevron = create_app()
    instance.listen()                      # QApplication 建立之後開始接收（is_primary 時已有 app 就會自動開始）
    instance.message_received.connect(on_args)

做法：
- 「誰是第一個」用 QLockFile 判斷。鎖檔記著持有者的 PID，持有的程序當掉後，下一個啟動的程序會發現該 PID
  已經不在而接手（Windows 上程序結束時檔案控制代碼會自動釋放）。這一步不需要 QApplication，所以能在
  `app_boot.boot()` 之前呼叫。
- 參數用 QLocalServer／QLocalSocket 傳（Windows 是 named pipe，macOS 是暫存資料夾裡的 Unix socket）。
  名稱含使用者帳號的雜湊，同一台電腦不同使用者互不干擾；socket 只開放給同一個使用者。
  第一個程序當掉留下的 Unix socket 檔，在接手時用 `QLocalServer.removeServer` 清掉。
- 傳送格式：JSON 字串陣列（ASCII，非 ASCII 字元用 \\u 跳脫）加換行，收到後回 `ok\\n`；`send()` 收到回覆才算成功。
  回覆後由傳送的一方關閉連線（Windows 的 named pipe 在伺服器端先斷線會丟掉還沒讀的回覆）。
"""
from __future__ import annotations

import getpass
import hashlib
import json
import os
import re
import sys

from PySide6.QtCore import (
    QCoreApplication,
    QDeadlineTimer,
    QDir,
    QElapsedTimer,
    QLockFile,
    QObject,
    QThread,
    QTimer,
    Signal,
)
from PySide6.QtNetwork import QLocalServer, QLocalSocket

MAX_MESSAGE_BYTES = 64 * 1024  # 一則訊息的上限（命令列參數用不到這麼多），超過就丟掉
IDLE_TIMEOUT_MS = 5000  # 連進來之後多久沒送完一則訊息就斷開
_ACK = b"ok\n"


def _user_id() -> str:
    """目前使用者帳號的識別字串（取得失敗時退回家目錄路徑）。"""
    try:
        name = getpass.getuser()
    except Exception:  # noqa: BLE001 - 某些環境沒有帳號名稱的環境變數，也查不到 pwd
        name = os.path.expanduser("~")
    return name or "user"


def server_name(key: str, user: str | None = None) -> str:
    """依 key 與使用者帳號產生 QLocalServer 的名稱。只用英數字，避免 named pipe／socket 路徑的特殊字元問題。"""
    # 長度要短：macOS 的 socket 放在 $TMPDIR（約 50 字元），Unix socket 路徑上限 104 位元組
    safe_key = re.sub(r"[^A-Za-z0-9_-]", "_", key)[:24] or "app"
    digest = hashlib.sha256((user if user is not None else _user_id()).encode("utf-8")).hexdigest()[:16]
    return f"{safe_key}-{digest}"


class SingleInstance(QObject):
    """單一實例判斷與參數轉交。`message_received(list[str])` 在第一個程序收到其他程序傳來的參數時發出。"""

    message_received = Signal(list)

    def __init__(self, key: str, parent: QObject | None = None, *, user: str | None = None):
        super().__init__(parent)
        self.name = server_name(key, user)
        self._lock = QLockFile(os.path.join(QDir.tempPath(), self.name + ".lock"))
        self._lock.setStaleLockTime(0)  # 不用「鎖檔多舊」判斷；只看持有的程序還在不在
        self._primary: bool | None = None
        self._server: QLocalServer | None = None
        self._buffers: dict[QLocalSocket, bytearray | None] = {}  # None：已回覆 ok，等對方關閉
        self.error = ""  # listen() 失敗時的原因（也會印到 stderr，打包版會進 engine.log）

    # ------------------------------------------------------------------ #
    #  判斷
    # ------------------------------------------------------------------ #
    def is_primary(self) -> bool:
        """這個程序是不是第一個。結果會記住，重複呼叫不會重新判斷。不需要先建立 QApplication。"""
        if self._primary is None:
            self._primary = bool(self._lock.tryLock(0))
            if self._primary and QCoreApplication.instance() is not None:
                self.listen()
        return self._primary

    def listen(self) -> bool:
        """開始接收其他程序傳來的參數（只有第一個程序會開始；重複呼叫沒關係）。要在 QApplication 建立之後呼叫。"""
        if not self.is_primary():
            return False
        if self._server is not None:
            return True
        server = QLocalServer(self)
        server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        # 拿到鎖就代表沒有其他活著的第一個程序：留下的同名 socket 一定是當掉的程序留下來的
        QLocalServer.removeServer(self.name)
        if not server.listen(self.name):
            self.error = server.errorString()
            print(f"單一實例：無法開始接收其他程序傳來的網址（{self.error}）", file=sys.stderr, flush=True)
            server.deleteLater()
            return False
        self.error = ""
        server.newConnection.connect(self._on_new_connection)
        self._server = server
        return True

    def close(self):
        """停止接收並放開鎖（App 結束前呼叫；沒呼叫的話程序結束時系統也會釋放）。"""
        if self._server is not None:
            self._server.close()
            self._server.deleteLater()
            self._server = None
        for sock in list(self._buffers):
            sock.abort()
            sock.deleteLater()
        self._buffers.clear()
        if self._primary:
            self._lock.unlock()
        self._primary = None

    # ------------------------------------------------------------------ #
    #  第二個程序：傳送
    # ------------------------------------------------------------------ #
    def send(self, args: list[str], timeout_ms: int = 5000) -> bool:
        """把參數交給第一個程序，收到確認才回傳 True。不需要事件迴圈，也不需要 QApplication。

        第一個程序可能還在啟動、還沒開始接收，所以連不上時會在 timeout_ms 內重試。
        """
        if self.is_primary():
            return False
        try:
            # ensure_ascii：macOS／Linux 的 argv 可能含無法編成 UTF-8 的字元（surrogateescape），轉成 \\u 跳脫才送得出去
            payload = json.dumps([str(a) for a in args]).encode("ascii") + b"\n"
        except (TypeError, ValueError):
            return False
        if len(payload) > MAX_MESSAGE_BYTES:
            return False
        timer = QElapsedTimer()
        timer.start()
        sock = QLocalSocket()
        try:
            # 只有「連不上」會重試；一旦送出內容就不再重送，避免對方收到卻沒回覆時重複交付同一個網址
            while True:
                remaining = timeout_ms - timer.elapsed()
                if remaining <= 0:
                    return False
                sock.connectToServer(self.name)
                if sock.waitForConnected(int(min(1000, remaining))):
                    break
                sock.abort()
                QThread.msleep(100)
            # 已經連上了：就算總時限快到，也留至少 1 秒把內容送完、等確認，不要白白放棄
            return self._exchange(sock, payload, max(1000, timeout_ms - timer.elapsed()))
        finally:
            sock.abort()

    @staticmethod
    def _exchange(sock: QLocalSocket, payload: bytes, remaining_ms: int) -> bool:
        deadline = QDeadlineTimer(max(1, int(remaining_ms)))
        sock.write(payload)
        while sock.bytesToWrite() > 0:
            if deadline.hasExpired() or not sock.waitForBytesWritten(int(max(1, deadline.remainingTime()))):
                return False
        reply = bytearray()
        while _ACK not in reply:
            if deadline.hasExpired() or not sock.waitForReadyRead(int(max(1, deadline.remainingTime()))):
                return False
            reply += bytes(sock.readAll())
        return True

    # ------------------------------------------------------------------ #
    #  第一個程序：接收
    # ------------------------------------------------------------------ #
    def _on_new_connection(self):
        while self._server is not None and self._server.hasPendingConnections():
            sock = self._server.nextPendingConnection()
            if sock is None:
                return
            self._buffers[sock] = bytearray()
            sock.readyRead.connect(lambda s=sock: self._on_ready_read(s))
            sock.disconnected.connect(lambda s=sock: self._drop(s))
            QTimer.singleShot(IDLE_TIMEOUT_MS, sock, lambda s=sock: self._drop(s))  # 連上卻一直不送完：斷開
            if sock.bytesAvailable():
                self._on_ready_read(sock)

    def _on_ready_read(self, sock: QLocalSocket):
        if sock not in self._buffers:
            return
        buf = self._buffers[sock]
        if buf is None:  # 已經處理完、在等對方關閉：之後送來的東西不理
            sock.readAll()
            return
        buf += bytes(sock.readAll())
        if len(buf) > MAX_MESSAGE_BYTES:
            self._drop(sock)
            return
        newline = buf.find(b"\n")
        if newline < 0:
            return
        args = _decode(bytes(buf[:newline]))
        if args is None:
            self._drop(sock)
            return
        # 回覆 ok 後不要自己斷線：Windows 的 named pipe 在伺服器端斷線時會丟掉對方還沒讀的資料，
        # 第二個程序就收不到確認。由對方讀完後關閉（disconnected → _drop），逾時也會清掉。
        self._buffers[sock] = None
        sock.write(_ACK)
        sock.flush()
        self.message_received.emit(args)

    def _drop(self, sock: QLocalSocket):
        if sock in self._buffers:
            del self._buffers[sock]
            sock.abort()
            sock.deleteLater()


def _decode(data: bytes) -> list[str] | None:
    """解析收到的訊息；格式不對（不是字串陣列）就回傳 None。"""
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        return None
    return value
