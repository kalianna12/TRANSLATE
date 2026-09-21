"""Offline identical-fixture CPU thread comparison; no translation requests."""
import json
from pathlib import Path
import statistics
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from benchmark import SAMPLES, make_fixture, normalized, edit_distance
from screenlingo.ocr import MultilingualOCR

rows = []
for threads in (4, 2, 1):
    engine = MultilingualOCR(inference_threads=threads)
    for mode in ("fixed", "auto"):
        times, errors, detects, recs = [], [], [], []
        for size, dark, textured in [(24, True, False), (18, True, False), (24, False, False), (14, True, False), (18, True, True)]:
            for lang, text, _ in SAMPLES:
                frame = np.asarray(make_fixture(lang, text, size, dark, textured))[:, :, ::-1].copy()
                engine.cache.clear()
                start = time.perf_counter()
                result = engine(frame, source=lang if mode == "fixed" else "auto")
                times.append((time.perf_counter() - start) * 1000)
                errors.append(edit_distance(normalized(text), normalized(" ".join(r[1] for r in result))))
                detects.append(engine.last_metrics["detect_ms"])
                recs.append(engine.last_metrics["recognize_ms"])
        row = dict(threads=threads, mode=mode, median_ms=statistics.median(times),
                   p95_ms=float(np.percentile(times,95)), errors=sum(errors),
                   detect_ms=statistics.median(detects), rec_ms=statistics.median(recs))
        rows.append(row)
        print(json.dumps(row), flush=True)
    del engine
Path("artifacts/ocr-thread-comparison.json").write_text(json.dumps(rows, indent=2))
