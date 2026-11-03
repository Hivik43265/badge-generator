# Этап 13 — QA (Backend)

Объект проверки: локальный коммит **eb00436** (проверялся в чистом worktree `/tmp/wt13`, detached). Frontend вне скоупа, кроме e2e_click_all (по указанию Архитектора). Код продукта не правился, ничего не коммитилось/не пушилось.

## Git
- На момент проверки: origin/main = 507747b, поверх — только eb00436. Backend-часть чистая.
- Незакоммиченное вне `reports/qa`: WIP Frontend (`ui/*`, `main.py`, `ui/errors.py`), скриншоты, `tests/stage5_timings.json` (артефакт тестов).
- **Внимание:** во время проверки в репозитории появились новые локальные коммиты 27d1c18 (D19), f92edf7, 515aae9 (Stage 13 фиксы Backend). Они **не проверены** этим отчётом — требуется повторный прогон.

## Прогоны (eb00436)
| Скрипт | Результат |
|---|---|
| pytest | 312 passed |
| e2e_check.py | 31/31 |
| e2e_stage10.py | 20/20 (узкое исключение 1b для копирования элементов в `export_persons(.db)`) |
| e2e_stage12.py | 28/28 |
| smoke (eb00436) | ALL OK (в рабочем дереве падал из-за WIP Frontend D19 — вне скоупа) |
| **e2e_stage13.py (новый)** | **25/42** |
| **e2e_click_all.py (новый)** | eb00436: 67 PASS / 12 FAIL; рабочее дерево с WIP Frontend: 75 PASS / 2 FAIL |

## e2e_stage13.py — что проходит
photo_path/photo_config round-trip; исходный .db не меняется `open_source` (sha256); save/load mapping, чужой файл → ValueError; 20000 строк во всех форматах, прогресс монотонный; отмена (Event и progress→False) — откат до 0 записей; .xls >65535 → ValueError, файл не создаётся; `auto_match` — обёртка над `headers.map_headers`; одна реализация (ядро `importer.import_records` у `import_file` и `import_rows`; `ui/backend_api.import_file` — фасад, проверка уточнена); нет логики сопоставления и SQL в `ui/`.

Риск (Frontend): `ui/dialogs.py:92` вызывает `map_headers` напрямую (реэкспорт в `ui/backend_api.py:15`), а не `auto_match` — параллельная точка входа, логики не дублирует.

Сигнатура `export_persons` отклоняется от брифа: `(con, path, format=None, ids=None, *, photo_dir=None, csv_encoding='utf-8-sig') -> dict`.

## Дефекты этапа 13 (нумерация с D25; D19–D22 и D24 зарезервированы Архитектором)
| № | Описание | Форматы | Владелец |
|---|---|---|---|
| D25 | Импорт с `validate=True` по умолчанию отклоняет экспортированную запись с пустым `first_name` (REQUIRED_MISSING) — round-trip теряет записи | все 4 | Backend |
| D26 | `auto_match` не учитывает метки полей целевого проекта: «Таб. №»→`tab_n`, «Примечание»→`primechanie`, «Отдел»→`department` вместо существующих `code/note/dept` → поля размножаются | xlsx/xls/csv | Backend |
| D27 | Обрезаются пробелы «  пробелы внутри  » → «пробелы внутри» даже при `validate=False` — не lossless | все 4 | Backend |
| D28 | `print_mark`/`printed_at` не переживают round-trip | xlsx/xls/csv (db OK) | Backend / решение Архитектора (спец. или явно «lossy») |
| D29 | `default_value` полей не переживает round-trip | xlsx/xls/csv (db OK) | Backend / решение Архитектора |
| D30 | e2e_click_all: при выделенной записи `act_queue_toggle`, `act_mark_printed`, `act_mark_unprinted`, `act_card_edit`, `act_card_delete` остаются disabled. Не исключено, что дело в скрипте (выделение через `_select_person`), не диагностировано до конца | — | QA/Frontend, уточнить |


> **D24 (Архитектор):** поля БД задаются только через «Менеджер полей» с типом данных (text/number/date/image/bool); никаких автосозданных и демо-полей; импорт никогда не создаёт поля, кроме импорта из .db с подтверждением. **D26 (QA) — частный случай D24** (auto_match/импорт создаёт дубли полей). Проверки D24 добавлены в e2e_stage13.py (блок «D24-*», ещё не прогонялись).

## e2e_click_all.py — воспроизведение D19–D21 Ивана на Linux (eb00436)
- **D19 воспроизводится**: «Добавить запись» с кириллицей → превью идентично пустому шаблону (diff=0), панель «Поле шаблона | Значение из БД» пустая; в старой БД без `person_fields` значения записываются в ключи `LABELS` (`middle_name/position/department`), а не в поля шаблона.
- **D20/D21 воспроизводятся** (класс: `QAction.triggered(bool)` передаёт `checked=False` в первый параметр слота):
  - `act_settings` → TypeError `argument of type 'bool' is not iterable` (`main_window.py:566`) — в реальном exe PyQt6 падает;
  - `act_capture` → TypeError в `os.path.relpath` (`main_window.py:499`);
  - `act_field_manager`, `act_queue` → `exec_=False`, диалог не открывается.
  Сопоставление с номерами D20/D21 — по комментарию Frontend в WIP (`ui/main_window.py`: «D20/D21: triggered(bool) не передаётся в слот») и `ui/errors.py` (D20 — глобальный перехват). Текстов D20/D21 у QA нет.
- **В рабочем дереве с WIP Frontend** D19/D20/D21 по скрипту исправлены (сценарий «Добавить»: 6/6 PASS). Остались: D30 и отсутствие `act_capture` в WIP (действие удалено или переименовано — Frontend подтвердить).

## Хук для exe
`main.py` в eb00436 не умеет запускать внешний QA-скрипт. Нужен хук: `BadgeGenerator.exe --qa-run <script.py>` → `runpy.run_path` в процессе exe (до `QApplication`/или с ним). В WIP Frontend уже есть `--self-test` (`ui.self_test`); удобно добавить рядом `--qa-run`. До этого e2e_click_all запускается только из исходников (`QT_QPA_PLATFORM=offscreen python reports/qa/e2e_click_all.py`).

## Вердикт
Backend этапа 13 (eb00436) **не принят**: D25–D27 блокируют «lossless round-trip», по D28/D29 нужно решение Архитектора. Новые коммиты 27d1c18/f92edf7/515aae9 нужно перепроверить.


---
# Перепроверка по решениям Архитектора (03.11.2026, ~20:40 Europe/Berlin)

## Git
- HEAD = **de864fc**, origin/main = 507747b, локально сверху **6 коммитов**: eb00436, 27d1c18, f92edf7, 515aae9, b8dfe12 (D24), de864fc. Ничего не запушено.
- Незакоммичено вне `reports/qa`: WIP Frontend — `main.py`, `ui/backend_api.py`, `ui/dialogs.py`, `ui/layout_editor.py`, `ui/main_view.py`, `ui/main_window.py`, `ui/record_form.py`, `ui/records_table.py`, `ui/smoke_test.py`, новые `ui/errors.py`, `ui/photo_block.py`, `ui/self_test.py`, `ui/qa_click_all.py` (в момент прогона синтаксически незавершён); скриншоты `reports/*.png`, `reports/stage-12-actions.md`, `tests/stage5_timings.json`.
- Прогоны «на HEAD» — в чистом worktree de864fc (удалён после прогона).

## Решения Архитектора, отражённые в e2e_stage13.py
D25 — пустое значение только warning, ошибки: FIELD_TYPE и полностью пустая строка; D26 — сопоставление с существующими полями по name, затем по label без учёта регистра/пробелов, полей не создаёт, остальное → `skipped_columns`; D27 — без strip при `validate=False`; D28 — колонки «Напечатано» (да/нет) и «Дата печати» (ДД.ММ.ГГГГ) в xlsx/xls/csv; D29 — потеря `default_value` в табличных форматах ожидаема (информ. PASS), в .db — сохраняется; D24 — импорт .db в тесте идёт с `import_fields=True` (подтверждение). Добавлены приёмочные: новая БД без полей; пустое/битое фото → warning PHOTO_EMPTY/PHOTO_BROKEN.

## Итоги на HEAD de864fc
| Скрипт | Результат |
|---|---|
| e2e_stage13.py | **47/62 PASS** |
| e2e_click_all.py | **78 PASS / 6 FAIL** |
| e2e_click_all.py на рабочем дереве (WIP Frontend, fallback-реализация) | **83 PASS / 0 FAIL** |

### e2e_stage13 — PASS
D24 (новая БД без полей, 5 типов, неизвестный тип → ValueError, csv не создаёт поля, .db без подтверждения не создаёт, с подтверждением — с типом), D26 на всех форматах, D29, приёмка фото (пустое → PHOTO_EMPTY, битое → PHOTO_BROKEN), photo_config, большие файлы, отмена, лимит .xls, дубли логики, нет SQL в ui/.

### e2e_stage13 — FAIL (открыто, Backend)
- **D25** — все 4 формата: `validate=True` даёт `REQUIRED_MISSING` (ошибка) на пустом `first_name`, запись теряется (added=2 из 3). Приёмка: неверный тип («abc» в number) и полностью пустая строка **не** дают ошибок (added=4, errors=[]).
- **D27** — все 4 формата: «  пробелы внутри  » обрезается при `validate=False`.
- **D28** — xlsx/xls/csv: колонок «Напечатано»/«Дата печати» в файле нет; `printed_at` теряется.

## D30 — первопричина: **скрипт, не продукт**
Продукт корректен: `ui/main_window.py:320-322` (`_sync_selection`) включает `act_queue_toggle/act_card_edit/act_card_delete/act_mark_printed/act_mark_unprinted` по `bool(self.records.selected_ids())`; `ui/records_table.py:299-301` (`selected_ids`) и `ui/main_window.py:415-419` (`_select_person`) работают — проверено отдельно: после выделения действия enabled. Причина — порядок в `reports/qa/e2e_click_all.py`: `act_connect`/`act_disconnect`/`act_card_delete` выполнялись в середине прохода и убирали запись/БД, после чего действия честно были disabled. Исправлено в скрипте (разрушающие действия — в конце, `LATE`). На HEAD проверка «все действия доступны» — PASS. **D30 закрыт как дефект QA-скрипта.**

## e2e_click_all — FAIL на HEAD de864fc (всё закрыто в незакоммиченном WIP Frontend)
- D20/D21: `act_settings` → TypeError (`checked=False` в `values`); «Настр. поля», «Очередь печати» не открываются (`exec_=False`).
- D22: `act_capture` ещё есть; у `RecordForm` нет `photo_block` (сценарий «добавить фото → снимок» не выполним).
- На рабочем дереве: 83/0 — D19/D20/D21/D22 по скрипту закрыты, снимок через `PhotoBlock.set_captured` сохраняется в `photos/` (камеры offscreen нет, `shoot()` без камеры не падает). Требуется коммит Frontend и повторный прогон.

## Хук для exe (решение Архитектора)
`--qa-run` отклонён. `reports/qa/e2e_click_all.py` — тонкая обёртка: если импортируется `ui.qa_click_all`, вызывает его `run(argv)`, иначе (модуля нет или он не импортируется) — собственная fallback-реализация с WARN; принудительно — `--fallback`. Сам `ui/qa_click_all.py` пишет Frontend, запуск из exe — через `--self-test`.

## Вердикт
Этап 13 **не принят**: открыты D25, D27, D28 (Backend). D26, D29, D24, приёмка фото — PASS. D30 закрыт (скрипт). Frontend: D20–D22 закрыты только в незакоммиченном WIP.

---
# Проверка на HEAD fd9614b (03.11.2026, ~22:45 Europe/Berlin)

Чистый worktree `fd9614b` (сначала fa29d7d — те же результаты), QA-скрипты — из рабочего дерева `reports/qa`.

| Проверка | Результат |
|---|---|
| pytest | **351 passed** |
| smoke (`ui/smoke_test.py`) | **ALL OK** |
| `main.py --self-test --log <path>` | **exit 0, 85/85 PASS**, исключений в слотах 0 |
| e2e_click_all.py | **exit 0, 85/85** — через `ui.qa_click_all` (WARN fallback: 0) |
| e2e_check.py | **31/31** |
| e2e_stage10.py | **20/20** |
| e2e_stage12.py | **32/32** |
| e2e_stage13.py | **62/62** |

## Изменения ожиданий QA (только по утверждённым решениям)
После `git checkout -- reports/` (Backend) правки в tracked `e2e_check.py`/`e2e_stage10.py` были потеряны и переделаны заново:
- **e2e_check.py**: версия схемы — из `bdb.LATEST` (≥5, v5 data_type, D24); перед импортом поля создаются заранее (`fc()`: `upsert_field` по `headers.LABELS`) — D24, новая БД без полей; наборы duplicates/missing_fields — по D25 ошибки только FIELD_TYPE/EMPTY_ROW, все строки учтены.
- **e2e_stage10.py**: 1a/6 — версия из LATEST; 1b — исключение для копирования макета в `export_persons(.db)` (`table_export.py`), не seed; 8 — ellipse (v4); 9b — инструменты ищутся как QAction `act_tool_<type>` в `main_window.py`, z-порядок через `move_z(d)`.
- **e2e_stage12.py**: 5.1 — `user_version == LATEST ≥ 5` + `data_type`; 1.0/1.2 — **57 действий** (D22: строка 31 реестра зачёркнута, act_capture удалён); 1.3 — act_capture отсутствует; 1.4 — информационно (повтор подписи не дубль); **1.8/1.9 переписаны по новому правилу дублей**: 1.8a уникальные объекты QAction, 1.8b defaultAction ссылается на QAction окна, 1.8c нет отдельных обработчиков функций QAction (`clicked.connect(<slot действия>)`), 1.9 кнопка импорта «Менеджер полей…» = `setDefaultAction(act_field_manager)`, 1.9b подпись по эталону, 1.9c (информ.) запасная ветка без родительского QAction; **D16** — кнопка «Печать», tooltip «Печать списка полей». Подпись «Открыть менеджер полей…» больше не встречается (4acf63b) — дефект на переименование не нужен.

## Проверки
1. **CI** (`.github/workflows/build-windows.yml`): reports/ упоминается только в комментарии (стр. 103); шаг «Self-test (GUI exe --self-test)» без `if:` и без `continue-on-error`, падает при exit≠0 и по таймауту 180 с; `if: always()` — только у загрузки лога. **PASS**.
2. **Диалог импорта этапа 13** (эталон `reports/mockup/reference_import.png`) — **отсутствует**: в `ui/dialogs.py` старый ImportDialog этапа 5.
3. `ui/dialogs.py` **не вызывает `map_headers`** (использует `api.auto_match`, стр. 113). Остался только реэкспорт `ui/backend_api.py:15` (`map_headers, SYNONYMS, LABELS`) — рекомендуется убрать (Frontend, некритично).
4. **SQL в ui/ нет** (AST, e2e_stage12 4.1 / e2e_stage13).
5. **git status вне reports/qa НЕ чистый** (см. ниже).

## Открытые критерии Frontend этапа 13 (нумерация с D31)
| № | Критерий | Состояние | Владелец |
|---|---|---|---|
| D31 | Диалог импорта по эталону: источники xlsx/xls/csv/.db, выбор листа через `open_source`/`read_rows`/`import_rows` | нет: только .xlsx/.csv через `import_file` (`dialogs.py:61,100,161`) | Frontend |
| D32 | Сохранение/загрузка сопоставления (`save_mapping`/`load_mapping`) | нет | Frontend |
| D33 | Превью строк и фото перед импортом | нет (таблица — только сопоставление колонок) | Frontend |
| D34 | Экспорт в xlsx/xls/csv/.db (`export_persons`) из того же `act_export` + tooltip D29 о потере `default_value` | нет: `act_export` = «Экспорт PNG/PDF…» | Frontend (заявлено «в работе») |
| D35 | Импорт .db с подтверждением `import_fields=True` (D24) | нет | Frontend (заявлено «в работе») |
| — | Автосопоставление только через `auto_match` | **есть** | — |
| — | Прогресс и отмена импорта | **есть** (QProgressDialog, откат) | — |
| — | Импорт/Экспорт — те же QAction `act_import`/`act_export` | **есть** (по одному QAction, кнопка менеджера полей — defaultAction) | — |

## Git (на 22:45)
- HEAD = **fd9614b**, origin/main = 507747b, локально +12 коммитов, ничего не запушено.
- **В репозитории незавершённый `git stash pop` с конфликтами** (stash@{0} «stage13-wip2» не снят): `UU ui/dialogs.py`, `UU ui/smoke_test.py`, staged `ui/backend_api.py`, `ui/main_window.py`.
- **Незакоммиченные изменения Backend (не попадут в push):** `badge_backend/api.py`, `badge_backend/render/__init__.py`, `badge_backend/services/photos.py` (ранее также workflow/spec/tests — к этому моменту закоммичены в fa29d7d).
- Незакоммиченное прочее: `reports/mockup/*.png` (reference_field_manager, reference_import, stage13_*), `reports/screens/*` (+ `make_screens.py`).
- QA-коммит выполнен позже, после разрешения конфликтов: **8f7abf9** (только `reports/qa/*.py` и `stage-*-qa.md`).

## Вердикт
Backend этапа 13 — **принят** (D25–D29 закрыты, 62/62, CI self-test обязателен). Frontend D19–D22, D24, D16, 1.9 — **закрыты** (85/85 self-test). Этап 13 в целом **не принят** до D31–D35 (импорт/экспорт по эталону) и приведения git в порядок (конфликт stash, незакоммиченный Backend).


---
# Перепроверка HEAD 8f7abf9 (поверх 91b0208, 2a68954, fd9614b) — 03.11.2026, ~23:00 Europe/Berlin

Чистый worktree 8f7abf9; e2e_stage13.py — с новыми проверками PH-a…PH-d.

| Проверка | Результат |
|---|---|
| pytest | **363 passed** |
| smoke | **ALL OK** |
| `main.py --self-test --log <path>` | **exit 0, 85/85**, исключений в слотах 0 |
| e2e_click_all.py (через `ui.qa_click_all`, без fallback) | **exit 0, 85/85** |
| e2e_check.py | **31/31** |
| e2e_stage10.py | **20/20** |
| e2e_stage12.py | **32/32** |
| e2e_stage13.py | **67/67** |

## Новые проверки (фото как image-поле, единый resolve_photo_path)
- **PH-a** AST по `badge_backend/`, `ui/`, `data_tools/`: нет `join`/`Path()`/`abs_path()`/`/` с `photo_path`/image-полем вне `photos.resolve_photo_path` — **PASS**; grep-вариант информационный (совпадения — только docstring/комментарии).
- **PH-b** `link_field`: photo→text и field→image → `ValueError`; photo→image принимается — **PASS**.
- **PH-c** legacy v1 (только `persons.photo_path`, photo-элемент без поля) → миграция до LATEST=5 → фото рендерится: все 120000 пикселей области отличаются от рендера без фото, центр = цвет фото — **PASS**.
- **PH-d** `missing_photos` проверяет обе стороны (решение Архитектора): нет оборота и нет лица — оба в списке, полная запись — нет — **PASS**.

Примечание: на общем боксе `/tmp/st.log` одновременно перезаписывался self-test другого агента (88/88 на незакоммиченном WIP Frontend с новым диалогом «Экспорт данных»); в таблице — только stdout собственного прогона на HEAD.

## Открытые пункты
| № | Пункт | Владелец |
|---|---|---|
| D31 | Новый диалог импорта по эталону (xlsx/xls/csv/.db, листы, `open_source`/`import_rows`) | Frontend (в работе) |
| D32 | Сохранение/загрузка сопоставления в UI | Frontend |
| D33 | Превью строк и фото перед импортом | Frontend |
| D34 | Экспорт данных xlsx/xls/csv/.db через `act_export` + подсказка D29 | Frontend (в WIP; в чужом WIP-прогоне self-test подсказка D29 ещё не проходила) |
| D35 | Импорт .db с подтверждением `import_fields=True` | Frontend (в работе) |
| — | Реэкспорт `map_headers` в `ui/backend_api.py:15` — убрать | Frontend, некритично |
| — | git вне reports/qa не чистый: WIP Frontend в `ui/*`, `tests/stage5_timings.json`, скриншоты/mockup; stash@{0} «stage13-wip2» не снят | Frontend / Backend |

## Вердикт
Backend этапа 13 (включая 91b0208, 2a68954) — **принят**. Frontend: закоммиченное (D16, D19–D22, D24, плоский Менеджер полей fd9614b) — **принято**. Этап 13 в целом — **не принят** до D31–D35 (новые диалоги импорта/экспорта).

## Перепроверка Frontend c916ec1 (D31–D35), 2026-11-03

Чистый worktree HEAD c916ec1. Команды: pytest 363 passed; smoke ALL OK; `--self-test` 89/89; e2e_click_all 89/89; e2e_check 31/31; e2e_stage10 20/20; e2e_stage12 32/32; e2e_stage13 67/67; **новый e2e_stage13b 29/29**.

| Дефект | Итог | Доказательство (e2e_stage13b) |
|---|---|---|
| D31 импорт xlsx/xls/csv/.db, выбор листа | PASS | xls с 2 листами, список листов, смена листа → превью, импорт выбранного листа, поля не создаются; open_source/read_rows/import_rows Backend |
| D32 сохранить/загрузить привязку | PASS | roundtrip save→load даёт тот же mapping; битый JSON → сообщение |
| D33 превью строк и фото | PASS | таблица превью, «Колонка/Значение», pixmap фото |
| D34 экспорт xlsx/xls/csv/.db через act_export | PASS | 4 файла через ExportDialog (export_persons); подсказка D29 видна для xlsx/xls/csv, скрыта для .db (это QLabel, не tooltip) |
| D35 .db с подтверждением import_fields | PASS | отмена → 0 записей; «Только существующие» → без новых полей; «Создать поля» → поле + default_value |

Дубли: нет. QAction act_import/act_export/act_field_manager по одному; «Менеджер полей…» = setDefaultAction(act_field_manager); ui/ не импортирует openpyxl/xlrd/xlwt/csv/sqlite3; путь к фото в ui/ не вычисляется; реэкспорт map_headers убран.
Замечание (не дубль по правилу, мёртвый код): `BackendAPI.import_file` (ui/backend_api.py:215) больше нигде не вызывается — предложить удалить.

Макет: reports/mockup/reference_import.png ЕСТЬ на диске, но не в git (untracked). Сравнение import.png с эталоном — структура совпадает (лист, заголовок, Поле БД|Тип|Сопоставлено|Колонка, справа фото+значения, превью, прогресс, кнопки привязки). Отличия на решение Архитектора: справа таблица «Колонка|Значение» вместо столбца карточек; добавлены «Фото: папка», «Требовать фото», окно отчёта; в эталоне третья кнопка (подпись нечитаема, «…жавЮСд») отсутствует; в превью два столбца «Фото» (image-поле и photo_path) — путает; экспорт — один диалог с «Что».

Git: c916ec1 закоммичен, stash пуст. Но в основном дереве снова есть незакоммиченные Frontend-правки этапа 14: M ui/backend_api.py, ui/photo_block.py, ui/record_form.py, ui/smoke_test.py, ?? ui/photo_editor.py; M reports/screenshot_*.png; эталоны reports/mockup/*.png не в git.
