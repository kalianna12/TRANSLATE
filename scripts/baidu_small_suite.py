"""Explicit live comparison: two images and three short texts, no retries."""
import getpass
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image
from benchmark import make_fixture, normalized, edit_distance
from screenlingo.baidu_probe import BaiduProbe, TestBudget, ProbeError


def main():
    if sys.argv[1:] != ["--live"]:
        print("Requires --live: uploads 2 synthetic images and 3 short texts")
        return
    appid = input("APPID: ").strip()
    secret = getpass.getpass("Secret: ")
    budget = TestBudget(Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "ScreenLingo/baidu-test-budget.sqlite3")
    client = BaiduProbe(appid, secret, budget)
    output = Path("artifacts/baidu-small-suite.json")
    samples = [("en", "Enemy spotted at the entrance."), ("ko", "입구에 적이 있어요.")]
    rows = []
    try:
        for lang, text in samples:
            im = make_fixture(lang, text, dark=False)
            padded = Image.new("RGB", (im.width, max(im.height, (im.width + 2) // 3)), (244, 246, 249))
            padded.paste(im, (0, 0))
            path = Path("artifacts") / ("baidu-" + lang + ".png")
            padded.save(path)
            result = client.image(path, "auto")
            detected = result["result"]["data"]["sumSrc"]
            result.update(expected=text, normalized_errors=edit_distance(normalized(text), normalized(detected)))
            rows.append(result)
            output.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(result, ensure_ascii=True), flush=True)
            time.sleep(5)
        for lang, text in [("jp", "思えば高一のとき三者面談でいきなり東大を目指しだして以来"), *samples]:
            result = client.text(text, lang if lang != "ko" else "kor")
            rows.append(result)
            output.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(result, ensure_ascii=True), flush=True)
            time.sleep(3)
    except ProbeError as exc:
        print(str(exc))
    finally:
        client.session.close()


if __name__ == "__main__":
    main()
