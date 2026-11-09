"""Badge Generator backend (no UI). Структура: db/, render/, services/."""
CARD_W_MM, CARD_H_MM, DPI = 85.6, 53.98, 300
CARD_W_PX, CARD_H_PX = 1011, 638
def mm_to_px(mm: float, dpi: int = DPI) -> int:
    return round(mm / 25.4 * dpi)
