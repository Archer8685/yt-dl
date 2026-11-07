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


class FakeYDL:
    """模擬 yt-dlp：前 fail_times 次寫出一段 .part 後斷線，之後完成並產出成品。"""
    calls = 0
    fail_times = 1

    def __init__(self, opts):
        self.home = Path(opts["paths"]["home"])
        self.tmp = Path(opts["paths"]["temp"])

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def download(self, urls):
        FakeYDL.calls += 1
        self.tmp.mkdir(parents=True, exist_ok=True)
        part = self.tmp / "big.f401.mp4.part"
        with part.open("ab") as f:
            f.write(b"x" * 1024)
        if FakeYDL.calls <= FakeYDL.fail_times:
            raise server.yt_dlp.utils.DownloadError("ERROR: unable to download video data: HTTP Error 403: Forbidden")
        part.unlink()
        (self.home / "big.mp4").write_bytes(b"done")
        return 0


@pytest.fixture
def fake_ydl(monkeypatch, tmp_path):
    FakeYDL.calls = 0
    monkeypatch.setattr(server.yt_dlp, "YoutubeDL", FakeYDL)
    monkeypatch.setattr(server, "RESUME_DELAY", 0)
    monkeypatch.setattr(server, "get_download_dir", lambda: tmp_path)
    return FakeYDL


def test_dropped_download_auto_resumes(fake_ydl):
    fake_ydl.fail_times = 2
    job = server.Job("https://www.youtube.com/watch?v=x", {"mode": "av"}, "t")
    server.run_job(job)
    assert fake_ydl.calls == 3
    assert job.status == "done"
    assert any("自動續傳" in line for line in job.log)


def test_failed_download_keeps_partial_and_can_resume(fake_ydl, client):
    fake_ydl.fail_times = server.AUTO_RESUME + 1
    job = server.Job("https://www.youtube.com/watch?v=x", {"mode": "av"}, "t")
    server.JOBS[job.id] = job
    try:
        server.run_job(job)
        assert job.status == "error"
        assert job.partial_bytes() > 0, "失敗時不能刪掉暫存檔"
        listed = next(j for j in client.get("/api/jobs").get_json() if j["id"] == job.id)
        assert listed["partial"] > 0
        fake_ydl.fail_times = 0
        assert client.post(f"/api/jobs/{job.id}/resume").status_code == 200
        assert client.post(f"/api/jobs/{job.id}/resume").status_code == 409  # 已在跑，不能重複
        for _ in range(100):
            if job.status == "done":
                break
            server.time.sleep(0.02)
        assert job.status == "done"
        assert [f["name"] for f in job.files()] == ["big.mp4"]  # job.json 不會出現在檔案列表
    finally:
        server.JOBS.pop(job.id, None)


def test_error_without_new_data_is_not_retried(fake_ydl, monkeypatch):
    def no_progress(self, urls):
        FakeYDL.calls += 1
        raise server.yt_dlp.utils.DownloadError("ERROR: Requested format is not available")
    monkeypatch.setattr(FakeYDL, "download", no_progress)
    job = server.Job("https://www.youtube.com/watch?v=x", {"mode": "av"}, "t")
    (job.dir / ".tmp").mkdir(parents=True)
    (job.dir / ".tmp" / "old.part").write_bytes(b"x")  # 上次留下的暫存檔
    server.run_job(job)
    assert fake_ydl.calls == 1
    assert job.status == "error"


def test_resume_without_partial_moves_to_new_storage(client, tmp_path, monkeypatch):
    old, new = tmp_path / "c", tmp_path / "d"
    job = server.Job("https://x", {"mode": "av"}, "t", job_dir=old / "abc")
    job.status = "error"
    job.dir.mkdir(parents=True)
    server.JOBS[job.id] = job
    monkeypatch.setattr(server, "get_download_dir", lambda: new)
    monkeypatch.setattr(server, "run_job", lambda j: None)
    try:
        assert client.post(f"/api/jobs/{job.id}/resume").status_code == 200
        assert job.dir == new / job.id
        assert not (old / "abc").exists()
    finally:
        server.JOBS.pop(job.id, None)


def test_interrupted_job_is_restored_after_restart(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "get_download_dir", lambda: tmp_path)
    job = server.Job("https://www.youtube.com/watch?v=x", {"mode": "av"}, "長影片")
    job.status = "downloading"
    (job.dir / ".tmp").mkdir(parents=True)
    (job.dir / ".tmp" / "a.mp4.part").write_bytes(b"x" * 2048)
    job.save()
    restored = server.Job.load(job.dir / server.JOB_META)
    assert restored.id == job.id and restored.dir == job.dir
    assert restored.status == "error" and restored.stage == "已中斷"
    assert restored.options == {"mode": "av"} and restored.title == "長影片"
    assert restored.partial_bytes() == 2048


def test_streams_waiting_for_merge_count_as_partial_and_are_not_moved(client, tmp_path, monkeypatch):
    old, new = tmp_path / "c", tmp_path / "d"
    job = server.Job("https://x", {"mode": "av"}, "t", job_dir=old / "abc")
    job.status = "error"
    tmp = job.dir / ".tmp"
    tmp.mkdir(parents=True)
    (tmp / "a.f401.mp4").write_bytes(b"x" * 600)  # 已下載完、等待合併
    (tmp / "a.temp.mp4").write_bytes(b"x" * 50)  # 合併到一半，重跑會重寫
    assert job.partial_bytes() == 600
    server.JOBS[job.id] = job
    monkeypatch.setattr(server, "get_download_dir", lambda: new)  # 使用者換了儲存位置
    monkeypatch.setattr(server, "run_job", lambda j: None)
    try:
        assert client.post(f"/api/jobs/{job.id}/resume").status_code == 200
        assert job.dir == old / "abc" and (tmp / "a.f401.mp4").exists(), "不能刪掉已下載的串流"
    finally:
        server.JOBS.pop(job.id, None)


def test_rate_meter_smooths_bursty_chunks():
    t = [0.0]
    m = server.RateMeter(window=10, clock=lambda: t[0])
    done, total = 0, 1_000_000_000
    # 平均 10 MB/s，但以「瞬間爆量、再停頓」的 chunk 形式到達
    for _ in range(30):
        t[0] += 0.05
        done += 5_000_000
        m.update("a.part", done, total)
        t[0] += 0.95
        done += 5_000_000
        m.update("a.part", done, total)
    assert 9e6 < m.speed < 11e6
    assert abs(m.eta - (total - done) / m.speed) <= 1
    m.update("a.part", total + 10, total)  # 已下載超過估計大小 → 不顯示負的剩餘時間
    assert m.eta is None
    t[0] += 120  # 斷線兩分鐘後續傳：不能把停頓算進平均
    m.update("a.part", done + 1, total)
    assert m.speed is None
    m.update("b.part", 100, total)  # 換檔案 → 重新計算，不沿用舊速率
    assert m.speed is None and m.eta is None


def test_postprocessor_labels_with_and_without_ffmpeg_prefix():
    assert server._pp_label("VideoRemuxer") == "重新封裝容器"
    assert server._pp_label("FFmpegVideoRemuxer") == "重新封裝容器"
    assert server._pp_label("Merger") == "合併影音軌"
    assert server._pp_label("SomethingNew") == "SomethingNew"
    assert server._pp_label(None) == "後處理"


def test_ffmpeg_steps_skip_faststart_rewrite():
    args = opts(mode="av")["postprocessor_args"]
    # yt-dlp 對每個後處理的第一個輸出會查到 "ffmpeg" 這個鍵，排在它自己加的 +faststart 之後
    for pp in ("Merger", "FFmpegMetadata", "EmbedThumbnail"):
        got = server.yt_dlp.utils._configuration_args(pp, args, "ffmpeg", ["_o1", "_o", ""])
        assert got == ["-movflags", "-faststart"]


def _top_atoms(path):
    import struct
    names = []
    with open(path, "rb") as f:
        while head := f.read(8):
            size, name = struct.unpack(">I4s", head)
            if size == 1:
                size = struct.unpack(">Q", f.read(8))[0] - 8
            names.append(name.decode())
            f.seek(size - 8, 1)
    return names


@pytest.mark.skipif(not server.shutil.which("ffmpeg"), reason="需要 ffmpeg")
def test_merge_keeps_index_at_end_so_cover_embed_is_cheap(tmp_path):
    import subprocess

    from mutagen.mp4 import MP4, MP4Cover
    from yt_dlp.postprocessor import FFmpegMergerPP
    v, a, out = tmp_path / "v.mp4", tmp_path / "a.m4a", tmp_path / "out.mp4"
    ff = ["ffmpeg", "-v", "error", "-y"]
    subprocess.run([*ff, "-f", "lavfi", "-i", "testsrc=d=2:s=160x120", "-c:v", "mpeg4", str(v)], check=True)
    subprocess.run([*ff, "-f", "lavfi", "-i", "sine=d=2", "-c:a", "aac", str(a)], check=True)
    ydl = server.yt_dlp.YoutubeDL({"quiet": True, "postprocessor_args": opts(mode="av")["postprocessor_args"]})
    fmts = [{"vcodec": "mpeg4", "acodec": "none", "protocol": "https"},
            {"vcodec": "none", "acodec": "aac", "protocol": "https"}]
    FFmpegMergerPP(ydl).run({"__files_to_merge": [str(v), str(a)], "requested_formats": fmts,
                             "filepath": str(out), "ext": "mp4"})
    atoms = _top_atoms(out)
    assert atoms.index("moov") > atoms.index("mdat"), "索引應留在檔尾，不再整份往後挪"
    meta = MP4(out)
    meta.tags["covr"] = [MP4Cover(b"\xff\xd8\xff" + b"0" * 1000, imageformat=MP4Cover.FORMAT_JPEG)]
    meta.save()
    atoms = _top_atoms(out)
    assert atoms.index("moov") > atoms.index("mdat")
    assert MP4(out).tags["covr"], "封面要能正常嵌入、檔案仍可讀"


def test_postprocess_progress_follows_output_file(tmp_path):
    job = server.Job("https://x", {"mode": "av"}, "t", job_dir=tmp_path / "j")
    tmp = job.dir / ".tmp"
    tmp.mkdir(parents=True)
    (tmp / "a.f401.mp4").write_bytes(b"x" * 600)
    (tmp / "a.f251.webm").write_bytes(b"x" * 400)
    (tmp / "other.temp.mp4").write_bytes(b"x" * 999)  # 標題剛好含 .temp. 的無關檔案
    out = tmp / "a.temp.mp4"
    out.write_bytes(b"x" * 900)
    server.os.utime(out, (1, 1))  # 上次中斷殘留的舊暫存檔
    job.status, job.stage = "processing", "合併影音軌"
    server._pp_start(job, {"filepath": str(tmp / "a.mp4"),
                           "__files_to_merge": [str(tmp / "a.f401.mp4"), str(tmp / "a.f251.webm")]})
    assert job.pp_out == out and job.pp_total == 1000
    server._pp_progress(job)
    assert job.progress == 0.0, "舊暫存檔不能當成進度"
    out.write_bytes(b"x" * 250)  # FFmpeg 覆寫後開始成長
    server._pp_progress(job)
    assert (job.progress, job.downloaded, job.total) == (25.0, 250, 1000)
    job.status = "done"
    out.write_bytes(b"x" * 900)
    server._pp_progress(job)  # 不在後處理時不更新
    assert job.progress == 25.0


def test_postprocessor_hook_sets_expected_size(fake_ydl, monkeypatch, tmp_path):
    seen = {}

    def merge(self, urls):
        v, a = tmp_path / "v.mp4", tmp_path / "a.webm"
        v.write_bytes(b"x" * 300)
        a.write_bytes(b"x" * 100)
        hook = self.opts["postprocessor_hooks"][0]
        hook({"status": "started", "postprocessor": "Merger",
              "info_dict": {"filepath": str(tmp_path / "m.mp4"), "__files_to_merge": [str(v), str(a)]}})
        seen.update(total=self.job.pp_total, status=self.job.status, progress=self.job.progress)
        hook({"status": "finished", "postprocessor": "Merger", "info_dict": {}})
        seen["after"] = self.job.pp_out
        (self.home / "big.mp4").write_bytes(b"done")
        return 0

    orig_init = FakeYDL.__init__

    def init(self, o):
        orig_init(self, o)
        self.opts = o
        self.job = job

    monkeypatch.setattr(FakeYDL, "__init__", init)
    monkeypatch.setattr(FakeYDL, "download", merge)
    job = server.Job("https://www.youtube.com/watch?v=x", {"mode": "av"}, "t")
    job.progress = 100.0
    server.run_job(job)
    assert seen == {"total": 400, "status": "processing", "progress": 0.0, "after": None}
    assert job.status == "done"


def test_frozen_build_points_updates_to_releases(client, monkeypatch):
    monkeypatch.setattr(server, "FROZEN", True)
    monkeypatch.setattr(server, "latest_version", lambda force=False: "2099.1.1")
    meta = client.get("/api/meta").get_json()
    assert meta["frozen"] is True and meta["releases_url"].startswith("https://github.com/")
    r = client.post("/api/update")
    assert r.status_code == 409 and r.get_json()["url"] == server.RELEASES_URL
    monkeypatch.setattr(server, "pip_upgrade", lambda: pytest.fail("打包版不能呼叫 pip"))
    server.startup_update()


def test_release_tag_gives_bundled_ytdlp_version():
    assert server._release_ytdlp_version("engine-2026.10.26-a1b2c3d") == "2026.10.26"
    assert server._release_ytdlp_version("v1.0") is None
    assert server._release_ytdlp_version(None) is None


def test_thumbnail_written_before_a_failure_is_not_progress(fake_ydl, monkeypatch):
    def thumb_then_fail(self, urls):
        FakeYDL.calls += 1
        self.tmp.mkdir(parents=True, exist_ok=True)
        (self.tmp / "a.jpg").write_bytes(b"x" * 5000)
        (self.tmp / "a.en.vtt").write_bytes(b"x" * 100)
        raise server.yt_dlp.utils.DownloadError("ERROR: Requested format is not available")
    monkeypatch.setattr(FakeYDL, "download", thumb_then_fail)
    job = server.Job("https://www.youtube.com/watch?v=x", {"mode": "av"}, "t")
    server.run_job(job)
    assert fake_ydl.calls == 1, "只寫了縮圖、字幕不算有進度，不該自動續傳"
    assert job.partial_bytes() == 0


def test_reveal_opens_file_manager_only_inside_job_dir(client, monkeypatch, tmp_path):
    opened = []
    monkeypatch.setattr(server, "reveal_in_file_manager", opened.append)
    job = server.Job("https://x", {}, "t", job_dir=tmp_path / "j")
    job.dir.mkdir()
    (job.dir / "v.mp4").write_bytes(b"x")
    server.JOBS[job.id] = job
    try:
        assert client.post(f"/api/jobs/{job.id}/reveal", json={"name": "v.mp4"}).status_code == 200
        assert client.post(f"/api/jobs/{job.id}/reveal", json={}).status_code == 200
        assert client.post(f"/api/jobs/{job.id}/reveal", json={"name": "../../x"}).status_code == 404
        assert client.post(f"/api/jobs/{job.id}/reveal", json={"name": "nope.mp4"}).status_code == 404
        assert client.post(f"/api/jobs/{job.id}/reveal", json={"name": "v.mp4"},
                           headers={"Origin": "https://evil.example"}).status_code == 403
        assert opened == [(job.dir / "v.mp4").resolve(), job.dir.resolve()]
    finally:
        server.JOBS.pop(job.id, None)


def test_explorer_select_quotes_only_the_path():
    p = Path(r"D:\yt dl\Me at the zoo [x].mp4")
    assert server._explorer_select_cmd(p) == 'explorer /select,"D:\\yt dl\\Me at the zoo [x].mp4"'


def test_user_data_dir_is_outside_the_bundle():
    d = server._user_data_dir()
    assert d.name == server.APP_NAME and d.is_absolute()


def test_cookies_upload_rejects_non_netscape(client):
    assert client.post("/api/cookies", json={"text": "hello"}).status_code == 400
