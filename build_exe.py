"""把引擎打包成免安裝的單一執行檔（內建 FFmpeg / ffprobe / Deno）。

用法：  python build_exe.py
需要：  pip install -r requirements.txt pyinstaller
產出：  dist/YT-Downloader-Windows.exe   或   dist/YT-Downloader-macOS-<arch>.zip

GitHub Actions（.github/workflows/release.yml）會在 Windows 與 macOS 上執行這支腳本並發布到 Releases。
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
VENDOR = BUILD / "vendor"
BIN = VENDOR / "bin"
NAME = "YT-Downloader"

DENO = "https://github.com/denoland/deno/releases/latest/download/deno-{triple}.zip"
FFMPEG_WIN = ("https://github.com/yt-dlp/FFmpeg-Builds/releases/download/latest/"
              "ffmpeg-master-latest-win64-gpl-shared.zip")
FFMPEG_MAC = "https://ffmpeg.martin-riedl.de/redirect/latest/macos/{arch}/release/{tool}.zip"


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
    """從壓縮檔取出 want(name) 為真的檔案，全部放到 BIN。"""
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


def build(label: str) -> Path:
    sep = os.pathsep
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--console",
           "--name", NAME, "--distpath", str(ROOT / "dist"), "--workpath", str(BUILD / "pyinstaller"),
           "--specpath", str(BUILD),
           "--add-data", f"{ROOT / 'index.html'}{sep}.",
           "--add-binary", f"{BIN}{os.sep}*{sep}bin",
           str(ROOT / "server.py")]
    subprocess.run(cmd, check=True)
    dist = ROOT / "dist"
    if sys.platform == "win32":
        out = dist / f"{NAME}-{label}.exe"
        out.unlink(missing_ok=True)
        (dist / f"{NAME}.exe").rename(out)
    else:
        out = dist / f"{NAME}-{label}.zip"
        out.unlink(missing_ok=True)
        # ditto 會保留執行權限與簽章
        subprocess.run(["ditto", "-c", "-k", "--keepParent", str(dist / NAME), str(out)], check=True)
    return out


def main():
    label = fetch_tools()
    check_tools()
    out = build(label)
    print(f"\n完成：{out}（{out.stat().st_size / 1024**2:.0f} MB）")


if __name__ == "__main__":
    main()
