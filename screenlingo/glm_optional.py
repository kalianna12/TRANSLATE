"""Opt-in local Ollama OCR. Never downloads on import/startup or uses cloud APIs."""
import base64
import json
import threading
import cv2
import requests
from PySide6.QtCore import QThread, Signal

HOST = "http://127.0.0.1:11434"
MODEL = "glm-ocr"


def local_session():
    session = requests.Session()
    session.trust_env = False
    return session


def installed(session):
    response = session.get(HOST + "/api/tags", timeout=(2, 5))
    response.raise_for_status()
    return any(item.get("name", "").split(":")[0] == MODEL for item in response.json().get("models", []))


class ModelTask(QThread):
    message = Signal(str)
    ready = Signal(bool)

    def __init__(self, download=False, parent=None):
        super().__init__(parent)
        self.download = download

    def run(self):
        try:
            with local_session() as session:
                if installed(session):
                    self.message.emit("GLM-OCR 已安装，可选择使用。")
                    self.ready.emit(True)
                    return
                if not self.download:
                    self.message.emit("Ollama 已运行，GLM-OCR 尚未下载。")
                    self.ready.emit(False)
                    return
                with session.post(HOST + "/api/pull", json={"model": MODEL, "stream": True}, stream=True, timeout=(3, 15)) as response:
                    response.raise_for_status()
                    for line in response.iter_lines():
                        if self.isInterruptionRequested():
                            self.message.emit("下载已取消，下次可继续。")
                            return
                        if not line:
                            continue
                        event = json.loads(line)
                        if event.get("error"):
                            raise ValueError("download failed")
                        total, completed = event.get("total", 0), event.get("completed", 0)
                        if total:
                            self.message.emit(f"下载 GLM：{completed / 1048576:.0f} / {total / 1048576:.0f} MB")
                        else:
                            self.message.emit("正在下载并校验 GLM-OCR…")
                ready = installed(session)
                self.ready.emit(ready)
                self.message.emit("GLM-OCR 已安装。" if ready else "模型未就绪，请重试检查。")
        except (requests.RequestException, ValueError, KeyError, TypeError):
            self.ready.emit(False)
            self.message.emit("无法连接或下载。请确认本机 Ollama 已安装并运行（默认端口 11434），然后重试。")


class OllamaRecognizer:
    cancelled = staticmethod(lambda: False)

    def __call__(self, crops):
        readings = []
        with local_session() as session:
            for crop in crops:
                if self.cancelled():
                    return [], 0
                ok, data = cv2.imencode(".png", crop)
                if not ok:
                    raise RuntimeError("GLM image encoding failed")
                with session.post(HOST + "/api/generate", json={
                    "model": MODEL, "prompt": "Text Recognition:",
                    "images": [base64.b64encode(data).decode("ascii")], "stream": True,
                    "keep_alive": "1m", "options": {"temperature": 0, "num_predict": 1024, "num_ctx": 4096}},
                    stream=True, timeout=(3, 10)) as response:
                    response.raise_for_status()
                    chunks, done = [], False
                    for raw in response.iter_lines():
                        if self.cancelled():
                            return [], 0
                        if not raw:
                            continue
                        result = json.loads(raw)
                        if result.get("error") or result.get("done_reason") == "length":
                            raise RuntimeError("GLM recognition incomplete")
                        chunks.append(result.get("response", ""))
                        done = result.get("done", False)
                    if not done:
                        raise RuntimeError("GLM recognition incomplete")
                text = "".join(chunks).strip()
                readings.append((text, 1.0))
        return readings, 0


class GlmOCR:
    def __init__(self, status, cancelled):
        from .ocr import MultilingualOCR
        with local_session() as session:
            if not installed(session):
                raise RuntimeError("GLM-OCR not installed")
        # Keep the proven local detector and crop coordinates for overlay alignment.
        self.engine = MultilingualOCR(status, cancelled, parallel_auto=False)
        self.engine.engine.text_rec = OllamaRecognizer()
        self.last_metrics = {}

    def __call__(self, bgr, cancelled=lambda: False, source="auto", on_chunk=None):
        # The GLM recognizer is multilingual; route one inference per crop.
        with self.engine.lock:
            self.engine.engine.text_rec.cancelled = cancelled
            result = self.engine(bgr, cancelled, source="ja", on_chunk=on_chunk)
        self.last_metrics = self.engine.last_metrics
        return result


_engine = None
_lock = threading.Lock()


def get_glm(status, cancelled):
    global _engine
    with _lock:
        if _engine is None:
            _engine = GlmOCR(status, cancelled)
    return _engine
