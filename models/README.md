# OCR weights

`python -m screenlingo.models` downloads two pinned RapidAI ONNX models and verifies SHA-256 before use. Large `.onnx` files are not committed to version control.

- `ch_PP-OCRv5_rec_mobile.onnx`: Chinese, English, Japanese recognition.
- `korean_PP-OCRv5_rec_mobile.onnx`: Korean recognition.

The detector is bundled with the pinned `rapidocr-onnxruntime` package. Weights are from [RapidAI's published model index](https://github.com/RapidAI/RapidOCR/blob/main/python/rapidocr/default_models.yaml), fixed to the ModelScope `v3.9.2` release. Source URLs and hashes are in `screenlingo/models.py`. Upstream project/model licensing applies; preserve it when redistributing.
