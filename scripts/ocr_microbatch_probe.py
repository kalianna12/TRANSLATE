"""Experiment: preserve original padding while splitting ONNX inference batches."""
import json
from pathlib import Path
import statistics
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cv2
import numpy as np
from benchmark import normalized, edit_distance
from document_benchmark import SAMPLES
from screenlingo.ocr import MultilingualOCR


class Microbatch:
    def __init__(self, original):
        self.original = original

    def __getattr__(self, name):
        return getattr(self.original, name)

    def __call__(self, images):
        if len(images) < 2:
            return self.original(images)
        outputs = [self.original(images[i:i + 1]) for i in range(len(images))]
        return [np.concatenate([part[j] for part in outputs], axis=0) for j in range(len(outputs[0]))]


def main():
    engine = MultilingualOCR()
    multi, ko = engine.engine.text_rec.session, engine.korean.session
    rows = []
    for split in (False, True):
        engine.engine.text_rec.session = Microbatch(multi) if split else multi
        engine.korean.session = Microbatch(ko) if split else ko
        for lang in ("ja", "en", "ko"):
            frame = cv2.imread("artifacts/documents/" + lang + ".png")
            times = []
            for _ in range(3):
                engine.cache.clear()
                start = time.perf_counter()
                actual = "".join(r[1] for r in engine(frame, source=lang))
                times.append((time.perf_counter() - start) * 1000)
            row = dict(split=split, lang=lang, median_ms=statistics.median(times),
                       errors=edit_distance(normalized("".join(SAMPLES[lang])), normalized(actual)))
            rows.append(row)
            print(row, flush=True)
    Path("artifacts/ocr-microbatch-probe.json").write_text(json.dumps(rows, indent=2))


if __name__ == "__main__":
    main()
