"""build_opts 與安全檢查的單元測試（不連網）。"""
from pathlib import Path

import pytest

import server

JOB = Path("downloads/_test")


def opts(**o):
    return server.build_opts(o, JOB)


def test_multi_language_audio_tracks_enable_multistreams():
    r = opts(mode="av", audio={"languages": ["en-US", "zh-Hant"]})
    assert r["format"].startswith("bv*+ba[language^=en-US]")
    assert "ba[language^=zh-Hant]" in r["format"]
    assert r["allow_multiple_audio_streams"] is True


def test_manual_formats_merge_all_audio():
    r = opts(mode="av", video={"format_id": "137"}, audio={"format_ids": ["251-0", "251-3"]})
    assert r["format"] == "137+251-0+251-3"
    assert r["allow_multiple_audio_streams"] is True


def test_format_ids_are_sanitized():
    r = opts(mode="av", video={"format_id": "137]/b[x"})
    assert "]" not in r["format"].split("+")[0]


def test_premium_prefers_premium_streams_with_fallback():
    r = opts(mode="av", video={"premium": True})
    first, *rest = r["format"].split("/")
    assert first.startswith("bv*[format_note*=Premium]")
    assert rest[0] == "bv*+ba[format_id!*=drc]"


def test_retries_zero_is_respected():
    assert opts(extras={"retries": 0})["retries"] == 0
    assert opts(extras={})["retries"] == 10
    assert opts(extras={"fragments": 99})["concurrent_fragment_downloads"] == 16


def test_subs_mode_does_not_download_thumbnail():
    r = opts(mode="subs", subs={"languages": ["en"]}, extras={"embed_thumbnail": True})
    assert not r.get("writethumbnail")
    assert r["skip_download"] is True
    assert r["writesubtitles"] is True


def test_audio_mode_extracts_with_codec_and_quality():
    r = opts(mode="audio", audio={"codec": "mp3", "quality": "320K"})
    pp = next(p for p in r["postprocessors"] if p["key"] == "FFmpegExtractAudio")
    assert pp["preferredcodec"] == "mp3" and pp["preferredquality"] == "320K"


def test_embed_thumbnail_skipped_for_unsupported_container():
    keys = [p["key"] for p in opts(mode="av", video={"container": "webm"},
                                   extras={"embed_thumbnail": True})["postprocessors"]]
    assert "EmbedThumbnail" not in keys


def test_ranges_are_tuples_and_validated():
    assert server._parse_ranges("0:30-1:45, 3:00-end") == [(30, 105), (180, float("inf"))]
    with pytest.raises(ValueError):
        server._parse_ranges("2:00-1:00")


@pytest.mark.parametrize("tpl", ["../../evil.%(ext)s", "C:\\x\\..\\y", "/abs/path"])
def test_template_cannot_escape_job_dir(tpl):
    t = server._safe_template(tpl)
    assert ".." not in t.split("/")
    assert not t.startswith("/")
    assert t[1:2] != ":"


def test_origin_allowlist():
    assert server._origin_allowed("https://archer8685.github.io")
    assert server._origin_allowed("http://localhost:3000")
    assert not server._origin_allowed("https://evil.example")
    assert not server._origin_allowed("http://localhost.evil.example")


@pytest.fixture
def client():
    server.app.config["TESTING"] = True
    return server.app.test_client()


def test_cross_origin_write_blocked(client):
    r = client.post("/api/download", json={}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403


def test_file_route_blocks_traversal(client):
    job = server.Job("https://x", {}, "t")
    server.JOBS[job.id] = job
    try:
        assert client.get(f"/api/jobs/{job.id}/file/../../server.py").status_code == 404
    finally:
        server.JOBS.pop(job.id)


def test_job_refuses_to_start_when_disk_is_full(monkeypatch, tmp_path):
    monkeypatch.setattr(server, "get_download_dir", lambda: tmp_path)
    monkeypatch.setattr(server, "disk_info", lambda p: {"path": str(p), "free": 100 * 1024**2, "total": 10 * 1024**3})
    job = server.Job("https://www.youtube.com/watch?v=x", {"mode": "audio"}, "t")
    server.run_job(job)
    assert job.status == "error"
    assert job.stage == "磁碟空間不足"
    assert "空間不足" in job.error


def test_settings_reject_relative_and_accept_writable_dir(client, monkeypatch, tmp_path):
    monkeypatch.setattr(server, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.delenv("YTDL_DOWNLOAD_DIR", raising=False)
    assert client.post("/api/settings", json={"download_dir": "relative/dir"}).status_code == 400
    target = tmp_path / "dl"
    r = client.post("/api/settings", json={"download_dir": str(target)})
    assert r.status_code == 200
    assert server.get_download_dir() == target.resolve()
    assert r.get_json()["disk"]["free"] is not None
    assert client.get("/api/settings").get_json()["drives"] is None
    assert client.get("/api/settings?drives=1").get_json()["drives"]


def test_cookies_upload_rejects_non_netscape(client):
    assert client.post("/api/cookies", json={"text": "hello"}).status_code == 400
