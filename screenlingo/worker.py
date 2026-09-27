import threading
import time

from contextlib import closing
from dataclasses import replace
from PySide6.QtCore import QThread, Signal

from .core import frame_changed, make_blocks
from .languages import LANGUAGE_NAMES, script_of
from .capture import CaptureUnavailable, CoordinatedScreenCapture, WindowCapture, PreviewThenWindowCapture
from .runtime import get_translator


def text_signature(blocks):
    return [(block.source, block.x, block.y, block.width, block.height) for block in blocks]


def same_text(first, second, tolerance=4):
    if len(first) != len(second):
        return False
    return all(a[0] == b[0] and all(abs(x - y) <= tolerance for x, y in zip(a[1:], b[1:]))
               for a, b in zip(first, second))


class TranslationWorker(QThread):
    result = Signal(int, object)
    status = Signal(int, str)
    fault = Signal(int, str)
    fatal = Signal(int, str)
    metrics = Signal(int, object)
    screen_requested = Signal(int, object)

    def __init__(self, generation, region, options, parent=None):
        super().__init__(parent)
        self.generation = generation
        self.region = region
        self.options = options
        self.cancel = threading.Event()

    def stop(self):
        self.cancel.set()

    def run(self):
        try:
            compare_text = (lambda a, b: [v[0] for v in a] == [v[0] for v in b]) if self.options.get("fixed_background") else same_text
            translator = get_translator(self.options)
            if self.options.get("provider") == "deepseek":
                with translator.operation_lock:
                    translator.ai_context.clear()
                    translator.cache.clear()
            if self.cancel.is_set():
                return
            self.status.emit(self.generation, "正在加载本地 OCR 模型…")
            from .ocr import get_ocr
            ocr = get_ocr(lambda message: self.status.emit(self.generation, message), self.cancel.is_set)
            previous = None
            previous_text = None
            failures = 0
            hwnd = self.options.get("window_hwnd", 0)
            source = WindowCapture(hwnd, self.region) if hwnd else CoordinatedScreenCapture(
                lambda reply: self.screen_requested.emit(self.generation, reply))
            with closing(source) as capture:
                while not self.cancel.is_set():
                    started = time.monotonic()
                    try:
                        bgr = capture.grab(self.cancel.is_set)
                        if bgr is None:
                            self.cancel.wait(0.2)
                            continue
                        rgb = bgr[:, :, ::-1].copy()
                        if frame_changed(previous, rgb):
                            self.status.emit(self.generation, "正在识别文字…")
                            from .ocr import detect_document_lines
                            document_lines = detect_document_lines(bgr) if self.options.get("progressive", True) and self.options.get("provider") != "deepseek" and self.options.get("reading_layout") != "manga" and not self.options.get("fixed_background") else None
                            if document_lines is not None and len(document_lines) >= 6:
                                from .document import translate_document
                                document_result = translate_document(self, capture, ocr, translator, bgr, previous_text, started)
                                if document_result is None:
                                    previous = previous_text = None
                                else:
                                    previous, previous_text = document_result
                                    if isinstance(capture, PreviewThenWindowCapture) and self.options["realtime"] and not self.cancel.is_set():
                                        capture.activate_window()
                                failures = 0
                                if not self.options["realtime"] or self.cancel.is_set():
                                    break
                                self.cancel.wait(max(0.05, self.options["interval"] / 1000 - (time.monotonic() - started)))
                                continue
                            ocr_started = time.perf_counter()
                            detected = ocr(bgr, self.cancel.is_set, source=self.options.get("source", "auto"))
                            ocr_ms = (time.perf_counter() - ocr_started) * 1000
                            if self.cancel.is_set():
                                break
                            blocks = make_blocks(detected, rgb, self.options.get("reading_layout", "standard"))
                            signature = text_signature(blocks)
                            # Moving scenery behind translucent chat does not invalidate unchanged text.
                            if previous_text is not None and compare_text(previous_text, signature):
                                previous = rgb
                                self.cancel.wait(max(0.05, self.options["interval"] / 1000 - (time.monotonic() - started)))
                                continue
                            self.result.emit(self.generation, [replace(block) for block in blocks])
                            translate_started = time.perf_counter()
                            if blocks:
                                self.status.emit(self.generation, f"正在翻译 {len(blocks)} 行文字…")
                                translations = translator.translate([b.source for b in blocks], self.cancel.is_set)
                                if self.cancel.is_set():
                                    break
                                for block, translated in zip(blocks, translations):
                                    block.translated = translated
                            translate_ms = (time.perf_counter() - translate_started) * 1000
                            # Do not paste an old translation onto a changed page after a slow request.
                            if self.options["realtime"]:
                                latest_bgr = capture.grab(self.cancel.is_set)
                                if latest_bgr is None:
                                    continue
                                latest = latest_bgr[:, :, ::-1].copy()
                                if frame_changed(rgb, latest):
                                    verify_started = time.perf_counter()
                                    latest_blocks = make_blocks(ocr(latest[:, :, ::-1].copy(), self.cancel.is_set,
                                                                   source=self.options.get("source", "auto")), latest, self.options.get("reading_layout", "standard"))
                                    ocr_ms += (time.perf_counter() - verify_started) * 1000
                                    if not compare_text(signature, text_signature(latest_blocks)):
                                        self.status.emit(self.generation, "聊天内容已更新，正在翻译最新文字…")
                                        previous = None
                                        previous_text = None
                                        continue
                                    rgb = latest
                            if self.cancel.is_set():
                                break
                            self.result.emit(self.generation, blocks)
                            previous = rgb
                            previous_text = signature
                            elapsed = time.monotonic() - started
                            state = "实时监测中" if self.options["realtime"] else "单次翻译完成"
                            languages = "/".join(sorted({LANGUAGE_NAMES[script_of(b.source)] for b in blocks})) or "无文字"
                            self.status.emit(self.generation, f"{state} · {languages} · {len(blocks)} 行 · {elapsed:.2f} 秒")
                            self.metrics.emit(self.generation, {"ocr_ms": round(ocr_ms, 1),
                                              "translate_ms": round(translate_ms, 1), "total_ms": round(elapsed * 1000, 1),
                                              "translation_cache_hits": translator.cache_hits,
                                              "network_calls": translator.network_calls, **ocr.last_metrics})
                            if isinstance(capture, PreviewThenWindowCapture) and self.options["realtime"] and not self.cancel.is_set():
                                capture.activate_window()
                        failures = 0
                        if not self.options["realtime"]:
                            break
                    except Exception as exc:
                        if self.cancel.is_set():
                            break
                        failures += 1
                        from .core import TranslationError
                        detail = str(exc) if isinstance(exc, (TranslationError, CaptureUnavailable)) else f"识别或截图失败（{type(exc).__name__}）"
                        if isinstance(exc, CaptureUnavailable):
                            self.result.emit(self.generation, [])
                            self.fatal.emit(self.generation, detail)
                            break
                        self.fault.emit(self.generation, detail)
                        if not self.options["realtime"]:
                            break
                        self.cancel.wait(max(getattr(exc, "retry_after", 0), min(30, 2 ** min(failures, 5))))
                    remaining = self.options["interval"] / 1000 - (time.monotonic() - started)
                    self.cancel.wait(max(0.05, remaining))
        except Exception as exc:
            if not self.cancel.is_set():
                detail = str(exc) if isinstance(exc, CaptureUnavailable) else f"模型或窗口采集初始化失败（{type(exc).__name__}），请检查依赖和模型下载。"
                self.fatal.emit(self.generation, detail)
        finally:
            pass  # HTTP session and bounded cache are reused by the next selection.
