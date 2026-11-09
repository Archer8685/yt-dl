# YT Downloader User Guide

[中文版](USER_GUIDE.md)

YT Downloader is a desktop app for Windows and macOS. It downloads videos, music, subtitles and thumbnails from YouTube and 1,000+ other websites.

The app's name appears as **YT 下載器** in the Start menu, on the desktop and in the macOS Applications folder. The interface itself can be switched to English (see [Settings](#settings)).

> [!IMPORTANT]
> This software is only a tool. It does not provide or host any media content and is not affiliated with YouTube or Google. Only download content you have the right to use, and follow copyright law and each platform's terms of service. See the full [Disclaimer (DISCLAIMER.md)](DISCLAIMER.md).

## Contents

- [Download and install](#download-and-install)
  - [Windows: install and allow the app](#install-windows)
  - [macOS: install and allow the app](#install-macos)
  - [Update the app](#update-the-app)
  - [Uninstall and remove everything](#uninstall)
- [Download videos](#download-videos)
- [Send a page from your browser in one click (bookmarklet)](#bookmarklet)
- [Download queue](#download-queue)
- [Keep running in the system tray and quit completely](#tray)
- [Settings](#settings)
- [FAQ](#faq)

## Download and install

Get the latest version from [Releases](https://github.com/Archer8685/yt-dl/releases/latest). yt-dlp, FFmpeg and Deno are built in, so you don't need to install anything else.

| Your computer | Download this file | Requirements |
| --- | --- | --- |
| Windows 10/11 | [`YT-Downloader-Setup-Windows.exe`](https://github.com/Archer8685/yt-dl/releases/latest/download/YT-Downloader-Setup-Windows.exe) | 64-bit (x64) PC |
| macOS (Apple silicon) | [`YT-Downloader-macOS-AppleSilicon.dmg`](https://github.com/Archer8685/yt-dl/releases/latest/download/YT-Downloader-macOS-AppleSilicon.dmg) | M1 or later Mac, macOS 14 or later |

- "Source code (zip)" and "Source code (tar.gz)" at the bottom of the Release page are the source code for developers. **They are not the app. Don't download them.**
- **Intel Macs are not supported.** Not sure which Mac you have? Click the Apple menu  → "About This Mac". If "Chip" says **Apple M1, M2, M3…**, you can use the app. If it says "Processor … Intel", it's an Intel Mac and the app won't run on it.
- **Why do I see warnings?** The app isn't signed with a paid code-signing certificate (Windows) or notarized by Apple (macOS), so the first time you download and open it, your system warns that it can't verify the publisher. This doesn't mean the file has a virus. The steps below show how to allow it. To check that the file hasn't been tampered with, see [Check that the download is intact](#verify-download).
- **The first time you open the app** it shows a usage notice. Click "I understand and agree" to continue; "Exit" closes the app. You'll only be asked once (unless the notice changes significantly).

<a id="install-windows"></a>

### Windows: install and allow the app

1. **Your browser warns about the download**: Chrome or Edge may say the file "isn't commonly downloaded" or "could be dangerous".
   - Edge: hover over the download, click "…" → "Keep" → "Show more" → "Keep anyway".
   - Chrome: click "Keep" in the download list (or "…" → "Download suspicious file").
2. **Run the installer**: double-click `YT-Downloader-Setup-Windows.exe`. If a blue "**Windows protected your PC**" screen (SmartScreen) appears, click "**More info**" → "**Run anyway**". The publisher shows as "Unknown publisher" because the app isn't digitally signed.
3. Read the usage notice, choose "I accept the agreement", and finish the setup. Then open "YT 下載器" from the Start menu or the desktop. By default the app is installed only for the current user, so no administrator rights are needed. The installer shows English or Chinese automatically, based on your Windows language.
4. **Your antivirus deleted or quarantined the app**: programs packaged with PyInstaller are sometimes flagged by mistake.
   - Windows Security (the built-in antivirus): open "Windows Security" → "Virus & threat protection" → "Protection history", find the quarantined YT Downloader item → "Actions" → "Restore". Then go to "Virus & threat protection settings" → "Manage settings" → "Exclusions" → "Add or remove exclusions" and add the install folder (by default `%LOCALAPPDATA%\Programs\YT-Downloader`).
   - Other antivirus software: restore the file from its quarantine and add the install folder above to its exceptions (allow list).
   - If the app still won't open after restoring it, run the installer again.

<a id="verify-download"></a>

**Check that the download is intact (optional)**: every Release includes `SHA256SUMS.txt`, which lists the SHA-256 checksum of each file.

- Windows: in the folder with the installer, hold Shift, right-click → "Open in Terminal" (or PowerShell), then run
  `Get-FileHash .\YT-Downloader-Setup-Windows.exe -Algorithm SHA256`
- macOS: open Terminal and run `shasum -a 256 ~/Downloads/YT-Downloader-macOS-AppleSilicon.dmg`

If the result matches the value for the same file name in `SHA256SUMS.txt` (upper or lower case doesn't matter), the file is complete and hasn't been tampered with.

<a id="install-macos"></a>

### macOS: install and allow the app

1. Open the downloaded `YT-Downloader-macOS-AppleSilicon.dmg` and drag "YT 下載器" into the Applications folder (when updating, choose "Replace").
2. **Double-click the app once first**: in Applications, double-click "YT 下載器". macOS says it "can't be opened", "the developer cannot be verified", or "Apple could not verify … is free of malware". Click "**Done**" (or "OK"). You must do this step first, or the button in the next step won't appear.
3. **Allow it in System Settings**: open "System Settings" → "**Privacy & Security**", scroll down to "Security", where you'll see that "YT 下載器" was blocked. Click "**Open Anyway**", enter your Mac login password, and click "Open Anyway" again. From then on the app opens normally.
   - **macOS 15 (Sequoia) and later**: you must use the System Settings steps above. The old shortcut of right-clicking the app → "Open" no longer works.
   - **macOS 14 (Sonoma)**: you can use the steps above, or in Finder's Applications folder right-click (or Control-click) the app → "Open" → click "Open" again in the dialog.
4. **Only** if you see "'YT 下載器' is damaged and can't be opened. You should move it to the Trash." (the download was flagged as quarantined, which happens with some browsers and unzip tools), open Terminal, run the command below once, and then open the app again:

   ```bash
   xattr -dr com.apple.quarantine "/Applications/YT 下載器.app"
   ```

- The first time you use some features, macOS may ask whether to allow YT 下載器 to "find devices on your local network". The app only talks to itself on this computer, so "Allow" or "Don't Allow" makes no difference to downloads.
- If your Mac has an Intel chip, the app in the dmg won't run (it says it can't be opened, or quits right away). There is no Intel version at the moment.

### Update the app

- **Wait for running downloads to finish** (or pause them in the "Queue") before installing a new version. The Windows installer asks you to close the running app; unfinished downloads can be continued later with "Resume" in the "Queue".
- Windows: just run the new installer. macOS: drag the new version into Applications and choose "Replace". You may need to allow the new version once more the first time you open it (see the steps above).
- Settings, cookies.txt and download history are kept. See the [changelog](CHANGELOG.md) for what changed in each version.

<a id="uninstall"></a>

### Uninstall and remove everything

**Windows**: go to "Settings → Apps → Installed apps", find "YT 下載器" → "Uninstall". At the end you'll be asked "**Also delete your settings and cookies?**":

- "Yes": also deletes your download location setting, cookies.txt (your sign-in data), the auto-updated yt-dlp, log files, and the app's interface preferences.
- "No": keeps this data, so a later reinstall picks it up again.
- Either way, **your downloaded videos are NOT deleted** (by default they're in `YT-Downloads` inside your Downloads folder).

**macOS**: drag "YT 下載器" from Applications to the Trash. macOS doesn't delete the settings and cookies for you. To remove everything, also delete these two items (in Finder press ⌘⇧G, paste the path and press Return to open it):

- `~/Library/Application Support/YT-Downloader` (download location setting, cookies.txt, auto-updated yt-dlp, log files)
- `~/Library/Preferences/com.ytdownloader.NativeApp.plist` (interface preferences; if the name is different, look for a plist with `YTDownloader` in its name)

**Why delete cookies.txt?** It's effectively your account sign-in. On a shared computer, or before handing your computer to someone else, be sure to delete it, or delete the cookies in the app's "Settings" first.

## Download videos

Choose "Add Download" in the sidebar.

1. **Paste a link**: paste the video link into the box at the top (or click "Paste"), then click "Analyze" or press Enter.
   - `https://` is added for you if you leave it out, and a bare 11-character YouTube video ID works too.
   - **Auto-paste**: copy a video link in your browser, then open or switch back to the app, and the link is pasted and analyzed automatically. Only links to videos on supported sites (or links straight to media files) are pasted, not ordinary web pages. If you're already setting up another video, the app shows "New link detected" under the address box with "Analyze" and "Ignore" instead of replacing it. You can turn auto-paste off in "Settings → General".
   - **Several links at once**: paste several lines (one link per line) or use batch add. You'll get a list to tick, and each link becomes its own download using the current options. Up to 100 links at a time.
   - You can also drag a link onto the window, or send it from your browser with the [bookmarklet](#bookmarklet).
   - Analyzing a long playlist can take a while; click "Cancel" to stop.
2. **Choose what to download**: once analyzed, the title, thumbnail and length are shown. Then choose:
   - **Mode**: video + audio, video only, audio only, subtitles, thumbnail
   - **Quality**: best, 4K, 1440p, 1080p, 720p, 480p, 360p (if the video doesn't go that high, the best available is used)
   - **Video format**: MP4, MKV, WebM, MOV
   - **Audio format** (audio only): MP3, M4A, Opus, FLAC, WAV, original (no conversion), plus audio quality
3. **Advanced options** (expandable): codec preference, FPS, HDR, multiple audio languages, subtitles (including auto-generated and translated ones), downloading only part of a video or splitting by chapter, removing sponsor segments with SponsorBlock, embedding metadata and cover art, file name template, cookies, proxy and speed limit. Advanced options remember your last settings.
4. Click "Download". The download is added to the "Queue".

**Playlists**: if the link contains a playlist, turn on "Download the whole playlist when the link contains one" and analyze. The videos in the playlist are listed. Tick the ones you want, filter with "Search title or uploader", or type a range (for example `1-10, 15`) and click "Apply range".

> Each time you open the app, "Add Download" starts from "Settings → Download defaults". Changing options on this page for one download doesn't change your defaults.

**Keyboard shortcuts** (on a Mac, use ⌘ instead of Ctrl): Ctrl+L goes to the address box, Ctrl+Enter starts the download, Ctrl+1/2/3 switches pages, Ctrl+, opens Settings, and Esc cancels analyzing.

<a id="bookmarklet"></a>

## Send a page from your browser in one click (bookmarklet)

Add a special bookmark to your browser. While watching a video, click it once to send the current page's address to YT Downloader's "Add Download" page and analyze it. **The app only fills in the link and analyzes it. It never starts downloading by itself**; what to download, and whether to download at all, is up to you.

**Setup** (works in Chrome, Edge, Firefox and Safari):

1. Show the bookmarks bar: Ctrl+Shift+B on Windows, ⌘⇧B on macOS (Safari: "View → Show Favorites Bar").
2. Right-click the bookmarks bar → "Add page" (Chrome) / "Add favorite" (Edge) / "Add Bookmark" (Firefox). In Safari, first add any page to Favorites, then right-click it → "Edit Address".
3. Name it "Send to YT Downloader", paste this whole line as the address (URL), and save:

   ```text
   javascript:location.href='ytdl://add?url='+encodeURIComponent(location.href)
   ```

**How to use it**:

1. After installing, **open the app at least once** so your browser recognizes `ytdl://` links (on macOS, the app must be in the Applications folder).
2. Open the video page you want and click "Send to YT Downloader" on the bookmarks bar.
3. **The first time, your browser asks whether to open "YT 下載器"** (for example, "Open YT 下載器?"). Click "Open". If you tick "Always allow…", it won't ask again.
4. The app comes to the front, fills the link into "Add Download" and analyzes it. If the app isn't running, it starts automatically. If you're in the middle of setting up another video, the app asks whether to switch to the new link instead of replacing what you're doing.

Nothing happens when you click it? Make sure the app is installed and has been opened at least once. On Windows you can run the installer again (it registers `ytdl://` again). If you click it on a video list or home page, it sends that page's address, so open the video itself first.

## Download queue

Choose "Queue" in the sidebar (the number next to it is how many downloads are in progress). Each download shows its progress, file size, speed and time left; waiting downloads show how many are ahead of them.

| Button | When it appears | What it does |
| --- | --- | --- |
| Pause | Downloading | Pauses the download and keeps what's been downloaded; click "Resume" later to continue |
| Resume | Paused, failed or interrupted | Continues from where it stopped (shown as "Retry" when there's nothing to continue from) |
| Cancel | Waiting or downloading | Stops the download and discards the unfinished part; it can't be resumed later. If part of it is already downloaded, the app asks first and suggests "Pause" instead |
| Open | Finished | Opens the file in your default player (you can also double-click the row) |
| Show in Explorer (macOS: Show in Finder) | There are downloaded files | Opens the folder containing the file |
| Retry failed items | A playlist finished with some videos failed | Downloads again only the videos that didn't succeed |
| Remove | Not downloading | Removes it from the list. **Downloaded files stay on your computer** unless you choose "Delete with files", which moves them to the Recycle Bin (macOS: Trash) |

- When something goes wrong, the download shows a short explanation and a button for the most likely fix (for example "Set up cookies" or "Analyze again"). "Details" shows the original error message, which you can copy, and "FAQ" opens the matching entry below.
- A download marked in orange "Done, but some steps failed" was downloaded, but a step such as embedding the cover failed. A playlist shows how many videos are done (for example "Done 180/200"); expand it to see which failed.
- Buttons at the top of the page: "Pause all", "Resume all", "Retry all" and "Clear completed" (removes finished downloads from the list; the files stay where they are).
- If you close the window while downloading, the app asks first (if you set it to keep running in the system tray, downloads continue in the background; see the next section).
- If the disk with your download folder runs low on space (under 2 GB, or not enough for the file), downloads stop automatically to protect your system drive. Finished files are kept.

<a id="tray"></a>

## Keep running in the system tray and quit completely

The app can keep downloading after you close its window: in "Settings → General", change "When closing the window" to "**Minimize to the system tray and keep downloading**" (the default is "Quit the app").

- **Where's the icon?** On Windows, in the system tray (notification area) at the bottom right of the taskbar (click "^" if you don't see it). On macOS, in the menu bar at the top of the screen.
- **Hover over the icon** to see the current progress (for example "2 downloading · 45%"). Right-click the icon (on macOS, click it) for the menu: Show window, current progress, Pause all, Resume all, Quit.
- **When a download finishes or fails**, a system notification appears; click it to open the app at that download. There's no notification while the app is in front. macOS asks the first time whether to allow notifications; if you don't get any, go to "System Settings → Notifications → YT 下載器" and turn on "Allow notifications". On Windows, check "Settings → System → Notifications".
- **To quit completely**, click "**Quit**" in the tray (menu bar) icon's menu. If downloads are running, the app asks first; unfinished downloads can be continued next time with "Resume" in the "Queue". On macOS you can also press ⌘Q while the app window is in front.
- Only one copy of YT Downloader runs at a time: opening it again (or clicking the bookmarklet) brings up the existing window instead of opening a second one.

## Settings

Choose "Settings" in the sidebar (it shows a badge when a yt-dlp update or a new app version is available).

| Section | What you can do |
| --- | --- |
| General | Turn "Auto-paste video links from the clipboard" on or off; choose whether closing the window quits the app or [minimizes it to the system tray](#tray); set how many downloads run at the same time (1–5) |
| Appearance | Theme: system / light / dark; text size: small / medium / large (scales the whole interface); language: system / 中文（繁體） / English (restart the app to apply) |
| Download defaults | The mode, quality, video format, audio format, audio quality and whole-playlist option used each time the app opens; changes apply immediately. "Reset all preferences…" restores appearance, download defaults and advanced options to how they were right after installing (it asks first; your storage location, cookies.txt and downloaded files are not affected) |
| Storage location | Shows the download folder and free space; "Change…", "Open in Explorer (Finder)", "Use default folder" |
| YouTube Premium | Uses your current cookies to check whether your account is signed in and has Premium, and shows when it was last checked; "Check again", "Update cookies.txt…" |
| Download components | Status of yt-dlp and FFmpeg; "Check for updates", then "Restart to apply" once a new version has downloaded |
| About | App version (and a notice when a new version is available), a summary of the usage notice, user guide, report a problem, license (MIT) and third-party licenses |

<a id="faq"></a>

## FAQ

When the app shows an error, clicking "FAQ" (or "How to fix") jumps straight to the matching entry below.

### Installing and opening

**My browser says the file "isn't commonly downloaded", Windows says "Windows protected your PC", or my antivirus deleted the file?**
All of these happen because the app has no paid digital signature. It doesn't mean there's a virus. See [Windows: install and allow the app](#install-windows) for how to allow it.

**macOS says the app "can't be opened", "the developer cannot be verified", or that it's "damaged"?**
See [macOS: install and allow the app](#install-macos): double-click it once, then click "Open Anyway" in "System Settings → Privacy & Security". You only need the Terminal command if it says "damaged".

**Can I use it on an Intel Mac?**
Intel Macs are not supported at the moment; there's only a version for Apple silicon (M1 and later). To check: click the Apple menu  → "About This Mac".

**When I open the app, it says "port 8765 is already in use" or "the download engine couldn't start"?**
The app's built-in download engine uses port 8765 on this computer. Usually another copy of YT Downloader is already running (check the system tray or menu bar), or another program is using that port. Close the other copy of YT Downloader (or restart your computer) and open the app again. If that doesn't help, please [report the problem](#report) and attach the log file.

### Error messages while downloading

<a id="err-invalid-url"></a>

**"Please enter a valid web address"**
The link must start with `http://` or `https://`. Copy the whole address from your browser's address bar, or copy the link from the video's "Share" button.

<a id="err-unsupported-url"></a>

**"This website isn't supported, or there is no video on this page"**
The website isn't on yt-dlp's list of supported sites, or you pasted a page with no video on it, such as a home page, search results or a channel page. Open the video itself and copy its address. See [yt-dlp Supported sites](https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md) for the list of sites.

<a id="err-video-unavailable"></a>

**"This video can't be found"**
The uploader may have deleted the video or made it private, or the link may be missing some characters. Open the same link in your browser to check that it plays.

<a id="err-private-video"></a>

**"This is a private video"**
Only accounts invited by the uploader can watch a private video. If your account has access, sign in as described in [Set up cookies](#cookies) and try again. Without access, it can't be downloaded.

<a id="err-age-restricted"></a>

**"This video is age-restricted"**
YouTube requires a signed-in, age-verified account to watch it. Use your own account as described in [Set up cookies](#cookies), then try again.

<a id="err-members-only"></a>

**"This video is for channel members only"**
Only accounts with a membership to that channel can watch it. If you're a member, use that account as described in [Set up cookies](#cookies), then try again.

<a id="err-geo-blocked"></a>

**"This video isn't available in your region"**
The uploader or platform has limited which countries or regions can watch it, so it can't be downloaded where you are. The app doesn't provide or recommend any way around regional restrictions (see the [Disclaimer](DISCLAIMER.md)).

<a id="err-bot-check"></a>

**"YouTube is asking for verification" (Sign in to confirm you're not a bot)**
YouTube sometimes asks you to prove you're not a bot, usually after many downloads in a short time. Use your own account as described in [Set up cookies](#cookies), and slow down (for example, run fewer downloads at the same time).

<a id="err-live-not-started"></a>

**"This live stream hasn't started yet"**
This is a scheduled live stream or premiere; it can be downloaded once it starts. For the most complete copy, download it after the stream ends and YouTube has finished processing it.

<a id="err-http-403"></a>

**"The server refused the download (the link may have expired)" (HTTP Error 403)**
Video download links expire; after a long pause or a network drop they stop working. Click "**Resume**" in the "Queue" and the app gets a fresh link and continues. If it keeps happening, YouTube has usually changed something: go to "Settings → Download components", click "Check for updates" to update yt-dlp, then "Restart to apply" (see [Downloads fail after YouTube changes something](#youtube-changed)). The error may also offer "Apply the new yt-dlp and retry", which does this for you.

<a id="err-rate-limited"></a>

**"Too many requests in a short time" (HTTP Error 429)**
The website has temporarily limited your connections. Wait a few minutes to an hour, then try again. Run fewer downloads at the same time, and avoid downloading a very long playlist all at once.

<a id="err-format-unavailable"></a>

**"The selected quality or format is no longer available"**
The video's available qualities have changed (for example, the uploader re-uploaded it, or a long time passed between analyzing and downloading). Go back to "Add Download", analyze the link again, and choose the quality again.

<a id="err-ffmpeg-failed"></a>

**"The download finished, but a processing step such as merging video and audio failed"**
The video was downloaded, but merging video and audio, converting, or embedding the cover or metadata failed. The original files are kept in the download folder. Common causes: not enough disk space, the file is open in a player or being scanned by antivirus, or the file name is too long. Fix the cause and download again; you can also try a different video format (for example MKV) or turn off "Embed metadata and cover art".

<a id="err-ffmpeg-missing"></a>

**"FFmpeg can't be found"**
FFmpeg is built into the app. If it can't be found, antivirus software has usually quarantined it (`bin\ffmpeg.exe`). Restore it from the quarantine and add an exception (see step 4 of [Windows: install and allow the app](#install-windows)), or run the installer again. "Settings → Download components" shows FFmpeg's status.

<a id="err-network"></a>

**"Can't reach the website" / "The network connection timed out"**
Check that you're online and can open the website in your browser. Work or school networks may block video sites, and VPN or firewall software can also affect the connection. The app retries a few times on short network problems; after that, click "Resume" in the "Queue".

<a id="err-proxy"></a>

**"Can't connect to the proxy you set"**
You set a proxy in "Add Download → Advanced options → Network", but the app can't connect to it. Check that the proxy address and port are correct and that the proxy program is running. If you don't need a proxy, clear the field.

<a id="err-cookie-browser"></a>

**"Can't read the browser's cookies"**
When you choose "Read cookies directly from the browser", Chrome and Edge lock their cookie file while they're open, and newer versions of Chrome and Edge on Windows also encrypt cookies so other programs can't read them. Use one of these instead:

1. Close Chrome/Edge completely (including any background process in the system tray) and try again.
2. Choose Firefox instead (it can be read while it's open).
3. Use an exported cookies.txt (the most reliable); see [Set up cookies](#cookies).

<a id="err-cookies-invalid"></a>

**"The cookies.txt file isn't in the right format"**
The file you imported isn't a "Netscape format" cookies.txt exported by a browser extension, or it's incomplete. Export it again as described in [Set up cookies](#cookies), and don't edit the file yourself.

<a id="err-disk-full"></a>

**"The disk is full, so the download stopped"**
When the disk with your download folder has less than 2 GB free, or not enough room for the file, the app stops downloading automatically to protect your system drive. Free up space, or go to "Settings → Storage location" → "Change…" to save to a drive with more space, then click "Resume" in the "Queue". Merging video and audio may temporarily need about twice the file size.

<a id="err-download-dir"></a>

**"The download location can't be accessed right now"**
The external drive, USB stick or network drive holding your download folder isn't connected, or you don't have permission to write to the folder. Connect the drive and try again, or go to "Settings → Storage location" → "Change…" to choose another folder (or "Use default folder").

<a id="err-engine"></a>

**"The download engine ran into an error"**
The app's built-in download engine hit an unexpected problem. Try again first; if that doesn't work, restart the app. If it keeps happening, please [report the problem](#report) and attach the log file so we can find the cause.

<a id="err-unknown"></a>

**"The download failed" (other errors)**
Open "Details" next to the error to see the original error message. First try clicking "Resume" in the "Queue" or analyzing the link again, and update yt-dlp in "Settings → Download components". If it still fails, please [report the problem](#report) with the details and the log file.

<a id="cookies"></a>

### Set up cookies (videos that need sign-in, Premium)

For age-restricted, members-only or private videos, or when YouTube asks for verification, the app needs cookies from **your own account** to download.

1. In your computer's browser, **sign in to your YouTube account first** and make sure the video plays.
2. Install a browser extension that exports cookies (for example "Get cookies.txt LOCALLY"). On a youtube.com page, click the extension and export the cookies.txt for `youtube.com` (Netscape format).
3. In the app, go to "Settings → YouTube Premium", click "Update cookies.txt…" and choose the file you exported. The app checks your account automatically, and turns on "Premium high bitrate" if it detects Premium.
   - You can also switch to reading cookies directly from the browser in "Add Download → Advanced options → Network" (this often fails for Chrome and Edge on Windows; see [Can't read the browser's cookies](#err-cookie-browser)).
4. When the cookies expire (the app says you're not signed in, or verification is requested again), export them again and click "Update cookies.txt…" once more.

> [!WARNING]
> **cookies.txt is effectively your account sign-in.** Anyone who has it can sign in as you.
> - Don't send cookies.txt to anyone, and **never attach it to a GitHub issue or paste its contents**.
> - cookies.txt stays on your computer; the app never uploads it anywhere. On a shared computer, delete the cookies in the app when you're done, or choose to delete them when uninstalling (see [Uninstall and remove everything](#uninstall)).
> - Only use your own account, and only download content that account is allowed to watch.

### Other questions

<a id="youtube-changed"></a>

**Downloads fail after YouTube changes something?**
The app checks for a new yt-dlp when it starts and every 6 hours, downloads it in the background, and uses it the next time it opens. You can also go to "Settings → Download components", click "Check for updates" and then "Restart to apply" to use it right away. If a new version fails to load, the app automatically falls back to its built-in version.

**Where are my downloads and settings stored?**
- Downloaded files: by default in `YT-Downloads` inside your Downloads folder. You can change this in "Settings → Storage location".
- Download location setting, cookies.txt, the auto-updated yt-dlp and the log file `engine.log`:
  - Windows: `%LOCALAPPDATA%\YT-Downloader` (paste it into File Explorer's address bar to open it)
  - macOS: `~/Library/Application Support/YT-Downloader` (the Library folder is hidden by default: in Finder press ⌘⇧G, paste the path and press Return)

**A download was interrupted. What now?**
If the connection drops or the stream link expires, the app reconnects and continues automatically (up to 3 times). Downloads that still fail, or that were interrupted by closing the app, keep the part already downloaded; click "Resume" in the "Queue" to continue. For long downloads, consider turning off your computer's automatic sleep.

**A large file finished downloading but stays on "Processing" for a long time?**
Merging video and audio and writing metadata and cover art make FFmpeg rewrite the whole file. The bigger the file, the longer it takes (about half an hour per step for a 100 GB file). Progress is shown on screen; please be patient and don't close the app.

<a id="report"></a>

**How do I report a problem?**
Go to [GitHub Issues](https://github.com/Archer8685/yt-dl/issues/new/choose), choose the bug report, and fill in the app version, your system and chip, the video link and the error message. Attaching the log file `engine.log` (see the previous questions for where it is) helps a lot:

- **Open it and look before uploading**: the log may contain links you downloaded and folder paths (including your computer's user name). Delete anything you don't want to make public.
- **Don't attach cookies.txt**, and don't paste its contents.

## Disclaimer

This software is provided "as is", without any warranty. You are responsible for making sure you have the right to download and use the content, and for how you use the software. See [DISCLAIMER.md](DISCLAIMER.md) for the full text (in English and Chinese).

This software is released under the [MIT License](LICENSE). The third-party components it includes (yt-dlp, FFmpeg, Qt and others) are provided under their own licenses; see [Third-party notices](THIRD_PARTY_NOTICES.md).
