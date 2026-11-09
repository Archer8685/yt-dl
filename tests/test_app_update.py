"""app_update.py（App 新版提示）的測試；不連網路，GitHub 的回應用假的。"""
import io
import json
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QSettings

import app_update
import native_common as nc

RELEASE = {
    "tag_name": "v1.4.0",
    "html_url": "https://github.com/Archer8685/yt-dl/releases/tag/v1.4.0",
    "draft": False,
    "prerelease": False,
    "published_at": "2026-12-01T00:00:00Z",
    "assets": [{"name": "YT-Downloader-Setup-Windows.exe"}, {"name": "YT-Downloader-macOS-AppleSilicon.dmg"},
               {"name": "SHA256SUMS.txt"}],
}


@pytest.fixture(autouse=True)
def store(tmp_path, monkeypatch):
    """快取寫到暫存的 ini 檔，不動這台電腦的真實設定。"""
    ini = str(tmp_path / "s.ini")
    monkeypatch.setattr(nc, "QSettings", lambda *a, **k: QSettings(ini, QSettings.IniFormat))
    monkeypatch.setattr(app_update, "_current_version", lambda: "1.3.0")
    return ini


def test_parse_release_picks_platform_installer():
    win = app_update.parse_release(RELEASE, "win32")
    assert win["version"] == "1.4.0" and win["url"] == RELEASE["html_url"]
    assert win["download_url"] == ("https://github.com/Archer8685/yt-dl/releases/latest/download/"
                                   "YT-Downloader-Setup-Windows.exe")
    mac = app_update.parse_release(RELEASE, "darwin")
    assert mac["download_url"].endswith("/YT-Downloader-macOS-AppleSilicon.dmg")
    linux = app_update.parse_release(RELEASE, "linux")  # 沒有安裝檔：開 Release 頁
    assert linux["asset"] is None and linux["download_url"] == RELEASE["html_url"]


@pytest.mark.parametrize("data", [
    None, [], {}, {"tag_name": "nightly"}, {**RELEASE, "draft": True}, {**RELEASE, "prerelease": True},
])
def test_parse_release_rejects_bad_data(data):
    assert app_update.parse_release(data, "win32") is None


def test_parse_release_only_trusts_repo_urls():
    info = app_update.parse_release({**RELEASE, "html_url": "https://evil.example/x"}, "linux")
    assert info["url"] == app_update.RELEASES_URL


@pytest.mark.parametrize("latest,current,expected", [
    ("1.4.0", "1.3.0", True), ("1.3.0", "1.3.0", False), ("1.2.9", "1.3.0", False),
    ("1.10.0", "1.9.0", True), ("1.4.0", "開發版", False), (None, "1.3.0", False),
])
def test_is_newer(latest, current, expected):
    assert app_update.is_newer(latest, current) is expected


def test_check_once_per_day_and_cached(monkeypatch):
    calls = []
    monkeypatch.setattr(app_update, "fetch_latest", lambda: calls.append(1) or app_update.parse_release(RELEASE))
    first = app_update.check(now=1000.0)
    assert first["version"] == "1.4.0" and calls == [1]
    assert app_update.check(now=1000.0 + 3600)["version"] == "1.4.0" and calls == [1]  # 同一天：用快取
    app_update.check(now=1000.0 + 25 * 3600)
    assert calls == [1, 1]  # 隔天才再連線
    app_update.check(force=True, now=1000.0 + 25 * 3600 + 5)
    assert calls == [1, 1, 1]  # 使用者按「檢查 App 更新」
    assert app_update.cached()["version"] == "1.4.0"


def test_check_failure_is_silent_and_counts_as_attempt(monkeypatch):
    calls = []

    def boom():
        calls.append(1)
        raise TimeoutError("timed out")
    monkeypatch.setattr(app_update, "fetch_latest", boom)
    assert app_update.check(now=5000.0) is None  # 沒有快取：None，不丟例外
    assert app_update.check(now=5100.0) is None and calls == [1]  # 離線時不會每次都重試
    nc.settings_store().setValue(app_update.KEY_LATEST, json.dumps(app_update.parse_release(RELEASE)))
    assert app_update.check(force=True, now=5200.0)["version"] == "1.4.0"  # 失敗時回上次的快取


def test_clock_going_back_still_checks(monkeypatch):
    calls = []
    monkeypatch.setattr(app_update, "fetch_latest", lambda: calls.append(1) or None)
    app_update.check(now=10_000.0)
    app_update.check(now=100.0)  # 電腦時間被調回去：不要卡住好幾天都不檢查
    assert calls == [1, 1]


def test_corrupt_cache_is_ignored():
    nc.settings_store().setValue(app_update.KEY_LATEST, "{not json")
    assert app_update.cached() is None
    nc.settings_store().setValue(app_update.KEY_LATEST, json.dumps({"version": "x"}))
    assert app_update.cached() is None


def test_available_and_skip():
    info = app_update.parse_release(RELEASE)
    assert app_update.available(info) is True
    assert app_update.available(info, current="1.4.0") is False
    assert app_update.available(None) is False
    app_update.skip_version("1.4.0")
    assert app_update.skipped_version() == "1.4.0" and app_update.available(info) is False
    newer = {**info, "version": "1.4.1"}
    assert app_update.available(newer) is True  # 略過的是 1.4.0，更新的版本照樣提示


def test_fetch_latest_request(monkeypatch):
    seen = {}

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout):
        seen["url"], seen["timeout"] = req.full_url, timeout
        seen["headers"] = {k.lower(): v for k, v in req.header_items()}
        return Resp(json.dumps(RELEASE).encode("utf-8"))

    monkeypatch.setattr(app_update.urllib.request, "urlopen", fake_urlopen)
    info = app_update.fetch_latest()
    assert info["version"] == "1.4.0"
    assert seen["url"] == "https://api.github.com/repos/Archer8685/yt-dl/releases/latest"
    assert seen["timeout"] == 5
    assert "authorization" not in seen["headers"]  # 不帶驗證
    assert seen["headers"]["user-agent"] == "YT-Downloader/1.3.0"


def test_download_url_is_quoted():
    info = app_update.parse_release({**RELEASE, "assets": [{"name": "YT Downloader #2.dmg"}]}, "darwin")
    assert info["download_url"].endswith("/YT%20Downloader%20%232.dmg")


def test_due(monkeypatch):
    assert app_update.due(now=1000.0)
    monkeypatch.setattr(app_update, "fetch_latest", lambda: None)
    app_update.check(now=1000.0)
    assert not app_update.due(now=2000.0) and app_update.due(now=1000.0 + 86400)
