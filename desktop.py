"""YT 下載器桌面 App：在原生視窗裡顯示介面，同時在背景執行下載引擎。

打包版（Windows 安裝程式 / macOS .app）的進入點；開發時也可以直接 `python desktop.py`。
- 沒有主控台視窗：輸出寫到使用者資料夾的 engine.log
- 先顯示啟動畫面，引擎就緒後載入介面
- 下載進行中關閉視窗會先確認（工作之後可以「繼續下載」）
- 已經有引擎在執行（重複開啟）時，只開視窗連到它
- 加上 --server 參數則只執行引擎、不開視窗
"""
from __future__ import annotations

import base64
import os
import sys
import threading
import time
import urllib.request
from pathlib import Path

TITLE = "YT 下載器"
BG = "#060010"
LOG_MAX = 5 * 1024 * 1024


# 視窗程式（打包時 --windowed）沒有主控台，sys.stdout / stderr 是 None，print 或 Flask 的紀錄會讓程式當掉
NO_CONSOLE = sys.stdout is None or sys.stderr is None


def _redirect_output(log_dir: Path | None):
    """沒有主控台時：資料夾確定前先丟掉輸出，之後寫到 engine.log。"""
    if not NO_CONSOLE:
        return
    if log_dir is None:
        sink = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115
    else:
        log = log_dir / "engine.log"
        if log.exists() and log.stat().st_size > LOG_MAX:
            log.replace(log.with_suffix(".log.old"))
        sink = open(log, "a", encoding="utf-8", buffering=1)  # noqa: SIM115 — 整個程式期間都要開著
    sys.stdout = sys.stderr = sink


def _icon_data_uri(bundle: Path) -> str:
    try:
        return "data:image/png;base64," + base64.b64encode((bundle / "assets" / "icon-128.png").read_bytes()).decode()
    except OSError:
        return ""


def page(icon: str, title: str, message: str, busy: bool = True) -> str:
    """啟動 / 錯誤畫面，配色與網頁一致。"""
    bar = '<div class="bar"><i></i></div>' if busy else ""
    img = f'<img src="{icon}" alt="">' if icon else ""
    return f"""<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8"><style>
html,body{{margin:0;height:100%;background:{BG};color:#f1eefc;font:15px/1.6 -apple-system,"Segoe UI","Microsoft JhengHei",
"PingFang TC",sans-serif;-webkit-user-select:none;user-select:none;overflow:hidden}}
body{{display:flex;align-items:center;justify-content:center;
background:radial-gradient(60% 50% at 50% 38%,rgba(139,92,246,.22),transparent 70%),{BG}}}
.box{{text-align:center;padding:24px;max-width:460px}}
img{{width:96px;height:96px;filter:drop-shadow(0 18px 40px rgba(82,39,255,.55));animation:float 2.4s ease-in-out infinite}}
h1{{margin:22px 0 6px;font-size:24px;font-weight:700;letter-spacing:.02em}}
p{{margin:0;color:#9a93b0;white-space:pre-line}}
.bar{{width:180px;height:4px;margin:26px auto 0;border-radius:4px;background:rgba(255,255,255,.08);overflow:hidden}}
.bar i{{display:block;width:40%;height:100%;border-radius:4px;background:linear-gradient(90deg,#5227ff,#8b5cf6,#ff6bd5);
animation:slide 1.2s ease-in-out infinite}}
@keyframes slide{{0%{{transform:translateX(-100%)}}100%{{transform:translateX(250%)}}}}
@keyframes float{{0%,100%{{transform:translateY(0)}}50%{{transform:translateY(-6px)}}}}
</style></head><body><div class="box">{img}<h1>{title}</h1><p>{message}</p>{bar}</div></body></html>"""


def wait_until_up(url: str, timeout: float) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            with urllib.request.urlopen(f"{url}/api/meta", timeout=2):
                return True
        except OSError:
            time.sleep(0.25)
    return False


def main():
    _redirect_output(None)
    import server  # 匯入時會決定資料夾位置、把內建的 ffmpeg / deno 加進 PATH
    _redirect_output(server.ROOT)
    if "--server" in sys.argv:  # 只跑引擎不開視窗（自動化測試、進階使用者用瀏覽器開介面）
        server.main()
        return
    import webview

    url = f"http://127.0.0.1:{server.PORT}"
    icon = _icon_data_uri(server.BUNDLE)
    attached = server._port_in_use(server.HOST, server.PORT)  # 已有引擎在跑：只開視窗
    if not attached:
        server.load_jobs()
        threading.Thread(target=server.app.run, daemon=True, kwargs={
            "host": server.HOST, "port": server.PORT, "threaded": True, "debug": False, "use_reloader": False,
        }).start()
        print(f"{TITLE} 引擎啟動於 {url}（yt-dlp {server.yt_dlp.version.__version__}）", flush=True)

    window = webview.create_window(TITLE, html=page(icon, TITLE, "正在啟動下載引擎…"),
                                   width=1240, height=880, min_size=(420, 600), background_color=BG)

    def on_closing():
        if attached or not server._busy():
            return True
        return window.create_confirmation_dialog(
            "要關閉 YT 下載器嗎？",
            "還有下載正在進行。關閉後工作會暫停，下次開啟時按「繼續下載」就能接著下載。")

    window.events.closing += on_closing

    def boot():
        if wait_until_up(url, 30):
            window.load_url(url)
        else:
            window.load_html(page(icon, "無法啟動下載引擎",
                                  f"連接埠 {server.PORT} 可能被其他程式佔用。\n"
                                  f"請關閉佔用的程式後重新開啟，或查看紀錄檔：\n{server.ROOT / 'engine.log'}",
                                  busy=False))

    webview.settings["ALLOW_DOWNLOADS"] = True  # 「下載」按鈕存檔、ZIP 打包
    try:
        # Windows 指定 Edge WebView2；不指定時沒裝 WebView2 會退回 IE 引擎，介面會壞掉
        webview.start(boot, private_mode=False, storage_path=str(server.ROOT / "webview"),
                      gui="edgechromium" if os.name == "nt" else None)
    except Exception as e:  # noqa: BLE001 — 沒有可用的網頁元件：改用瀏覽器
        print(f"無法開啟 App 視窗：{e}", flush=True)
        if not attached and not wait_until_up(url, 30):
            os._exit(1)
        import webbrowser
        webbrowser.open(url)
        _message(TITLE, "這台電腦缺少 Microsoft Edge WebView2，已改用瀏覽器開啟下載器。\n"
                        "使用期間請不要按「確定」；按下「確定」就會關閉下載引擎。\n\n"
                        "安裝 WebView2 後即可使用 App 視窗：https://go.microsoft.com/fwlink/p/?LinkId=2124703")
    os._exit(0)  # 結束背景的 Flask 與下載執行緒


def _message(title: str, text: str):
    """沒有網頁元件時用系統對話框顯示訊息（會停在這裡直到使用者按確定）。"""
    if os.name == "nt":
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, title, 0x40)
    else:
        print(text, flush=True)
        threading.Event().wait()


if __name__ == "__main__":
    main()
