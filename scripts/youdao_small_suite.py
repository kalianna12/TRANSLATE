"""Three short automatic-language tests through the application's real adapter."""
import getpass
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import time

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from screenlingo.core import Translator, TranslationError


class LimitedSession(requests.Session):
    def __init__(self, path):
        super().__init__()
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.detected = ""
        with sqlite3.connect(self.path) as db:
            db.execute("CREATE TABLE IF NOT EXISTS attempts (stamp REAL, chars INTEGER, digest TEXT)")

    def request(self, method, url, **kwargs):
        if method != "POST" or url != "https://openapi.youdao.com/api":
            raise TranslationError("测试只允许有道官方文本接口")
        text = kwargs["data"]["q"]
        digest = hashlib.sha256(text.encode()).hexdigest()
        with sqlite3.connect(self.path, timeout=10) as db:
            db.execute("BEGIN IMMEDIATE")
            count, chars, last = db.execute("SELECT COUNT(*), COALESCE(SUM(chars),0), MAX(stamp) FROM attempts").fetchone()
            if count >= 3 or chars + len(text) > 500:
                raise TranslationError("本轮测试预算已用完（最多3次、500字符）")
            if last and time.time() - last < 3:
                raise TranslationError("测试请求至少间隔3秒")
            if db.execute("SELECT 1 FROM attempts WHERE digest=?", (digest,)).fetchone():
                raise TranslationError("重复素材已拦截，不重复扣费")
            db.execute("INSERT INTO attempts VALUES (?,?,?)", (time.time(), len(text), digest))
        response = super().request(method, url, allow_redirects=False, **kwargs)
        if response.status_code != 200:
            raise TranslationError("有道 HTTP 错误 " + str(response.status_code))
        try:
            self.detected = response.json().get("l", "")
        except (ValueError, AttributeError):
            self.detected = ""
        return response


def main():
    if sys.argv[1:] != ["--live"]:
        print("Add --live to send up to three short samples")
        return
    appid = input("Application ID: ").strip()
    secret = getpass.getpass("Application secret: ")
    path = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "ScreenLingo/youdao-test-budget.sqlite3"
    session = LimitedSession(path)
    translator = Translator(provider="youdao", source="auto", app_id=appid, api_key=secret, session=session)
    rows = []
    try:
        for language, text in [("ja", "思えば高一のとき三者面談でいきなり東大を目指しだして以来"),
                               ("en", "Enemy spotted at the entrance."), ("ko", "입구에 적이 있어요.")]:
            started = time.perf_counter()
            translated = translator.translate([text])
            row = dict(language=language, source=text, translated=translated, detected=session.detected,
                       elapsed_ms=(time.perf_counter() - started) * 1000, chars=len(text))
            rows.append(row)
            Path("artifacts/youdao-small-suite.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(row, ensure_ascii=True), flush=True)
            time.sleep(3)
    except TranslationError as exc:
        print(str(exc), flush=True)
        return 1
    finally:
        translator.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
