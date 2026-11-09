"""引擎可靠度（v1.3.0 E1）：失敗判斷、播放清單部分失敗、暫停／繼續、刪除、排程、錯誤格式。

不連網：播放清單測試用真的 yt-dlp 流程，搭配本機的假網站（自訂 extractor ＋ file:// 媒體檔）。
"""
from __future__ import annotations

import json
import os
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from yt_dlp.extractor.common import InfoExtractor
from yt_dlp.utils import ExtractorError

import server

# --------------------------------------------------------------------------- #
#  共用：本機假網站
# --------------------------------------------------------------------------- #
PRIVATE: set[str] = set()  # 這些編號的影片解析時會丟出「私人影片」
MEDIA: dict[str, Path] = {}


class FakePlaylistIE(InfoExtractor):
    IE_NAME = "fakepl"
    _VALID_URL = r"https?://fake\.test/playlist/(?P<id>\d+)"

    def _real_extract(self, url):
        n = int(self._match_id(url))
        entries = [self.url_result(f"https://fake.test/v/{i}", FakeVideoIE, video_id=f"vid{i}",
                                   video_title=f"影片 {i}") for i in range(1, n + 1)]
        return self.playlist_result(entries, "pl", "測試清單")


class FakeVideoIE(InfoExtractor):
    IE_NAME = "fakev"
    _VALID_URL = r"https?://fake\.test/v/(?P<id>\d+)"
    _RETURN_TYPE = "video"

    def _real_extract(self, url):
        n = self._match_id(url)
        if n in PRIVATE:
            raise ExtractorError("Private video. Sign in if you've been granted access to this video",
                                 expected=True, video_id=f"vid{n}")
        return {"id": f"vid{n}", "title": f"影片 {n}", "url": MEDIA["file"].as_uri(), "ext": "mp4",
                "vcodec": "h264", "acodec": "aac"}


class LocalYDL(server.yt_dlp.YoutubeDL):
    def __init__(self, params=None, auto_init=True):
        super().__init__({**(params or {}), "enable_file_urls": True}, auto_init=False)
        self.add_info_extractor(FakePlaylistIE())
        self.add_info_extractor(FakeVideoIE())


@pytest.fixture
def local_site(monkeypatch, tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    MEDIA["file"] = src / "media.mp4"
    MEDIA["file"].write_bytes(b"\x00" * 4096)
    PRIVATE.clear()
    dl = tmp_path / "dl"
    monkeypatch.setattr(server.yt_dlp, "YoutubeDL", LocalYDL)
    monkeypatch.setattr(server, "get_download_dir", lambda: dl)
    monkeypatch.setattr(server, "NET_BACKOFF", (0, 0, 0))
    monkeypatch.setattr(server, "RESUME_DELAY", 0)
    return dl


@pytest.fixture
def client():
    server.app.config["TESTING"] = True
    return server.app.test_client()


@pytest.fixture
def jobs():
    """測試結束後把加進 JOBS 的工作拿掉。"""
    added: list[server.Job] = []

    def add(job):
        with server.JOBS_LOCK:
            server.JOBS[job.id] = job
        added.append(job)
        return job

    yield add
    with server.JOBS_LOCK:
        for j in added:
            server.JOBS.pop(j.id, None)


def wait_for(cond, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


# --------------------------------------------------------------------------- #
#  R3 播放清單部分失敗
# --------------------------------------------------------------------------- #
def test_playlist_continues_after_private_video(local_site):
    PRIVATE.add("2")
    job = server.Job("https://fake.test/playlist/3", {"mode": "av", "playlist": True}, "清單")
    server.run_job(job)
    names = sorted(f["name"] for f in job.files())
    assert names == ["影片 1 [vid1].mp4", "影片 3 [vid3].mp4"], "第 2 部失敗後要繼續下載第 3 部"
    assert job.status == "done"
    assert job.total_count == 3 and job.done_count == 2
    assert len(job.failed_items) == 1
    item = job.failed_items[0]
    assert item["index"] == 2 and item["title"] == "影片 2"
    assert item["error_code"] == "private_video"
    assert "Private video" in item["error_detail"]
    assert job.warnings, "部分失敗要有警告"
    d = job.to_dict()
    assert d["done_count"] == 2 and d["total_count"] == 3
    shown = d["failed_items"][0]
    assert shown["index"] == 2 and shown["title"] == "影片 2" and shown["error_code"] == "private_video"
    assert shown["error"].startswith("這是私人影片") and "Private video" in shown["error_detail"]
    assert d["warnings"] == ["完成 2/3，1 部無法下載"] and d["stage"] == "完成 2/3"
    en = job.to_dict(lang="en")
    assert en["failed_items"][0]["error"].startswith("This is a private video")
    assert en["warnings"] == ["Done 2/3; 1 couldn't be downloaded"] and en["stage"] == "Done 2/3"


def test_retry_failed_reruns_only_failed_items(local_site, client, jobs):
    PRIVATE.add("2")
    job = jobs(server.Job("https://fake.test/playlist/3", {"mode": "av", "playlist": True}, "清單"))
    server.run_job(job)
    assert len(job.failed_items) == 1
    PRIVATE.clear()
    seen = []
    orig = FakeVideoIE._real_extract
    FakeVideoIE._real_extract = lambda self, url: seen.append(url) or orig(self, url)
    try:
        r = client.post(f"/api/jobs/{job.id}/retry_failed")
        assert r.status_code == 200
        assert wait_for(lambda: job.status == "done" and not job.failed_items)
    finally:
        FakeVideoIE._real_extract = orig
    assert seen == ["https://fake.test/v/2"], "只重跑失敗的那一部"
    assert job.done_count == 3 and job.total_count == 3
    assert len(job.files()) == 3
    assert client.post(f"/api/jobs/{job.id}/retry_failed").status_code == 409  # 沒有失敗的項目了


def test_playlist_where_every_item_fails_is_an_error(local_site):
    PRIVATE.update({"1", "2"})
    job = server.Job("https://fake.test/playlist/2", {"mode": "av", "playlist": True}, "清單")
    server.run_job(job)
    assert job.status == "error"
    assert len(job.failed_items) == 2


# --------------------------------------------------------------------------- #
#  R2 只有縮圖／字幕不算完成
# --------------------------------------------------------------------------- #
class ThumbThen403:
    """先寫出縮圖和字幕（在工作資料夾），影片下載到一半丟出 403。"""
    calls = 0

    def __init__(self, opts):
        self.home = Path(opts["paths"]["home"])
        self.tmp = Path(opts["paths"]["temp"])

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def download(self, urls):
        ThumbThen403.calls += 1
        self.home.mkdir(parents=True, exist_ok=True)
        (self.home / "a [x].jpg").write_bytes(b"j" * 100)
        (self.home / "a [x].en.vtt").write_bytes(b"v" * 100)
        self.tmp.mkdir(parents=True, exist_ok=True)
        with (self.tmp / "a [x].f137.mp4.part").open("ab") as f:
            f.write(b"x" * 1000)
        raise server.yt_dlp.utils.DownloadError("ERROR: unable to download video data: HTTP Error 403: Forbidden")


def test_thumbnail_and_subtitles_only_is_an_error_not_done(monkeypatch, tmp_path, client, jobs):
    ThumbThen403.calls = 0
    monkeypatch.setattr(server.yt_dlp, "YoutubeDL", ThumbThen403)
    monkeypatch.setattr(server, "get_download_dir", lambda: tmp_path)
    monkeypatch.setattr(server, "RESUME_DELAY", 0)
    monkeypatch.setattr(server, "NET_BACKOFF", (0, 0, 0))
    job = jobs(server.Job("https://www.youtube.com/watch?v=xxxxxxxxxxx", {"mode": "av"}, "t"))
    server.run_job(job)
    assert job.status == "error", "只有縮圖和字幕時不能算完成"
    assert job.partial_bytes() > 0, ".tmp 要保留，才能繼續下載"
    assert job.error_code == "http_403"
    assert job.error_action == "resume"
    d = client.get("/api/jobs").get_json()
    mine = next(j for j in d if j["id"] == job.id)
    assert mine["status"] == "error" and mine["partial"] > 0
    assert mine["error_code"] == "http_403" and mine["error_faq"] == "err-http-403"


# --------------------------------------------------------------------------- #
#  其餘測試共用的 yt-dlp 替身：依 script 決定這一輪做什麼
# --------------------------------------------------------------------------- #
class ScriptedYDL:
    script = None  # callable(ydl) -> 結束碼

    def __init__(self, opts):
        self.opts = opts
        self.home = Path(opts["paths"]["home"])
        self.tmp = Path(opts["paths"]["temp"])

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def download(self, urls):
        return type(self).script(self) or 0

    def progress(self, done, total=1_000_000, fid="137"):
        for h in self.opts["progress_hooks"]:
            h({"status": "downloading", "downloaded_bytes": done, "total_bytes": total, "filename": "a",
               "info_dict": {"format_id": fid}})

    def pp(self, status, name="Merger", info=None):
        for h in self.opts["postprocessor_hooks"]:
            h({"status": status, "postprocessor": name, "info_dict": info or {}})

    def finish(self, name="a [x].mp4"):
        self.home.mkdir(parents=True, exist_ok=True)
        (self.home / name).write_bytes(b"done")


@pytest.fixture
def scripted(monkeypatch, tmp_path):
    ScriptedYDL.script = None
    monkeypatch.setattr(server.yt_dlp, "YoutubeDL", ScriptedYDL)
    monkeypatch.setattr(server, "get_download_dir", lambda: tmp_path / "dl")
    monkeypatch.setattr(server, "RESUME_DELAY", 0)
    monkeypatch.setattr(server, "NET_BACKOFF", (0, 0, 0))
    return ScriptedYDL


YT = "https://www.youtube.com/watch?v=jNQXAC9IVR"  # 後面再接一個字元，湊成 11 碼影片 id


def new_job(suffix="w", **options):
    return server.Job(YT + suffix, {"mode": "av", **options}, "t")


def unreachable_dir(tmp_path: Path) -> Path:
    """任何系統都建立不了的資料夾（上一層是檔案），用來模擬磁碟不存在。"""
    blocker = tmp_path / "blocker"
    blocker.write_text("x")
    return blocker / "yt"


def done_job(root: Path, name="v.mp4", status="done") -> server.Job:
    job = server.Job("https://x", {"mode": "av"}, "t", job_dir=root / os.urandom(6).hex())
    job.dir.mkdir(parents=True)
    (job.dir / name).write_bytes(b"v")
    job.status = status
    job.save()
    return job


def saved(job: server.Job) -> dict:
    return json.loads((job.dir / server.JOB_META).read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
#  R2（續）：yt-dlp 回報成功但只有縮圖
# --------------------------------------------------------------------------- #
def test_success_without_main_media_is_an_error(scripted):
    scripted.script = lambda y: y.finish("a [x].jpg")
    job = new_job()
    server.run_job(job)
    assert job.status == "error"
    assert job.stage_code == "failed"


def test_subtitle_mode_counts_subtitle_files(scripted):
    scripted.script = lambda y: y.finish("a [x].en.srt")
    job = new_job(mode="subs", subs={"languages": ["en"]})
    server.run_job(job)
    assert job.status == "done" and job.stage_code == "done"


# --------------------------------------------------------------------------- #
#  R1 下載資料夾所在的磁碟不存在
# --------------------------------------------------------------------------- #
def test_engine_imports_when_download_drive_is_missing(tmp_path):
    bad = "Z:\\nodrive\\yt" if os.name == "nt" and not os.path.exists("Z:\\") else str(unreachable_dir(tmp_path))
    env = {**os.environ, "YTDL_DOWNLOAD_DIR": bad, "YTDL_PORT": "18799", "PYTHONIOENCODING": "utf-8"}
    code = "import json, server; print(json.dumps(server.download_dir_problem()))"
    p = subprocess.run([sys.executable, "-c", code], cwd=Path(server.__file__).parent, env=env,
                       capture_output=True, text=True, encoding="utf-8", timeout=120, check=False)
    assert p.returncode == 0, p.stderr
    assert json.loads(p.stdout.strip().splitlines()[-1]), "磁碟不存在要回報錯誤，不能讓 import 失敗"


def test_missing_download_dir_is_reported_as_json(client, monkeypatch, tmp_path):
    bad = unreachable_dir(tmp_path)
    monkeypatch.setenv("YTDL_DOWNLOAD_DIR", str(bad))
    assert server.get_download_dir() == bad
    meta = client.get("/api/meta")
    m = meta.get_json()
    assert meta.status_code == 200 and "設定 → 儲存位置" in m["download_dir_error"]
    assert str(bad) in m["download_dir_error_detail"] and m["download_dir"] == str(bad)
    en = client.get("/api/meta", headers={"Accept-Language": "en-US,en;q=0.9"}).get_json()
    assert "Settings → Storage location" in en["download_dir_error"]
    s = client.get("/api/settings")
    assert s.status_code == 200 and s.get_json()["download_dir_error"]
    r = client.post("/api/download", json={"url": YT + "w", "options": {"mode": "av"}})
    assert r.status_code == 503 and r.is_json
    body = r.get_json()
    assert body["error_code"] == "download_dir_unavailable"
    assert body["error_action"] == "open_storage_settings" and body["error_faq"] == "err-download-dir"
    assert server.download_dir_problem(tmp_path) is None


def test_job_on_vanished_drive_fails_cleanly(scripted, tmp_path):
    job = server.Job(YT + "w", {"mode": "av"}, "t", job_dir=unreachable_dir(tmp_path) / "abc")
    server.run_job(job)
    assert job.status == "error" and job.error_code == "download_dir_unavailable"
    assert job.stage_code == "download_dir_unavailable"


# --------------------------------------------------------------------------- #
#  ERR6 錯誤一律回傳 JSON
# --------------------------------------------------------------------------- #
def test_unhandled_exception_returns_json_500(client, monkeypatch):
    monkeypatch.setattr(server, "list_drives", lambda: 1 / 0)
    r = client.get("/api/settings?drives=1")
    assert r.status_code == 500 and r.is_json
    body = r.get_json()
    assert body["error_code"] == "engine_internal" and body["error_action"] == "retry"
    assert "ZeroDivisionError" in body["error_detail"] and body["error"]


def test_unknown_job_is_json_404(client):
    r = client.get("/api/jobs/doesnotexist")
    assert r.status_code == 404 and r.is_json and r.get_json()["error"]


# --------------------------------------------------------------------------- #
#  R4 暫停／繼續
# --------------------------------------------------------------------------- #
def test_pause_keeps_partial_and_resume_continues_from_same_byte(scripted, client, jobs):
    started, release, sizes = threading.Event(), threading.Event(), []

    def script(y):
        y.tmp.mkdir(parents=True, exist_ok=True)
        part = y.tmp / "a [x].f137.mp4.part"
        sizes.append(part.stat().st_size if part.exists() else 0)
        for _ in range(500):
            with part.open("ab") as f:
                f.write(b"x" * 100)
            y.progress(part.stat().st_size)
            started.set()
            if release.is_set():
                break
            time.sleep(0.01)
        part.unlink()
        y.finish()

    scripted.script = script
    jid = client.post("/api/download", json={"url": YT + "w", "options": {"mode": "av"}}).get_json()["id"]
    job = jobs(server.JOBS[jid])
    assert started.wait(5)
    assert client.post(f"/api/jobs/{jid}/pause").status_code == 200
    assert wait_for(lambda: job.status == "paused")
    assert job.partial_bytes() > 0, "暫停時 .part 要保留"
    d = client.get(f"/api/jobs/{jid}").get_json()
    assert d["status"] == "paused" and d["partial"] > 0 and d["stage_code"] == "paused"
    assert saved(job)["status"] == "paused"
    assert client.post(f"/api/jobs/{jid}/pause").status_code == 409  # 已經暫停了
    release.set()
    assert client.post(f"/api/jobs/{jid}/resume").status_code == 200
    assert wait_for(lambda: job.status == "done")
    assert sizes[1] > 0, "繼續下載要從原本的位元組位置接著下載（partial_bytes 沒有歸零）"


def test_queue_position_and_pause_while_queued(scripted, client, jobs, monkeypatch):
    monkeypatch.setattr(server, "SCHED", server.Scheduler(1))
    gate = threading.Event()

    def script(y):
        gate.wait(5)
        y.finish()

    scripted.script = script
    ids = [client.post("/api/download", json={"url": YT + c, "options": {"mode": "av"}}).get_json()["id"]
           for c in "wxy"]
    js = [jobs(server.JOBS[i]) for i in ids]
    assert wait_for(lambda: js[0].status == "downloading" and server.SCHED.position(js[2]) == 2)
    listed = {j["id"]: j for j in client.get("/api/jobs").get_json()}
    assert listed[ids[1]]["queue_position"] == 1 and listed[ids[2]]["queue_position"] == 2
    assert "queue_position" not in listed[ids[0]]
    assert client.post(f"/api/jobs/{ids[1]}/pause").status_code == 200
    assert js[1].status == "paused", "排隊中暫停立即生效"
    assert saved(js[1])["status"] == "paused"
    assert wait_for(lambda: server.SCHED.position(js[2]) == 1)
    gate.set()
    assert wait_for(lambda: js[0].status == "done" and js[2].status == "done")
    assert js[1].status == "paused"
    assert client.post(f"/api/jobs/{ids[1]}/resume").status_code == 200
    assert wait_for(lambda: js[1].status == "done")


def test_cancel_queued_job_is_saved(scripted, client, jobs, monkeypatch):
    """R7：取消排隊中的工作要存檔，重開 App 才不會變成「已中斷」。"""
    monkeypatch.setattr(server, "SCHED", server.Scheduler(1))
    gate = threading.Event()
    scripted.script = lambda y: (gate.wait(5), y.finish())
    a, b = (client.post("/api/download", json={"url": YT + c, "options": {"mode": "av"}}).get_json()["id"]
            for c in "wx")
    ja, jb = jobs(server.JOBS[a]), jobs(server.JOBS[b])
    assert wait_for(lambda: ja.status == "downloading")
    assert client.post(f"/api/jobs/{b}/cancel").get_json()["status"] == "cancelled"
    assert saved(jb)["status"] == "cancelled"
    assert server.Job.load(jb.dir / server.JOB_META).status == "cancelled"
    gate.set()
    assert wait_for(lambda: ja.status == "done")
    assert jb.status == "cancelled"


def test_cancel_deletes_partial_but_pause_keeps_it(scripted):
    for reason, status, kept in (("pause", "paused", True), ("cancel", "cancelled", False)):
        job = new_job()

        def script(y, job=job, reason=reason):
            y.tmp.mkdir(parents=True, exist_ok=True)
            (y.tmp / "a.f137.mp4.part").write_bytes(b"x" * 100)
            job.stop_reason = reason
            job.cancel_flag.set()
            y.progress(100)

        scripted.script = script
        server.run_job(job)
        assert job.status == status
        assert (job.partial_bytes() > 0) is kept


def test_scheduler_limit_change_applies_immediately():
    sched = server.Scheduler(1)
    a, b = new_job("w"), new_job("x")
    assert sched.acquire(a, a.run_token)
    got = threading.Event()
    threading.Thread(target=lambda: sched.acquire(b, b.run_token) and got.set(), daemon=True).start()
    assert wait_for(lambda: sched.position(b) == 1)
    assert not got.wait(0.2)
    sched.set_limit(2)
    assert got.wait(2), "調高上限要立刻讓排隊中的工作開始，不用重開"


def test_parallel_setting(client, monkeypatch, tmp_path):
    monkeypatch.setattr(server, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr(server, "SCHED", server.Scheduler(3))
    monkeypatch.setenv("YTDL_DOWNLOAD_DIR", str(tmp_path / "dl"))  # 儲存位置被環境變數鎖住時仍可改同時下載數
    r = client.post("/api/settings", json={"parallel": 2})
    assert r.status_code == 200 and r.get_json()["parallel"] == 2
    assert server.SCHED.limit == 2
    assert json.loads((tmp_path / "settings.json").read_text(encoding="utf-8")) == {"parallel": 2}
    assert server._initial_parallel() == 2
    for bad in (0, 6, "x", None):
        assert client.post("/api/settings", json={"parallel": bad}).status_code == 400
    assert client.get("/api/settings").get_json()["parallel_range"] == [1, 5]


# --------------------------------------------------------------------------- #
#  R5 刪除（只移除紀錄／資源回收筒）、清除已完成
# --------------------------------------------------------------------------- #
def test_delete_defaults_to_keeping_files(client, jobs, tmp_path):
    job = jobs(done_job(tmp_path))
    r = client.delete(f"/api/jobs/{job.id}")
    assert r.status_code == 200 and r.get_json()["files"] == "keep"
    assert (job.dir / "v.mp4").exists(), "預設只從清單移除，檔案要留著"
    assert not (job.dir / server.JOB_META).exists()
    assert job.id not in server.JOBS


def test_delete_with_trash_uses_recycle_bin(client, jobs, tmp_path, monkeypatch):
    trashed = []
    monkeypatch.setattr(server, "send2trash", trashed.append)
    job = jobs(done_job(tmp_path))
    assert client.delete(f"/api/jobs/{job.id}?files=trash").status_code == 200
    assert trashed == [str(job.dir)]
    assert job.id not in server.JOBS


def test_delete_trash_failure_keeps_everything(client, jobs, tmp_path, monkeypatch):
    def boom(path):
        raise OSError("recycle bin unavailable")
    monkeypatch.setattr(server, "send2trash", boom)
    job = jobs(done_job(tmp_path))
    r = client.delete(f"/api/jobs/{job.id}?files=trash")
    assert r.status_code == 500 and r.get_json()["error_code"] == "engine_internal"
    assert (job.dir / "v.mp4").exists() and job.id in server.JOBS
    monkeypatch.setattr(server, "send2trash", None)
    assert client.delete(f"/api/jobs/{job.id}?files=trash").status_code == 500
    assert client.delete(f"/api/jobs/{job.id}?files=nuke").status_code == 400


def test_clear_removes_finished_jobs_only(client, jobs, tmp_path):
    a, b = jobs(done_job(tmp_path)), jobs(done_job(tmp_path))
    err = jobs(done_job(tmp_path, status="error"))
    r = client.post("/api/jobs/clear").get_json()
    assert r["count"] == 2 and set(r["ids"]) == {a.id, b.id}
    assert a.id not in server.JOBS and b.id not in server.JOBS and err.id in server.JOBS
    assert (a.dir / "v.mp4").exists() and (b.dir / "v.mp4").exists()


# --------------------------------------------------------------------------- #
#  R8 settings.json 原子寫入
# --------------------------------------------------------------------------- #
def test_settings_are_written_atomically_with_backup(monkeypatch, tmp_path):
    f = tmp_path / "settings.json"
    monkeypatch.setattr(server, "SETTINGS_FILE", f)
    server._save_settings({"download_dir": "A"})
    server._save_settings({"download_dir": "B"})
    assert json.loads(f.read_text(encoding="utf-8")) == {"download_dir": "B"}
    assert not (tmp_path / "settings.json.tmp").exists()
    f.write_text("{broken", encoding="utf-8")  # 例如在別的地方斷電寫壞
    assert server._load_settings() == {"download_dir": "B"}, "檔案壞掉時不能悄悄改回預設資料夾"


# --------------------------------------------------------------------------- #
#  R10 網路錯誤退避重試、全部暫停／繼續／重試
# --------------------------------------------------------------------------- #
DNS_ERR = ("ERROR: [youtube] x: Unable to download webpage: <urlopen error [Errno 11001] getaddrinfo failed> "
           "(caused by TransportError('<urlopen error [Errno 11001] getaddrinfo failed>'))")


def test_network_error_without_progress_is_retried(scripted):
    calls = []

    def script(y):
        calls.append(1)
        if len(calls) <= 2:
            raise server.yt_dlp.utils.DownloadError(DNS_ERR)
        y.finish()

    scripted.script = script
    job = new_job()
    server.run_job(job)
    assert job.status == "done" and len(calls) == 3
    assert any("秒後重試" in line for line in job.log)


def test_network_error_gives_up_after_backoff(scripted):
    calls = []

    def script(y):
        calls.append(1)
        raise server.yt_dlp.utils.DownloadError(DNS_ERR)

    scripted.script = script
    job = new_job()
    server.run_job(job)
    assert len(calls) == 1 + len(server.NET_BACKOFF)
    assert job.status == "error" and job.error_code == "network_dns" and job.error_action == "retry"


def test_backoff_schedule():
    assert server.NET_BACKOFF == (5, 15, 60)
    assert server._is_network_err("HTTP Error 503: Service Unavailable")
    assert server._is_network_err("HTTP Error 429: Too Many Requests")
    assert not server._is_network_err("HTTP Error 403: Forbidden")
    assert not server._is_network_err("Requested format is not available")


def test_pause_all_resume_all_retry_all(scripted, client, jobs, monkeypatch):
    monkeypatch.setattr(server, "SCHED", server.Scheduler(1))
    gate = threading.Event()

    def script(y):
        for _ in range(500):
            y.progress(100)
            if gate.is_set():
                break
            time.sleep(0.01)
        y.finish()

    scripted.script = script
    ids = [client.post("/api/download", json={"url": YT + c, "options": {"mode": "av"}}).get_json()["id"]
           for c in "wx"]
    js = [jobs(server.JOBS[i]) for i in ids]
    assert wait_for(lambda: js[0].status == "downloading")
    r = client.post("/api/jobs/pause_all").get_json()
    assert r["count"] == 2
    assert wait_for(lambda: all(j.status == "paused" for j in js))
    failed = jobs(server.Job(YT + "y", {"mode": "av"}, "t", job_dir=server.get_download_dir() / "failedjob"))
    failed.status = "error"
    gate.set()
    assert client.post("/api/jobs/retry_all").get_json()["count"] == 1
    assert client.post("/api/jobs/resume_all").get_json()["count"] == 2
    assert wait_for(lambda: all(j.status == "done" for j in [*js, failed]), timeout=10)


# --------------------------------------------------------------------------- #
#  R11 後處理期間的磁碟空間
# --------------------------------------------------------------------------- #
def _merge_script(free, after_start=None, then_fail=False):
    def script(y):
        y.tmp.mkdir(parents=True, exist_ok=True)
        stream = y.tmp / "a [x].f137.mp4"
        stream.write_bytes(b"x" * 1000)
        y.pp("started", "Merger", {"filepath": str(y.tmp / "a [x].mp4"), "__files_to_merge": [str(stream)]})
        if after_start is not None:
            free["v"] = after_start
        if then_fail:
            raise server.yt_dlp.utils.DownloadError("ERROR: Postprocessing: Conversion failed!")
        y.finish()
    return script


def test_merge_checks_free_space_first(scripted, monkeypatch):
    free = {"v": 1200}
    monkeypatch.setattr(server, "disk_info", lambda p: {"path": str(p), "free": free["v"], "total": 0})
    monkeypatch.setattr(server, "MIN_FREE_BYTES", 500)
    scripted.script = _merge_script(free)
    job = new_job()
    server.run_job(job)
    assert job.status == "error" and job.stage_code == "disk_full" and job.stage == "磁碟空間不足"
    assert job.error_code == "disk_full" and job.error_action == "open_storage_settings"
    assert "合併影音軌" in job.error and "需要約" in job.error
    assert job.partial_bytes() == 1000, "已下載的串流要保留，才能繼續"


def test_ffmpeg_failure_while_disk_ran_out_is_reported_as_disk_full(scripted, monkeypatch):
    free = {"v": 10_000}
    monkeypatch.setattr(server, "disk_info", lambda p: {"path": str(p), "free": free["v"], "total": 0})
    monkeypatch.setattr(server, "MIN_FREE_BYTES", 0)
    scripted.script = _merge_script(free, after_start=10, then_fail=True)
    job = new_job()
    server.run_job(job)
    assert job.status == "error" and job.error_code == "disk_full"


# --------------------------------------------------------------------------- #
#  R13 檔名長度、R14 網址檢查
# --------------------------------------------------------------------------- #
def test_file_names_are_trimmed_for_windows_paths(scripted):
    seen = {}
    scripted.script = lambda y: (seen.update(trim=y.opts["trim_file_name"]), y.finish())
    server.run_job(new_job())
    assert 32 <= seen["trim"] <= 150
    assert server._trim_length(Path("C:/a")) == 150
    assert server._trim_length(Path("C:/" + "x" * 200)) == 32


@pytest.mark.parametrize(("url", "ok"), [
    ("https://www.youtube.com/watch?v=", False),
    ("https://www.youtube.com/watch?v=abc", False),
    ("https://www.youtube.com/watch", False),
    ("https://youtu.be/", False),
    ("https://www.youtube.com/shorts/", False),
    ("ftp://x", False),
    ("https://www.youtube.com/watch?v=jNQXAC9IVRw", True),
    ("https://youtu.be/jNQXAC9IVRw?t=3", True),
    ("https://m.youtube.com/watch?list=PL123", True),
    ("https://www.youtube.com/@NASA/videos", True),
    ("https://www.youtube.com/shorts/jNQXAC9IVRw", True),
    ("https://www.youtube.com/playlist?list=PL123", True),
    ("https://vimeo.com/123", True),
])
def test_url_problem(url, ok):
    assert (server.url_problem(url) is None) is ok


def test_info_rejects_empty_video_id(client):
    r = client.post("/api/info", json={"url": "https://www.youtube.com/watch?v="})
    assert r.status_code == 400 and r.get_json()["error_code"] == "invalid_url"


# --------------------------------------------------------------------------- #
#  PERF1 /api/meta 不等 PyPI、Q7 檔案列表快取
# --------------------------------------------------------------------------- #
def test_meta_does_not_wait_for_pypi(client, monkeypatch):
    # 前面的測試呼叫 /api/meta 時可能已在背景查詢 PyPI：等它結束，免得它晚一步蓋掉這裡設定的值
    assert server._LATEST_REFRESH.acquire(timeout=30)
    server._LATEST_REFRESH.release()
    monkeypatch.setitem(server._LATEST, "checked", 0.0)
    monkeypatch.setitem(server._LATEST, "version", None)
    release = threading.Event()

    def slow_latest(channel="stable", get=None):
        release.wait(5)
        return "2099.1.1", {"info": {}}

    monkeypatch.setattr(server.ytdlp_update, "latest", slow_latest)
    t = time.monotonic()
    r = client.get("/api/meta")
    assert time.monotonic() - t < 1.0
    assert r.get_json()["latest"] is None
    release.set()
    assert wait_for(lambda: server._LATEST["version"] == "2099.1.1")
    assert client.get("/api/meta").get_json()["latest"] == "2099.1.1"


def test_pypi_lookup_timeout_is_short():
    seen = []

    def fake_get(url, timeout):
        seen.append(timeout)
        return json.dumps({"info": {"version": "1.0"}, "releases": {}}).encode()

    server.ytdlp_update.latest("stable", get=fake_get)
    assert seen == [5]


def test_finished_jobs_are_not_rescanned_on_every_poll(client, jobs, tmp_path, monkeypatch):
    job = jobs(done_job(tmp_path))
    calls = []
    orig = server.Job.files
    monkeypatch.setattr(server.Job, "files", lambda self: calls.append(self.id) or orig(self))
    for _ in range(5):
        client.get("/api/jobs")
    assert calls.count(job.id) == 1


def test_jobs_endpoint_with_1000_finished_jobs(client, tmp_path, monkeypatch):
    monkeypatch.setattr(server, "JOBS", {})
    for i in range(1000):
        j = server.Job("https://x", {"mode": "av"}, f"t{i}", job_dir=tmp_path / f"{i:04d}")
        j.dir.mkdir()
        (j.dir / "v.mp4").write_bytes(b"x")
        j.status = "done"
        server.JOBS[j.id] = j
    client.get("/api/jobs")  # 第一次輪詢建立快取
    times = []
    for _ in range(5):
        t = time.perf_counter()
        assert len(client.get("/api/jobs").get_json()) == 1000
        times.append(time.perf_counter() - t)
    assert statistics.median(times) < 0.3, times  # 目標 150 ms；CI 機器較慢，放寬一點


# --------------------------------------------------------------------------- #
#  ERR4 失敗原因寫進 engine.log 與 job.json，重開後還在
# --------------------------------------------------------------------------- #
def test_failure_is_written_to_engine_log_and_job_json(scripted, capsys):
    def script(y):
        for i in range(40):
            y.opts["logger"].info(f"line {i}")
        raise server.yt_dlp.utils.DownloadError("ERROR: Requested format is not available. Use --list-formats")

    scripted.script = script
    job = new_job()
    server.run_job(job)
    out = capsys.readouterr().out
    assert job.id in out and "Requested format" in out
    assert "    line 39" in out and "    line 10" in out and "    line 9\n" not in out
    data = saved(job)
    assert data["log"][-1] == "line 39" and data["error_code"] == "format_unavailable"
    restored = server.Job.load(job.dir / server.JOB_META)
    assert list(restored.log)[-1] == "line 39"
    assert restored.error_code == "format_unavailable" and restored.error_action == "reanalyze"


def test_old_job_json_without_codes_still_loads(tmp_path):
    d = tmp_path / "abc"
    d.mkdir()
    (d / server.JOB_META).write_text(json.dumps({
        "id": "abc", "url": "https://x", "options": {}, "title": "t", "status": "error",
        "stage": "失敗", "error": "HTTP Error 403: Forbidden", "progress": 1, "created": 1, "finished": 2,
    }), encoding="utf-8")
    job = server.Job.load(d / server.JOB_META)
    assert job.error_code == "http_403" and job.warnings == [] and job.failed_items == []
    d = job.to_dict()
    assert d["stage_code"] == "failed" and d["stage"] == "失敗"
    assert d["error"].startswith("伺服器拒絕下載") and d["error_detail"] == "HTTP Error 403: Forbidden"


# --------------------------------------------------------------------------- #
#  收尾期間的競態、清單總數未知
# --------------------------------------------------------------------------- #
def test_resume_delete_clear_wait_until_previous_run_has_finished(client, jobs, tmp_path):
    job = jobs(done_job(tmp_path, status="paused"))
    job.running = True  # 狀態已經是 paused，但上一輪的執行緒還在存檔、清暫存
    assert client.post(f"/api/jobs/{job.id}/resume").status_code == 409
    assert client.delete(f"/api/jobs/{job.id}").status_code == 409
    assert client.post(f"/api/jobs/{job.id}/cancel").get_json()["status"] == "paused"
    job.status = "done"
    assert client.post("/api/jobs/clear").get_json()["count"] == 0
    job.running = False
    assert client.post("/api/jobs/clear").get_json()["count"] == 1


def test_pause_between_scheduler_grant_and_start_does_not_run(scripted, monkeypatch):
    ran = []
    scripted.script = lambda y: (ran.append(1), y.finish())
    job = new_job()
    monkeypatch.setattr(server, "SCHED", server.Scheduler(1))  # 不和其他測試留下的執行緒共用名額
    real_acquire = server.SCHED.acquire

    def acquire_then_pause(j, token):
        ok = real_acquire(j, token)
        with server.JOBS_LOCK:
            server._stop(j, "pause")  # 剛拿到名額的瞬間被暫停
        return ok

    monkeypatch.setattr(server.SCHED, "acquire", acquire_then_pause)
    server.run_job(job)
    assert ran == [] and job.status == "paused" and not job.running
    assert server.SCHED.running == 0, "沒開始的工作也要還名額"


def test_unknown_playlist_total_still_collects_failures():
    job = new_job(playlist=True)
    log = server.JobLogger(job, collect_failures=True)
    log.info("[download] Downloading item 4 of NA")
    log.error("ERROR: [youtube] abcdefghijk: Private video. Sign in if you've been granted access")
    assert job._autonumber == 4 and job.total_count is None and job.item == "4"
    assert job._run_failures[0]["index"] == 4 and job._run_failures[0]["error_code"] == "private_video"


def test_queue_position_ignores_superseded_entries():
    sched = server.Scheduler(1)
    a, b = new_job("w"), new_job("x")
    sched.waiting = [(a, a.run_token - 1), (a, a.run_token), (b, b.run_token)]
    assert sched.position(a) == 1 and sched.position(b) == 2


# --------------------------------------------------------------------------- #
#  第二階段：engine_messages、Accept-Language、工作只存代碼＋參數
# --------------------------------------------------------------------------- #
EN = {"Accept-Language": "en-US,en;q=0.9"}


@pytest.mark.parametrize(("header", "lang"), [
    (None, "zh"), ("en", "en"), ("en-GB", "en"), ("zh-TW,en;q=0.8", "zh"), ("ja", "zh"), ("", "zh"),
])
def test_language_follows_accept_language(client, header, lang):
    headers = {"Accept-Language": header} if header is not None else {}
    body = client.post("/api/info", json={"url": "ftp://x"}, headers=headers).get_json()
    assert body["error_code"] == "invalid_url"
    assert body["error"] == server.em.error_payload("invalid_url", lang)["message"]


def test_api_errors_are_bilingual(client, monkeypatch):
    zh = client.get("/api/jobs/nope").get_json()["error"]
    en = client.get("/api/jobs/nope", headers=EN).get_json()["error"]
    assert zh == "找不到指定的工作或檔案" and en == "The job or file wasn't found."
    r = client.post("/api/info", json={"url": "https://www.youtube.com/watch?v="}, headers=EN).get_json()
    assert r["error"] == "This YouTube link is incomplete. Copy the full video link."
    monkeypatch.setattr(server, "list_drives", lambda: 1 / 0)
    r = client.get("/api/settings?drives=1", headers=EN).get_json()
    assert r["error_code"] == "engine_internal" and r["error"].startswith("The download engine ran into an error")


def test_info_failure_uses_friendly_error(client, monkeypatch):
    class Boom:
        def __init__(self, opts):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def extract_info(self, url, download=False):
            raise server.yt_dlp.utils.DownloadError(
                "ERROR: [youtube] jNQXAC9IVRw: Sign in to confirm your age. This video may be inappropriate for "
                "some users. Use --cookies-from-browser or --cookies for the authentication.")

    monkeypatch.setattr(server.yt_dlp, "YoutubeDL", Boom)
    zh = client.post("/api/info", json={"url": YT + "w"}).get_json()
    en = client.post("/api/info", json={"url": YT + "w"}, headers=EN).get_json()
    assert zh["error_code"] == en["error_code"] == "age_restricted"
    assert zh["error_action"] == "open_cookie_settings" and zh["error_faq"] == "err-age-restricted"
    assert "--" not in zh["error"] and "--" not in en["error"]
    assert "--cookies-from-browser" in zh["error_detail"], "原文要完整保留在 error_detail"
    assert en["error"].startswith("This video is age-restricted")


def test_job_stores_codes_and_renders_per_request(scripted, client, jobs):
    def script(y):
        raise server.yt_dlp.utils.DownloadError("ERROR: Requested format is not available. Use --list-formats")

    scripted.script = script
    job = jobs(new_job())
    server.run_job(job)
    data = saved(job)
    assert data["error_code"] == "format_unavailable" and data["stage_code"] == "failed"
    assert data["error_params"]["detail"].startswith("Requested format is not available")
    zh = client.get(f"/api/jobs/{job.id}").get_json()
    en = client.get(f"/api/jobs/{job.id}", headers=EN).get_json()
    assert zh["stage"] == "失敗" and en["stage"] == "Failed"
    assert zh["error"].startswith("指定的畫質或格式已不存在") and en["error"].startswith("The selected quality")
    assert zh["error_action"] == en["error_action"] == "reanalyze"
    restored = server.Job.load(job.dir / server.JOB_META)  # 重開後切成英文，舊工作的訊息也跟著變
    assert restored.to_dict(lang="en")["error"] == en["error"]


def test_stage_text_follows_language(scripted):
    seen = {}

    def script(y):
        y.progress(10, fid="137")
        seen["zh"] = job.to_dict(lang="zh")["stage"]
        seen["en"] = job.to_dict(lang="en")["stage"]
        seen["code"] = (job.stage_code, job.stage_params)
        y.finish()

    scripted.script = script
    job = new_job()
    server.run_job(job)
    assert seen == {"zh": "下載中 137", "en": "Downloading 137", "code": ("downloading", {"format_id": "137"})}
    assert job.to_dict(lang="en")["stage"] == "Done"


def test_disk_full_points_to_storage_settings(scripted, monkeypatch):
    """ERR5：空間不足的訊息指向「設定 → 儲存位置」，不再是「下載佇列上方」。"""
    monkeypatch.setattr(server, "disk_info", lambda p: {"path": str(p), "free": 100, "total": 0})
    job = new_job()
    server.run_job(job)
    zh, en = job.to_dict(lang="zh"), job.to_dict(lang="en")
    assert zh["error_code"] == "disk_full" and zh["error_action"] == "open_storage_settings"
    assert "設定 → 儲存位置" in zh["error"] and "下載佇列上方" not in zh["error"]
    assert "Settings → Storage location" in en["error"] and zh["stage"] == "磁碟空間不足" and en["stage"] == "Disk full"


def test_http_403_suggests_update_when_newer_ytdlp_exists(scripted, monkeypatch):
    scripted.script = lambda y: (_ for _ in ()).throw(
        server.yt_dlp.utils.DownloadError("ERROR: unable to download video data: HTTP Error 403: Forbidden"))
    job = new_job()
    server.run_job(job)
    assert job.to_dict()["error_action"] == "resume"
    monkeypatch.setitem(server.UPDATE_STATE, "ready", "2099.1.1")
    assert job.to_dict()["error_action"] == "update_ytdlp"


def test_option_errors_are_bilingual(client):
    body = {"url": YT + "w", "options": {"mode": "av", "extras": {"sections": "abc"}}}
    zh = client.post("/api/download", json=body).get_json()
    en = client.post("/api/download", json=body, headers=EN).get_json()
    assert zh["error"] == "時間範圍格式錯誤：abc（例：1:30-2:45）"
    assert en["error"] == "Invalid time range: abc (example: 1:30-2:45)"


def test_interrupted_job_message_is_bilingual(tmp_path):
    d = tmp_path / "abc"
    (d / ".tmp").mkdir(parents=True)
    (d / ".tmp" / "a.mp4.part").write_bytes(b"x" * 2048)
    (d / server.JOB_META).write_text(json.dumps({"url": "https://x", "options": {}, "status": "downloading"}),
                                     encoding="utf-8")
    job = server.Job.load(d / server.JOB_META)
    zh, en = job.to_dict(lang="zh"), job.to_dict(lang="en")
    assert zh["stage"] == "已中斷" and en["stage"] == "Interrupted"
    assert zh["error_action"] == "resume" and "繼續下載" in zh["error"] and "Resume" in en["error"]


def test_phase1_job_json_still_loads(tmp_path):
    """第一階段（e11a991）寫的 job.json：舊的 stage_code、error_detail、文字型 warnings。"""
    d = tmp_path / "p1"
    d.mkdir()
    (d / server.JOB_META).write_text(json.dumps({
        "id": "p1", "url": "https://x", "options": {"playlist": True}, "title": "t", "status": "done",
        "stage": "完成 2/3", "stage_code": "done_partial", "error": "完成 2/3，1 部無法下載",
        "error_code": None, "error_detail": None, "error_action": None, "error_faq": None,
        "warnings": ["1 部無法下載"], "done_count": 2, "total_count": 3,
        "failed_items": [{"index": 2, "title": "影片 2", "id": "vid2", "error_code": "private_video",
                          "error": "Private video", "error_detail": "[youtube] vid2: Private video"}],
    }), encoding="utf-8")
    job = server.Job.load(d / server.JOB_META)
    v = job.to_dict(lang="en")
    assert v["stage"] == "Done 2/3" and v["warnings"] == ["1 部無法下載"]
    assert v["failed_items"][0]["error"].startswith("This is a private video")
    (d / server.JOB_META).write_text(json.dumps({
        "url": "https://x", "options": {}, "status": "error", "stage": "磁碟空間不足", "stage_code": "disk_full",
        "error": "磁碟空間不足：D:\\ 只剩 1.0 GB", "error_code": "disk_full", "error_detail": "磁碟空間不足：D:\\ 只剩 1.0 GB",
    }), encoding="utf-8")
    job = server.Job.load(d / server.JOB_META)
    v = job.to_dict(lang="en")
    assert v["stage"] == "Disk full" and v["error_code"] == "disk_full" and "1.0 GB" in v["error_detail"]


def test_v12_done_with_warning_job_json(tmp_path):
    d = tmp_path / "old"
    d.mkdir()
    (d / server.JOB_META).write_text(json.dumps({
        "url": "https://x", "options": {}, "status": "done", "stage": "完成（有警告）",
        "error": "部分步驟失敗：Conversion failed!",
    }), encoding="utf-8")
    job = server.Job.load(d / server.JOB_META)
    assert job.stage_code == "done_with_warnings" and job.error_code is None
    v = job.to_dict(lang="en")
    assert v["stage"] == "Done (with warnings)" and v["warnings"] == ["部分步驟失敗：Conversion failed!"]


def test_steps_failed_warning_is_bilingual(scripted):
    def script(y):
        y.finish()
        raise server.yt_dlp.utils.DownloadError("ERROR: Postprocessing: Conversion failed!")

    scripted.script = script
    job = new_job()
    server.run_job(job)
    assert job.status == "done" and job.stage_code == "done_with_warnings"
    zh, en = job.to_dict(lang="zh"), job.to_dict(lang="en")
    assert zh["warnings"][0].startswith("部分步驟失敗：下載完成，但「合併影音軌」等後製步驟失敗")
    assert en["warnings"][0].startswith("Some steps failed: The download finished")
    assert zh["error"] == zh["warnings"][0], "舊版 App 與網頁版從 error 顯示警告"


def test_every_stage_code_has_text_in_both_languages():
    for code in server.STAGE_CODES:
        for lang in ("zh", "en"):
            text = server.render_stage(code, {"format_id": "1", "attempt": 1, "max": 3, "s": 5, "done": 1,
                                              "total": 2, "name": "Merger"}, lang)
            assert text and text != code and "{" not in text, (code, lang)


def test_every_engine_text_has_both_languages():
    for key, entry in server.ENGINE_TEXT.items():
        assert set(entry) == {"zh", "en"}, key
        for lang in ("zh", "en"):
            assert "--" not in entry[lang] and "github.com" not in entry[lang].lower(), (key, lang)


def test_browser_requests_stay_chinese(client):
    """網頁版是中文介面：瀏覽器一定會帶 Accept-Language，但有 Sec-Fetch-* 標頭時一律回中文。"""
    browser = {"Accept-Language": "en-US,en;q=0.9", "Sec-Fetch-Mode": "cors", "Sec-Fetch-Site": "same-origin"}
    assert client.get("/api/jobs/nope", headers=browser).get_json()["error"] == "找不到指定的工作或檔案"
    assert client.get("/api/jobs/nope", headers=EN).get_json()["error"] == "The job or file wasn't found."


def test_steps_failed_warning_keeps_raw_reason(scripted):
    def script(y):
        y.finish()
        raise server.yt_dlp.utils.DownloadError("ERROR: Postprocessing: Conversion failed!")

    scripted.script = script
    job = new_job()
    server.run_job(job)
    assert job.warnings[0]["args"]["detail"] == "Postprocessing: Conversion failed!"
    assert "Conversion failed" not in job.to_dict(lang="zh")["warnings"][0]
