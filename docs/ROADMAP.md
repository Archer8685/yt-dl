# YT 下載器 下一版規劃（v1.3.0 起）

- 撰寫日期：2026-11-09（同日依使用者決定改版，見[第 6 節](#6-已決定的事)）｜基準版本：v1.2.0（`main` @ 68ae7d0）
- 資料來源：四份盤點報告（存在 session 共用筆記資料夾，不在 repo 裡）
  - **APP**＝`ux-audit-app.md`（App 實機操作，A1–I2）
  - **ONB**＝`ux-audit-onboarding.md`（安裝、更新、文件、求助，1-1–6-3）
  - **ENG**＝`ux-audit-engine.md`（效能、可靠度、錯誤處理，1-1–5-4）
  - **FEAT**＝`feature-research.md`（新功能候選，1-1–1-19、不建議 2-1–2-8）
- 本文件只是規劃，沒有改任何程式。表格裡的「來源」欄就是上面報告的編號，例如 `APP-E1` 是 App 報告的 E1。

---

## 摘要（先看這一頁）

### 下一版主題：v1.3.0「可靠、看得懂、找得到，走向國際」

v1.2.0 的功能已經很完整，但盤點發現幾個問題：有的會**讓使用者以為下載成功、其實沒有**，有的會**讓 App 打不開**，還有大量錯誤訊息直接顯示 yt-dlp 的英文原文。v1.3.0 先修好這些問題，同時處理最明顯的操作障礙。

依使用者決定，v1.3.0 同時加入三個較大的新功能：**系統匣常駐**、**`ytdl://` 一鍵送到 App**（含單一實例機制），以及**英文介面**（可切換跟隨系統／中文／English，USER_GUIDE 也出英文版）。另外還有幾個小功能：批次貼上、拖放網址、下載完成通知、暫停／繼續全部、同時下載數、App 新版提示。專案改用 **MIT 授權**。

比較大的結構調整放到 **v1.4.0「整理與管理」**，包括工作紀錄搬出下載資料夾、輸出資料夾自動分類、下載歷史。頻道追蹤放到 **v1.5.0**。

### 最重要的 5 件事（v1.3.0）

| # | 要做的事 | 為什麼重要 | 對應 |
|---|---|---|---|
| 1 | **下載結果要可信**：只有縮圖或字幕檔時不能算「完成」；播放清單遇到一部失敗要繼續下載其他部，並顯示「完成 180/200，20 部無法下載」；網路一開始就斷線也要自動重試 | 現在使用者可能看到「完成」，實際只拿到一張 jpg，或 200 部只下載了 37 部 | R2、R3、R10、R11 |
| 2 | **App 一定打得開，錯誤原因要說對**：下載資料夾所在的磁碟不存在時，App 要能開啟並提示「更換位置」；引擎回傳 500 時不要誤報「連接埠被佔用」；`/api/meta` 不再同步查 PyPI | 外接硬碟、隨身碟、NAS 使用者拔掉磁碟後 App 完全開不起來 | R1、ERR6、PERF1 |
| 3 | **不再丟掉使用者的資料**：「取消」改成真正的「暫停／繼續」；「刪除」預設改成「只從清單移除」，刪檔改成放進資源回收筒，另加「清除已完成」 | 取消鈕的提示說「可以再繼續」，實際上會刪掉暫存檔；刪除一定是永久刪除 | R4、R5 |
| 4 | **看得懂的錯誤訊息**：引擎回傳錯誤代碼、說明和下一步按鈕，說明有中文和英文；App 可以看工作紀錄、複製錯誤；FAQ 補齊常見錯誤，錯誤訊息直接連到 FAQ | 目前使用者會看到 `Use --cookies-from-browser` 這類命令列訊息，這是最多人求助的原因 | ERR1–ERR5、ERR9 |
| 5 | **主要動作看得到**：「摘要＋下載」改成固定在底部的動作列；解析中可以取消；切到「字幕」模式時自動展開語言選擇 | 預設視窗大小下看不到「下載」鈕 | DL1、DL2、DL3 |

### v1.3.0 的規模與開工順序

- 預估工作量約 **46 人日**，切成 **15 個工作包**，日曆時間約 **12 個工作天**（約 2.5 週）。
- **第一批（立刻同時開工，6 包）**：WP-0 拆檔、I0 多語系基礎、E1 引擎可靠度、E2 引擎訊息、F 文件發布與授權、T 系統整合。各包的檔案範圍見[第 5.1 節](#51-檔案所有權與開工批次)。
- **第二批**（WP-0、I0 合併後）：A1、A2、B、C1、C2 五個介面工作包，加上 F 合併後開始的 F-EN 英文文件。
- **第三批**（介面工作包全部合併後）：I2 英文翻譯、D 無障礙與字串收尾。
- **第四批**：INT 整合發布。

### 已決定的事（詳見[第 6 節](#6-已決定的事)）

| 決定 | 內容 |
|---|---|
| 程式碼簽章 | **Windows 和 macOS 都不做**。文件改成一步一步教使用者放行 SmartScreen／Gatekeeper |
| 系統匣常駐、`ytdl://`、英文介面 | **併入 v1.3.0** |
| 授權 | **MIT**，著作權人 Archer8685，另附第三方授權說明 |
| Intel Mac | 不出 Intel 版，文件寫明不支援 |
| GitHub Pages | 改成 GitHub Actions 發布 |
| 其他 | App 只提示新版、不自動安裝；網頁版停止加新功能；不開 Discussions；不做 App 內搜尋；頻道追蹤 v1.5.0 先做只通知版；第 6.2 節的小決定都照建議 |

---

## 1. 總表：去重與合併後的所有項目

四份報告共約 100 個項目，有不少重複（例如錯誤訊息在四份報告都出現；App 新版提示在 APP 和 ONB 都有）。合併後的總表如下。

- **嚴重度**：高＝會卡住、誤導，或可能遺失資料；中＝明顯多花力氣或看不懂；低＝打磨。
- **工作量**：小＝半天到 1 天；中＝2–3 天；大＝1 週以上。
- **版本**：1.3／1.4／1.5＝排定的版本；不做＝見[第 7 節](#7-不建議做的功能)。
- **工作包**：v1.3.0 的工作包代號，見[第 5 節](#5-v130-工作包可平行)。

### 1.1 可靠度（R）

| ID | 項目 | 來源 | 嚴重度 | 工作量 | 版本 | 工作包 |
|---|---|---|---|---|---|---|
| R1 | 下載資料夾所在的磁碟不存在時 App 打不開；執行中拔掉磁碟，所有 API 回傳 500 | ENG-5-1 | 高 | 小 | 1.3 | E1、C1 |
| R2 | 只要工作資料夾裡有縮圖或字幕檔，失敗就被當成「完成（有警告）」，而且沒有「繼續下載」 | ENG-2-2 | 高 | 小 | 1.3 | E1、B |
| R3 | 播放清單遇到一部無法下載的影片就整個停止，卻顯示「完成（有警告）」（程式碼確認沒設 `ignoreerrors`，實際行為是推論） | ENG-2-1 | 高 | 小 | 1.3 | E1、B |
| R4 | 「取消」的提示說可以繼續，實際上取消後不能續傳，暫存檔也被刪掉 | APP-E1 | 高 | 小–中 | 1.3 | E1、B |
| R5 | 刪除一定永久刪檔；沒有「只從清單移除」「清除已完成」；不使用資源回收筒 | APP-E2、ENG-5-4 | 高 | 小 | 1.3 | E1、B |
| R6 | 「完成（有警告）」的警告內容在 App 裡看不到 | APP-E5 | 中 | 小 | 1.3 | B |
| R7 | 取消「排隊中」的工作沒有存檔，重開 App 會變成「已中斷」 | ENG-2-9 | 低 | 小 | 1.3 | E1 |
| R8 | `settings.json` 不是原子寫入，寫壞後會悄悄改回預設下載資料夾 | ENG-5-2（前半） | 中 | 小 | 1.3 | E1 |
| R9 | 更換下載位置後，舊位置的工作從佇列消失 | ENG-5-2（後半） | 中 | 中 | 1.4 | 工作紀錄重構 |
| R10 | 一開始就斷線、DNS 失敗、5xx、429 不會自動重試；睡眠醒來後排隊工作一次全部失敗；沒有「全部重試」 | ENG-2-4 | 中 | 小 | 1.3 | E1、B |
| R11 | 合併、轉檔等後處理期間沒有檢查磁碟空間，空間不足會被當成一般失敗 | ENG-2-5 | 中 | 小 | 1.3 | E1 |
| R12 | 關閉 App 時 ffmpeg 子程序沒有一起結束，可能鎖住檔案（推論） | ENG-4-5 | 低–中 | 小 | 1.4 | — |
| R13 | 沒有設定 `trim_file_name`，長標題加上工作資料夾可能超過 Windows 260 字元路徑 | ENG-2-7 | 低–中 | 小 | 1.3 | E1 |
| R14 | `watch?v=`（空 id）會被解析成「recommended」播放清單 | ENG-2-11 | 低 | 小 | 1.3 | E1 |

### 1.2 錯誤訊息、紀錄與求助（ERR）

| ID | 項目 | 來源 | 嚴重度 | 工作量 | 版本 | 工作包 |
|---|---|---|---|---|---|---|
| ERR1 | 沒有錯誤翻譯層：yt-dlp 英文原文、CLI 參數、GitHub 回報連結直接顯示（解析失敗、佇列失敗都是） | APP-B4、APP-E3、ENG-3-1、ENG-3-2、ONB-5-1 | 高 | 中 | 1.3 | E2、E1、A1、B |
| ERR2 | Chrome／Edge Cookie 讀不到時，只有「測試」按鈕有中文提示，解析和下載沒有 | ENG-3-2、ENG 前 10 #5 | 高 | 小 | 1.3 | 併入 ERR1 |
| ERR3 | 下載失敗時，即使有新版 yt-dlp 等著套用，也不會建議「套用並重試」 | ONB-4-2 | 中 | 小 | 1.3 | E2、B |
| ERR4 | App 看不到工作紀錄；`job.log` 不寫進 job.json，重開就沒了；`engine.log` 80% 是輪詢紀錄、沒有錯誤；「關於」沒有開啟紀錄資料夾、回報問題的入口 | APP-E3、ENG-3-1、ENG-4-2、ONB-5-3 | 中 | 小 | 1.3 | E1、B、C2 |
| ERR5 | 磁碟空間不足的訊息叫使用者去「下載佇列上方」改位置（那是網頁版的位置） | APP-E4 | 中 | 小 | 1.3 | E1、E2 |
| ERR6 | 引擎回傳 500 時是 Flask 的 HTML 頁，App 顯示英文 Qt 錯誤或誤報「連接埠可能被其他程式佔用」 | ENG-3-2 末列、ENG-5-1 | 高 | 小 | 1.3 | E1、C1 |
| ERR7 | 引擎連不上時 banner 是英文、不能重試，同一個錯誤顯示兩次 | APP-G1 | 高 | 小 | 1.3 | C1 |
| ERR8 | 所有回饋都放同一條 banner，錯誤 6 秒就消失，不能關、不能複製 | APP-G3 | 中 | 小 | 1.3 | C1 |
| ERR9 | FAQ 缺 403、「確認你不是機器人」、429、私人／地區限制、Chrome Cookie 加密、防毒誤判、連接埠被佔用等；沒有固定錨點讓錯誤訊息連過去 | ONB-5-2 | 高 | 小–中 | 1.3 | F、F-EN |
| ERR10 | GitHub 沒有 issue 範本，回報常缺版本、log，還可能貼出 cookies | ONB-5-4 | 中 | 小 | 1.3 | F |
| ERR11 | engine.log 含家目錄路徑、觀看網址，文件沒提醒；寫入時沒有遮蔽 | ONB-5-5 | 低 | 小 | 文件 1.3；遮蔽 1.4 | F |
| ERR12 | 網路斷線和引擎斷線沒有分開，沒有離線偵測 | APP-G2 | 中 | 中 | 1.4 | — |

### 1.3 新增下載流程（DL）

| ID | 項目 | 來源 | 嚴重度 | 工作量 | 版本 | 工作包 |
|---|---|---|---|---|---|---|
| DL1 | 「下載」鈕在畫面外，要捲過 7 個進階分組；解析後「解析」仍是藍色主按鈕；播放清單變成兩層捲動 | APP-C1、APP-D1 | 高 | 中 | 1.3 | A1 |
| DL2 | 「字幕」模式的語言選擇藏在收合的分組裡；摘要的錯誤文字不能點去修正（含播放清單「全選」） | APP-C2、APP-D3 | 高 | 小 | 1.3 | A1、A2 |
| DL3 | 解析中不能取消、沒有進度感，按鈕寬度跳動 | APP-B3、ENG-2-3（前端） | 高 | 小 | 1.3 | A1 |
| DL4 | 長清單／頻道解析：引擎端沒有進度、不能中止、不能分批回傳（NASA 頻道 40.5 秒） | ENG-2-3 | 中 | 中 | 1.4 | — |
| DL5 | 剪貼簿自動貼上會蓋掉正在設定的影片，選好的選項被清掉；提示 3.5 秒就消失、不能復原 | APP-B5 | 中 | 小 | 1.3 | A1 |
| DL6 | 少了 `https://` 就被拒；不接受只有 11 碼的影片 ID | APP-B2 | 中 | 小 | 1.3 | A1 |
| DL7 | 開啟後焦點不在網址欄，不能直接 Ctrl+V＋Enter | APP-A2 | 中 | 小 | 1.3 | A1、C1 |
| DL8 | 沒有任何快捷鍵；不支援把網址或 .txt 拖進視窗 | APP-B6、FEAT-1-4 | 中 | 小 | 1.3 | C1、A1 |
| DL9 | 空狀態只有一條輸入框，沒有說明支援什麼、怎麼用 | APP-B1、ONB-3-1 | 中 | 小 | 1.3 | A1 |
| DL10 | 沒有預估檔案大小，「最佳畫質」看不出實際解析度 | APP-C3 | 中 | 中 | 1.4 | — |
| DL11 | 進階選項約 40 個控制項、yt-dlp 術語；檔名範本沒有預覽；設了代理、限速這類長效設定沒有提醒 | APP-C4 | 中 | 中 | 1.4 | — |
| DL12 | 三個「預設值」按鈕名稱類似、範圍不同 | APP-C5 | 中 | 小 | 1.3 | A2、C2 |
| DL13 | 「下載整個清單」開關的文字不能點；切換後會重新解析但畫面沒說 | APP-C6 | 低 | 小 | 1.3 | A1 |
| DL14 | 播放清單範圍語法錯誤時沒有給例子 | APP-D2 | 低 | 小 | 1.3 | A2 |
| DL15 | 窄視窗＋大字時縮圖固定 192×108 擠壓標題；縮圖沒有佔位圖 | APP-H1 | 中 | 小 | 1.3 | A1 |
| DL16 | 直播、預定直播沒有提示；預定直播直接顯示英文錯誤；可以「等待開播後自動錄」 | ENG-2-10、FEAT-1-11 | 低–中 | 小–中 | 1.4 | — |

### 1.4 下載佇列（Q）

| ID | 項目 | 來源 | 嚴重度 | 工作量 | 版本 | 工作包 |
|---|---|---|---|---|---|---|
| Q1 | 已完成只能「在檔案總管中顯示」，不能直接開啟；雙擊沒反應 | APP-E6 | 中 | 小 | 1.3 | B |
| Q2 | 狀態視覺區分不夠（排隊、下載都是藍條；失敗、取消都是橘條） | APP-E7（前半） | 低 | 小 | 1.3 | B |
| Q3 | 佇列列沒有縮圖、格式；沒有「進行中／已完成」分組 | APP-E7（後半） | 低 | 小–中 | 1.4 | — |
| Q4 | 同一部影片可以重複加入，沒有提醒 | APP-E8、FEAT-1-5 | 低 | 小 | 1.4 | 歷史 |
| Q5 | 沒有「暫停全部／繼續全部／全部重試」 | APP-E1、ENG-2-4、FEAT-1-9、FEAT-1-10 | 中 | 小 | 1.3 | E1、B、T |
| Q6 | 排隊中的工作不知道為什麼沒動（同時只跑 3 個） | ENG-2-8 | 低 | 小 | 1.3 | E1、B |
| Q7 | `/api/jobs` 每次輪詢都重新掃描所有工作資料夾（1000 個工作 1.35 秒、每 0.7 秒一次） | ENG-4-1、FEAT-0-C | 中 | 小 | 快取 1.3；分頁 1.4 | E1 |
| Q8 | 每個工作存在 12 碼亂碼子資料夾；失敗的工作留下空資料夾 | ENG-2-6、FEAT-0-A | 中 | 中 | 1.4 | 工作紀錄重構 |

### 1.5 設定與外觀（SET）

| ID | 項目 | 來源 | 嚴重度 | 工作量 | 版本 | 工作包 |
|---|---|---|---|---|---|---|
| SET1 | App 沒有「有新版」提示，使用者會一直停在舊版 | ONB-4-1、APP-F5 | 高 | 中 | 1.3 | C2 |
| SET2 | 更新 yt-dlp 成功後 App 直接重啟，沒先詢問 | APP-F5（後半） | 低 | 小 | 1.3 | C2 |
| SET3 | Cookie 設定分散在設定頁和進階選項兩處 | APP-F1 | 中 | 中 | 1.4 | — |
| SET4 | 沒設定 Cookie 時顯示紅字「無法檢查」（應為「未設定」）；Cookie 過期要等下載失敗才知道 | APP-F2 | 中 | 小 | 文案 1.3；每日自動檢查 1.4 | C2 |
| SET5 | App 內不能刪除 cookies.txt；解除安裝也不會刪 | ONB-2-4 | 中（隱私） | 小 | 1.3 | C2、F |
| SET6 | 用環境變數鎖定下載資料夾時，「變更…」還能按 | APP-F3 | 低 | 小 | 1.3 | C2 |
| SET7 | 設定頁很長、沒有分區導覽 | APP-F4 | 低 | 中 | 1.4 | — |
| SET8 | 同時下載數只能用環境變數改 | ENG-2-8、FEAT-1-9 | 低–中 | 小 | 1.3 | E1、C2 |
| SET9 | 視窗大小、位置、目前頁面不會記住 | APP-H3 | 低 | 小 | 1.3 | C1 |
| SET10 | 淺色模式的次要文字對比約 3.3:1，低於 AA | APP-H4 | 低 | 小 | 1.3 | C1 |
| SET11 | 使用聲明對話框文字太密；完整聲明要上網才看得到 | APP-A1 | 低 | 小 | 1.3 | C1 |
| SET12 | 文字大小只有三段、不跟系統；自己畫的元件不跟字級變大 | APP-H2 | 低 | 中 | 1.4 | — |

### 1.6 無障礙（A11Y）

| ID | 項目 | 來源 | 嚴重度 | 工作量 | 版本 | 工作包 |
|---|---|---|---|---|---|---|
| A11Y1 | 22 個開關、7 個分組標題沒有無障礙名稱；表單標籤沒有和控制項關聯（全視窗 accessibleName 是 0 個） | APP-I1 | 高 | 中 | 1.3 | A2、C1、D |
| A11Y2 | 側邊欄、分段控制只能 Tab 到選中的那顆；QScrollArea 是看不見的 Tab 停留點；焦點環太淡 | APP-I2 | 中 | 小 | 1.3 | C1、A2、D |

### 1.7 效能與打包（PERF）

| ID | 項目 | 來源 | 嚴重度 | 工作量 | 版本 | 工作包 |
|---|---|---|---|---|---|---|
| PERF1 | `/api/meta` 同步查 PyPI，網路被擋時要 15 秒，設定頁和引擎檢查都要等 | ENG-1-1 | 中 | 小 | 1.3 | E1 |
| PERF2 | `_port_in_use` 每次啟動白等 0.2 秒 | ENG-1-2 | 低 | 小 | 1.4 | — |
| PERF3 | 視窗要等 yt-dlp、Flask 載入完才出現（可以先開視窗） | ENG-1-3 | 低–中 | 中 | 1.4 | — |
| PERF4 | 播放清單縮圖抓最大張、快取沒上限（5560 部約 320 MB） | ENG-4-3 | 低 | 小 | 1.4 | — |
| PERF5 | 安裝檔 374 MB，其中 ffmpeg＋deno 佔 75%；可換精簡版 ffmpeg | ENG-1-4 | 低 | 中 | 1.4 | — |
| PERF6 | 舊工作只保留摘要、歷史保留期限 | ENG-4-4 | 低 | 小 | 1.4（和歷史一起做） | — |
| — | 維持 onedir 打包，**不要**改成單檔 | ENG-1-4 | 資訊 | — | 不做 | — |

### 1.8 安裝、發布、授權與文件（ONB）

| ID | 項目 | 來源 | 嚴重度 | 工作量 | 版本 | 工作包 |
|---|---|---|---|---|---|---|
| ONB1 | GitHub 首頁先看到開發者文件，沒有下載表和截圖；repo 的 description、homepage、topics 都是空的 | ONB-1-1 | 中 | 小 | 1.3 | F（repo 設定由主 session 執行） |
| ONB2 | Release 說明先講更新內容，沒寫該下載哪個檔、檔案大小、系統需求；容易誤點 Source code | ONB-1-2 | 中 | 小 | 1.3 | F |
| ONB3 | CHANGELOG 開頭是寫給維護者的說明和空的「未發布」段落 | ONB-1-3 | 低 | 小 | 1.3 | F |
| ONB4 | Release 沒有 SHA-256 校驗值 | ONB-1-4 | 低 | 小 | 1.3 | F |
| ONB5 | Windows：SmartScreen「未知的發行者」、瀏覽器「通常不會下載此檔案」、防毒誤判隔離，文件沒教完整（**已決定不簽章**，文件要一步一步教放行） | ONB-2-1 | 高 | 小 | 1.3 | F、F-EN |
| ONB6 | macOS：「已損毀」說法、macOS 15 必須進系統設定的順序，三份文件不一致（**已決定不公證**，文件要一步一步教放行）；dmg 沒有「拖到應用程式」背景圖 | ONB-2-2 | 高 | 小（文件）／中（dmg） | 文件 1.3；dmg 背景 1.4 | F、F-EN |
| ONB7 | 只有 Apple 晶片 dmg，文件沒寫 Intel Mac 不支援（已決定不出 Intel 版） | ONB-2-3 | 中 | 小 | 1.3 | F |
| ONB8 | 解除安裝不會詢問是否刪除設定與 cookies.txt，文件沒寫殘留位置 | ONB-2-4 | 中（隱私） | 小–中 | 1.3 | F |
| ONB9 | 安裝精靈只有中文 | ONB-2-5 | 低 | 小 | 1.3 | F |
| ONB10 | macOS「區域網路」權限提示沒說明（要實機確認會不會跳） | ONB-2-6 | 低 | 小 | 1.4 | — |
| ONB11 | 文件沒提醒「更新前先等下載完成，或之後按繼續下載」 | ONB-4-3 | 低 | 小 | 1.3 | F |
| ONB12 | GitHub Pages 是 legacy 分支發布，整個 repo（含 `build_app.py`）都被公開成網站，和 `pages.yml` 互相覆蓋（已決定改成 GitHub Actions） | ONB-6-1 | 中 | 小 | 立刻 | 主 session（GitHub 設定） |
| ONB13 | 網頁版和 USER_GUIDE 的安裝說明不一致；網頁版沒連到 USER_GUIDE | ONB-6-2 | 低 | 小 | 1.3 | F |
| ONB14 | 網頁版定位不清楚；已決定停止加新功能，Pages 首頁改成產品介紹＋下載頁 | ONB-6-3 | 中 | 中 | 1.4 | — |
| ONB15 | 沒有 LICENSE，和 `DISCLAIMER.md:5`、README 的「開源」說法矛盾（已決定用 MIT） | ONB-七 | 中 | 小 | 1.3 | F |
| ONB16 | 沒有英文版使用說明（英文介面上線後必須有） | 新增（配合 F13） | 中 | 中 | 1.3 | F-EN |

### 1.9 新功能（FEAT）

| ID | 功能 | 來源 | 價值 | 工作量 | 版本 | 工作包 |
|---|---|---|---|---|---|---|
| F1 | 批次貼上多個網址／匯入 .txt | FEAT-1-1 | 高 | 小–中 | 1.3 | A1 |
| F2 | 下載完成／失敗的系統通知 | FEAT-1-2、APP-E9 | 高 | 小 | 1.3 | B、T、C1 |
| F3 | 系統匣常駐、關閉視窗後繼續下載 | FEAT-1-3 | 中高 | 中 | **1.3** | T、C1、C2 |
| F4 | 拖放網址／文字檔（＝DL8） | FEAT-1-4 | 中 | 小 | 1.3 | C1、A1 |
| F5 | 下載歷史、搜尋、「已經下載過」提醒 | FEAT-1-5 | 高 | 中 | 1.4 | — |
| F6 | 輸出資料夾規則（自動分類，取代亂碼資料夾） | FEAT-1-6、ENG-2-6 | 高 | 中 | 1.4 | — |
| F7 | `ytdl://` 連結＋書籤小工具＋單一實例機制 | FEAT-1-7 | 中高 | 中 | **1.3** | T、C1、F、F-EN |
| F8 | 頻道／播放清單追蹤（先做只通知版） | FEAT-1-8 | 高（族群集中） | 大 | 1.5 | — |
| F9a | 同時下載數設定、暫停／繼續全部（＝SET8、Q5） | FEAT-1-9 | 中 | 小 | 1.3 | E1、B、C2 |
| F9b | 佇列全部完成後睡眠／關機 | FEAT-1-9 | 中 | 小 | 1.4 | — |
| F10 | 指定時段下載 | FEAT-1-10 | 中 | 中 | 1.5 | — |
| F11 | 等待首播／預定直播（＝DL16） | FEAT-1-11 | 中 | 小–中 | 1.4 | — |
| F12 | 字幕燒錄（硬字幕） | FEAT-1-12 | 中 | 中 | 1.5 | — |
| F13 | 英文介面（跟隨系統／中文／English）＋英文使用說明 | FEAT-1-13 | 中 | 大 | **1.3** | I0、E2、所有介面包、I2、F-EN |
| F14 | 可攜版 | FEAT-1-14 | 中低 | 小–中 | 1.5 | — |
| F15 | App 內搜尋影片 | FEAT-1-15 | 中 | 小–中 | 不做（已決定） | — |
| F16 | 本機檔案轉檔／剪輯工具 | FEAT-1-16 | 中 | 中 | 暫不做 | — |
| F17 | Podcast 訂閱源 | FEAT-1-17 | 低–中 | 大 | 不做 | — |
| F18 | 語音轉字幕（Whisper） | FEAT-1-18 | 中 | 大 | 暫不做 | — |
| F19 | 設定匯出／匯入 | FEAT-1-19 | 低–中 | 小 | 1.5 | — |

---

## 2. 抽查：對照程式碼確認高嚴重度問題

抽查 12 項，全部和報告描述一致；只有行號有 ±1 的差異（以下用實際行號）。基準是 `main` @ 68ae7d0。

| ID | 報告描述 | 程式碼位置 | 結果 |
|---|---|---|---|
| R1 | 磁碟不存在時 `import server` 就失敗 | `server.py:83` `d.mkdir(parents=True, exist_ok=True)` 沒有 try；`server.py:95` 在模組載入時就呼叫 `get_download_dir()` | ✅ 一致。資料夾建立失敗會直接丟出 `FileNotFoundError`，App 無法啟動 |
| R2 | 有任何檔案就算「完成（有警告）」 | `server.py:996-998` `elif job.files():` → `"done", "完成（有警告）"`；`Job.files()`（`server.py:709-719`）只排除 `.tmp` 子資料夾與暫存副檔名，縮圖、字幕都算；`server.py:589`、`server.py:599` 字幕與縮圖轉換器都設 `"when": "before_dl"`，會在影片下載前就寫出檔案 | ✅ 一致 |
| R3 | 播放清單沒設 `ignoreerrors` | `build_opts`（`server.py:465` 起）整份檔案搜尋不到 `ignoreerrors` | ✅ 程式碼一致；「整個清單停住」是依 yt-dlp 預設行為推論，實作時要先寫測試重現 |
| R4 | 取消後不能續傳、暫存檔被刪 | 提示文字 `native_app.py:1109`「已下載的部分會保留，可以再繼續」；「繼續下載」只在 `st == "error"` 顯示（`native_app.py:1110`）；引擎 `server.py:1080` 非 error 一律回 409；`server.py:1006-1007` 狀態不是 error 就 `rmtree(job.dir / ".tmp")` | ✅ 一致 |
| R5 | 刪除是 rmtree 整個工作資料夾 | `server.py:1102` `shutil.rmtree(job.dir, ignore_errors=True)` | ✅ 一致 |
| R6 | 完成時警告被丟掉 | `native_app.py:1095-1097` done 狀態只組「已完成 · N 個檔案 · 大小」，沒讀 `job.error` | ✅ 一致 |
| R7 | 取消排隊工作沒存檔 | `server.py:1067-1072` `api_cancel` 沒有 `job.save()`；`server.py:873-875` `run_job` 提早 return 也沒存 | ✅ 一致 |
| R8 | settings.json 非原子寫入 | `server.py:1212` 直接 `write_text`；對照 job.json 用 tmp＋replace（`server.py:755`） | ✅ 一致 |
| ERR1 | 沒有錯誤翻譯層 | `server.py:1017-1019` `_clean_err` 只去掉 ANSI 色碼和 `ERROR:`；`native_app.py:900` `f"無法解析：{msg}"`；`native_app.py:1099` 直接顯示 `job.get("error")` | ✅ 一致 |
| DL3 | 解析不限時間、不能取消 | `native_app.py:892` `timeout_ms=0`（報告寫 891） | ✅ 一致 |
| DL8、A11Y1、SET9、F2、SET1、F13 | 沒有拖放、快捷鍵、無障礙名稱、記住視窗、系統匣、查 GitHub Releases、多語系 | 在 `native_app.py`、`native_options.py`、`native_playlist.py` 搜尋 `setAcceptDrops`、`QShortcut`、`setAccessibleName`、`saveGeometry`、`QSystemTrayIcon`、`api.github`、`tr(`、`translate(` 全部沒有結果。三個介面檔約有 375 行含中文字串，`server.py` 約 107 行 | ✅ 一致 |
| SET8 | 同時下載數固定 | `server.py:783` `MAX_PARALLEL = threading.Semaphore(int(os.environ.get("YTDL_PARALLEL", "3")))`，Semaphore 不能動態調整 | ✅ 一致；改成可調要換掉 Semaphore |

另外發現一件報告裡沒標出的事：ENG-3-2 的對照表把「地區限制」的建議訊息寫成「可以在進階選項設定 Proxy 或地區」。這等於教使用者規避地區限制，和 `DISCLAIMER.md` 第 3 點衝突。實作錯誤訊息時**不要**這樣寫，改成「這部影片在你所在的地區無法觀看」（見[附錄 A](#附錄-a錯誤代碼對照表e2f-與-f-en-共用)）。

---

## 3. 優先順序

### 3.1 排序方法

分數＝使用者影響（高 3／中 2／低 1）×發生機率（常見 3／偶爾 2／少見 1）÷工作量（小 1／中 2／大 4），再依風險調整：

- **必修**：會讓使用者誤以為成功、遺失資料，或 App 打不開的項目，不論分數都排進 v1.3.0。
- **使用者指定**：系統匣常駐、`ytdl://`、英文介面依使用者決定排進 v1.3.0。
- **加分**：只動一個檔案、幾乎不會影響其他功能的項目往前排。
- **減分**：要改核心資料結構（工作資料夾、佇列排程）的項目往後排，等測試補齊再做。

### 3.2 必修的可靠度問題（v1.3.0 一定要做）

| 順位 | ID | 問題 | 為什麼必修 |
|---|---|---|---|
| 1 | R2 | 只有縮圖／字幕就判成完成 | 使用者以為下載好了，其實只有一張 jpg，而且沒有續傳按鈕 |
| 2 | R1 | 磁碟不存在時 App 打不開 | App 完全無法使用，也沒有 UI 可以改設定 |
| 3 | R3 | 播放清單一部失敗就停止，卻顯示完成 | 少了大量影片卻顯示完成，很難發現 |
| 4 | R4 | 取消會丟掉進度，提示卻說可以繼續 | 文字和行為相反，使用者照著做就遺失進度 |
| 5 | R5 | 刪除一定永久刪檔 | 只想整理清單的人會誤刪影片，救不回來 |
| 6 | ERR6 | 500 錯誤誤報連接埠被佔用 | 原因說錯，使用者會往錯的方向處理 |
| 7 | R8 | settings.json 寫壞後悄悄換資料夾 | 下載跑到別的地方，使用者找不到檔案 |
| 8 | R11 | 後處理空間不足被當成一般失敗（或完成） | 會和 R2 疊加，變成「完成」但檔案壞掉 |
| 9 | R7 | 取消排隊工作沒存檔 | 小，但會讓已取消的工作在重開後「復活」 |

### 3.3 v1.3.0 其他項目的排序（影響 ÷ 工作量）

| 順位 | 項目 | ID | 影響 | 工作量 |
|---|---|---|---|---|
| 1 | 錯誤翻譯層＋下一步按鈕＋FAQ 錨點 | ERR1、ERR2、ERR3、ERR9 | 高 | 中 |
| 2 | 引擎離線 banner 改成看得懂的說明＋重試；錯誤 toast 不自動消失 | ERR7、ERR8 | 高 | 小 |
| 3 | 底部固定動作列；解析可取消；字幕模式自動展開 | DL1、DL3、DL2 | 高 | 中 |
| 4 | SmartScreen／Gatekeeper 放行教學（取代簽章） | ONB5、ONB6 | 高 | 小 |
| 5 | `/api/meta` 不再同步查 PyPI | PERF1 | 中 | 小 |
| 6 | 斷線自動重試＋全部重試；暫停／繼續全部 | R10、Q5 | 中 | 小 |
| 7 | 看得到工作紀錄、複製錯誤、開啟紀錄資料夾、回報問題 | ERR4 | 中 | 小 |
| 8 | App 新版提示 | SET1 | 高 | 中 |
| 9 | 下載完成通知、系統匣常駐 | F2、F3 | 高 | 中 |
| 10 | 無障礙名稱與鍵盤操作 | A11Y1、A11Y2 | 高（對受影響的人） | 中 |
| 11 | 自動貼上不覆蓋、補 https、焦點、快捷鍵、拖放 | DL5–DL8 | 中 | 小 |
| 12 | 批次貼上、`ytdl://` | F1、F7 | 中高 | 中 |
| 13 | 英文介面＋英文使用說明 | F13、ONB16 | 中（擴大使用者） | 大 |
| 14 | `/api/jobs` 快取 | Q7 | 中（工作多的人很明顯） | 小 |
| 15 | 文件：下載表、Release 說明、Intel Mac、SHA256、issue 範本、LICENSE | ONB1–ONB4、ONB7–ONB9、ONB15、ERR10 | 中 | 小 |
| 16 | 其餘小項（開啟檔案、狀態圖示、同時下載數、視窗記憶、對比、文案） | Q1、Q2、Q6、SET2–SET11 | 低–中 | 小 |

---

## 4. 分版本規劃

### 4.1 v1.3.0「可靠、看得懂、找得到，走向國際」

**目標**：使用者看到的狀態都是真的、看得懂下一步、主要按鈕找得到；App 可以在系統匣常駐、從瀏覽器一鍵送網址進來；介面和使用說明都有英文版。不動工作資料夾結構。

**項目清單**

- 可靠度（必修）：R1、R2、R3、R4、R5、R6、R7、R8、R10、R11、R13、R14
- 錯誤與求助：ERR1–ERR10、ERR11（文件提醒）
- 新增下載：DL1、DL2、DL3、DL5、DL6、DL7、DL8、DL9、DL12、DL13、DL14、DL15
- 佇列：Q1、Q2、Q5、Q6、Q7（快取）
- 設定：SET1、SET2、SET4（文案）、SET5、SET6、SET8、SET9、SET10、SET11
- 無障礙：A11Y1、A11Y2
- 效能：PERF1
- 文件、發布與授權：ONB1–ONB9、ONB11、ONB13、ONB15、ONB16；ONB12（GitHub 設定）
- 新功能：F1 批次貼上、F2 完成通知、F3 系統匣常駐、F4 拖放、F7 `ytdl://`＋單一實例、F9a 同時下載數＋暫停／繼續全部、F13 英文介面

**預估工作量**：約 46 人日，日曆時間約 12 個工作天。比原本的規劃（30 人日、8–9 天）多了：英文介面約 9 人日（I0、I2、E2 的雙語訊息，加上各介面包改用翻譯函式），英文文件約 2.5 人日，系統匣＋`ytdl://`＋單一實例約 4.5 人日。

| 期間 | 批次 | 說明 |
|---|---|---|
| 第 1–1.5 天 | 第一批 | WP-0、I0 最快完成並合併；E1、E2、F、T 繼續做 |
| 第 2–6.5 天 | 第二批 | A1、A2、B、C1、C2 平行；F 合併後 F-EN 開工；E1 第二階段接上 E2 |
| 第 7–10 天 | 第三批 | I2 英文翻譯、D 無障礙與字串收尾 |
| 第 10–12 天 | 第四批 | INT 整合 QA、打包實機測試、發布 |

**驗收標準**（全部要有自動測試或可重複的手動步驟）

1. **磁碟不存在**：`YTDL_DOWNLOAD_DIR=Z:\nodrive\yt`（或 settings.json 指到不存在的磁碟）時 App 能開啟，顯示「儲存位置 Z:\nodrive\yt 目前無法存取」，按「更換位置」選新資料夾後不用重開就能下載。執行中拔掉磁碟時顯示同一個提示，不出現「連接埠被佔用」。
2. **失敗不會變完成**：用模擬的 yt-dlp（測試替身）在「已寫出縮圖和字幕、影片下載到一半丟出 403」的情況下，工作狀態是 `error`，有「繼續下載」，`.tmp` 保留。
3. **播放清單部分失敗**：清單裡有一部私人影片時，其他影片都下載完成；工作顯示「完成 4/5，1 部無法下載」，可以展開看是哪一部、什麼原因，並能「重試失敗的項目」。
4. **暫停／繼續**：下載中按「暫停」後狀態是 `paused`，`.part` 保留；按「繼續」從原本的位元組位置接著下載（測試檢查 `partial_bytes` 沒有歸零）。
5. **刪除**：預設「從清單移除」只刪工作紀錄，影片檔還在；「連同檔案刪除」把檔案移到資源回收筒（macOS 是垃圾桶）。「清除已完成」一次移除所有已完成工作，不動檔案。
6. **錯誤訊息**：[附錄 A](#附錄-a錯誤代碼對照表e2f-與-f-en-共用) 每一個錯誤代碼都有測試案例（輸入 yt-dlp 原文 → 輸出代碼與訊息），中文和英文訊息都要有。顯示給使用者的訊息裡不能出現 `--`（命令列參數）、`github.com`、`please report`；原文完整保留在「詳細資訊」裡。每個代碼在 USER_GUIDE.md 和 USER_GUIDE.en.md 都有對應的錨點（自動測試比對）。
7. **效能**：1000 個已完成工作時 `/api/jobs` 中位數 < 150 ms；網路被擋時 `/api/meta` < 1 秒；`engine.log` 不再出現 `GET /api/jobs` 存取紀錄，工作失敗時會寫入錯誤原因和最後 30 行紀錄。
8. **主要動作看得到**：1000×700 視窗下，單支影片、字幕模式、播放清單模式都不用捲動就看得到「下載」鈕；切到字幕模式時字幕分組自動展開。解析中按「取消」或 Esc，1 秒內恢復可輸入狀態。
9. **無障礙**：自動測試走過所有頁面，每個可以取得焦點的元件都有文字或 accessibleName；QScrollArea 不吃 Tab；側邊欄和分段控制可以用方向鍵切換。
10. **小功能**：貼上 10 行網址（含 2 行無效）時列出 8 個可勾選項目並一次加入佇列；拖放網址或 .txt 到視窗有效；App 不在前景時，工作完成或失敗會跳系統通知；設定頁可以把同時下載數改成 1–5，立即生效；佇列有「暫停全部／繼續全部／全部重試」。
11. **系統匣**：設定「關閉視窗時：縮到系統匣」後關閉視窗，下載繼續；系統匣選單有「顯示視窗、暫停全部、繼續全部、結束」，滑鼠移上去看得到進度；選「結束」時若有下載進行中會先詢問。預設值維持「關閉視窗時結束 App（下載中會詢問）」。
12. **單一實例與 `ytdl://`**：App 已開著時再開一次，會喚醒原本的視窗，不會出現第二個引擎；開啟 `ytdl://add?url=https%3A%2F%2Fwww.youtube.com%2Fwatch%3Fv%3DjNQXAC9IVRw` 時，網址填入「新增下載」並開始解析，**不會自動開始下載**；`ytdl://add?url=file:///C:/…`、`javascript:` 等非 http/https 網址一律拒絕並提示；Windows 解除安裝後登錄機碼被清除；USER_GUIDE 有書籤小工具的安裝步驟。
13. **英文介面**：設定頁「語言」可以選「跟隨系統／中文（繁體）／English」，切換後提示重新啟動；英文作業系統選「跟隨系統」時顯示英文。English 模式下走過主要流程（貼網址、解析、下載、佇列、設定、錯誤訊息、系統匣選單、通知、安裝精靈）都沒有殘留中文；自動測試確認翻譯檔沒有未翻譯的項目；英文字串較長時版面不破（720×520 最小視窗截圖檢查）。「使用說明」和錯誤訊息的 FAQ 連結依語言開 USER_GUIDE.md 或 USER_GUIDE.en.md。
14. **授權與文件**：repo 根目錄有 `LICENSE`（MIT，著作權人 Archer8685）和 `THIRD_PARTY_NOTICES.md`，安裝檔裡也有；README 不再寫「未附開源授權檔」；SmartScreen 和 Gatekeeper 的放行步驟在 USER_GUIDE（中英）、Release 說明、index.html 三處一致，不再提簽章計畫。
15. **發布**：Release 頁最上面是「該下載哪個檔」表格（含大小、系統需求、Intel Mac 不支援）；附上 `SHA256SUMS.txt`；`CHANGELOG.md` 有 v1.3.0 段落；`review-qa-loop` 全部乾淨、`pytest` 全綠、`ui-screenshots` workflow 中英文截圖都正常。

### 4.2 v1.4.0「整理與管理」

**目標**：解決亂碼資料夾和「我之前載過嗎、存在哪？」的問題。

**項目清單**

- **工作紀錄重構（核心，先做）**：工作紀錄從 `<下載資料夾>/<id>/job.json` 移到 App 資料夾（`ROOT/jobs/<id>.json`）。下載中仍用工作專屬的暫存區，完成後把成品搬到使用者看得到的位置；同名檔案自動加 ` (2)`；要讀得懂 v1.3 以前的舊工作資料夾。順便解決 R9（記住所有用過的下載位置）和 Q8。
- F6 輸出資料夾規則（不分類／依上傳者／依播放清單／依日期／依模式）
- F5 下載歷史（SQLite）、搜尋、Q4「已經下載過」提醒；Q7 第二階段：佇列只顯示近期工作、分頁；PERF6
- DL4 長清單非同步解析：顯示進度、引擎端可取消、先回傳前 N 部
- DL16／F11 直播與預定直播提示、等待開播自動錄
- DL10 預估檔案大小；DL11 進階選項分成「常用／專家」、檔名預覽、長效設定提醒
- SET3 Cookie 設定集中到「帳號與 Cookie」區；SET4 每天自動檢查是否過期；SET7 設定頁分區導覽；SET12 字級跟系統
- ERR12 網路離線偵測、恢復後自動繼續；ERR11 紀錄檔遮蔽家目錄
- Q3 佇列縮圖、格式、分組；F9b 全部完成後睡眠／關機
- ONB14 Pages 首頁改成產品介紹＋下載頁（網頁版操作介面停止加新功能）
- R12 關閉時讓 ffmpeg 一起結束；PERF2 啟動時的連接埠檢查；PERF3 先開視窗再載入引擎；PERF4 縮圖快取上限；PERF5 精簡版 ffmpeg；ONB6 dmg 背景圖；ONB10 macOS 區域網路權限 FAQ

**預估工作量**：約 35 人日。工作紀錄重構約 5 人日，必須先做完並合併，其他項目才能平行，日曆時間約 3 週。新增的介面字串照 v1.3.0 的多語系規範寫，並同時補英文翻譯。

**驗收標準**

1. 新下載的檔案直接出現在 `<下載資料夾>`（或依規則的子資料夾），看不到 12 碼資料夾；v1.3 留下的舊工作仍可續傳、刪除、在檔案總管中顯示。
2. 更換下載位置後，舊位置的工作仍在佇列；舊位置的磁碟拔掉時顯示「N 個工作所在的磁碟目前無法存取」。
3. 歷史頁可以用標題、上傳者搜尋；貼上下載過的網址時提示「你在 11/3 下載過（檔案仍在／已不存在）」。
4. 3000 筆歷史時 `/api/jobs` 中位數仍 < 150 ms。
5. 解析 5000 部的頻道時每秒更新「已讀取 N 部」，按取消後引擎停止解析（CPU 回到閒置）。
6. Pages 首頁是產品介紹與下載頁，`build_app.py` 這類原始碼不再能從網站讀到。

### 4.3 v1.5.0 以後

| 版本 | 主題 | 項目 |
|---|---|---|
| v1.5.0 | 自動化 | F8 頻道／播放清單追蹤（先做「只通知」，數量上限 50、只抓加入追蹤之後的新影片；之後再看是否開放自動下載）、F10 指定時段下載、F19 設定匯出／匯入（不含 cookies）、F14 可攜版 |
| 再評估 | — | F12 字幕燒錄、F16 本機轉檔、F18 語音轉字幕（只考慮做成選配外掛）、其他語言的介面（v1.3.0 的翻譯機制完成後，加語言只要新增翻譯檔） |

---

## 5. v1.3.0 工作包（可平行）

### 5.1 檔案所有權與開工批次

原則：**一個檔案只屬於一個工作包**。`native_app.py` 有 2079 行，裡面有四個頁面，幾乎每個工作包都要改它，所以先用 WP-0 把它拆開，之後每個頁面一個檔案、一個工作包。英文介面的做法見[第 5.3 節](#53-英文介面怎麼做才不會互相衝突)。

| 批次 | 工作包 | 負責的檔案（只有這個工作包可以改） | 工作量 | 開工條件 |
|---|---|---|---|---|
| **第一批** | **WP-0 拆檔** | `native_app.py` → 拆出 `native_common.py`、`native_download.py`、`native_queue.py`、`native_settings.py`；`tests/test_native_app.py` 拆成對應的測試檔；`tools/ui_screenshot.py`（若 import 路徑要改） | 1 人日 | 立刻 |
| **第一批** | **I0 多語系基礎** | 新增 `i18n.py`、`docs/I18N.md`（字串規範）、`i18n/`（翻譯檔資料夾，先放空的 `yt_dl_en.ts`）、新增 `tools/i18n_update.py`（抽字串、編譯 .qm）、新增 `tests/test_i18n.py` | 1.5 人日 | 立刻 |
| **第一批** | **E1 引擎可靠度** | `server.py`、`app_boot.py`、`ytdlp_update.py`、`requirements.txt`、`requirements-app.txt`、`pyproject.toml`、`tests/test_server.py`、`tests/test_app_boot.py`、新增 `tests/test_engine_reliability.py` | 5.5 人日 | 立刻（第二階段等 E2 合併） |
| **第一批** | **E2 引擎訊息** | 新增 `engine_messages.py`（錯誤分類＋處理階段文字，中英雙語）、新增 `tests/test_engine_messages.py` | 3 人日 | 立刻 |
| **第一批** | **F 文件、發布與授權** | `README.md`、`USER_GUIDE.md`、`CHANGELOG.md`（只改開頭格式）、`index.html`、新增 `LICENSE`、新增 `THIRD_PARTY_NOTICES.md`、`tools/release_notes.py`、`tests/test_release_notes.py`、`.github/workflows/release.yml`、新增 `.github/ISSUE_TEMPLATE/*`、`build_app.py` | 3.5 人日 | 立刻 |
| **第一批** | **T 系統整合** | 新增 `single_instance.py`、`url_handoff.py`、`native_tray.py`，以及對應的 `tests/test_single_instance.py`、`tests/test_url_handoff.py`、`tests/test_native_tray.py` | 3.5 人日 | 立刻（字串要照 I0 規範，I0 合併前先用 `QCoreApplication.translate` 直接寫） |
| 第二批 | **A1 新增下載頁** | `native_download.py`、`tests/test_native_download.py` | 4.5 人日 | WP-0、I0 合併後 |
| 第二批 | **A2 進階選項與播放清單** | `native_options.py`、`native_playlist.py`、`tests/test_native_options.py`、`tests/test_native_playlist.py` | 3 人日 | I0 合併後（和 A1 一起開工，方便對齊介面） |
| 第二批 | **B 佇列頁** | `native_queue.py`、`tests/test_native_queue.py` | 3.5 人日 | WP-0、I0 合併後 |
| 第二批 | **C1 主視窗與共用元件** | `native_app.py`（拆完後剩 MainWindow、Toolbar、main、主題）、`native_common.py`、`tests/test_native_app.py`、`tests/test_native_common.py`、`assets/` 下新增的圖示 | 3.5 人日 | WP-0、I0 合併後；接系統匣要等 T 合併 |
| 第二批 | **C2 設定頁與 App 更新** | `native_settings.py`、新增 `app_update.py`、`tests/test_native_settings.py`、新增 `tests/test_app_update.py` | 3.5 人日 | WP-0、I0 合併後 |
| 第二批 | **F-EN 英文文件** | 新增 `USER_GUIDE.en.md`；`README.md` 的英文段落（F 合併後 README 交給 F-EN） | 2.5 人日 | F 合併後 |
| 第三批 | **I2 英文翻譯** | `i18n/` 下的翻譯檔（`yt_dl_en.ts`、編譯出的 `.qm`）；`docs/I18N.md` 的用語表 | 3 人日 | A1、A2、B、C1、C2、T 都合併後 |
| 第三批 | **D 無障礙與字串收尾** | 新增 `tests/test_accessibility.py`、新增 `tests/test_no_untranslated.py`；允許小幅修正任何 native 檔案（此時其他介面包都已合併） | 2 人日 | 同上，和 I2 同時做 |
| 第四批 | **INT 整合發布** | `VERSION`、`CHANGELOG.md`（v1.3.0 段落）；整合 QA、發布 | 2 人日 | 全部合併後 |

合計約 46 人日。這一版沒有工作包需要改 `DISCLAIMER.md`（英文段落已經有了）、`.github/workflows/pages.yml`、`.github/workflows/ui-screenshots.yml`（若要加英文截圖，交給 F 一起改，屬於 F 的範圍）。

**不屬於任何工作包、由主 session 執行的事**：GitHub Pages 來源改成 GitHub Actions（`gh api -X PUT repos/Archer8685/yt-dl/pages -f build_type=workflow`，或在 Settings → Pages → Source 選 GitHub Actions）；用 `gh repo edit` 設定 description、homepage、topics（文字由 F 準備）。這兩件是對外公開的設定，使用者已經同意方向，執行前再確認一次文字。

### 5.2 依賴關係與開工順序

```text
第一批（立刻同時開工）
  WP-0 拆檔 ─┐   I0 多語系基礎 ─┐   E2 引擎訊息 ──► E1 第二階段
             │                 │   E1 引擎可靠度 ────────────────┐
             │                 │   F 文件發布授權 ──┐             │
             │                 │   T 系統整合 ──────┼─────┐       │
             ▼                 ▼                    ▼     │       │
第二批   A1 · A2 · B · C1 · C2（照第 5.5 節介面約定）  F-EN │       │
             │                                    │     │       │
             └──────────────┬─────────────────────┴─────┴───────┘
                            ▼
第三批          I2 英文翻譯  ＋  D 無障礙與字串收尾（同時做）
                            ▼
第四批                INT 整合發布
```

- **WP-0、I0 → 第二批的五個介面包**：拆檔和字串規範都要先合併，否則所有人都在改同一個 2000 行的檔案，或是各自發明翻譯寫法。這兩包都只要 1–1.5 天，要最優先合併。
- **E2 → E1 第二階段**：E1 先做不依賴訊息模組的部分；E2 合併後，E1 再把 `/api/info`、`run_job`、Flask 錯誤處理、處理階段文字都接到 `engine_messages.py`。
- **T → C1 的系統匣與單一實例接線**：C1 可以先做其他項目，T 合併後再接 `TrayController` 和 `SingleInstance`。
- **F → F-EN**：英文文件照中文 FAQ 的錨點和內容翻譯，F 合併後才開始；`README.md` 在 F 合併後改由 F-EN 負責。
- **E1 ↔ 介面包**：介面包照[第 5.5 節](#55-介面約定開工前就固定)的 API 約定寫，欄位不存在時要退回舊行為，這樣不用等 E1 合併就能開發和測試。端對端測試在 E1 合併後補做，或交給 INT。
- **第三批**：I2 只改 `i18n/` 下的翻譯檔，D 只改 native 檔案和新測試，兩包可以同時做。D 發現漏掉的字串（沒包翻譯函式）時直接修，並通知 I2 重新抽字串。

### 5.3 英文介面怎麼做才不會互相衝突

英文介面會碰到所有介面檔案。做法是「**先訂規範、各自照規範寫、最後統一翻譯**」：

1. **I0（第一批）訂好規範和工具**，不改任何現有介面檔：
   - `i18n.py`：語言設定（`system`／`zh_TW`／`en`，存在 QSettings）、啟動時安裝 `QTranslator`（App 自己的 `yt_dl_<lang>.qm`，加上 Qt 內建的 `qtbase_<lang>.qm`，讓標準按鈕和對話框也翻譯）、`current_language()`、`guide_url(anchor)`（依語言回傳 USER_GUIDE.md 或 USER_GUIDE.en.md 的網址）。
   - `docs/I18N.md` 字串規範：
     - 原文寫繁體中文，翻譯檔放英文（不用另外把原文改成英文，現有約 375 行字串不必重寫）。
     - Qt 物件裡用 `self.tr("…")`，其他地方用 `QCoreApplication.translate("<模組或類別名>", "…")`。不要自己包一層函式名稱，否則 `pyside6-lupdate` 抽不到字串（若 I0 確認可以用 `-tr-function-alias` 支援短名稱，就寫進規範）。
     - 不在翻譯函式裡用 f-string；變數用 `"{name}"` 佔位，再 `.format(name=…)`；數量用 `%n` 處理單複數。
     - 不把句子拆成好幾段拼接（英文語序不同）；按鈕和選單文字要預留英文約 1.5 倍的寬度，不要寫死寬度。
     - 引擎回傳的文字（錯誤、處理階段）不在 App 端翻譯，由引擎依語言回傳（見第 4 點）。
   - `tools/i18n_update.py`：一個指令跑 `pyside6-lupdate` 抽出所有介面檔的字串到 `i18n/yt_dl_en.ts`，再跑 `pyside6-lrelease` 編譯 `.qm`。
   - `tests/test_i18n.py`：語言設定、`QTranslator` 載入、`guide_url` 的測試。
2. **第二批的每個介面包把自己檔案裡「所有」使用者看得到的字串都改用翻譯函式**，包括原本就有的字串。因為每個檔案只屬於一個工作包，這樣做不會和別人衝突。T 包（`native_tray.py`）也照同一套規範寫。各包**不用寫英文翻譯**，也不要改 `i18n/` 下的檔案。
3. **I2（第三批）統一翻譯**：跑 `tools/i18n_update.py` 抽出全部字串，在 `yt_dl_en.ts` 補英文翻譯，整理 `docs/I18N.md` 的用語表（例如「解析」統一翻成 Analyze、「佇列」翻成 Queue），編譯 `.qm`。D 的 `tests/test_no_untranslated.py` 檢查翻譯檔裡沒有未翻譯的項目，並用簡單的掃描確認介面檔沒有「沒包翻譯函式的中文字串」。
4. **引擎的文字**：E2 的 `engine_messages.py` 用 Python 字典存中英兩種訊息（錯誤分類與處理階段，例如「排隊中」「合併影音軌」）。App 的 `Api`（C1 負責）每個請求都帶 `Accept-Language` 標頭，E1 依標頭選語言。工作物件改存「代碼＋參數」，回傳時才組成文字，所以切換語言後舊工作的訊息也會跟著變。網頁版（`index.html`）不帶標頭，維持中文。
5. **語言切換設定**：C2 在設定頁「外觀」區加「語言：跟隨系統／中文（繁體）／English」，切換後提示重新啟動（不做即時切換，降低複雜度）。
6. **安裝精靈與文件**：F 在 `build_app.py` 的 Inno 腳本加英文語系；並確認 PyInstaller 的 Qt 檔案過濾不會刪掉 `qtbase_en.qm`、`qtbase_zh_TW.qm`，`i18n/*.qm` 也要打包進去（`datas` 用萬用字元，`.qm` 還沒產生時也不會出錯）。F-EN 寫 `USER_GUIDE.en.md`。

**USER_GUIDE 英文版的規劃**：v1.3.0 出 `USER_GUIDE.en.md`，內容和中文版對應：安裝（含 SmartScreen／Gatekeeper 放行步驟）、基本使用、系統匣與 `ytdl://` 書籤小工具、FAQ。FAQ 的錨點和中文版**完全相同**（`err-…`），App 才能用同一個錨點開兩種語言。README 最上方加一行英文介紹和英文下載表，連到英文使用說明。`DISCLAIMER.md` 已經有英文段落，不用另外寫。之後中文 FAQ 有改動時，同一個 PR 要一起改英文版（寫進 `docs/I18N.md` 和 PR 檢查清單）。

### 5.4 各工作包內容

#### WP-0 拆檔（純重構，不改行為）
- 依現在的程式結構拆：`native_app.py:75-712`（主題、格式化工具、`Api`、`form_row`、`Card`、`Segmented`、設定存取、免責聲明）→ `native_common.py`；`DownloadPage`（`native_app.py:713-1018`）→ `native_download.py`；`JobRow`、`QueuePage`（`native_app.py:1019-1256`）→ `native_queue.py`；`SettingsPage`（`native_app.py:1257-1650`）→ `native_settings.py`；`native_app.py` 只留 `Toolbar`、`MainWindow`、`main()` 和啟動相關函式。
- `native_app.py` 保留 re-export（`from native_common import *` 等），讓 `build_app.py`、`tools/ui_screenshot.py`、現有測試的 `import native_app` 不用改。
- 驗收：`pytest` 全綠、`tools/ui_screenshot.py` 截圖和拆檔前一致、PyInstaller 打包能啟動。這個工作包要盡快合併。

#### I0 多語系基礎
- 見[第 5.3 節](#53-英文介面怎麼做才不會互相衝突)第 1 點。另外先用一個小範例（例如一個測試用的 QWidget）跑通「寫 `self.tr` → 抽字串 → 補英文 → 編譯 → 切成 English 後顯示英文」整條流程，確認 PySide6 6.12 的 `pyside6-lupdate` 抽得到 Python 檔案裡的字串。
- 驗收：`tools/i18n_update.py` 能產生 `.ts`、`.qm`；`docs/I18N.md` 寫好規範與範例；不改任何現有介面檔。這個工作包要盡快合併。

#### E1 引擎可靠度
- R1：`get_download_dir()` 建立失敗時不丟例外，回傳路徑＋錯誤狀態；移除 `server.py:95` 模組載入時建立資料夾；`/api/meta` 加 `download_dir_error`；需要下載資料夾的 API 在資料夾不可用時回傳 JSON 錯誤（代碼 `download_dir_unavailable`）。
- ERR6：`@app.errorhandler(Exception)` 一律回傳 JSON（代碼 `engine_internal`），App 不再看到 HTML 500。
- R2：完成判斷改成「有主要媒體檔」（影片／音訊容器副檔名，或從 yt-dlp 的 `MoveFiles` 後處理記下最終檔）；沒有就算 `error`，保留 `.tmp`。
- R3：播放清單模式設 `ignoreerrors: "only_download"`，在 `JobLogger.error` 收集失敗項目（第幾部、標題、代碼、原文），完成時回傳 `failed_items`、`done_count`、`total_count`；`POST /api/jobs/<id>/retry_failed` 只重跑失敗的項目。
- R4：新增 `paused` 狀態：`POST /api/jobs/<id>/pause`（下載中或排隊中都可以），保留 `.tmp`；`resume` 接受 `error` 與 `paused`。`cancel` 保留給「不要了」的情境（會刪暫存）。
- R5：`DELETE /api/jobs/<id>?files=keep|trash`，預設 `keep`（只刪紀錄）；`trash` 用 `send2trash`；`POST /api/jobs/clear` 清除所有已完成工作（不動檔案）。
- R7：`api_cancel` 和 `run_job` 提早 return 都要 `save()`。R8：settings.json 改成 tmp＋`os.replace`。
- R10：網路類錯誤（`TransportError`、`getaddrinfo`、`timed out`、HTTP 5xx／429）即使沒進度也用 5→15→60 秒退避重試 3 次；`POST /api/jobs/pause_all`、`resume_all`、`retry_all`。
- R11：每個後處理步驟開始時和 `watch_pp` 中檢查剩餘空間；不夠時給「合併需要約 X GB，磁碟只剩 Y GB」。
- R13：依下載資料夾長度設定 `trim_file_name`。R14：YouTube 網址至少要有 11 碼 `v=`、`list=`、`/@`、`/shorts/` 等形式。
- PERF1：`/api/meta` 只回傳快取的最新版本（可以是 null），PyPI 查詢放背景；`ytdlp_update.py` 逾時從 15 秒降到 5 秒。
- Q7：工作進入完成狀態時快取 `files()`，刪除、續傳時才更新。
- SET8／Q6：用可調整上限的排程器取代 `threading.Semaphore`；`/api/settings` 加 `parallel`（1–5）；排隊中的工作回傳 `queue_position`。
- ERR4：`app_boot.py` 把 werkzeug 的存取紀錄調到 WARNING；工作失敗時把錯誤和最後 30 行紀錄寫進 `engine.log` 和 job.json；`GET /api/jobs/<id>` 的 log 重開後仍在。
- 第二階段（E2 合併後）：`/api/info` 失敗、`job.error`、`failed_items`、Flask 錯誤處理、處理階段文字全部經過 `engine_messages.py`；依請求的 `Accept-Language`（`en` 開頭用英文，其他用中文）回傳文字；工作物件存代碼與參數（`error_code`、`error_params`、`stage_code`、`stage_params`），在 `to_dict()` 時才組成文字。ERR5 的「設定 → 儲存位置」也在這時改。
- 不要改：`build_app.py`（屬於 F）。新增依賴 `send2trash` 是純 Python 套件，PyInstaller 會自動收進去；若打包測試發現沒收到，請通知 F 加 hiddenimport。

#### E2 引擎訊息（`engine_messages.py`）
- `friendly_error(exc_or_message, lang="zh") -> dict`，回傳格式見[第 5.5 節](#55-介面約定開工前就固定)。用 `isinstance`（`GeoRestrictedError`、`UnsupportedError`、`DownloadError.exc_info`）加關鍵字比對，涵蓋[附錄 A](#附錄-a錯誤代碼對照表e2f-與-f-en-共用)的所有代碼。
- `stage_text(stage_code, lang, **params)`：處理階段文字（排隊中、準備中、下載中、重新連線中 N/M、合併影音軌、寫入中繼資料、完成、完成（有警告）、已暫停、已取消、失敗…），取代 `server.py` 裡寫死的中文；後處理名稱表（`server.py:826` 附近）也搬過來。
- 每個代碼和階段都要有中文和英文；`message` 裡不能出現本機完整路徑（例如 cookies.txt 的路徑）。
- 不 import `server`（避免循環 import），只依賴 yt-dlp 的例外類別。
- 測試：每個錯誤代碼至少兩個真實原文樣本（引擎報告的實測字串可以直接用）；每個代碼、階段在兩種語言都有文字。
- 追加（已實作）：`server_error`（HTTP 5xx），FAQ 錨點用 `err-network`；USER_GUIDE 兩個語言版本的這一題要涵蓋它（由 F／F-EN 補，見附錄 A）。

#### F 文件、發布與授權
- ONB15：新增 `LICENSE`（MIT，`Copyright (c) 2026 Archer8685`）；新增 `THIRD_PARTY_NOTICES.md`，列出 yt-dlp（Unlicense）、FFmpeg（依實際打包的版本是 LGPL 或 GPL，附授權全文連結與原始碼取得方式）、Deno（MIT）、PySide6／Qt（LGPLv3）、Flask 等；`build_app.py` 把這兩個檔案打包進安裝檔；README 拿掉「未附開源授權檔」。
- ONB5／ONB6／ONB7（已決定不簽章、不公證）：USER_GUIDE、Release 說明、index.html 三處統一成同一套放行步驟，**不再提簽章計畫**。
  - Windows：瀏覽器說「通常不會下載此檔案」時按「保留」；SmartScreen「Windows 已保護您的電腦」→「其他資訊」→「仍要執行」；防毒誤判隔離時怎麼還原、怎麼加入例外；說明原因是「沒有付費的數位簽章，不代表有病毒」，並教使用者用 `SHA256SUMS.txt` 確認檔案沒被竄改。
  - macOS：① 先雙擊一次（會被擋）② 系統設定 → 隱私權與安全性 → 最下方「仍要打開」③ 只有顯示「已損毀」時才用 `xattr -dr com.apple.quarantine`；分開寫 macOS 14 和 15 的差異。
  - Intel Mac：寫明不支援，教使用者看自己的晶片（ → 關於這台 Mac）。
- ERR9：USER_GUIDE FAQ 依[附錄 A](#附錄-a錯誤代碼對照表e2f-與-f-en-共用)補齊，每題用固定錨點（`<a id="err-…"></a>`）；cookies 一題加步驟與安全提醒（先登入、不要把 cookies.txt 給別人或貼到 issue）。`err-network` 一題要同時涵蓋 E2 追加的 `server_error`（HTTP 5xx：網站伺服器暫時出問題，等幾分鐘再試，不是使用者網路的問題）。
- F7：USER_GUIDE 加「從瀏覽器一鍵送到 App」：書籤小工具的程式碼（`javascript:location.href='ytdl://add?url='+encodeURIComponent(location.href)`）和安裝步驟；說明第一次點時瀏覽器會詢問是否開啟 App。F3：說明系統匣常駐和怎麼完全結束 App。
- `build_app.py`：
  - F7：Windows 的 Inno `[Registry]` 註冊 `HKCU\Software\Classes\ytdl`（指向 App，帶 `"%1"`），加 `uninsdeletekey`；macOS 的 `info_plist` 加 `CFBundleURLTypes`（scheme `ytdl`）。
  - F13：Inno 加英文語系，依系統語言自動選；確認 Qt 檔案過濾保留 `qtbase_en.qm`、`qtbase_zh_TW.qm`；`datas` 加入 `i18n/*.qm`。
  - ONB8：解除安裝時詢問「是否一併刪除設定與 cookies（下載的影片不會刪）」（中英文）。
- ONB1：README 最上方放下載表（`releases/latest/download/` 連結）和截圖，開發者內容移到下方；準備 repo 的 description、homepage、topics 文字，交給主 session 套用。ONB13：index.html 頁尾加「使用說明」「回報問題」。ONB11：更新前先等下載完成。ERR11：上傳 log 前先看內容。
- ONB2：`tools/release_notes.py` 把「該下載哪個檔」表格放最上面（系統、檔名、大小、需求、Intel Mac 不支援），加一句「不要下載 Source code」，附放行步驟的連結。ONB3：CHANGELOG 的維護說明改成 HTML 註解，同步更新 `tests/test_release_notes.py`。
- ONB4：`release.yml` 產生並上傳 `SHA256SUMS.txt`，Release 說明附驗證指令。
- ERR10：`.github/ISSUE_TEMPLATE/bug_report.yml`（App 版本、介面語言、系統與晶片、網址、錯誤訊息、engine.log、勾選「看過 FAQ」「沒有附 cookies.txt」）、`feature_request.yml`、`config.yml`（導向 FAQ）。
- F 合併後，`README.md` 改由 F-EN 負責。

#### T 系統整合（`single_instance.py`、`url_handoff.py`、`native_tray.py`）
- `single_instance.py`：用 `QLocalServer`／`QLocalSocket`，名稱依使用者帳號區分（同一台電腦不同使用者互不干擾）。第二次啟動時把命令列參數（可能是 `ytdl://` 網址）傳給第一個，然後結束；第一個收到後發出 `message_received(list[str])`。要處理「第一個當掉、留下殘留的 socket」的情況。必須在 `app_boot.boot()` **之前**就能判斷，避免啟動第二個引擎。
- `url_handoff.py`：`parse_handoff(arg: str) -> str | None`。接受 `ytdl://add?url=<編碼後的網址>`、直接的 http/https 網址、macOS `QFileOpenEvent` 傳來的網址；解碼後只接受 `http`／`https`，長度上限 2048，拒絕 `file:`、`javascript:`、`data:` 等。**只回傳網址，不做任何下載動作**。
- `native_tray.py`：`TrayController(QObject)`：系統匣圖示（macOS 是選單列）、選單（顯示視窗、目前進度、暫停全部、繼續全部、結束）、滑鼠移上去顯示進度（例如「2 個下載中 · 45%」）、`notify(title, body, job_id)` 顯示系統通知，點通知發出 `notification_clicked(job_id)`。只透過訊號和外界溝通，不直接呼叫引擎 API。
- 字串照 I0 規範寫；I0 合併前先直接用 `QCoreApplication.translate`。
- 驗收：單元測試涵蓋惡意網址（`ytdl://add?url=javascript:…`、`file:///`、超長網址、重複編碼）；兩個程序的單一實例測試；Windows 和 macOS 都能顯示系統匣和通知（macOS 未簽章 App 的通知權限要實機確認，結果寫進 USER_GUIDE）。

#### A1 新增下載頁（`native_download.py`）
- 所有使用者看得到的字串改用翻譯函式（照 `docs/I18N.md`），包括原本就有的字串。
- DL1：「摘要＋下載」做成固定在底部的動作列；解析完成後「解析」改成次要樣式；播放清單模式讓清單填滿剩下的高度。
- DL3：解析中按鈕變成「取消」（`QNetworkReply.abort()`，丟掉舊的請求序號）；骨架卡片或不確定進度條；超過 15 秒顯示「播放清單很長時會比較久」；按鈕固定最小寬度（中英文都放得下）。
- DL2（下載頁這一半）：切到字幕模式時呼叫 A2 的 `reveal_section("subtitles")`；摘要裡的錯誤做成可點的連結，點了跳到要修正的地方。
- DL5：已經有解析好的影片時，剪貼簿的新連結改成在網址列下方顯示「偵測到新連結：…［解析］［忽略］」，不直接取代。從 `ytdl://` 傳進來的網址也走同一個提示（避免蓋掉正在設定的影片）。
- DL6：看起來像網域時自動補 `https://`；接受 11 碼影片 ID。DL7：提供 `focus_url()`。DL9：空狀態三步驟說明、支援網站舉例、拖放與書籤小工具提示。DL13：開關和文字做成同一個可點元件，重新解析時說明原因。DL15：窄視窗縮圖縮小、載入前顯示佔位圖。
- ERR1（下載頁這一半）：解析失敗時顯示 `error`，「詳細資訊」可展開 `error_detail`，依 `error_action` 顯示按鈕（例如呼叫 `MainWindow.open_settings("cookies")`），「怎麼解決」連到 `i18n.guide_url(faq)`。
- F1：網址欄可以貼多行，或用「批次新增」對話框（也可以選 .txt）；逐行抽出網址，列成可勾選清單，套用目前選項，一行一個工作。一次最多 100 個。
- F4／F7（下載頁這一半）：提供 `accept_urls(list[str])`：一個網址 → 填入並解析（已有解析好的影片時走 DL5 的提示）；多個 → 走批次流程。

#### A2 進階選項與播放清單（`native_options.py`、`native_playlist.py`）
- 所有使用者看得到的字串改用翻譯函式。
- DL2：提供 `AdvancedOptions.reveal_section(key)`（展開並捲到該分組）。
- A11Y1：`Switch` 建構時接收標題並 `setAccessibleName`；`switch_row`、`block_row` 自動把標題設成控制項名稱；`SectionHeader` 設名稱和「已展開／已收合」描述；`Chip` 回報 checkable 狀態；裝飾性元件設 `Qt.NoFocus`。
- A11Y2：分段控制支援方向鍵；自繪元件統一 2 px 焦點環。自繪元件（Chip、Switch、播放清單列）的尺寸改用 `fontMetrics` 計算，英文較長的文字不會被切掉。
- DL12：「還原預設值」改成「進階選項恢復預設」，並提供復原。DL14：範圍語法錯誤後面接「例如：1-10, 15, 20-」。播放清單「一部都沒選」時提供「全選」連結（DL2）。

#### B 佇列頁（`native_queue.py`）
- 所有使用者看得到的字串改用翻譯函式；引擎回傳的 `stage`、`error` 文字直接顯示（引擎已依語言組好）。
- R4：下載中顯示「暫停」，`paused` 顯示「繼續」；改掉會誤導的提示文字。
- R5：預設「從清單移除」，「連同檔案刪除（移到資源回收筒）」放次要；「清除已完成」按鈕。
- R2／R3／R6：`done` 且有 `warnings` 時顯示橘色「已完成，但有部分步驟失敗」；播放清單顯示「完成 180/200」，可展開失敗清單，有「重試失敗的項目」。
- ERR1／ERR3／ERR4：顯示錯誤訊息，可展開原文、可複製；依 `error_action` 顯示按鈕（「設定 Cookie」「繼續下載」「套用 yt-dlp 新版並重試」）；每列有「顯示紀錄」。
- Q1：「開啟」（用預設播放器開最大的檔案）、雙擊開啟。Q2：狀態圖示；取消用灰色。Q5：「暫停全部／繼續全部／全部重試」，並提供 `pause_all()`、`resume_all()` 給 C1 接系統匣選單。Q6：「排隊中（前面還有 N 個）」。
- F2／F3（佇列這一半）：工作進入 `done`／`error` 時發出 `job_finished` 訊號；提供 `summary()`（進行中數量、整體進度）給系統匣顯示；提供 `show_job(job_id)`（捲到該工作並標示）給點通知時使用。

#### C1 主視窗與共用元件（`native_app.py`、`native_common.py`）
- 所有使用者看得到的字串改用翻譯函式；`main()` 一開始呼叫 `i18n.install(app)`。
- R1／ERR6／ERR7：引擎離線 banner 改成看得懂的標題＋說明＋「重試」「開啟紀錄檔」「重新啟動 App」；離線時停用「解析」，不再顯示第二份錯誤；`/api/meta` 有 `download_dir_error` 時顯示「儲存位置目前無法存取［更換位置］［重試］」；`Api` 收到非 JSON 回應時不再說「連接埠被佔用」；`Api` 每個請求都帶 `Accept-Language`（`i18n.current_language()`）。
- ERR8：`toast()` 加 `level` 和 `actions` 參數（保持舊的呼叫方式可用）；錯誤類不自動消失，要手動關閉，可以複製。
- DL8／F4：快捷鍵（Ctrl+L 網址欄、Ctrl+Enter 下載、Ctrl+1/2/3 切頁、Ctrl+, 設定、Esc 取消解析）；整個視窗接受拖放，轉給 `DownloadPage.accept_urls()`。DL7：啟動和切回「新增下載」時呼叫 `focus_url()`。
- F7（T 合併後）：`main()` 在 `app_boot.boot()` 之前先用 `SingleInstance` 判斷，已有 App 在執行就把參數交給它並結束；收到 `message_received` 時喚醒視窗，並把 `url_handoff.parse_handoff()` 通過的網址交給 `DownloadPage.accept_urls()`；macOS 接 `QFileOpenEvent`。
- F2／F3（T 合併後）：建立 `TrayController`，接 `QueuePage.job_finished` 顯示通知（App 在前景時不通知），點通知開到該工作；系統匣選單接 B 的 `pause_all()`／`resume_all()`；`closeEvent` 依 C2 的設定（`close_action` = `quit`／`tray`）決定結束還是縮到系統匣；縮到系統匣時第一次顯示「App 會在背景繼續下載」的通知。「結束」時若有下載進行中，照現在的方式先詢問。
- A11Y1／A11Y2：`form_row` 用 `setBuddy` 並設定 accessibleName；側邊欄支援方向鍵；`QScrollArea.setFocusPolicy(Qt.NoFocus)`。
- SET9 記住視窗大小、位置；SET10 淺色次要文字加深到約 `#6E6E73`；SET11 使用聲明改成三點條列，「查看完整聲明」用 App 內的捲動對話框顯示已打包的 `DISCLAIMER.md`（依語言顯示中文或英文段落）。
- 提供 `MainWindow.open_settings(section)`，轉呼叫 C2 的 `SettingsPage.focus_section(section)`。

#### C2 設定頁與 App 更新（`native_settings.py`、`app_update.py`）
- 所有使用者看得到的字串改用翻譯函式。
- F13：「外觀」區加「語言：跟隨系統／中文（繁體）／English」（呼叫 `i18n.set_language()`），切換後提示重新啟動並提供「立即重新啟動」按鈕（沿用現有的重啟機制）。
- F3：「一般」區加「關閉視窗時：結束 App／縮到系統匣，背景繼續下載」，預設「結束 App」；提供 `close_action()` 給 C1 讀取。
- SET1：`app_update.py` 查 `https://api.github.com/repos/Archer8685/yt-dl/releases/latest`（不帶驗證、每天最多一次、結果快取、逾時 5 秒、失敗不顯示錯誤）；有新版時側邊欄「設定」顯示徽章、「關於」顯示「有新版 x.y.z：查看更新內容／下載」，下載按鈕開該平台安裝檔的 `releases/latest/download/<檔名>`；可以「略過此版本」。只提示，不自動安裝。
- SET2：yt-dlp 更新完成後先詢問再重啟，說明進行中的下載會怎樣。
- ERR4：「關於」加「使用說明」（`i18n.guide_url()`）、「開啟紀錄資料夾」、「回報問題」（開 issue 新增頁，網址帶上 App 版本、yt-dlp 版本、作業系統、介面語言，**不帶任何影片網址或檔案路徑**）；顯示授權（MIT）與「第三方授權」連結。
- SET4：沒有 Cookie 時顯示中性的「未設定」＋「如何匯出 cookies.txt」連結。SET5：「刪除 Cookie」按鈕（引擎已有 `DELETE /api/cookies`）。SET6：環境變數鎖定時停用「變更…」並說明原因。SET8：同時下載數 1–5。DL12：「恢復所有預設值」改成「重設所有偏好…」、「恢復預設」改成「改回預設資料夾」。
- 提供 `SettingsPage.focus_section(section)`，section 至少支援 `"storage"`、`"cookies"`、`"language"`、`"about"`。

#### F-EN 英文文件（F 合併後）
- 新增 `USER_GUIDE.en.md`：和中文版對應的章節（安裝與放行步驟、基本使用、系統匣、書籤小工具、更新、移除、FAQ），FAQ 錨點和中文版完全相同；`err-network` 一題同樣要涵蓋 `server_error`（HTTP 5xx）。
- `README.md`：最上方加英文一句話介紹、英文下載表、連到 `USER_GUIDE.en.md`。
- 在 USER_GUIDE 兩個版本的開頭互相連結（中文版開頭的連結也由 F-EN 加，此時 F 已合併，`USER_GUIDE.md` 的這一行交給 F-EN）。
- 驗收：D 的錨點測試同時檢查兩個版本。

#### I2 英文翻譯（第三批）
- 跑 `tools/i18n_update.py` 抽出所有字串，在 `i18n/yt_dl_en.ts` 補完英文翻譯、編譯 `.qm`。
- 整理用語表寫進 `docs/I18N.md`，介面、`engine_messages.py` 的英文、`USER_GUIDE.en.md` 用同一套用語（不一致時列給 D 或回報主 session，不直接改別人的檔案）。
- 用 `tools/ui_screenshot.py` 以 English 模式截圖，檢查文字被截斷或版面破掉的地方，列給 D 修。

#### D 無障礙與字串收尾（第三批）
- 新增 `tests/test_accessibility.py`：建立每一頁（含進階選項全部展開、播放清單模式），檢查所有可取得焦點的元件都有文字或 accessibleName；QScrollArea 不吃 Tab；側邊欄方向鍵可以切頁。
- 新增 `tests/test_no_untranslated.py`：翻譯檔沒有未翻譯的項目；介面檔沒有沒包翻譯函式的中文字串（允許清單：註解、log 訊息）；`engine_messages.py` 的每個錯誤代碼在 `USER_GUIDE.md` 和 `USER_GUIDE.en.md` 都有錨點。
- 修正測試和 I2 截圖抓到的問題（此時其他介面包都已合併，可以小幅修改任何 native 檔案；改了字串要通知 I2 重新抽字串）。

#### INT 整合發布
- `VERSION` 改成 1.3.0，`CHANGELOG.md` 寫 v1.3.0 段落（用一般使用者看得懂的話；Release 說明要不要附英文摘要由 INT 決定，`tools/release_notes.py` 支援就附）。
- 跑完[第 4.1 節](#41-v130可靠看得懂找得到走向國際)的 15 項驗收；照全域規則跑 `review-qa-loop`；Windows 打包版在中文和英文系統各實機走一遍（含安裝、SmartScreen 放行、`ytdl://`、系統匣、解除安裝）；macOS 打包版走一遍（含 Gatekeeper 放行、通知權限）。

### 5.5 介面約定（開工前就固定）

各工作包只透過以下介面互相溝通，不改對方的檔案。欄位不存在時要退回舊行為。

**引擎 API（E1 提供，A1、B、C1、C2 使用）**

| 項目 | 約定 |
|---|---|
| 語言 | App 每個請求帶 `Accept-Language`；`en` 開頭回傳英文，其他回傳中文。沒帶標頭（網頁版）一律中文 |
| 錯誤物件 | 解析失敗與 API 錯誤回傳 `{"error": <依語言的訊息>, "error_code": <代碼>, "error_detail": <原文>, "error_action": <動作或 null>, "error_faq": <錨點>}`。`error` 欄位保留，舊版 App 也能顯示 |
| 工作物件新增欄位 | `error_code`、`error_detail`、`error_action`、`error_faq`、`stage_code`、`warnings`（list[str]，done 但有部分步驟失敗時）、`failed_items`（list[{index, title, error_code, error, error_detail}]）、`done_count`、`total_count`、`queue_position`（排隊中才有）。`stage`、`error` 文字依請求語言組成 |
| 新狀態 | `paused`（屬於可續傳狀態，和 `error` 一樣可以 resume） |
| 新端點 | `POST /api/jobs/<id>/pause`、`POST /api/jobs/<id>/retry_failed`、`POST /api/jobs/pause_all`、`POST /api/jobs/resume_all`、`POST /api/jobs/retry_all`、`POST /api/jobs/clear`（清除已完成） |
| 改動的端點 | `POST /api/jobs/<id>/resume` 接受 `error`、`paused`；`DELETE /api/jobs/<id>?files=keep\|trash`（預設 keep）；`GET/POST /api/settings` 加 `parallel`（1–5）；`GET /api/meta` 加 `download_dir_error`（字串或 null），`latest` 可能是 null |
| `friendly_error()`（E2 提供，E1 使用） | `friendly_error(exc_or_message, lang) -> {"code", "message", "detail", "action", "faq"}`；`stage_text(stage_code, lang, **params) -> str` |
| `error_action` 可能的值 | `open_cookie_settings`、`open_storage_settings`、`open_network_settings`、`reanalyze`、`resume`、`update_ytdlp`、`retry`、`null` |

**Qt 與模組介面（跨工作包呼叫）**

| 提供者 | 介面 | 使用者 |
|---|---|---|
| I0 | `i18n.install(app)`、`i18n.current_language() -> "zh_TW"\|"en"`、`i18n.get_setting()`／`set_language("system"\|"zh_TW"\|"en")`、`i18n.guide_url(anchor: str = "")` | C1、C2、A1、B |
| T | `SingleInstance(key)`：`.is_primary() -> bool`、`.send(args: list[str]) -> bool`、訊號 `message_received(list)`；`url_handoff.parse_handoff(arg) -> str \| None`；`TrayController(parent)`：`.set_summary(text, progress)`、`.notify(title, body, job_id)`、訊號 `show_requested`、`pause_all_requested`、`resume_all_requested`、`quit_requested`、`notification_clicked(str)` | C1 |
| A1 | `DownloadPage.focus_url()`、`DownloadPage.accept_urls(urls: list[str])`、`DownloadPage.cancel_analyze()`、`DownloadPage.start_download()` | C1 |
| A2 | `AdvancedOptions.reveal_section(key: str)`，key 至少有 `"subtitles"`、`"clip"`、`"network"` | A1 |
| B | `QueuePage.job_finished = Signal(dict)`（狀態剛變成 done 或 error 時發出）、`QueuePage.summary() -> dict`（active、progress）、`pause_all()`、`resume_all()`、`show_job(job_id)` | C1 |
| C1 | `MainWindow.open_settings(section: str)`；`toast(text, level="info"\|"error", actions=[(label, callback)])` | A1、B、C2 |
| C2 | `SettingsPage.focus_section(section: str)`、`SettingsPage.close_action() -> "quit"\|"tray"`、`SettingsPage.update_available = Signal(dict)`；`app_update.check(force=False) -> dict \| None` | C1 |
| 共用 | `ytdl://` 格式：`ytdl://add?url=<encodeURIComponent 後的 http/https 網址>`。F（安裝註冊、書籤小工具）、F-EN、T（解析）都照這個格式 | F、F-EN、T |

### 5.6 給實作子 session 的共同規則

- 每個工作包在自己的 worktree 和分支工作，只改第 5.1 節列給自己的檔案；需要別人的檔案改東西時，寫進共用筆記資料夾，由主 session 協調。
- 完成前照全域規則跑 `review-qa-loop`（code review、pytest、型別與 lint；介面工作包要用 `tools/ui_screenshot.py` 截圖確認）。
- 新的使用者可見字串原文用繁體中文、照 `docs/I18N.md` 包翻譯函式，用一般使用者看得懂的說法，不出現 yt-dlp 術語或命令列參數。英文翻譯統一由 I2 補，各包不要改 `i18n/`。
- 不要更新 `CHANGELOG.md` 的版本段落和 `VERSION`（INT 統一處理）。

---

## 6. 已決定的事

2026-11-09 使用者看完第一版規劃後決定。原話：「Windows 程式碼簽章&macOS 簽章與公證（每年 US$99）不用；系統匣常駐、ytdl:// 一鍵送到 App+英文介面要加入；其他的也都加入」，以及「LICENSE 用 MIT（著作權人寫 Archer8685）、Intel Mac 先在文件寫明不支援、GitHub Pages 改成 GitHub Actions 發布，第 6.2 節的小決定都照建議」。

### 6.1 大決定

| # | 項目 | 決定 | 對規劃的影響 |
|---|---|---|---|
| 1 | 專案授權（LICENSE） | **MIT**，著作權人 Archer8685；另附 `THIRD_PARTY_NOTICES.md` | v1.3.0 的 F 工作包新增 `LICENSE`、`THIRD_PARTY_NOTICES.md` 並打包進安裝檔（ONB15）。打包的 FFmpeg 若是 GPL 版本，第三方說明要附授權全文與原始碼取得方式（這不是法律意見，有疑慮請諮詢專業人士） |
| 2 | Windows 程式碼簽章 | **不做** | 文件一步一步教使用者放行瀏覽器警告、SmartScreen、防毒誤判，並提供 SHA-256 校驗值讓使用者自己確認檔案（ONB4、ONB5），不再提簽章計畫 |
| 3 | macOS 簽章與公證 | **不做** | 文件統一 Gatekeeper 放行三步驟，分開寫 macOS 14／15 的差異（ONB6）；`ytdl://` 和通知在未簽章 App 上的行為要實機確認並寫進文件 |
| 4 | Intel Mac 版 | **不出 Intel 版**，文件寫明不支援 | F 在 USER_GUIDE、Release 說明、README 下載表標明（ONB7） |
| 5 | 英文介面 | **併入 v1.3.0**，可切換跟隨系統／中文（繁體）／English，USER_GUIDE 出英文版 | 新增 I0、I2、F-EN 三個工作包；E2 改成雙語訊息；各介面包改用翻譯函式（第 5.3 節） |
| 6 | 系統匣常駐、關閉視窗後繼續下載 | **併入 v1.3.0**，預設維持「關閉視窗時結束 App」 | 新增 T 工作包；C1 接線、C2 加設定 |
| 7 | `ytdl://` 一鍵送到 App（含單一實例） | **併入 v1.3.0**，只填入網址並解析，**絕不自動開始下載**，只接受 http/https | T 實作單一實例與網址驗證；F 在安裝檔註冊協定並寫書籤小工具說明 |
| 8 | 頻道／播放清單追蹤 | 照建議：**v1.5.0 先做「只通知」版** | 數量上限 50、只抓加入追蹤之後的新影片、檢查間隔至少 1 小時 |
| 9 | App 自動更新的程度 | 照建議：**只提示新版、開下載頁，不自動安裝** | C2 的 SET1 |
| 10 | 網頁版是否繼續維護 | 照建議：**停止加新功能**，v1.4.0 把 Pages 首頁改成產品介紹＋下載頁 | ONB14 排進 v1.4.0；v1.3.0 只修文件不一致（ONB13），網頁版不做英文 |
| 11 | App 內搜尋影片 | 照建議：**不做** | F15 移到不做 |
| 12 | GitHub Discussions | 照建議：**維持關閉** | issue 範本的 `config.yml` 導向 FAQ |

### 6.2 小決定（照建議）

| # | 項目 | 決定 |
|---|---|---|
| 1 | GitHub Pages 來源 | 改成 **GitHub Actions** 發布（ONB12）。由主 session 用 `gh api` 或使用者在 Settings → Pages 操作，不需要改程式 |
| 2 | repo 的 description、homepage、topics | 要設定；F 準備文字，主 session 用 `gh repo edit` 套用（執行前確認文字） |
| 3 | 佇列「刪除」的預設動作 | 預設「從清單移除」，刪檔是次要選項且放進資源回收筒 |
| 4 | 批次貼上的上限 | 一次最多 100 個網址 |
| 5 | 同時下載數範圍 | 1–5，預設維持 3 |
| 6 | 「取消」和「暫停」 | 都保留：「暫停」保留進度；「取消」代表不要了，會先確認「已下載 X MB 會被捨棄」 |

---

## 7. 不建議做的功能

| 功能 | 原因 | 和 `DISCLAIMER.md` 的關係 |
|---|---|---|
| 破解 DRM（Netflix、Disney+、Spotify、受保護的 YouTube 電影等） | 多數地區法律（含台灣著作權法第 80-2 條）禁止規避技術保護措施；yt-dlp 本身也不支援 | **直接衝突**：第 3 點「規避…或破解 DRM 等技術保護措施」、「本軟體不提供、也不支援破解 DRM 的功能」 |
| 內建 VPN、公開代理清單、自動切換地區；**錯誤訊息建議用 Proxy 繞過地區限制** | 提供規避工具或引導都等於鼓勵規避。現有的手動代理欄位保留（公司網路、使用者自己的代理），但不提供代理來源，也不在地區限制的錯誤訊息裡建議改代理 | **直接衝突**：第 3 點「規避…地區限制」 |
| 反偵測：自動輪換 IP／User-Agent、自動產生 PO Token、繞過「確認你不是機器人」 | 刻意規避平台防護，會讓專案被視為濫用工具，也很容易隨 YouTube 改版失效；yt-dlp 官方的更新（已有自動更新）就夠了 | 衝突：第 2 點（遵守平台服務條款）、第 3 點 |
| 整個頻道或網站「完整封存並持續同步」、沒有上限的批次爬取 | 大量爬取容易被限流、帳號被標記，也最可能被用來重新上傳他人內容；追蹤功能改用「只抓新影片＋數量上限」，批次貼上限制 100 個 | 衝突：第 3 點「重製、散布…盜版內容」的風險最高 |
| `ytdl://` 收到網址就自動開始下載 | 任何網頁都能觸發這個連結，自動下載等於讓網頁替使用者決定下載什麼；v1.3.0 只填入並解析，由使用者按下載 | 安全理由；也符合第 1 點「下載什麼由使用者自己決定」 |
| 下載後自動上傳到其他平台、產生雲端分享連結 | 直接協助重新散布 | **直接衝突**：第 3 點「重製、散布、販售或公開播送」；第 4 點「不散布任何影音內容」 |
| Podcast 訂閱源（在區網提供 RSS 給手機） | 要把引擎開放到區網，有安全疑慮；把下載內容以訂閱源形式提供接近重新散布 | 和第 3、4 點的精神有張力 |
| 使用他人帳號 Cookie、共享 Premium 帳號 | 違反平台條款，也有隱私風險 | **直接衝突**：第 5 點「只能用於你自己的帳號」 |
| 引擎開放到區網或網際網路、手機遙控下載 | 等於在區網提供沒有驗證的下載與檔案讀取 API（`/api/file`），安全風險大；真的需要時要另外設計配對與驗證 | 安全理由（第 4 點也說明下載只在使用者自己的電腦上） |
| App 內搜尋影片（已決定不做） | 會讓 App 變成「YouTube 替代前端」，偏離「下載你有權使用的內容」的定位；搜尋頁也最常因 YouTube 改版而壞掉 | 和第 2 點（確認有權下載）的定位有張力 |
| 上架 Chrome／Edge 擴充功能商店 | Chrome Web Store 政策不允許下載 YouTube 影片的擴充功能，送審大概率被拒，還要另外維護一個專案；用 `ytdl://`＋書籤小工具達到大部分效果 | 平台政策 |
| 改成單檔（onefile）打包 | 每次啟動都要解壓 279 MB 的 ffmpeg＋deno，會多好幾秒並被防毒重複掃描；維持 onedir | 技術理由 |
| 自動下載並安裝 App 更新 | 沒有簽章（已決定不做），自動安裝會被 SmartScreen、Gatekeeper 擋，體驗比手動下載更差 | 技術理由 |
| 本機轉檔工具箱、語音轉字幕（暫不做） | 讓 App 往「影音工具箱」擴張、打包體積大增（Whisper 模型數百 MB 到數 GB）；之後只考慮做成選配外掛 | 範圍理由 |

---

## 附錄 A：錯誤代碼對照表（E2、F 與 F-EN 共用）

E2 依這張表實作 `friendly_error()`（中文訊息如下，英文由 E2 撰寫、I2 統一用語），F 和 F-EN 依這張表在 `USER_GUIDE.md`、`USER_GUIDE.en.md` 建立**相同的**錨點。訊息是建議文案，實作時可以微調，但**代碼和錨點不能改**（D 工作包會用測試比對）。

| 代碼 | 判斷依據（關鍵字或例外類別） | 建議中文訊息 | `action` | USER_GUIDE 錨點 |
|---|---|---|---|---|
| `invalid_url` | 非 http/https 網址 | 請輸入有效的網址 | null | `err-invalid-url` |
| `unsupported_url` | `UnsupportedError`、`Unsupported URL` | 不支援這個網站，或這個網頁裡沒有影片 | null | `err-unsupported-url` |
| `video_unavailable` | `This video is unavailable`、`Video unavailable` | 找不到這部影片，可能已被刪除或網址打錯 | null | `err-video-unavailable` |
| `private_video` | `Private video` | 這是私人影片，需要用有權限的帳號登入 | `open_cookie_settings` | `err-private-video` |
| `age_restricted` | `Sign in to confirm your age` | 這部影片有年齡限制，請在「設定 → Cookie」登入自己的帳號後再試 | `open_cookie_settings` | `err-age-restricted` |
| `members_only` | `members-only`、`Join this channel` | 這是頻道會員限定影片，需要登入有會員資格的帳號 | `open_cookie_settings` | `err-members-only` |
| `geo_blocked` | `GeoRestrictedError`、`not available in your country`、`geo restriction` | 這部影片在你所在的地區無法觀看（**不要**建議改用 Proxy） | null | `err-geo-blocked` |
| `bot_check` | `not a bot`、`Sign in to confirm you` | YouTube 要求驗證，請設定 Cookie 登入後再試 | `open_cookie_settings` | `err-bot-check` |
| `live_not_started` | `live event will begin`、`Premieres in` | 直播還沒開始（預計 N 分鐘後），開播後再下載 | null | `err-live-not-started` |
| `http_403` | `HTTP Error 403` | 伺服器拒絕下載（連結可能過期），請按「繼續下載」；一直出現的話請更新 yt-dlp | `resume`（有新版時 `update_ytdlp`） | `err-http-403` |
| `rate_limited` | `HTTP Error 429`、`Too Many Requests` | 短時間內請求太多次，請過幾分鐘再試 | `retry` | `err-rate-limited` |
| `format_unavailable` | `Requested format is not available` | 指定的畫質或格式已不存在，請重新解析後再選一次 | `reanalyze` | `err-format-unavailable` |
| `ffmpeg_failed` | `Conversion failed`、`ffmpeg exited with code` | 下載完成，但「合併影音軌」等後製步驟失敗；原始檔已保留 | null | `err-ffmpeg-failed` |
| `ffmpeg_missing` | `ffmpeg is not installed`、`ffmpeg not found` | 找不到 FFmpeg，請到「設定」查看狀態 | null | `err-ffmpeg-missing` |
| `network_dns` | `getaddrinfo failed`、`Failed to resolve`、`Name or service not known` | 無法連線到網站，請確認網路連線 | `retry` | `err-network` |
| `network_timeout` | `timed out`、`TransportError`、`Connection reset` | 網路連線逾時，請確認網路後再試 | `retry` | `err-network` |
| `server_error` | `HTTP Error 5xx`（如 `502: Bad Gateway`、`503: Service Unavailable`）；**不比對**裸的 `internal server error`（那是引擎自己的 Flask 500，歸 `engine_internal`） | 網站目前沒有回應（伺服器暫時出問題），請過幾分鐘再試 | `retry` | `err-network`（E2 已在 `engine_messages.py` 實作，沿用網路一題的錨點；該 FAQ 題目要補上「網站伺服器暫時出問題」的說明） |
| `proxy_error` | `Unable to connect to proxy`、`ProxyError` | 連不上你設定的 Proxy，請檢查進階選項裡的 Proxy 設定 | `open_network_settings` | `err-proxy` |
| `cookie_browser_locked` | `Could not copy Chrome cookie database`、`cookie database`、Chromium 加密相關 | 無法讀取瀏覽器的 Cookie（Chrome／Edge 開著時會被鎖住）。請關閉瀏覽器再試，或改用 Firefox 或 cookies.txt | `open_cookie_settings` | `err-cookie-browser` |
| `cookies_invalid` | `Netscape format cookies file` | cookies.txt 格式不正確，請重新匯出（訊息裡不顯示檔案路徑） | `open_cookie_settings` | `err-cookies-invalid` |
| `disk_full` | `Errno 28`、`No space left`、引擎自己的空間檢查 | （維持現有中文訊息，位置改成「設定 → 儲存位置」） | `open_storage_settings` | `err-disk-full` |
| `download_dir_unavailable` | 下載資料夾建立或寫入失敗 | 儲存位置 X 目前無法存取，請確認磁碟已接上或更換儲存位置 | `open_storage_settings` | `err-download-dir` |
| `engine_internal` | Flask 未處理的例外 | 下載引擎發生錯誤，請重試；一直發生的話請回報問題並附上紀錄檔 | `retry` | `err-engine` |
| `unknown` | 其他 | 下載失敗。可以展開「詳細資訊」查看原因，或回報問題 | `retry` | `err-unknown` |

另外，USER_GUIDE 兩個版本都要有這幾個非錯誤代碼的固定錨點，供 App 和 Release 說明連結：`install-windows`（SmartScreen 放行）、`install-macos`（Gatekeeper 放行）、`tray`（系統匣）、`bookmarklet`（`ytdl://` 書籤小工具）、`uninstall`（完整移除）。

## 附錄 B：沒有收進來的報告內容

- APP-H4 的「深色模式整體可用」、ENG 第 7 節「做得好的地方」、ONB-3-1「第一次開啟大致順暢」、ONB-4-3「升級後設定保留」是觀察或肯定，沒有列成工作項目；改版時要保留這些行為（例如下載中每 3 秒檢查磁碟、yt-dlp 自動更新的 sha256 驗證、onedir 打包）。
- ENG-4-4（長時間執行記憶體）沒有發現問題，只把「歷史保留期限」併入 PERF6。
- ENG-5-3（cookies.txt 明文）：v1.3.0 只做「App 內可刪除」與文件說明（SET5、ONB8），DPAPI 加密列為 v1.4.0 之後再評估，因為使用時仍要解密成暫存檔給 yt-dlp，實際保護有限。
- ONB 第七節的「程式碼簽章」「macOS 公證」選項：使用者已決定不做，見[第 6 節](#6-已決定的事)。
