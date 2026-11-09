"""Блок фото формы записи (D22): живая камера (QtMultimedia) с выбором устройства, «Сфотографировать»,
«Переснять», «Из файла…». Без камеры/QtMultimedia — понятная надпись, работает «Из файла…».

Снимок сразу попадает в превью (временный файл). При сохранении записи commit() передаёт байты в Backend
save_photo (fa29d7d) → относительный photo_path «photos/<name>».
"""
import os, tempfile, uuid
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QComboBox, QLabel, QPushButton, QFileDialog, QStackedWidget

file_hook = None          # тесты: file_hook(block) -> путь вместо QFileDialog


def multimedia():
    """(QMediaDevices, ok, сообщение). Любая ошибка импорта/устройств — без исключения."""
    try:
        from PyQt6.QtMultimedia import QMediaDevices
    except Exception as e:  # noqa: BLE001
        return None, False, f"Камера недоступна: модуль QtMultimedia не загружен ({e.__class__.__name__})"
    try:
        devs = list(QMediaDevices.videoInputs())
    except Exception as e:  # noqa: BLE001
        return QMediaDevices, False, f"Камера недоступна: {e}"
    return QMediaDevices, bool(devs), "" if devs else "Камера не найдена — используйте «Из файла…»"


class PhotoBlock(QWidget):
    changed = pyqtSignal(str)         # путь для превью (абсолютный или относительный base_dir) или ""

    def __init__(self, base_dir, photo_path="", parent=None):
        super().__init__(parent)
        self.base_dir, self.path, self.captured = base_dir or ".", photo_path or "", None
        self.cam = self.session = self.cap = self.video = None
        self.camera_combo = QComboBox(); self.camera_combo.setMinimumWidth(180)
        self.status = QLabel(); self.status.setWordWrap(True); self.status.setStyleSheet("color:#6B7280;")
        self.stack = QStackedWidget(); self.stack.setMinimumSize(240, 180)
        self.still = QLabel(alignment=Qt.AlignmentFlag.AlignCenter); self.still.setStyleSheet("background:#F4F7F7; border:1px solid #D5DCDA;")
        self.stack.addWidget(self.still)
        self.b_shot, self.b_retake, self.b_file = QPushButton("Сфотографировать"), QPushButton("Переснять"), QPushButton("Из файла…")
        self.b_shot.clicked.connect(lambda: self.shoot()); self.b_retake.clicked.connect(lambda: self.retake())
        self.b_file.clicked.connect(lambda: self.from_file())
        top = QHBoxLayout(); top.addWidget(QLabel("Камера:")); top.addWidget(self.camera_combo, 1)
        bl = QHBoxLayout()
        for b in (self.b_shot, self.b_retake, self.b_file): b.setMinimumWidth(b.sizeHint().width()); bl.addWidget(b)
        lay = QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0)
        lay.addLayout(top); lay.addWidget(self.stack, 1); lay.addWidget(self.status); lay.addLayout(bl)
        QMD, ok, msg = multimedia()
        self.has_camera = ok
        if ok:
            for d in QMD.videoInputs(): self.camera_combo.addItem(d.description(), d)
            self.camera_combo.currentIndexChanged.connect(lambda *_: self._start())
            self._setup_camera()
        else:
            self.camera_combo.addItem("— нет камеры —"); self.camera_combo.setEnabled(False)
            self.status.setText(msg)
        # этап 14: один QAction «Редактировать изображение…» — двойной клик по фото и контекстное меню
        from .photo_editor import make_edit_action
        self.save_photo, self.editor, self.session = None, None, None   # session — Backend PhotoSession формы (D43)
        self.pending_view = None   # spec 6: вид с «Применить» до появления person_id
        self.api, self.field_name, self.person_id = None, None, None     # задаёт RecordForm
        self.act_edit = make_edit_action(self, self.edit_photo)
        self.still.setContextMenuPolicy(Qt.ContextMenuPolicy.ActionsContextMenu); self.still.addAction(self.act_edit)
        self.still.installEventFilter(self); self.still.setToolTip("Двойной клик — редактировать изображение")
        self._update_buttons(); self._show_still()

    # ---- камера ----
    def _setup_camera(self):
        try:
            from PyQt6.QtMultimedia import QMediaCaptureSession, QImageCapture
            from PyQt6.QtMultimediaWidgets import QVideoWidget
            self.session = QMediaCaptureSession(); self.cap = QImageCapture(); self.session.setImageCapture(self.cap)
            self.video = QVideoWidget(); self.session.setVideoOutput(self.video); self.stack.addWidget(self.video)
            self.cap.imageCaptured.connect(lambda _id, img: self.set_captured(img))
            self.cap.errorOccurred.connect(lambda *_a: self.status.setText(f"Ошибка камеры: {self.cap.errorString()}"))
            self._start()
        except Exception as e:  # noqa: BLE001
            self.has_camera = False; self.status.setText(f"Камера недоступна: {e}"); self._update_buttons()

    def _start(self):
        from PyQt6.QtMultimedia import QCamera
        if self.cam is not None: self.cam.stop()
        dev = self.camera_combo.currentData()
        self.cam = QCamera(dev) if dev is not None else QCamera()
        self.cam.errorOccurred.connect(lambda *_a: self.status.setText(f"Ошибка камеры: {self.cam.errorString()}"))
        self.session.setCamera(self.cam); self.cam.start()
        if self.captured is None: self.stack.setCurrentWidget(self.video)
        self.status.setText("Живое изображение — нажмите «Сфотографировать»")

    def shoot(self):
        if not self.has_camera or self.cap is None: return False
        if not self.cap.isReadyForCapture():
            self.status.setText("Камера ещё не готова"); return False
        self.cap.capture(); return True

    def retake(self):
        self.captured = None
        if self.has_camera and self.video is not None:
            self.stack.setCurrentWidget(self.video)
            if self.cam is not None and not self.cam.isActive(): self.cam.start()
        self._update_buttons(); return True

    def stop(self):
        if self.cam is not None: self.cam.stop()

    # ---- снимок / файл ----
    def set_captured(self, img: QImage):
        """Снимок (или тестовое изображение) → временный файл → превью."""
        if img is None or img.isNull(): return False
        tmp = os.path.join(tempfile.gettempdir(), f"bg_capture_{uuid.uuid4().hex}.png"); img.save(tmp)
        self.captured, self.path = tmp, tmp
        if self.cam is not None: self.cam.stop()
        self._show_still(); self._update_buttons(); self.status.setText("Снимок сделан — «Переснять» или сохраните запись")
        self.changed.emit(tmp); return True

    def from_file(self, path=None):
        if path is None:
            path = file_hook(self) if file_hook is not None else \
                QFileDialog.getOpenFileName(self, "Фото записи", self.base_dir, "Изображения (*.png *.jpg *.jpeg *.bmp)")[0]
        if not path: return False
        self.captured = None
        if self.session is not None:
            # «Из файла…» через Backend PhotoSession.save_photo: новая копия в photos/ (её учитывает сессия),
            # выбранный исходник никогда не трогается и не учитывается. UI сам ничего не решает и .track не зовёт.
            try:
                with open(path, "rb") as f: data = f.read()
                ext = os.path.splitext(path)[1].lstrip(".") or "jpg"
                path = self.session.save_photo(data, ext=ext)
            except (OSError, ValueError) as e:
                self.status.setText(f"Фото не загружено: {e}"); return False
            self.path = path; self._show_still(); self._update_buttons(); self.changed.emit(path); return True
        try:
            rel = os.path.relpath(path, self.base_dir); path = path if rel.startswith("..") else rel
        except ValueError:
            pass
        self.path = path; self._show_still(); self._update_buttons(); self.changed.emit(path); return True

    def _abs(self, p):
        return p if not p or os.path.isabs(p) else os.path.join(self.base_dir, p)

    def _show_still(self):
        from PyQt6.QtGui import QPixmap
        pm = QPixmap(self._abs(self.path)) if self.path else QPixmap()
        if pm.isNull(): self.still.setPixmap(QPixmap()); self.still.setText("нет фото")
        else: self.still.setPixmap(pm.scaled(220, 170, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        if self.captured is not None or not self.has_camera or self.video is None: self.stack.setCurrentWidget(self.still)

    def eventFilter(self, obj, ev):
        from PyQt6.QtCore import QEvent
        if obj is self.still and ev.type() == QEvent.Type.MouseButtonDblClick:
            if self.act_edit.isEnabled(): self.act_edit.trigger()
            return True
        return super().eventFilter(obj, ev)

    def edit_photo(self):
        """Редактор фото (только по действию пользователя; после снимка/файла сам не открывается)."""
        from . import photo_editor as pe
        full = self._abs(self.path)
        if not self.path or not os.path.isfile(full) or self.api is None: return None
        eid = None
        try:
            spec = self.api.photo_edit_target(self.field_name)
            if spec: eid = spec.get("element_id")
        except Exception:
            eid = None
        d = self.editor = pe.PhotoEditor(full, self.api, None, self, field_name=self.field_name, person_id=self.person_id,
                                             session=self.session, element_id=eid)
        d.accepted.connect(lambda: self._edited(d))
        return pe.editor_hook(d) if pe.editor_hook is not None else d.exec()

    def _edited(self, d):
        """spec 6: «Применить» не подменяет путь — исходник остаётся; вид уже в set_photo_view или в pending_view."""
        if not getattr(d, "applied", False): return
        if self.captured:
            try: os.remove(self.captured)
            except OSError: pass
            self.captured = None
        # новая запись: set_photo_view после create_person в RecordForm.save
        self.pending_view = None if d.person_id is not None else getattr(d, "view_params", None)
        self._show_still(); self._update_buttons()

    def _update_buttons(self):
        self.b_shot.setEnabled(self.has_camera and self.captured is None); self.b_retake.setEnabled(self.has_camera and self.captured is not None)
        if hasattr(self, "act_edit"): self.act_edit.setEnabled(bool(self.path))

    def commit(self, save_photo, person_id=None):
        """Снимок → Backend save_photo(image_bytes, person_id=…, ext=…) → «photos/<name>» (ValueError — пусто/битые данные).
        Без снимка — текущий путь (из файла) или None."""
        if self.captured:
            with open(self.captured, "rb") as f: data = f.read()
            rel = save_photo(data, person_id=person_id, ext="png")
            try: os.remove(self.captured)
            except OSError: pass
            self.captured = None; self.path = rel
        return self.path or None
