"""Pinned upstream weights, downloaded atomically and verified before loading."""
import hashlib
from pathlib import Path

import requests


MODEL_DIR = Path(__file__).resolve().parents[1] / "models"
BASE_URL = "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.9.2/onnx/PP-OCRv5/rec/"
MODELS = {
    "russian": ("cyrillic_PP-OCRv5_rec_mobile.onnx", "90f761b4bfcce0c8c561c0cb5c887b0971d3ec01c32164bdf7374a35b0982711"),
    "multilingual": ("ch_PP-OCRv5_rec_mobile.onnx", "5825fc7ebf84ae7a412be049820b4d86d77620f204a041697b0494669b1742c5"),
    "korean": ("korean_PP-OCRv5_rec_mobile.onnx", "cd6e2ea50f6943ca7271eb8c56a877a5a90720b7047fe9c41a2e541a25773c9b"),
}


def ensure_models(status=lambda message: None, cancelled=lambda: False):
    MODEL_DIR.mkdir(exist_ok=True)
    paths = {}
    for name, (filename, digest) in MODELS.items():
        path = MODEL_DIR / filename
        if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == digest:
            paths[name] = str(path)
            continue
        status(f"首次使用：正在下载 {filename}，请稍候…")
        temp = path.with_suffix(".download")
        try:
            with requests.get(BASE_URL + filename, stream=True, timeout=(10, 30)) as response:
                response.raise_for_status()
                sha = hashlib.sha256()
                with temp.open("wb") as stream:
                    for chunk in response.iter_content(1024 * 256):
                        if cancelled():
                            raise InterruptedError("模型下载已取消")
                        stream.write(chunk)
                        sha.update(chunk)
            if sha.hexdigest() != digest:
                raise RuntimeError("OCR 模型校验失败，请重试下载。")
            temp.replace(path)
        finally:
            temp.unlink(missing_ok=True)
        paths[name] = str(path)
    return paths


if __name__ == "__main__":
    print(ensure_models(status=print))
