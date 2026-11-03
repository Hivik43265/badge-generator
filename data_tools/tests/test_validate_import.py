import csv
from pathlib import Path
import validate_import as vi
from validate_import import Error
from conftest import tree_hash

def codes(errors): return {(e.row, e.code) for e in errors}

def load(p):
    with open(p, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))

# --- чистые функции ---
def test_validate_records_pure_ok():
    recs = [{"last_name": "Иванов", "first_name": "Иван", "email": "a@b.ru", "phone": "+7 900 111-22-33"}]
    assert vi.validate_records(recs) == []
    assert vi.valid_records(recs, [])[0]["photo_config"] == "0;0;1.0;0;0;0"

def test_validate_records_errors_and_rows():
    recs = [{"last_name": "", "first_name": "Иван"},
            {"last_name": "Петров", "first_name": "Пётр", "email": "bad", "phone": "123", "photo_config": "0;0;1;0.5;0;0"},
            {"last_name": "Петров ", "first_name": "Петр", "email": "BAD"}]
    errs = vi.validate_records(recs, start_row=10)
    assert all(isinstance(e, Error) for e in errs)
    assert codes(errs) == {(10, "REQUIRED_MISSING"), (11, "EMAIL_INVALID"), (11, "PHONE_INVALID"),
                           (11, "PHOTO_CONFIG_INVALID"), (12, "EMAIL_INVALID"), (12, "DUPLICATE")}
    assert vi.valid_records(recs, errs, start_row=10) == []

def test_check_columns():
    assert vi.check_columns(vi.FIELDS) == []
    assert [e.field for e in vi.check_columns(["Фамилия", "first_name"])] == ["last_name"]

def test_photo_config_format():
    ok = ["", None, "0;0;1.0;0;0;0", "-5;3.5;2;10;-4;90"]
    bad = ["0;0;1", "0;0;1.0;0.5;0;0", "0;0;x;0;0;0", "0;0;1;0;0;0;0", "0;0;1,0;0;0;0"]
    assert all(vi.check_photo_config(v) for v in ok)
    assert not any(vi.check_photo_config(v) for v in bad)

# --- наборы ---
def test_clean_set_cli(sets, tmp_path):
    before = tree_hash(sets / "clean")
    rc = vi.main([str(sets / "clean/persons.csv"), "--photos", str(sets / "clean/photos"),
                  "--report", str(tmp_path / "r.csv")])
    assert rc == 0 and tree_hash(sets / "clean") == before
    assert len(load(tmp_path / "valid.csv")) == 5

def test_photo_errors(sets):
    d = sets / "zero_byte_and_broken"
    errs = vi.validate_records(load(d / "persons.csv"), d / "photos", start_row=2)
    assert codes(errs) == {(3, "PHOTO_EMPTY"), (4, "PHOTO_BROKEN"), (5, "PHOTO_NOT_FOUND")}

def test_duplicates(sets):
    errs = vi.validate_records(load(sets / "duplicates/persons.csv"), start_row=2)
    assert codes(errs) == {(4, "DUPLICATE"), (5, "DUPLICATE")}

def test_missing_fields_cli(sets, tmp_path):
    rc = vi.main([str(sets / "missing_fields/persons.csv"), "--report", str(tmp_path / "r.csv")])
    assert rc == 1
    rows = {(int(r["row"]), r["code"]) for r in load(tmp_path / "r.csv")}
    assert rows == {(2, "REQUIRED_MISSING"), (3, "REQUIRED_MISSING"), (4, "EMAIL_INVALID"),
                    (4, "PHONE_INVALID"), (5, "PHOTO_CONFIG_INVALID")}
    assert [r["last_name"] for r in load(tmp_path / "valid.csv")] == ["Ок"]

def test_large(sets):
    d = sets / "large"
    assert vi.validate_records(load(d / "persons.csv"), d / "photos") == []
    assert len(load(d / "persons.csv")) == 1000

def test_cli_missing_column(tmp_path):
    f = tmp_path / "a.csv"; f.write_text("Фамилия,first_name\nИванов,Иван\n", encoding="utf-8")
    assert vi.main([str(f), "--report", str(tmp_path / "r.csv")]) == 1
    assert load(tmp_path / "r.csv")[0]["code"] == "MISSING_COLUMN"

def test_no_mapping_or_excel_in_module():
    src = Path(vi.__file__).read_text(encoding="utf-8")
    assert "openpyxl" not in src and "--mapping" not in src and "__fio__" not in src
