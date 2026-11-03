# QA D49 (release/s13-s14 поверх origin/main b083ce0)
Cherry-pick: Backend a7f8d32→49b3b1f; Frontend 96e7d20→bd4343c и 5f90697→fab3007. Без push и CI.

Прогоны (offscreen): pytest 428 passed; --self-test 106/106; click_all 106/106; e2e_stage13 67/67; e2e_stage13b 61/61; e2e_stage14 59/59; e2e_d47 20/20.

## (1) Spec / CI — PASS
- REQUIRED_QT: bin/Qt6PrintSupport.dll. OPTIONAL_QT: plugins/printsupport/windowsprintersupport.dll → в отчёте OPTIONAL-FOUND/OPTIONAL-MISSING.
- Проверка CI `-like "MISSING*"`: оператор -like якорится на начало строки и не учитывает регистр. Сымитировано через fnmatch (pwsh на box нет): строка «OPTIONAL-MISSING\t…» → не совпадает; «MISSING\tbin/Qt6PrintSupport.dll\t» → совпадает, CI упадёт. «FOUND\tcv2\t*» не путается с OPTIONAL-FOUND.
- Spec по-прежнему бросает SystemExit без cv2 и без каскада (строки 20, 22).

## (2) --self-test печать — PASS
- Печать идёт через существующий MainWindow.do_print(printer=QPrinter PdfFormat) → print_snapshot Backend; собственного кода печати нет. Hooks clear_marks/confirm/warning восстанавливаются в finally; PDF удаляется.
- Шаблон только во временном проекте самотеста: текст «Тест Кириллица» и Code128. В продукте шаблона по умолчанию нет: в новой БД template_elements = 0.
- Норма: PDF 71923 байт, 2 стр.; рендер min яркость 0; «Шаблон пуст» нет.
- Принудительные сбои, все дают FAIL и rc=1:
  - do_print возвращает ошибку;
  - PDF 0 байт;
  - create_element ничего не создаёт → «Шаблон пуст»;
  - render_card_db возвращает белое изображение.
- До ч.3 (шаблон пуст) PDF был 41 КБ, но страницы пустые: 85,7×54 мм, без текста, белые. Теперь ч.3 это ловит.
- Предупреждение печати: «Предупреждение: сторона 'back' шаблона пуста» и «с плейсхолдером «нет фото»: [1]» — ожидаемо, на обороте нет элементов. Не ошибка; при желании добавить элемент на оборот или игнорировать в самотесте.

## Замечание: слой
Самотест вызывает badge_backend.api.render_card_db напрямую, в обход BackendAPI. Это не дубль: функция та же. Но это обход слоя UI→BackendAPI — так же делают qa_click_all и smoke_test, это тестовый код, не продукт. Рекомендация: BackendAPI(a49).render_card(pid49, "front") → QImage, и проверить, что не все пиксели белые. Так проверяется и pil_to_qimage, тот же путь, что у превью.

## Тесты не потеряны
Собранные id в релизе до и после fab3007 одинаковы: 428 = 428. На ветке Frontend stage-14 у меня 413 passed: нет 10 тестов test_d38_d39_import_photos (RC этапа 13) и 5 тестов test_d48_cleanup (Backend main), они есть только в релизе. 388 у Frontend на их ветке не воспроизводится; вероятно, другой рабочий каталог или устаревшая база. Новых публичных API нет.
