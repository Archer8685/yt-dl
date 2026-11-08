"""pytest 共用設定。"""
import os
import sys

_status = {"code": 0}


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
