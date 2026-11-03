# QA D47 (release/s13-s14 поверх origin/main 630bb86)

Cherry-pick: eb2cccd→2f83a9c (D47.1), 2d23552→785ef6f (D47.2), 686fa7e→1253e25 (D47.3), 481fc0b→9cb2dc7 (D47.4), Frontend 4e315d4→8e6839f (self-test). Без push и сборки.

## Прогоны (offscreen)
pytest 423 passed; --self-test 104/104; click_all 104/104; e2e_stage13 67/67; e2e_stage13b 61/61; e2e_stage14 59/59; e2e_d47 5/8 (3 FAIL = D48, см. ниже).

## Требования Архитектора
1. **PASS.** Тест закрывает соединения (closing). Аудит sqlite3.connect: sources.py (_ro, копия legacy, work_path) — всё через closing(); importer — workbook закрывается в finally; api.py restore — try/finally; db.connect/testing — возвращают соединение вызывающему.
2. **PASS с оговоркой.** test_db_import_leaves_no_open_handles (/proc/self/fd) ловит удерживаемое соединение (e2e_d47: инъекция → fd найден). Но при откате 785ef6f на Linux падает только test_close_reraises_when_unlink_fails: старый код на CPython закрывал соединения сборкой мусора, исходная ошибка воспроизводится лишь на Windows. Окончательное подтверждение — Windows CI.
3. **PASS.** Spec: SystemExit без cv2/каскада; в отчёт о бандле добавлены cv2 и selftest_face.jpg; CI: «required in bundle» для каскада, cv2 и ассета.
4. **PASS.** --self-test вызывает load_photo_for_edit + detect_face_crop на selftest_face.jpg → (50,16,224,288). Нет ассета → FAIL, rc=1; нет каскада → FAIL (RuntimeError), rc=1. Замечание: проверяется crop is not None, точные координаты не сравниваются.

## Дубли / API
Новых публичных функций нет. _selftest_face_crop (ui/backend_api.py) — приватный, использует существующие load_photo_for_edit/detect_face_crop, не дублирует их. Ассет одобрен Архитектором.

## Тесты не потеряны
Собрано id: 630bb86 = 418, сейчас 423; +5 новых (test_d47_handles ×3, test_d47_selftest_asset ×2), удалённых нет. «413» у Backend = 418 − 5 deselected golden в Windows CI (или их main без QA-мерджей).

## D48 (Frontend, OPEN): Sheet.close() теперь бросает — UI молчит
ui/dialogs.py:128-132 close_sheets(): `except Exception: pass`. При исключении в set_file/reject/closeEvent диалог не падает (PASS), но ошибка не показывается, а временная копия .db остаётся на диске. Нужно: вывести сообщение в лог диалога или статус, например «Не удалось удалить временный файл: …». Проверка: reports/qa/e2e_d47.py.

# QA D48 (cherry-pick Backend 48d3e30→53e9130, Frontend 480ce99→3a6e658)
Прогоны: pytest 427 passed; --self-test 104/104; click_all 104/104; e2e_stage13 67/67; e2e_stage13b 61/61; e2e_stage14 59/59; e2e_d47 16/16 (8 старых + 8 новых D48).

- Sheet.close() бросает только OSError: unlink → except OSError: log + raise. Своего класса исключений у Backend нет. **PASS**
- close_sheets ловит только OSError и пишет в журнал по-русски с именем файла: «Не удалось закрыть источник «bg_import_….db» (временная копия не удалена): …». Прочие исключения пробрасываются, остальные листы при этом закрываются. **PASS**
- При закрытии диалога (done/closeEvent) один повтор close(); после освобождения файла копия удаляется. **PASS**
- Сквозная проверка: close() упал → копия осталась → новый процесс (BackendAPI → db.connect) удалил её (возраст 7 ч). **PASS**
- Чистится только свой каталог и свой префикс: чужой файл и свежая копия (<6 ч) не тронуты. Ошибка очистки не ломает старт (logging.exception). **PASS**
- Самотест: достаточно «лицо найдено», координаты не сравниваются — по решению Архитектора.
- Новых публичных API нет: _cleanup_stale_work_copies, _work_dir, _close_list приватные; у close_sheets добавлен необязательный final=False, совместимо. Дублей нет.

## Решения Backend без утверждения Архитектора
1. Отдельный каталог <tempdir>/BadgeGenerator-import/.
2. Шаблон имени bg_import_*.db, включая -journal/-wal/-shm.
3. Порог возраста 6 ч: более свежие копии не удаляются, даже если они от этого же упавшего процесса.
4. Очистка внутри db.connect, один раз за процесс (глобальный флаг), а не явным шагом старта приложения.
5. Старые bg_import_*.db в корне tempdir от версий до D48 не чистятся.
Замечание: при постоянной блокировке ошибка пишется в журнал дважды (первая попытка и повтор).
