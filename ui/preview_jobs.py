"""Фоновый рендер превью карточки.

Данные (person, elements, background, пути) собираются в GUI-потоке через
BackendAPI.gather_render_args. Воркер вызывает только чистый Backend render_card
(без соединения SQLite) и pil_to_qimage. QPixmap создаётся в GUI-потоке.
"""
from PyQt6.QtCore import QObject, QRunnable, QThreadPool, pyqtSignal


class RenderSignals(QObject):
    finished = pyqtSignal(int, object, str)  # generation, QImage | Exception, side


class RenderCardJob(QRunnable):
    def __init__(self, generation, payload, signals):
        super().__init__()
        self.setAutoDelete(True)
        self.generation = int(generation)
        self.payload = payload
        self.signals = signals

    def run(self):
        from .backend_api import pil_to_qimage, render_card_mem
        try:
            result = pil_to_qimage(render_card_mem(**self.payload))
        except Exception as e:  # noqa: BLE001
            result = e
        self.signals.finished.emit(self.generation, result, self.payload.get("side") or "front")


def render_pool():
    return QThreadPool.globalInstance()
