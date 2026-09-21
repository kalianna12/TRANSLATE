import threading
import time
import numpy as np
import cv2
import pytest
import requests

from screenlingo.ocr import detect_document_lines
from screenlingo.core import TextBlock, Translator, TranslationError, group_vertical_paragraphs, Region
from screenlingo.document import translate_document
from screenlingo.worker import TranslationWorker, text_signature
from test_core import Session, free_response


def test_projection_keeps_small_text_on_wide_pages_at_original_resolution():
    image = np.full((600, 3000, 3), 255, dtype=np.uint8)
    for y in (50, 120, 190, 260, 330, 400):
        cv2.putText(image, "Long document text should retain small glyphs across a wide page.",
                    (25, y), cv2.FONT_HERSHEY_SIMPLEX, .65, (0, 0, 0), 1)
    boxes = detect_document_lines(image)
    assert boxes is not None and len(boxes) == 6
    assert boxes[0][:, 1].max() < boxes[1][:, 1].min()


def test_projection_rejects_portrait_manga_and_textured_background():
    assert detect_document_lines(np.full((1515, 1080, 3), 255, np.uint8)) is None
    noise = np.random.default_rng(1).integers(0, 255, (500, 1000, 3), dtype=np.uint8)
    assert detect_document_lines(noise) is None


def test_manga_groups_do_not_mix_panels_with_the_same_column_positions():
    blocks = [TextBlock(300, 20, 20, 100, "右上"), TextBlock(300, 220, 20, 100, "右下"),
              TextBlock(265, 20, 20, 100, "左上"), TextBlock(265, 220, 20, 100, "左下"),
              TextBlock(340, 20, 7, 50, "ふりがな"), TextBlock(20, 450, 200, 20, "Title")]
    sources = [b.source for b in group_vertical_paragraphs(blocks)]
    assert "右上左上" in sources and "右下左下" in sources
    assert "ふりがな" in sources and "Title" in sources


def readings(prefix="line", count=6):
    return [([[10, 10 + i * 24], [180, 10 + i * 24], [180, 28 + i * 24], [10, 28 + i * 24]],
             f"{prefix}{i}", .99) for i in range(count)]


class FakeTranslator:
    network_calls = 0
    cache_hits = 0
    def translate(self, texts, cancelled):
        return ["译文" + text for text in texts]


def worker():
    return TranslationWorker(1, Region(0, 0, 900, 180), {"source": "en", "realtime": True})


def test_first_partial_translation_arrives_before_ocr_finishes():
    first_shown = threading.Event()
    class OCR:
        last_metrics = {}
        def __call__(self, image, cancelled, source, on_chunk=None):
            on_chunk(readings(count=1))
            assert first_shown.wait(2), "Consumer waited for all OCR before showing the first translation"
            return readings()
    class Capture:
        def grab(self, cancelled):
            return np.zeros((180, 900, 3), dtype=np.uint8)
    active = worker()
    shown = []
    def receive(token, blocks):
        if blocks and all(b.translated for b in blocks):
            shown.append(len(blocks))
            first_shown.set()
    active.result.connect(receive)
    result = translate_document(active, Capture(), OCR(), FakeTranslator(), Capture().grab(None), None, time.monotonic())
    assert shown == [1, 6] and result is not None


def test_page_change_discards_partial_translation():
    class OCR:
        last_metrics = {}
        def __call__(self, image, cancelled, source, on_chunk=None):
            if on_chunk:
                on_chunk(readings(count=1))
                return readings()
            return readings("new")
    class Capture:
        def grab(self, cancelled):
            return np.full((180, 900, 3), 255, dtype=np.uint8)
    active = worker()
    shown = []
    active.result.connect(lambda token, blocks: shown.extend(b.translated for b in blocks if b.translated))
    result = translate_document(active, Capture(), OCR(), FakeTranslator(), np.zeros((180, 900, 3), np.uint8), None, time.monotonic())
    assert result is None and shown == []


def test_google_chunks_long_pages_without_losing_line_order(monkeypatch):
    translator = Translator(source="en")
    calls = []
    def request_chunk(texts, cancelled):
        calls.append(texts)
        return ["translated " + t for t in texts]
    monkeypatch.setattr(translator, "_free", request_chunk)
    texts = [f"Line {i}: " + "a" * 180 for i in range(16)]
    try:
        assert translator.translate(texts) == ["translated " + t for t in texts]
        assert len(calls) == 4 and all(len(group) == 4 for group in calls)
    finally:
        translator.close()


def test_successful_chunks_survive_a_later_failure(monkeypatch):
    translator = Translator(source="en")
    calls = []
    def request_chunk(texts, cancelled):
        calls.extend(texts)
        if texts[0] == "line4":
            time.sleep(.02)
            raise TranslationError("rate limited", retry_after=60)
        return ["ok " + t for t in texts]
    monkeypatch.setattr(translator, "_free", request_chunk)
    try:
        with pytest.raises(TranslationError):
            translator.translate([f"line{i}" for i in range(8)])
        assert translator.cache["line0"] == "ok line0"
        monkeypatch.setattr(translator, "_free", lambda texts, cancelled: ["ok " + t for t in texts])
        assert translator.translate([f"line{i}" for i in range(8)]) == [f"ok line{i}" for i in range(8)]
        assert translator.cache_hits == 4
    finally:
        translator.close()


def test_retry_after_is_shared_across_language_changes(monkeypatch):
    monkeypatch.setattr(Translator, "_cooldowns", {})
    response = requests.Response()
    response.status_code = 429
    response.headers["Retry-After"] = "120"
    first = Translator(session=Session([requests.HTTPError(response=response)]))
    second_session = Session([free_response("谢谢")])
    second = Translator(source="ko", session=second_session)
    try:
        with pytest.raises(TranslationError) as error:
            first.translate(["Hello"])
        assert error.value.retry_after == 120
        with pytest.raises(TranslationError) as error:
            second.translate(["감사합니다"])
        assert error.value.retry_after > 110 and not second_session.calls
    finally:
        first.close()
        second.close()
