def test_provider_credentials_are_separate(tmp_path, monkeypatch):
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication
    from screenlingo.ui import MainWindow
    from screenlingo import windows_settings
    app = QApplication.instance() or QApplication([])
    app.setOrganizationName("ScreenLingoUnitTests")
    app.setApplicationName("Preferences")
    monkeypatch.setattr(windows_settings, "startup_enabled", lambda: False)
    window = MainWindow()
    window.settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(window.hotkeys, "configure", lambda bindings: None)
    try:
        window.provider.setCurrentIndex(window.provider.findData("baidu"))
        window.app_id.setText("test-app")
        window.api_key.setText("test-secret")
        window.remember_key.setChecked(True)
        window.save_settings()
        assert "test-secret" not in (tmp_path / "settings.ini").read_text()
        window.provider.setCurrentIndex(window.provider.findData("youdao"))
        assert not window.api_key.text()
        assert not window.app_id.text()
        window.provider.setCurrentIndex(window.provider.findData("baidu"))
        assert window.api_key.text() == "test-secret"
        assert window.app_id.text() == "test-app"
        window.remember_key.setChecked(False)
        window.save_settings()
        window.load_credentials()
        assert not window.api_key.text()
    finally:
        window.quit_app()
