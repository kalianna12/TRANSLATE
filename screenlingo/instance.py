"""One tray process per Windows account; repeat launch opens preferences."""
import hashlib
import os
from PySide6.QtCore import QLockFile, QStandardPaths
from PySide6.QtNetwork import QLocalServer, QLocalSocket


def acquire(app):
    folder = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation)
    os.makedirs(folder, exist_ok=True)
    name = "ScreenLingo-" + hashlib.sha256(folder.encode()).hexdigest()[:16]
    lock = QLockFile(os.path.join(folder, "tray.lock"))
    lock.setStaleLockTime(0)
    if not lock.tryLock(0):
        socket = QLocalSocket()
        socket.connectToServer(name)
        if socket.waitForConnected(1500):
            socket.write(b"preferences")
            socket.waitForBytesWritten(1000)
            socket.disconnectFromServer()
        return None
    QLocalServer.removeServer(name)
    server = QLocalServer(app)
    if not server.listen(name):
        lock.unlock()
        return None
    app.instance_lock, app.instance_server = lock, server
    return server
