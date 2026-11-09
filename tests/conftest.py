"""pytest 共用設定。"""
import os
import sys

import pytest

# macOS 的 offscreen 平台不會自己找系統字型：沒指定時用 Qt 的替代字型，字高和版面寬度都和真正的 App 不同
# （CI 上開關尺寸、最小視窗寬度的測試因此失敗）。要在任何測試模組建立 QApplication 之前設定。
if sys.platform == "darwin":
    os.environ.setdefault("QT_QPA_FONTDIR", "/System/Library/Fonts")

_status = {"code": 0}


@pytest.fixture(autouse=True)
def _source_language_by_default(request, monkeypatch):
    """介面語言預設用原文（中文）：語言設定是「跟隨系統」，在英文系統（例如 CI）上會變成英文，
    依賴中文文字的測試就會失敗。測試裡呼叫 i18n.install() 時照樣換成指定的語言。
    test_i18n.py 本身要測「跟隨系統」的判斷，不套用。"""
    if request.node.path.name == "test_i18n.py" or "i18n" not in sys.modules:
        yield
        return
    import i18n
    if i18n._current is None:
        monkeypatch.setattr(i18n, "_current", i18n.SOURCE_LANGUAGE)
    yield


def pytest_sessionfinish(session, exitstatus):
    _status["code"] = int(exitstatus)


def pytest_unconfigure(config):
    """測試都跑完、結果也印完之後：照 App 的 shutdown() 流程釋放 Qt，再用測試的結束碼結束程序。

    測試建立了很多 Qt 物件（視窗、網路元件）。留給 Python 結束時隨機順序回收，macOS 偶爾會在
    QApplication 之後才刪到某些物件而當掉（"shared QObject was deleted directly"）；
    Qt 物件還活著就直接 os._exit，Windows 卸載 Qt DLL 時又會存取違規。所以先依序刪掉再結束。
    """
    if "PySide6.QtCore" not in sys.modules:
        return
    import shiboken6
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is not None:
        for w in QApplication.topLevelWidgets():
            if shiboken6.isValid(w):
                shiboken6.delete(w)
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        shiboken6.delete(app)
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(_status["code"])
