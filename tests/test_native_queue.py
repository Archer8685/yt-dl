"""native_queue.py（下載佇列頁）的行為測試；用 offscreen 平台，不需要螢幕。"""
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", "C:/Windows/Fonts" if os.name == "nt" else "")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QMessageBox, QPushButton

import native_app as na
import native_common as nc
import native_options
import native_queue as nq


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    # 介面會存 QSettings：測試寫到暫存的 ini 檔，不要動到這台電腦的真實設定
    ini = str(tmp_path_factory.mktemp("qsettings") / "native.ini")
    native_options.QSettings = nc.QSettings = lambda *a, **k: QSettings(ini, QSettings.IniFormat)
    a, _ = na.create_app()
    return a


class FakeApi:
    """記下請求、由測試決定何時回應。"""

    def __init__(self):
        self.calls = []

    def _add(self, method, path, body, ok, err):
        self.calls.append((method, path, body, ok, err))

    def post(self, path, body=None, ok=None, err=None, timeout_ms=0):
        self._add("POST", path, body, ok, err)

    def get(self, path, ok=None, err=None, timeout_ms=0):
        self._add("GET", path, None, ok, err)

    def delete(self, path, ok=None, err=None, timeout_ms=0):
        self._add("DELETE", path, None, ok, err)

    def image(self, url, ok, timeout_ms=0):
        self._add("IMG", url, None, ok, None)

    def last(self, path):
        return [c for c in self.calls if c[1] == path][-1]


# --------------------------------------------------------------------------- #
#  下載佇列
# --------------------------------------------------------------------------- #
def job(jid, status, **kw):
    return {"id": jid, "url": "u", "title": f"T{jid}", "status": status, "progress": 0, **kw}


def test_job_actions_refresh_without_type_error(app):
    api = FakeApi()
    calls = []
    row = nq.JobRow(api, lambda *a: calls.append(a))
    row.update_job(job("1", "downloading"))
    next(b for b in row.findChildren(QPushButton) if b.text() == "取消").click()
    method, path, _b, ok, _err = api.calls[-1]
    assert (method, path) == ("POST", "/api/jobs/1/cancel")
    ok({"id": "1"})  # Api 呼叫成功回呼時會傳入回應內容
    assert calls == [()]


def test_delete_asks_before_removing_files(app, monkeypatch):
    api = FakeApi()
    row = nq.JobRow(api, lambda *a: None)
    row.update_job(job("2", "done", files=[{"name": "v.mp4", "size": 5_000_000}]))
    seen = {}

    def answer(choice):
        def exec_(box):
            seen["text"] = box.informativeText()
            next(b for b in box.buttons() if b.text() == choice).click()
            return 0
        return exec_

    monkeypatch.setattr(QMessageBox, "exec", answer("取消"))
    delete = next(b for b in row.findChildren(QPushButton) if b.text() == "刪除")
    delete.click()
    assert not [c for c in api.calls if c[0] == "DELETE"]
    assert "永久刪除" in seen["text"]
    monkeypatch.setattr(QMessageBox, "exec", answer("刪除"))
    delete.click()
    assert [c[1] for c in api.calls if c[0] == "DELETE"] == ["/api/jobs/2"]


def test_cancelled_job_with_files_can_be_revealed(app):
    row = nq.JobRow(FakeApi(), lambda *a: None)
    row.update_job(job("3", "cancelled", files=[{"name": "a.mp4", "size": 1}]))
    texts = [b.text() for b in row.findChildren(QPushButton)]
    assert f"在{nc.FILE_MANAGER}中顯示" in texts and "刪除" in texts


def test_queue_ignores_older_snapshot(app):
    api = FakeApi()
    q = nq.QueuePage(api)
    q.refresh()
    q.refresh()
    first, second = [c for c in api.calls if c[1] == "/api/jobs"]
    second[3]([job("b", "done")])
    first[3]([job("a", "downloading")])  # 較晚回來的舊結果
    assert q.order == ["b"]


def test_queue_reports_offline_after_two_failed_polls(app):
    api = FakeApi()
    q = nq.QueuePage(api)
    states = []
    q.online.connect(lambda ok, msg: states.append(ok))
    q._poll()
    api.last("/api/jobs")[4]("Connection refused")
    assert states == []  # 一次失敗不算斷線
    q._poll()
    api.last("/api/jobs")[4]("Connection refused")
    assert states == [False]
    q._poll()
    api.last("/api/jobs")[3]([])
    assert states == [False, True]
    q._timer.stop()


def test_queue_does_not_stack_polls(app):
    api = FakeApi()
    q = nq.QueuePage(api)
    q._poll()
    q._poll()  # 上一次還沒回來：不能再送
    assert len([c for c in api.calls if c[1] == "/api/jobs"]) == 1
    q._timer.stop()
