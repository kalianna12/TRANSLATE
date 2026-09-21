"""Local GLM-OCR versus RapidOCR; no translation/API credentials or desktop captures."""
import argparse
import base64
from collections import defaultdict
import io
import json
from pathlib import Path
import sys
import time

import numpy as np
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from benchmark import make_fixture, normalized, edit_distance
from document_benchmark import fixture, SAMPLES
from vertical_fixture import vertical_fixture, COLUMNS
from screenlingo.ocr import MultilingualOCR


class Timed:
    def __init__(self, operation, name, timings):
        self.operation, self.name, self.timings = operation, name, timings

    def __call__(self, *args, **kwargs):
        start = time.perf_counter()
        try:
            return self.operation(*args, **kwargs)
        finally:
            self.timings[self.name] += (time.perf_counter() - start) * 1000

    def __getattr__(self, key):
        return getattr(self.operation, key)


def profile_engine(engine, timings):
    detector = engine.engine.text_det
    detector.infer = Timed(detector.infer, "detection_inference_ms", timings)
    detector.postprocess_op = Timed(detector.postprocess_op, "detection_postprocess_ms", timings)
    engine.engine.get_crop_img_list = Timed(engine.engine.get_crop_img_list, "crop_ms", timings)
    for name, rec in [("multilingual", engine.engine.text_rec), ("korean", engine.korean)]:
        rec.resize_norm_img = Timed(rec.resize_norm_img, name + "_preprocess_ms", timings)
        rec.session = Timed(rec.session, name + "_inference_ms", timings)
        rec.postprocess_op = Timed(rec.postprocess_op, name + "_decode_ms", timings)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline-only", action="store_true")
    parser.add_argument("--output", default="artifacts/glm-ocr-comparison.json")
    args = parser.parse_args()
    cases = [(lang, make_fixture(lang, text), text) for lang, text in
             [("en", "Enemy spotted at the entrance."), ("ja", "敵が入口にいます。"), ("ko", "입구에 적이 있어요.")]]
    cases.append(("vertical-ja", vertical_fixture(), "".join(COLUMNS)))
    cases.extend(("page-" + lang, fixture(lang), "".join(lines)) for lang, lines in SAMPLES.items())
    timings = defaultdict(float)
    engine = MultilingualOCR()
    profile_engine(engine, timings)
    rows = []
    session = requests.Session()
    session.trust_env = False
    if not args.baseline_only:
        info = session.post("http://127.0.0.1:11439/api/show", json={"model": "glm-ocr"}, timeout=10).json()
        Path("artifacts/glm-model-info.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    for run in range(3):
        for name, image, reference in cases:
            # Change one background pixel outside text, so repeated runs cannot
            # reuse an identical-image encoder cache. Both engines see this image.
            image = image.copy()
            pixel = image.getpixel((0, 0))
            image.putpixel((0, 0), tuple(max(0, channel - run - 1) for channel in pixel))
            frame = np.asarray(image)[:, :, ::-1].copy()
            stream = io.BytesIO()
            image.save(stream, format="PNG")
            encoded = base64.b64encode(stream.getvalue()).decode()
            for model in (["rapidocr"] if args.baseline_only else ["rapidocr", "glm-ocr"]):
                timings.clear()
                engine.cache.clear()
                start = time.perf_counter()
                extra = {}
                if model == "rapidocr":
                    readings = engine(frame, source="auto")
                    actual = "".join(r[1] for r in readings)
                    extra = {"stages": dict(timings), "metrics": engine.last_metrics.copy()}
                else:
                    parts, first = [], None
                    with session.post("http://127.0.0.1:11439/api/generate", json={
                        "model": "glm-ocr", "prompt": "Text Recognition:", "images": [encoded],
                        "stream": True, "keep_alive": "5m",
                        "options": {"temperature": 0, "num_predict": 2048, "num_ctx": 4096, "seed": 0}},
                        stream=True, timeout=(5, 180)) as response:
                        response.raise_for_status()
                        finished = False
                        for raw in response.iter_lines(chunk_size=1):
                            if not raw:
                                continue
                            event = json.loads(raw)
                            if event.get("error"):
                                raise RuntimeError(event["error"])
                            if event.get("response"):
                                first = first if first is not None else (time.perf_counter() - start) * 1000
                                parts.append(event["response"])
                            if event.get("done"):
                                extra = {key: event.get(key) for key in ("load_duration", "prompt_eval_duration", "eval_duration", "eval_count", "done_reason")}
                                extra["first_text_ms"] = first
                                finished = True
                        if not finished:
                            raise RuntimeError("Incomplete stream")
                    actual = "".join(parts)
                row = dict(case=name, model=model, run=run, elapsed_ms=(time.perf_counter() - start)*1000,
                           chars=len(normalized(reference)), errors=edit_distance(normalized(reference), normalized(actual)),
                           actual=actual, **extra)
                rows.append(row)
                Path(args.output).write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
                print(json.dumps({k: row[k] for k in ("case", "model", "run", "elapsed_ms", "errors")}), flush=True)
    session.close()


if __name__ == "__main__":
    main()
