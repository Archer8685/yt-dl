"""把下載器打包成桌面 App（內建 FFmpeg / ffprobe / Deno，不用裝 Python）。

用法：  python build_app.py
需要：  pip install -r requirements-app.txt
產出：
  Windows  dist/YT-Downloader-Setup-Windows.exe   安裝精靈（需要 Inno Setup 6；沒有時只產出 dist/YT-Downloader/ 資料夾）
  macOS    dist/YT-Downloader-macOS-<arch>.dmg     拖進「應用程式」即可

GitHub Actions（.github/workflows/release.yml）會在 Windows 與 macOS 上執行這支腳本並發布到 Releases。
環境變數 YTDL_APP_VERSION 會寫進安裝程式的版本欄位。
"""
from __future__ import annotations

import os
import platform
import shutil
import stat
import subprocess
import sys
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
VERSION = os.environ.get("YTDL_APP_VERSION", "0.0.0-dev")

DENO = "https://github.com/denoland/deno/releases/latest/download/deno-{triple}.zip"
FFMPEG_WIN = ("https://github.com/yt-dlp/FFmpeg-Builds/releases/download/latest/"
              "ffmpeg-master-latest-win64-gpl-shared.zip")
FFMPEG_MAC = "https://ffmpeg.martin-riedl.de/redirect/latest/macos/{arch}/release/{tool}.zip"
INNO_ZH = "https://raw.githubusercontent.com/jrsoftware/issrc/main/Files/Languages/ChineseTraditional.isl"
ISCC_PATHS = [r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe", r"C:\Program Files\Inno Setup 6\ISCC.exe"]


def download(url: str, dest: Path) -> Path:
    if dest.exists():
        return dest
    print(f"下載 {url}", flush=True)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp")
    # 優先用系統 curl：Windows / macOS 內建，且使用系統憑證（公司網路的 SSL 檢查也能通過）
    if shutil.which("curl"):
        subprocess.run(["curl", "-fL", "--retry", "3", "-o", str(tmp), url], check=True)
    else:
        req = urllib.request.Request(url, headers={"User-Agent": "yt-dl-build"})
        with urllib.request.urlopen(req, timeout=300) as r, tmp.open("wb") as f:
            shutil.copyfileobj(r, f)
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


def pyinstaller():
    """onedir 視窗程式：啟動不用每次解壓，macOS 會產生 .app。"""
    sep = os.pathsep
    icon = ROOT / "assets" / ("icon.ico" if sys.platform == "win32" else "icon.icns")
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed",
           "--name", NAME, "--icon", str(icon), "--osx-bundle-identifier", BUNDLE_ID,
           "--distpath", str(DIST), "--workpath", str(BUILD / "pyinstaller"), "--specpath", str(BUILD),
           "--add-data", f"{ROOT / 'index.html'}{sep}.",
           "--add-data", f"{ROOT / 'assets' / 'icon-128.png'}{sep}assets",
           "--add-binary", f"{BIN}{os.sep}*{sep}bin",
           str(ROOT / "desktop.py")]
    shutil.rmtree(DIST / NAME, ignore_errors=True)
    shutil.rmtree(DIST / f"{NAME}.app", ignore_errors=True)
    subprocess.run(cmd, check=True)


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
