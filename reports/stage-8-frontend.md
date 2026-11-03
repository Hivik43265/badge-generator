# Этап 8 — Frontend: D5 (печать → «напечатано», колонка printed_at)

Изменено только `ui/` (`backend_api.py`, `records_table.py`, `main_window.py`, `smoke_test.py`). В `badge_backend/`, `data_tools/` и `.venv` правок нет. Переход на breaking change из `reports/stage-8-backend.md`.

## Изменения
1. **Отметка «к печати»:** чекбокс «Печать», «Отметить все» и «Снять отметки» работают через `BackendAPI.set_print_mark(ids, value)` → `api.set_print_mark(con, ids, value: bool) -> int`. `printed_at` при этом не меняется.
2. **После успешной печати:** печать не отменена, без ошибки и страниц больше 0. Пользователь видит «Печать прошла успешно? Снять отметки с N записей?». При «Да» вызывается `BackendAPI.mark_printed(ids)` → `api.mark_printed(con, printed_ids) -> int`: одной транзакцией `print_mark=0` и `printed_at=now`, после чего таблица обновляется. `ids` — уникальные `person.id` из snapshot печати. «Нет», отмена или ошибка ничего не меняют. Флаг `False` и обходной `clear_print_marks` удалены.
3. **Колонка «Напечатано»** (последняя, только для чтения): `printed_at` = None показывается пустой ячейкой. ISO 8601 со смещением переводится в локальный пояс в формате `dd.MM.yyyy HH:mm`. Сортировка идёт по `datetime.timestamp()`, то есть по реальному моменту, а не по строке; пустые значения в начале. Во всплывающей подсказке исходная ISO-строка.
4. **Миграция:** `BackendAPI.open_db` открывает базу через `api.connect()`, которая сама применяет миграции. Затем проверяется `PRAGMA user_version` ≥ `db.LATEST`; если версия ниже, явно вызывается `db.migrate(con)`, а при неудаче выдаётся ошибка. В тесте старая v1-БД открывается и доводится до v2 без потери данных.

## Проверка вызовов
- `rg -n "mark_printed\(" ui`:
```
ui/main_window.py:111:        changed = self.api.mark_printed(ids)   # print_mark=0 + printed_at=now (атомарно, Backend)
ui/smoke_test.py:224:# --- в ui/ нет вызовов mark_printed(..., value) ---
ui/smoke_test.py:234:ok("AST-проверка ui/: нет вызовов mark_printed(..., value)")
ui/backend_api.py:73:    def mark_printed(self, ids):
ui/backend_api.py:75:        return _api.mark_printed(self.con, list(ids))
```
- Все вызовы соответствуют новой сигнатуре. Фасад: `_api.mark_printed(self.con, ids)`, UI: `self.api.mark_printed(ids)`. Строки в `smoke_test.py` — это комментарий и сообщение. Смоук-тест дополнительно проверяет это через AST: вызовов `mark_printed(..., value)` нет.

## D7 — без прямого SQL в ui/
1. `BackendAPI.schema_version()` возвращает `badge_backend.api.get_schema_version(self.con)` (после `connect()` это 2). `open_db` вызывает только функции Backend: `api.connect`, `get_schema_version` и, если версия ниже `db.LATEST`, `db.migrate`. SQL и PRAGMA в ui/ больше нет.
2. Миграционная проверка в смоук-тесте переписана на Backend-хелпер `badge_backend.testing.create_legacy_db(path, version=1)`. Сначала `api.connect(str(p))` и `api.get_schema_version(con) == 2`. Затем второй legacy-файл открывается через UI (`switch_db`): `schema_version() == 2`, запись создаётся через API, `printed_at is None`, колонка «Напечатано» пустая. `sqlite3` из ui/ удалён. Прежний тест не только проверял схему, но и сохранность данных, вставленных в v1; без прямого SQL такие данные вставить нельзя, поэтому эта часть остаётся за тестами Backend (`tests/test_d5_printed_at.py`).
3. AST-проверка `_no_sql_in_ui()` в `ui/smoke_test.py` проходит по всем `ui/*.py` и ищет вызовы атрибутов `.execute/.executemany/.executescript`, строковые константы с «PRAGMA» без учёта регистра, `import sqlite3` и `from sqlite3 …`. Узлы самой функции-чекера исключаются, а имена в ней собираются из частей. Отдельно проверено, что чекер срабатывает: на временном файле с `import sqlite3`, `c.execute("x")` и `"pragma foo"` он нашёл все 3 нарушения.
4. Комментарий `sqlite3.IntegrityError` в `layout_editor.py` переформулирован. `rg -n -i "pragma|\.execute|sqlite3" ui` ничего не находит.

## Вывод `QT_QPA_PLATFORM=offscreen .venv/bin/python ui/smoke_test.py`
```
OK   импорт: отмена через QProgressDialog → cancelled=True, ничего не добавлено
OK   импорт: added=2 skipped=1 errors=2 warnings=2
OK   таблица: колонки ['Должность', 'Таб. номер', 'Подразделение', 'Фамилия', 'Имя', 'Отчество', 'Напечатано'] (Мусор исключён, label задан)
OK   импорт: require_photo флаг передаётся (прогон с отменой)
OK   поиск, чекбокс «Печать» → set_print_mark, printed_at не тронут; колонка «Напечатано» пустая, read-only
OK   форма: photo_config=10;0;1.5;0;0;15 только у #1
OK   палитра v1: ['text', 'field', 'photo', 'image', 'rect'] (qr/barcode скрыты)
OK   пересечение: 'Гость' (610,40,360x70) → предупреждение [(13, 2)], подсветка #d00000
OK   'Гость' перенесён в (40, 556, 300, 56): пересечений ни с одним элементом нет (9 проверено)
OK   редактор: delete_element, стороны
OK   предпросмотр: рендер Backend
OK   экспорт PNG: ['1_front.png', '1_back.png']
OK   нет фото: предупреждение ['#2 Петрова Анна'], «Нет» → экспорт не выполнен
OK   нет фото: «Да» → allow_missing_photo=True, PDF создан, Экспорт: PDF: 1; с плейсхолдером «нет фото»: [2]
OK   отмена PDF: Экспорт: отменено пользователем (файл не создан)
OK   отмена PNG: Экспорт: отменено пользователем; файлов: 0; с плейсхолдером «нет фото»: [2]
OK   печать: 2 стр. (только print_mark=1)
OK   печать без фото: «Нет» → отмена; «Да» → 4 стр., плейсхолдер у [2]
OK   отмена печати: Печать: отменено пользователем; страниц: 0; с плейсхолдером «нет фото»: [2]
OK   D5 «Нет»: вопрос про 2 записи, отметки не изменены [1, 2]
OK   D5 отмена печати: вопрос не задан, отметки не изменены
OK   D5 печать не состоялась: вопрос не задан, отметки не изменены
OK   D5 printed_at: 2026-11-03T16:46:03+03:00 → в таблице «03.11.2026 16:46»; у #3 пусто
OK   D5 «Да»: сняты отметки только с напечатанных [1, 2], #3 остался отмеченным, таблица обновлена
OK   «Напечатано»: локальный пояс dd.MM.yyyy HH:mm, сортировка по datetime
OK   AST-проверка ui/: нет вызовов mark_printed(..., value)
OK   create_legacy_db(v1) → connect/open_db → v2; printed_at=None через API, колонка «Напечатано» пустая
OK   D7 AST: в ui/*.py (9 файлов) нет прямого SQL (вызовы exec*, служебные команды БД, импорт драйвера)
OK   БД :memory: — экспорт PDF через snapshot в QThread
OK   Открыть БД / вкладки
ALL OK; tmp = /tmp/bg_ui_ppacc3xp
```
