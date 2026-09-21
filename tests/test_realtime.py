from screenlingo.core import TextBlock, Translator
from screenlingo.languages import script_of
from screenlingo.ocr import choose_reading
from screenlingo.worker import same_text, text_signature
from test_core import Session, free_response
import numpy as np
from screenlingo.ocr import crop_key


def test_mixed_source_languages_are_sent_as_separate_batches():
    session = Session([free_response("你好"), free_response("谢谢"), free_response("请等待")])
    translator = Translator(session=session)
    texts = ["Hello", "ありがとう", "기다려 주세요"]
    assert translator.translate(texts) == ["你好", "谢谢", "请等待"]
    assert len(session.calls) == 3
    assert [call[1]["params"]["q"] for call in session.calls] == texts
    translator.close()


def test_confidence_arbitration_requires_hangul():
    assert choose_reading(("助けてください", 0.94), ("123", 0.99))[0] == "助けてください"
    assert choose_reading(("wrong", 0.6), ("도와주세요", 0.99))[0] == "도와주세요"
    assert choose_reading(("Hello", 0.98), ("가", 0.70))[0] == "Hello"


def test_script_detection_does_not_claim_han_only_is_japanese():
    assert script_of("敵がいます") == "ja"
    assert script_of("적이 있어요") == "ko"
    assert script_of("Enemy at B!") == "en"
    assert script_of("待機中") == "CJK"


def test_animated_background_preserves_same_chat_but_scroll_invalidates_it():
    first = [TextBlock(10, 20, 100, 24, "Hello")]
    small_jitter = [TextBlock(12, 21, 102, 24, "Hello")]
    scrolled = [TextBlock(10, 70, 100, 24, "Hello")]
    changed = [TextBlock(10, 20, 100, 24, "Goodbye")]
    assert same_text(text_signature(first), text_signature(small_jitter))
    assert not same_text(text_signature(first), text_signature(scrolled))
    assert not same_text(text_signature(first), text_signature(changed))
    assert not same_text(text_signature(first), [])


def test_line_fingerprint_ignores_background_brightness_but_not_changed_glyphs():
    first = np.full((24, 100, 3), 20, dtype=np.uint8)
    first[5:18, 20:26] = 240
    brighter = np.full_like(first, 40)
    brighter[5:18, 20:26] = 240
    changed = brighter.copy()
    changed[5:18, 35:41] = 240
    assert crop_key(first) == crop_key(brighter)
    assert crop_key(first) != crop_key(changed)
