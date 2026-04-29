import gfx

BORDER = 7
ROWS = 26
COLS = 32
BLACK = 0
WHITE = 15
FILL = "0123456789ABCDEFGHIJKLMNOPQRS"


def _line_text(row):
    return ("{:02d} ".format(row) + FILL)[:COLS]


def _draw_test_pattern():
    gfx.set_border(BORDER)
    gfx.cls(BLACK)
    for row in range(ROWS):
        gfx.print_string(0, row * 8, _line_text(row + 1), BLACK, WHITE)


def run():
    gfx.init()
    _draw_test_pattern()

if __name__ == "__main__":
    run()
