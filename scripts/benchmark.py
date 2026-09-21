"""Reproducible synthetic chat benchmark; every source sentence is declared below."""
import argparse
import json
from pathlib import Path
import platform
import statistics
import sys
import time
import unicodedata

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from screenlingo.core import Translator
from screenlingo.ocr import MultilingualOCR, script_of


SAMPLES = [
    ("en", "Enemy spotted at the entrance.", "敌人"),
    ("en", "Please wait for the next round.", "等"),
    ("en", "I need help. Cover me!", "掩护"),
    ("en", "Good game! Thanks for playing.", "谢"),
    ("ja", "敵が入口にいます。", "敌"),
    ("ja", "次のラウンドまで待ってください。", "等"),
    ("ja", "助けてください！", "帮"),
    ("ja", "一緒に遊んでくれてありがとう。", "谢"),
    ("ko", "입구에 적이 있어요.", "敌"),
    ("ko", "다음 라운드까지 기다려 주세요.", "等"),
    ("ko", "도와주세요!", "帮"),
    ("ko", "같이 게임해 주셔서 감사합니다.", "谢"),
]
FONTS = {"en": "arial.ttf", "ja": "YuGothM.ttc", "ko": "malgun.ttf"}


def make_fixture(language, text, size=24, dark=True, textured=False):
    font = ImageFont.truetype("C:/Windows/Fonts/" + FONTS[language], size)
    width = max(500, int(font.getlength(text)) + 48)
    image = Image.new("RGB", (width, size * 3), (23, 31, 44) if dark else (244, 246, 249))
    if textured:
        rng = np.random.default_rng(20260918)
        background = rng.integers(12, 65, (size * 3, width, 3), dtype=np.uint8)
        image = Image.fromarray(background)
    ImageDraw.Draw(image).text((20, 10), text, font=font, fill=(236, 241, 250) if dark else (20, 24, 30))
    return image


def normalized(text):
    # Whitespace/punctuation vary across OCR engines; preserve actual letters and case.
    return "".join(c for c in unicodedata.normalize("NFKC", text) if c.isalnum())


def edit_distance(a, b):
    row = list(range(len(b) + 1))
    for i, char in enumerate(a, 1):
        new = [i]
        for j, other in enumerate(b, 1):
            new.append(min(new[-1] + 1, row[j] + 1, row[j - 1] + (char != other)))
        row = new
    return row[-1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--network", action="store_true")
    parser.add_argument("--output", default="artifacts/benchmark.json")
    parser.add_argument("--source-mode", choices=["auto", "fixed"], default="auto")
    args = parser.parse_args()
    start = time.perf_counter()
    engine = MultilingualOCR()
    cold_ms = (time.perf_counter() - start) * 1000
    translators = {lang: Translator(source=lang) for lang in ("auto", "en", "ja", "ko")}
    if args.network:
        for translator in translators.values():
            translator.warm_connection()
    rows = []
    try:
        for size, dark, textured in [(24, True, False), (18, True, False), (24, False, False),
                                     (14, True, False), (18, True, True)]:
            for language, text, keyword in SAMPLES:
                source = language if args.source_mode == "fixed" else "auto"
                translator = translators[source]
                image = make_fixture(language, text, size, dark, textured)
                bgr = np.array(image)[:, :, ::-1].copy()
                started = time.perf_counter()
                result = engine(bgr, source=source)
                ocr_ms = (time.perf_counter() - started) * 1000
                actual = " ".join(item[1] for item in result)
                reference = normalized(text)
                distance = edit_distance(reference, normalized(actual))
                row = {"language": language, "source_mode": source, "font_px": size, "dark": dark,
                       "textured": textured,
                       "source": text, "recognized": actual, "ocr_ms": round(ocr_ms, 2),
                       "char_errors": distance, "char_count": len(reference),
                       "language_correct": script_of(actual) == language,
                       "exact_normalized": distance == 0, "exact_raw": actual == text}
                if args.network:
                    started = time.perf_counter()
                    translated = translator.translate([actual])[0] if actual else ""
                    row.update(translation=translated, translate_ms=round((time.perf_counter() - started) * 1000, 2),
                               keyword_pass=keyword in translated, translation_cache_hits=translator.cache_hits)
                # Repeated frame measures recognition cache without attributing network latency to OCR.
                started = time.perf_counter()
                engine(bgr, source=source)
                row["cached_ocr_ms"] = round((time.perf_counter() - started) * 1000, 2)
                rows.append(row)
                print(language, size, dark, "CER", distance, "ms", round(ocr_ms), ascii(actual), flush=True)
    finally:
        for translator in translators.values():
            translator.close()
    summary = {"platform": platform.platform(), "cold_init_ms": round(cold_ms, 2), "samples": len(rows),
               "ocr_median_ms": round(statistics.median(r["ocr_ms"] for r in rows), 2),
               "ocr_p95_ms": round(float(np.percentile([r["ocr_ms"] for r in rows], 95)), 2),
               "cached_ocr_median_ms": round(statistics.median(r["cached_ocr_ms"] for r in rows), 2),
               "character_accuracy": 1 - sum(r["char_errors"] for r in rows) / sum(r["char_count"] for r in rows),
               "exact_lines": sum(r["exact_normalized"] for r in rows),
               "raw_exact_lines": sum(r["exact_raw"] for r in rows), "source_mode": args.source_mode,
               "language_correct": sum(r["language_correct"] for r in rows)}
    if args.network:
        summary["translation_keyword_pass"] = sum(r["keyword_pass"] for r in rows)
        summary["translation_median_ms"] = statistics.median(r["translate_ms"] for r in rows)
        uncached = [r for r in rows if not r["translation_cache_hits"]]
        summary["translation_uncached_median_ms"] = statistics.median(r["translate_ms"] for r in uncached)
        totals = [r["ocr_ms"] + r["translate_ms"] for r in uncached]
        summary["uncached_processing_median_ms"] = statistics.median(totals)
        summary["uncached_processing_p95_ms"] = float(np.percentile(totals, 95))
        summary["uncached_processing_under_500ms"] = sum(t <= 500 for t in totals)
        summary["uncached_samples"] = len(uncached)
    output = Path(args.output)
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
