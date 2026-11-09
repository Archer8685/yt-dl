# 第三方元件授權說明（Third-Party Notices）

YT 下載器本身以 [MIT 授權](LICENSE) 釋出（Copyright (c) 2026 Archer8685）。
安裝檔（Windows 安裝精靈、macOS dmg）另外內含下列第三方元件，它們各自依自己的授權條款提供，**不受本專案的 MIT 授權約束**。
這份清單依 `build_app.py` 實際打包的內容整理；這不是法律意見，有疑慮請諮詢專業人士。

*YT Downloader itself is released under the [MIT License](LICENSE). The installers also bundle the third-party components listed below, each under its own license.*

## 獨立執行的工具（放在 App 的 `bin/` 資料夾，以獨立程式執行）

| 元件 | 用途 | 授權 | 來源 |
| --- | --- | --- | --- |
| [FFmpeg](https://ffmpeg.org)、ffprobe | 合併影音軌、轉檔、剪輯、嵌入中繼資料 | **GPL**（見下方說明） | Windows：[yt-dlp/FFmpeg-Builds](https://github.com/yt-dlp/FFmpeg-Builds)（`ffmpeg-master-latest-win64-gpl-shared`）；macOS：[ffmpeg.martin-riedl.de](https://ffmpeg.martin-riedl.de) |
| [Deno](https://deno.com) | 讓 yt-dlp 解讀 YouTube 的播放器程式 | MIT | [denoland/deno](https://github.com/denoland/deno) |

### FFmpeg（GPL 組建）

打包的 FFmpeg 是「GPL 組建」：除了 FFmpeg 本身（LGPL 2.1 以上）之外，還編譯進了 x264、x265 等 GPL 授權的函式庫，所以整個 FFmpeg 執行檔與它的函式庫依 **GNU General Public License（GPL）** 散布：組建設定含 `--enable-version3` 時為 GPLv3，否則為 GPLv2 以上。實際的組建設定可以執行 `ffmpeg -version`，看 `configuration:` 那一行。

- 授權全文：GPLv3 <https://www.gnu.org/licenses/gpl-3.0.html>、GPLv2 <https://www.gnu.org/licenses/old-licenses/gpl-2.0.html>（FFmpeg 的授權說明：<https://ffmpeg.org/legal.html>）
- YT 下載器以「另外執行一個程式」的方式呼叫 FFmpeg（不連結進 App 的程式碼），FFmpeg 的檔案原封不動放在 App 的 `bin/` 資料夾。
- **原始碼取得方式**：
  - FFmpeg 原始碼：<https://github.com/FFmpeg/FFmpeg>（執行 `ffmpeg -version` 可看到組建所用的版本／commit）。
  - Windows 版的組建腳本與各函式庫版本：<https://github.com/yt-dlp/FFmpeg-Builds>（每個組建的 Release 頁面都列出對應的原始碼版本）。
  - macOS 版的組建說明與腳本：<https://ffmpeg.martin-riedl.de>。
  - 如果上述連結失效、或你需要和某一版安裝檔完全對應的原始碼，請到 [GitHub Issues](https://github.com/Archer8685/yt-dl/issues) 提出，我們會提供。

## App 內含的 Python 元件

| 元件 | 用途 | 授權 |
| --- | --- | --- |
| [yt-dlp](https://github.com/yt-dlp/yt-dlp) | 解析與下載影片 | Unlicense（公眾領域） |
| [yt-dlp-ejs](https://github.com/yt-dlp/ejs) | yt-dlp 解 YouTube 簽章用的 JavaScript | Unlicense；內含的 JavaScript 套件依各自授權（MIT、ISC） |
| [Qt for Python（PySide6、Shiboken6）](https://doc.qt.io/qtforpython-6/)與 [Qt 6](https://www.qt.io) | 桌面介面 | **LGPL 第 3 版**（見下方說明） |
| [Flask](https://flask.palletsprojects.com)、Werkzeug、Jinja2、MarkupSafe、itsdangerous、Click | 本機下載引擎（HTTP API） | BSD-3-Clause |
| [Blinker](https://github.com/pallets-eco/blinker) | Flask 的訊號機制 | MIT |
| [Requests](https://requests.readthedocs.io) | 網路連線 | Apache-2.0 |
| [urllib3](https://github.com/urllib3/urllib3) | 網路連線 | MIT |
| [certifi](https://github.com/certifi/python-certifi) | 憑證清單 | MPL-2.0 |
| [charset-normalizer](https://github.com/jawah/charset_normalizer) | 文字編碼判斷 | MIT |
| [idna](https://github.com/kjd/idna) | 國際化網域名稱 | BSD-3-Clause |
| [Brotli](https://github.com/google/brotli) | 解壓縮 | MIT |
| [websockets](https://github.com/python-websockets/websockets) | yt-dlp 的部分網站支援 | BSD-3-Clause |
| [pycryptodomex](https://www.pycryptodome.org) | yt-dlp 的部分網站支援（解密） | BSD-2-Clause／公眾領域 |
| [Mutagen](https://github.com/quodlibet/mutagen) | 寫入音訊檔的封面與中繼資料 | GPL 第 2 版或更新版本 |
| [Send2Trash](https://github.com/arsenetar/send2trash) | 把刪除的檔案移到資源回收筒（v1.3.0 起） | BSD-3-Clause |
| [PyObjC](https://github.com/ronaldoussoren/pyobjc)（僅 macOS） | macOS 原生外觀 | MIT |
| [Python](https://www.python.org) 執行環境 | 執行 App | PSF License |
| [PyInstaller](https://pyinstaller.org) 啟動程式 | 把 App 打包成執行檔 | GPL 第 2 版，附「bootloader 例外」（打包出的程式不受 GPL 約束） |

### Qt／PySide6（LGPLv3）

- 授權全文：<https://www.gnu.org/licenses/lgpl-3.0.html>（Qt 的授權說明：<https://www.qt.io/licensing/open-source-lgpl-obligations>）
- 原始碼：Qt <https://code.qt.io/cgit/qt/qtbase.git/>；Qt for Python <https://code.qt.io/cgit/pyside/pyside-setup.git/>
- App 使用未修改的 Qt 與 PySide6 動態函式庫，放在 App 資料夾裡（Windows：安裝資料夾的 `_internal\PySide6`；macOS：`YT 下載器.app/Contents/Frameworks`），可以自行替換成相容的版本。

### Mutagen（GPLv2+）

- 授權全文：<https://www.gnu.org/licenses/old-licenses/gpl-2.0.html>
- 原始碼：<https://github.com/quodlibet/mutagen>，或 PyPI 上對應版本的原始碼套件 <https://pypi.org/project/mutagen/#files>

## 授權全文連結

| 授權 | 全文 |
| --- | --- |
| MIT | <https://opensource.org/license/mit> |
| Unlicense | <https://unlicense.org> |
| BSD-2-Clause／BSD-3-Clause | <https://opensource.org/license/bsd-2-clause>／<https://opensource.org/license/bsd-3-clause> |
| ISC | <https://opensource.org/license/isc-license-txt> |
| Apache-2.0 | <https://www.apache.org/licenses/LICENSE-2.0> |
| MPL-2.0 | <https://www.mozilla.org/MPL/2.0/> |
| GPLv2／GPLv3 | <https://www.gnu.org/licenses/old-licenses/gpl-2.0.html>／<https://www.gnu.org/licenses/gpl-3.0.html> |
| LGPLv3 | <https://www.gnu.org/licenses/lgpl-3.0.html> |
| PSF License | <https://docs.python.org/3/license.html> |
