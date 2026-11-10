"""Этап 15: режим шаблона, менеджер шаблонов, восстановление после сбоя (UI).

SQL и обработка изображений здесь запрещены: только вызовы BackendAPI и диалоги.
"""
from pathlib import Path
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QHBoxLayout, QVBoxLayout, QPushButton, QLabel, QDialog, QListWidget, QListWidgetItem,
                             QMessageBox, QFileDialog, QTextEdit)

UNLINKED_COLOR = "#E07A00"      # рамка объекта шаблона «не связан» (после «Отвязать поле»)
LINKED_COLOR = "#3070d0"        # обычная рамка (как в layout_editor.ElementItem)
PRINTED_ROW_COLOR = "#DCEFE4"   # строка «Напечатано» в таблице записей
PHOTO_FIELD_LABEL, PHOTO_FIELD_TYPE = "Фото", "Изображение"
STUB = "Не реализовано: этап 15, ждёт Backend"
MOCK_UNLINKED_AFTER_LOAD = ("ФИО — объект будет отвязан", "Отдел — объект будет отвязан",
                            "QR-код — объект будет отвязан")

stub_hook = None   # тесты/скриншоты: stub_hook(title, text) вместо QMessageBox
restore_prompt_hook = None   # тесты: hook(state) -> "restore" | "keep" | None
save_changes_hook = None     # тесты: hook() -> True (Да) | False (Нет) | None (Отмена)
save_template_project_hook = None  # тесты: hook() -> True (Да) | False (Отмена)
replace_template_hook = None  # тесты: hook() -> True | False
recover_work_hook = None      # тесты: hook() -> True (Да) | False (Нет) | None (закрыть)
bgt_path_hook = None          # тесты: hook("export"|"import") -> путь | None
smartid_report_hook = None    # тесты: hook(result) вместо окна отчёта


def stub_message(parent, title, text=STUB):
    """Заглушка для действий, которым ещё нет утверждённого Backend/макета."""
    if stub_hook is not None: return stub_hook(title, text)
    QMessageBox.information(parent, title, text); return None


def template_restore_box(parent, state):
    """Диалог «снимок после сбоя»: Восстановить = cancel, Оставить правки = commit."""
    name = (state or {}).get("name") or "шаблон"
    box = QMessageBox(parent)
    box.setObjectName("dlg_template_restore")
    box.setWindowTitle("Шаблон не сохранён")
    box.setIcon(QMessageBox.Icon.Warning)
    box.setText(f"Шаблон «{name}» не был сохранён.\nВосстановить прежний или оставить правки?")
    box.b_restore = box.addButton("Восстановить", QMessageBox.ButtonRole.AcceptRole)
    box.b_keep = box.addButton("Оставить правки", QMessageBox.ButtonRole.DestructiveRole)
    box.setDefaultButton(box.b_restore)
    return box


def ask_restore_template(parent, state):
    """→ 'restore' | 'keep' | None."""
    if restore_prompt_hook is not None: return restore_prompt_hook(state)
    box = template_restore_box(parent, state)
    box.exec()
    if box.clickedButton() is box.b_restore: return "restore"
    if box.clickedButton() is box.b_keep: return "keep"
    return None


def save_changes_box(parent):
    """«Сохранить изменения?» при закрытии, только если проект dirty."""
    box = QMessageBox(parent)
    box.setObjectName("dlg_save_changes")
    box.setWindowTitle("Сохранить изменения?")
    box.setIcon(QMessageBox.Icon.Question)
    box.setText("Сохранить изменения?")
    box.b_yes = box.addButton("Да", QMessageBox.ButtonRole.YesRole)
    box.b_no = box.addButton("Нет", QMessageBox.ButtonRole.NoRole)
    box.b_cancel = box.addButton("Отмена", QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(box.b_yes)
    return box


def ask_save_changes(parent):
    """→ True (Да) | False (Нет) | None (Отмена)."""
    if save_changes_hook is not None: return save_changes_hook()
    box = save_changes_box(parent); box.exec()
    if box.clickedButton() is box.b_yes: return True
    if box.clickedButton() is box.b_no: return False
    return None


def save_template_and_project_box(parent):
    """Ctrl+S в режиме шаблона: не фиксирует черновик молча."""
    box = QMessageBox(parent)
    box.setObjectName("dlg_save_template_and_project")
    box.setWindowTitle("Сохранить")
    box.setIcon(QMessageBox.Icon.Question)
    box.setText("Сохранить правки шаблона и проект?")
    box.b_yes = box.addButton("Да", QMessageBox.ButtonRole.YesRole)
    box.b_cancel = box.addButton("Отмена", QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(box.b_cancel)
    return box


def ask_save_template_and_project(parent):
    """→ True (Да) | False (Отмена)."""
    if save_template_project_hook is not None: return bool(save_template_project_hook())
    box = save_template_and_project_box(parent); box.exec()
    return box.clickedButton() is box.b_yes


def recover_work_box(parent):
    """open_project → RecoverableProjectError: «Восстановить несохранённую работу?»"""
    box = QMessageBox(parent)
    box.setObjectName("dlg_recover_work")
    box.setWindowTitle("Восстановить несохранённую работу?")
    box.setIcon(QMessageBox.Icon.Question)
    box.setText("Восстановить несохранённую работу?")
    box.b_yes = box.addButton("Да", QMessageBox.ButtonRole.YesRole)
    box.b_no = box.addButton("Нет", QMessageBox.ButtonRole.NoRole)
    box.b_cancel = box.addButton("Отмена", QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(box.b_yes)
    return box


def ask_recover_work(parent):
    """→ True (восстановить) | False (открыть исходник) | None (не открывать)."""
    if recover_work_hook is not None: return recover_work_hook()
    box = recover_work_box(parent); box.exec()
    if box.clickedButton() is box.b_yes: return True
    if box.clickedButton() is box.b_no: return False
    return None


def project_locked_box(parent):
    box = QMessageBox(parent)
    box.setObjectName("dlg_project_locked")
    box.setWindowTitle("Проект уже открыт")
    box.setIcon(QMessageBox.Icon.Warning)
    box.setText("Проект уже открыт в другом окне")
    box.addButton("ОК", QMessageBox.ButtonRole.AcceptRole)
    return box


def show_project_locked(parent):
    box = project_locked_box(parent); box.exec(); return None


def save_error_box(parent, message):
    box = QMessageBox(parent)
    box.setObjectName("dlg_save_error")
    box.setWindowTitle("Сохранить")
    box.setIcon(QMessageBox.Icon.Warning)
    box.setText(str(message))
    box.addButton("ОК", QMessageBox.ButtonRole.AcceptRole)
    return box


def show_save_error(parent, message):
    box = save_error_box(parent, message); box.exec(); return None


def _format_unlinked(unlinked):
    """preview_template_file()['unlinked_objects'] или готовые строки → подписи списка."""
    if unlinked is None: return list(MOCK_UNLINKED_AFTER_LOAD)
    out = []
    for item in unlinked:
        if isinstance(item, dict):
            fn = item.get("field_name") or item.get("type") or "объект"
            out.append(f"{fn} — объект будет отвязан")
        else:
            out.append(str(item))
    return out


class ReplaceTemplateDialog(QDialog):
    """Подтверждение загрузки .bgt: активный шаблон будет полностью заменён."""

    def __init__(self, parent=None, unlinked=None):
        super().__init__(parent)
        self.setObjectName("dlg_replace_template")
        self.setWindowTitle("Текущий шаблон будет заменён")
        self.resize(480, 280)
        self.unlinked = _format_unlinked(unlinked)
        lab = QLabel("Загрузка файла .bgt полностью заменит активный шаблон (новый шаблон не создаётся).\n"
                     "Объекты, которые будут отвязаны:")
        lab.setWordWrap(True)
        self.list = QListWidget()
        for name in self.unlinked: self.list.addItem(name)
        self.b_yes, self.b_cancel = QPushButton("Заменить"), QPushButton("Отмена")
        self.b_yes.clicked.connect(self.accept); self.b_cancel.clicked.connect(self.reject)
        btns = QHBoxLayout(); btns.addStretch(1); btns.addWidget(self.b_yes); btns.addWidget(self.b_cancel)
        lay = QVBoxLayout(self); lay.addWidget(lab); lay.addWidget(self.list, 1); lay.addLayout(btns)


def confirm_replace_template(parent, unlinked=None):
    """→ True если пользователь подтвердил замену активного шаблона."""
    if replace_template_hook is not None: return bool(replace_template_hook())
    return ReplaceTemplateDialog(parent, unlinked).exec() == QDialog.DialogCode.Accepted


class TemplateTools:
    """«Режим шаблона» / «✓ Сохранить шаблон» / «Менеджер шаблонов»."""

    def __init__(self, parent, editor=None):
        self.parent, self.editor, self.template_mode, self.act_mode, self.act_save = parent, editor, False, None, None
        self._saving = False

    def bind(self, act_mode, act_save):
        self.act_mode, self.act_save = act_mode, act_save; self.set_template_mode(False)

    def _api(self):
        return getattr(self.editor, "api", None) or getattr(self.parent, "api", None)

    def set_template_mode(self, on):
        on = bool(on)
        if not on and self.template_mode and not self._saving:
            if self._dirty():
                if not self.confirm_discard():
                    if self.act_mode is not None: self.act_mode.setChecked(True)
                    return self.template_mode
                self.discard()
            else:
                self._drop_snapshot(commit=True)
        elif on and not self.template_mode:
            if not self._begin():
                if self.act_mode is not None: self.act_mode.setChecked(False)
                return self.template_mode
        self.template_mode = on
        if self.act_save is not None: self.act_save.setEnabled(on)
        if self.act_mode is not None and self.act_mode.isChecked() != on: self.act_mode.setChecked(on)
        if on: self._snap = self._snapshot()
        if self.editor is not None: self.editor.set_template_mode_banner(on)
        return self.template_mode

    def _snapshot(self):
        api = self._api()
        if api is None: return None
        style = api.get_template_style() if hasattr(api, "get_template_style") else None
        return [api.list_elements(sd) for sd in ("front", "back")] + [api.get_background(sd) for sd in ("front", "back")] + [style]

    def _dirty(self):
        return getattr(self, "_snap", None) is not None and self._snapshot() != self._snap

    confirm_hook = None   # тесты: lambda -> bool

    def confirm_discard(self):
        if self.confirm_hook is not None: return bool(self.confirm_hook())
        return QMessageBox.question(self.parent, "Режим шаблона", "Выйти из режима шаблона без сохранения?\nНесохранённые изменения будут отменены.",
                                    QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel) == QMessageBox.StandardButton.Discard

    def _begin(self):
        api = self._api()
        if api is None or not hasattr(api, "begin_template_edit"): return True
        try:
            if api.get_template_edit_state() is None:
                api.begin_template_edit()
            return True
        except ValueError as e:
            QMessageBox.warning(self.parent, "Режим шаблона", str(e))
            return False

    def _drop_snapshot(self, commit=True):
        api = self._api()
        if api is None or not hasattr(api, "get_template_edit_state"): return None
        if api.get_template_edit_state() is None: return None
        return api.commit_template_edit() if commit else api.cancel_template_edit()

    def discard(self):
        """«Не сохранять»: вернуть шаблон к снимку Backend (cancel_template_edit)."""
        api = self._api()
        if api is not None and hasattr(api, "cancel_template_edit"):
            api.cancel_template_edit()
        if self.editor is not None: self.editor.reload()
        return True

    def save_template(self):
        if not self.template_mode: return None
        api = self._api()
        r = api.commit_template_edit() if api is not None and hasattr(api, "commit_template_edit") else None
        self._saving = True
        try: self.set_template_mode(False)
        finally: self._saving = False
        if self.editor is not None: self.editor.reload()
        return r

    def open_manager(self, exec_=True):
        d = TemplateManagerDialog(self.parent, api=self._api())
        if exec_: d.exec()
        return d


class TemplateManagerDialog(QDialog):
    """Список шаблонов: активировать, редактировать, удалить; сохранить/загрузить .bgt (макет)."""

    def __init__(self, parent=None, templates=None, api=None):
        super().__init__(parent); self.setWindowTitle("Менеджер шаблонов"); self.resize(580, 380)
        self.api = api or getattr(parent, "api", None)
        self.list = QListWidget()
        self.b_activate, self.b_edit, self.b_delete = (QPushButton(t) for t in ("Активировать", "Редактировать", "Удалить"))
        self.b_save_file = QPushButton("Сохранить шаблон в файл…")
        self.b_load_file = QPushButton("Загрузить шаблон из файла…")
        self.b_export, self.b_import = self.b_save_file, self.b_load_file   # прежние имена для совместимости тестов
        self.b_close = QPushButton("Закрыть")
        self.b_activate.clicked.connect(self.activate)
        self.b_edit.clicked.connect(self.edit)
        self.b_delete.clicked.connect(self.delete)
        self.b_save_file.clicked.connect(self.save_to_file)
        self.b_load_file.clicked.connect(self.load_from_file)
        self.b_close.clicked.connect(self.accept)
        note = QLabel("Файл .bgt полностью заменяет активный шаблон (новый шаблон не создаётся).")
        note.setObjectName("lbl_bgt_note"); note.setStyleSheet("color:#9A5B00;")
        side = QVBoxLayout()
        for b in (self.b_activate, self.b_edit, self.b_delete, self.b_save_file, self.b_load_file):
            b.setMinimumWidth(220); side.addWidget(b)
        side.addStretch(1); side.addWidget(self.b_close)
        h = QHBoxLayout(); h.addWidget(self.list, 1); h.addLayout(side)
        lay = QVBoxLayout(self); lay.addWidget(QLabel("Шаблоны проекта:")); lay.addLayout(h); lay.addWidget(note)
        in_mode = bool(getattr(getattr(parent, "template_tools", None), "template_mode", False))
        self.b_load_file.setEnabled(not in_mode)
        self.b_load_file.setToolTip("В режиме шаблона загрузка недоступна" if in_mode else "Заменить активный шаблон из файла .bgt")
        if templates is not None: self._fill(templates)
        else: self.reload()

    def _ask_bgt_path(self, kind, title, save=True):
        if bgt_path_hook is not None: return bgt_path_hook(kind)
        start = ""
        api = self.api
        if api is not None:
            src = Path(str(getattr(api, "db_path", "") or ""))
            if src and str(src) not in (":memory:", ""):
                start = str(src.with_suffix(".bgt"))
        fn = QFileDialog.getSaveFileName if save else QFileDialog.getOpenFileName
        p, _ = fn(self, title, start, "Шаблон (*.bgt)"); return p or None

    def save_to_file(self):
        """Экспорт активного шаблона: QFileDialog сам спрашивает о перезаписи; Backend overwrite=True."""
        if self.api is None or not hasattr(self.api, "export_template"):
            return stub_message(self, "Сохранить шаблон в файл", STUB)
        path = self._ask_bgt_path("export", "Сохранить шаблон в файл…", save=True)
        if not path: return None
        try:
            dest = self.api.export_template(path, overwrite=True)
        except (ValueError, OSError) as e:
            show_save_error(self, e); return None
        return dest

    def load_from_file(self):
        """Загрузка .bgt полностью заменяет активный шаблон. В режиме шаблона кнопка выключена."""
        if not self.b_load_file.isEnabled(): return False
        if self.api is None or not hasattr(self.api, "import_template"):
            return stub_message(self, "Загрузить шаблон из файла", STUB)
        path = self._ask_bgt_path("import", "Загрузить шаблон из файла…", save=False)
        if not path: return None
        try:
            preview = self.api.preview_template_file(path)
        except (ValueError, OSError, FileNotFoundError) as e:
            show_save_error(self, e); return None
        unlinked = (preview or {}).get("unlinked_objects") or []
        if not confirm_replace_template(self, unlinked): return False
        try:
            r = self.api.import_template(path)
        except Exception as e:
            # TemplateEditActiveError / ValueError
            show_save_error(self, e); return None
        self.reload()
        parent = self.parent()
        ed = getattr(parent, "layout_editor", None) if parent is not None else None
        if ed is not None: ed.reload()
        return r

    def reload(self):
        rows = []
        if self.api is not None:
            rows = [(t["id"], t["name"], t["active"]) for t in self.api.list_templates()]
        self._fill(rows)

    def _fill(self, rows):
        self.list.clear()
        for row in rows or []:
            if len(row) == 2: name, active = row; tid = name
            else: tid, name, active = row
            it = QListWidgetItem(name + ("   — активный" if active else ""))
            it.setData(Qt.ItemDataRole.UserRole, tid)
            if active:
                f = it.font(); f.setBold(True); it.setFont(f)
            self.list.addItem(it)
        if self.list.count(): self.list.setCurrentRow(0)

    def _tid(self):
        it = self.list.currentItem()
        return it.data(Qt.ItemDataRole.UserRole) if it else None

    def _err(self, title, e):
        QMessageBox.warning(self, title, str(e))

    def activate(self):
        tid = self._tid()
        if tid is None or self.api is None: return False
        try: self.api.set_active_template(tid)
        except ValueError as e:
            self._err("Активировать шаблон", e); return False
        self.reload()
        parent = self.parent()
        if parent is not None and hasattr(parent, "refresh_all"): parent.refresh_all()
        return True

    def edit(self):
        tid = self._tid()
        if tid is None: return False
        if self.api is not None:
            try:
                active = self.api.get_active_template()["id"]
                if tid != active: self.api.set_active_template(tid)
            except ValueError as e:
                self._err("Редактировать шаблон", e); return False
        parent = self.parent()
        self.accept()
        if parent is not None and hasattr(parent, "refresh_all"): parent.refresh_all()
        tt = getattr(parent, "template_tools", None)
        if tt is not None: tt.set_template_mode(True)
        return True

    def delete(self):
        tid = self._tid()
        if tid is None or self.api is None: return False
        it = self.list.currentItem()
        name = it.text().replace("   — активный", "") if it else str(tid)
        if QMessageBox.question(self, "Удалить шаблон", f"Удалить шаблон «{name}»?") != QMessageBox.StandardButton.Yes:
            return False
        try: r = self.api.delete_template(tid)
        except ValueError as e:
            self._err("Удалить шаблон", e); return False
        self.reload()
        parent = self.parent()
        if parent is not None and hasattr(parent, "refresh_all"): parent.refresh_all()
        return r

def format_smartid_report(result):
    """Текст отчёта импорта .csd/.csp — только отображение полученных данных."""
    result = result or {}
    rep = result.get("report") or {}
    def _n(v):
        if isinstance(v, int):
            return v
        return len(v or [])
    imported, skipped, guessed = _n(rep.get("imported")), _n(rep.get("skipped")), _n(rep.get("guessed"))
    created = list(rep.get("created_fields") or [])
    warnings = list(rep.get("warnings") or [])
    persons = int(result.get("persons_imported") or 0)
    lines = [
        f"Импортировано объектов: {imported}",
        f"Пропущено объектов: {skipped}",
        f"Догадок при разборе: {guessed}",
    ]
    if created:
        lines.append("Созданы поля: " + ", ".join(str(x) for x in created))
    else:
        lines.append("Новых полей не создано.")
    lines.append(f"Добавлено записей: {persons}")
    if warnings:
        lines.append("Предупреждения:")
        for w in warnings:
            lines.append(f"• {w}")
    else:
        lines.append("Предупреждений нет.")
    return "\n".join(lines)


class SmartIdImportReportDialog(QDialog):
    """Окно отчёта после открытия .csd/.csp."""

    def __init__(self, result, parent=None):
        super().__init__(parent)
        self.result = result or {}
        self.setObjectName("dlg_smartid_import_report")
        self.setWindowTitle("Отчёт об импорте")
        self.resize(520, 380)
        text = QTextEdit(); text.setReadOnly(True); text.setObjectName("txt_smartid_report")
        text.setPlainText(format_smartid_report(self.result))
        ok = QPushButton("ОК"); ok.setDefault(True); ok.clicked.connect(self.accept)
        lay = QVBoxLayout(self); lay.addWidget(QLabel("Импорт из Smart ID Designer")); lay.addWidget(text, 1)
        btns = QHBoxLayout(); btns.addStretch(1); btns.addWidget(ok); lay.addLayout(btns)


def show_smartid_import_report(parent, result):
    """Показать отчёт. Тесты подменяют диалог через smartid_report_hook."""
    if smartid_report_hook is not None:
        return smartid_report_hook(result)
    d = SmartIdImportReportDialog(result, parent)
    d.exec()
    return d
