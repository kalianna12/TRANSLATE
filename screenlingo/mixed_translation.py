"""Keep different source scripts separate for single-language MT endpoints."""
import re
from collections import OrderedDict

PATTERN = re.compile(r'[\u3040-\u30ff\u3400-\u9fff]+|[\uac00-\ud7af\u1100-\u11ff]+|[\u0400-\u052f]+|[A-Za-z]+|[^A-Za-z\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af\u1100-\u11ff\u0400-\u052f]+')


def segments(text):
    from .languages import script_of
    result = []
    for match in PATTERN.finditer(text):
        value = match.group()
        lang = script_of(value) if any(c.isalpha() for c in value) else None
        if lang == 'CJK':
            lang = 'auto'  # Han alone may be Chinese or Japanese; do not force either.
        result.append((value, lang))
    # Rejoin words of the same language across whitespace to preserve phrase context.
    merged = []
    for value, lang in result:
        if lang and len(merged) >= 2 and merged[-1][0].isspace() and merged[-2][1] == lang:
            space, _ = merged.pop()
            previous, _ = merged.pop()
            merged.append((previous + space + value, lang))
        else:
            merged.append((value, lang))
    return merged


def translate_mixed(client, texts, cancelled):
    plans = [segments(text) for text in texts]
    if not any(len({lang for _, lang in parts if lang}) >= 2 for parts in plans):
        return None
    groups = {}
    for parts in plans:
        for value, lang in parts:
            if lang:
                groups.setdefault(lang, []).append(value)
    source, cache = client.source, client.cache
    if not hasattr(client, 'mixed_caches'):
        client.mixed_caches = {}
    values, hits = {}, 0
    try:
        for lang, originals in groups.items():
            if cancelled():
                return []
            originals = list(dict.fromkeys(originals))
            if lang == 'auto' and client.target == 'zh-CN':
                # Some MT services auto-reverse Chinese -> English despite to=Chinese.
                # Han-only fragments in a mixed line are already readable Chinese.
                values.update({(lang, text): text for text in originals})
                continue
            client.source = lang
            client.cache = client.mixed_caches.setdefault(lang, OrderedDict())
            translated = client._translate(originals, cancelled)
            if cancelled():
                return []
            values.update({(lang, a): b for a, b in zip(originals, translated)})
            hits += client.cache_hits
    finally:
        client.source, client.cache = source, cache
        client.cache_hits = hits
    return [''.join(values[(lang, value)] if lang else value for value, lang in parts) for parts in plans]
