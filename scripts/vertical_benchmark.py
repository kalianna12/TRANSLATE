"""Compare intact-column recognition and glyph reflow on declared synthetic text."""
import sys
import json
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
import cv2
from vertical_fixture import vertical_fixture, COLUMNS
from screenlingo.ocr import MultilingualOCR

engine = MultilingualOCR()
rows = []
inputs = [(f"font-{size}", np.array(vertical_fixture(size))[:, :, ::-1].copy()) for size in (20, 32, 40)]
browser = cv2.imread("artifacts/browser-source-manga.png")
if browser is not None:
    inputs.append(("browser-175percent", browser))
for label, image in inputs:
    for scale in (1, 0.75, 0.5):
        resized = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        engine.cache.clear()
        started = time.perf_counter()
        result = engine(resized, source="ja")
        row = {"fixture": label, "scale": scale, "ms": (time.perf_counter() - started) * 1000,
               "readings": [r[1] for r in result], "exact": "".join(r[1] for r in result) == "".join(COLUMNS)}
        rows.append(row)
        print(ascii(row), flush=True)
Path("artifacts/vertical-comparison.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
