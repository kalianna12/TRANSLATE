import pytest
import requests
from scripts.youdao_small_suite import LimitedSession
from screenlingo.core import TranslationError


def test_youdao_cap_persists_before_request_and_blocks_duplicates(tmp_path, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr("scripts.youdao_small_suite.time.time", lambda: clock[0])
    calls = []
    def request(self, method, url, **kwargs):
        calls.append(kwargs)
        raise requests.ConnectionError("fake network failure")
    monkeypatch.setattr(requests.Session, "request", request)
    path = tmp_path / "usage.db"
    for text in ("one", "two", "three"):
        with LimitedSession(path) as session:
            with pytest.raises(requests.ConnectionError):
                session.request("POST", "https://openapi.youdao.com/api", data={"q": text})
        clock[0] += 4
    with LimitedSession(path) as session:
        with pytest.raises(TranslationError):
            session.request("POST", "https://openapi.youdao.com/api", data={"q": "four"})
    assert len(calls) == 3
    assert all(c["allow_redirects"] is False for c in calls)
