"""App 新版提示：查 GitHub Releases 的最新版本（只提示、開下載頁，不自動下載或安裝）。

- check(force=False)：查 https://api.github.com/repos/Archer8685/yt-dl/releases/latest
  （不帶驗證、逾時 5 秒）。每天最多真的連線一次，其餘時間回傳快取；連線失敗回傳上次的快取（沒有就 None），
  不丟例外、不顯示錯誤。會連網路，請在背景執行緒呼叫。
- available(info)：info 比目前版本新、而且不是使用者「略過」的版本。
- skip_version(version)／skipped_version()：「略過此版本」。

快取與略過的版本存在 App 的 QSettings（native_common.settings_store()）的 app_update/ 底下。
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.parse
import urllib.request

REPO = "Archer8685/yt-dl"
API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_URL = f"https://github.com/{REPO}/releases/latest"
DOWNLOAD_URL = f"https://github.com/{REPO}/releases/latest/download/"  # 後面接安裝檔名稱
TIMEOUT_S = 5
CHECK_INTERVAL_S = 24 * 3600  # 每天最多一次

KEY_CHECKED = "app_update/checked_at"  # 上次真的連線的時間（epoch 秒；失敗也算，離線時不會一直重試）
KEY_LATEST = "app_update/latest"  # 上次查到的結果（JSON）
KEY_SKIPPED = "app_update/skipped"  # 使用者按「略過此版本」的版本

WINDOWS_ASSET = "YT-Downloader-Setup-Windows.exe"


def _store():
    from native_common import settings_store  # 測試會把 native_common 的 QSettings 換成暫存檔
    return settings_store()


def _current_version() -> str:
    from native_common import app_version
    return app_version()


def vtuple(v: str | None) -> tuple[int, ...]:
    """「v1.3.0」→ (1, 3, 0)。沒有數字（例如「開發版」）回傳空的 tuple。"""
    return tuple(int(x) for x in re.findall(r"\d+", str(v or "")))


def is_newer(latest: str | None, current: str | None) -> bool:
    """latest 是否比 current 新；任何一邊看不出版本號就當成不新（開發版不提示）。"""
    a, b = vtuple(latest), vtuple(current)
    return bool(a) and bool(b) and a > b


def asset_name(assets: list[str], platform: str | None = None) -> str | None:
    """在 Release 的檔案清單裡挑出這個平台的安裝檔名稱；沒有就 None。"""
    platform = platform or sys.platform
    if platform == "win32":
        if WINDOWS_ASSET in assets:
            return WINDOWS_ASSET
        return next((a for a in assets if a.lower().endswith(".exe")), None)
    if platform == "darwin":
        return next((a for a in assets if a.lower().endswith(".dmg")), None)
    return None


def parse_release(data: dict, platform: str | None = None) -> dict | None:
    """GitHub API 的 release JSON → 介面要用的資料；格式不對回傳 None。"""
    if not isinstance(data, dict) or data.get("draft") or data.get("prerelease"):
        return None
    tag = str(data.get("tag_name") or "").strip()
    version = tag[1:] if tag[:1] in ("v", "V") else tag
    if not vtuple(version):
        return None
    names = [str(a.get("name") or "") for a in data.get("assets") or [] if isinstance(a, dict)]
    asset = asset_name(names, platform)
    page = str(data.get("html_url") or "")
    if not page.startswith(f"https://github.com/{REPO}/"):  # 只開這個 repo 的網址
        page = RELEASES_URL
    return {
        "version": version,
        "tag": tag,
        "url": page,  # 「查看更新內容」
        "download_url": DOWNLOAD_URL + urllib.parse.quote(asset) if asset else page,  # 「下載」：這個平台的安裝檔
        "asset": asset,
        "published_at": str(data.get("published_at") or ""),
    }


def fetch_latest(timeout: float = TIMEOUT_S) -> dict | None:
    """連 GitHub 查最新的 Release（不帶驗證）。失敗會丟例外。"""
    req = urllib.request.Request(API_URL, headers={
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": f"YT-Downloader/{_current_version()}",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return parse_release(json.loads(r.read(512 * 1024).decode("utf-8")))


def cached() -> dict | None:
    """上次查到的結果（沒有或壞掉時 None）。"""
    try:
        data = json.loads(str(_store().value(KEY_LATEST, "") or "") or "null")
    except ValueError:
        return None
    return data if isinstance(data, dict) and vtuple(data.get("version")) else None


def due(now: float | None = None) -> bool:
    """距離上次連線是否已經超過一天（從沒查過、或電腦時間被調回去也算）。"""
    now = time.time() if now is None else now
    try:
        last = float(_store().value(KEY_CHECKED, 0) or 0)
    except (TypeError, ValueError):
        last = 0.0
    return not (last > 0 and 0 <= now - last < CHECK_INTERVAL_S)


def check(force: bool = False, now: float | None = None) -> dict | None:
    """回傳最新 Release 的資料（見 parse_release），查不到時 None；不會丟例外。

    距離上次連線不到一天（且不是 force）就直接回傳快取。連線失敗也記下時間，回傳上次的快取。
    """
    now = time.time() if now is None else now
    if not force and not due(now):
        return cached()
    store = _store()
    store.setValue(KEY_CHECKED, now)
    store.sync()
    try:
        info = fetch_latest()
    except Exception:  # noqa: BLE001 — 離線、逾時、GitHub 限流、格式不對：都安靜地當成沒查到
        return cached()
    if info is None:
        return cached()
    store = _store()
    store.setValue(KEY_LATEST, json.dumps(info, ensure_ascii=False))
    store.sync()
    return info


def skipped_version() -> str:
    return str(_store().value(KEY_SKIPPED, "") or "")


def skip_version(version: str) -> None:
    """「略過此版本」：這一版不再提示，之後更新的版本照樣提示。"""
    store = _store()
    store.setValue(KEY_SKIPPED, version or "")
    store.sync()


def available(info: dict | None, current: str | None = None) -> bool:
    """info 是不是要提示的新版：比目前版本新，而且使用者沒有略過這一版。"""
    if not info:
        return False
    version = info.get("version")
    if not is_newer(version, current if current is not None else _current_version()):
        return False
    return vtuple(version) != vtuple(skipped_version())
