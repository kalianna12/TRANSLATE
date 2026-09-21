from screenlingo import windows_settings as ws


def test_dpapi_roundtrip():
    secret = "test-only-日本語"
    encrypted = ws.protect(secret)
    assert secret not in encrypted
    assert ws.unprotect(encrypted) == secret


def test_startup_registry_roundtrip(monkeypatch):
    # Separate value: never modify the user's real startup preference.
    monkeypatch.setattr(ws, "RUN_NAME", "ScreenLingo-Isolated-Test")
    try:
        ws.set_startup(True)
        assert ws.startup_enabled()
        ws.set_startup(False)
        assert not ws.startup_enabled()
    finally:
        ws.set_startup(False)
