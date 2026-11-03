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
