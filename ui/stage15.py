"""Этап 15, шаг 1 — ТОЛЬКО интерфейс (макет и заглушки по приказу Архитектора).

Здесь нет логики Backend, SQL и обработки изображений. Всё, что требует Backend, помечено «TODO stage15»
и показывает заглушку (stub_message). Существующие функции Backend вызываются только там, где они уже
использовались до этапа 15 (set_prop панели свойств редактора).
"""
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QAction
from PyQt6.QtWidgets import (QWidget, QGroupBox, QFormLayout, QHBoxLayout, QVBoxLayout, QFontComboBox, QSpinBox,
                             QPushButton, QToolButton, QLabel, QDialog, QListWidget, QListWidgetItem, QMessageBox,
                             QColorDialog)

UNLINKED_COLOR = "#E07A00"      # рамка объекта шаблона «не связан» (после «Отвязать поле»)
LINKED_COLOR = "#3070d0"        # обычная рамка (как в layout_editor.ElementItem)
PRINTED_ROW_COLOR = "#DCEFE4"   # строка «Напечатано» в таблице записей
PHOTO_FIELD_LABEL, PHOTO_FIELD_TYPE = "Фото", "Изображение"
STUB = "Не реализовано: этап 15, ждёт Backend"

stub_hook = None   # тесты/скриншоты: stub_hook(title, text) вместо QMessageBox


def stub_message(parent, title, text=STUB):
    """TODO stage15: единая заглушка для действий, которым нужен Backend."""
    if stub_hook is not None: return stub_hook(title, text)
    QMessageBox.information(parent, title, text); return None


def _color_btn(text):
    b = QToolButton(); b.setText(text); b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
    b.setMinimumWidth(90); b.color = None; return b


def _set_btn_color(b, c):
    b.color = c; b.setStyleSheet(f"QToolButton{{border:1px solid #888; border-left:14px solid {c}; padding:2px 6px;}}" if c else "")


class FormatPanel(QGroupBox):
    """П.2: панель «Редактирование» — шрифт, размер, отступы, цвет текста, заливка, цвет/толщина границы;
    «Режим шаблона» (ручная расстановка элементов), «✓» — сохранить шаблон, «Менеджер шаблонов»."""

    def __init__(self, editor=None, parent=None):
        super().__init__("Редактирование", parent); self.editor = editor
        self.font = QFontComboBox(); self.font.setToolTip("TODO stage15: ключ стиля font_family — ждёт Backend (рендер)")
        self.size = QSpinBox(); self.size.setRange(4, 200); self.size.setValue(14); self.size.setSuffix(" pt")
        self.padding = QSpinBox(); self.padding.setRange(0, 200); self.padding.setSuffix(" px")
        self.padding.setToolTip("TODO stage15: ключ стиля padding — ждёт Backend (рендер)")
        self.text_color, self.fill, self.border = _color_btn("Цвет текста"), _color_btn("Заливка"), _color_btn("Граница")
        self.border_w = QSpinBox(); self.border_w.setRange(0, 100); self.border_w.setValue(1); self.border_w.setSuffix(" px")
        f = QFormLayout(); f.addRow("Шрифт:", self.font); f.addRow("Размер шрифта:", self.size); f.addRow("Отступы:", self.padding)
        colors = QHBoxLayout(); [colors.addWidget(b) for b in (self.text_color, self.fill)]
        f.addRow("Цвет:", colors)
        brow = QHBoxLayout(); brow.addWidget(self.border); brow.addWidget(self.border_w); f.addRow("Граница:", brow)
        # кнопки панели — QToolButton на собственных QAction (правило: одно действие = один QAction, одно место)
        self.act_mode = QAction("Режим создания шаблона", self); self.act_mode.setObjectName("act_template_mode"); self.act_mode.setCheckable(True)
        self.act_save = QAction("✓", self); self.act_save.setObjectName("act_template_save"); self.act_save.setToolTip("Сохранить шаблон")
        self.act_manager = QAction("Менеджер шаблонов", self); self.act_manager.setObjectName("act_template_manager")
        self.b_mode, self.b_save, self.b_manager = (QToolButton() for _ in range(3))
        for b, a in ((self.b_mode, self.act_mode), (self.b_save, self.act_save), (self.b_manager, self.act_manager)):
            b.setDefaultAction(a); b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.b_mode.setStyleSheet("QToolButton{border:1px solid #9AA; border-radius:3px; padding:3px 8px;} QToolButton:checked{background:#2E7D6B; color:white;}")
        self.b_manager.setStyleSheet("QToolButton{border:1px solid #9AA; border-radius:3px; padding:3px 8px;}")
        self.b_save.setStyleSheet("QToolButton{font-size:16px; font-weight:bold; color:white; background:#2E7D6B;"
                                  " border-radius:4px; padding:2px 10px;} QToolButton:disabled{background:#B9C9C4;}")
        row = QHBoxLayout(); row.addWidget(self.b_mode, 1); row.addWidget(self.b_save); row.addWidget(self.b_manager)
        self.mode_hint = QLabel("Режим шаблона: расставьте элементы на карточке вручную и выберите поля; сохранение — «✓».")
        self.mode_hint.setWordWrap(True); self.mode_hint.setStyleSheet("color:#2E7D6B; font-weight:600;")
        lay = QVBoxLayout(self); lay.addLayout(f); lay.addLayout(row); lay.addWidget(self.mode_hint)
        self.set_template_mode(False)
        self.act_mode.toggled.connect(self.set_template_mode)
        self.act_save.triggered.connect(lambda *_: self.save_template()); self.act_manager.triggered.connect(lambda *_: self.open_manager())
        for b, key in ((self.text_color, "color"), (self.fill, "fill"), (self.border, "stroke")):
            b.clicked.connect(lambda _=False, b=b, key=key: self.pick(b, key))
        self.size.valueChanged.connect(lambda v: self._apply("font_size", v))
        self.border_w.valueChanged.connect(lambda v: self._apply("stroke_width", v))

    def _apply(self, key, value):
        """Применение через существующий путь панели свойств редактора (set_prop); без нового API."""
        ed = self.editor
        if ed is None or ed.current is None: return False
        if key == "font_size": ed.p_font.setValue(int(value)); return ed.apply_props()
        return ed.set_prop(key, value)

    def pick(self, b, key, color=None):
        c = color or QColorDialog.getColor(QColor(b.color or "#000000"), self, b.text()).name()
        _set_btn_color(b, c); self._apply(key, c); return c

    def set_template_mode(self, on):
        self.template_mode = bool(on); self.act_save.setEnabled(self.template_mode); self.mode_hint.setVisible(self.template_mode)
        if self.act_mode.isChecked() != self.template_mode: self.act_mode.setChecked(self.template_mode)
        if self.editor is not None and hasattr(self.editor, "set_template_mode_banner"): self.editor.set_template_mode_banner(self.template_mode)

    def save_template(self):
        # TODO stage15: сохранение шаблона — Backend (save_template / templates) ещё нет
        return stub_message(self, "Сохранить шаблон", STUB)

    def open_manager(self, exec_=True):
        d = TemplateManagerDialog(self)
        if exec_: d.exec()
        return d


# TODO stage15: список шаблонов — заглушка до Backend list_templates
PLACEHOLDER_TEMPLATES = [("Сотрудник (стандарт)", True), ("Гость", False), ("Подрядчик", False)]


class TemplateManagerDialog(QDialog):
    """П.2: «Менеджер шаблонов» — список всех шаблонов; «Активировать», «Редактировать», «Удалить» (заглушки)."""

    def __init__(self, parent=None, templates=None):
        super().__init__(parent); self.setWindowTitle("Менеджер шаблонов"); self.resize(460, 320)
        self.list = QListWidget()
        for name, active in (templates or PLACEHOLDER_TEMPLATES):
            it = QListWidgetItem(name + ("   — активный" if active else "")); it.setData(Qt.ItemDataRole.UserRole, name)
            if active: f = it.font(); f.setBold(True); it.setFont(f)
            self.list.addItem(it)
        self.list.setCurrentRow(0)
        self.b_activate, self.b_edit, self.b_delete, self.b_close = (QPushButton(t) for t in ("Активировать", "Редактировать", "Удалить", "Закрыть"))
        for b, t in ((self.b_activate, "Активировать шаблон"), (self.b_edit, "Редактировать шаблон"), (self.b_delete, "Удалить шаблон")):
            b.clicked.connect(lambda _=False, t=t: stub_message(self, t))      # TODO stage15: Backend
        self.b_close.clicked.connect(self.accept)
        note = QLabel("Макет: список шаблонов — пример, действия пока не реализованы (этап 15)."); note.setStyleSheet("color:#9A5B00;")
        side = QVBoxLayout(); [side.addWidget(b) for b in (self.b_activate, self.b_edit, self.b_delete)]; side.addStretch(1); side.addWidget(self.b_close)
        h = QHBoxLayout(); h.addWidget(self.list, 1); h.addLayout(side)
        lay = QVBoxLayout(self); lay.addWidget(QLabel("Шаблоны проекта:")); lay.addLayout(h); lay.addWidget(note)
