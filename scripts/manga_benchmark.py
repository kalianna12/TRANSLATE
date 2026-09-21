"""Synthetic multi-bubble layout using text transcribed from the supplied manga."""
import json
from pathlib import Path
import sys
import time
import statistics
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from benchmark import normalized, edit_distance
from screenlingo.ocr import MultilingualOCR
from screenlingo.core import make_blocks

BUBBLES = [
    ((530, 60, 950, 480), ["巴と澪は", "ルトに任せる", "として…"]),
    ((60, 60, 470, 480), ["そろそろ", "昼時だよね", "店の状況は", "どんな感じ？"]),
    ((530, 560, 950, 1000), ["今日の分の", "商品は", "もう終わり", "そうですね"]),
    ((60, 560, 470, 1000), ["開店前に", "長蛇の列が", "できたため"]),
]
image = Image.new("RGB", (1024, 1100), "white")
draw = ImageDraw.Draw(image)
font = ImageFont.truetype("C:/Windows/Fonts/YuGothM.ttc", 28)
for rect, columns in BUBBLES:
    draw.ellipse(rect, outline="black", width=2)
    for column, text in enumerate(columns):
        x = rect[2] - 85 - column * 48
        for row, char in enumerate(text):
            draw.text((x, rect[1] + 75 + row * 31), char, fill="black", font=font, anchor="lt")
draw.line((30, 525, 994, 525), fill="black", width=4)
Path("artifacts").mkdir(exist_ok=True)
image.save("artifacts/manga-bubbles.png")
rgb = np.array(image)
engine = MultilingualOCR()
rows = []
for source in ("ja", "auto"):
    runs = []
    for _ in range(3):
        engine.cache.clear()
        started = time.perf_counter()
        blocks = make_blocks(engine(rgb[:, :, ::-1].copy(), source=source), rgb)
        runs.append((time.perf_counter() - started) * 1000)
    elapsed = statistics.median(runs)
    bubbles = []
    for rect, columns in BUBBLES:
        selected = [b for b in blocks if rect[0] <= b.x + b.width / 2 <= rect[2]
                    and rect[1] <= b.y + b.height / 2 <= rect[3]]
        text = "".join(b.source for b in sorted(selected, key=lambda b: -b.x))
        expected = "".join(columns)
        bubbles.append({"expected": expected, "recognized": text, "blocks": len(selected),
                        "char_errors": edit_distance(normalized(expected), normalized(text)),
                        "char_count": len(normalized(expected))})
    row = {"source": source, "ocr_ms": elapsed, "runs_ms": runs, "metrics": engine.last_metrics.copy(), "bubbles": bubbles}
    rows.append(row)
    print(source, round(elapsed), "bubble errors", [b["char_errors"] for b in bubbles],
          "blocks", [b["blocks"] for b in bubbles], flush=True)
Path("artifacts/manga-benchmark.json").write_text(json.dumps({"scope": "Synthetic four-bubble text layout; no original art, screentones or full furigana. Not original-image OCR.",
                                                             "rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
