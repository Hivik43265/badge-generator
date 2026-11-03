# Фикстуры photo_config

Генерация: `python testdata/make_testsets.py --fixtures`. PNG: режим RGB, без альфа-канала,
без метаданных, `compress_level=0`; повторная генерация даёт побайтно идентичные файлы.
Координаты в пикселях, (0,0) — левый верхний угол, bbox = (x0, y0, x1, y1) включительно.
`markers.json` — точные пиксели {name, x, y, color:[r,g,b]} для автоматической проверки.
Рендер-тесты и эталонные PNG — зона Backend (`/workspace/badge_generator/tests/`).

## portrait_300x400.png — 300×400, #1

| Элемент | Позиция |
|---|---|
| size | (300, 400) |
| marker | 42 |
| TL red square | (0, 0, 41, 41) |
| TR green circle | (258, 0, 299, 41) |
| BL blue triangle | (0, 358, 41, 399) |
| BR yellow diamond | (258, 358, 299, 399) |
| center crosshair | (150, 200) |
| crosshair arm | 30 |
| arrow UP tip | (90, 60) |
| arrow shaft x | 90 |
| index label center | (204, 248) |
| magenta anchor dot center | (90, 280) |
| anchor dot radius | 8 |

Контрольные пиксели (markers.json):

- TL_red_square: (4, 36) = (255, 0, 0)
- TR_green_circle: (279, 34) = (0, 200, 0)
- BL_blue_triangle: (4, 394) = (0, 0, 255)
- BR_yellow_diamond: (279, 368) = (255, 210, 0)
- center_crosshair: (150, 200) = (0, 0, 0)
- magenta_anchor_dot: (90, 280) = (255, 0, 255)
- arrow_tip_black: (90, 64) = (0, 0, 0)

## portrait_600x800.png — 600×800, #2

| Элемент | Позиция |
|---|---|
| size | (600, 800) |
| marker | 85 |
| TL red square | (0, 0, 84, 84) |
| TR green circle | (515, 0, 599, 84) |
| BL blue triangle | (0, 715, 84, 799) |
| BR yellow diamond | (515, 715, 599, 799) |
| center crosshair | (300, 400) |
| crosshair arm | 60 |
| arrow UP tip | (180, 120) |
| arrow shaft x | 180 |
| index label center | (408, 496) |
| magenta anchor dot center | (180, 560) |
| anchor dot radius | 17 |

Контрольные пиксели (markers.json):

- TL_red_square: (4, 79) = (255, 0, 0)
- TR_green_circle: (558, 77) = (0, 200, 0)
- BL_blue_triangle: (4, 794) = (0, 0, 255)
- BR_yellow_diamond: (558, 725) = (255, 210, 0)
- center_crosshair: (300, 400) = (0, 0, 0)
- magenta_anchor_dot: (180, 560) = (255, 0, 255)
- arrow_tip_black: (180, 124) = (0, 0, 0)

## landscape_400x300.png — 400×300, #3

| Элемент | Позиция |
|---|---|
| size | (400, 300) |
| marker | 42 |
| TL red square | (0, 0, 41, 41) |
| TR green circle | (358, 0, 399, 41) |
| BL blue triangle | (0, 258, 41, 299) |
| BR yellow diamond | (358, 258, 399, 299) |
| center crosshair | (200, 150) |
| crosshair arm | 30 |
| arrow UP tip | (120, 45) |
| arrow shaft x | 120 |
| index label center | (272, 186) |
| magenta anchor dot center | (120, 210) |
| anchor dot radius | 8 |

Контрольные пиксели (markers.json):

- TL_red_square: (4, 36) = (255, 0, 0)
- TR_green_circle: (379, 34) = (0, 200, 0)
- BL_blue_triangle: (4, 294) = (0, 0, 255)
- BR_yellow_diamond: (379, 268) = (255, 210, 0)
- center_crosshair: (200, 150) = (0, 0, 0)
- magenta_anchor_dot: (120, 210) = (255, 0, 255)
- arrow_tip_black: (120, 49) = (0, 0, 0)
