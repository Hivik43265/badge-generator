"""Смоук собранного backend (этап 11): migrate в tmp, пустой и непустой рендер, экспорт PNG/PDF.
Выход 0 — успех. Собирается вторым exe (BadgeSmoke.exe) тем же spec."""
import os, sys, tempfile
sys_path_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if not getattr(sys, "frozen", False): sys.path.insert(0, sys_path_root)
from pathlib import Path

def main() -> int:
    from badge_backend import api, db
    from badge_backend.render import render_card
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        con = api.connect(t / "smoke.db")
        assert db.get_schema_version(con) == db.LATEST, "migrate"
        assert db.SCHEMA_PATH.exists(), db.SCHEMA_PATH
        pid = api.create_person(con, {"last_name": "Иванов", "first_name": "Иван"})
        api.update_person(con, pid, print_mark=1)
        img = render_card(api.get_person(con, pid), [], "front")
        assert img.size == (1011, 638), img.size
        api.create_element(con, "rect", 10, 10, 200, 100, style={"stroke": "#000", "stroke_width": 3})
        api.create_element(con, "field", 20, 150, 600, 80, field_name="last_name")
        api.create_element(con, "barcode", 20, 300, 400, 120, static_value="BG-0001")
        api.create_element(con, "qr", 700, 300, 250, 250, static_value="https://example.org")
        api.create_element(con, "line", 20, 600, 900, 0, style={"stroke": "#000", "stroke_width": 2})
        pngs = api.export_png(con, [pid], out_dir=t, allow_missing_photo=True)
        pdf = api.export_pdf(con, [pid], out_path=t / "cards.pdf", allow_missing_photo=True)
        assert len(list(pngs)) == 2 and Path(pdf).stat().st_size > 0
        print("SMOKE OK: schema v%d, %d png, pdf %d bytes" % (db.LATEST, len(list(pngs)), Path(pdf).stat().st_size))
        con.close()
    return 0

if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        import traceback; traceback.print_exc(); print("SMOKE FAIL:", e); sys.exit(1)
