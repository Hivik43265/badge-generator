"""Этап 15, шаг 1 — ТОЛЬКО интерфейс (макет и заглушки по приказу Архитектора).

Здесь нет логики Backend, SQL и обработки изображений. Всё, что требует Backend, помечено «TODO stage15»
и показывает заглушку (stub_message). Существующие функции Backend вызываются только там, где они уже
использовались до этапа 15 (set_prop панели свойств редактора).
"""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QHBoxLayout, QVBoxLayout, QPushButton, QLabel, QDialog, QListWidget, QListWidgetItem,
                             QMessageBox)

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


class TemplateTools:
    """П.2: «Режим шаблона» / «✓ Сохранить шаблон» / «Менеджер шаблонов» — слоты QAction ленты «Редактировать»."""

    def __init__(self, parent, editor=None):
        self.parent, self.editor, self.template_mode, self.act_mode, self.act_save = parent, editor, False, None, None

    def bind(self, act_mode, act_save):
        self.act_mode, self.act_save = act_mode, act_save; self.set_template_mode(False)

    def set_template_mode(self, on):
        self.template_mode = bool(on)
        pass  # «Сохранить шаблон» всегда доступна (контракт self-test: все действия ленты доступны)
        if self.act_mode is not None and self.act_mode.isChecked() != self.template_mode: self.act_mode.setChecked(self.template_mode)
        if self.editor is not None: self.editor.set_template_mode_banner(self.template_mode)
        return self.template_mode

    def save_template(self):
        # TODO stage15: сохранение шаблона — Backend (save_template / templates) ещё нет
        return stub_message(self.parent, "Сохранить шаблон", STUB)

    def open_manager(self, exec_=True):
        d = TemplateManagerDialog(self.parent)
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
