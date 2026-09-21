"""Small real-image regions using the application's GLM recognizer, local only."""
import json
from pathlib import Path
import sys
import time
import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from screenlingo import glm_optional


def main():
    glm_optional.HOST = "http://127.0.0.1:11439"
    output = Path("artifacts/real-image-crops")
    output.mkdir(exist_ok=True)
    source = json.loads(Path("artifacts/real-image-ocr/results.json").read_text(encoding="utf-8"))
    rows = []
    for filename, index in [("han1.jpg", 2), ("ri1.jpg", 0), ("ying2.jpg", 1)]:
        row = next(r for r in source if r["file"] == filename and r["model"] == "rapid-fixed")
        b = row["blocks"][index]
        im = Image.open(Path("testimage") / filename).convert("RGB")
        box = (max(0, b["x"] - 4), max(0, b["y"] - 4),
               min(im.width, b["x"] + b["width"] + 4), min(im.height, b["y"] + b["height"] + 4))
        crop = im.crop(box)
        crop.save(output / filename.replace(".jpg", ".png"))
        result = dict(file=filename, box=box, rapid_text=b["source"])
        start = time.perf_counter()
        try:
            readings, _ = glm_optional.OllamaRecognizer()([np.asarray(crop)[:, :, ::-1].copy()])
            result["readings"] = readings
        except Exception as exc:
            result["error"] = type(exc).__name__ + ": " + str(exc)
        result["elapsed_ms"] = (time.perf_counter() - start) * 1000
        rows.append(result)
        (output / "results.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=True), flush=True)


if __name__ == "__main__":
    main()
