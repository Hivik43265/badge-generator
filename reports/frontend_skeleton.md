# BG-Frontend: отчёт по каркасу UI (2026-11-03)

Код: /workspace/badge_generator/ui, запуск: `.venv/bin/python main.py`.
Автотест: `QT_QPA_PLATFORM=offscreen .venv/bin/python ui/smoke_test.py` — ALL OK.
Скриншоты: screenshot.png, screenshot_layout.png, screenshot_preview.png.

## Экраны
- main_window.py — главное окно: меню Файл (Импорт, Экспорт, Печать, Выход), вкладки Записи / Макет / Предпросмотр.
- records_table.py — таблица: колонки из person_fields + чекбокс print_mark, поиск, добавить/изменить/удалить.
- record_form.py — форма записи + настройки фото (photo_config только выбранной записи).
- layout_editor.py — холст 1011x638 px, front/back, перемещение элементов (ресайз и панель свойств — следующий этап).
- preview.py — показывает только результат render_card().
- Диалоги импорта/экспорта/печати (QPrintDialog → services/print) — после API Backend.

## Вызовы Backend (через ui/backend_api.py, сейчас заглушки)
list_person_fields, list_persons, get_person, save_person, delete_person, set_print_mark,
list_template_elements(side), save_template_elements(side, elements), get_background(side),
render_card(person_id, side), import_csv, export_cards, print (services/print — добавить).

## Соблюдение правил
Нет SQL и собственного рендера в UI. photo_config по v1.0: '0;0;1.0;0;0;0', целые px, angle по часовой.
