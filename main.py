"""ScreenLingo desktop entry point."""
import sys

from PySide6.QtWidgets import QApplication

from screenlingo.ui import MainWindow


def main():
    if "--self-test" in sys.argv:
        from screenlingo.release_check import run
        run(sys.argv[sys.argv.index("--self-test") + 1])
        return
    app = QApplication(sys.argv)
    app.setApplicationName("ScreenLingo")
    app.setOrganizationName("ScreenLingo")
    app.setQuitOnLastWindowClosed(False)
    from screenlingo.instance import acquire
    server = acquire(app)
    if server is None:
        return
    window = MainWindow()
    def reopen():
        connection = server.nextPendingConnection()
        if connection:
            connection.close()
            connection.deleteLater()
        window.restore()
    server.newConnection.connect(reopen)
    window.tray_only = True
    from screenlingo.warmup import Preparation
    window.preparation = Preparation(window.options(), window)
    window.preparation.ready.connect(lambda message: window.status.setText(message)
                                     if not window.translation_active and not window.initialization_error else None)
    window.preparation.finished.connect(lambda: window.close() if window.closing else None)
    window.preparation.start()
    if "--preferences" in sys.argv or (window.provider.currentData() in ("baidu", "youdao", "cloud") and not window.options()["api_key"]):
        window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
