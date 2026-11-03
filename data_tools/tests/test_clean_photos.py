import csv
import pytest
from PIL import Image
import clean_photos
from conftest import tree_hash

def test_clean_copies_and_reports(sets, tmp_path):
    src = sets / "zero_byte_and_broken" / "photos"
    before = tree_hash(src)
    out = tmp_path / "out"
    mapping, rejected = clean_photos.clean(src, out)
    assert tree_hash(src) == before  # исходники не тронуты
    assert mapping == [("img_1.webp", "0001.webp"), ("IMG_2.JPG", "0002.jpg"), ("img_10.png", "0003.png")]
    assert dict(rejected) == {"empty.jpg": "zero_byte", "broken.jpg": "broken", "notes.txt": "unsupported"}
    assert sorted(p.name for p in out.iterdir()) == ["0001.webp", "0002.jpg", "0003.png", "mapping.csv", "rejected.csv"]
    assert (out / "0002.jpg").read_bytes() == (src / "IMG_2.JPG").read_bytes()  # без трансформаций
    rows = list(csv.DictReader(open(out / "rejected.csv", encoding="utf-8")))
    assert {r["reason"] for r in rows} == {"zero_byte", "broken", "unsupported"}

def test_dry_run_writes_nothing(sets, tmp_path):
    src = sets / "zero_byte_and_broken" / "photos"; before = tree_hash(src)
    clean_photos.main([str(src), str(tmp_path / "o"), "--dry-run"])
    assert not (tmp_path / "o").exists() and tree_hash(src) == before

def test_start_digits_and_report_dir(sets, tmp_path):
    src = sets / "clean" / "photos"; before = tree_hash(src)
    clean_photos.main([str(src), str(tmp_path / "o"), "--start", "7", "--digits", "3", "--report-dir", str(tmp_path / "r")])
    assert sorted(p.name for p in (tmp_path / "o").iterdir())[0] == "007.jpg"
    assert (tmp_path / "r" / "mapping.csv").exists() and tree_hash(src) == before

def test_refuses_same_or_nested_out(sets):
    src = sets / "clean" / "photos"
    with pytest.raises(SystemExit): clean_photos.clean(src, src)
    with pytest.raises(SystemExit): clean_photos.clean(src, src / "sub")

def test_refuses_nonempty_out(sets, tmp_path):
    (tmp_path / "x").write_text("1")
    with pytest.raises(SystemExit): clean_photos.clean(sets / "clean" / "photos", tmp_path)

def test_natural_sort():
    assert sorted(["a10", "a2", "A1"], key=clean_photos.natural_key) == ["A1", "a2", "a10"]
