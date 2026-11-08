"""tools/release_notes.py：每次 Release 都要有 CHANGELOG.md 裡的更新說明。"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import release_notes as rn

SAMPLE = """# 更新紀錄

## 未發布
- 還沒發布的功能

## 1.2.0 — 2026-12-01
### 新功能
- 新功能 A

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


def test_notes_have_changes_then_install_guide():
    notes = rn.release_notes("1.2.0", SAMPLE)
    assert notes.startswith("## 更新內容\n\n### 新功能\n- 新功能 A")
    assert notes.index("新功能 A") < notes.index("## 下載與安裝")
    assert "YT-Downloader-Setup-Windows.exe" in notes and "YT-Downloader-macOS-AppleSilicon.dmg" in notes


def test_current_version_has_release_notes():
    """改 VERSION 發布前，CHANGELOG.md 一定要先寫好這一版的說明（否則發布流程會停下來）。"""
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert rn.changelog_section(version, (ROOT / "CHANGELOG.md").read_text(encoding="utf-8"))
