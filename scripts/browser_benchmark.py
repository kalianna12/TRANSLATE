"""Repeated selection-to-paint measurements in isolated Edge fixtures, no client cache."""
import argparse
import json
from pathlib import Path
import statistics
import subprocess
import sys
import numpy as np

parser = argparse.ArgumentParser()
parser.add_argument("--runs", type=int, default=5)
parser.add_argument("--source", choices=["auto", "ja"], default="ja")
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
rows = []
for i in range(args.runs):
    name = f"browser-{args.source}-final-{i + 1}.json"
    completed = subprocess.run([sys.executable, str(root / "scripts/browser_test.py"), "--warm", "--source", args.source,
                                "--output", name], cwd=root, capture_output=True, text=True, timeout=90)
    path = root / "artifacts" / name
    if completed.returncode or not path.exists():
        print(completed.stdout, completed.stderr)
        raise SystemExit("Browser integration failed; this run is not a latency pass.")
    result = json.loads(path.read_text(encoding="utf-8"))
    assert result["passed"] and result["paint_latency_ms"] is not None
    rows.append(result)
    print(i + 1, round(result["paint_latency_ms"], 1), "ms", flush=True)
latencies = [row["paint_latency_ms"] for row in rows]
summary = {"source": args.source, "runs": len(rows), "median_ms": statistics.median(latencies),
           "p95_ms": float(np.percentile(latencies, 95)), "under_500ms": sum(t <= 500 for t in latencies),
           "min_ms": min(latencies), "max_ms": max(latencies),
           "scope": "Model and Google connection prewarmed. Fresh process per sample; no local OCR/translation cache for fixture. Synthetic manga at 175% display scaling."}
(root / "artifacts" / f"browser-{args.source}-final-series.json").write_text(
    json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(summary, indent=2), flush=True)
