"""產生 GitHub Release 的說明：CHANGELOG.md 裡這一版的「更新內容」＋安裝說明。

    python tools/release_notes.py 1.1.0 > notes.md

CHANGELOG.md 沒有這一版的段落（`## 1.1.0 — 日期`）時印出錯誤並以結束碼 1 結束，發布流程就會停下來：
每一版都一定要有更新說明。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

INSTALL = """\
## 下載與安裝

YT 下載器桌面 App，內含 yt-dlp、FFmpeg、Deno，不用另外安裝任何東西。
yt-dlp 會自動更新：App 在背景從 PyPI 下載新版，下次開啟（或按「重新啟動以套用」）就會使用。

### Windows 10 / 11
下載 **YT-Downloader-Setup-Windows.exe**，執行安裝精靈；完成後從「開始」功能表或桌面開啟「YT 下載器」。
若出現「Windows 已保護您的電腦」，按「其他資訊」→「仍要執行」。解除安裝：設定 → 應用程式。
從舊版更新：直接安裝新版即可，設定與下載紀錄會保留。

### macOS（Apple 晶片）
下載 **YT-Downloader-macOS-AppleSilicon.dmg**，打開後把「YT 下載器」拖進「應用程式」（取代舊版）。
第一次開啟若被擋下：到「系統設定 → 隱私權與安全性」按「仍要打開」，
或在「終端機」執行一次 `xattr -dr com.apple.quarantine "/Applications/YT 下載器.app"`。

檔案預設存在「下載」資料夾裡的 YT-Downloads，可以在 App 的「設定 → 儲存位置」更改。
"""


def changelog_section(version: str, text: str) -> str | None:
    """取出 `## <version> — 日期` 到下一個 `## ` 標題之間的內容（不含標題）。"""
    m = re.search(rf"^## {re.escape(version)}(?:\s|$).*?\n(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
    if not m:
        return None
    body = m.group(1).strip()
    return body or None


def release_notes(version: str, changelog: str) -> str:
    body = changelog_section(version, changelog)
    if body is None:
        raise ValueError(f"CHANGELOG.md 沒有 {version} 的更新說明：請在 CHANGELOG.md 加上「## {version} — 日期」段落再發布")
    # 段落裡的 ### 小標在 Release 頁面當成第二層
    return f"## 更新內容\n\n{body}\n\n{INSTALL}"


def main():
    if len(sys.argv) != 2:
        sys.exit("用法：python tools/release_notes.py <版本號>")
    version = sys.argv[1].strip().lstrip("v")
    try:
        notes = release_notes(version, (ROOT / "CHANGELOG.md").read_text(encoding="utf-8"))
    except ValueError as e:
        print(f"::error::{e}", file=sys.stderr)
        sys.exit(1)
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stdout.write(notes)


if __name__ == "__main__":
    main()
