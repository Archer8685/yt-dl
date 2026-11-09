"""英文介面收尾檢查（ROADMAP 5.4「D」、驗收第 6、13 點）。

1. 介面檔裡使用者看得到的中文字串都包了翻譯函式（self.tr／QCoreApplication.translate／_tr／
   QT_TRANSLATE_NOOP）。用 AST 掃描：中文字串常值只能出現在翻譯函式的參數、docstring、log／print，
   或下面 ALLOWED 列出的地方。
2. 翻譯檔 i18n/yt_dl_en.ts 沒有未翻譯的項目（I2 已補完）。改了介面字串後重新抽字串，新字串補好翻譯才會通過。
3. engine_messages.py 的每個錯誤代碼在 USER_GUIDE.md 和 USER_GUIDE.en.md 都有錨點。
"""
from __future__ import annotations

import ast
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import i18n_update

CJK = re.compile(r"[㐀-鿿豈-﫿　-〿！-～]")
TR_FUNCS = {"tr", "translate", "_tr", "QT_TRANSLATE_NOOP"}
LOG_FUNCS = {"debug", "info", "warning", "error", "exception", "critical", "log"}
LOG_OWNERS = {"log", "logger", "logging"}
# 不給使用者看、或刻意不翻譯的中文字串：(檔名, 字串的一部分) → 理由
ALLOWED: dict[tuple[str, str], str] = {
    # 解析使用者輸入用的正規表示式／分隔字元（使用者可能打中文標點），不是顯示文字
    ("native_playlist.py", "，、;；"): "範圍輸入接受中文標點",
    ("native_playlist.py", "~～:："): "範圍輸入接受全形連字號",
    ("native_options.py", "[-~到]"): "和 server._parse_ranges 相同的正規表示式",
    ("url_handoff.py", "。"): "主機名稱裡的全形句點（瀏覽器當成 .）",
    ("native_download.py", "，。、；（）「」"): "從文字裡抓網址的正規表示式（全形標點當結尾）",
    ("native_download.py", ".,;:!?)]}>，。、；"): "網址尾端要去掉的標點",
    # 要和 .github/ISSUE_TEMPLATE/bug_report.yml 的下拉選項一字不差，GitHub 才會預先選好
    ("native_settings.py", "中文（繁體）"): "回報問題表單的選項值",
    ("native_settings.py", "其他（請在下方說明）"): "回報問題表單的選項值",
    ("native_settings.py", "（Apple 晶片 / Apple silicon）"): "回報問題表單的選項值",
    # 引擎的 /api/meta update_message 目前只有中文、也沒有成功／失敗代碼，只能比對前綴判斷（待引擎補代碼）
    ("native_settings.py", "更新失敗"): "比對引擎訊息，不是顯示文字",
}


def _ui_files() -> list[Path]:
    return [p for p in i18n_update.ui_sources(ROOT)]


def _docstring_ids(tree: ast.AST) -> set[int]:
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                ids.add(id(first.value))
    return ids


def _func_name(call: ast.Call) -> str:
    f = call.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        return f.attr
    return ""


def _is_log_call(call: ast.Call) -> bool:
    """print(...)、log.info(...)／logger.warning(...)／logging.error(...)。

    只認 log／logger／logging 開頭的呼叫：QMessageBox.warning(...) 這種同名的介面函式不算。
    """
    f = call.func
    if isinstance(f, ast.Name):
        return f.id == "print"
    return (isinstance(f, ast.Attribute) and f.attr in LOG_FUNCS and isinstance(f.value, ast.Name)
            and f.value.id.lstrip("_").lower() in LOG_OWNERS)


def _exempt_ids(tree: ast.AST) -> set[int]:
    """翻譯函式與 log／print 呼叫裡的字串常值（含 f-string 片段）。"""
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and (_func_name(node) in TR_FUNCS or _is_log_call(node)):
            for arg in [*node.args, *(k.value for k in node.keywords)]:
                for sub in ast.walk(arg):
                    if isinstance(sub, ast.Constant):
                        ids.add(id(sub))
    return ids


def untranslated(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    skip = _docstring_ids(tree) | _exempt_ids(tree)
    found = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in skip
                and CJK.search(node.value)
                and not any(name == path.name and part in node.value for (name, part) in ALLOWED)):
            found.append(f"{path.name}:{node.lineno}: {node.value[:40]!r}")
    return found


def test_scanner_finds_bare_chinese(tmp_path):
    src = tmp_path / "demo.py"
    src.write_text('"""說明"""\n'
                   'from PySide6.QtCore import QCoreApplication\n'
                   '_tr = QCoreApplication.translate\n'
                   'def f(self, n):\n'
                   '    """函式說明"""\n'
                   '    a = self.tr("已包")\n'
                   '    b = _tr("demo", "已包 %n 部", None, n)\n'
                   '    print("紀錄")\n'
                   '    log.warning("紀錄 %s", n)\n'
                   '    QMessageBox.warning(self, "標題", "訊息")\n'
                   '    c = "沒包"\n'
                   '    d = f"也沒包 {n}"\n', encoding="utf-8")
    found = untranslated(src)
    assert sorted(f.split(": ", 1)[1] for f in found) == ["'也沒包 '", "'標題'", "'沒包'", "'訊息'"]


@pytest.mark.parametrize("path", _ui_files(), ids=lambda p: p.name)
def test_ui_strings_are_wrapped(path):
    found = untranslated(path)
    assert not found, "沒包翻譯函式的中文字串（見 docs/I18N.md）：\n" + "\n".join(found)


# --------------------------------------------------------------------------- 翻譯檔

def _messages():
    root = ET.parse(i18n_update.ts_path("en")).getroot()
    for ctx in root.iter("context"):
        name = ctx.findtext("name")
        for msg in ctx.iter("message"):
            yield name, msg


def _untranslated_messages() -> list[str]:
    out = []
    for ctx, msg in _messages():
        tr = msg.find("translation")
        if tr is not None and tr.get("type") in ("obsolete", "vanished"):
            continue
        numerus = msg.get("numerus") == "yes"
        forms = [f.text for f in tr.iter("numerusform")] if (numerus and tr is not None) else [
            tr.text if tr is not None else None]
        if tr is None or tr.get("type") == "unfinished" or not all((f or "").strip() for f in forms):
            out.append(f"{ctx}: {msg.findtext('source')!r}")
    return out


def test_ts_file_fully_translated():
    """改了介面字串後跑 python tools/i18n_update.py --no-release：新字串會是 unfinished，這項會失敗直到補完翻譯。"""
    assert any(True for _ in _messages()), "翻譯檔還是空的：先跑 python tools/i18n_update.py 抽字串"
    missing = _untranslated_messages()
    assert not missing, f"{len(missing)} 個未翻譯：\n" + "\n".join(missing[:30])


def test_numerus_translations_have_both_forms():
    """有 %n 的翻譯（已經翻好的）要有單數和複數兩種寫法，英文才不會出現「1 videos」。"""
    bad = []
    for ctx, msg in _messages():
        tr = msg.find("translation")
        if msg.get("numerus") != "yes" or tr is None or tr.get("type") == "unfinished":
            continue
        forms = [f.text for f in tr.iter("numerusform")]
        if len(forms) < 2 or not all((f or "").strip() for f in forms):
            bad.append(f"{ctx}: {msg.findtext('source')!r}")
    assert not bad, "\n".join(bad)


def test_translations_keep_placeholders():
    """已翻譯的字串要保留原文的 {name} 佔位（少了 .format() 會 KeyError 或漏資料）。"""
    bad = []
    for ctx, msg in _messages():
        tr = msg.find("translation")
        if tr is None or tr.get("type") in ("unfinished", "obsolete", "vanished"):
            continue
        src = set(re.findall(r"(?<!\{)\{(\w+)\}(?!\})", msg.findtext("source") or ""))
        texts = [f.text or "" for f in tr.iter("numerusform")] or [tr.text or ""]
        for t in texts:
            if set(re.findall(r"(?<!\{)\{(\w+)\}(?!\})", t)) != src:
                bad.append(f"{ctx}: {msg.findtext('source')!r} → {t!r}")
    assert not bad, "\n".join(bad)


# --------------------------------------------------------------------------- 錯誤代碼錨點

def _anchors(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8")
    ids = set(re.findall(r'<a\s+(?:id|name)="([^"]+)"', text))
    # GitHub 自動產生的標題錨點：小寫、空白換成 -、去掉標點
    for title in re.findall(r"^#+\s+(.+)$", text, flags=re.MULTILINE):
        ids.add(re.sub(r"[^\w\- ]", "", title.strip().lower()).replace(" ", "-"))
    return ids


@pytest.mark.parametrize("guide", ["USER_GUIDE.md", "USER_GUIDE.en.md"])
def test_every_error_code_has_guide_anchor(guide):
    """直接從 engine_messages 取代碼（新增代碼時不用另外改清單；test_packaging_docs 是寫死的清單）。"""
    import engine_messages
    faqs = {engine_messages._ERRORS[c]["faq"] for c in engine_messages.ERROR_CODES}
    assert faqs
    missing = sorted(faqs - _anchors(ROOT / guide))
    assert not missing, f"{guide} 缺少錨點：{missing}"
