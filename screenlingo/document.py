"""Overlap page OCR with translation; all capture remains on its owning worker thread."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import queue
import threading
import time

from .core import frame_changed, make_blocks


def translate_document(worker, capture, ocr, translator, bgr, previous_text, started):
    from .worker import same_text, text_signature
    compare_text = (lambda a, b: [v[0] for v in a] == [v[0] for v in b]) if worker.options.get("fixed_background") else same_text
    local_cancel = threading.Event()
    cancelled = lambda: local_cancel.is_set() or worker.cancel.is_set()
    updates = queue.Queue()
    source = worker.options.get("source", "auto")
    rgb = bgr[:, :, ::-1].copy()
    final_rgb = rgb
    translated = {}
    signature = None
    first_ms = None
    translate_ms = 0
    verify_ms = 0
    ocr_ms = 0
    delivered = None
    calls_before = translator.network_calls

    def still_current(current_signature, final=False):
        nonlocal final_rgb, verify_ms
        if not worker.options["realtime"]:
            return True
        latest_bgr = capture.grab(cancelled)
        if latest_bgr is None:
            return False
        latest = latest_bgr[:, :, ::-1].copy()
        if frame_changed(rgb, latest):
            begin = time.perf_counter()
            latest_blocks = make_blocks(ocr(latest_bgr, cancelled, source=source), latest, worker.options.get("reading_layout", "standard"))
            verify_ms += (time.perf_counter() - begin) * 1000
            latest_signature = text_signature(latest_blocks)
            compare = latest_signature if final else latest_signature[:len(current_signature)]
            if not compare_text(current_signature, compare):
                worker.result.emit(worker.generation, [])
                worker.status.emit(worker.generation, "聊天内容已更新，正在翻译最新文字…")
                return False
        final_rgb = latest
        return True

    def produce():
        begin = time.perf_counter()
        try:
            result = ocr(bgr, cancelled, source=source,
                         on_chunk=lambda lines: updates.put((lines, False, 0, None)) if not cancelled() else None)
            updates.put((result, True, (time.perf_counter() - begin) * 1000, None))
        except Exception as exc:
            updates.put(([], True, 0, exc))

    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="document-ocr") as pool:
        pool.submit(produce)
        try:
            while not cancelled():
                try:
                    event = updates.get(timeout=0.05)
                except queue.Empty:
                    continue
                # Coalesce completed OCR batches while a prior translation was in flight.
                while not updates.empty():
                    event = updates.get_nowait()
                detected, complete, duration, error = event
                if error:
                    raise error
                if complete:
                    ocr_ms = duration
                blocks = make_blocks(detected, rgb, worker.options.get("reading_layout", "standard"))
                signature = text_signature(blocks)
                unchanged = (previous_text is not None and
                             compare_text(signature, previous_text[:len(signature)]))
                if signature and not unchanged and signature != delivered:
                    for block in blocks:
                        block.translated = translated.get(block.source, "")
                    if not translated:
                        worker.result.emit(worker.generation, [replace(block) for block in blocks])
                    worker.status.emit(worker.generation, f"正在分段翻译正文：已识别 {len(blocks)} 行…")
                    begin = time.perf_counter()
                    # Send only newly recognized lines. DeepSeek retains prior context;
                    # resending each growing prefix wastes tokens and changes earlier prose.
                    missing = list(dict.fromkeys(b.source for b in blocks if b.source not in translated))
                    new_values = translator.translate(missing, cancelled) if missing else []
                    if cancelled():
                        return None
                    if len(new_values) != len(missing):
                        from .core import TranslationError
                        raise TranslationError("分段译文数量不匹配，请重试。")
                    translated.update(zip(missing, new_values))
                    values = [translated[b.source] for b in blocks]
                    translate_ms += (time.perf_counter() - begin) * 1000
                    if cancelled():
                        return None
                    # Validate before EACH partial overlay; old pages must never overwrite new text.
                    if not still_current(signature, final=complete):
                        return None
                    if cancelled():
                        return None
                    for block, value in zip(blocks, values):
                        block.translated = value
                        translated[block.source] = value
                    worker.result.emit(worker.generation, blocks)
                    delivered = signature
                    if first_ms is None:
                        first_ms = (time.monotonic() - started) * 1000
                if complete:
                    if not still_current(signature, final=True):
                        return None
                    # A shorter new page must also clear lines removed from the previous page.
                    if unchanged and not compare_text(signature, previous_text):
                        values = translator.translate([b.source for b in blocks], cancelled)
                        for block, value in zip(blocks, values):
                            block.translated = value
                        if not cancelled():
                            worker.result.emit(worker.generation, blocks)
                    elapsed = (time.monotonic() - started) * 1000
                    state = "实时监测中" if worker.options["realtime"] else "单次翻译完成"
                    worker.status.emit(worker.generation, f"{state} · 正文 {len(blocks)} 行 · {elapsed / 1000:.2f} 秒")
                    worker.metrics.emit(worker.generation, {
                        "ocr_ms": round(ocr_ms + verify_ms, 1), "translate_ms": round(translate_ms, 1),
                        "total_ms": round(elapsed, 1), "first_result_ms": round(first_ms, 1) if first_ms else None,
                        "translation_cache_hits": translator.cache_hits,
                        "network_calls": translator.network_calls - calls_before, **ocr.last_metrics})
                    return final_rgb, signature
            return None
        finally:
            local_cancel.set()
