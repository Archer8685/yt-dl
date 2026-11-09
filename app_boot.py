"""桌面 App（native_app.py）的啟動流程。

    import app_boot
    server = app_boot.boot()                   # 處理命令列參數、匯入引擎；--server / --check-ytdlp 會在這裡結束
    url, busy = app_boot.start_engine(server)  # 在背景執行緒啟動引擎（已有程式在用連接埠就連過去）
    ...建立 QApplication 與視窗...
    app_boot.install_smoke_test(app)           # --smoke-test：視窗出現後自動結束（CI 用）

命令列參數：
  --check-ytdlp <資料夾>  確認自動更新下載的新版 yt-dlp 能載入（server.py 呼叫，寫入 <資料夾>/OK）
  --server               只跑引擎不開視窗（CI 啟動測試、進階使用者用瀏覽器開介面）
  --smoke-test           開啟視窗幾秒後自動結束，結束碼 0 表示視窗有正常顯示（CI 的 GUI 煙霧測試）
"""
from __future__ import annotations

import logging
import os
import sys
import threading
import time
import traceback
from pathlib import Path

LOG_MAX = 5 * 1024 * 1024
SMOKE_SECONDS = 4

# 視窗程式（打包時 --windowed）沒有主控台，sys.stdout / stderr 是 None，print 或 Flask 的紀錄會讓程式當掉
NO_CONSOLE = sys.stdout is None or sys.stderr is None


def safe_streams():
    """主控台編碼不支援的字元（中文訊息、影片標題的 emoji）印出時用 ? 取代，不要讓程式當掉。

    例如 CI 的 Windows 主控台是 cp1252，打包版又不吃 PYTHONUTF8 等環境變數。
    """
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(errors="replace")
            except (ValueError, OSError):
                pass


def redirect_output(log_dir: Path | None):
    """沒有主控台時：資料夾確定前先丟掉輸出，之後寫到 <log_dir>/engine.log（超過 5 MB 換新檔）。"""
    if not NO_CONSOLE:
        return
    if log_dir is None:
        sink = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115
    else:
        log = log_dir / "engine.log"
        try:
            if log.exists() and log.stat().st_size > LOG_MAX:
                log.replace(log.with_suffix(".log.old"))
        except OSError:  # Windows：另一個執行中的 App 正開著紀錄檔，這次先不換新檔
            pass
        sink = open(log, "a", encoding="utf-8", buffering=1)  # noqa: SIM115 — 整個程式期間都要開著
    old = sys.stdout
    sys.stdout = sys.stderr = sink
    if old is not None and old not in (sys.__stdout__, sys.__stderr__):
        old.close()


def handle_check_ytdlp(argv: list[str]):
    """--check-ytdlp <資料夾>：在匯入引擎（和內建的 yt-dlp）之前處理，結果用結束碼回報。

    新版載入失敗一定要回報結束碼 1，而不是讓例外跑出去：打包的視窗程式遇到未處理的例外，
    PyInstaller 會跳出錯誤對話框等使用者按確定，背景的自動更新就卡在那裡。
    """
    if len(argv) == 3 and argv[1] == "--check-ytdlp":
        try:
            import ytdlp_update
            code = ytdlp_update.check(argv[2])
        except BaseException:  # noqa: BLE001 — 任何失敗都只代表「這一版不能用」
            if sys.stderr is not None:
                traceback.print_exc()
            code = 1
        os._exit(code)


def wait_port_free(server, timeout: float = 15) -> bool:
    """更新後重新啟動（YTDL_JUST_UPDATED=1）時，等舊程序釋放連接埠（最多 timeout 秒）。

    回傳 False 表示時間到了連接埠仍被佔用；不是更新後重啟就不等、直接回傳 True。
    """
    if os.environ.get("YTDL_JUST_UPDATED") != "1":
        return True
    end = time.monotonic() + timeout
    while server._port_in_use(server.HOST, server.PORT):
        if time.monotonic() >= end:
            return False
        time.sleep(0.2)
    return True


def quiet_access_log():
    """engine.log 不記每一次 API 存取：App 每 0.7 秒輪詢 /api/jobs，原本 80% 的紀錄都是這種，真正的錯誤反而被洗掉。
    werkzeug 的警告與錯誤（例如連接埠被佔用）照樣會寫進去。"""
    logging.getLogger("werkzeug").setLevel(logging.WARNING)


def boot(argv: list[str] | None = None):
    """App 啟動的共用前置步驟，回傳 server 模組；--check-ytdlp 與 --server 不會回傳。"""
    argv = sys.argv if argv is None else argv
    handle_check_ytdlp(argv)
    safe_streams()
    redirect_output(None)
    import server  # 匯入時會決定資料夾位置、把內建的 ffmpeg / deno 加進 PATH
    redirect_output(server.ROOT)
    wait_port_free(server)
    quiet_access_log()
    if "--server" in argv:
        server.main()
        sys.exit(0)
    return server


def start_engine(server):
    """在背景執行緒啟動下載引擎，回傳 (網址, 是否有工作進行中的函式)。

    連接埠已經有程式在用時（通常是另一個執行中的 App）直接連過去；那時關閉這個視窗不會中斷對方的下載，
    所以「是否有工作進行中」一律回答否。對方是不是引擎由介面啟動後檢查（MainWindow.check_engine）。
    """
    url = f"http://127.0.0.1:{server.PORT}"
    if server._port_in_use(server.HOST, server.PORT):
        print(f"連接埠 {server.PORT} 已有程式在使用，介面改連到它", flush=True)
        return url, lambda: False
    quiet_access_log()
    server.load_jobs()
    server.start_background_updates()
    threading.Thread(target=server.app.run, daemon=True, kwargs={
        "host": server.HOST, "port": server.PORT, "threaded": True, "debug": False, "use_reloader": False,
    }).start()
    print(f"YT 下載器引擎啟動於 {url}（yt-dlp {server.yt_dlp.version.__version__}"
          f"{'，自動更新版' if server.YTDLP_OVERLAY else ''}）", flush=True)  # 只寫進紀錄，不翻譯
    return url, server._busy


def smoke_test_requested(argv: list[str] | None = None) -> bool:
    return "--smoke-test" in (sys.argv if argv is None else argv)


def install_smoke_test(app, seconds: float = SMOKE_SECONDS) -> bool:
    """--smoke-test：幾秒後檢查有沒有顯示中的視窗並結束事件迴圈（有 → 結束碼 0，沒有 → 3）。

    搭配 QT_QPA_PLATFORM=offscreen 可以在沒有螢幕的 CI 上跑。沒有指定 --smoke-test 時什麼都不做。
    """
    if not smoke_test_requested():
        return False
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    def finish():
        shown = []
        try:
            shown = [w for w in QApplication.topLevelWidgets() if w.isVisible()]
            # 只印 ASCII：CI 會從這行判斷結果，不能因為主控台編碼印不出中文而失敗
            print(f"smoke test: {len(shown)} window(s) shown", flush=True)
        finally:
            # 只結束事件迴圈：讓 App 走平常關閉的流程（app.exec() 回傳 → shutdown() 釋放 Qt 物件 → 結束程序），
            # 這段收尾也一起被測到
            app.exit(0 if shown else 3)

    QTimer.singleShot(int(seconds * 1000), finish)
    return True
