"""RapidOCR recognizer using ORT's reusable CPU allocation arena."""
from rapidocr_onnxruntime.ch_ppocr_rec import TextRecognizer
from rapidocr_onnxruntime.ch_ppocr_rec.utils import CTCLabelDecode
from rapidocr_onnxruntime.utils import OrtInferSession


class ReusableCpuSession(OrtInferSession):
    @staticmethod
    def _init_sess_opts(config):
        options = OrtInferSession._init_sess_opts(config)
        options.enable_cpu_mem_arena = True
        return options


class CpuTextRecognizer(TextRecognizer):
    def __init__(self, config):
        self.session = ReusableCpuSession(config)
        characters = self.session.get_character_list() if self.session.have_key() else None
        self.postprocess_op = CTCLabelDecode(character=characters, character_path=config.get('rec_keys_path'))
        self.rec_batch_num = config['rec_batch_num']
        self.rec_image_shape = config['rec_img_shape']
