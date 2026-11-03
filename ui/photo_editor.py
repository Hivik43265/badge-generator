"""Этап 14: «Редактировать изображение» (эталон reports/mockup/reference_photo_editor.png).

Яркость / Контраст / Масштаб / Вращать — ползунок + поле; превью только через Backend apply_photo_edit (адаптер
backend_api; нет функции → оригинал и статус «недоступно»). Пунктирная рамка кадрирования с пропорциями фото-элемента,
перетаскивание и изменение размера за углы с сохранением пропорций. «Портрет» — detect_face_crop Backend.
«Применить» → save_photo → относительный путь (в значение поля типа image). Внизу только «Применить» / «Отмена».
"""
import json
from PyQt6.QtCore import Qt, QTimer, QRectF, QPointF
from PyQt6.QtGui import QPen, QColor, QPixmap, QAction
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QSlider, QSpinBox, QCheckBox,
                             QPushButton, QGraphicsView, QGraphicsScene, QGraphicsRectItem, QGraphicsPixmapItem, QFrame)
from .backend_api import (pil_to_qimage, PHOTO_EDIT_DEFAULTS, photo_edit_available, face_detect_available,
                          open_image, apply_photo_edit, detect_face_crop, image_png_bytes,
                          apply_and_save_available)

editor_hook = None   # тесты: editor_hook(dialog) вместо exec(); возвращает результат exec


class CropFrame(QGraphicsRectItem):
    """Пунктирная рамка: перетаскивание целиком; углы — размер с сохранением пропорций."""
    H = 10

    def __init__(self, rect, aspect, bounds):
        super().__init__(rect); self.aspect, self.bounds, self._mode = aspect, bounds, None
        pen = QPen(QColor("#1F4FFF")); pen.setStyle(Qt.PenStyle.DashLine); pen.setWidth(0); pen.setCosmetic(True)
        self.setPen(pen); self.setAcceptHoverEvents(True); self.setZValue(10)

    def _corner(self, p):
        r = self.rect(); h = self.H / max(self.scene().views()[0].transform().m11(), 1e-6) if self.scene() and self.scene().views() else self.H
        for name, c in (("tl", r.topLeft()), ("tr", r.topRight()), ("bl", r.bottomLeft()), ("br", r.bottomRight())):
            if abs(p.x() - c.x()) <= h and abs(p.y() - c.y()) <= h: return name
        return "move" if r.contains(p) else None

    def hoverMoveEvent(self, e):
        m = self._corner(e.pos())
        self.setCursor(Qt.CursorShape.SizeFDiagCursor if m in ("tl", "br") else Qt.CursorShape.SizeBDiagCursor if m in ("tr", "bl")
                       else Qt.CursorShape.SizeAllCursor if m == "move" else Qt.CursorShape.ArrowCursor)

    def mousePressEvent(self, e):
        self._mode, self._start, self._r0 = self._corner(e.pos()), e.pos(), QRectF(self.rect())
        if self._mode is None: e.ignore()

    def mouseMoveEvent(self, e):
        if self._mode == "move": self.move_by(e.pos() - self._start, self._r0)
        elif self._mode: self.resize_corner(self._mode, e.pos(), self._r0)

    def mouseReleaseEvent(self, e): self._mode = None

    def move_by(self, d, r0=None):
        r = QRectF(r0 or self.rect()).translated(d); b = self.bounds
        r.moveLeft(min(max(r.left(), b.left()), b.right() - r.width())); r.moveTop(min(max(r.top(), b.top()), b.bottom() - r.height()))
        self.setRect(r)

    def resize_corner(self, corner, p, r0=None):
        """Угол тянется к p, противоположный неподвижен; высота = ширина / aspect."""
        r0 = QRectF(r0 or self.rect()); b = self.bounds
        fx = r0.right() if "l" in corner else r0.left(); fy = r0.bottom() if "t" in corner else r0.top()
        w = max(abs(p.x() - fx), abs(p.y() - fy) * self.aspect, 20)
        maxw = min((fx - b.left()) if "l" in corner else (b.right() - fx), ((fy - b.top()) if "t" in corner else (b.bottom() - fy)) * self.aspect)
        w = min(w, maxw); h = w / self.aspect
        x = fx - w if "l" in corner else fx; y = fy - h if "t" in corner else fy
        self.setRect(QRectF(x, y, w, h))


class PhotoEditor(QDialog):
    SLIDERS = (("brightness", "Яркость", -50, 50, ""), ("contrast", "Контраст", -50, 50, ""),
               ("scale", "Масштаб", 10, 400, " %"), ("rotate", "Вращать", -180, 180, "°"))

    def __init__(self, path, api=None, aspect=3 / 4, parent=None, *, field_name=None, person_id=None):
        """api — BackendAPI (умолчания проекта, apply_and_save_photo, save_photo); field_name/person_id — поле image записи."""
        super().__init__(parent); self.setWindowTitle("Редактировать изображение"); self.resize(520, 640)
        self.path, self.api, self.aspect, self.result_path = path, api, aspect or 3 / 4, None
        self.field_name, self.person_id = field_name, person_id
        self.src = open_image(path, getattr(api, "base_dir", None)); self.img = self.src
        grid = QGridLayout(); self.sl, self.sp = {}, {}
        for i, (k, lab, lo, hi, suf) in enumerate(self.SLIDERS):
            s = QSlider(Qt.Orientation.Horizontal); s.setRange(lo, hi); sp = QSpinBox(); sp.setRange(lo, hi); sp.setSuffix(suf)
            s.valueChanged.connect(sp.setValue); sp.valueChanged.connect(s.setValue); sp.valueChanged.connect(lambda *_: self._timer.start())
            grid.addWidget(QLabel(lab), i, 0, Qt.AlignmentFlag.AlignRight); grid.addWidget(s, i, 1); grid.addWidget(sp, i, 2)
            self.sl[k], self.sp[k] = s, sp
        self.portrait, self.autoeffect = QCheckBox("Портрет"), QCheckBox("Автоэффект")
        self.portrait.setToolTip("Рамка по лицу (поиск лица — Backend)"); self.portrait.toggled.connect(lambda on: on and self.find_face())
        self.autoeffect.toggled.connect(lambda *_: self._timer.start())
        self.b_setdef, self.b_def = QPushButton("Установить по умолчанию"), QPushButton("По умолчанию")
        self.b_setdef.clicked.connect(lambda: self.save_defaults()); self.b_def.clicked.connect(lambda: self.load_defaults())
        opts = QHBoxLayout(); opts.addStretch(1); opts.addWidget(self.portrait); opts.addSpacing(30); opts.addWidget(self.autoeffect); opts.addStretch(1)
        defs = QHBoxLayout(); defs.addWidget(self.b_setdef); defs.addWidget(self.b_def)
        line = QFrame(); line.setFrameShape(QFrame.Shape.HLine)
        self.scene = QGraphicsScene(self); self.view = QGraphicsView(self.scene); self.view.setMinimumHeight(300)
        self.view.setRenderHints(self.view.renderHints()); self.pix = QGraphicsPixmapItem(); self.scene.addItem(self.pix)
        self.frame = None
        self.status = QLabel(); self.status.setWordWrap(True); self.status.setStyleSheet("color:#9A5B00;")
        self.b_apply, self.b_cancel = QPushButton("Применить"), QPushButton("Отмена")
        self.b_apply.setDefault(True); self.b_apply.clicked.connect(lambda: self.apply()); self.b_cancel.clicked.connect(self.reject)
        bottom = QHBoxLayout(); bottom.addWidget(self.b_apply, 1); bottom.addWidget(self.b_cancel, 1)
        lay = QVBoxLayout(self); lay.addLayout(grid); lay.addLayout(opts); lay.addLayout(defs); lay.addWidget(line)
        lay.addWidget(self.view, 1); lay.addWidget(self.status); lay.addLayout(bottom)
        self._timer = QTimer(self, singleShot=True, interval=60, timeout=self.update_preview)
        self.load_defaults(preview=False); self.update_preview(); self.reset_frame()
        msgs = []
        if not photo_edit_available(): msgs.append("Редактирование недоступно: в Backend нет apply_photo_edit — показан оригинал")
        if not face_detect_available(): msgs.append("«Портрет» недоступен: в Backend нет detect_face_crop")
        self.base_status = "; ".join(msgs); self.status.setText(self.base_status)

    # ---- параметры ----
    def params(self, crop=True):
        p = {k: self.sp[k].value() for k, *_ in self.SLIDERS}; p["rotate"] = float(p["rotate"])
        p["autoeffect"] = self.autoeffect.isChecked(); p["crop"] = self.crop() if crop else None
        return p

    def set_params(self, p):
        for k, *_ in self.SLIDERS: self.sp[k].setValue(int(p.get(k, PHOTO_EDIT_DEFAULTS[k])))
        self.autoeffect.setChecked(bool(p.get("autoeffect")))

    def save_defaults(self):
        """«Установить по умолчанию» → Backend set_photo_edit_defaults (умолчания проекта, без crop)."""
        try:
            if self.api is None: raise ValueError("нет открытого проекта")
            p = self.api.set_photo_edit_defaults(self.params(crop=False))
        except ValueError as e:
            self.status.setText(f"Умолчания не сохранены: {e}"); return None
        self.status.setText("Текущие настройки сохранены как умолчания проекта"); return p

    def load_defaults(self, preview=True):
        """«По умолчанию» → Backend get_photo_edit_defaults; нет проекта/функции → DEFAULT_PHOTO_EDIT."""
        p = self.api.get_photo_edit_defaults() if self.api is not None else dict(PHOTO_EDIT_DEFAULTS)
        self.set_params({**PHOTO_EDIT_DEFAULTS, **p})
        if preview: self.update_preview()

    # ---- превью: только Backend ----
    def update_preview(self):
        try: self.img = apply_photo_edit(self.src, self.params(crop=False))
        except ValueError as e:
            self.status.setText(f"Ошибка правки: {e}"); return False
        if self.status.text().startswith("Ошибка правки"): self.status.setText(self.base_status)
        self.pix.setPixmap(QPixmap.fromImage(pil_to_qimage(self.img)))
        b = QRectF(0, 0, self.img.width, self.img.height); self.scene.setSceneRect(b)
        if self.frame is not None:
            self.frame.bounds = b
            if not b.contains(self.frame.rect()): self.reset_frame()
        self.view.fitInView(b, Qt.AspectRatioMode.KeepAspectRatio)

    def resizeEvent(self, e):
        super().resizeEvent(e); self.view.fitInView(self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def showEvent(self, e):
        super().showEvent(e); self.view.fitInView(self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    # ---- рамка ----
    def reset_frame(self):
        b = self.scene.sceneRect(); h = b.height() * 0.8; w = h * self.aspect
        if w > b.width() * 0.8: w = b.width() * 0.8; h = w / self.aspect
        r = QRectF(b.center().x() - w / 2, b.center().y() - h / 2, w, h)
        if self.frame is None: self.frame = CropFrame(r, self.aspect, b); self.scene.addItem(self.frame)
        else: self.frame.setRect(r)

    def crop(self):
        r = self.frame.rect(); return (int(round(r.x())), int(round(r.y())), int(round(r.width())), int(round(r.height())))

    def set_crop(self, x, y, w, h):
        self.frame.setRect(QRectF(x, y, w, w / self.aspect if w and h and abs(w / h - self.aspect) > 1e-3 else h))

    def find_face(self):
        try: box = detect_face_crop(self.img, self.aspect)
        except ValueError as e: box = None; self.status.setText(f"Поиск лица: {e}")
        if not box:
            self.portrait.blockSignals(True); self.portrait.setChecked(False); self.portrait.blockSignals(False)
            self.status.setText("Лицо не найдено" + (f" ({self.base_status})" if not face_detect_available() else "")); return False
        self.set_crop(*box); self.status.setText(self.base_status); return True

    # ---- применить ----
    def apply(self):
        """«Применить» → Backend apply_and_save_photo БЕЗ person_id/field_name (новый файл, исходник не трогается).
        Путь идёт в форму записи и попадает в БД только по «Сохранить»; при «Отмена» формы файл остаётся в photos/
        без ссылки (согласовано с Backend). Нет apply_and_save_photo → apply_photo_edit + save_photo (байты)."""
        if not photo_edit_available():
            self.status.setText("Применить нельзя: в Backend нет apply_photo_edit"); return False
        if self.api is None:
            self.status.setText("Применить нельзя: нет открытого проекта"); return False
        p = self.params()
        try:
            if apply_and_save_available() and self.path:
                self.result_path = self.api.apply_and_save_photo(self.path, p)
            else:
                self.result_path = self.api.save_photo(image_png_bytes(apply_photo_edit(self.src, p)), person_id=None, ext="png")
        except ValueError as e:
            self.status.setText(f"Фото не сохранено: {e}"); return False
        self.accept(); return True


def make_edit_action(parent, slot):
    """Единственный QAction «Редактировать изображение…» блока фото: двойной клик и контекстное меню."""
    a = QAction("Редактировать изображение…", parent); a.setObjectName("act_photo_edit"); a.triggered.connect(lambda *_: slot())
    return a
