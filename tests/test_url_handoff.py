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


def test_parse_args_filters_and_dedupes():
    args = ["--smoke-test", f"ytdl://add?url={enc(YT)}", YT, "javascript:alert(1)", "https://example.com/b"]
    assert parse_handoff_args(args) == [YT, "https://example.com/b"]
    assert parse_handoff_args([]) == []
    assert parse_handoff_args(None) == []
