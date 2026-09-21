import pytest
import numpy as np
from screenlingo import glm_optional as glm


class Session:
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass
    def get(self, url, **kwargs):
        assert url == "http://127.0.0.1:11434/api/tags"
        class Response:
            def raise_for_status(self):
                pass
            def json(self):
                return {"models": []}
        return Response()
    def post(self, *args, **kwargs):
        pytest.fail("Checking availability must never download or run inference")


def test_check_only_never_downloads(monkeypatch):
    monkeypatch.setattr(glm, "local_session", Session)
    task = glm.ModelTask(download=False)
    ready = []
    task.ready.connect(ready.append)
    task.run()
    assert ready == [False]


def test_glm_cancelled_before_crop_sends_nothing(monkeypatch):
    monkeypatch.setattr(glm, "local_session", Session)
    recognizer = glm.OllamaRecognizer()
    recognizer.cancelled = lambda: True
    assert recognizer([np.zeros((30, 100, 3), np.uint8)]) == ([], 0)


@pytest.mark.parametrize("reason,success", [("stop", True), ("length", False)])
def test_glm_stream_requires_complete_output(monkeypatch, reason, success):
    import json
    class Stream(Session):
        def post(self, url, **kwargs):
            assert url == "http://127.0.0.1:11434/api/generate"
            assert kwargs["json"]["stream"] is True
            class Response(Session):
                def raise_for_status(self):
                    pass
                def iter_lines(self):
                    yield json.dumps({"response": "hello", "done": False}).encode()
                    yield json.dumps({"done": True, "done_reason": reason}).encode()
            return Response()
    monkeypatch.setattr(glm, "local_session", Stream)
    recognizer = glm.OllamaRecognizer()
    if success:
        assert recognizer([np.zeros((30, 100, 3), np.uint8)])[0] == [("hello", 1.0)]
    else:
        with pytest.raises(RuntimeError, match="incomplete"):
            recognizer([np.zeros((30, 100, 3), np.uint8)])
