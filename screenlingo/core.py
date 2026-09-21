from collections import OrderedDict
from dataclasses import dataclass
import html
import os
import threading
import hashlib
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed, CancelledError
from itertools import groupby

import numpy as np
import cv2
import requests

from .languages import script_of


LANGUAGES = {
    "简体中文": "zh-CN", "繁體中文": "zh-TW", "English": "en",
    "日本語": "ja", "한국어": "ko", "Français": "fr", "Deutsch": "de",
    "Español": "es", "Português": "pt", "Italiano": "it",
    "Русский": "ru", "Tiếng Việt": "vi", "ไทย": "th", "العربية": "ar",
}


@dataclass(frozen=True)
class Region:
    left: int
    top: int
    width: int
    height: int

    def as_dict(self):
        return vars(self).copy()


@dataclass
class TextBlock:
    x: int
    y: int
    width: int
    height: int
    source: str
    translated: str = ""
    background: tuple = (245, 245, 245)
    foreground: tuple = (20, 20, 20)


def frame_changed(previous, current, threshold=2.0):
    """Ignore cursor-sized noise but catch local text changes on a large screen."""
    if previous is None or previous.shape != current.shape:
        return True
    # Exact integer sums avoid two full-frame int16 copies and a float64 mean image.
    # Reduce contiguous columns first, then the much smaller row array.
    delta = cv2.absdiff(previous, current)
    height, width = current.shape[:2]
    if not height or not width:
        return False
    xs, ys = np.arange(0, width, 64), np.arange(0, height, 64)
    totals = np.add.reduceat(np.add.reduceat(delta, xs, axis=1, dtype=np.uint32),
                             ys, axis=0, dtype=np.uint32).sum(axis=2)
    areas = np.diff(np.append(ys, height))[:, None] * np.diff(np.append(xs, width))[None, :] * 3
    return bool(np.any(totals > threshold * areas))


def make_blocks(result, rgb, reading_layout="standard"):
    blocks = []
    height, width = rgb.shape[:2]
    for points, text, confidence in result or []:
        if float(confidence) < 0.55 or not str(text).strip():
            continue
        points = np.asarray(points)
        x1 = max(0, int(points[:, 0].min()) - 2)
        y1 = max(0, int(points[:, 1].min()) - 2)
        x2 = min(width, int(np.ceil(points[:, 0].max())) + 2)
        y2 = min(height, int(np.ceil(points[:, 1].max())) + 2)
        if x2 <= x1 or y2 <= y1:
            continue
        crop = rgb[y1:y2, x1:x2]
        edges = np.concatenate([crop[0], crop[-1], crop[:, 0], crop[:, -1]])
        bg = tuple(int(v) for v in np.median(edges, axis=0))
        luminance = sum(v * w for v, w in zip(bg, (0.2126, 0.7152, 0.0722)))
        fg = (24, 28, 36) if luminance > 145 else (248, 250, 252)
        blocks.append(TextBlock(x1, y1, x2 - x1, y2 - y1, str(text), background=bg, foreground=fg))
    return group_vertical_paragraphs(blocks, manga=reading_layout == "manga")


def group_vertical_paragraphs(blocks, manga=False):
    """Translate adjacent Japanese vertical columns in reading order as one paragraph."""
    vertical = [b for b in blocks if b.height >= b.width * 1.8 and script_of(b.source) in ("ja", "CJK")]
    if len(vertical) < 2:
        if manga:
            from .manga import reading_order
            return reading_order(blocks)
        return blocks
    remaining = [b for b in blocks if b not in vertical]
    # Cluster spatially before sorting. Columns from another panel at the same X
    # must not interrupt the reading order of a bubble above it.
    groups = []
    while vertical:
        group = [vertical.pop(0)]
        scan = 0
        while scan < len(group):
            prior = group[scan]
            for block in vertical[:]:
                left, right = sorted((prior, block), key=lambda b: b.x)
                overlap = min(prior.y + prior.height, block.y + block.height) - max(prior.y, block.y)
                comparable = min(prior.width, block.width) >= max(prior.width, block.width) * 0.6
                if (comparable and (-min(prior.width, block.width) * .2 if manga else 0) <= right.x - left.x - left.width <= max(prior.width, block.width) * (1.0 if manga else 1.6)
                        and abs(prior.y - block.y) <= max(prior.width, block.width) * 1.5
                        and overlap >= min(prior.height, block.height) * 0.4):
                    group.append(block)
                    vertical.remove(block)
            scan += 1
        groups.append(sorted(group, key=lambda b: -b.x))
    groups.sort(key=lambda group: (min(b.y for b in group), -max(b.x for b in group)))
    for group in groups:
        if len(group) == 1:
            remaining.extend(group)
            continue
        left, top = min(b.x for b in group), min(b.y for b in group)
        right, bottom = max(b.x + b.width for b in group), max(b.y + b.height for b in group)
        bg = tuple(int(v) for v in np.median([b.background for b in group], axis=0))
        luminance = sum(v * w for v, w in zip(bg, (0.2126, 0.7152, 0.0722)))
        fg = (24, 28, 36) if luminance > 145 else (248, 250, 252)
        remaining.append(TextBlock(left, top, right - left, bottom - top, "".join(b.source for b in group),
                                   background=bg, foreground=fg))
    if manga:
        from .manga import reading_order
        return reading_order(remaining)
    return remaining


class TranslationError(RuntimeError):
    def __init__(self, message, retry_after=0):
        super().__init__(message)
        self.retry_after = retry_after


class Translator:
    """Bounded LRU cache. Credentials live only in memory / environment."""
    _cooldowns = {}
    _cooldown_lock = threading.Lock()

    def __init__(self, target="zh-CN", provider="free", api_key="", proxy="", session=None, source="auto", app_id="", reasoning_effort="none", reading_layout="standard"):
        self.target = target
        self.source = source
        self.provider = provider
        prefix = {"baidu": "BAIDU", "youdao": "YOUDAO", "deepseek": "DEEPSEEK"}.get(provider, "GOOGLE_TRANSLATE")
        self.reasoning_effort = reasoning_effort
        self.reading_layout = reading_layout
        self.ai_context = []
        self.last_usage = {}
        self.api_key = api_key or os.getenv(prefix + "_API_KEY", "")
        self.app_id = app_id or os.getenv(prefix + "_APP_ID", "")
        self.session = session or requests.Session()
        self.custom_session = session is not None
        if not self.custom_session:
            self.adapter = requests.adapters.HTTPAdapter(pool_connections=4, pool_maxsize=3, pool_block=True)
            self.session.mount("https://", self.adapter)
        self.pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="google")
        self.local = threading.local()
        self.sessions = []
        self.lock = threading.Lock()
        if proxy:
            self.session.proxies.update({"http": proxy, "https": proxy})
        self.cache = OrderedDict()
        self.network_calls = 0
        self.cache_hits = 0
        self.operation_lock = threading.RLock()

    def close(self):
        with self.operation_lock:
            self.pool.shutdown(wait=True, cancel_futures=True)
            for session in self.sessions:
                session.close()
            self.session.close()

    def warm_connection(self):
        """Open the Google connection with public boilerplate, never captured text."""
        if self.provider != "free":
            return
        with self.operation_lock:
            calls_before = self.network_calls
            try:
                self._request("GET", "https://translate.googleapis.com/translate_a/single",
                              params={"client": "gtx", "sl": "en", "tl": "zh-CN", "dt": "t", "q": "Ready"},
                              timeout=(2, 2))
            except TranslationError:
                return False  # Warm only one shared connection and respect service cooldowns.
            finally:
                self.network_calls = calls_before
            return True

    def translate(self, texts, cancelled=lambda: False):
        with self.operation_lock:
            return self._translate(texts, cancelled)

    def _translate(self, texts, cancelled):
        if self.provider == "deepseek":
            from .ai_translation import translate
            return translate(self, texts, cancelled)
        self.cache_hits = sum(t in self.cache for t in texts)
        missing = list(dict.fromkeys(t for t in texts if t not in self.cache))
        # Do not ask Google to infer one source language for mixed Japanese/Korean chat.
        if self.provider == "free":
            missing.sort(key=script_of)
        for start in range(0, len(missing), 24):
            if cancelled():
                return []
            batch = missing[start:start + 24]
            if self.provider == "cloud":
                values = self._cloud(batch)
            elif self.provider in ("baidu", "youdao"):
                values = self._official_batch(batch, cancelled)
            else:
                groups = [batch] if self.source != "auto" else [list(group) for _, group in groupby(batch, key=script_of)]
                jobs = [chunk for group in groups for chunk in self._chunks(group)]
                if len(jobs) > 1 and not self.custom_session:
                    futures = {self.pool.submit(self._free, group, cancelled): group for group in jobs}
                    error = None
                    for future in as_completed(futures):
                        try:
                            translated = future.result()
                            if len(translated) != len(futures[future]):
                                if cancelled():
                                    continue
                                raise TranslationError("翻译服务返回内容不完整，请稍后重试。")
                            # Keep successful chunks if another request is rate-limited.
                            for key, value in zip(futures[future], translated):
                                self.cache[key] = value
                        except CancelledError:
                            pass
                        except Exception as exc:
                            error = error or exc
                            for pending in futures:
                                pending.cancel()
                    if cancelled():
                        return []
                    if error:
                        while len(self.cache) > 4096:
                            self.cache.popitem(last=False)
                        raise error
                    values = [self.cache[t] for t in batch]
                else:
                    values = [value for group in jobs for value in self._free(group, cancelled)]
            if len(values) != len(batch):
                raise TranslationError("翻译服务返回内容不完整，请稍后重试。")
            for key, value in zip(batch, values):
                self.cache[key] = value
        result = [self.cache[t] for t in texts]
        for t in texts:
            self.cache.move_to_end(t)
        while len(self.cache) > 4096:
            self.cache.popitem(last=False)
        return result

    @staticmethod
    def _chunks(texts):
        """Keep requests small enough for long pages without falling back to N round trips."""
        current, size = [], 0
        for text in texts:
            length = len(text.encode("utf-8")) + 1
            if current and (size + length > 1200 or len(current) >= 4):
                yield current
                current, size = [], 0
            current.append(text)
            size += length
        if current:
            yield current

    def _http_session(self):
        session = self.session
        if threading.current_thread().name.startswith("google") and not self.custom_session:
            if not hasattr(self.local, "session"):
                self.local.session = requests.Session()
                self.local.session.proxies.update(self.session.proxies)
                self.local.session.mount("https://", self.adapter)
                with self.lock:
                    self.sessions.append(self.local.session)
            session = self.local.session
        return session

    def _request(self, method, url, **kwargs):
        from urllib.parse import urlsplit
        host = urlsplit(url).netloc
        with self._cooldown_lock:
            remaining = self._cooldowns.get(host, 0) - time.monotonic()
        if remaining > 0:
            raise TranslationError("翻译服务正在限流等待中，请稍后重试。", retry_after=remaining)
        with self.lock:
            self.network_calls += 1
        session = self._http_session()
        try:
            response = session.request(method, url, timeout=kwargs.pop("timeout", (4, 10)), **kwargs)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            code = getattr(getattr(exc, "response", None), "status_code", None)
            # Never expose request URLs: official API keys appear in query parameters.
            if isinstance(exc, requests.Timeout):
                message = "翻译请求超时，请关闭思考、缩小区域或检查网络。"
            elif code == 402:
                message = "翻译账户余额不足（HTTP 402），请检查账户余额。"
            elif code in (400, 422):
                message = f"翻译请求参数被拒绝（HTTP {code}），请检查模型及推理设置。"
            elif code in (500, 503):
                message = f"翻译服务暂时异常（HTTP {code}），请稍后重试。"
            elif code in (401, 403):
                message = "翻译服务拒绝访问，请检查密钥、API 是否启用和账户配额。"
            elif code == 429:
                message = "翻译请求过于频繁，请增大刷新间隔或检查服务配额。"
                raw = getattr(exc.response, "headers", {}).get("Retry-After", "60")
                try:
                    wait = float(raw)
                except (TypeError, ValueError):
                    try:
                        from email.utils import parsedate_to_datetime
                        wait = parsedate_to_datetime(raw).timestamp() - time.time()
                    except (TypeError, ValueError, OverflowError):
                        wait = 60
                import math
                wait = max(1, wait) if math.isfinite(wait) else 60
                with self._cooldown_lock:
                    self._cooldowns[host] = max(self._cooldowns.get(host, 0), time.monotonic() + wait)
                raise TranslationError(message, retry_after=wait) from None
            else:
                message = "无法连接翻译服务，请检查网络或代理设置。"
            raise TranslationError(message) from None
        except ValueError:
            raise TranslationError("翻译服务返回了无法解析的响应。") from None

    def _cloud(self, texts):
        if not self.api_key:
            raise TranslationError("官方 API 模式需要填写 Google Cloud Translation API Key。")
        data = self._request("POST", "https://translation.googleapis.com/language/translate/v2",
                             params={"key": self.api_key},
                             json={"q": texts, "target": self.target, "format": "text",
                                   **({"source": self.source} if self.source != "auto" else {})})
        try:
            return [html.unescape(t["translatedText"]) for t in data["data"]["translations"]]
        except (KeyError, TypeError):
            raise TranslationError("Google 官方 API 响应格式异常。") from None

    def _free_one(self, text):
        data = self._request("GET", "https://translate.googleapis.com/translate_a/single",
                             params={"client": "gtx", "sl": self.source, "tl": self.target,
                                     "dt": "t", "q": text})
        try:
            return "".join(str(segment[0]) for segment in data[0] if segment[0])
        except (IndexError, TypeError):
            raise TranslationError("Google 试用接口响应发生变化，请改用官方 API。") from None

    def _free(self, texts, cancelled):
        # Joining lines reduces network round trips. Validate alignment before mapping boxes.
        if len(texts) == 1:
            return [self._free_one(texts[0])]
        joined = "\n".join(texts)
        if len(joined) < 3500 and all("\n" not in text for text in texts):
            result = self._free_one(joined).split("\n")
            if len(result) == len(texts) and all(t.strip() for t in result):
                return result
        result = []
        for text in texts:
            if cancelled():
                return []
            result.append(self._free_one(text))
        return result

    def _official_one(self, text):
        if not self.app_id or not self.api_key:
            raise TranslationError("此翻译源需要应用 ID 和密钥，请在首选项中填写。")
        salt = uuid.uuid4().hex
        if self.provider == "baidu":
            mapping = {"auto": "auto", "zh-CN": "zh", "zh-TW": "cht", "ja": "jp", "ko": "kor",
                       "fr": "fra", "es": "spa", "de": "de", "ru": "ru", "vi": "vie", "ar": "ara", "it": "it"}
            data = self._request("POST", "https://fanyi-api.baidu.com/api/trans/vip/translate", data={
                "q": text, "from": mapping.get(self.source, self.source), "to": mapping.get(self.target, self.target),
                "appid": self.app_id, "salt": salt,
                "sign": hashlib.md5((self.app_id + text + salt + self.api_key).encode("utf-8")).hexdigest()})
            if "error_code" in data:
                raise TranslationError(f"百度翻译错误 {data['error_code']}，请检查语言、凭据及配额。")
            try:
                return "\n".join(item["dst"] for item in data["trans_result"])
            except (KeyError, TypeError):
                raise TranslationError("百度翻译响应格式异常。") from None
        mapping = {"zh-CN": "zh-CHS", "zh-TW": "zh-CHT"}
        current = str(int(time.time()))
        digest_input = text if len(text) <= 20 else text[:10] + str(len(text)) + text[-10:]
        data = self._request("POST", "https://openapi.youdao.com/api", data={
            "q": text, "from": mapping.get(self.source, self.source), "to": mapping.get(self.target, self.target),
            "appKey": self.app_id, "salt": salt, "curtime": current, "signType": "v3",
            "sign": hashlib.sha256((self.app_id + digest_input + salt + current + self.api_key).encode("utf-8")).hexdigest()})
        if str(data.get("errorCode")) != "0":
            raise TranslationError(f"有道翻译错误 {data.get('errorCode', '未知')}，请检查语言、凭据及配额。")
        try:
            return "\n".join(data["translation"])
        except (KeyError, TypeError):
            raise TranslationError("有道翻译响应格式异常。") from None

    def _official_batch(self, texts, cancelled):
        if len(texts) == 1:
            return [self._official_one(texts[0])]
        joined = "\n".join(texts)
        if len(joined.encode("utf-8")) < 5000 and all("\n" not in t for t in texts):
            values = self._official_one(joined).split("\n")
            if len(values) == len(texts):
                return values
        result = []
        for text in texts:
            if cancelled():
                return []
            result.append(self._official_one(text))
        return result
