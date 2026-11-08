"""把下載器打包成桌面 App（內建 FFmpeg / ffprobe / Deno，不用裝 Python）。

用法：  python build_app.py
需要：  pip install -r requirements-app.txt
產出：
  Windows  dist/YT-Downloader-Setup-Windows.exe   安裝精靈（需要 Inno Setup 6；沒有時只產出 dist/YT-Downloader/ 資料夾）
  macOS    dist/YT-Downloader-macOS-<arch>.dmg     拖進「應用程式」即可

GitHub Actions（.github/workflows/release.yml）會在 Windows 與 macOS 上執行這支腳本並發布到 Releases。
App 版本號取自 VERSION 檔（可用環境變數 YTDL_APP_VERSION 覆寫），會寫進安裝程式的版本欄位。
"""
from __future__ import annotations

import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BUILD = ROOT / "build"
DIST = ROOT / "dist"
VENDOR = BUILD / "vendor"
BIN = VENDOR / "bin"
NAME = "YT-Downloader"            # 執行檔 / 資料夾名稱（英數，避免各平台路徑編碼問題）
DISPLAY = "YT 下載器"              # 使用者看到的名稱：開始功能表、桌面捷徑、macOS App
BUNDLE_ID = "io.github.archer8685.ytdl"
VERSION = os.environ.get("YTDL_APP_VERSION") or (ROOT / "VERSION").read_text(encoding="utf-8").strip()

DENO = "https://github.com/denoland/deno/releases/latest/download/deno-{triple}.zip"
FFMPEG_WIN = ("https://github.com/yt-dlp/FFmpeg-Builds/releases/download/latest/"
              "ffmpeg-master-latest-win64-gpl-shared.zip")
FFMPEG_MAC = "https://ffmpeg.martin-riedl.de/redirect/latest/macos/{arch}/release/{tool}.zip"
INNO_ZH = "https://raw.githubusercontent.com/jrsoftware/issrc/main/Files/Languages/ChineseTraditional.isl"
ISCC_PATHS = [r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe", r"C:\Program Files\Inno Setup 6\ISCC.exe"]


GITHUB_RELEASE_URL = re.compile(
    r"https://github\.com/([^/]+)/([^/]+)/releases/(?:latest/download|download/([^/]+))/([^/?#]+)$")


def _fetch(url: str, out: Path, headers: dict[str, str] | None = None):
    headers = {"User-Agent": "yt-dl-build", **(headers or {})}
    # 優先用系統 curl：Windows / macOS 內建，且使用系統憑證（公司網路的 SSL 檢查也能通過）
    if shutil.which("curl"):
        cmd = ["curl", "-fsSL", "--retry", "3", "-o", str(out), url]
        for k, v in headers.items():
            cmd[1:1] = ["-H", f"{k}: {v}"]
        subprocess.run(cmd, check=True)
    else:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=300) as r, out.open("wb") as f:
            shutil.copyfileobj(r, f)


def _github_api_asset(url: str, tmp_json: Path) -> str | None:
    """GitHub Releases 的下載網址 → 同一個檔案的 API 下載網址。

    github.com/.../releases/download/ 偶爾會一直回 504，API 的下載通常還是正常的。
    """
    m = GITHUB_RELEASE_URL.match(url)
    if not m:
        return None
    owner, repo, tag, name = m.groups()
    api = f"https://api.github.com/repos/{owner}/{repo}/releases/" + (f"tags/{tag}" if tag else "latest")
    _fetch(api, tmp_json, {"Accept": "application/vnd.github+json"})
    assets = json.loads(tmp_json.read_text(encoding="utf-8")).get("assets") or []
    tmp_json.unlink()
    asset = next((a for a in assets if a.get("name") == name), None)
    return asset and asset["url"]


def download(url: str, dest: Path) -> Path:
    if dest.exists():
        return dest
    print(f"下載 {url}", flush=True)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp")
    # GitHub 的下載偶爾會暫時回 504 或連線中斷：多試幾次、每次等久一點；
    # 從第二次起改走 GitHub API 下載同一個檔案
    attempts = 5
    for i in range(1, attempts + 1):
        try:
            api_url = _github_api_asset(url, dest.with_suffix(".json")) if i > 1 else None
            if api_url:
                print(f"download via GitHub API: {api_url}", flush=True)
                _fetch(api_url, tmp, {"Accept": "application/octet-stream"})
            else:
                _fetch(url, tmp)
            break
        except (subprocess.CalledProcessError, OSError, ValueError) as e:
            if i == attempts:
                raise
            wait = 15 * i
            print(f"download failed ({e}); retry {i}/{attempts - 1} in {wait}s", flush=True)
            time.sleep(wait)
    tmp.replace(dest)
    return dest


def extract(archive: Path, want):
    """從壓縮檔取出 want(path, name) 為真的檔案，全部放到 BIN。"""
    with zipfile.ZipFile(archive) as z:
        for info in z.infolist():
            name = info.filename.rsplit("/", 1)[-1]
            if info.is_dir() or not want(info.filename, name):
                continue
            out = BIN / name
            with z.open(info) as src, out.open("wb") as dst:
                shutil.copyfileobj(src, dst)
            out.chmod(out.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def fetch_tools() -> str:
    """下載目前平台的 ffmpeg / ffprobe / deno，回傳產出檔名的平台標籤。"""
    shutil.rmtree(BIN, ignore_errors=True)
    BIN.mkdir(parents=True)
    machine = platform.machine().lower()
    if sys.platform == "win32":
        ff = download(FFMPEG_WIN, VENDOR / "ffmpeg-win64.zip")
        extract(ff, lambda path, name: "/bin/" in path and (name in ("ffmpeg.exe", "ffprobe.exe")
                                                             or name.endswith(".dll")))
        extract(download(DENO.format(triple="x86_64-pc-windows-msvc"), VENDOR / "deno-win64.zip"),
                lambda path, name: name == "deno.exe")
        return "Windows"
    if sys.platform == "darwin":
        arch = "arm64" if machine in ("arm64", "aarch64") else "amd64"
        for tool in ("ffmpeg", "ffprobe"):
            extract(download(FFMPEG_MAC.format(arch=arch, tool=tool), VENDOR / f"{tool}-mac-{arch}.zip"),
                    lambda path, name, t=tool: name == t)
        triple = "aarch64-apple-darwin" if arch == "arm64" else "x86_64-apple-darwin"
        extract(download(DENO.format(triple=triple), VENDOR / f"deno-mac-{arch}.zip"),
                lambda path, name: name == "deno")
        return f"macOS-{'AppleSilicon' if arch == 'arm64' else 'Intel'}"
    raise SystemExit("目前只支援在 Windows 或 macOS 上打包")


def check_tools():
    """確認下載的工具能在這台機器上執行（避免打包進壞掉或架構不對的檔案）。"""
    exe = ".exe" if sys.platform == "win32" else ""
    for tool, arg in (("ffmpeg", "-version"), ("ffprobe", "-version"), ("deno", "--version")):
        out = subprocess.run([str(BIN / f"{tool}{exe}"), arg], capture_output=True, text=True, check=True)
        print(f"  {tool}: {out.stdout.splitlines()[0]}")


def bundled_version_file() -> Path:
    """記下打包進去的 yt-dlp 版本：App 只在自動更新下載的版本比它新時才改用更新版。"""
    import yt_dlp
    out = BUILD / "bundled-ytdlp.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yt_dlp.version.__version__, encoding="utf-8")
    return out


# 介面只用到 QtCore / QtGui / QtWidgets / QtNetwork（QtSvg 保留給圖示用）；其他 Qt 模組一律不打包
QT_EXCLUDES = [f"PySide6.{m}" for m in (
    "QtWebEngineCore", "QtWebEngineWidgets", "QtWebEngineQuick", "QtWebChannel", "QtWebSockets", "QtWebView",
    "Qt3DCore", "Qt3DRender", "Qt3DInput", "Qt3DLogic", "Qt3DAnimation", "Qt3DExtras",
    "QtQml", "QtQuick", "QtQuickWidgets", "QtQuickControls2", "QtQuick3D", "QtQuickTest",
    "QtMultimedia", "QtMultimediaWidgets", "QtSpatialAudio", "QtTextToSpeech",
    "QtCharts", "QtDataVisualization", "QtGraphs", "QtGraphsWidgets", "QtPdf", "QtPdfWidgets",
    "QtSql", "QtTest", "QtDesigner", "QtUiTools", "QtHelp", "QtOpenGL", "QtOpenGLWidgets",
    "QtBluetooth", "QtNfc", "QtPositioning", "QtLocation", "QtSensors", "QtSerialPort", "QtSerialBus",
    "QtRemoteObjects", "QtScxml", "QtStateMachine", "QtHttpServer", "QtXml", "QtConcurrent", "QtDBus",
    "QtAxContainer", "QtCanvasPainter",
)] + ["tkinter", "PyQt5", "PyQt6"]

SPEC = """# 由 build_app.py 產生，請勿手動修改
import fnmatch, re, sys

DROP = {drop!r}
KEEP_IMAGEFORMATS = {keep_imageformats!r}
KEEP_PLATFORMS = {keep_platforms!r}
TOOLS_DIR = {tools_dir!r}


def keep(dest, src=""):
    p = dest.replace("\\\\", "/").lower()
    if any(fnmatch.fnmatch(p, pat) for pat in DROP):
        return False
    # PyInstaller 會分析 bin/ 裡 ffmpeg.exe 的相依 DLL，在最上層再放一份（約 180 MB）。
    # 工具只用 bin/ 裡的那份，所以來源在工具資料夾、卻放在最上層的檔案一律不要
    if "/" not in p and src.replace("\\\\", "/").lower().startswith(TOOLS_DIR):
        return False
    stem = re.sub(r"^lib", "", p.rsplit("/", 1)[-1].split(".")[0])
    if "/plugins/imageformats/" in p:
        return stem in KEEP_IMAGEFORMATS
    if "/plugins/platforms/" in p:
        return stem in KEEP_PLATFORMS
    if "/translations/" in p and p.endswith(".qm"):
        return p.endswith("_zh_tw.qm")  # Qt 內建對話框的繁體中文
    return True


# macOS 的毛玻璃側邊欄用 PyObjC（在函式裡才 import，明確列出確保打包進去）
MAC_IMPORTS = ["objc", "AppKit", "Foundation"] if sys.platform == "darwin" else []
a = Analysis([{entry!r}], pathex=[{root!r}], datas={datas!r}, binaries={binaries!r},
             hiddenimports=MAC_IMPORTS, excludes={excludes!r})
before = len(a.binaries) + len(a.datas)
a.binaries = [x for x in a.binaries if keep(x[0], x[1])]
a.datas = [x for x in a.datas if keep(x[0], x[1])]
# 只印 ASCII：這段在 PyInstaller 子程序裡執行，CI 的 Windows 主控台是 cp1252，印中文會讓打包失敗
print(f"build_app: removed {{before - len(a.binaries) - len(a.datas)}} unused Qt files")
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name={name!r}, console=False, icon={icon!r},
          upx=False, codesign_identity=None, entitlements_file=None)
coll = COLLECT(exe, a.binaries, a.datas, name={name!r}, upx=False)
if sys.platform == "darwin":
    app = BUNDLE(coll, name={name!r} + ".app", icon={icon!r}, bundle_identifier={bundle_id!r},
                 info_plist={{"CFBundleDisplayName": {display!r}, "CFBundleShortVersionString": {version!r},
                              "CFBundleVersion": {version!r}, "NSHighResolutionCapable": True,
                              "NSRequiresAquaSystemAppearance": False,
                              "NSLocalNetworkUsageDescription": {local_net!r}}})
"""
# macOS 15 起，程式碰到網路功能時系統可能詢問「允許尋找區域網路上的裝置」；這段文字會顯示在詢問視窗裡
LOCAL_NET_REASON = "YT 下載器的視窗和背景的下載引擎在這台電腦上透過本機連線溝通，不會連到區域網路上的其他裝置。"


def pyinstaller():
    """onedir 視窗程式（原生 Qt 介面 native_app.py）：啟動不用每次解壓，macOS 會產生 .app。"""
    icon = ROOT / "assets" / ("icon.ico" if sys.platform == "win32" else "icon.icns")
    spec = BUILD / f"{NAME}.spec"
    spec.parent.mkdir(parents=True, exist_ok=True)
    spec.write_text(SPEC.format(
        entry=str(ROOT / "native_app.py"), root=str(ROOT), name=NAME, icon=str(icon), bundle_id=BUNDLE_ID,
        display=DISPLAY, version=VERSION, excludes=QT_EXCLUDES,
        datas=[(str(ROOT / "index.html"), "."),  # 引擎的網頁版介面（瀏覽器開 http://127.0.0.1:8765）
               (str(ROOT / "assets" / "icon-128.png"), "assets"),
               (str(ROOT / "assets" / "chevron.png"), "assets"),  # Windows 彈出選單的箭頭
               (str(bundled_version_file()), ".")],
        binaries=[(str(BIN / "*"), "bin")],  # FFmpeg / ffprobe / Deno
        tools_dir=str(BIN.resolve()).replace("\\", "/").lower() + "/",
        # 用不到卻很大的檔案：軟體 OpenGL（約 20 MB）、PDF 引擎（只有 qpdf 圖片外掛會用到）、
        # 虛擬鍵盤輸入法外掛與它拖進來的 QML / Quick（約 15 MB）
        drop=["*/opengl32sw.dll", "*/qt6pdf.*", "*/qtpdf.framework/*",
              "*/platforminputcontexts/*virtualkeyboard*", "*/qt6virtualkeyboard*", "*/qtvirtualkeyboard*.framework/*",
              "*/qt6qml*", "*/qtqml*.framework/*", "*/qt6quick*", "*/qtquick*.framework/*",
              "pyside6/qt6opengl.dll"],
        keep_imageformats=["qjpeg", "qwebp", "qgif", "qico", "qsvg"],  # 縮圖是 JPEG / WebP；PNG 內建
        keep_platforms=["qwindows", "qcocoa", "qoffscreen"],  # qoffscreen：CI 沒有螢幕時的煙霧測試
        local_net=LOCAL_NET_REASON,
    ), encoding="utf-8")
    shutil.rmtree(DIST / NAME, ignore_errors=True)
    shutil.rmtree(DIST / f"{NAME}.app", ignore_errors=True)
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
                    "--distpath", str(DIST), "--workpath", str(BUILD / "pyinstaller"), str(spec)], check=True,
                   env={**os.environ, "PYTHONIOENCODING": "utf-8"})  # 子程序的輸出（含中文路徑）也用 UTF-8


INNO_SCRIPT = r"""
#define AppName "{display}"
#define AppExe "{name}.exe"

[Setup]
AppId={{{{6D0B2E4A-7F3C-4C1E-9B6A-2F5D8E1A9C47}}
AppName={{#AppName}}
AppVersion={version}
AppVerName={{#AppName}} {version}
AppPublisher=Archer8685
AppPublisherURL=https://github.com/Archer8685/yt-dl
AppSupportURL=https://github.com/Archer8685/yt-dl/issues
AppUpdatesURL=https://github.com/Archer8685/yt-dl/releases/latest
DefaultDirName={{autopf}}\{name}
DefaultGroupName={{#AppName}}
DisableProgramGroupPage=yes
; 預設只裝給目前使用者，不需要系統管理員權限；安裝時可改成所有使用者
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir={dist}
OutputBaseFilename={name}-Setup-Windows
SetupIconFile={icon}
UninstallDisplayIcon={{app}}\{{#AppExe}}
UninstallDisplayName={{#AppName}}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes

[Languages]
Name: "zh"; MessagesFile: "{lang}"

[Tasks]
Name: "desktopicon"; Description: "{{cm:CreateDesktopIcon}}"; GroupDescription: "{{cm:AdditionalIcons}}"

[Files]
Source: "{src}\*"; DestDir: "{{app}}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{{autoprograms}}\{{#AppName}}"; Filename: "{{app}}\{{#AppExe}}"
Name: "{{autodesktop}}\{{#AppName}}"; Filename: "{{app}}\{{#AppExe}}"; Tasks: desktopicon

[Run]
Filename: "{{app}}\{{#AppExe}}"; Description: "{{cm:LaunchProgram,{{#AppName}}}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{{app}}"
"""


def windows_installer() -> Path | None:
    iscc = next((p for p in ISCC_PATHS if Path(p).exists()), shutil.which("ISCC"))
    if not iscc:
        print("找不到 Inno Setup 6（ISCC.exe），略過安裝程式；App 在 dist/YT-Downloader/")
        return None
    # 新版 Inno Setup 已內建繁體中文；舊版沒有時才從官方 repo 下載
    bundled = Path(iscc).parent / "Languages" / "ChineseTraditional.isl"
    lang = bundled if bundled.exists() else download(INNO_ZH, VENDOR / "ChineseTraditional.isl")
    iss = BUILD / "installer.iss"
    # Inno Setup 需要 UTF-8 BOM 才會把中文當 UTF-8 讀
    iss.write_text(INNO_SCRIPT.format(display=DISPLAY, name=NAME, version=VERSION, dist=DIST,
                                      icon=ROOT / "assets" / "icon.ico", lang=lang, src=DIST / NAME),
                   encoding="utf-8-sig")
    subprocess.run([iscc, "/Q", str(iss)], check=True)
    return DIST / f"{NAME}-Setup-Windows.exe"


def mac_dmg(label: str) -> Path:
    app = DIST / f"{NAME}.app"
    stage = BUILD / "dmg"
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir(parents=True)
    # 用 ditto 複製以保留簽章與權限；App 顯示中文名稱
    subprocess.run(["ditto", str(app), str(stage / f"{DISPLAY}.app")], check=True)
    (stage / "Applications").symlink_to("/Applications")
    out = DIST / f"{NAME}-{label}.dmg"
    out.unlink(missing_ok=True)
    subprocess.run(["hdiutil", "create", "-volname", DISPLAY, "-srcfolder", str(stage),
                    "-ov", "-format", "UDZO", str(out)], check=True)
    return out


def main():
    for stream in (sys.stdout, sys.stderr):  # CI 的 Windows 主控台是 cp1252，印中文會當掉
        stream.reconfigure(encoding="utf-8", errors="replace")
    label = fetch_tools()
    check_tools()
    pyinstaller()
    out = windows_installer() if sys.platform == "win32" else mac_dmg(label)
    if out:
        print(f"\n完成：{out}（{out.stat().st_size / 1024**2:.0f} MB）")


if __name__ == "__main__":
    main()
