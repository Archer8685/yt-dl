"""產生 GitHub Release 的說明。

順序：該下載哪個檔（表格）→ CHANGELOG.md 裡這一版的「更新內容」→ 安裝與放行步驟（連到 USER_GUIDE.md）
→ 檢查檔案是否完整（SHA256SUMS.txt）→ 免責聲明。

    python tools/release_notes.py 1.3.0 > notes.md
    python tools/release_notes.py 1.3.0 --assets release-assets > notes.md   # 表格附上實際檔案大小

CHANGELOG.md 沒有這一版的段落（`## 1.3.0 — 日期`）時印出錯誤並以結束碼 1 結束，發布流程就會停下來：
每一版都一定要有更新說明。CHANGELOG.md 裡的 HTML 註解（`<!-- … -->`，維護說明）不會出現在 Release 說明裡。
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

REPO_URL = "https://github.com/Archer8685/yt-dl"
# 文件一律連到 main 的最新版（使用說明、免責聲明會隨新版更新）
DOCS_URL = f"{REPO_URL}/blob/main"
USER_GUIDE_URL = f"{DOCS_URL}/USER_GUIDE.md"
DISCLAIMER_URL = f"{DOCS_URL}/DISCLAIMER.md"

WINDOWS_FILE = "YT-Downloader-Setup-Windows.exe"
MAC_FILE = "YT-Downloader-macOS-AppleSilicon.dmg"
CHECKSUMS_FILE = "SHA256SUMS.txt"

# (系統, 檔名, 需求)
DOWNLOADS = [
    ("Windows 10／11", WINDOWS_FILE, "64 位元（x64）電腦"),
    ("macOS（Apple 晶片）", MAC_FILE, "M1 以後的 Mac，macOS 14 以上。**Intel Mac 不支援**"),
]

INSTALL = f"""\
## 下載與安裝

App 已內含 yt-dlp、FFmpeg、Deno，不用另外安裝任何東西；yt-dlp 會在背景自動更新。
第一次開啟會顯示使用聲明，按「我了解並同意」後才能使用。檔案預設存在「下載」資料夾裡的 YT-Downloads。
完整操作與常見問題請見 [使用說明（USER_GUIDE.md）]({USER_GUIDE_URL})。

> App 沒有付費的數位簽章，所以 Windows 和 macOS 第一次開啟時會跳出警告。這不代表有病毒；
> 想確認檔案沒被竄改，可以比對下方的 SHA-256 校驗值。

### Windows 10／11
1. 下載 **{WINDOWS_FILE}**。瀏覽器若說「通常不會下載此檔案」，按「…」→「保留」。
2. 執行安裝精靈。出現「Windows 已保護您的電腦」時，按「其他資訊」→「仍要執行」。
3. 防毒軟體若把檔案隔離或刪除，請到防毒軟體的「隔離區」還原並加入例外。
4. 從舊版更新：先等進行中的下載完成，再直接安裝新版，設定與下載紀錄會保留。

詳細步驟：[Windows 安裝與放行]({USER_GUIDE_URL}#install-windows)

### macOS（Apple 晶片）
1. 下載 **{MAC_FILE}**，打開後把「YT 下載器」拖進「應用程式」（取代舊版）。
2. 先雙擊開啟一次（會被擋下，按「完成」）。
3. 到「系統設定 → 隱私權與安全性」，捲到最下方按「仍要打開」，再輸入密碼確認。
4. 只有顯示「已損毀，應該丟到垃圾桶」時，才在「終端機」執行一次
   `xattr -dr com.apple.quarantine "/Applications/YT 下載器.app"`。

Intel Mac 不支援：點左上角  →「關於這台 Mac」，「晶片」寫 Apple M 開頭才能使用。
詳細步驟（含 macOS 14、15 的差異）：[macOS 安裝與放行]({USER_GUIDE_URL}#install-macos)
"""

CHECKSUMS = f"""\
## 檢查檔案是否完整（選用）

下載 **{CHECKSUMS_FILE}**，在安裝檔所在的資料夾執行下面的指令，算出來的值和 {CHECKSUMS_FILE} 裡同名檔案的值一樣
（英文大小寫不同沒關係），就代表檔案完整、沒被竄改。

- Windows（PowerShell）：`Get-FileHash .\\{WINDOWS_FILE} -Algorithm SHA256`
- macOS（終端機）：`shasum -a 256 {MAC_FILE}`
"""

DISCLAIMER = f"""\
## 免責聲明

本軟體只是工具，不提供、不託管任何影音內容，與 YouTube／Google 無任何關聯，並以「現狀」提供、不提供任何保證。
請只下載你有權使用的內容，遵守著作權法與各平台服務條款；不得用於侵權、散布盜版或規避付費、DRM 等保護措施。
使用者須自行承擔使用責任。完整內容請見 [DISCLAIMER.md]({DISCLAIMER_URL})。

*This software is a tool only and is not affiliated with YouTube or Google. Download only content you have the right to use. See [DISCLAIMER.md]({DISCLAIMER_URL}).*
"""


def strip_comments(text: str) -> str:
    """拿掉 HTML 註解（CHANGELOG.md 開頭的維護說明）。"""
    return re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)


def changelog_section(version: str, text: str) -> str | None:
    """取出 `## <version> — 日期` 到下一個 `## ` 標題之間的內容（不含標題、不含 HTML 註解）。"""
    text = strip_comments(text)
    m = re.search(rf"^## {re.escape(version)}(?:\s|$).*?\n(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
    if not m:
        return None
    body = m.group(1).strip()
    return body or None


def human_size(n: int) -> str:
    return f"{n / 1024 ** 2:.0f} MB"


def download_table(version: str, sizes: dict[str, int] | None = None) -> str:
    """「該下載哪個檔」：放在 Release 說明最上面。連結指向這一版的檔案。"""
    sizes = sizes or {}
    rows = ["| 你的電腦 | 下載這個檔案 | 大小 | 需求 |", "| --- | --- | --- | --- |"]
    for system, name, need in DOWNLOADS:
        url = f"{REPO_URL}/releases/download/v{version}/{name}"
        size = human_size(sizes[name]) if name in sizes else "—"
        rows.append(f"| {system} | [{name}]({url}) | {size} | {need} |")
    return (
        "## 該下載哪個檔\n\n" + "\n".join(rows) + "\n\n"
        "**請不要下載下方的「Source code」**：那是給開發者的原始碼，不是 App。\n"
        f"第一次開啟會被 Windows／macOS 擋下是正常的，放行步驟見下方「下載與安裝」"
        f"或 [使用說明]({USER_GUIDE_URL}#install-windows)。\n"
    )


def release_notes(version: str, changelog: str, sizes: dict[str, int] | None = None) -> str:
    body = changelog_section(version, changelog)
    if body is None:
        raise ValueError(f"CHANGELOG.md 沒有 {version} 的更新說明：請在 CHANGELOG.md 加上「## {version} — 日期」段落再發布")
    # 段落裡的 ### 小標在 Release 頁面當成第二層
    return f"{download_table(version, sizes)}\n## 更新內容\n\n{body}\n\n{INSTALL}\n{CHECKSUMS}\n{DISCLAIMER}"


def asset_sizes(folder: Path) -> dict[str, int]:
    return {p.name: p.stat().st_size for p in folder.iterdir() if p.is_file()}


def main():
    parser = argparse.ArgumentParser(description="產生 GitHub Release 說明")
    parser.add_argument("version")
    parser.add_argument("--assets", type=Path, help="安裝檔所在的資料夾（表格會附上實際大小）")
    args = parser.parse_args()
    version = args.version.strip().lstrip("v")
    try:
        sizes = asset_sizes(args.assets) if args.assets else None
        notes = release_notes(version, (ROOT / "CHANGELOG.md").read_text(encoding="utf-8"), sizes)
    except (ValueError, OSError) as e:
        print(f"::error::{e}", file=sys.stderr)
        sys.exit(1)
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stdout.write(notes)


if __name__ == "__main__":
    main()
