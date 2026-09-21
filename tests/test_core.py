import numpy as np
import pytest
import requests

from screenlingo.core import Translator, TranslationError, frame_changed, make_blocks
from screenlingo.win32 import parse_hotkey


class Response:
    def __init__(self, data):
        self.data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self.data


class Session:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []
        self.proxies = {}

    def request(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        result = next(self.responses)
        if isinstance(result, Exception):
            raise result
        return Response(result)

    def close(self):
        pass


def free_response(text):
    return [[[text, "source", None, None]], None, "en"]


def test_small_changed_text_is_detected_on_large_screen():
    before = np.zeros((1080, 1920, 3), dtype=np.uint8)
    after = before.copy()
    after[500:520, 1000:1070] = 255
    assert frame_changed(before, after)
    assert not frame_changed(before, before)
    assert frame_changed(None, before)


def test_noise_is_ignored_and_shapes_change():
    before = np.zeros((100, 100, 3), dtype=np.uint8)
    after = before.copy()
    after[0, 0] = 255
    assert not frame_changed(before, after)
    assert frame_changed(before, after[:80])


def test_fast_frame_check_matches_reference_on_edge_tiles_and_thresholds():
    rng = np.random.default_rng(73)
    for height, width in [(1, 1), (63, 67), (65, 129), (180, 300)]:
        before = rng.integers(0, 250, (height, width, 3), dtype=np.uint8)
        after = before + rng.integers(0, 5, before.shape, dtype=np.uint8)
        delta = np.abs(before.astype(np.int16) - after.astype(np.int16)).mean(axis=2)
        for threshold in (0, 1.9, 2, 2.1, 5):
            expected = any(delta[y:y + 64, x:x + 64].mean() > threshold
                           for y in range(0, height, 64) for x in range(0, width, 64))
            assert frame_changed(before, after, threshold) == expected


def test_boxes_are_clamped_and_low_confidence_filtered():
    image = np.full((40, 100, 3), 240, dtype=np.uint8)
    points = [[-5, 2], [80, 2], [80, 22], [-5, 22]]
    blocks = make_blocks([(points, "Hello", 0.98), (points, "noise", 0.2)], image)
    assert len(blocks) == 1
    assert blocks[0].x == 0
    assert blocks[0].background == (240, 240, 240)
    assert blocks[0].width == 82


def test_translation_batches_deduplicates_and_caches():
    session = Session([free_response("你好\n世界")])
    translator = Translator(session=session)
    assert translator.translate(["Hello", "World", "Hello"]) == ["你好", "世界", "你好"]
    assert translator.translate(["World"]) == ["世界"]
    assert len(session.calls) == 1


def test_misaligned_batch_falls_back_to_separate_requests():
    session = Session([free_response("合并的句子"), free_response("你好"), free_response("世界")])
    translator = Translator(session=session)
    assert translator.translate(["Hello", "World"]) == ["你好", "世界"]
    assert len(session.calls) == 3


def test_cloud_payload_and_entity_decoding():
    session = Session([{"data": {"translations": [{"translatedText": "A &amp; B"}]}}])
    translator = Translator(provider="cloud", api_key="secret", session=session)
    assert translator.translate(["A and B"]) == ["A & B"]
    assert session.calls[0][1]["json"]["target"] == "zh-CN"


def test_error_does_not_leak_api_key():
    session = Session([requests.ConnectionError("https://example.test?key=secret")])
    translator = Translator(provider="cloud", api_key="secret", session=session)
    with pytest.raises(TranslationError) as error:
        translator.translate(["Hello"])
    assert "secret" not in str(error.value)


def test_cancel_does_not_request_network():
    session = Session([])
    assert Translator(session=session).translate(["Hello"], lambda: True) == []
    assert not session.calls


@pytest.mark.parametrize("sequence,vk", [("Ctrl+T", 84), ("Alt+Shift+F12", 123), ("Ctrl+1", 49)])
def test_supported_hotkeys(sequence, vk):
    modifiers, actual = parse_hotkey(sequence)
    assert modifiers & 0x4000
    assert actual == vk


@pytest.mark.parametrize("sequence", ["", "T", "Ctrl+", "Ctrl+F25", "Ctrl+T, Ctrl+X", "Ctrl+中"])
def test_invalid_hotkeys(sequence):
    with pytest.raises(ValueError):
        parse_hotkey(sequence)


def test_fixed_source_is_sent_to_google():
    session = Session([free_response("谢谢")])
    with __import__("contextlib").closing(Translator(source="ko", session=session)) as translator:
        assert translator.translate(["감사합니다"]) == ["谢谢"]
    assert session.calls[0][1]["params"]["sl"] == "ko"


def test_baidu_signature_and_language_codes():
    import hashlib
    session = Session([{"trans_result": [{"dst": "谢谢"}]}])
    translator = Translator(provider="baidu", source="ja", app_id="test", api_key="key", session=session)
    assert translator.translate(["ありがとう"]) == ["谢谢"]
    payload = session.calls[0][1]["data"]
    assert (payload["from"], payload["to"]) == ("jp", "zh")
    assert payload["sign"] == hashlib.md5(("testありがとう" + payload["salt"] + "key").encode()).hexdigest()
    translator.close()


def test_youdao_v3_long_input_signature():
    import hashlib
    session = Session([{"errorCode": "0", "translation": ["结果"]}])
    translator = Translator(provider="youdao", source="ko", app_id="app", api_key="key", session=session)
    query = "가나다라마바사아자차카타파하" * 3
    assert translator.translate([query]) == ["结果"]
    payload = session.calls[0][1]["data"]
    digest = query[:10] + str(len(query)) + query[-10:]
    assert payload["sign"] == hashlib.sha256(("app" + digest + payload["salt"] + payload["curtime"] + "key").encode()).hexdigest()
    assert (payload["from"], payload["to"], payload["signType"]) == ("ko", "zh-CHS", "v3")
    translator.close()


@pytest.mark.parametrize("provider,data", [("baidu", {"error_code": "54003"}), ("youdao", {"errorCode": "411"})])
def test_official_errors_are_visible(provider, data):
    translator = Translator(provider=provider, app_id="app", api_key="secret", session=Session([data]))
    with pytest.raises(TranslationError) as error:
        translator.translate(["Hello"])
    assert "secret" not in str(error.value)
    translator.close()


def test_vertical_columns_merge_right_to_left_without_joining_distant_bubbles():
    from screenlingo.core import TextBlock, group_vertical_paragraphs
    blocks = [TextBlock(20, 0, 20, 100, "面談"), TextBlock(50, 0, 20, 100, "三者"),
              TextBlock(250, 0, 20, 100, "別の話")]
    merged = group_vertical_paragraphs(blocks)
    assert [b.source for b in merged] == ["別の話", "三者面談"]
    assert merged[1].width == 50
