"""Отдельное окно захвата с веб-камеры (D22).

Превью идёт через QVideoSink → QLabel (не QVideoWidget): на Windows QVideoWidget
часто остаётся чёрным при бэкенде ffmpeg, а кадр, взятый до первого валидного
videoFrameChanged, тоже чёрный/пустой. Кнопка «Сделать фото» включается только
после первого непустого кадра; снимок берётся из этого кадра.
"""
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QDialogButtonBox,
)


class WebcamCaptureDialog(QDialog):
    """Модальное окно: живое изображение, «Сделать фото» и «Отмена»."""

    def __init__(self, device=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Сделать фото")
        self.setModal(True)
        self.resize(640, 520)
        self._device = device
        self._last = None
        self.cam = self.session = self.sink = self.cap = None

        self.preview = QLabel("Ожидание изображения с камеры…", alignment=Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(480, 360)
        self.preview.setStyleSheet("background:#111; color:#9CA3AF; border:1px solid #374151;")

        self.status = QLabel(); self.status.setWordWrap(True); self.status.setStyleSheet("color:#6B7280;")

        self.b_shot = QPushButton("Сделать фото")
        self.b_shot.setEnabled(False)
        self.b_shot.clicked.connect(self._take)
        self.b_cancel = QPushButton("Отмена")
        self.b_cancel.clicked.connect(self.reject)
        bb = QDialogButtonBox(); bb.addButton(self.b_shot, QDialogButtonBox.ButtonRole.AcceptRole)
        bb.addButton(self.b_cancel, QDialogButtonBox.ButtonRole.RejectRole)

        lay = QVBoxLayout(self)
        lay.addWidget(self.preview, 1)
        lay.addWidget(self.status)
        row = QHBoxLayout(); row.addStretch(); row.addWidget(bb); lay.addLayout(row)

        self._setup()

    def captured_image(self) -> QImage | None:
        """Последний валидный кадр (копия QImage) или None."""
        return self._last

    def _setup(self):
        try:
            from PyQt6.QtMultimedia import QCamera, QMediaCaptureSession, QVideoSink, QImageCapture
        except Exception as e:  # noqa: BLE001
            self.status.setText(f"Камера недоступна: модуль QtMultimedia не загружен ({e.__class__.__name__})")
            return
        try:
            # parent=self: сессия не должна собираться GC (в PhotoBlock self.session
            # перезаписывался Backend PhotoSession и отрывал пайплайн — чёрный кадр).
            self.session = QMediaCaptureSession(self)
            self.sink = QVideoSink(self)
            self.session.setVideoOutput(self.sink)
            self.sink.videoFrameChanged.connect(self._on_frame)
            self.cap = QImageCapture(self)
            self.session.setImageCapture(self.cap)
            self.cap.errorOccurred.connect(self._on_cap_error)
            self.cam = QCamera(self._device, self) if self._device is not None else QCamera(self)
            self.cam.errorOccurred.connect(self._on_cam_error)
            self.session.setCamera(self.cam)
            self.cam.start()
            self.status.setText("Ожидание первого кадра…")
        except Exception as e:  # noqa: BLE001
            self.status.setText(f"Камера недоступна: {e}")

    def _on_frame(self, frame):
        if frame is None or not frame.isValid():
            return
        img = frame.toImage()
        if img is None or img.isNull() or img.width() <= 0 or img.height() <= 0:
            return
        img = img.copy()
        first = self._last is None
        self._last = img
        if first:
            self.b_shot.setEnabled(True)
            self.status.setText("Нажмите «Сделать фото», чтобы сохранить кадр")
        size = self.preview.size()
        self.preview.setPixmap(QPixmap.fromImage(img).scaled(
            size if size.width() > 1 else self.preview.minimumSize(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        ))
        self.preview.setText("")

    def _on_cam_error(self, *_a):
        err = self.cam.errorString() if self.cam is not None else ""
        self.status.setText(f"Ошибка камеры: {err or 'неизвестная ошибка'}")

    def _on_cap_error(self, *_a):
        err = self.cap.errorString() if self.cap is not None else ""
        self.status.setText(f"Ошибка снимка: {err or 'неизвестная ошибка'}")

    def _take(self):
        if self._last is None or self._last.isNull():
            self.status.setText("Камера ещё не дала кадр")
            return
        self._release()
        self.accept()

    def _release(self):
        if self.sink is not None:
            try:
                self.sink.videoFrameChanged.disconnect(self._on_frame)
            except Exception:  # noqa: BLE001
                pass
        if self.cam is not None:
            try:
                self.cam.stop()
            except Exception:  # noqa: BLE001
                pass
            self.cam = None

    def reject(self):
        self._release()
        super().reject()

    def accept(self):
        self._release()
        super().accept()

    def closeEvent(self, ev):
        self._release()
        super().closeEvent(ev)

