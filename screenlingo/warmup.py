from PySide6.QtCore import QThread, Signal


class Preparation(QThread):
    ready = Signal(str)

    def __init__(self, options, parent=None):
        super().__init__(parent)
        self.options = options

    def run(self):
        try:
            import numpy as np
            import cv2
            from .ocr import get_ocr
            engine = get_ocr(cancelled=self.isInterruptionRequested)
            if self.isInterruptionRequested():
                return
            # Exercise detection and both recognition kernels on public synthetic text.
            sample = np.full((72, 400, 3), 255, dtype=np.uint8)
            cv2.putText(sample, "Ready for translation", (10, 45), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2)
            engine(sample, self.isInterruptionRequested)
            if self.isInterruptionRequested():
                return
            from .runtime import warm_translator
            connected = warm_translator(self.options)
            if connected is False:
                self.ready.emit("识别已就绪，翻译连接未预热。若服务限流，将等待后重试。")
            else:
                self.ready.emit("准备就绪。固定原文语言可进一步提速。")
        except Exception as exc:
            self.ready.emit(f"模型准备失败（{type(exc).__name__}），开始翻译时会重试。")
