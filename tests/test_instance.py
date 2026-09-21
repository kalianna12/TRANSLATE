def test_second_launch_notifies_first_without_creating_server(monkeypatch):
    from PySide6.QtWidgets import QApplication
    from screenlingo import instance
    app = QApplication.instance() or QApplication([])
    class Lock:
        def __init__(self, path):
            pass
        def setStaleLockTime(self, value):
            pass
        def tryLock(self, delay):
            return False
    writes = []
    class Socket:
        def connectToServer(self, name):
            assert name.startswith("ScreenLingo-")
        def waitForConnected(self, timeout):
            return True
        def write(self, value):
            writes.append(value)
        def waitForBytesWritten(self, timeout):
            return True
        def disconnectFromServer(self):
            pass
    monkeypatch.setattr(instance, "QLockFile", Lock)
    monkeypatch.setattr(instance, "QLocalSocket", Socket)
    assert instance.acquire(app) is None
    assert writes == [b"preferences"]
