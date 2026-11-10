"""Этап 14: «Редактировать изображение» (эталон reports/mockup/reference_photo_editor.png).

Яркость / Контраст / Масштаб / Вращать — ползунок + поле; превью только через Backend apply_photo_edit (адаптер
backend_api; исходник только через load_photo_for_edit). Пунктирная рамка кадрирования с пропорциями фото-элемента,
перетаскивание и изменение размера за углы с сохранением пропорций. Координаты рамки (crop) —
в пикселях изображения после EXIF-поворота, масштаба и вращения (не пиксели исходного файла).
«Портрет» — detect_face_crop / portrait_params Backend.
«Применить» → только set_photo_view (исходник не меняется, нового JPEG нет). Внизу только «Применить» / «Отмена».
"""
import json
from PyQt6.QtCore import Qt, QTimer, QRectF, QPointF
from PyQt6.QtGui import QPen, QColor, QPixmap, QAction, QTransform, QPainterPath, QBrush
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QSlider, QSpinBox, QCheckBox,
                             QPushButton, QGraphicsView, QGraphicsScene, QGraphicsRectItem, QGraphicsPixmapItem, QFrame)
from .backend_api import (pil_to_qimage, PHOTO_EDIT_DEFAULTS, photo_edit_available, face_detect_available,
                          open_image, apply_photo_edit, apply_photo_view, preview_photo_edit, detect_face_crop,
                          NO_TARGET_FN, NO_TARGET,
                          portrait_params, autoeffect_params)

editor_hook = None   # тесты: editor_hook(dialog) вместо exec(); возвращает результат exec


class CropFrame(QGraphicsRectItem):
    """Пунктирная рамка: перетаскивание целиком; углы — размер с сохранением пропорций.
    Снаружи рамки — полупрозрачная затемняющая маска (только отрисовка, params/рендер карточки не трогает)."""
    H = 10
    MASK = QColor(0, 0, 0, 128)   # ~50% чёрный

    def __init__(self, rect, aspect, bounds):
        super().__init__(rect); self.aspect, self.bounds, self._mode = aspect, QRectF(bounds), None
        pen = QPen(QColor("#1F4FFF")); pen.setStyle(Qt.PenStyle.DashLine); pen.setWidth(0); pen.setCosmetic(True)
        self.setPen(pen); self.setBrush(QBrush(Qt.BrushStyle.NoBrush))
        self.setAcceptHoverEvents(True); self.setZValue(10)

    PEN_PX = 2   # толщина пера в пикселях экрана

    def set_bounds(self, b):
        b = QRectF(b)
        if b == self.bounds: return
        self.prepareGeometryChange(); self.bounds = b

    def _px(self):
        """Размер 1 пикселя экрана в единицах сцены (масштаб первого вида)."""
        v = self.scene().views() if self.scene() else []
        return 1 / max(v[0].transform().m11(), 1e-6) if v else 1.0

    def boundingRect(self):
        """Вся область фото + перо: иначе маска за пределами rect() не перерисуется."""
        m = self.PEN_PX * self._px()
        return self.bounds.united(self.rect()).adjusted(-m, -m, m, m)

    def paint(self, painter, option, widget=None):
        """Затемнение вне crop (OddEven: bounds − rect) + D42 пунктир в пикселях устройства."""
        # маска: быстро, без правки пикселей изображения
        hole = self.rect().intersected(self.bounds)
        path = QPainterPath(); path.setFillRule(Qt.FillRule.OddEvenFill)
        path.addRect(self.bounds); path.addRect(hole)
        painter.save()
        painter.setPen(Qt.PenStyle.NoPen); painter.setBrush(QBrush(self.MASK))
        painter.drawPath(path); painter.restore()
        # пунктир рамки
        dev = painter.worldTransform().mapRect(self.rect()); h = self.PEN_PX / 2
        r = dev.adjusted(h, h, -h, -h)
        painter.save(); painter.setWorldTransform(QTransform())
        pen = QPen(self.pen()); pen.setCosmetic(False); pen.setWidthF(self.PEN_PX); painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush); painter.drawRect(r); painter.restore()

    def visible_device_rect(self):
        """Тесты D42: прямоугольник линии рамки (с пером) в пикселях вида."""
        return self.scene().views()[0].viewportTransform().mapRect(self.rect())   # перо целиком внутри этого прямоугольника

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
        """Угол тянется к p, противоположный неподвижен; высота = ширина / aspect (aspect None — свободная рамка)."""
        r0 = QRectF(r0 or self.rect()); b = self.bounds
        fx = r0.right() if "l" in corner else r0.left(); fy = r0.bottom() if "t" in corner else r0.top()
        if self.aspect is None:
            maxw = (fx - b.left()) if "l" in corner else (b.right() - fx); maxh = (fy - b.top()) if "t" in corner else (b.bottom() - fy)
            w = min(max(abs(p.x() - fx), 20), maxw); h = min(max(abs(p.y() - fy), 20), maxh)
            self.setRect(QRectF(fx - w if "l" in corner else fx, fy - h if "t" in corner else fy, w, h)); return
        w = max(abs(p.x() - fx), abs(p.y() - fy) * self.aspect, 20)
        maxw = min((fx - b.left()) if "l" in corner else (b.right() - fx), ((fy - b.top()) if "t" in corner else (b.bottom() - fy)) * self.aspect)
        w = min(w, maxw); h = w / self.aspect
        x = fx - w if "l" in corner else fx; y = fy - h if "t" in corner else fy
        self.setRect(QRectF(x, y, w, h))


_FREE_FRAME = "В шаблоне нет фото-элемента, пропорции свободные"   # D46: постоянная часть статуса при target None


class PhotoEditor(QDialog):
    SLIDERS = (("brightness", "Яркость", -50, 50, ""), ("contrast", "Контраст", -50, 50, ""),
               ("scale", "Масштаб", 10, 400, " %"), ("rotate", "Вращать", -180, 180, "°"))

    def __init__(self, path, api=None, _aspect_ignored=None, parent=None, *, field_name=None, person_id=None, session=None, element_id=None):
        """api — BackendAPI; element_id — фото-элемент (двойной щелчок). Пропорции рамки — ТОЛЬКО Backend
        get_photo_editor_state / photo_edit_target(..., element_id=) (третий позиционный аргумент не используется)."""
        super().__init__(parent); self.setWindowTitle("Редактировать изображение"); self.resize(520, 640)
        self.path, self.api, self.result_path = path, api, None
        self.view_params, self.applied = None, False  # spec 6: Apply → только вид, без нового файла
        self.field_name, self.person_id, self.session = field_name, person_id, session   # session — Backend PhotoSession формы
        self.element_id, self._autoeffect_baked = element_id, False
        self.target, self.aspect, self.target_error, self._editor_state = None, None, None, None
        self._crop, self._live_preview, self._prev_k = None, False, 1.0
        if person_id is not None and api is not None and hasattr(api, "get_photo_editor_state"):
            try:
                eid = element_id
                if eid is None and field_name:
                    try: spec = api.photo_edit_target(field_name)
                    except TypeError: spec = api.photo_edit_target(field_name)
                    if spec: eid = spec.get("element_id")
                self._editor_state = api.get_photo_editor_state(person_id, eid)
            except (ValueError, TypeError, LookupError):
                self._editor_state = None
        try:
            if self._editor_state and self._editor_state.get("frame"):
                self.target = self._editor_state["frame"]
            elif api is not None:
                try:
                    self.target = api.photo_edit_target(field_name, element_id=element_id)
                except TypeError:
                    self.target = api.photo_edit_target(field_name)
            if not self.target or not self.target.get("aspect"): self.target, self.target_error = None, _FREE_FRAME   # D46
            else: self.aspect = float(self.target["aspect"])
        except LookupError: self.target_error = NO_TARGET_FN + " — рамка свободная"
        except ValueError as e: self.target_error = f"{NO_TARGET}: {e}"
        if self._editor_state:
            if self._editor_state.get("element_id") is not None:
                self.element_id = self._editor_state["element_id"]
            if "field_name" in self._editor_state and self._editor_state["field_name"] is not None:
                self.field_name = self._editor_state["field_name"]
        if self.element_id is None and self.target: self.element_id = self.target.get("element_id")
        self.load_error = None
        try: self.src = open_image(path, getattr(api, "base_dir", None))
        except LookupError as e: self.src, self.load_error = None, str(e)
        except ValueError as e: self.src, self.load_error = None, f"Не удалось открыть фото: {e}"
        self.img = self.src
        grid = QGridLayout(); self.sl, self.sp = {}, {}
        for i, (k, lab, lo, hi, suf) in enumerate(self.SLIDERS):
            s = QSlider(Qt.Orientation.Horizontal); s.setRange(lo, hi); sp = QSpinBox(); sp.setRange(lo, hi); sp.setSuffix(suf)
            s.valueChanged.connect(sp.setValue); sp.valueChanged.connect(s.setValue)
            sp.valueChanged.connect(lambda *_: self._timer.start()); sp.valueChanged.connect(lambda *_, k=k: self._on_slider(k))
            grid.addWidget(QLabel(lab), i, 0, Qt.AlignmentFlag.AlignRight); grid.addWidget(s, i, 1); grid.addWidget(sp, i, 2)
            self.sl[k], self.sp[k] = s, sp
        self.portrait, self.autoeffect = QCheckBox("Портрет"), QCheckBox("Автоэффект")
        self.portrait.setToolTip("Рамка по лицу (поиск лица — Backend)")
        self.portrait.toggled.connect(self._on_portrait)
        self.autoeffect.toggled.connect(self._on_autoeffect)
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
        msgs = []
        if not photo_edit_available(): msgs.append("Редактирование недоступно: в Backend нет apply_photo_edit — показан оригинал")
        if not face_detect_available(): msgs.append("«Портрет» недоступен: в Backend нет detect_face_crop")
        if self.target_error: msgs.insert(0, self.target_error)
        self.base_status = "; ".join(msgs); self.status.setText(self.base_status)
        if self.aspect is None: self.portrait.setEnabled(False)       # без пропорций Backend: свободная рамка, «Портрет» выключен
        if self.src is None:        # исходник не загружен: только «Отмена» и сообщение по-русски
            for wdg in (*self.sl.values(), *self.sp.values(), self.portrait, self.autoeffect, self.b_setdef, self.b_def, self.b_apply):
                wdg.setEnabled(False)
            self.base_status = self.load_error; self.status.setText(self.load_error); return
        self._load_initial()

    def _load_initial(self):
        view = None
        if self._editor_state and self._editor_state.get("params") is not None:
            view = self._editor_state["params"]
        elif self.person_id is not None and self.api is not None and hasattr(self.api, "get_photo_view"):
            try: view = self.api.get_photo_view(self.person_id, self.field_name)
            except ValueError: view = None
        if view:
            self._crop = view.get("crop")
            self.set_params(view); self._live_preview = False
            self.update_preview()
            # crop — в пикселях после EXIF/scale/rotate (не исходного файла); рамка = этот crop
            if view.get("crop"):
                self.set_crop(*view["crop"])
            elif self.portrait.isChecked() and self.aspect is not None:
                self.apply_portrait()
            else:
                self.reset_frame()
            return
        self.load_defaults(preview=False); self.update_preview(); self.reset_frame()
        if self.portrait.isChecked() and self.aspect is not None: self.apply_portrait()   # D41

    def _on_slider(self, key):
        if getattr(self, "_setting_params", False): return
        self._live_preview = True
        if key in ("brightness", "contrast") and self.autoeffect.isChecked():
            self.autoeffect.blockSignals(True); self.autoeffect.setChecked(False); self.autoeffect.blockSignals(False)
            self._autoeffect_baked = False
        if key in ("scale", "rotate") and self.portrait.isChecked():
            self.portrait.blockSignals(True); self.portrait.setChecked(False); self.portrait.blockSignals(False)

    def _on_portrait(self, on):
        if getattr(self, "_setting_params", False): return
        self._live_preview = True
        if on: self.apply_portrait()
        else: self._timer.start()

    def _on_autoeffect(self, on):
        if getattr(self, "_setting_params", False): return
        self._live_preview = True
        if not on:
            self._autoeffect_baked = False; self._timer.start(); return
        if self.src is None: return
        p = autoeffect_params(self.src, self.params(crop=False)) or {}
        self._setting_params = True
        try:
            for k in ("brightness", "contrast"):
                if k in p: self.sp[k].setValue(int(p[k]))
            self.autoeffect.setChecked(True)    # галочка остаётся, даже если Backend вернул autoeffect=False
        finally:
            self._setting_params = False
        self._autoeffect_baked = True; self._timer.start()

    def apply_portrait(self):
        """«Портрет»: Backend portrait_params → только crop (рамка) и scale; яркость/контраст/автоэффект не трогаем."""
        if self.src is None or self.aspect is None: return False
        if self.frame is None: self.reset_frame()
        cur = self.params(crop=False)
        p = portrait_params(self.src, self.aspect, cur)
        if not p or not p.get("crop"):
            self.portrait.blockSignals(True); self.portrait.setChecked(False); self.portrait.blockSignals(False)
            self.status.setText("Лицо не найдено" + (f" ({self.base_status})" if not face_detect_available() else ""))
            return False
        # не set_params(p): иначе яркость/контраст/автоэффект перезапишутся (в т.ч. значениями автоэффекта)
        self.portrait.blockSignals(True); self.portrait.setChecked(True); self.portrait.blockSignals(False)
        if p.get("scale") is not None and int(p["scale"]) != int(self.sp["scale"].value()):
            self._setting_params = True
            try: self.sp["scale"].setValue(int(p["scale"]))
            finally: self._setting_params = False
        self._live_preview = True
        self.set_crop(*p["crop"])
        self.update_preview()
        self.set_crop(*p["crop"])   # рамка после смены размера превью
        self.status.setText(self.base_status); return True

    def show_applied(self, mode, on):
        if not on or getattr(self, "_setting_params", False): return {}
        if mode == "portrait": return {"ok": self.apply_portrait(), "element_id": self.element_id}
        if mode == "autoeffect": self._on_autoeffect(True); return {k: self.sp[k].value() for k in ("brightness", "contrast")}
        return {}

    # ---- параметры ----
    def params(self, crop=True):
        p = {k: self.sp[k].value() for k, *_ in self.SLIDERS}; p["rotate"] = float(p["rotate"])
        p["autoeffect"] = self.autoeffect.isChecked(); p["portrait"] = self.portrait.isChecked()
        p["crop"] = self.crop() if crop else None
        return p

    def set_params(self, p):
        self._setting_params = True     # умолчания/загрузка: галочки не перезаписывают значения (этап 15)
        try: self._set_params(p)
        finally: self._setting_params = False

    def _set_params(self, p):
        for k, *_ in self.SLIDERS: self.sp[k].setValue(int(p.get(k, PHOTO_EDIT_DEFAULTS[k])))
        self.autoeffect.setChecked(bool(p.get("autoeffect")))
        self.portrait.blockSignals(True); self.portrait.setChecked(bool(p.get("portrait"))); self.portrait.blockSignals(False)

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
        if preview:
            self.update_preview()
            if self.portrait.isChecked() and self.frame is not None: self.apply_portrait()

    def _preview_size(self):
        """Размер рамки фото-элемента (width_px, height_px) из get_photo_editor_state()['frame'] / target."""
        fr = (self._editor_state or {}).get("frame") if self._editor_state else None
        if not fr: fr = self.target
        if not fr: return None
        if fr.get("size"):
            w, h = fr["size"]
            return (int(w), int(h)) if w and h else None
        w, h = fr.get("width_px"), fr.get("height_px")
        return (int(w), int(h)) if w and h else None

    def _uses_frame_preview(self):
        return self.person_id is not None and self._preview_size() is not None

    # ---- превью: только Backend ----
    def update_preview(self):
        """Превью = исходник после яркости/контраста/масштаба/поворота БЕЗ crop.
        Пунктирная рамка = реальный crop из params (то, что попадёт на карточку)."""
        if self.src is None: return False
        try:
            pp = self.params(crop=False)
            if getattr(self, "_autoeffect_baked", False): pp = {**pp, "autoeffect": False}
            # crop не вшиваем в пиксели — иначе рамка становится декоративной ~80% поверх уже обрезанного кадра
            self.img, self._prev_k = preview_photo_edit(self.src, {**pp, "crop": None})
        except ValueError as e:
            self.status.setText(f"Ошибка правки: {e}"); return False
        if self.status.text().startswith("Ошибка правки") or self.target_error == _FREE_FRAME:
            self.status.setText(self.base_status)          # D46: текст о свободной рамке не затирается после превью
        self.pix.setPixmap(QPixmap.fromImage(pil_to_qimage(self.img)))
        b = QRectF(0, 0, self.img.width, self.img.height); self.scene.setSceneRect(b)
        if self.frame is None:
            self.reset_frame()
        else:
            self.frame.set_bounds(b)
            if self._crop:
                x, y, w, h = self._crop
                k = self._k()
                r = QRectF(x * k, y * k, w * k, h * k).intersected(b)
                if r.width() >= 1 and r.height() >= 1: self.frame.setRect(r)
                else: self.reset_frame()
            elif not b.contains(self.frame.rect()):
                self.reset_frame()
        self.view.fitInView(b, Qt.AspectRatioMode.KeepAspectRatio)

    def resizeEvent(self, e):
        super().resizeEvent(e); self.view.fitInView(self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def showEvent(self, e):
        super().showEvent(e); self.view.fitInView(self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    # ---- рамка ----
    def reset_frame(self):
        b = self.scene.sceneRect()
        if self.aspect is None: w, h = b.width() * 0.8, b.height() * 0.8          # свободная рамка
        else:
            h = b.height() * 0.8; w = h * self.aspect
            if w > b.width() * 0.8: w = b.width() * 0.8; h = w / self.aspect
        r = QRectF(b.center().x() - w / 2, b.center().y() - h / 2, w, h)
        if self.frame is None: self.frame = CropFrame(r, self.aspect, b); self.scene.addItem(self.frame)
        else: self.frame.set_bounds(b); self.frame.setRect(r)

    def _k(self):
        """Масштаб превью относительно полного кадра после scale/rotate (фикстуры ≤800 px → 1.0)."""
        k = getattr(self, "_prev_k", 1.0) or 1.0
        return k if k > 0 else 1.0

    def crop(self):
        """Текущий кадр в координатах полного изображения (после EXIF/scale/rotate), не пиксели превью."""
        if self.frame is not None:
            r = self.frame.rect(); k = self._k()
            self._crop = (int(round(r.x() / k)), int(round(r.y() / k)),
                          int(round(r.width() / k)), int(round(r.height() / k)))
            return self._crop
        return self._crop

    def set_crop(self, x, y, w, h):
        """crop Backend: px после EXIF, масштаба и вращения — на превью рамка = crop * k."""
        self._crop = (int(x), int(y), int(w), int(h))
        if self.frame is None: self.reset_frame()
        if self.frame is not None:
            k = self._k()
            self.frame.set_bounds(self.scene.sceneRect())
            self.frame.setRect(QRectF(self._crop[0] * k, self._crop[1] * k, self._crop[2] * k, self._crop[3] * k))

    def find_face(self):
        if self.src is None or self.frame is None or self.aspect is None: return False
        try: box = detect_face_crop(self.img, self.aspect)
        except ValueError as e: box = None; self.status.setText(f"Поиск лица: {e}")
        if not box:
            self.portrait.blockSignals(True); self.portrait.setChecked(False); self.portrait.blockSignals(False)
            self.status.setText("Лицо не найдено" + (f" ({self.base_status})" if not face_detect_available() else "")); return False
        k = self._k(); self.set_crop(*tuple(int(round(v / k)) for v in box)); self.status.setText(self.base_status); return True

    # ---- применить ----
    def apply(self):
        """«Применить» (spec 6): только вид — set_photo_view; исходник и путь формы не меняются, JPEG не создаётся.
        person_id есть → сразу в working copy (session.con). Новая запись → view_params в форму, set_photo_view при «Сохранить».
        Карточка/печать по-прежнему через render_photo / apply_photo_view."""
        if self.src is None: self.status.setText(self.load_error or "Фото не загружено"); return False
        if not photo_edit_available():
            self.status.setText("Применить нельзя: в Backend нет apply_photo_edit"); return False
        if self.api is None:
            self.status.setText("Применить нельзя: нет открытого проекта"); return False
        p = self.params()
        if getattr(self, "_autoeffect_baked", False):
            p = {**p, "autoeffect": False}
        try:
            self._validate_view(p)
        except ValueError as e:
            self.status.setText(f"Вид не сохранён: {e}"); return False
        try:
            if self.person_id is not None:
                if not hasattr(self.api, "set_photo_view"):
                    raise ValueError("в Backend нет set_photo_view")
                self.api.set_photo_view(self.person_id, p, self.field_name)
            self.view_params, self.applied, self.result_path = p, True, None
        except ValueError as e:
            self.status.setText(f"Вид не сохранён: {e}"); return False
        self.accept(); return True

    def _validate_view(self, p):
        """Проверить пересечение crop с кадром после scale/rotate без LANCZOS на полном снимке."""
        crop = p.get("crop")
        if not crop or self.src is None:
            return
        import math
        sc = (p.get("scale") or 100) / 100.0
        w, h = self.src.width * sc, self.src.height * sc
        rot = float(p.get("rotate") or 0)
        if rot:
            a = abs(rot) * math.pi / 180.0
            c, s = abs(math.cos(a)), abs(math.sin(a))
            w, h = w * c + h * s, w * s + h * c
        x, y, cw, ch = crop
        l, t, r, b = max(0, x), max(0, y), min(w, x + cw), min(h, y + ch)
        if r <= l or b <= t:
            raise ValueError(f"crop {crop} вне изображения ({max(1, int(round(w)))}, {max(1, int(round(h)))})")


def make_edit_action(parent, slot):
    """Единственный QAction «Редактировать изображение…» блока фото: двойной клик и контекстное меню."""
    a = QAction("Редактировать изображение…", parent); a.setObjectName("act_photo_edit"); a.triggered.connect(lambda *_: slot())
    return a
