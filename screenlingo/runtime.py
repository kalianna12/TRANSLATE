"""Keep models, translation cache and HTTP connections warm across region selections."""
import threading
from .core import Translator

_lock = threading.RLock()
_translator = None
_key = None


def warm_translator(options):
    # Do not replace a translator selected by the user while OCR was warming up.
    key = tuple(options.get(k, "") for k in ("target", "provider", "api_key", "proxy", "source", "app_id"))
    with _lock:
        if _key is None or _key == key:
            return get_translator(options).warm_connection()


def get_translator(options):
    global _translator, _key
    key = tuple(options.get(k, "") for k in ("target", "provider", "api_key", "proxy", "source", "app_id"))
    with _lock:
        if key != _key or _translator is None:
            if _translator:
                _translator.close()
            _translator = Translator(target=options["target"], provider=options["provider"],
                                     api_key=options.get("api_key", ""), proxy=options.get("proxy", ""),
                                     source=options.get("source", "auto"), app_id=options.get("app_id", ""))
            _key = key
        return _translator


def close_runtime():
    global _translator, _key
    with _lock:
        if _translator:
            _translator.close()
        _translator, _key = None, None
