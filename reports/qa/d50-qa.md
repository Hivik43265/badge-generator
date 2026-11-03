# QA D50 (release/s13-s14 поверх origin/main dc651e8)
Cherry-pick: Backend db5d65b→d394b93; Frontend 2c9ce60→2295cfc, 26aa629→f799cab. Без push и CI.

Затронуты только файлы: .github/workflows/build-windows.yml (+17), ui/qa_click_all.py (−1, локальный import QImage), tests/test_d50_selftest_no_fixture.py (новый).

## Прогоны (offscreen)
- --self-test с fixture: 106/106, rc=0.
- --self-test без tests/fixtures/face_astronaut.jpg: 106/106, rc=0, 0 FAIL. Файл возвращён на место.
- Шаг workflow «Self-test without test fixtures» прогнан локально как bash-скрипт (RUNNER_TEMP=/tmp/rt): rc=0, 106/106, FAIL нет, fixture восстановлен trap'ом.
- pytest 429 passed (было 428, +1 test_d50; длительность ~75 с из-за двух прогонов самопроверки).
- click_all 106/106; e2e_stage13 67/67; e2e_stage13b 61/61; e2e_stage14 59/59; e2e_d47 20/20.

## Локальные импорты до использования
AST-проверка: имя, импортированное внутри функции, используется в ней (или во вложенных) раньше строки импорта. На старой версии qa_click_all находит ошибку D50 (QImage, строка 172 / import 218). На ui/qa_click_all.py, ui/self_test.py, ui/smoke_test.py после исправления — 0 находок. pyflakes этот случай не ловит.

## Правила D50
Изменений схемы нет; новых зависимостей нет (requirements не тронуты); новых публичных API нет (badge_backend не тронут). **PASS.**

## Замечание
Шаг CI ищет подстроку «FAIL» во всём логе. Если в имени или доказательстве PASS-проверки встретится «FAIL», шаг даст ложный красный. Надёжнее искать по началу строки: grep -q '^FAIL'.
