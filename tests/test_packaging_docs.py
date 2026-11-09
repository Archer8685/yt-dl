"""打包設定（build_app.py）與使用者文件：安裝精靈、ytdl:// 註冊、翻譯檔、授權檔、FAQ 錨點。"""
import functools
import re
from pathlib import Path

import pytest

import build_app

ROOT = Path(__file__).resolve().parent.parent
GUIDE = (ROOT / "USER_GUIDE.md").read_text(encoding="utf-8")

# ROADMAP 附錄 A：engine_messages.py 的錯誤代碼會連到這些錨點，名稱不能改
ERROR_ANCHORS = [
    "err-invalid-url", "err-unsupported-url", "err-video-unavailable", "err-private-video",
    "err-age-restricted", "err-members-only", "err-geo-blocked", "err-bot-check", "err-live-not-started",
    "err-http-403", "err-rate-limited", "err-format-unavailable", "err-ffmpeg-failed", "err-ffmpeg-missing",
    "err-network", "err-proxy", "err-cookie-browser", "err-cookies-invalid", "err-disk-full",
    "err-download-dir", "err-engine", "err-unknown",
]
PAGE_ANCHORS = ["install-windows", "install-macos", "tray", "bookmarklet", "uninstall", "faq"]


def inno_script(**overrides) -> str:
    args = {"display": build_app.DISPLAY, "name": build_app.NAME, "version": "9.9.9", "dist": "D", "icon": "I",
            "lang": "ChineseTraditional.isl", "src": "S", "license": "LIC", "scheme": build_app.URL_SCHEME,
            "root": "R"}
    return build_app.INNO_SCRIPT.format(**{**args, **overrides})


def spec_text(datas=()) -> str:
    return build_app.SPEC.format(
        drop=["*/opengl32sw.dll"], keep_imageformats=["qjpeg"], keep_platforms=["qwindows"],
        keep_translations=build_app.KEEP_TRANSLATIONS, tools_dir="c:/tools/", entry="e.py", root="r",
        datas=list(datas), binaries=[], excludes=[], name=build_app.NAME, icon="i", bundle_id=build_app.BUNDLE_ID,
        display=build_app.DISPLAY, version="9.9.9", local_net="L", scheme=build_app.URL_SCHEME)


@functools.cache
def spec_keep():
    """取出 spec 裡的 keep() 過濾函式（spec 後半段要在 PyInstaller 裡才能執行）。"""
    text = spec_text()
    ns: dict = {}
    exec(text[:text.index("# macOS 的毛玻璃")], ns)  # noqa: S102 — 我們自己產生的 spec 文字
    return ns["keep"]


# ---- Windows 安裝精靈 ----

def test_installer_has_english_and_chinese_picked_automatically():
    s = inno_script()
    langs = s[s.index("[Languages]"):s.index("[CustomMessages]")]
    assert 'Name: "en"; MessagesFile: "compiler:Default.isl"' in langs
    assert 'Name: "zh"; MessagesFile: "ChineseTraditional.isl"' in langs
    assert langs.index('"en"') < langs.index('"zh"')  # 不是中文的系統退回第一個（English）
    assert "ShowLanguageDialog=no" in s


def test_installer_registers_ytdl_protocol_and_removes_it_on_uninstall():
    s = inno_script()
    reg = [line for line in s.splitlines() if line.startswith("Root:")]
    assert reg and all('Subkey: "Software\\Classes\\ytdl' in line for line in reg)
    assert all(line.startswith("Root: HKA;") for line in reg)  # 只裝給自己時是 HKCU
    assert any('ValueName: "URL Protocol"' in line for line in reg)
    root_key = next(line for line in reg if 'Subkey: "Software\\Classes\\ytdl";' in line)
    assert root_key.endswith("Flags: uninsdeletekey")
    command = next(line for line in reg if r"\shell\open\command" in line)
    assert command.endswith('ValueData: """{app}\\{#AppExe}"" ""%1"""')  # 網址當成一個參數傳給 App


def test_uninstaller_asks_before_deleting_settings_and_cookies():
    s = inno_script()
    code = s[s.index("[Code]"):]
    assert "CurUninstallStepChanged" in code and "usPostUninstall" in code
    assert "not UninstallSilent" in code  # 靜默解除安裝不跳視窗、不刪資料
    assert "MB_DEFBUTTON2" in code  # 預設選「否」
    assert r"DelTree(ExpandConstant('{localappdata}\YT-Downloader')" in code
    assert r"RegDeleteKeyIncludingSubkeys(HKCU, 'Software\YTDownloader')" in code
    messages = s[s.index("[CustomMessages]"):s.index("[Registry]")]
    assert "en.DeleteUserData=" in messages and "zh.DeleteUserData=" in messages
    assert "下載的影片不會被刪除" in messages and "NOT deleted" in messages


def test_installer_paths_match_engine_and_settings():
    """解除安裝刪的資料夾、機碼要和引擎、介面實際用的一樣。"""
    import server
    assert server.APP_NAME == build_app.NAME
    # QSettings("YTDownloader", …)：拆檔後可能在 native_common.py，所以掃所有介面檔
    sources = "\n".join(p.read_text(encoding="utf-8") for p in ROOT.glob("native_*.py"))
    assert re.search(r'^SETTINGS_ORG\b.*=\s*"YTDownloader"', sources, re.MULTILINE)


def test_installer_puts_license_files_in_app_folder():
    s = inno_script(root=r"C:\src")
    assert r'Source: "C:\src\LICENSE"; DestDir: "{app}"; DestName: "LICENSE.txt"' in s
    assert r'Source: "C:\src\THIRD_PARTY_NOTICES.md"; DestDir: "{app}"' in s


def test_inno_template_has_no_unfilled_fields():
    """format() 之後不能殘留沒替換的 Python 欄位（例如少寫一個參數）。"""
    s = inno_script()
    assert not re.search(r"\{(display|name|version|dist|icon|lang|src|license|scheme|root)\}", s)


# ---- PyInstaller spec ----

def test_spec_compiles_and_registers_url_scheme_on_macos():
    text = spec_text(datas=build_app.doc_datas())
    compile(text, "spec", "exec")
    assert '"CFBundleURLSchemes": [\'ytdl\']' in text
    assert f"\"CFBundleURLName\": '{build_app.BUNDLE_ID}'" in text


@pytest.mark.parametrize("path, kept", [
    ("PySide6/translations/qtbase_zh_TW.qm", True),
    ("PySide6/translations/qtbase_en.qm", True),
    ("PySide6/translations/qt_zh_TW.qm", True),
    ("PySide6/translations/qt_en.qm", True),
    ("PySide6/translations/qtbase_ja.qm", False),
    ("PySide6/translations/qtdeclarative_zh_TW.qm", False),
    ("PySide6/translations/qtwebengine_en.qm", False),
    ("i18n/yt_dl_en.qm", True),  # App 自己的翻譯檔不能被 Qt 的過濾規則刪掉
    ("LICENSE", True),
    ("THIRD_PARTY_NOTICES.md", True),
])
def test_spec_keeps_only_supported_translations(path, kept):
    assert spec_keep()(path, "c:/site-packages/" + path) is kept


def test_translation_datas_skip_missing_qm(tmp_path, monkeypatch):
    monkeypatch.setattr(build_app, "ROOT", tmp_path)
    assert build_app.translation_datas() == []  # 沒有 i18n 資料夾
    (tmp_path / "i18n").mkdir()
    (tmp_path / "i18n" / "yt_dl_en.ts").write_text("<TS/>", encoding="utf-8")
    assert build_app.translation_datas() == []  # 只有原始檔、還沒編譯
    (tmp_path / "i18n" / "yt_dl_en.qm").write_bytes(b"qm")
    assert build_app.translation_datas() == [(str(tmp_path / "i18n" / "yt_dl_en.qm"), "i18n")]


def test_license_files_are_bundled():
    datas = build_app.doc_datas()
    assert [Path(src).name for src, _ in datas] == ["LICENSE", "THIRD_PARTY_NOTICES.md"]
    assert all(Path(src).is_file() and dest == "." for src, dest in datas)


# ---- 授權 ----

def test_license_is_mit():
    text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert text.startswith("MIT License") and "Copyright (c) 2026 Archer8685" in text


def test_third_party_notices_cover_bundled_components():
    text = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    for name in ("yt-dlp", "FFmpeg", "Deno", "PySide6", "Qt", "Flask", "Mutagen"):
        assert name in text, name
    assert "GPL" in text and "gpl-3.0" in text and "原始碼" in text  # GPL 組建的 FFmpeg 要附授權全文與原始碼取得方式
    assert "gpl-shared" in build_app.FFMPEG_WIN  # 打包的確實是 GPL 組建；換成 LGPL 組建時要改說明


# ---- 使用說明 ----

@pytest.mark.parametrize("anchor", ERROR_ANCHORS + PAGE_ANCHORS)
def test_guide_has_fixed_anchor(anchor):
    assert GUIDE.count(f'<a id="{anchor}"></a>') == 1


def _slug(heading: str) -> str:
    s = re.sub(r"[^\w\- ]", "", heading.strip().lower())
    return s.replace(" ", "-")


def test_guide_internal_links_resolve():
    ids = set(re.findall(r'<a id="([^"]+)"></a>', GUIDE))
    ids |= {_slug(h) for h in re.findall(r"^#{1,6} (.+)$", GUIDE, re.MULTILINE)}
    links = re.findall(r"\]\(#([^)]+)\)", GUIDE)
    assert links
    assert not [link for link in links if link not in ids]


def test_guide_relative_file_links_exist():
    for target in re.findall(r"\]\(((?!https?:|#)[^)#]+)", GUIDE):
        assert (ROOT / target).is_file(), target


def test_guide_bookmarklet_uses_shared_ytdl_format():
    assert "javascript:location.href='ytdl://add?url='+encodeURIComponent(location.href)" in GUIDE
    assert "不會自動開始下載" in GUIDE


def test_guide_does_not_promise_signing_or_suggest_proxy_for_geo_block():
    assert "簽章計畫" not in GUIDE and "未來會簽章" not in GUIDE
    geo = GUIDE[GUIDE.index('<a id="err-geo-blocked">'):GUIDE.index('<a id="err-bot-check">')]
    assert "Proxy" not in geo and "VPN" not in geo and "代理" not in geo


def test_guide_unblock_steps_and_intel_notice():
    win = GUIDE[GUIDE.index('<a id="install-windows">'):GUIDE.index('<a id="install-macos">')]
    for step in ("保留", "其他資訊", "仍要執行", "還原", "排除項目", "SHA256SUMS.txt"):
        assert step in win, step
    mac = GUIDE[GUIDE.index('<a id="install-macos">'):GUIDE.index("### 更新 App")]
    for step in ("先雙擊開啟一次", "隱私權與安全性", "仍要打開", "已損毀", "xattr", "macOS 15", "macOS 14"):
        assert step in mac, step
    assert "Intel Mac 不支援" in GUIDE


# ---- 網頁版、README、issue 範本 ----

def test_web_page_links_guide_and_issues():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    footer = html[html.index("<footer>"):html.index("</footer>")]
    assert "USER_GUIDE.md" in footer and "issues/new/choose" in footer
    assert "USER_GUIDE.md#install-windows" in html and "USER_GUIDE.md#install-macos" in html
    assert "Intel Mac 不支援" in html


def test_readme_starts_with_downloads():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert readme.index("## 下載") < readme.index("## 專案架構")
    assert "releases/latest/download/YT-Downloader-Setup-Windows.exe" in readme
    assert "releases/latest/download/YT-Downloader-macOS-AppleSilicon.dmg" in readme
    assert "未附開源授權" not in readme and "(LICENSE)" in readme


def test_issue_templates_are_valid():
    yaml = pytest.importorskip("yaml")
    folder = ROOT / ".github" / "ISSUE_TEMPLATE"
    bug = yaml.safe_load((folder / "bug_report.yml").read_text(encoding="utf-8"))
    ids = {item.get("id") for item in bug["body"]}
    assert {"app_version", "language", "os", "url", "error", "log", "checks"} <= ids
    checks = next(item for item in bug["body"] if item.get("id") == "checks")
    labels = " ".join(o["label"] for o in checks["attributes"]["options"])
    assert "FAQ" in labels and "cookies.txt" in labels
    assert yaml.safe_load((folder / "feature_request.yml").read_text(encoding="utf-8"))["body"]
    config = yaml.safe_load((folder / "config.yml").read_text(encoding="utf-8"))
    assert config["blank_issues_enabled"] is False
    assert any("USER_GUIDE.md#faq" in link["url"] for link in config["contact_links"])
