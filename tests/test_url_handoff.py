"""url_handoff.parse_handoff：只放行 http/https 影片網址，其他（含惡意網址）一律拒絕。"""
from __future__ import annotations

from urllib.parse import quote

import pytest
from PySide6.QtCore import QUrl

from url_handoff import MAX_URL_LENGTH, parse_handoff, parse_handoff_args

YT = "https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PL123&t=42s"


def enc(url: str) -> str:
    """和書籤小工具的 encodeURIComponent 一樣的編碼。"""
    return quote(url, safe="-_.!~*'()")


@pytest.mark.parametrize("arg, expected", [
    (f"ytdl://add?url={enc(YT)}", YT),
    (f"ytdl://add/?url={enc(YT)}", YT),  # Windows／部分瀏覽器會補斜線
    (f"YTDL://ADD?url={enc(YT)}", YT),
    (f"ytdl://add?foo=1&url={enc(YT)}", YT),
    (YT, YT),
    ("http://example.com/video", "http://example.com/video"),
    ("HTTPS://youtu.be/dQw4w9WgXcQ", "HTTPS://youtu.be/dQw4w9WgXcQ"),
    (f"  {YT}\n", YT),  # 命令列前後的空白
    ("https://www.bilibili.com/video/BV1xx411c7mD?p=2", "https://www.bilibili.com/video/BV1xx411c7mD?p=2"),
    ("https://例子.tw/影片", "https://例子.tw/影片"),
])
def test_accepts_valid(arg, expected):
    assert parse_handoff(arg) == expected


def test_plus_is_not_turned_into_space():
    url = "https://example.com/search?q=a+b"
    assert parse_handoff(f"ytdl://add?url={enc(url)}") == url
    assert parse_handoff("ytdl://add?url=https://example.com/search?q=a+b") == url  # 沒編碼的 + 也保留


def test_accepts_qurl_from_file_open_event():
    assert parse_handoff(QUrl(f"ytdl://add?url={enc(YT)}")) == YT
    assert parse_handoff(QUrl("https://youtu.be/dQw4w9WgXcQ")) == "https://youtu.be/dQw4w9WgXcQ"
    assert parse_handoff(QUrl("file:///etc/passwd")) is None
    # 百分比編碼要原封不動交給 parse_handoff 解碼一次（不能先被 QUrl 解掉一部分）
    url = "https://example.com/a%2Fb?q=%E5%BD%B1%26x"
    assert parse_handoff(QUrl(f"ytdl://add?url={enc(url)}")) == url
    assert parse_handoff(QUrl(f"ytdl://add?url={enc('https://example.com/a?q=c d')}")) is None
    assert parse_handoff(QUrl(f"ytdl://add?url={enc(enc('javascript:alert(1)'))}")) is None
    assert parse_handoff(QUrl()) is None


@pytest.mark.parametrize("arg", [
    # 危險協定，直接給或包在 ytdl:// 裡
    "javascript:alert(1)",
    "ytdl://add?url=javascript:alert(document.cookie)",
    f"ytdl://add?url={enc('javascript:alert(1)')}",
    "ytdl://add?url=JaVaScRiPt%3Aalert(1)",
    "ytdl://add?url=%20javascript:alert(1)",
    "file:///C:/Windows/System32/calc.exe",
    "file:///etc/passwd",
    f"ytdl://add?url={enc('file:///etc/passwd')}",
    "ytdl://add?url=file://server/share/x.mp4",
    "data:text/html,<script>alert(1)</script>",
    f"ytdl://add?url={enc('data:text/html;base64,PHNjcmlwdD4=')}",
    "vbscript:msgbox(1)",
    "ftp://example.com/a.mp4",
    "ytdl://add?url=ytdl://add?url=https://example.com",
    # 重複編碼：只解碼一次，結果不是 http/https 就拒絕
    f"ytdl://add?url={enc(enc('javascript:alert(1)'))}",
    f"ytdl://add?url={enc(enc(YT))}",
    f"ytdl://add?url={enc(enc(enc('file:///etc/passwd')))}",
    # 格式不對
    "ytdl://add",
    "ytdl://add?url=",
    "ytdl://add?link=https://example.com",
    f"ytdl://download?url={enc(YT)}",
    f"ytdl://add/extra?url={enc(YT)}",
    f"ytdl://add?url={enc(YT)}&url={enc('https://evil.example')}",
    f"ytdl://add?url={enc(YT)}#frag",
    "ytdl:add?url=https://example.com",
    "https://",
    "https:///path-only",
    "https:/example.com",
    "https:\\\\example.com\\a",
    "http://exa mple.com/",
    f"ytdl://add?url={enc('https://example.com/a?q=c d')}",  # 解碼後有空白
    "https://example.com/\r\nX-Injected: 1",
    f"ytdl://add?url={enc('https://example.com/%0d%0a')}%0AX:1",
    f"ytdl://add?url={enc('https://example.com/')}%0D%0A",
    "https://example.com:99999/",
    "https://example.com:abc/",
    "https://example.com:0/",
    "https://www.youtube.com@evil.example/watch?v=x",
    "https://user:pass@example.com/",
    "ytdl://add?url=%E0%A4%A",  # 壞掉的百分比編碼
    "ytdl://add?url=%FF%FE",  # 不是 UTF-8
    "--smoke-test",
    "C:\\Users\\me\\video.mp4",
    "/Users/me/video.mp4",
    "",
    "   ",
    None,
    123,
    ["https://example.com"],
])
def test_rejects(arg):
    assert parse_handoff(arg) is None


def test_length_limit():
    base = "https://example.com/?q="
    ok = base + "a" * (MAX_URL_LENGTH - len(base))
    assert len(ok) == MAX_URL_LENGTH
    assert parse_handoff(ok) == ok
    assert parse_handoff(ok + "a") is None
    assert parse_handoff(f"ytdl://add?url={enc(ok)}") == ok
    assert parse_handoff(f"ytdl://add?url={enc(ok + 'a')}") is None
    assert parse_handoff("ytdl://add?url=" + "%41" * 100_000) is None  # 超長的原始參數直接拒絕
    assert parse_handoff("https://example.com/" + "a" * 1_000_000) is None


LOOPBACK = [
    "http://localhost/admin", "http://LOCALHOST:8765/api/jobs", "http://localhost./", "http://app.localhost/",
    "http://127.0.0.1:5000/", "http://127.8.9.10/", "http://127.1/", "http://2130706433/", "http://2130706432/",
    "http://0x7f.0.0.1/",
    "http://0177.0.0.1/", "http://0x7f000001/", "http://127.0.0.1./", "http://0.0.0.0:8765/", "http://0/",
    "http://[::1]/", "http://[0:0:0:0:0:0:0:1]:8080/", "http://[::]/", "http://[::ffff:127.0.0.1]/",
    "http://[::ffff:7f00:1]/", "http://%31%32%37.0.0.1/", "http://１２７．０．０．１/", "http://127。0。0。1/",
]


@pytest.mark.parametrize("url", LOOPBACK)
def test_ytdl_rejects_loopback(url):
    """ytdl:// 是任何網頁都能觸發的：不能拿來叫 App 去連這台電腦上的服務（v13-followups「給 D」）。"""
    assert parse_handoff(f"ytdl://add?url={enc(url)}") is None
    assert parse_handoff(QUrl(f"ytdl://add?url={enc(url)}")) is None


@pytest.mark.parametrize("url", ["http://localhost:8080/video.mp4", "http://127.0.0.1/v", "http://[::1]/v"])
def test_direct_loopback_url_still_accepted(url):
    """命令列、拖到 App 圖示上是使用者自己的動作（例如測試本機的影片伺服器），照舊放行。"""
    assert parse_handoff(url) == url


@pytest.mark.parametrize("url", [
    "https://127.example.com/v", "https://localhost.example.com/v", "https://1.2.3.4/v",
    "https://128.0.0.1/v", "https://192.168.1.10/v", "https://[2001:db8::1]/v", "https://youtube.com./watch?v=x",
    "https://0x7f.example/v", "https://2130706431/v",  # 2130706431 = 126.255.255.255（127.0.0.0 的前一個）
])
def test_ytdl_accepts_non_loopback(url):
    assert parse_handoff(f"ytdl://add?url={enc(url)}") == url


def test_is_loopback_host_edge_cases():
    from url_handoff import is_loopback_host
    assert is_loopback_host("127.255.255.255")
    assert not is_loopback_host("127.0.0.1.1")  # 五段：不是 IPv4，是一般主機名稱
    assert not is_loopback_host("256.0.0.1") and not is_loopback_host("")
    assert not is_loopback_host("fe80::1%eth0") and is_loopback_host("::1%lo")
    # int() 會接受的奇怪寫法不能讓它丟例外（負數會讓 IPv4Address 丟 ValueError）
    for host in ("-1", "0x-1", "+127.0.0.1", "1_27.0.0.1", "-1.0.0.1", "0x", "٣"):
        assert is_loopback_host(host) in (True, False), host


@pytest.mark.parametrize("host", ["-1", "0x-1", "-1.0.0.1", "+1"])
def test_odd_numeric_hosts_do_not_crash(host):
    url = f"http://{host}/v"
    assert parse_handoff(f"ytdl://add?url={enc(url)}") in (url, None)


@pytest.mark.parametrize("arg, local", [
    (f"ytdl://add?url={enc('http://127.0.0.1:8765/api/jobs')}", True),
    (f"ytdl://add?url={enc('http://localhost/x')}", True),
    (f"ytdl://add?url={enc('javascript:alert(1)')}", False),  # 協定不對，不是「指向這台電腦」
    (f"ytdl://add?url={enc('file:///C:/Windows/win.ini')}", False),
    (f"ytdl://add?url={enc(YT)}", False),  # 會被接受的網址
    ("http://127.0.0.1/x", False),  # 直接給的網址不受限制
    ("ytdl://add", False),
])
def test_rejected_as_local(arg, local):
    from url_handoff import rejected_as_local
    assert rejected_as_local(arg) is local


def test_parse_args_filters_and_dedupes():
    args = ["--smoke-test", f"ytdl://add?url={enc(YT)}", YT, "javascript:alert(1)", "https://example.com/b"]
    assert parse_handoff_args(args) == [YT, "https://example.com/b"]
    assert parse_handoff_args([]) == []
    assert parse_handoff_args(None) == []
