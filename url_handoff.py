"""從命令列參數或 macOS 的開啟網址事件取出要交給 App 的影片網址。

接受三種來源：
- `ytdl://add?url=<encodeURIComponent 後的網址>`（書籤小工具、安裝時註冊的協定；格式見 ROADMAP 第 5.5 節）
- 直接的 `http://`／`https://` 網址（例如拖到 App 圖示上、或從命令列傳入）
- macOS `QFileOpenEvent.url()` 傳來的 QUrl（內容就是上面兩種之一）

**只回傳網址，不做任何下載動作**：任何網頁都能觸發 `ytdl://` 連結，App 收到後只能填入網址並解析，
要由使用者自己按下載。

安全規則：
- 解碼後只接受 http／https，而且要有主機名稱；拒絕 `file:`、`javascript:`、`data:` 等其他協定。
- `ytdl://` 的網址參數只解碼一次。解碼一次還不是 http／https（例如重複編碼的 `javascript%3A…`）就拒絕，
  不會一直解碼下去。
- 網址長度上限 2048 個字元；不接受空白、換行等控制字元，也不接受 `帳號:密碼@主機` 形式
  （`https://youtube.com@evil.example/` 這種看起來像 YouTube 的網址）。
- `ytdl://` 來的網址不接受本機位址（localhost、127.0.0.0/8、::1、0.0.0.0，含 `127.1`、`2130706433`、
  `0x7f.1`、`[::ffff:127.0.0.1]` 這類瀏覽器也認得的寫法）：App 收到後會自動解析，等於讓任何網頁
  叫本機的引擎去連這台電腦上的服務。直接從命令列或拖放給的網址是使用者自己的動作，不受這條限制。
"""
from __future__ import annotations

import ipaddress
import re
import unicodedata
from urllib.parse import unquote, urlsplit

from PySide6.QtCore import QUrl

MAX_URL_LENGTH = 2048
SCHEME = "ytdl"
_ALLOWED_SCHEMES = ("http", "https")
_HEX = re.compile(r"0[xX]([0-9A-Fa-f]*)", re.ASCII)
_OCT = re.compile(r"0[0-7]+", re.ASCII)
_DEC = re.compile(r"[0-9]+", re.ASCII)
_MAX_RAW_LENGTH = MAX_URL_LENGTH * 3 + 64  # 編碼過的 ytdl:// 參數最多約 3 倍長；再長一定超過上限，不必解析


def parse_handoff(arg) -> str | None:
    """把一個參數轉成可以交給「新增下載」頁的網址；不是可接受的網址就回傳 None。

    `arg` 可以是字串，或 QUrl（macOS 的 `QFileOpenEvent.url()`）。
    """
    text = _as_text(arg)
    if text is None:
        return None
    text = text.strip()
    if not text or len(text) > _MAX_RAW_LENGTH:
        return None
    scheme = text.split(":", 1)[0].lower() if ":" in text else ""
    if scheme == SCHEME:
        return _from_ytdl(text)
    if scheme in _ALLOWED_SCHEMES:
        return _validate(text)
    return None


def parse_handoff_args(args) -> list[str]:
    """把一串命令列參數（例如 `sys.argv[1:]` 或 SingleInstance 收到的 list）轉成網址清單，去掉重複、保留順序。"""
    urls: list[str] = []
    for arg in args or []:
        url = parse_handoff(arg)
        if url is not None and url not in urls:
            urls.append(url)
    return urls


def _as_text(arg) -> str | None:
    if isinstance(arg, str):
        return arg
    if isinstance(arg, QUrl):
        # FullyEncoded：保留所有百分比編碼，之後只由 _from_ytdl 解碼一次（預設的 PrettyDecoded 會先解掉一部分）
        return arg.toString(QUrl.ComponentFormattingOption.FullyEncoded)
    return None


def _from_ytdl(text: str) -> str | None:
    """`ytdl://add?url=<編碼後的網址>`；也接受瀏覽器或 Windows 會補上的 `ytdl://add/?url=…`。"""
    if any(_is_bad_char(c) for c in text):
        return None
    try:
        parts = urlsplit(text)
    except ValueError:
        return None
    if parts.netloc.lower() != "add" or parts.path not in ("", "/") or parts.fragment:
        return None
    values = [v for k, v in _query_pairs(parts.query) if k == "url"]
    if len(values) != 1:  # 沒有或多個 url 參數：不猜哪一個才對
        return None
    try:
        decoded = unquote(values[0], errors="strict")  # 只解碼一次；不把 + 當空白（encodeURIComponent 會把空白編成 %20）
    except UnicodeDecodeError:
        return None
    return _validate(decoded, allow_loopback=False)


def _query_pairs(query: str):
    for piece in query.split("&"):
        if not piece:
            continue
        key, sep, value = piece.partition("=")
        yield key, (value if sep else "")


def _is_bad_char(c: str) -> bool:
    return c <= " " or c == "\x7f" or c in "  ﻿"


def _ipv4_number(part: str) -> int | None:
    """WHATWG 網址規則的 IPv4 片段：十進位、0x 十六進位、0 開頭八進位。

    先用正規表示式限定 ASCII 數字：int() 也吃「-1」「+5」「1_0」和全形以外的 Unicode 數字，
    負數會讓 IPv4Address 丟例外。
    """
    if m := _HEX.fullmatch(part):
        return int(m.group(1) or "0", 16)
    if _OCT.fullmatch(part):
        return int(part, 8)
    if _DEC.fullmatch(part):
        return int(part, 10)
    return None


def _parse_ipv4(host: str) -> ipaddress.IPv4Address | None:
    """瀏覽器（WHATWG）認得的 IPv4 寫法：`127.0.0.1`、`127.1`、`2130706433`、`0x7f.0.0.1`、`0177.0.0.1`。"""
    parts = host.split(".")
    if parts and parts[-1] == "":  # 結尾的點：「127.0.0.1.」
        parts = parts[:-1]
    if not 1 <= len(parts) <= 4 or any(p == "" for p in parts):
        return None
    nums = [_ipv4_number(p) for p in parts]
    if any(n is None for n in nums):
        return None
    *head, last = nums
    if any(n > 255 for n in head) or last >= 256 ** (5 - len(nums)):
        return None
    value = last
    for i, n in enumerate(head):
        value += n << (8 * (3 - i))
    return ipaddress.IPv4Address(value)


def is_loopback_host(host: str) -> bool:
    """主機是不是指向這台電腦（loopback 或 0.0.0.0／::）。host 是 urlsplit().hostname（小寫、沒有方括號）。"""
    host = unicodedata.normalize("NFKC", unquote(host or "")).replace("。", ".").lower()
    name = host.rstrip(".")
    if name == "localhost" or name.endswith(".localhost"):
        return True
    addr: ipaddress.IPv4Address | ipaddress.IPv6Address | None = None
    if ":" in host:
        try:
            addr = ipaddress.IPv6Address(host.split("%", 1)[0])  # 去掉 zone id（fe80::1%eth0）
        except ValueError:
            return False
        mapped = addr.ipv4_mapped
        if mapped is not None:
            addr = mapped
    else:
        addr = _parse_ipv4(host)
    return addr is not None and (addr.is_loopback or addr.is_unspecified)


def _validate(url: str, allow_loopback: bool = True) -> str | None:
    if not url or len(url) > MAX_URL_LENGTH:
        return None
    if any(_is_bad_char(c) or c == "\\" for c in url):
        return None
    try:
        parts = urlsplit(url)
        port = parts.port  # 連接埠不是數字或超出範圍時會丟 ValueError
    except ValueError:
        return None
    if parts.scheme.lower() not in _ALLOWED_SCHEMES or not url.lower().startswith(parts.scheme.lower() + "://"):
        return None
    if not parts.hostname or "@" in parts.netloc:
        return None
    if port == 0:
        return None
    if not allow_loopback and is_loopback_host(parts.hostname):
        return None
    return url
