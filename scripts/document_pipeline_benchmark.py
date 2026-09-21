"""Real OCR/Google pipeline on declared arrays. No screenshot or GUI latency claim."""
import argparse
import json
from pathlib import Path
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from document_benchmark import fixture, SAMPLES
from benchmark import normalized, edit_distance
from screenlingo.core import Region
from screenlingo.ocr import get_ocr
from screenlingo.runtime import get_translator, close_runtime
from screenlingo.worker import TranslationWorker
import screenlingo.worker as worker_module

parser = argparse.ArgumentParser()
parser.add_argument("--languages", nargs="+", choices=["ja", "en", "ko"], default=["ja", "en", "ko"])
parser.add_argument("--baseline", action="store_true")
parser.add_argument("--output", default="artifacts/document-pipeline.json")
args = parser.parse_args()
engine = get_ocr()
engine.document_fast_path = not args.baseline
rows = []
for lang in args.languages:
    image = fixture(lang)
    bgr = np.array(image)[:, :, ::-1].copy()
    class Capture:
        def __init__(self, region):
            pass
        def grab(self, cancelled):
            return bgr.copy()
        def close(self):
            pass
    worker_module.ScreenCapture = Capture
    options = {"source": lang, "target": "zh-CN", "provider": "free", "interval": 200,
               "realtime": False, "progressive": not args.baseline}
    engine.cache.clear()
    translator = get_translator(options)
    translator.warm_connection()
    row = {"language": lang, "baseline": args.baseline, "first_result_ms": None, "complete_ms": None,
           "errors": [], "counts": []}
    worker = TranslationWorker(1, Region(0, 0, image.width, image.height), options)
    def receive(token, blocks):
        if blocks and all(b.translated for b in blocks):
            elapsed = (time.perf_counter() - started) * 1000
            if row["first_result_ms"] is None:
                row["first_result_ms"] = elapsed
            row["complete_ms"] = elapsed
            row["counts"].append(len(blocks))
            row["texts"] = [{"source": b.source, "translated": b.translated} for b in blocks]
    worker.result.connect(receive)
    worker.metrics.connect(lambda token, data: row.update(metrics=data))
    worker.fault.connect(lambda token, error: row["errors"].append(error))
    worker.fatal.connect(lambda token, error: row["errors"].append(error))
    started = time.perf_counter()
    worker.run()
    reference = normalized("".join(SAMPLES[lang]))
    actual = normalized("".join(t["source"] for t in row.get("texts", [])))
    row.update(char_errors=edit_distance(reference, actual), char_count=len(reference))
    rows.append(row)
    print(lang, row["first_result_ms"], row["complete_ms"], row["counts"], ascii(row["errors"]), flush=True)
    if row["errors"]:
        break  # Stop live tests on network failure; no repeated probes during cooldown.
close_runtime()
Path(args.output).write_text(json.dumps({"scope": "Real local OCR and Google on synthetic arrays; excludes screen capture, selection and painting. First result may contain only one line.",
                                       "rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
raise SystemExit(1 if any(row["errors"] for row in rows) else 0)
