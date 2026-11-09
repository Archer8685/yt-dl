"""抽出介面字串並編譯翻譯檔。

    python tools/i18n_update.py               # 抽字串到 i18n/yt_dl_en.ts，再編譯成 i18n/yt_dl_en.qm
    python tools/i18n_update.py --no-release  # 只抽字串（給 I2 補翻譯）
    python tools/i18n_update.py --release-only  # 只把 .ts 編譯成 .qm

抽字串用 PySide6 附的 lupdate，編譯用 lrelease。規範見 docs/I18N.md。
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
I18N_DIR = ROOT / "i18n"
SOURCE_LANGUAGE = "zh_TW"
TARGET_LANGUAGES = ("en",)
TS_PREFIX = "yt_dl"

# 引擎和建置腳本沒有介面字串（引擎文字由 engine_messages.py 依語言回傳），不抽。
EXCLUDE = {"server.py", "engine_messages.py", "build_app.py", "ytdlp_update.py"}

# 除了 QCoreApplication.translate／self.tr，也認得這個短名稱：_tr = QCoreApplication.translate
TR_FUNCTION_ALIAS = "translate+=_tr"


def ts_path(lang: str) -> Path:
    return I18N_DIR / f"{TS_PREFIX}_{lang}.ts"


def qm_path(ts: Path) -> Path:
    return ts.with_suffix(".qm")


def ui_sources(root: Path | None = None) -> list[Path]:
    """要抽字串的檔案：專案根目錄的 .py（排除引擎與建置腳本）。"""
    return sorted(p for p in (root or ROOT).glob("*.py") if p.name not in EXCLUDE)


def find_tool(name: str) -> str:
    """找 PySide6 附的 lupdate／lrelease。"""
    try:
        import PySide6
    except ImportError:  # pragma: no cover - 沒裝 PySide6 就不能跑
        PySide6 = None
    if PySide6 is not None:
        exe = Path(PySide6.__file__).resolve().parent / (name + (".exe" if os.name == "nt" else ""))
        if exe.is_file():
            return os.fspath(exe)
    for candidate in (f"pyside6-{name}", name):
        found = shutil.which(candidate)
        if found:
            return found
    raise FileNotFoundError(f"找不到 {name}，請先安裝 requirements-app.txt（PySide6）")


def _run(cmd: list[str]) -> None:
    print("> " + " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)


def run_lupdate(sources, ts: Path, target_language: str) -> None:
    """把 sources 的字串抽到 ts（已有的翻譯會保留，消失的字串會移除）。"""
    sources = [os.fspath(s) for s in sources]
    if not sources:
        raise ValueError("沒有要抽字串的檔案")
    ts.parent.mkdir(parents=True, exist_ok=True)
    _run([find_tool("lupdate"), "-no-obsolete", "-locations", "relative",
          "-tr-function-alias", TR_FUNCTION_ALIAS,
          "-source-language", SOURCE_LANGUAGE, "-target-language", target_language,
          *sources, "-ts", os.fspath(ts)])


def run_lrelease(ts: Path, qm: Path | None = None) -> Path:
    """把 ts 編譯成 qm（預設同資料夾、同檔名），回傳 qm 路徑。"""
    qm = qm or qm_path(ts)
    _run([find_tool("lrelease"), "-silent", os.fspath(ts), "-qm", os.fspath(qm)])
    return qm


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="抽出介面字串並編譯翻譯檔（docs/I18N.md）")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--no-release", action="store_true", help="只抽字串，不編譯 .qm")
    mode.add_argument("--release-only", action="store_true", help="只編譯 .qm，不抽字串")
    args = parser.parse_args(argv)
    try:
        for lang in TARGET_LANGUAGES:
            ts = ts_path(lang)
            if not args.release_only:
                run_lupdate(ui_sources(), ts, lang)
            if not args.no_release:
                if not ts.is_file():
                    print(f"找不到 {ts}，請先抽字串", file=sys.stderr)
                    return 1
                run_lrelease(ts)
    except (FileNotFoundError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as exc:
        print(f"指令失敗（結束碼 {exc.returncode}）", file=sys.stderr)
        return exc.returncode or 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
