"""Compare exact tile-change semantics and timing on synthetic full-size frames."""
import json
from pathlib import Path
import statistics
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from screenlingo.core import frame_changed


def reference(previous, current, threshold=2):
    delta = np.abs(current.astype(np.int16) - previous.astype(np.int16)).mean(axis=2)
    return any(float(delta[y:y + 64, x:x + 64].mean()) > threshold
               for y in range(0, delta.shape[0], 64) for x in range(0, delta.shape[1], 64))


rows = []
for height, width in [(720, 1280), (1080, 1920), (2160, 3840)]:
    before = np.zeros((height, width, 3), dtype=np.uint8)
    for changed in (False, True):
        after = before.copy()
        if changed:
            after[-30:-10, -100:-70] = 255
        row = {"width": width, "height": height, "changed": changed}
        for name, function in [("before_ms", reference), ("after_ms", frame_changed)]:
            samples = []
            for _ in range(7):
                started = time.perf_counter()
                assert function(before, after) == changed
                samples.append((time.perf_counter() - started) * 1000)
            row[name] = statistics.median(samples)
        rows.append(row)
        print(row, flush=True)
Path("artifacts/frame-benchmark.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
