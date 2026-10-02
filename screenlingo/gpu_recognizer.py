"""CUDA recognition with CTC reduction on the device, before host transfer."""
import hashlib
import os
import time
from pathlib import Path

import numpy as np
import onnxruntime as ort
from rapidocr_onnxruntime.ch_ppocr_rec import TextRecognizer
from rapidocr_onnxruntime.ch_ppocr_rec.utils import CTCLabelDecode


def compact_model(source):
    """Keep model weights/precision intact; export only CTC indices and scores."""
    import onnx
    from onnx import helper, TensorProto
    source = Path(source)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()[:16]
    target = source.parent / "gpu" / f"{source.stem}-{digest}-ctc-v1.onnx"
    if target.exists():
        return target
    model = onnx.load(str(source))
    output = model.graph.output[0].name
    model.graph.node.append(helper.make_node("ArgMax", [output], ["ctc_indices"], axis=2, keepdims=0))
    opset = next(item.version for item in model.opset_import if item.domain == "")
    if opset >= 18:
        model.graph.initializer.append(helper.make_tensor("ctc_axes", TensorProto.INT64, [1], [2]))
        node = helper.make_node("ReduceMax", [output, "ctc_axes"], ["ctc_scores"], keepdims=0)
    else:
        node = helper.make_node("ReduceMax", [output], ["ctc_scores"], axes=[2], keepdims=0)
    model.graph.node.append(node)
    del model.graph.output[:]
    model.graph.output.extend([
        helper.make_tensor_value_info("ctc_indices", TensorProto.INT64, ["batch", "steps"]),
        helper.make_tensor_value_info("ctc_scores", TensorProto.FLOAT, ["batch", "steps"]),
    ])
    onnx.checker.check_model(model)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(f".{os.getpid()}.tmp")
    try:
        onnx.save(model, str(temporary))
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


class CompactDecode(CTCLabelDecode):
    def __call__(self, predictions, return_word_box=False, **kwargs):
        indices, scores = predictions
        result = self.decode(indices, scores, return_word_box, is_remove_duplicate=True)
        if return_word_box:
            for i, reading in enumerate(result):
                reading[2][0] *= kwargs["wh_ratio_list"][i] / kwargs["max_wh_ratio"]
        return result


class CudaSession:
    def __init__(self, model_path):
        options = ort.SessionOptions()
        options.intra_op_num_threads = 1
        options.inter_op_num_threads = 1
        options.log_severity_level = 3
        self.session = ort.InferenceSession(str(compact_model(model_path)), options, providers=[
            ("CUDAExecutionProvider", {"device_id": 0, "cudnn_conv_algo_search": "HEURISTIC"}),
            "CPUExecutionProvider",
        ])
        if self.session.get_providers()[0] != "CUDAExecutionProvider":
            raise RuntimeError("CUDA provider unavailable")
        self.input_name = self.session.get_inputs()[0].name

    def __call__(self, batch):
        return [self.session.run(None, {self.input_name: batch})]


class GpuTextRecognizer(TextRecognizer):
    accelerated = True
    def __init__(self, config):
        self.session = CudaSession(config["model_path"])
        characters = self.session.session.get_modelmeta().custom_metadata_map["character"].splitlines()
        self.postprocess_op = CompactDecode(character=characters)
        self.rec_batch_num = config.get("rec_batch_num", 2)
        self.rec_image_shape = [3, 48, 320]

    def __call__(self, images, return_word_box=False):
        # Preserve the CPU pairwise padding. Increasing padding on a long crop
        # changes attention context and can change letters, even at FP32.
        # Only combine pairs already sharing the exact 320-pixel input width.
        if isinstance(images, np.ndarray) or self.rec_batch_num <= 2:
            return super().__call__(images, return_word_box)
        start = time.perf_counter()
        ratios = [image.shape[1] / image.shape[0] for image in images]
        order = np.argsort(ratios)
        batches, pending = [], []
        for offset in range(0, len(order), 2):
            pair = list(order[offset:offset + 2])
            if max(ratios[i] for i in pair) <= 320 / 48:
                pending.extend(pair)
                if len(pending) >= self.rec_batch_num:
                    batches.append(pending)
                    pending = []
            else:
                if pending:
                    batches.append(pending)
                    pending = []
                batches.append(pair)
        if pending:
            batches.append(pending)
        result = [None] * len(images)
        for indices in batches:
            readings, _ = super().__call__([images[i] for i in indices], return_word_box)
            for index, reading in zip(indices, readings):
                result[index] = reading
        return result, time.perf_counter() - start
