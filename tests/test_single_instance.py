"""single_instance：同一個使用者只開一個 App，第二次啟動把參數交給第一個。用真的兩個程序測。"""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import uuid
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QElapsedTimer
from PySide6.QtWidgets import QApplication

import single_instance
from single_instance import SingleInstance, server_name

ROOT = Path(__file__).resolve().parent.parent

# 子程序：不建立 QApplication（模擬 app_boot.boot() 之前就判斷），印出判斷結果並照指令動作
CHILD = textwrap.dedent("""
    import os, sys
    sys.path.insert(0, sys.argv[1])
    from single_instance import SingleInstance
    inst = SingleInstance(sys.argv[2])
    primary = inst.is_primary()
    print("primary" if primary else "secondary", flush=True)
    mode = sys.argv[3]
    if mode == "send_surrogate" and not primary:  # macOS／Linux 的 argv 可能含 surrogateescape 字元
        print("sent" if inst.send(["bad\\udcff", *sys.argv[4:]]) else "failed", flush=True)
    elif mode == "send" and not primary:
        print("sent" if inst.send(sys.argv[4:], timeout_ms=int(os.environ.get("SEND_TIMEOUT", "5000"))) else "failed",
              flush=True)
    elif mode == "crash" and primary:
        os._exit(3)  # 模擬當掉：不放開鎖、不關 server
    elif mode == "hold" and primary:
        sys.stdin.readline()  # 等測試叫它結束
    elif mode == "late_listen" and primary:
        # C1 的實際流程：boot() 之前判斷 → 建立 QApplication → listen() → 收訊息
        import json, time
        from PySide6.QtCore import QCoreApplication, QTimer
        time.sleep(float(os.environ.get("LATE_DELAY", "0")))  # 模擬 boot() 花的時間
        app = QCoreApplication([])
        print("listening" if inst.listen() else "listen-failed", flush=True)
        inst.message_received.connect(lambda args: (print(json.dumps(args), flush=True), app.quit()))
        QTimer.singleShot(15000, app.quit)
        app.exec()
""")


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def key():
    return "yt-dl-test-" + uuid.uuid4().hex[:8]


def run_child(key: str, mode: str, *args: str, env=None, **kw) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-c", CHILD, str(ROOT), key, mode, *args],
        stdout=subprocess.PIPE, stdin=subprocess.PIPE, text=True, encoding="utf-8",
        env={**os.environ, **(env or {})}, **kw,
    )


def pump_until(cond, ms=8000) -> bool:
    t = QElapsedTimer()
    t.start()
    while not cond() and t.elapsed() < ms:
        QCoreApplication.processEvents()
    return cond()


def communicate_pumping(proc: subprocess.Popen, ms=15000) -> str:
    """等子程序結束，等的同時跑事件迴圈（第一個程序要靠事件迴圈收訊息）。"""
    pump_until(lambda: proc.poll() is not None, ms)
    if proc.poll() is None:
        proc.kill()
    out, _ = proc.communicate(timeout=10)
    return out


def test_server_name_differs_per_user_and_is_safe():
    a = server_name("yt-dl", "alice")
    assert a == server_name("yt-dl", "alice")
    assert a != server_name("yt-dl", "bob")
    assert a != server_name("other", "alice")
    weird = server_name("../x y\\z", "alice")
    assert all(c.isalnum() or c in "-_" for c in weird)
    assert "alice" not in a  # 不把帳號名稱直接放進名稱


def test_first_is_primary_second_hands_off_args(app, key):
    first = SingleInstance(key)
    received = []
    first.message_received.connect(received.append)
    try:
        assert first.is_primary() is True
        assert first.is_primary() is True  # 重複呼叫結果不變
        url = "ytdl://add?url=https%3A%2F%2Fwww.youtube.com%2Fwatch%3Fv%3Ddq_ab1234AB"
        out = communicate_pumping(run_child(key, "send", url, "中文參數"))
        assert out.split() == ["secondary", "sent"]
        assert pump_until(lambda: received)
        assert received == [[url, "中文參數"]]
    finally:
        first.close()


def test_primary_decided_before_qapplication_then_listen(key):
    """C1 的流程：第一個程序在 QApplication 建立前判斷，之後才 listen；第二個程序送的參數要收得到。"""
    import json

    holder = run_child(key, "late_listen")
    try:
        assert holder.stdout.readline().strip() == "primary"
        assert holder.stdout.readline().strip() == "listening"
        second = SingleInstance(key)
        assert second.is_primary() is False
        assert second.send(["https://example.com/v", "影片"]) is True
        assert json.loads(holder.stdout.readline()) == ["https://example.com/v", "影片"]
    finally:
        holder.wait(timeout=15)


def test_send_waits_for_primary_that_is_still_starting(key):
    """第一個程序拿到鎖但還沒 listen（還在 boot）：第二個程序在時限內重試連線，對方開始接收後送達。"""
    import json

    holder = run_child(key, "late_listen", env={"LATE_DELAY": "1"})
    try:
        assert holder.stdout.readline().strip() == "primary"
        second = SingleInstance(key)
        assert second.send(["x"], timeout_ms=8000) is True
        assert holder.stdout.readline().strip() == "listening"
        assert json.loads(holder.stdout.readline()) == ["x"]
    finally:
        holder.wait(timeout=15)


def test_primary_without_listen_send_fails_in_time(key):
    """子程序先在沒有 QApplication 的情況下拿到第一個，但一直沒有 listen：第二個程序要在時限內回報失敗。"""
    holder = run_child(key, "hold")
    try:
        assert holder.stdout.readline().strip() == "primary"
        second = SingleInstance(key)
        assert second.is_primary() is False
        # 子程序沒有建立 QApplication 也沒有 listen，送不出去要在時限內回報失敗，不能卡住
        t = QElapsedTimer()
        t.start()
        assert second.send(["x"], timeout_ms=600) is False
        assert t.elapsed() < 3000
    finally:
        holder.stdin.write("\n")
        holder.stdin.flush()
        holder.wait(timeout=10)


def test_takes_over_after_primary_crash(app, key):
    crashed = run_child(key, "crash")
    out, _ = crashed.communicate(timeout=15)
    assert out.split() == ["primary"]
    assert crashed.returncode == 3
    # 當掉的程序留下鎖檔（以及 macOS／Linux 上的 socket 檔），下一個要能接手並正常接收
    lock = Path(single_instance.QDir.tempPath()) / (server_name(key) + ".lock")
    assert lock.exists()
    taker = SingleInstance(key)
    received = []
    taker.message_received.connect(received.append)
    try:
        assert taker.is_primary() is True
        out = communicate_pumping(run_child(key, "send", "https://example.com/a"))
        assert out.split() == ["secondary", "sent"]
        assert pump_until(lambda: received == [["https://example.com/a"]])
    finally:
        taker.close()


def test_close_releases_for_next_instance(app, key):
    first = SingleInstance(key)
    assert first.is_primary()
    first.close()
    second = SingleInstance(key)
    try:
        assert second.is_primary() is True
    finally:
        second.close()


def test_primary_cannot_send(app, key):
    first = SingleInstance(key)
    try:
        assert first.is_primary()
        assert first.send(["x"]) is False
    finally:
        first.close()


def test_different_user_names_do_not_interfere(app, key):
    alice = SingleInstance(key, user="alice")
    bob = SingleInstance(key, user="bob")
    try:
        assert alice.is_primary() and bob.is_primary()
    finally:
        alice.close()
        bob.close()


@pytest.mark.parametrize("payload", [
    b"not json\n",
    b'{"a": 1}\n',
    b'["ok", 3]\n',
    b"\xff\xfe\n",
])
def test_malformed_messages_are_ignored(app, key, payload):
    """別的程式連進來亂送資料：不發訊號、不回 ok、App 不受影響。"""
    from PySide6.QtNetwork import QLocalSocket

    first = SingleInstance(key)
    received = []
    first.message_received.connect(received.append)
    try:
        assert first.is_primary()
        sock = QLocalSocket()
        sock.connectToServer(first.name)
        assert pump_until(lambda: sock.state() == QLocalSocket.LocalSocketState.ConnectedState, 3000)
        sock.write(payload)
        sock.flush()
        pump_until(lambda: sock.state() == QLocalSocket.LocalSocketState.UnconnectedState, 3000)
        assert bytes(sock.readAll()) == b""
        assert received == []
        sock.abort()
    finally:
        first.close()


def test_oversized_message_is_dropped(app, key):
    from PySide6.QtNetwork import QLocalSocket

    first = SingleInstance(key)
    received = []
    first.message_received.connect(received.append)
    try:
        assert first.is_primary()
        sock = QLocalSocket()
        sock.connectToServer(first.name)
        assert pump_until(lambda: sock.state() == QLocalSocket.LocalSocketState.ConnectedState, 3000)
        sock.write(b"[" + b'"a",' * (single_instance.MAX_MESSAGE_BYTES // 4 + 10))
        sock.flush()
        assert pump_until(lambda: sock.state() == QLocalSocket.LocalSocketState.UnconnectedState, 5000)
        assert received == []
        assert first._buffers == {}
    finally:
        first.close()


def test_server_name_is_short_enough_for_macos_socket_path():
    # macOS 的 $TMPDIR 約 50 字元，Unix socket 路徑上限 104 位元組
    assert len(server_name("k" * 200, "someone")) <= 41


def test_send_handles_undecodable_argv(app, key):
    """macOS／Linux 的 argv 可能含 surrogateescape 字元：要能送出，不能整批丟掉。"""
    first = SingleInstance(key)
    received = []
    first.message_received.connect(received.append)
    try:
        assert first.is_primary()
        out = communicate_pumping(run_child(key, "send_surrogate", "https://example.com/b"))
        assert out.split() == ["secondary", "sent"]
        assert pump_until(lambda: received)
        # 無法解碼的字元經過 Qt 訊號（QString）會被拿掉；重點是同一批的其他參數照樣送到
        assert len(received) == 1 and received[0][0].startswith("bad")
        assert received[0][1] == "https://example.com/b"
    finally:
        first.close()


def test_payload_is_not_resent_when_ack_is_missing(app, key, monkeypatch):
    """對方收到了卻沒回 ok（或回覆遺失）：不能重送，否則同一個網址會被交付兩次。"""
    from PySide6.QtNetwork import QLocalServer

    server = QLocalServer()
    QLocalServer.removeServer(server_name(key))
    assert server.listen(server_name(key))
    holder = run_child(key, "hold")  # 拿著鎖，讓測試程序當第二個
    conns = []

    def on_conn():  # 收下連線但永遠不回 ok
        while server.hasPendingConnections():
            conns.append(server.nextPendingConnection())

    server.newConnection.connect(on_conn)
    try:
        assert holder.stdout.readline().strip() == "primary"
        out = communicate_pumping(run_child(key, "send", "x", env={"SEND_TIMEOUT": "2000"}))
        assert out.split() == ["secondary", "failed"]
        assert len(conns) == 1  # 送出後就不再重新連線重送
    finally:
        server.close()
        holder.stdin.write("\n")
        holder.stdin.flush()
        holder.wait(timeout=10)


def test_idle_connection_is_dropped(app, key, monkeypatch):
    from PySide6.QtNetwork import QLocalSocket

    monkeypatch.setattr(single_instance, "IDLE_TIMEOUT_MS", 200)
    first = SingleInstance(key)
    try:
        assert first.is_primary()
        sock = QLocalSocket()
        sock.connectToServer(first.name)
        assert pump_until(lambda: len(first._buffers) == 1, 3000)
        sock.write(b'["no newline"')
        sock.flush()
        assert pump_until(lambda: first._buffers == {}, 3000)
        assert pump_until(lambda: sock.state() == QLocalSocket.LocalSocketState.UnconnectedState, 3000)
    finally:
        first.close()


def test_send_rejects_oversized_args(app, key):
    holder = run_child(key, "hold")
    try:
        assert holder.stdout.readline().strip() == "primary"
        second = SingleInstance(key)
        assert second.send(["x" * (single_instance.MAX_MESSAGE_BYTES + 1)], timeout_ms=300) is False
    finally:
        holder.stdin.write("\n")
        holder.stdin.flush()
        holder.wait(timeout=10)
