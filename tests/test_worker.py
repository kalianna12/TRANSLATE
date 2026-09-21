import numpy as np

from screenlingo.core import Region
import screenlingo.ocr as ocr_module
import screenlingo.worker as worker_module


def test_slow_translation_is_discarded_when_chat_has_changed(monkeypatch):
    class Capture:
        def __init__(self, region):
            self.values = iter([0, 255, 255, 255])

        def grab(self, cancelled):
            return np.full((50, 100, 3), next(self.values), dtype=np.uint8)

        def close(self):
            pass

    class OCR:
        last_metrics = {}

        def __call__(self, bgr, cancelled, source="auto"):
            text = "old" if bgr[0, 0, 0] == 0 else "new"
            return [([[5, 5], [80, 5], [80, 25], [5, 25]], text, 0.99)]

    class Translator:
        cache_hits = 0
        network_calls = 0

        def __init__(self, **kwargs):
            pass

        def translate(self, texts, cancelled):
            return ["translated " + text for text in texts]

        def close(self):
            pass

    monkeypatch.setattr(worker_module, "ScreenCapture", Capture)
    monkeypatch.setattr(worker_module, "get_translator", lambda options: Translator())
    monkeypatch.setattr(ocr_module, "get_ocr", lambda *args: OCR())
    worker = worker_module.TranslationWorker(1, Region(0, 0, 100, 50), {
        "target": "zh-CN", "provider": "free", "api_key": "", "proxy": "",
        "interval": 250, "realtime": True})
    completed = []

    def receive(token, blocks):
        if blocks and blocks[0].translated:
            completed.append(blocks[0].translated)
            worker.stop()

    worker.result.connect(receive)
    worker.run()
    assert completed == ["translated new"]
