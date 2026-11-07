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

需要：Python 3.10+、[FFmpeg](https://ffmpeg.org/download.html)、[Node.js](https://nodejs.org) 或 [Deno](https://deno.com)（YouTube 解 JS challenge 用）。

```bash
git clone https://github.com/Archer8685/yt-dl.git
cd yt-dl
start.bat      # Windows
./start.sh     # macOS / Linux
```

啟動後打開 http://127.0.0.1:8765，或打開 GitHub Pages 版介面（會自動連到本機引擎）。

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
