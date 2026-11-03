"""Форма записи: поля из person_fields + настройки фото (photo_config) с живым превью от Backend."""
import os
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (QWidget, QDialog, QFormLayout, QLineEdit, QGroupBox, QPushButton, QSpinBox,
                             QDoubleSpinBox, QLabel, QDialogButtonBox, QVBoxLayout, QHBoxLayout,
                             QFileDialog, QCheckBox, QComboBox, QMessageBox)
from .backend_api import BackendAPI, PhotoConfig, DEFAULT_PHOTO_CONFIG, field_type
from .photo_block import PhotoBlock


# ---- D24: редактор по типу данных поля (data_type; нет в Backend → «Строка») ----
DATE_FMT = "dd.MM.yyyy"
validate_hook = None   # тесты: validate_hook(text) вместо QMessageBox


class ImageFieldEdit(PhotoBlock):
    """Поле типа «Изображение» (Backend 91b0208): блок камера / «Из файла…».
    Значение поля — относительный путь, который вернул save_photo (снимок) или выбранный файл."""
    def __init__(self, value, base_dir, parent=None):
        super().__init__(base_dir, value, parent)
        self.textChanged = self.changed
    def text(self): return self.path or ""
    def setText(self, t): self.path = t or ""; self.captured = None; self._show_still(); self.changed.emit(self.path)


def make_editor(kind, value, base_dir=None):
    from PyQt6.QtCore import QDate
    from PyQt6.QtWidgets import QDateEdit
    if kind == "number":
        e = QDoubleSpinBox(); e.setRange(-1e12, 1e12); e.setDecimals(0 if not value or value.lstrip("-").isdigit() else 2)
        try: e.setValue(float(value.replace(",", ".")) if value else 0)
        except ValueError: pass
        e.kind = kind; return e
    if kind == "date":
        e = QDateEdit(); e.setCalendarPopup(True); e.setDisplayFormat(DATE_FMT); e.setSpecialValueText(" ")
        e.setMinimumDate(QDate(1900, 1, 1)); d = QDate.fromString(value, DATE_FMT)
        if not d.isValid(): d = QDate.fromString(value, "yyyy-MM-dd")
        e.setDate(d if d.isValid() else e.minimumDate()); e.kind = kind; return e
    if kind == "bool":
        e = QCheckBox("Да"); e.setChecked(value.strip().lower() in ("1", "да", "true", "yes", "y")); e.kind = kind; return e
    if kind == "image":
        e = ImageFieldEdit(value, base_dir); e.kind = kind; return e
    e = QLineEdit(value); e.kind = "string"; return e


def editor_value(e):
    k = getattr(e, "kind", "string")
    if k == "number":
        v = e.value(); return str(int(v)) if e.decimals() == 0 else str(v)
    if k == "date": return "" if e.date() == e.minimumDate() else e.date().toString("yyyy-MM-dd")   # Backend хранит ISO
    if k == "bool": return "1" if e.isChecked() else "0"
    return e.text().strip()


def editor_signal(e):
    k = getattr(e, "kind", "string")
    return {"number": lambda: e.valueChanged, "date": lambda: e.dateChanged, "bool": lambda: e.toggled}.get(k, lambda: e.textChanged)()


class RecordForm(QDialog):
    def __init__(self, api: BackendAPI, person_id=None, parent=None):
        super().__init__(parent)
        self.api, self.person_id = api, person_id
        p = api.get_person(person_id) if person_id else None
        self.person = p or {"id": None, "fields": {}, "photo_path": None,
                            "photo_config": DEFAULT_PHOTO_CONFIG, "print_mark": 0}
        self.setWindowTitle(f"Запись #{person_id}" if p else "Новая запись")
        # Единственный источник набора полей — list_fields() (person_fields). Поля шаблона (field_name), которых нет
        # в person_fields, показываются отдельно и регистрируются upsert_field при сохранении (D19: рассинхрон).
        fields = list(api.list_fields())
        known = {f["name"] for f in fields}
        tmpl = list(dict.fromkeys(e["field_name"] for e in api.list_elements() if e.get("field_name") and e["field_name"] not in known))
        base = max([f.get("sort_order") or 0 for f in fields] or [0]) + 1
        self._new_fields = [{"name": n, "label": n, "sort_order": base + i} for i, n in enumerate(tmpl)]
        form = QFormLayout(); self.edits = {}
        for f in fields + self._new_fields:
            e = make_editor(field_type(f), str(self.person["fields"].get(f["name"], "") or ""), api.base_dir)
            new = f in self._new_fields
            if new: e.setToolTip("Поле есть в шаблоне, но нет в person_fields — будет создано при сохранении")
            self.edits[f["name"]] = e; form.addRow((f["label"] or f["name"]) + (" (новое)" if new else "") + ":", e)
        if not self.edits:
            form.addRow(QLabel("Нет полей: создайте их в «Настр. поля» или импортируйте данные."))

        self.image_edits = {n: e for n, e in self.edits.items() if getattr(e, "kind", "") == "image"}
        cfg = PhotoConfig.parse(self.person["photo_config"])
        box = QGroupBox("Фото записи (объекты «Фото» без поля)" if self.image_edits else "Фото"); pf = QFormLayout(box)
        self.photo_path = QLineEdit(self.person["photo_path"] or ""); self.photo_path.setReadOnly(True)
        self.photo_block = PhotoBlock(api.base_dir, self.person["photo_path"] or "", self)       # D22: камера / файл
        self.photo_block.changed.connect(lambda p: (self.photo_path.setText(p), self.update_preview()))
        pf.addRow(self.photo_block); pf.addRow("Файл:", self.photo_path)

        def spin(v, lo=-3000, hi=3000):
            s = QSpinBox(); s.setRange(lo, hi); s.setSuffix(" px"); s.setValue(v); return s
        self.sx, self.sy = spin(cfg.x), spin(cfg.y)
        self.cx, self.cy = spin(cfg.crop_x, 0, 20000), spin(cfg.crop_y, 0, 20000)
        self.scale = QDoubleSpinBox(); self.scale.setRange(0.05, 20); self.scale.setSingleStep(0.05)
        self.scale.setDecimals(2); self.scale.setValue(cfg.scale)
        self.angle = QDoubleSpinBox(); self.angle.setRange(-360, 360); self.angle.setSuffix("°"); self.angle.setValue(cfg.angle)
        row = lambda a, b: (lambda l: (l.addWidget(a), l.addWidget(b), l)[-1])(QHBoxLayout())
        pf.addRow("Масштаб:", self.scale); pf.addRow("Смещение X/Y:", row(self.sx, self.sy))
        pf.addRow("Обрезка X/Y (исходник):", row(self.cx, self.cy)); pf.addRow("Поворот (по часовой):", self.angle)
        reset = QPushButton("Сбросить настройки фото"); reset.clicked.connect(self._reset_cfg); pf.addRow(reset)

        self.side = QComboBox(); self.side.addItem("Лицевая", "front"); self.side.addItem("Оборотная", "back")
        self.preview = QLabel(alignment=Qt.AlignmentFlag.AlignCenter); self.preview.setMinimumSize(506, 319)
        self.preview.setStyleSheet("border:1px solid #aaa;")
        pv = QVBoxLayout(); pv.addWidget(QLabel("Превью (рендер Backend):")); pv.addWidget(self.side); pv.addWidget(self.preview); pv.addStretch()

        self._timer = QTimer(self, singleShot=True, interval=150, timeout=self.update_preview)
        for w in (self.sx, self.sy, self.cx, self.cy): w.valueChanged.connect(lambda *_: self._timer.start())
        for w in (self.scale, self.angle): w.valueChanged.connect(lambda *_: self._timer.start())
        for e in self.edits.values(): editor_signal(e).connect(lambda *_: self._timer.start())
        self.side.currentIndexChanged.connect(lambda *_: self.update_preview())

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Save).setText("Сохранить")
        bb.button(QDialogButtonBox.StandardButton.Cancel).setText("Отмена")
        bb.accepted.connect(self.save); bb.rejected.connect(self.reject)
        # фото записи (persons.photo_path) нужно только объектам «Фото», не связанным с image-полем
        self.photo_session = api.photo_session()     # D43: Backend PhotoSession — все новые фото формы
        els = api.list_elements()
        unlinked = any(e["type"] == "photo" and not e.get("field_name") for e in els)
        for blk, fn in [(self.photo_block, None), *[(e, n) for n, e in self.image_edits.items()]]:
            blk.save_photo, blk.api, blk.session = api.save_photo, api, self.photo_session      # пропорции рамки — Backend photo_edit_target(field_name)
            blk.field_name, blk.person_id = fn, (person_id if p else None)
        self.photo_box = box; box.setVisible(not self.image_edits or unlinked)
        left = QVBoxLayout(); left.addLayout(form); left.addWidget(box); left.addStretch()
        main = QHBoxLayout(); main.addLayout(left); main.addLayout(pv)
        lay = QVBoxLayout(self); lay.addLayout(main); lay.addWidget(bb)
        self.update_preview()

    def config_string(self) -> str:
        return PhotoConfig(self.sx.value(), self.sy.value(), self.scale.value(),
                           self.cx.value(), self.cy.value(), self.angle.value()).dump()

    def _reset_cfg(self):
        c = PhotoConfig.parse(DEFAULT_PHOTO_CONFIG)
        for w, v in ((self.sx, c.x), (self.sy, c.y), (self.scale, c.scale), (self.cx, c.crop_x),
                     (self.cy, c.crop_y), (self.angle, c.angle)): w.setValue(v)

    def _load_photo(self):
        return self.photo_block.from_file()

    def draft_person(self) -> dict:
        """Несохранённое состояние формы для превью (рендерит Backend)."""
        import json
        fields = {**self.person["fields"], **{n: editor_value(e) for n, e in self.edits.items()}}
        return {"id": self.person["id"], "fields_json": json.dumps(fields, ensure_ascii=False),
                "photo_path": self.photo_path.text() or None, "photo_config": self.config_string()}

    def update_preview(self):
        try:
            img = self.api.render_preview(self.draft_person(), self.side.currentData(), 0.5)
            self.preview.setPixmap(QPixmap.fromImage(img))
        except Exception as e:  # noqa: BLE001
            self.preview.setText(f"Ошибка рендера: {e}")

    def save(self):
        fields = {n: editor_value(e) for n, e in self.edits.items()}
        try:
            bad = self.api.validate_fields(fields)          # Backend de864fc: проверка по data_type
        except Exception:  # noqa: BLE001
            bad = []
        if bad:
            msg = "\n".join(f"• {b.get('field')}: {b.get('details') or b.get('code')}" for b in bad)
            if validate_hook is not None: validate_hook(msg); return False
            QMessageBox.warning(self, "Проверка полей", f"Значения не соответствуют типу поля:\n{msg}"); return False
        save_photo = self.photo_session.save_photo if self.photo_session is not None else self.api.save_photo
        try:
            for n, e in self.image_edits.items():          # image-поле: save_photo без person_id → путь в значение поля
                if e.captured: fields[n] = e.commit(save_photo, None) or ""
            photo = self.photo_block.commit(save_photo, self.person_id or None) if self.photo_block.captured \
                else (self.photo_path.text() or None)
        except ValueError as e:
            msg = f"Снимок не сохранён: изображение пустое или повреждено ({e}). Переснимите или выберите файл."
            if validate_hook is not None: validate_hook(msg); return False
            QMessageBox.warning(self, "Фото", msg); return False
        try:
            for f in self._new_fields:
                self.api.upsert_field(f["name"], f["label"], f["sort_order"])   # D19: поле шаблона → person_fields
            if self.person_id:
                self.api.update_person(self.person_id, fields=fields, photo_path=photo)
            else:
                self.person_id = self.api.create_person(fields, photo, None, 0)
            self.api.update_photo_config(self.person_id, self.config_string())   # только эта запись
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Ошибка сохранения", str(e)); return
        if self.photo_session is not None: self.committed = self.photo_session.commit(discard_unreferenced=True)  # промежуточные
        self.stop_cameras(); self.accept()

    def stop_cameras(self):
        self.photo_block.stop()
        for e in self.image_edits.values(): e.stop()

    def reject(self):
        """«Отмена»: D43 — Backend PhotoSession.discard() удаляет созданные в этой форме фото без ссылок (сами не удаляем)."""
        self.stop_cameras()
        try: self.discarded = self.photo_session.discard() if self.photo_session is not None else []
        except Exception as e: self.discarded = [f"ошибка: {e}"]  # noqa: BLE001
        super().reject()
