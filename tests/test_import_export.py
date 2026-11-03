import csv, json
from pathlib import Path
import pytest
from PIL import Image
from openpyxl import Workbook
from badge_backend import api
from badge_backend.services.headers import map_headers, slugify, split_fio, header_key
from badge_backend.services.importer import read_table, parse_file
DT = Path(__file__).resolve().parent.parent / "data_tools" / "testdata" / "sets"

def test_map_headers_synonyms():
    assert map_headers(["ФИО", "Фамилия", " last name ", "E-Mail", "Тел.", "Фото", "", None, "Цех", "Цех"]) == \
        ["__fio__", "last_name", None, "email", "phone", "photo_path", None, None, "tsekh", "tsekh_2"]
    assert map_headers(["Surname", "Имя"], {"last_name": ["Surname"]}) == ["last_name", "first_name"]
    assert slugify("Табельный №") == "tabelnyy_n" and slugify("!!!") == "field"
    assert split_fio("Ёлкин Пётр Сергеевич Оглы") == ("Ёлкин", "Пётр", "Сергеевич Оглы")
    assert header_key("  Ё_лка ") == "е лка"

@pytest.mark.skipif(not (DT / "messy_headers" / "persons_raw.xlsx").exists(), reason="нет набора Data")
def test_messy_headers_xlsx(con):
    r = api.import_file(con, DT / "messy_headers" / "persons_raw.xlsx")
    assert r.validator == "data_tools.validate_import.validate_records" and r.added >= 1
    p = api.list_persons(con)[0]["fields"]
    assert p["last_name"] == "Ёлкин" and p["first_name"] == "Пётр" and p["middle_name"] == "Сергеевич"
    assert p["position"] == "Директор" and p["email"] == "e@example.com"
    labels = {f["name"]: f["label"] for f in api.list_fields(con)}
    assert labels["position"].strip() == "ДОЛЖНОСТЬ" and labels["last_name"] == "Фамилия"

def _csv(path, rows, enc="utf-8-sig", delim=";"):
    with open(path, "w", newline="", encoding=enc) as f: csv.writer(f, delimiter=delim).writerows(rows)
    return path

@pytest.mark.parametrize("enc,delim", [("utf-8-sig", ";"), ("cp1251", ";"), ("utf-8", ","), ("cp1251", "\t")])
def test_csv_encodings_delims(con, tmp_path, enc, delim):
    p = _csv(tmp_path / "a.csv", [["Фамилия", "Имя", "Отдел кадров"], ["Иванов", "Иван", "ОК"], ["", "", ""],
                                  ["Петров", "Пётр", ""]], enc, delim)
    r = api.import_file(con, p)
    assert (r.added, r.skipped) == (2, 0)
    assert api.list_persons(con)[0]["fields"] == {"last_name": "Иванов", "first_name": "Иван", "otdel_kadrov": "ОК"}
    assert {f["name"]: f["label"] for f in api.list_fields(con)}["otdel_kadrov"] == "Отдел кадров"

def test_xlsx_photo_and_errors(con, tmp_path):
    (tmp_path / "ph").mkdir(); Image.new("RGB", (30, 40), "red").save(tmp_path / "ph" / "a.jpg")
    wb = Workbook(); ws = wb.active
    for row in [["Фамилия", "Имя", "Фото", "photo_config", "Табельный номер"],
                ["Иванов", "Иван", "a.jpg", "5;5;1.5;0;0;10", 123],
                [None, None, None, None, None],
                ["Петров", None, "a.jpg", None, 2],
                ["Сидоров", "Олег", "none.jpg", None, 3]]: ws.append(row)
    wb.save(tmp_path / "p.xlsx")
    r = api.import_file(con, tmp_path / "p.xlsx", photo_dir=tmp_path / "ph")
    assert (r.added, r.skipped) == (1, 2)
    codes = {(e["row"], e["code"]) for e in r.errors}
    assert (4, "REQUIRED_MISSING") in codes and (5, "PHOTO_NOT_FOUND") in codes
    p = api.list_persons(con)[0]
    assert p["photo_path"] == "a.jpg" and p["photo_config"] == "5;5;1.5;0;0;10"
    assert p["fields"]["employee_id"] == "123" and "photo_path" not in p["fields"]

def test_unsupported_format(con, tmp_path):
    (tmp_path / "x.doc").write_text("x")
    with pytest.raises(ValueError): api.import_file(con, tmp_path / "x.doc")

def test_default_photo_config_on_import(con, tmp_path):
    api.import_file(con, _csv(tmp_path / "a.csv", [["Фамилия", "Имя"], ["А", "Б"]]))
    assert api.list_persons(con)[0]["photo_config"] == "0;0;1.0;0;0;0"

# --- экспорт ---
def test_export_png(demo_db, tmp_path):
    c, ids, d = demo_db
    files = api.export_png(c, None, tmp_path / "out", ("front", "back"), base_dir=d, allow_missing_photo=True)
    assert sorted(f.name for f in files) == sorted(f"{i}_{s}.png" for i in ids[:2] for s in ("front", "back"))
    im = Image.open(files[0]); assert im.size == (1011, 638) and round(im.info["dpi"][0]) == 300

def _pdf_pages(path):
    import re
    data = Path(path).read_bytes()
    boxes = re.findall(rb"/MediaBox\s*\[\s*([\d.\s]+)\]", data)
    return [tuple(float(v) for v in b.split()) for b in boxes]

def test_export_pdf_pages_cr80(demo_db, tmp_path):
    c, ids, d = demo_db
    out = api.export_pdf(c, None, tmp_path / "c.pdf", ("front", "back"), base_dir=d, allow_missing_photo=True)
    pages = _pdf_pages(out); assert len(pages) == 4      # 2 помеченных × 2 стороны
    for b in pages:
        w_mm, h_mm = (b[2] - b[0]) / 72 * 25.4, (b[3] - b[1]) / 72 * 25.4
        assert abs(w_mm - 85.6) < 0.1 and abs(h_mm - 54.0) < 0.1
    assert len(_pdf_pages(api.export_pdf(c, [ids[2]], tmp_path / "one.pdf", "front", base_dir=d, allow_missing_photo=True))) == 1

def test_export_errors_and_mark(demo_db, tmp_path):
    c, ids, d = demo_db
    with pytest.raises(ValueError): api.export_pdf(c, [], tmp_path / "e.pdf")
    with pytest.raises(ValueError): api.export_png(c, ids, tmp_path, ("top",))
    assert api.set_print_mark(c, ids[:2], False) == 2 and api.list_persons(c, only_marked=True) == []
    assert api.set_print_mark(c, [ids[2]], True) == 1 and [p["id"] for p in api.list_persons(c, True)] == [ids[2]]
    assert api.mark_printed(c, []) == 0 and api.set_print_mark(c, []) == 0
