"""打包版 App 的 yt-dlp 自動更新。

App 裡的 yt-dlp 是打包時的版本，YouTube 改版時需要盡快換新版。yt-dlp 是純 Python 套件，
所以不必重裝 App：從 PyPI 下載新版 wheel，解壓到使用者資料夾，下次啟動時排在 sys.path 最前面優先載入。

  <資料夾>/ytdlp/current.json   {"version": "...", "dir": "<版本>"}，指向目前要用的版本
  <資料夾>/ytdlp/<版本>/        yt_dlp/ 與相依的 yt_dlp_ejs/（YouTube JS 驗證腳本）

安全機制：
- wheel 用 PyPI 提供的 sha256 校驗
- 換上新版前，先用另一個程序實際載入一次（verify），失敗就不切換
- 啟動時新版載入失敗，自動退回內建版本並停用這份更新
- 只在更新版比內建版新時使用（安裝新版 App 後，舊的更新自動失效）
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

PYPI = "https://pypi.org/pypi/{name}/json"
PYPI_VERSION = "https://pypi.org/pypi/{name}/{version}/json"
# 查詢最新版本的逾時（秒）：網路被擋時不要讓背景檢查卡太久；下載 wheel 另用較長的逾時
PYPI_TIMEOUT = 5
PACKAGES = ("yt_dlp", "yt_dlp_ejs")


def vtuple(v: str | None) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", v or "0"))


def overlay_root(root: Path) -> Path:
    return root / "ytdlp"


def bundled_version(bundle: Path) -> str | None:
    """打包時寫入的內建 yt-dlp 版本（build_app.py 產生 bundled-ytdlp.txt）。"""
    try:
        return (bundle / "bundled-ytdlp.txt").read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def current(root: Path) -> tuple[str, Path] | None:
    try:
        info = json.loads((overlay_root(root) / "current.json").read_text(encoding="utf-8"))
        path = overlay_root(root) / info["dir"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if not (path / "yt_dlp" / "__init__.py").is_file():
        return None
    return str(info["version"]), path


def activate(root: Path, bundle: Path) -> str | None:
    """啟動時呼叫（在 import yt_dlp 之前）：有比內建更新的版本就排到 sys.path 最前面。"""
    cur = current(root)
    if not cur:
        return None
    version, path = cur
    if vtuple(version) <= vtuple(bundled_version(bundle)):
        return None
    sys.path.insert(0, str(path))
    return version


def fallback(root: Path):
    """更新版載入失敗：移出 sys.path、清掉載入一半的模組，並停用這份更新，改用內建版本。"""
    cur = current(root)
    if cur:
        sys.path[:] = [p for p in sys.path if Path(p) != cur[1]]
    for name in list(sys.modules):
        if name.split(".")[0] in PACKAGES:
            del sys.modules[name]
    meta = overlay_root(root) / "current.json"
    if meta.exists():
        meta.replace(meta.with_name("broken.json"))


def _get(url: str, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "yt-dl-app"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _wheel(files: list[dict]) -> dict:
    """PyPI 的檔案清單中挑出純 Python wheel。"""
    for f in files:
        if f.get("packagetype") == "bdist_wheel" and f.get("filename", "").endswith("-py3-none-any.whl"):
            return f
    raise RuntimeError("PyPI 上找不到可用的 wheel")


def _download_wheel(f: dict, get=_get) -> zipfile.ZipFile:
    data = get(f["url"], 300)
    want = (f.get("digests") or {}).get("sha256")
    if not want or hashlib.sha256(data).hexdigest() != want:
        raise RuntimeError(f"{f.get('filename')} 校驗失敗")
    return zipfile.ZipFile(io.BytesIO(data))


def latest(channel: str = "stable", get=_get) -> tuple[str, dict]:
    """回傳 PyPI 上最新的 yt-dlp 版本與該版本的 metadata。nightly 頻道包含 pre-release。"""
    data = json.loads(get(PYPI.format(name="yt-dlp"), PYPI_TIMEOUT))
    version = data["info"]["version"]
    if channel == "nightly":
        version = max([version, *data.get("releases", {})], key=vtuple)
        if version != data["info"]["version"]:
            data = json.loads(get(PYPI_VERSION.format(name="yt-dlp", version=version), PYPI_TIMEOUT))
    return version, data


def _ejs_requirement(info: dict) -> str | None:
    """yt-dlp[default] 鎖定的 yt-dlp-ejs 版本（例如 yt-dlp-ejs==0.8.0; extra == "default"）。"""
    for req in info.get("requires_dist") or []:
        m = re.match(r"yt-dlp-ejs\s*==\s*([\w.]+)", req)
        if m:
            return m.group(1)
    return None


def _extract(z: zipfile.ZipFile, dest: Path, package: str):
    for name in z.namelist():
        if name.startswith(f"{package}/") and not name.endswith("/"):
            out = dest / name
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(z.read(name))


def install(root: Path, version: str, data: dict, verify, get=_get) -> Path:
    """下載指定版本並切換過去。verify(path) 回傳 True 才會啟用；失敗會丟出例外且不影響目前版本。"""
    base = overlay_root(root)
    base.mkdir(parents=True, exist_ok=True)
    stage = base / f"{version}.staging"
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir()
    try:
        _extract(_download_wheel(_wheel(data["urls"]), get), stage, "yt_dlp")
        ejs = _ejs_requirement(data["info"])
        if ejs:
            ejs_data = json.loads(get(PYPI_VERSION.format(name="yt-dlp-ejs", version=ejs), 15))
            _extract(_download_wheel(_wheel(ejs_data["urls"]), get), stage, "yt_dlp_ejs")
        if not verify(stage):
            raise RuntimeError(f"yt-dlp {version} 無法載入，維持目前版本")
        final = base / version
        shutil.rmtree(final, ignore_errors=True)
        stage.rename(final)
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    tmp = base / "current.json.tmp"
    tmp.write_text(json.dumps({"version": version, "dir": version}), encoding="utf-8")
    tmp.replace(base / "current.json")
    (base / "broken.json").unlink(missing_ok=True)
    return final


def cleanup(root: Path, keep: set[str]):
    """刪掉用不到的舊版本（目前執行中的版本也要保留，避免刪到正在使用的檔案）。"""
    base = overlay_root(root)
    if not base.is_dir():
        return
    for p in base.iterdir():
        if p.is_dir() and p.name not in keep:
            shutil.rmtree(p, ignore_errors=True)


def check(path: str) -> int:
    """verify 用：在獨立程序中載入指定資料夾的 yt-dlp，成功就寫出 OK 檔並回傳 0。"""
    sys.path.insert(0, path)
    import yt_dlp
    with yt_dlp.YoutubeDL({"quiet": True}):
        pass
    if not str(Path(yt_dlp.__file__).resolve()).startswith(str(Path(path).resolve())):
        return 2  # 載到的不是新版本
    (Path(path) / "OK").write_text(yt_dlp.version.__version__, encoding="utf-8")
    return 0
