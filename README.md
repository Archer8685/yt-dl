# YT 下載器（YT Downloader）

**English:** A free desktop app for Windows and macOS that downloads videos, music, subtitles and thumbnails from YouTube and 1,000+ other sites. yt-dlp and FFmpeg are built in and yt-dlp updates itself; the interface is available in English. **[User guide & FAQ (English)](USER_GUIDE.en.md)**

| Your computer | Download | Requirements |
| --- | --- | --- |
| **Windows 10/11** | [⬇ YT-Downloader-Setup-Windows.exe](https://github.com/Archer8685/yt-dl/releases/latest/download/YT-Downloader-Setup-Windows.exe) | 64-bit (x64) PC |
| **macOS (Apple silicon)** | [⬇ YT-Downloader-macOS-AppleSilicon.dmg](https://github.com/Archer8685/yt-dl/releases/latest/download/YT-Downloader-macOS-AppleSilicon.dmg) | M1 or later, macOS 14+ |

Intel Macs are not supported. The app isn't code-signed, so Windows and macOS warn you the first time; this doesn't mean it has a virus. Follow the [Windows](USER_GUIDE.en.md#install-windows) or [macOS](USER_GUIDE.en.md#install-macos) steps to allow it. Only download content you have the right to use; see the [Disclaimer](DISCLAIMER.md).

---

下載 YouTube 與 1000+ 個網站的影片、音樂、字幕和縮圖的免費桌面 App（Windows／macOS）。內建 yt-dlp、FFmpeg，不用另外安裝任何東西；yt-dlp 會自動更新。

> [!IMPORTANT]
> 本軟體只是工具，不提供任何影音內容，與 YouTube／Google 無關。請只下載你有權使用的內容；使用、修改或散布本專案即表示同意 [免責聲明（DISCLAIMER.md）](DISCLAIMER.md)。

## 下載

| 你的電腦 | 下載這個檔案 | 需求 |
| --- | --- | --- |
| **Windows 10／11** | [⬇ YT-Downloader-Setup-Windows.exe](https://github.com/Archer8685/yt-dl/releases/latest/download/YT-Downloader-Setup-Windows.exe) | 64 位元（x64）電腦 |
| **macOS（Apple 晶片）** | [⬇ YT-Downloader-macOS-AppleSilicon.dmg](https://github.com/Archer8685/yt-dl/releases/latest/download/YT-Downloader-macOS-AppleSilicon.dmg) | M1 以後的 Mac，macOS 14 以上 |

- **Intel Mac 不支援**（點左上角  →「關於這台 Mac」，「晶片」寫 Apple M 開頭才能使用）。
- App 沒有付費的數位簽章，第一次開啟時 Windows（SmartScreen）和 macOS（Gatekeeper）會跳出警告，這不代表有病毒：照 [Windows 放行步驟](USER_GUIDE.md#install-windows)、[macOS 放行步驟](USER_GUIDE.md#install-macos) 操作即可。每一版都附 `SHA256SUMS.txt`，可以[自己確認檔案沒被竄改](USER_GUIDE.md#verify-download)。
- Release 頁面上的「Source code」是給開發者的原始碼，不是 App。
- 所有版本與更新內容：[Releases](https://github.com/Archer8685/yt-dl/releases)・[更新紀錄](CHANGELOG.md)

**使用說明與常見問題：[USER_GUIDE.md](USER_GUIDE.md)**（[下載失敗、錯誤訊息怎麼辦](USER_GUIDE.md#faq)・[從瀏覽器一鍵送到 App](USER_GUIDE.md#bookmarklet)・[回報問題](https://github.com/Archer8685/yt-dl/issues/new/choose)）

## 功能

- 影片＋音訊、僅影片、僅音訊（MP3、M4A、FLAC…）、字幕、縮圖；最高 4K／HDR
- 播放清單：勾選、搜尋、輸入範圍；下載佇列可暫停、續傳
- 剪輯片段、依章節切割、SponsorBlock、嵌入中繼資料與封面
- 書籤小工具（`ytdl://`）從瀏覽器一鍵送到 App；可縮到系統匣在背景下載
- 中文（繁體）／English 介面，淺色／深色主題

---

以下是給開發者的內容。

## 專案架構

介面與引擎跑在同一個程序：`server.py` 在背景執行緒提供本機 HTTP API（預設 `127.0.0.1:8765`），Qt 介面透過 API 操作。

| 檔案 | 負責 |
| --- | --- |
| `native_app.py` | App 進入點與主視窗：側邊欄、「新增下載」、「下載佇列」、「設定」頁；樣式表與主題、剪貼簿自動貼上、免責聲明對話框、macOS 毛玻璃側邊欄 |
| `native_options.py` | 「進階選項」面板（編碼、音軌、字幕、剪輯、SponsorBlock、中繼資料、Cookie／代理／限速）與共用元件（`Switch` 等） |
| `native_playlist.py` | 播放清單選擇：勾選、搜尋、範圍、縮圖延遲載入 |
| `app_boot.py` | 啟動流程：命令列參數、匯入引擎（含自動更新的 yt-dlp）、背景啟動引擎、紀錄檔、`--smoke-test` |
| `server.py` | 下載引擎（Flask + yt-dlp）：解析、佇列、續傳、磁碟空間檢查、cookies、Premium 檢查；也提供網頁版介面 `index.html` |
| `ytdlp_update.py` | yt-dlp 自動更新：從 PyPI 下載新版到使用者資料夾，驗證能載入後才啟用，失敗退回內建版 |
| `build_app.py` | 打包：下載 FFmpeg／ffprobe／Deno → 產生 PyInstaller spec → Inno Setup 安裝精靈或 dmg |
| `index.html` | 網頁版介面（引擎直接提供，也部署到 GitHub Pages 連本機引擎） |
| `tools/release_notes.py` | 由 `CHANGELOG.md` 該版段落產生 Release 說明（下載表＋更新內容＋安裝與放行步驟＋校驗方式＋免責聲明） |
| `tools/ui_screenshot.py` | 以範例資料開啟 App 並截三個頁面（淺色／深色） |
| `tests/` | pytest：引擎 API、介面元件（offscreen Qt）、啟動流程、Release 說明 |

其他：`VERSION`（App 版本，發布觸發點）、`CHANGELOG.md`、`DISCLAIMER.md`、`USER_GUIDE.md`／`USER_GUIDE.en.md`（使用說明中英文版）、`LICENSE`、`THIRD_PARTY_NOTICES.md`、`.github/ISSUE_TEMPLATE/`（回報問題／功能建議表單）、`assets/`（圖示）、`start.bat`／`start.sh`（只跑引擎＋網頁版）。

## 開發環境

需要 Python 3.10+（CI 用 3.12）；從原始碼執行另需 PATH 上有 FFmpeg，以及 Deno 或 Node.js（yt-dlp 解 YouTube 簽章用）。

```bash
git clone https://github.com/Archer8685/yt-dl.git
cd yt-dl
python -m venv .venv
.venv/Scripts/activate          # macOS／Linux：source .venv/bin/activate
pip install -r requirements-app.txt pytest ruff
python native_app.py            # 原生 App
```

- `requirements.txt`：引擎（yt-dlp、Flask）；`requirements-app.txt`：再加 PySide6-Essentials、PyInstaller、macOS 的 PyObjC。
- `python native_app.py --server`：只跑引擎不開視窗，瀏覽器開 http://127.0.0.1:8765 用網頁版。
- `python native_app.py --smoke-test`：視窗顯示幾秒後自動結束（可搭配 `QT_QPA_PLATFORM=offscreen`）。
- `start.bat`／`start.sh`：只跑 `server.py`，每次啟動會 `pip install -U yt-dlp`。
- 開發時「設定 → 關於」顯示專案根目錄的 `VERSION`。

## 測試

```bash
python -m pytest -q
ruff check .
python tools/ui_screenshot.py shots light   # 截圖到 shots/，第二個參數 light 或 dark
```

- 介面測試用 offscreen Qt（各測試檔設定 `QT_QPA_PLATFORM=offscreen`；`tests/conftest.py` 負責結束時依序釋放 Qt），不需要螢幕。
- `tests/test_release_notes.py` 會檢查目前的 `VERSION` 在 `CHANGELOG.md` 有對應段落：改版號前先寫 CHANGELOG，否則測試失敗。
- 自動化執行 App 時設 `YTDL_ACCEPT_DISCLAIMER=1`，避免被第一次開啟的使用聲明擋住（`--smoke-test` 會自動跳過）。

## 打包

```bash
python build_app.py
```

1. 下載當前平台的 FFmpeg／ffprobe／Deno 到 `build/vendor/bin` 並實際執行確認（GitHub 下載失敗會重試並改走 GitHub API；有 `GITHUB_TOKEN` 會帶上）。
2. 產生 `build/YT-Downloader.spec` 並執行 PyInstaller（onedir、無主控台）：
   - `datas`：`index.html`、`assets/icon-128.png`、`assets/chevron.png`、`bundled-ytdlp.txt`（內建 yt-dlp 版本，自動更新比對用）、`VERSION`（「關於」顯示的版本）、`LICENSE`、`THIRD_PARTY_NOTICES.md`；`i18n/*.qm`（App 的翻譯檔，放到 App 裡的 `i18n/`；還沒用 `tools/i18n_update.py` 編譯出來時自動略過）
   - `binaries`：`bin/` 下的 FFmpeg／ffprobe／Deno
   - 排除用不到的 Qt 模組與外掛（WebEngine、QML／Quick、Multimedia、軟體 OpenGL…）；Qt 內建翻譯只留 `qtbase_*`、`qt_*` 的 zh_TW 與 en
   - macOS 產生 `.app`（Info.plist 含顯示名稱、版本、深色模式、區域網路說明、`ytdl://` 的 `CFBundleURLTypes`）並 `hiddenimports` PyObjC
3. 產出：
   - Windows：Inno Setup 6（`ISCC.exe`）→ `dist/YT-Downloader-Setup-Windows.exe`。腳本 `build/installer.iss` 以 UTF-8 BOM 寫入；`LicenseFile` 是由 `DISCLAIMER.md` 轉成的 `build/DISCLAIMER.txt`（UTF-8 BOM），安裝前要選「我同意」。精靈有 English 與繁體中文，依 Windows 介面語言自動選。預設只裝給目前使用者（不需管理員）。安裝時註冊 `ytdl://`（`HKCU\Software\Classes\ytdl`，裝給所有使用者時是 HKLM），並把 `LICENSE.txt`、`THIRD_PARTY_NOTICES.md` 放在安裝資料夾最上層；解除安裝時刪除 `ytdl` 機碼，並詢問是否一併刪除 `%LOCALAPPDATA%\YT-Downloader` 與 `HKCU\Software\YTDownloader`（預設否，靜默解除安裝時保留）。沒有 Inno Setup 時只產出 `dist/YT-Downloader/`。
   - macOS：`dist/YT-Downloader-macOS-AppleSilicon.dmg`（Intel 為 `-Intel`，但 CI 不產生、也不支援）。
- 版本號取自 `VERSION`，可用 `YTDL_APP_VERSION` 覆寫。App 不做程式碼簽章／公證（已決定），文件改為教使用者放行並提供 SHA-256 校驗值。

## CI（`.github/workflows/`）

| Workflow | 觸發 | 內容 |
| --- | --- | --- |
| `release.yml` | push 到 `main` 且改了 `VERSION`；手動 | 該版已發布就略過；先用 `tools/release_notes.py` 確認 CHANGELOG 有該版段落 → Windows／macOS 各自 pytest、打包、實際安裝（靜默安裝／掛載 dmg）、引擎啟動測試、yt-dlp 自動更新載入測試（含壞掉的版本要快速失敗）、GUI 煙霧測試、檢查授權檔與 `ytdl://` 註冊 → 產生 `SHA256SUMS.txt`，連同安裝檔發布 `v<版本>` Release |
| `ui-screenshots.yml` | 改了 `native_*.py`、`app_boot.py`、`assets/**`、`tools/ui_screenshot.py`；手動 | macOS／Windows 以淺色與深色各截一次三個頁面，放在該次執行的 Artifacts |
| `pages.yml` | 改了 `index.html` | 把網頁版介面部署到 GitHub Pages |

## 發布流程

1. 在 `CHANGELOG.md` 最上方寫 `## <版本> — YYYY-MM-DD` 段落（用一般使用者看得懂的話；維護說明在檔案開頭的 HTML 註解裡）。
2. 修改 `VERSION`，跑 `pytest`。
3. Commit 並 push 到 `main` → `release.yml` 打包、測試、發布。Release 說明（`tools/release_notes.py`）= 該下載哪個檔（附實際大小、Intel Mac 不支援、不要下載 Source code）+ 該版段落 + 安裝與放行步驟（連到 `USER_GUIDE.md` 的 `#install-windows`、`#install-macos`）+ SHA-256 校驗方式 + 免責聲明。

同一版只會發布一次；要重發請先刪掉該 Release／tag，或改版號。

## 環境變數

| 變數 | 說明 |
| --- | --- |
| `YTDL_PORT`／`YTDL_HOST` | 引擎監聽位址（預設 `127.0.0.1:8765`） |
| `YTDL_DOWNLOAD_DIR` | 固定下載位置（設定後介面上不能改） |
| `YTDL_PARALLEL` | 同時下載數（預設 3） |
| `YTDL_MIN_FREE_GB` | 剩餘空間低於此值就停止下載（預設 2） |
| `YTDL_AUTO_UPDATE=0` | 關閉 yt-dlp 自動更新 |
| `YTDL_CHANNEL=nightly` | 自動更新改用 yt-dlp nightly |
| `YTDL_ALLOWED_ORIGINS` | 允許跨來源呼叫引擎的網站，逗號分隔（預設 `https://archer8685.github.io`） |
| `YTDL_ACCEPT_DISCLAIMER=1` | 跳過第一次開啟的使用聲明（自動化、截圖） |
| `YTDL_APP_VERSION` | 打包時覆寫 App 版本號（`build_app.py`） |
| `GITHUB_TOKEN` | 打包時下載工具走 GitHub API 用，避免匿名請求被限流 |

資料存放位置：

- 引擎資料（`settings.json` 的下載位置、`cookies.txt`、自動更新的 yt-dlp、`engine.log`）：打包版在 Windows `%LOCALAPPDATA%\YT-Downloader`、macOS `~/Library/Application Support/YT-Downloader`；從原始碼執行時在專案根目錄（預設下載到 `downloads/`，已在 `.gitignore`）。
- 介面偏好（外觀、下載預設值、進階選項、自動貼上、免責聲明同意紀錄）：`QSettings("YTDownloader", "NativeApp")`，即 Windows 登錄 `HKCU\Software\YTDownloader\NativeApp`、macOS `~/Library/Preferences` 的 plist。

## 授權與免責

本專案以 [MIT 授權](LICENSE) 釋出（Copyright (c) 2026 Archer8685）；使用前請先閱讀 [DISCLAIMER.md](DISCLAIMER.md)。
安裝檔內含的第三方元件依各自授權提供，完整清單、授權全文與原始碼取得方式見 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)：[yt-dlp](https://github.com/yt-dlp/yt-dlp)（Unlicense）、[FFmpeg](https://ffmpeg.org)（GPL 組建）、[Deno](https://deno.com)（MIT）、[Qt for Python](https://doc.qt.io/qtforpython-6/)（LGPLv3）等。

USER_GUIDE 的 FAQ 每一題都有固定錨點（`err-…`，對照 `engine_messages.py` 的錯誤代碼；另有 `install-windows`、`install-macos`、`tray`、`bookmarklet`、`uninstall`），App 與 Release 說明會直接連過去：**不要改錨點名稱**，新增或修改 FAQ 時英文版 `USER_GUIDE.en.md` 要一起改。
