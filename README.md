# YT Downloader

一頁式影片下載器，底層使用 [yt-dlp](https://github.com/yt-dlp/yt-dlp) + FFmpeg。支援 YouTube 與 yt-dlp 支援的 1000+ 網站。

**線上介面：** https://archer8685.github.io/yt-dl/ （需搭配本機引擎，見下方）

## 功能

- **影片＋音訊 / 僅影片 / 僅音訊 / 僅字幕 / 僅縮圖** 五種模式
- **畫質**：最佳、8K 到 144p；編碼偏好 AV1 / VP9 / H.264 / H.265；FPS 上限；HDR / SDR
- **容器**：MP4、MKV、WebM、MOV、AVI、FLV（重新封裝或重新編碼）
- **多音軌**：可複選多種語言音軌，一次合併進同一個影片檔（例如原音＋中文配音）
- **音訊轉檔**：MP3、M4A、AAC、Opus、OGG、FLAC、WAV、ALAC，320k–64k 或 VBR
- **字幕**：上傳者字幕、自動字幕、自動翻譯字幕，可複選；SRT / VTT / ASS / LRC；嵌入或另存
- **手動格式表**：列出所有串流，可自選影片串流＋多條音訊串流
- **YouTube Premium**：上傳 Premium 帳號的 cookies.txt 後，可下載 Premium 專屬的 1080p 高位元率串流
- **剪輯**：只下載指定時間範圍（可多段）、依章節切割、點章節快速加入
- **SponsorBlock**：移除或標記贊助、片頭、片尾等片段
- **中繼資料**：嵌入標題、章節、封面縮圖；另存說明、info.json、留言
- **播放清單**：勾選要下載的項目或輸入範圍
- **網路**：cookies.txt / 瀏覽器 Cookie、代理伺服器、限速、地區、並行分段、重試次數
- 下載佇列：進度、速度、剩餘時間、取消、紀錄、多檔打包 ZIP
- **yt-dlp 自動更新**：引擎啟動時與每 6 小時檢查 PyPI，有新版自動更新並重啟

## 架構

GitHub Pages 只能放靜態網頁，**無法執行 yt-dlp**，所以分成兩部分：

| 部分 | 位置 | 作用 |
| --- | --- | --- |
| 介面 `index.html` | GitHub Pages，或引擎本身 | 操作畫面 |
| 引擎 `server.py` | 你的電腦 `127.0.0.1:8765` | 執行 yt-dlp / FFmpeg，存放下載的檔案 |

## 安裝與啟動

### 桌面 App（建議）

到 [Releases](https://github.com/Archer8685/yt-dl/releases/latest) 下載。App 已內建 yt-dlp、FFmpeg、Deno，不用裝 Python；介面在自己的視窗裡，不需要另開瀏覽器。

| 系統 | 檔案 | 安裝方式 |
| --- | --- | --- |
| Windows 10 / 11 | `YT-Downloader-Setup-Windows.exe` | 執行安裝精靈，之後從「開始」功能表或桌面開啟「YT 下載器」。出現「Windows 已保護您的電腦」時，按「其他資訊」→「仍要執行」。解除安裝在「設定 → 應用程式」 |
| macOS（Apple 晶片） | `YT-Downloader-macOS-AppleSilicon.dmg` | 打開後把「YT 下載器」拖進「應用程式」。第一次被擋下時，到「系統設定 → 隱私權與安全性」按「仍要打開」，或執行一次 `xattr -dr com.apple.quarantine "/Applications/YT 下載器.app"` |

- 檔案預設存在「下載」資料夾裡的 `YT-Downloads`。
- 設定、cookies、執行紀錄 `engine.log` 存在 `%LOCALAPPDATA%\YT-Downloader`（macOS：`~/Library/Application Support/YT-Downloader`）。
- 下載進行中關閉視窗時會先詢問；關掉後，下次開啟按「繼續下載」即可接著下載。
- 每個下載完成的檔案都有「開啟資料夾」，會直接在檔案總管 / Finder 中顯示。
- 用 `YT-Downloader --server` 啟動時只執行引擎、不開視窗，可以改用瀏覽器開 http://127.0.0.1:8765。

App 無法自行更新 yt-dlp。GitHub Actions 每天會檢查 yt-dlp 新版並重新打包；App 裡出現「下載新版引擎」時，下載並安裝新版即可（設定與下載紀錄會保留）。

### 用 Python 原始碼執行（Linux、Intel Mac、開發用）

需要：Python 3.10+、[FFmpeg](https://ffmpeg.org/download.html)、[Node.js](https://nodejs.org) 或 [Deno](https://deno.com)（YouTube 解 JS challenge 用）。

```bash
git clone https://github.com/Archer8685/yt-dl.git
cd yt-dl
start.bat      # Windows
./start.sh     # macOS / Linux
```

啟動後打開 http://127.0.0.1:8765，或打開 GitHub Pages 版介面（會自動連到本機引擎）。

### 自己打包

```bash
pip install -r requirements-app.txt
python build_app.py      # Windows：dist/YT-Downloader-Setup-Windows.exe（需要 Inno Setup 6）；macOS：dist/YT-Downloader-macOS-*.dmg
python desktop.py        # 開發時直接開 App 視窗
```

- `build_app.py` 會下載對應平台的 FFmpeg / ffprobe / Deno 一起打包。
- App 圖示由 `assets/make_icon.py` 產生（需要 Pillow）。
- push 到 `main` 或每天排程時，`.github/workflows/release.yml` 會在 Windows 與 macOS 上打包，實際安裝並做啟動測試後發布到 Releases。同一份程式碼加同一版 yt-dlp 只發布一次。

## yt-dlp 自動更新

YouTube 經常改版，yt-dlp 也跟著頻繁更新。引擎有三層自動更新：

1. `start.bat` / `start.sh` 每次啟動都會執行 `pip install -U`
2. `server.py` 啟動時查 PyPI，有新版就更新並自動重啟
3. 執行期間每 6 小時再檢查一次（沒有下載工作時才會更新重啟）

介面右上角也會在有新版時出現「更新至 x.x.x」按鈕。

| 環境變數 | 說明 |
| --- | --- |
| `YTDL_AUTO_UPDATE=0` | 關閉自動更新 |
| `YTDL_CHANNEL=nightly` | 使用 nightly（pre-release）版本，YouTube 壞掉時修正最快 |
| `YTDL_PORT` / `YTDL_HOST` | 監聽位址（預設 `127.0.0.1:8765`） |
| `YTDL_ALLOWED_ORIGINS` | 允許跨來源呼叫的網站，預設 `https://archer8685.github.io` |
| `YTDL_PARALLEL` | 同時下載數（預設 3） |
| `YTDL_DOWNLOAD_DIR` | 固定下載位置（設定後網頁上就不能改） |
| `YTDL_MIN_FREE_GB` | 剩餘空間低於此值就停止下載（預設 2） |

## 儲存位置與磁碟空間

下載佇列上方會顯示目前的儲存位置和剩餘空間，按「變更」可以一鍵切到其他磁碟，或輸入完整路徑（設定存在 `settings.json`）。

下載前和下載中都會檢查空間：如果檔案預估大小放不下，或剩餘空間低於 2 GB，會立即停止並保留已完成的檔案，不會把系統碟塞滿。下載整季 4K 這類大量內容前，建議先換到空間大的磁碟。

## 大檔案、中斷與續傳

- 下載途中斷線或串流網址過期（長時間下載常見的 HTTP 403）時，引擎會自動重新取得網址、從中斷處續傳，最多 3 次。
- 失敗的工作會保留已下載的暫存資料，按「繼續下載」就能接著下載；「清除已完成」不會刪掉這些工作。
- 每個工作都存有 `job.json`，引擎被關掉（關視窗、睡眠、重開機）後重新執行 `start.bat`，中斷的工作會顯示「已中斷」與「繼續下載」。
- 網頁和引擎斷線時，下載佇列上方會出現提示，不會再停在舊的進度上。
- 合併影音軌、寫入中繼資料時也會顯示進度、速度與剩餘時間。FFmpeg 每個步驟都要把整個檔案寫一遍，100 GB 的檔案在同一顆硬碟上每步約需半小時，請耐心等候。
- 為了少寫幾遍大檔案，MP4 不加 faststart（索引放在檔尾）。本機播放沒有差別；如果要放到網站上邊下載邊播放，可以用 `ffmpeg -i in.mp4 -c copy -movflags +faststart out.mp4` 轉一次。
- 長時間下載時，請讓 `start.bat` 的視窗保持開著，並關掉電腦的自動睡眠。

## YouTube Premium / 會員 / 年齡限制

1. 在瀏覽器登入你的 YouTube（Premium）帳號
2. 用擴充功能（例如「Get cookies.txt LOCALLY」）匯出 `youtube.com` 的 cookies.txt
3. 在介面「網路」區塊上傳，勾選「使用 cookies.txt」，然後重新解析網址
4. 格式表中標有 **Premium** 的就是 Premium 專屬串流；開啟「YouTube Premium 高位元率」會優先選它

cookies.txt 只存在你電腦上的專案資料夾（已列入 `.gitignore`），不會上傳到任何地方。也可以改用「從瀏覽器讀取 Cookie」。

## GitHub Pages 設定

Repo → Settings → Pages → Source 選 **GitHub Actions**。之後每次 push `index.html` 會由 `.github/workflows/pages.yml` 自動部署。

> Chrome 從 https 網站連到本機時，可能跳出「允許存取區域網路裝置」的提示，請選允許。Safari 不支援這種連線，請改用 Chrome / Edge / Firefox，或直接開 http://127.0.0.1:8765。

## 注意

請只下載你有權使用的內容，並遵守各平台服務條款與著作權法。
