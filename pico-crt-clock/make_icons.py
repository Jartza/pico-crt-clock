# ── icon building helpers ─────────────────────────────────────────────────
# Icons are 32×16 px, one byte per pixel (value 0–15).
# Helpers run once at boot; the icon bytearrays persist for the session.

def _px(b, x, y, v, w=32, h=16):
    if 0 <= x < w and 0 <= y < h:
        b[y * w + x] = v

def _fill_circle(b, cx, cy, r, v, w=32, h=16):
    r2 = r * r
    for dy in range(-r, r + 1):
        y = cy + dy
        if 0 <= y < h:
            for dx in range(-r, r + 1):
                x = cx + dx
                if 0 <= x < w and dx*dx + dy*dy <= r2:
                    b[y * w + x] = v

def _fill_rect(b, x0, y0, x1, y1, v, w=32, h=16):
    for y in range(max(0, y0), min(h, y1 + 1)):
        for x in range(max(0, x0), min(w, x1 + 1)):
            b[y * w + x] = v

def _line(b, x0, y0, x1, y1, c, w=32, h=16):
    dx = abs(x1 - x0)
    sx = 1 if x0 < x1 else -1
    dy = -abs(y1 - y0)
    sy = 1 if y0 < y1 else -1
    err = dx + dy

    while True:
        if 0 <= x0 < w and 0 <= y0 < h:
            b[y0 * w + x0] = c
        if x0 == x1 and y0 == y1:
            break
        e2 = err << 1
        if e2 >= dy:
            err += dy
            x0 += sx
        if e2 <= dx:
            err += dx
            y0 += sy

def _lightning(b, x0, y0, x1, y1, x2, y2, x3, y3, c):
    _line(b, x0, y0, x1, y1, c)
    _line(b, x1, y1, x2, y2, c)
    _line(b, x2, y2, x3, y3, c)

# ── sky icons (32×16) ─────────────────────────────────────────────────────
def _make_sky_sun():
    b = bytearray(32 * 16)
    _fill_circle(b, 15, 7, 4, 15)          # disc, white
    # Cardinal rays
    _px(b, 15,  0, 11);  _px(b, 15,  1, 11)   # N
    _px(b, 15, 13, 11);  _px(b, 15, 14, 11)   # S
    _px(b,  8,  7, 11);  _px(b,  9,  7, 11)   # W
    _px(b, 21,  7, 11);  _px(b, 22,  7, 11)   # E
    # Diagonal rays
    _px(b,  9,  2, 11);  _px(b,  8,  1, 11)   # NW
    _px(b, 21,  2, 11);  _px(b, 22,  1, 11)   # NE
    _px(b,  9, 12, 11);  _px(b,  8, 13, 11)   # SW
    _px(b, 21, 12, 11);  _px(b, 22, 13, 11)   # SE
    return b

def _make_sky_cloud():
    b = bytearray(32 * 16)
    _fill_circle(b,  8, 11, 5, 11)         # left lobe
    _fill_circle(b, 16,  7, 6, 11)         # centre lobe (taller)
    _fill_circle(b, 24, 11, 5, 11)         # right lobe
    _fill_rect  (b,  3, 11, 28, 15, 11)   # fill between lobes at bottom
    return b

def _make_sky_partly():
    # Small sun upper-right, cloud lower-left overlapping it
    b = bytearray(32 * 16)
    _fill_circle(b, 23,  4, 4, 15)         # sun disc
    _px(b, 23, 0, 12); _px(b, 28, 0, 12)  # sun rays
    _px(b, 29, 4, 12); _px(b, 28, 8, 12)
    _fill_circle(b,  9, 12, 4, 11)         # cloud left lobe
    _fill_circle(b, 16,  9, 5, 11)         # cloud centre (overlaps sun)
    _fill_circle(b, 23, 12, 4, 11)         # cloud right lobe
    _fill_rect  (b,  5, 12, 26, 15, 11)   # fill cloud bottom
    return b

# ── precipitation icons (32×16) ───────────────────────────────────────────

def _make_precip_rain():
    b = bytearray(32 * 16)
    # Short diagonal streaks: 4 columns × 3 rows, fading from top
    for cx in (3, 11, 19, 27):
        for cy in (1, 6, 11):
            for d in range(3):
                _px(b, cx + d, cy + d * 2,     15 - d * 4)
                _px(b, cx + d, cy + d * 2 + 1,  8 - d * 2)
    return b

def _make_precip_snow():
    b = bytearray(32 * 16)
    flakes = [(4,2),(12,2),(20,2),(28,2),
                (8,8),(16,8),(24,8),
                (4,13),(12,13),(20,13),(28,13)]
    for sx, sy in flakes:
        _px(b, sx, sy, 15)                  # centre bright
        for dx, dy in ((0,1),(0,-1),(1,0),(-1,0)):
            _px(b, sx+dx, sy+dy, 9)         # cross arms dim
    return b

def _make_precip_drizzle():
    b = bytearray(32 * 16)
    drops = [(4,1),(12,1),(20,1),(28,1),
                (8,6),(16,6),(24,6),
                (4,11),(12,11),(20,11),(28,11)]
    for sx, sy in drops:
        _px(b, sx, sy,     10)
        _px(b, sx, sy + 1, 6)
    return b

def _make_precip_thunder():
    b = bytearray(32 * 16)
    # left small
    _lightning(b,  8,  1, 11,  4,  8,  7, 12, 11, 9)
    # center big, more zigzag
    _lightning(b, 13,  0, 18,  5, 14,  9, 21, 16, 15)
    _lightning(b, 14,  0, 19,  5, 15,  9, 22, 16, 15)
    # right small
    _lightning(b, 22,  4, 25,  7, 23, 9, 26, 12, 11)
    return b

def _make_gray_bar():
    b = bytearray(256 * 32)
    row = bytearray(x // 16 for x in range(256))
    for y in range(32):
        b[y * 256:(y + 1) * 256] = row
    return b

# Create bytearray python initialization code from bytearray
# contents, using hexadecimal values and nice print formatting,
# 16 bytes per line for readability.
# for example:
# b = bytearray([
#    0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09, 0x0A, 0x0B, 0x0C, 0x0D, 0x0E, 0x0F,
# ])
def _print_bytearray_hex(name, b):
    hex_str = ",\n    ".join(
        ", ".join("0x{:02X}".format(x) for x in b[i:i+16])
        for i in range(0, len(b), 16)
    )
    return("{} = bytearray([\n    {},\n])\n\n".format(name, hex_str))


# ── construct icons ───────────────────────────────────────────────────────
sky_sun        = _make_sky_sun()
sky_partly     = _make_sky_partly()
sky_cloud      = _make_sky_cloud()
precip_rain    = _make_precip_rain()
precip_snow    = _make_precip_snow()
precip_drizzle = _make_precip_drizzle()
precip_thunder = _make_precip_thunder()
# gray_bar       = _make_gray_bar()

# Write the icons as python code to file called icons.py, using
# _print_bytearray_hex() for each icon.
f = open("icons.py", "w")
f.write("# This file is generated by make_icons.py; do not edit directly.\n\n")
f.write(_print_bytearray_hex("sky_sun", sky_sun))
f.write(_print_bytearray_hex("sky_partly", sky_partly))
f.write(_print_bytearray_hex("sky_cloud", sky_cloud))
f.write(_print_bytearray_hex("precip_rain", precip_rain))
f.write(_print_bytearray_hex("precip_snow", precip_snow))
f.write(_print_bytearray_hex("precip_drizzle", precip_drizzle))
f.write(_print_bytearray_hex("precip_thunder", precip_thunder))
f.close()
