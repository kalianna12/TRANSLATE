"""Actual user-image OCR comparison, loopback-only GLM; never calls translation APIs."""
import argparse
import base64
import hashlib
import io
import json
from pathlib import Path
import sys
import time

import numpy as np
from PIL import Image
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from screenlingo.ocr import MultilingualOCR
from screenlingo.core import make_blocks
from glm_ocr_benchmark import Timed, profile_engine
from collections import defaultdict


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("folder", type=Path)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--output", type=Path, default=Path("artifacts/real-image-ocr"))
    parser.add_argument("--repeat-penalty", type=float, default=1.0)
    parser.add_argument("--models", nargs="+", default=["rapid-auto", "rapid-fixed", "glm-full-image"])
    args = parser.parse_args()
    files = sorted(p for p in args.folder.iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png"))
    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.trust_env = False
    engine = MultilingualOCR()
    stages = defaultdict(float)
    profile_engine(engine, stages)
    rows = []
    for run in range(args.runs):
        for path in files:
            language = "ko" if path.stem.startswith("han") else "ja" if path.stem.startswith("ri") else "en"
            original = Image.open(path).convert("RGB")
            image = original.copy()
            pixel = image.getpixel((0, 0))
            image.putpixel((0, 0), tuple(max(0, c - run - 1) for c in pixel))
            bgr = np.asarray(image)[:, :, ::-1].copy()
            stream = io.BytesIO()
            image.save(stream, format="PNG")
            encoded = base64.b64encode(stream.getvalue()).decode("ascii")
            for model in args.models:
                row = dict(file=path.name, sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                           dimensions=image.size, model=model, run=run, repeat_penalty=args.repeat_penalty)
                engine.cache.clear()
                stages.clear()
                start = time.perf_counter()
                chunks, first = [], None
                try:
                    if model.startswith("rapid"):
                        result = engine(bgr, source="auto" if model == "rapid-auto" else language)
                        # Match application grouping/read-order for upright Japanese columns.
                        blocks = make_blocks(result, bgr[:, :, ::-1])
                        actual = "\n".join(block.source for block in blocks)
                        row.update(blocks=[dict(x=b.x, y=b.y, width=b.width, height=b.height, source=b.source) for b in blocks],
                                   stages=dict(stages), metrics=engine.last_metrics.copy())
                    else:
                        chunks, first = [], None
                        done = False
                        with session.post("http://127.0.0.1:11439/api/generate", json={
                            "model": "glm-ocr", "prompt": "Text Recognition:", "images": [encoded],
                            "stream": True, "keep_alive": "5m",
                            "options": {"temperature": 0, "num_predict": 3072, "num_ctx": 8192, "seed": 0,
                                        "repeat_penalty": args.repeat_penalty}},
                            stream=True, timeout=(5, 90)) as response:
                            response.raise_for_status()
                            for raw in response.iter_lines(chunk_size=1):
                                if time.perf_counter() - start > 120:
                                    raise TimeoutError("Image exceeded 120 second test limit")
                                if not raw:
                                    continue
                                event = json.loads(raw)
                                if event.get("error"):
                                    raise RuntimeError(event["error"])
                                if event.get("response"):
                                    if first is None:
                                        first = (time.perf_counter() - start) * 1000
                                    chunks.append(event["response"])
                                if event.get("done"):
                                    done = True
                                    row.update({key: event.get(key) for key in ("load_duration", "prompt_eval_duration", "eval_duration", "prompt_eval_count", "eval_count", "done_reason")})
                        if not done:
                            raise RuntimeError("Incomplete response stream")
                        actual = "".join(chunks)
                        row["first_text_ms"] = first
                        row["complete"] = row.get("done_reason") != "length"
                    row["elapsed_ms"] = (time.perf_counter() - start) * 1000
                    row["text"] = actual
                    (output / f"{path.stem}-{model}-{run}.txt").write_text(actual, encoding="utf-8")
                    if model == "glm-full-image":
                        row["loaded_models"] = session.get("http://127.0.0.1:11439/api/ps", timeout=5).json()
                except Exception as exc:
                    row.update(elapsed_ms=(time.perf_counter() - start) * 1000, error=type(exc).__name__ + ": " + str(exc))
                    if model == "glm-full-image":
                        row.update(text="".join(chunks), first_text_ms=first, complete=False)
                rows.append(row)
                (output / "results.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
                print(json.dumps({key: row.get(key) for key in ("file", "model", "run", "elapsed_ms", "first_text_ms", "complete", "error")}), flush=True)
    session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
