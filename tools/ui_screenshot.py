"""原生介面截圖（檢查外觀用，CI 會在 macOS / Windows 上跑）。

    python tools/ui_screenshot.py <輸出資料夾> [light|dark]

用範例影片資料填好「新增下載」頁，依序截「新增下載」「下載佇列」「設定」三頁。
macOS 另外用系統的 screencapture 截下真實視窗（含毛玻璃側邊欄、紅黃綠按鈕）；
Qt 的 grab() 只畫得出 Qt 自己的內容。
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("YTDL_ACCEPT_DISCLAIMER", "1")  # 自動截圖不能被第一次開啟的免責聲明對話框卡住

from PySide6.QtCore import QTimer
from PySide6.QtGui import QPixmap

import native_app as na

SAMPLE = {
    "type": "video", "title": "Big Buck Bunny 60fps 4K - Official Blender Foundation Short Film",
    "uploader": "Blender", "duration": 634, "heights": [2160, 1440, 1080, 720, 480, 360],
    "view_count": 12345678, "extractor": "Youtube", "webpage_url": "https://www.youtube.com/watch?v=aqz-KE-bpKQ",
    "thumbnail": None,
    "audio_tracks": [{"lang": "en", "label": "English", "original": True, "count": 3},
                     {"lang": "zh-TW", "label": "中文", "original": False, "count": 2}],
    "subtitles": [{"lang": "en", "name": "English"}], "auto_captions": [],
}


def main():
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    dark = (sys.argv[2] if len(sys.argv) > 2 else "light") == "dark"
    tag = "dark" if dark else "light"

    # 和 native_app.main() 相同的順序：mac_window_setup 要在 apply_theme 之前（它決定側邊欄要不要透明）
    app, chevron = na.create_app()
    url, busy = na.start_engine()
    win = na.MainWindow(na.Api(url, app), busy)
    win.move(80, 80)
    vibrancy = na.mac_window_setup(win)
    na.apply_theme(app, win, chevron, dark)
    win.show()
    win.raise_()
    win.activateWindow()
    win.start()
    print(f"vibrancy={vibrancy}", flush=True)

    def capture(name: str):
        win.grab().save(str(out / f"{tag}-{name}.png"))
        if na.IS_MAC:  # 真實視窗畫面（需要螢幕錄製權限；GitHub 的 macOS 機器可以）
            g = win.frameGeometry()
            subprocess.run(["screencapture", "-x", "-o", f"-R{g.x()},{g.y()},{g.width()},{g.height()}",
                            str(out / f"{tag}-{name}-window.png")], check=False)

    pages = ["download", "queue", "settings"]

    def step(i: int):
        if i == len(pages):
            app.quit()
            return
        win.go(i)
        QTimer.singleShot(1200, lambda: (capture(pages[i]), step(i + 1)))

    def fill():
        win.download.url.setText(SAMPLE["webpage_url"])
        win.download.on_info(SAMPLE)
        win.download.thumb.setPixmap(na.rounded(QPixmap(str(ROOT / "assets" / "icon.png")), 192, 108, 8))
        step(0)

    # 先確認介面真的連得到引擎（設定頁拿到下載資料夾）再截圖，並把結果印在 CI 紀錄裡：
    # 截到的空白畫面才分得出是「還沒載入」還是「連不上」
    import time
    import urllib.request
    try:
        with urllib.request.urlopen(url + "/api/settings", timeout=5) as r:
            print(f"urllib /api/settings: HTTP {r.status}", flush=True)
    except OSError as e:
        print(f"urllib /api/settings failed: {e}", flush=True)
    t0 = time.monotonic()
    result = {}
    win.api.get("/api/settings", lambda s: result.setdefault("ok", s.get("download_dir")),
                lambda m: result.setdefault("err", m))

    def wait_engine():
        if result or time.monotonic() - t0 > 20:
            print(f"Qt /api/settings after {time.monotonic() - t0:.1f}s: {result or 'no reply'}", flush=True)
            fill()
        else:
            QTimer.singleShot(200, wait_engine)

    QTimer.singleShot(500, wait_engine)
    code = app.exec()
    na.shutdown(app, win)
    os._exit(code)


if __name__ == "__main__":
    main()
