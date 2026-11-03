# Этап 11 — QA (Контролёр), 2026-11-03

## Прогоны (Linux, offscreen)
- pytest: **256 passed** (254 + 2 новых tests/test_frozen_paths.py)
- ui/smoke_test.py: **ALL OK**
- reports/qa/e2e_check.py: **31/31 PASS**
- reports/qa/e2e_stage10.py: **20/20 PASS**. Ложное срабатывание 1c снято: добавлено исключение `_only_unit_assert`. Файл ui/smoke_test.py пропускается, только если ВСЕ строки с «Гость» там — `assert element_caption(...)`.

## Правка badge_backend/db.py (frozen-режим)
- Объём правки минимальный: `_frozen_data_dir()`, ветка frozen в `default_db_path()`, fallback пути к schema.sql через `_MEIPASS`. Вне frozen поведение не изменилось (это покрыто тестом).
- Во frozen-режиме, если каталог не задан или лежит внутри _MEIPASS, БД кладётся в `%APPDATA%\BadgeGenerator\project.db`; без APPDATA — в `~/.BadgeGenerator`. Во временную папку она не попадает. Явный каталог вне _MEIPASS используется как задан.
- Дублирования нет: в ui/ путь берётся только через `_api.default_db_path(ROOT)` (ui/backend_api.py:19). В data_tools/ и main.py логики путей нет.
- Вердикт: это исправление дефекта упаковки (без него БД терялась бы при выходе). Исключение из заморозки кода оправдано и согласуется с правилом «пути и БД — зона Backend».

## exe (локальные артефакты /tmp/pyi_dist, Linux ELF)
- BadgeSmoke (19.6 МБ): `SMOKE OK: schema v3, 2 png, pdf 48172 bytes`, rc=0. Предупреждение о пустой стороне back ожидаемо.
- BadgeGenerator (96 МБ): работал 15 с без падения (rc=124 — выход по timeout), создал $APPDATA/BadgeGenerator/project.db.
- Заявление Backend подтверждено. Ограничение: это сборка под Linux, Windows .exe не собирался.

## Заблокировано
- Зелёный workflow на windows-latest и скачивание артефакта: нет git-репозитория и remote, gh не авторизован. Нужно решение Ивана (создать репозиторий, выдать доступ), затем git init и push, затем запуск workflow.
- Шрифты в exe не вшиты, на Windows используется системный Arial. Проверить кириллицу по чек-листу Windows.

## Дефекты
Новых нет. Рекомендация: принять этап 11 условно, окончательно — после зелёного CI и запуска exe на Windows.
