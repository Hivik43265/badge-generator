"""Этап 5: импорт 600 строк (CSV разных кодировок/разделителей, xlsx) без потерь, PDF на 50+ карточек."""
from badge_backend.testing import import_with_fields as _imp
import csv, json, re, sqlite3, time
from pathlib import Path
import pytest
from openpyxl import Workbook
from badge_backend import api
from data_tools.validate_import import validate_records

N = 600
HEAD = ["Фамилия", "Имя", "Отчество", "Должность", "Отдел", "E-mail", "Телефон", "Примечание"]
KEYS = ["last_name", "first_name", "middle_name", "position", "department", "email", "phone", "primechanie"]

def make_rows(n=N):
    fam = ["Ёлкин", "Щукин", "Объедков", "Пьянзин", "Зайцев-Ёжиков", "Мельникова"]
    rows = []
    for i in range(n):
        rows.append([f"{fam[i % 6]}{i}", ["Пётр", "Алёна", "Юлия", "Эдуард"][i % 4], "Семёнович",
                     f'Инженер, "ведущий" {i}', f"Отдел «Ёж», цех; {i % 7}", f"user{i}@пример.рф".replace("пример.рф", "example.com"),
                     f"+7 900 {i:03d}-{i % 100:02d}-11", f'текст с "кавычками", запятой; и ё № {i}'])
    return rows

def expected(rows):
    return [dict(zip(KEYS, r)) for r in rows]

def write_csv(p, rows, enc, delim):
    with open(p, "w", newline="", encoding=enc) as f:
        csv.writer(f, delimiter=delim, quoting=csv.QUOTE_MINIMAL).writerows([HEAD, *rows])
    return p

def check_lossless(con, rows, rep):
    exp = expected(rows)
    assert (rep.added, rep.skipped, rep.errors) == (N, 0, [])
    got = [p["fields"] for p in api.list_persons(con)]
    assert len(got) == N and got == exp           # полевое сравнение с исходником
    # повторная валидация того, что в БД, — без ошибок
    assert validate_records([{k: v for k, v in g.items()} for g in got]) == []

CSV_CASES = [("utf-8-sig", ";"), ("utf-8-sig", ","), ("utf-8", ";"), ("utf-8", ","), ("cp1251", ";"), ("cp1251", ",")]
TIMINGS = {}

@pytest.mark.parametrize("enc,delim", CSV_CASES)
def test_csv_600_lossless(tmp_path, enc, delim):
    rows = make_rows(); p = write_csv(tmp_path / "p.csv", rows, enc, delim)
    con = api.connect(tmp_path / "db.sqlite")
    t = time.perf_counter(); rep = _imp(api.import_file, con, p); dt = time.perf_counter() - t
    check_lossless(con, rows, rep); TIMINGS[f"csv {enc} '{delim}'"] = (N, rep.added, dt)
    assert dt < 3.0

def test_xlsx_600_lossless(tmp_path):
    rows = make_rows(); wb = Workbook(); ws = wb.active; ws.append(HEAD)
    for r in rows: ws.append(r)
    wb.save(tmp_path / "p.xlsx")
    con = api.connect(tmp_path / "db.sqlite")
    t = time.perf_counter(); rep = _imp(api.import_file, con, tmp_path / "p.xlsx"); dt = time.perf_counter() - t
    check_lossless(con, rows, rep); TIMINGS["xlsx"] = (N, rep.added, dt)
    assert dt < 5.0

def test_import_single_transaction(tmp_path):
    """Импорт = одна транзакция: один COMMIT; при сбое посередине — откат всего."""
    rows = make_rows(); p = write_csv(tmp_path / "p.csv", rows, "utf-8", ";")
    from badge_backend.testing import prepare_fields
    con = api.connect(tmp_path / "db.sqlite"); stmts = []; prepare_fields(con, p)
    con.set_trace_callback(stmts.append)
    api.import_file(con, p)
    con.set_trace_callback(None)
    assert sum(1 for s in stmts if s.strip().upper().startswith("COMMIT")) == 1
    # откат: триггер роняет 300-ю вставку
    con2 = api.connect(tmp_path / "db2.sqlite")
    con2.execute("CREATE TRIGGER boom BEFORE INSERT ON persons WHEN (SELECT COUNT(*) FROM persons) >= 300 "
                 "BEGIN SELECT RAISE(ABORT, 'boom'); END")
    nf = len(prepare_fields(con2, p))
    with pytest.raises(sqlite3.DatabaseError): api.import_file(con2, p)
    assert con2.execute("SELECT COUNT(*) FROM persons").fetchone()[0] == 0
    assert con2.execute("SELECT COUNT(*) FROM person_fields").fetchone()[0] == nf   # D24: импорт полей не трогает

def test_header_only_quotes_sniff(tmp_path):
    """Разделитель внутри кавычек первой строки данных не сбивает автоопределение."""
    p = tmp_path / "q.csv"
    p.write_text('Фамилия,Имя\n"Иванов; мл.","Иван, ""Ваня"""\n', encoding="utf-8")
    con = api.connect(); rep = _imp(api.import_file, con, p)
    assert rep.added == 1 and api.list_persons(con)[0]["fields"] == {"last_name": "Иванов; мл.", "first_name": 'Иван, "Ваня"'}

def test_export_pdf_60_cards(tmp_path):
    from badge_backend import demo
    con = api.connect(); demo.make_photo(tmp_path / "p.jpg"); demo.make_logo(tmp_path / "demo_logo.png"); demo.build_demo(con)
    ids = [api.create_person(con, {"last_name": f"Ёлкин{i}", "first_name": "Пётр", "employee_id": f"{i:06d}"},
                             "p.jpg", print_mark=1) for i in range(60)]
    t = time.perf_counter()
    out = api.export_pdf(con, None, tmp_path / "all.pdf", ("front", "back"), base_dir=tmp_path)
    dt = time.perf_counter() - t
    data = out.read_bytes()
    boxes = re.findall(rb"/MediaBox\s*\[\s*([\d.\s]+)\]", data)
    assert len(re.findall(rb"/Type\s*/Page[^s]", data)) == len(boxes) == 120
    for b in boxes:
        x0, y0, x1, y1 = map(float, b.split())
        assert abs((x1 - x0) / 72 * 25.4 - 85.6) < 0.1 and abs((y1 - y0) / 72 * 25.4 - 54.0) < 0.1
    TIMINGS["pdf 60×2"] = (60, 120, dt)

def test_zz_write_timings():
    Path(__file__).with_name("stage5_timings.json").write_text(json.dumps(TIMINGS, ensure_ascii=False, indent=1))

def test_cells_preserved_extra_fields(tmp_path):
    """Баг-фикс: переносы строк и двойные пробелы в доп. полях не схлопываются; даты xlsx — ISO."""
    import datetime
    p = tmp_path / "nl.csv"
    p.write_bytes('Фамилия;Имя;Примечание\r\nИванов;Иван;"строка 1\r\nстрока  2"\r\n'.encode("utf-8"))
    con = api.connect(); _imp(api.import_file, con, p)
    assert api.list_persons(con)[0]["fields"]["primechanie"] == "строка 1\nстрока  2"
    wb = Workbook(); ws = wb.active; ws.append(["Фамилия", "Имя", "Дата выдачи", "Код"])
    ws.append(["Ёлкин", "Пётр", datetime.datetime(2026, 11, 3), 7.0]); wb.save(tmp_path / "d.xlsx")
    con = api.connect(); _imp(api.import_file, con, tmp_path / "d.xlsx")
    f = api.list_persons(con)[0]["fields"]
    assert f["data_vydachi"] == "2026-11-03" and f["kod"] == "7"
