"""Optional CUDA runtime bootstrap; call before importing RapidOCR/ONNX Runtime."""
import logging
from pathlib import Path
import sys

_prepared = False


def prepare():
    global _prepared
    if _prepared:
        return
    _prepared = True
    if getattr(sys, "frozen", False) or "onnxruntime" in sys.modules:
        return
    root = Path(__file__).resolve().parents[1] / ".gpu-runtime"
    if not (root / "onnxruntime" / "__init__.py").is_file():
        return
    sys.path.insert(0, str(root))
    try:
        import onnxruntime as ort
        ort.preload_dlls(directory="")
        ort.set_default_logger_severity(3)
    except Exception:
        logging.getLogger(__name__).exception("Optional CUDA runtime failed to load")
        sys.path.remove(str(root))
        # A failed native import must not poison the CPU runtime import.
        for name in list(sys.modules):
            if name == "onnxruntime" or name.startswith("onnxruntime."):
                del sys.modules[name]


def available():
    import onnxruntime as ort
    return "CUDAExecutionProvider" in ort.get_available_providers()
