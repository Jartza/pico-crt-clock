from common import *


BORDER = 7
ROWS = 26
COLS = 32
FILL = "0123456789ABCDEFGHIJKLMNOPQR|"


def _line_text(row):
    return ("{:02d} ".format(row) + FILL)[:COLS]


def _draw_test_pattern():
    gfx.set_border(BORDER)
    gfx.cls(BLACK)
    for row in range(ROWS):
        gfx.print_string(0, row * 8, _line_text(row), BLACK, WHITE)


def run(pin=None, **extras):
    gfx.init()
    _draw_test_pattern()

    counter = 0
    while True:
        gfx.wait_vblank()
        active, counter = check_pin_stable(pin, 0, counter)
        if not active:
            return
        time.sleep_ms(50)


if __name__ == "__main__":
    run()
