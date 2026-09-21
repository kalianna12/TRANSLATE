from collections import OrderedDict
import threading
import numpy as np
import pytest
from screenlingo.ocr import MultilingualOCR, merge_vertical_boxes
import screenlingo.runtime as runtime


@pytest.mark.parametrize("source,counts", [("auto", [1, 1]), ("ja", [1, 0]), ("en", [1, 0]), ("ko", [0, 1])])
def test_fixed_language_uses_only_selected_recognizer_and_separate_crop_cache(source, counts):
    calls = [0, 0]
    class Engine:
        def text_det(self, image):
            return np.array([[[0, 0], [80, 0], [80, 20], [0, 20]]], dtype=np.float32), 0
        def get_crop_img_list(self, image, boxes):
            return [image]
        def text_rec(self, crops):
            calls[0] += 1
            return [("こんにちは", .95)], 0
    def korean(crops):
        calls[1] += 1
        return [("안녕하세요", .99)], 0
    engine = MultilingualOCR.__new__(MultilingualOCR)
    engine.engine, engine.korean = Engine(), korean
    engine.cache, engine.lock = OrderedDict(), threading.RLock()
    image = np.full((20, 80, 3), 255, dtype=np.uint8)
    result = engine(image, source=source)
    assert calls == counts
    assert result[0][1] == ("안녕하세요" if source in ("auto", "ko") else "こんにちは")
    engine(image, source=source)
    assert calls == counts
    engine(image, source="ko" if source != "ko" else "ja")
    assert sum(calls) == sum(counts) + 1


def test_vertical_detector_fragments_join_in_column_order():
    def box(x, y, w, h):
        return [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]
    merged = merge_vertical_boxes([box(20, 5, 15, 100), box(55, 5, 15, 55), box(55, 64, 15, 35)])
    assert len(merged) == 2
    assert merged[0][:, 0].min() == 55
    assert merged[0][:, 1].max() == 99


def test_auto_recognizers_overlap_and_keep_confidence_selection():
    started = threading.Event()
    release = threading.Event()
    class Engine:
        def text_det(self, image):
            return np.array([[[0, 0], [80, 0], [80, 20], [0, 20]]], dtype=np.float32), 0
        def get_crop_img_list(self, image, boxes):
            return [image]
        def text_rec(self, crops):
            assert started.wait(2), "Korean inference must already be running"
            release.set()
            return [("こんにちは", .95)], 0
    def korean(crops):
        started.set()
        assert release.wait(2), "Multilingual inference must overlap"
        return [("안녕하세요", .99)], 0
    engine = MultilingualOCR.__new__(MultilingualOCR)
    engine.engine, engine.korean = Engine(), korean
    engine.cache, engine.lock = OrderedDict(), threading.RLock()
    engine.parallel_auto = True
    result = engine(np.full((20, 80, 3), 255, dtype=np.uint8))
    assert result[0][1] == "안녕하세요"


def test_shared_translator_reused_and_warmup_cannot_revert_user_language(monkeypatch):
    class Translator:
        def __init__(self, **options):
            self.options, self.closed, self.warmed = options, False, False
        def close(self):
            self.closed = True
        def warm_connection(self):
            self.warmed = True
    runtime.close_runtime()
    monkeypatch.setattr(runtime, "Translator", Translator)
    auto = {"target": "zh-CN", "source": "auto", "provider": "free"}
    first = runtime.get_translator(auto)
    assert first is runtime.get_translator(auto)
    fixed = {**auto, "source": "ko"}
    second = runtime.get_translator(fixed)
    assert first.closed and second is not first
    runtime.warm_translator(auto)
    assert runtime.get_translator(fixed) is second
    assert not second.closed
    runtime.close_runtime()
