"""Badge Generator backend (no UI). Структура: db/, render/, services/."""
CARD_W_MM, CARD_H_MM, DPI = 85.6, 53.98, 300
CARD_W_PX, CARD_H_PX = 1011, 638
GRID_DPI = 254
UNIT_MM = 0.1
CARD_W_UNITS, CARD_H_UNITS = 856, 540  # 85,6 × 54,0 мм на сетке 0,1 мм


def mm_to_px(mm: float, dpi: int = DPI) -> int:
    return round(mm / 25.4 * dpi)


def px_to_mm(px, dpi: int = DPI) -> float:
    return px * 25.4 / dpi


def units_to_mm(u) -> float:
    """Единицы 0,1 мм → мм. Округление до 0,01 мм: 856 * 0.1 иначе даёт 85.60000000000001."""
    return round(float(u) * UNIT_MM, 2)


def mm_to_units(mm) -> int:
    return round(mm / UNIT_MM)


def units_to_px(u, dpi: int = DPI) -> int:
    return round(u * dpi / GRID_DPI)


def px_to_units(px, dpi: int = DPI) -> int:
    return round(px * GRID_DPI / dpi)
