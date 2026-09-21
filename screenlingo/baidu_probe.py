"""Small, quota-bounded Baidu experiments; deliberately separate from realtime polling."""
import hashlib
import json
import sqlite3
import time
import uuid
from pathlib import Path

import cv2
import numpy as np
import requests


class ProbeError(RuntimeError):
    pass


class TestBudget:
    """Persist attempts BEFORE sending, including failures. Cross-process atomic."""
    LIMITS = {"image": 100, "text": 100000}
    INTERVALS = {"image": 5.0, "text": 3.0}

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as db:
            db.execute("CREATE TABLE IF NOT EXISTS attempts (month TEXT, kind TEXT, units INTEGER, stamp REAL, digest TEXT)")

    def reserve(self, kind, units, digest, now=None):
        if kind not in self.LIMITS or not isinstance(units, int) or units < 1:
            raise ProbeError("Invalid budget request")
        if kind == "image" and units != 1:
            raise ProbeError("One image per request")
        now = time.time() if now is None else now
        month = time.strftime("%Y-%m", time.localtime(now))
        with sqlite3.connect(self.path, timeout=10) as db:
            db.execute("BEGIN IMMEDIATE")
            used = db.execute("SELECT COALESCE(SUM(units),0) FROM attempts WHERE month=? AND kind=?", (month, kind)).fetchone()[0]
            if used + units > self.LIMITS[kind]:
                raise ProbeError("Monthly test budget exhausted")
            if db.execute("SELECT 1 FROM attempts WHERE month=? AND kind=? AND digest=?", (month, kind, digest)).fetchone():
                raise ProbeError("Already attempted this sample this month; duplicate blocked")
            last = db.execute("SELECT MAX(stamp) FROM attempts").fetchone()[0]
            if last is not None and now - last < self.INTERVALS[kind]:
                raise ProbeError("Request interval too short; try later")
            db.execute("INSERT INTO attempts VALUES (?,?,?,?,?)", (month, kind, units, now, digest))
        return used + units


def image_payload(raw, appid, secret, source="auto", target="zh", salt=None):
    salt = salt or uuid.uuid4().hex
    sign = hashlib.md5((appid + hashlib.md5(raw).hexdigest() + salt + "APICUIDmac" + secret).encode()).hexdigest()
    return dict(appid=appid, salt=salt, sign=sign, cuid="APICUID", mac="mac",
                version="3", paste="0", **{"from": source, "to": target})


class BaiduProbe:
    def __init__(self, appid, secret, budget, session=None):
        if not appid or not secret:
            raise ProbeError("APPID and developer secret are required")
        self.appid, self.secret, self.budget = appid, secret, budget
        self.session = session or requests.Session()

    def _send(self, kind, data, units, fingerprint, files=None):
        digest = hashlib.sha256(fingerprint).hexdigest()
        used = self.budget.reserve(kind, units, digest)
        endpoint = "sdk/picture" if kind == "image" else "vip/translate"
        start = time.perf_counter()
        try:
            response = self.session.post("https://fanyi-api.baidu.com/api/trans/" + endpoint,
                                         data=data, files=files, timeout=(5, 20), allow_redirects=False)
            if response.status_code != 200:
                raise ProbeError("Baidu HTTP status " + str(response.status_code))
            result = response.json()
        except (requests.RequestException, ValueError):
            raise ProbeError("Baidu connection or response failed; attempt counted, no retry") from None
        if not isinstance(result, dict):
            raise ProbeError("Invalid Baidu response")
        code = str(result.get("error_code", "0"))
        if code != "0":
            # Never echo server messages which could contain submitted credentials.
            raise ProbeError("Baidu API error " + (code if code.isdigit() else "unknown"))
        return {"elapsed_ms": (time.perf_counter() - start) * 1000,
                "monthly_test_units": used, "kind": kind, "result": result}

    def image(self, path, source="auto", target="zh"):
        path = Path(path)
        if path.suffix not in (".png", ".jpg", ".jpeg"):
            raise ProbeError("Use lowercase .png/.jpg/.jpeg")
        raw = path.read_bytes()
        if len(raw) > 4 * 1024 * 1024:
            raise ProbeError("Image exceeds 4 MB")
        pixels = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        if pixels is None:
            raise ProbeError("Invalid image")
        h, w = pixels.shape[:2]
        if min(h, w) < 30 or max(h, w) > 4096 or max(h, w) > 3 * min(h, w):
            raise ProbeError("Image dimensions outside Baidu limits")
        data = image_payload(raw, self.appid, self.secret, source, target)
        return self._send("image", data, 1, source.encode() + b":" + target.encode() + b":" + raw,
                          {"image": ("sample" + path.suffix, raw, "image/png" if path.suffix == ".png" else "image/jpeg")})

    def text(self, text, source="auto", target="zh"):
        if not text.strip() or len(text) > 2000:
            raise ProbeError("Test text must contain 1..2000 characters")
        salt = uuid.uuid4().hex
        data = dict(q=text, appid=self.appid, salt=salt,
                    sign=hashlib.md5((self.appid + text + salt + self.secret).encode()).hexdigest(),
                    **{"from": source, "to": target})
        return self._send("text", data, len(text), json.dumps([source, target, text]).encode())
