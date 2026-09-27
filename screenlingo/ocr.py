"""One detector, three script recognizers and cached multilingual line fusion."""
from collections import OrderedDict
import hashlib
import time
import threading
import os
from concurrent.futures import ThreadPoolExecutor

import cv2
import numpy as np
from rapidocr_onnxruntime import RapidOCR
from rapidocr_onnxruntime.ch_ppocr_rec import TextRecognizer

from .models import ensure_models
from .languages import script_of

_recognition_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ocr-script")


def recognize_three(engine, crops, positions=False):
    """Join every model before returning, including when another model raises."""
    ratios = [p.shape[1] / max(1, p.shape[0]) for p in crops if p is not None]
    long_batch = len(ratios) >= 3 and max(ratios) > 20
    def invoke(model, images):
        previous = getattr(model, "rec_batch_num", None)
        if long_batch and previous is not None:
            model.rec_batch_num = min(previous, 2)
        try:
            return recognize_with_positions(model, images) if positions else model(images)
        finally:
            if previous is not None:
                model.rec_batch_num = previous
    if not getattr(engine, "parallel_auto", False):
        return [invoke(model, crops)[0] for model in (engine.engine.text_rec, engine.korean, engine.russian)]
    korean = _recognition_pool.submit(invoke, engine.korean, crops)
    russian = _recognition_pool.submit(invoke, engine.russian, crops)
    try:
        multi = invoke(engine.engine.text_rec, crops)[0]
    finally:
        try:
            ko = korean.result()[0]
        finally:
            ru = russian.result()[0]
    return multi, ko, ru


def choose_reading(multilingual, korean):
    """Confidence arbitration with a Hangul requirement for the Korean candidate."""
    text, confidence = multilingual[:2]
    ko_text, ko_confidence = korean[:2]
    if script_of(ko_text) == "ko" and ko_confidence > confidence:
        return ko_text, float(ko_confidence)
    return text, float(confidence)


def crop_key(crop):
    """Ignore uniform background brightness changes while keeping exact glyph masks."""
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    _, mask = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    if np.count_nonzero(mask) > mask.size // 2:
        mask = 255 - mask
    return crop.shape, hashlib.blake2b(mask.tobytes(), digest_size=16).digest()


def split_mixed_line(crop):
    """Split horizontal words at whitespace so one script cannot erase another."""
    h, w = crop.shape[:2]
    if w < h * 2:
        return [crop]
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    _, mask = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    if np.count_nonzero(mask) > mask.size // 2:
        mask = 255 - mask
    blank = np.count_nonzero(mask, axis=0) == 0
    cuts = [0]
    start = None
    for x, empty in enumerate(blank):
        if empty and start is None:
            start = x
        elif not empty and start is not None:
            if start > 0 and x - start >= max(3, round(h * .28)):
                cuts.append((start + x) // 2)
            start = None
    cuts.append(w)
    return [crop[:, a:b] for a, b in zip(cuts, cuts[1:]) if b > a]


def recognize_with_positions(recognizer, crops):
    if isinstance(recognizer, TextRecognizer):
        return recognizer(crops, return_word_box=True)
    return recognizer(crops)


def split_script_runs(crop, readings):
    """Use confident CTC script runs to cut tightly joined multilingual text."""
    h, w = crop.shape[:2]
    if w < h * 2:
        return [crop]
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    _, mask = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    if np.count_nonzero(mask) > mask.size // 2:
        mask = 255 - mask
    ink = np.count_nonzero(mask, axis=0)
    cuts = [0, w]
    for reading, script in readings:
        if len(reading) < 3:
            continue
        text, score, info = reading
        length, words, columns, states, confidence = info
        chars = [c for word in words for c in word]
        positions = [x * w / length for group in columns for x in group]
        runs = []
        for i, c in enumerate(chars):
            valid = script_of(c) == script and confidence[i] >= .8
            if valid:
                if runs and runs[-1][-1] == i-1:
                    runs[-1].append(i)
                else:
                    runs.append([i])
        for run in runs:
            if len(run) < 2:
                continue
            for i, j in [(run[0]-1, run[0]), (run[-1], run[-1]+1)]:
                if i < 0 or j >= len(chars):
                    continue
                center = (positions[i] + positions[j]) / 2
                left, right = max(1, int(center-h*.35)), min(w-1, int(center+h*.35))
                if right <= left:
                    continue
                candidates = np.arange(left, right)
                x = int(candidates[np.argmin(ink[left:right] * h + abs(candidates-center))])
                if all(abs(x-c) > h*.45 for c in cuts):
                    cuts.append(x)
    cuts.sort()
    return [crop[:, a:b] for a, b in zip(cuts, cuts[1:])]


def merge_vertical_boxes(boxes):
    """Join detector fragments of an upright column before recognition, not after translation."""
    boxes = [np.asarray(box, dtype=np.float32) for box in boxes]

    def bounds(box):
        x, y = box.min(axis=0)
        right, bottom = box.max(axis=0)
        return float(x), float(y), float(right), float(bottom)

    changed = True
    while changed:
        changed = False
        for i, first in enumerate(boxes):
            ax, ay, ar, ab = bounds(first)
            aw, ah = ar - ax, ab - ay
            if ah < aw * 1.8:
                continue
            for j, second in enumerate(boxes):
                if i == j:
                    continue
                bx, by, br, bb = bounds(second)
                bw, bh = br - bx, bb - by
                overlap = min(ar, br) - max(ax, bx)
                gap = max(ay, by) - min(ab, bb)
                if (bh >= bw * 0.7 and overlap >= min(aw, bw) * 0.65
                        and abs((ax + ar) - (bx + br)) / 2 <= max(aw, bw) * 0.4
                        and gap <= max(aw, bw) * 0.8):
                    left, top, right, bottom = min(ax, bx), min(ay, by), max(ar, br), max(ab, bb)
                    boxes[i] = np.array([[left, top], [right, top], [right, bottom], [left, bottom]], dtype=np.float32)
                    boxes.pop(j)
                    changed = True
                    break
            if changed:
                break
    vertical = sum((b[:, 1].max() - b[:, 1].min()) > 1.8 * (b[:, 0].max() - b[:, 0].min()) for b in boxes)
    if vertical >= 2 and vertical >= len(boxes) * 0.6:
        return sorted(boxes, key=lambda b: (-float(b[:, 0].mean()), float(b[:, 1].min())))
    return RapidOCR.sorted_boxes(np.asarray(boxes))


def detect_document_lines(bgr):
    """Conservative projection path for wide, flat-background horizontal documents.

    Narrow/portrait selections, textures, vertical columns and ambiguous layouts
    stay on the neural detector. Coordinates always refer to the original pixels.
    """
    height, width = bgr.shape[:2]
    if width < 700 or height < 160 or width < height * 1.15:
        return None
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    counts = np.bincount(gray.ravel(), minlength=256)
    background = int(counts.argmax())
    flat = counts[max(0, background - 3):min(256, background + 4)].sum() / gray.size
    if flat < 0.82:
        return None
    mask = np.abs(gray.astype(np.int16) - background) > 35
    rows = np.flatnonzero(mask.sum(axis=1) >= 4)
    if not len(rows):
        return None
    groups = np.split(rows, np.flatnonzero(np.diff(rows) > 4) + 1)
    if not 3 <= len(groups) <= 80:
        return None
    boxes, ratios = [], []
    for group in groups:
        top, bottom = int(group[0]), int(group[-1]) + 1
        line_height = bottom - top
        xs = np.flatnonzero(mask[top:bottom].any(axis=0))
        if not len(xs) or not 8 <= line_height <= 100:
            return None
        left, right = int(xs[0]), int(xs[-1]) + 1
        ratios.append((right - left) / line_height)
        # A short heading should not send an otherwise clean document to the
        # downscaled neural detector. The page-wide median guard remains below.
        left, right = max(0, left - 3), min(width - 1, right + 3)
        top, bottom = max(0, top - 3), min(height - 1, bottom + 3)
        boxes.append([[left, top], [right, top], [right, bottom], [left, bottom]])
    if np.median(ratios) < 15:
        return None
    return np.asarray(boxes, dtype=np.float32)



class MultilingualOCR:
    def __init__(self, status=lambda message: None, cancelled=lambda: False, inference_threads=None, document_fast_path=True, parallel_auto=None):
        paths = ensure_models(status, cancelled)
        if cancelled():
            raise InterruptedError()
        threads = inference_threads or min(4, max(1, (os.cpu_count() or 4) // 4))
        self.engine = RapidOCR(
            rec_model_path=paths["multilingual"], intra_op_num_threads=threads, inter_op_num_threads=1,
            det_limit_type="max", det_limit_side_len=1280, use_cls=False,
        )
        self.korean = TextRecognizer({
            "model_path": paths["korean"], "intra_op_num_threads": threads, "inter_op_num_threads": 1,
            "use_cuda": False, "use_dml": False, "rec_batch_num": 6, "rec_img_shape": [3, 48, 320],
        })
        self.cache = OrderedDict()
        self.part_cache = OrderedDict()
        self.russian = TextRecognizer({
            "model_path": paths["russian"], "intra_op_num_threads": threads, "inter_op_num_threads": 1,
            "use_cuda": False, "use_dml": False, "rec_batch_num": 6, "rec_img_shape": [3, 48, 320],
        })
        self.last_metrics = {}
        self.lock = threading.RLock()
        self.document_fast_path = document_fast_path
        self.parallel_auto = (os.cpu_count() or 1) >= 8 if parallel_auto is None else parallel_auto

    def __call__(self, bgr, cancelled=lambda: False, source="auto", on_chunk=None):
        with self.lock:
            return self.recognize(bgr, cancelled, source, on_chunk)

    def recognize(self, bgr, cancelled, source, on_chunk=None):
        start = time.perf_counter()
        boxes = detect_document_lines(bgr) if getattr(self, "document_fast_path", True) else None
        detector = "projection" if boxes is not None else "neural"
        if boxes is None:
            boxes, _ = self.engine.text_det(bgr)
        detection_ms = (time.perf_counter() - start) * 1000
        if boxes is None or len(boxes) == 0 or cancelled():
            self.last_metrics = {"detect_ms": detection_ms, "recognize_ms": 0, "line_cache_hits": 0, "detector": detector}
            return []
        boxes = merge_vertical_boxes(boxes)
        crops = self.engine.get_crop_img_list(bgr, boxes)
        keys = [(source, crop_key(crop)) for crop in crops]
        missing = [i for i, key in enumerate(keys) if key not in self.cache]
        recognition_start = time.perf_counter()
        coarse_ms = refine_ms = 0.0
        part_hits = 0
        chunks = [missing]
        if on_chunk and len(boxes) >= 3:
            chunks = [missing[:2]] + [missing[i:i + 4] for i in range(2, len(missing), 4)]
        for indices in chunks:
            if cancelled():
                return []
            if not indices:
                continue
            pending = [crops[i] for i in indices]
            if source == "ru":
                readings, _ = self.russian(pending)
            elif source == "ko":
                readings, _ = self.korean(pending)
            elif source != "auto":
                readings, _ = self.engine.text_rec(pending)
            else:
                stage_start = time.perf_counter()
                multi, korean, russian = recognize_three(self, pending, positions=True)
                coarse_ms += (time.perf_counter() - stage_start) * 1000
                if cancelled():
                    return []
                readings = [choose_reading(a, b) for a, b in zip(multi, korean)]
                if cancelled():
                    return []
                readings = [r[:2] if script_of(r[0]) == "ru" and r[1] > a[1] else a
                            for a, r in zip(readings, russian)]
                # Arbitrate each word with ALL script models, including Korean.
                plans, all_parts = [], []
                for index, (m, k, r) in enumerate(zip(multi, korean, russian)):
                    if not ((script_of(r[0]) == "ru" and m[0] != r[0]) or
                            (script_of(k[0]) == "ko" and m[0] != k[0])):
                        continue
                    parts = split_mixed_line(pending[index])
                    if len(parts) < 4 and script_of(k[0]) == "ko" and script_of(r[0]) == "ru":
                        parts = split_script_runs(pending[index], [(k, "ko"), (r, "ru")])
                    if len(parts) < 2:
                        continue
                    if cancelled():
                        return []
                    plans.append((index, len(all_parts), len(parts)))
                    all_parts.extend(parts)
                if all_parts:
                    stage_start = time.perf_counter()
                    if not hasattr(self, "part_cache"):
                        self.part_cache = OrderedDict()
                    part_keys = [(p.shape, hashlib.blake2b(p.tobytes(), digest_size=16).digest()) for p in all_parts]
                    unique = {}
                    for key, part in zip(part_keys, all_parts):
                        if key not in self.part_cache:
                            unique.setdefault(key, part)
                        else:
                            part_hits += 1
                    if unique:
                        mr, kr, rr = recognize_three(self, list(unique.values()))
                        candidates = [choose_reading(a, b) for a, b in zip(mr, kr)]
                        candidates = [b[:2] if script_of(b[0]) == "ru" and b[1] > a[1] else a[:2]
                                      for a, b in zip(candidates, rr)]
                        self.part_cache.update(zip(unique, candidates))
                    selected = [self.part_cache[key] for key in part_keys]
                    for key in part_keys:
                        self.part_cache.move_to_end(key)
                    while len(self.part_cache) > 1024:
                        self.part_cache.popitem(last=False)
                    refine_ms += (time.perf_counter() - stage_start) * 1000
                    for index, offset, count in plans:
                        fused = selected[offset:offset+count]
                        if len({script_of(t) for t, s in fused if t}) > 1:
                            readings[index] = (" ".join(t for t, s in fused), float(np.mean([s for t, s in fused])))
            for i, reading in zip(indices, readings):
                self.cache[keys[i]] = reading[:2]
            if on_chunk:
                prefix = []
                for box, key in zip(boxes, keys):
                    if key not in self.cache:
                        break
                    text, score = self.cache[key]
                    prefix.append((box.tolist(), text, score))
                on_chunk(prefix)
        result = []
        for box, key in zip(boxes, keys):
            text, score = self.cache[key]
            self.cache.move_to_end(key)
            result.append((box.tolist(), text, score))
        while len(self.cache) > 512:
            self.cache.popitem(last=False)
        self.last_metrics = {"detect_ms": detection_ms,
                             "coarse_ms": coarse_ms, "refine_ms": refine_ms, "part_cache_hits": part_hits,
                             "recognize_ms": (time.perf_counter() - recognition_start) * 1000,
                             "line_cache_hits": len(keys) - len(missing), "detector": detector}
        return result


_shared_engine = None
_init_lock = threading.Lock()


def get_ocr(status=lambda message: None, cancelled=lambda: False):
    """Called only by the single active worker; reuse loaded models across selections."""
    global _shared_engine
    with _init_lock:
        if _shared_engine is None:
            _shared_engine = MultilingualOCR(status, cancelled)
    return _shared_engine
