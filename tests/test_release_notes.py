"""tools/release_notes.py：每次 Release 都要有 CHANGELOG.md 裡的更新說明，且先告訴使用者該下載哪個檔。"""
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import release_notes as rn

SAMPLE = """# 更新紀錄

<!--
維護說明：標題格式是 `## 版本號 — 日期`。
## 9.9.9 — 註解裡的範例標題不能被當成真的段落
-->

## 未發布
- 還沒發布的功能

## 1.2.0 — 2026-12-01
### 新功能
- 新功能 A
<!-- 段落裡的註解也不能出現在 Release 說明 -->

## 1.1.0 — 2026-11-08
- 功能 B
"""


def test_section_is_extracted_between_headings():
    assert rn.changelog_section("1.2.0", SAMPLE) == "### 新功能\n- 新功能 A"
    assert rn.changelog_section("1.1.0", SAMPLE) == "- 功能 B"


def test_unreleased_and_missing_versions_have_no_section():
    assert rn.changelog_section("1.3.0", SAMPLE) is None
    assert rn.changelog_section("1.2", SAMPLE) is None  # 不能把 1.2.0 當成 1.2
    with pytest.raises(ValueError, match="1.3.0"):
        rn.release_notes("1.3.0", SAMPLE)


def test_html_comments_are_not_sections_or_content():
    assert rn.changelog_section("9.9.9", SAMPLE) is None
    notes = rn.release_notes("1.2.0", SAMPLE)
    assert "<!--" not in notes and "維護說明" not in notes


def test_download_table_comes_first():
    notes = rn.release_notes("1.2.0", SAMPLE)
    assert notes.startswith("## 該下載哪個檔\n")
    table = notes[:notes.index("## 更新內容")]
    for name in ("YT-Downloader-Setup-Windows.exe", "YT-Downloader-macOS-AppleSilicon.dmg"):
        assert f"https://github.com/Archer8685/yt-dl/releases/download/v1.2.0/{name}" in table
    assert "Intel Mac 不支援" in table
    assert "Source code" in table  # 提醒不要下載 GitHub 自動附的原始碼
    assert "USER_GUIDE.md#install-windows" in table


def test_download_table_shows_real_sizes(tmp_path):
    (tmp_path / "YT-Downloader-Setup-Windows.exe").write_bytes(b"x" * (3 * 1024 ** 2))
    notes = rn.release_notes("1.2.0", SAMPLE, rn.asset_sizes(tmp_path))
    rows = {line.split("|")[1].strip(): line for line in notes.splitlines() if line.startswith("| ")}
    assert "| 3 MB |" in rows["Windows 10／11"]
    assert "| — |" in rows["macOS（Apple 晶片）"]  # 沒有檔案時不亂寫大小


def test_notes_order():
    notes = rn.release_notes("1.2.0", SAMPLE)
    order = ["## 該下載哪個檔", "## 更新內容", "新功能 A", "## 下載與安裝", "## 檢查檔案是否完整", "## 免責聲明"]
    positions = [notes.index(h) for h in order]
    assert positions == sorted(positions)


def test_install_guide_has_unblock_steps_and_links():
    notes = rn.release_notes("1.2.0", SAMPLE)
    install = notes[notes.index("## 下載與安裝"):notes.index("## 檢查檔案是否完整")]
    assert "https://github.com/Archer8685/yt-dl/blob/main/USER_GUIDE.md" in install
    for step in ("保留", "其他資訊", "仍要執行", "隱私權與安全性", "仍要打開", "已損毀", "xattr", "Intel Mac 不支援"):
        assert step in install, step
    assert "簽章計畫" not in notes and "未來會簽章" not in notes  # 已決定不做簽章，不再提計畫
    assert (ROOT / "USER_GUIDE.md").is_file()  # 連結指向的檔案要真的存在


def test_guide_anchors_used_in_notes_exist():
    """Release 說明連到 USER_GUIDE.md 的錨點，使用說明裡一定要有。"""
    notes = rn.release_notes("1.2.0", SAMPLE)
    guide = (ROOT / "USER_GUIDE.md").read_text(encoding="utf-8")
    anchors = set(re.findall(r"USER_GUIDE\.md#([\w-]+)", notes))
    assert anchors >= {"install-windows", "install-macos"}
    for anchor in anchors:
        assert f'<a id="{anchor}"></a>' in guide, anchor


def test_checksum_instructions():
    notes = rn.release_notes("1.2.0", SAMPLE)
    part = notes[notes.index("## 檢查檔案是否完整"):notes.index("## 免責聲明")]
    assert "SHA256SUMS.txt" in part
    assert "Get-FileHash" in part and "shasum -a 256" in part


def test_notes_end_with_disclaimer_link():
    notes = rn.release_notes("1.2.0", SAMPLE)
    tail = notes[notes.index("## 免責聲明"):]
    assert "https://github.com/Archer8685/yt-dl/blob/main/DISCLAIMER.md" in tail
    assert "有權" in tail and "YouTube" in tail
    assert (ROOT / "DISCLAIMER.md").is_file()  # 連結指向的檔案要真的存在


def test_changelog_maintainer_notes_are_hidden():
    """CHANGELOG.md 開頭給維護者的說明要包在 HTML 註解裡，一般使用者在 GitHub 上看不到。"""
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    head = text[:text.index("\n## ")]
    visible = rn.strip_comments(head)
    assert "<!--" in head and "發布" in head
    assert "發布" not in visible and "VERSION" not in visible


def test_current_version_has_release_notes():
    """改 VERSION 發布前，CHANGELOG.md 一定要先寫好這一版的說明（否則發布流程會停下來）。"""
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert rn.changelog_section(version, (ROOT / "CHANGELOG.md").read_text(encoding="utf-8"))


def test_cli_writes_notes_with_asset_sizes(tmp_path, monkeypatch, capsys):
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    (tmp_path / "YT-Downloader-macOS-AppleSilicon.dmg").write_bytes(b"x" * (2 * 1024 ** 2))
    monkeypatch.setattr(sys, "argv", ["release_notes.py", f"v{version}", "--assets", str(tmp_path)])
    rn.main()
    out = capsys.readouterr().out
    assert out.startswith("## 該下載哪個檔") and "| 2 MB |" in out
