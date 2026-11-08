# YT Downloader

用 [yt-dlp](https://github.com/yt-dlp/yt-dlp) + FFmpeg 下載 YouTube 與 1000+ 網站影片的桌面 App（PySide6 原生介面 + Flask 下載引擎，Windows／macOS）。

> [!IMPORTANT]
> 本軟體只是工具，不提供任何影音內容，與 YouTube／Google 無關。請只下載你有權使用的內容；使用、修改或散布本專案即表示同意 [免責聲明（DISCLAIMER.md）](DISCLAIMER.md)。

**一般使用者請看 [使用說明（USER_GUIDE.md）](USER_GUIDE.md)**；安裝檔在 [Releases](https://github.com/Archer8685/yt-dl/releases/latest)。

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
| `tools/release_notes.py` | 由 `CHANGELOG.md` 該版段落產生 Release 說明（＋安裝說明＋免責聲明） |
| `tools/ui_screenshot.py` | 以範例資料開啟 App 並截三個頁面（淺色／深色） |
| `tests/` | pytest：引擎 API、介面元件（offscreen Qt）、啟動流程、Release 說明 |

其他：`VERSION`（App 版本，發布觸發點）、`CHANGELOG.md`、`DISCLAIMER.md`、`USER_GUIDE.md`、`assets/`（圖示）、`start.bat`／`start.sh`（只跑引擎＋網頁版）。

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
   - `datas`：`index.html`、`assets/icon-128.png`、`assets/chevron.png`、`bundled-ytdlp.txt`（內建 yt-dlp 版本，自動更新比對用）、`VERSION`（「關於」顯示的版本）
   - `binaries`：`bin/` 下的 FFmpeg／ffprobe／Deno
   - 排除用不到的 Qt 模組與外掛（WebEngine、QML／Quick、Multimedia、軟體 OpenGL…），只留 zh_TW 翻譯
   - macOS 產生 `.app`（Info.plist 含顯示名稱、版本、深色模式、區域網路說明）並 `hiddenimports` PyObjC
3. 產出：
   - Windows：Inno Setup 6（`ISCC.exe`）→ `dist/YT-Downloader-Setup-Windows.exe`。腳本 `build/installer.iss` 以 UTF-8 BOM 寫入；`LicenseFile` 是由 `DISCLAIMER.md` 轉成的 `build/DISCLAIMER.txt`（UTF-8 BOM），安裝前要選「我同意」。預設只裝給目前使用者（不需管理員）。沒有 Inno Setup 時只產出 `dist/YT-Downloader/`。
   - macOS：`dist/YT-Downloader-macOS-AppleSilicon.dmg`（Intel 為 `-Intel`）。
- 版本號取自 `VERSION`，可用 `YTDL_APP_VERSION` 覆寫。App 未做程式碼簽章／公證。

## CI（`.github/workflows/`）

| Workflow | 觸發 | 內容 |
| --- | --- | --- |
| `release.yml` | push 到 `main` 且改了 `VERSION`；手動 | 該版已發布就略過；先用 `tools/release_notes.py` 確認 CHANGELOG 有該版段落 → Windows／macOS 各自 pytest、打包、實際安裝（靜默安裝／掛載 dmg）、引擎啟動測試、yt-dlp 自動更新載入測試（含壞掉的版本要快速失敗）、GUI 煙霧測試 → 發布 `v<版本>` Release |
| `ui-screenshots.yml` | 改了 `native_*.py`、`app_boot.py`、`assets/**`、`tools/ui_screenshot.py`；手動 | macOS／Windows 以淺色與深色各截一次三個頁面，放在該次執行的 Artifacts |
| `pages.yml` | 改了 `index.html` | 把網頁版介面部署到 GitHub Pages |

## 發布流程

1. 在 `CHANGELOG.md` 最上方寫 `## <版本> — YYYY-MM-DD` 段落（未發布的改動先放「未發布」底下）。
2. 修改 `VERSION`，跑 `pytest`。
3. Commit 並 push 到 `main` → `release.yml` 打包、測試、發布。Release 說明 = 該版段落 + 安裝說明（連到 `USER_GUIDE.md`）+ 免責聲明。

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

本專案未附開源授權檔；使用前請先閱讀 [DISCLAIMER.md](DISCLAIMER.md)。第三方元件依各自授權：[yt-dlp](https://github.com/yt-dlp/yt-dlp)（Unlicense）、[FFmpeg](https://ffmpeg.org)（打包版為 GPL 組建）、[Deno](https://deno.com)（MIT）、[Qt for Python](https://doc.qt.io/qtforpython-6/)（LGPL）。
