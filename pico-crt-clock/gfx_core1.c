// gfx_core1.c
// Runs entirely on core1.
// Call gfx_core1_launch() once from core0 early in main() — before
// MicroPython starts.  After that, core0 never touches this code.

#include "pico/multicore.h"
#include "pico/stdlib.h"
#include "hardware/pio.h"
#include "gfx_queue.h"
#include "cvideo.h"
#include "graphics.h"
#include "charset.h"

// ── shared state definitions (declared extern in gfx_queue.h) ───────────────
gfx_queue_t          gfx_queue      = {0};
volatile uint8_t     gfx_blit_buf[GFX_BLIT_BUFSIZE];
volatile bool        gfx_blit_busy  = false;
volatile bool        gfx_deinit_done = false;

// ── double-size character renderer ───────────────────────────────────────────
// Renders one glyph at 2× scale (16×16 px) by writing 2×2 pixel blocks
// directly to the bitmap.  Uses the Spectrum 48K charset (96 glyphs from
// ASCII 32, 8 bytes per glyph, MSB = leftmost pixel).
// bitmap/width/height are all provided by cvideo.h.
static void print_char_2x(int x, int y, unsigned char c,
                           unsigned char bc, unsigned char fc) {
    if (c < 32 || c > 127) c = 32;
    const unsigned char *glyph = &charset[(c - 32) * 8];
#ifdef USE_COLOUR_LUT
    unsigned char bg = colour_lut[bc & 15];
    unsigned char fg = colour_lut[fc & 15];
#else
    unsigned char bg = colour_base + bc;
    unsigned char fg = colour_base + fc;
#endif
    for (int row = 0; row < 8; row++) {
        unsigned char bits = glyph[row];
        int py = y + row * 2;
        for (int col = 0; col < 8; col++) {
            unsigned char v = (bits & (0x80u >> col)) ? fg : bg;
            int px = x + col * 2;
            // Bounds: need px+1 < width and py+1 < height.
            // Casting to unsigned folds the px<0 check into one comparison.
            if ((unsigned)px < (unsigned)(width - 1) &&
                (unsigned)py < (unsigned)(height - 1)) {
                bitmap[ py      * width + px    ] = v;
                bitmap[ py      * width + px + 1] = v;
                bitmap[(py + 1) * width + px    ] = v;
                bitmap[(py + 1) * width + px + 1] = v;
            }
        }
    }
}

// ── command dispatcher ───────────────────────────────────────────────────────
static void dispatch(const gfx_cmd_t *c) {
    switch (c->type) {

        case CMD_WAIT_VBLANK:
            wait_vblank();
            break;

        case CMD_CLS:
            wait_vblank();          // cls always waits first — clean flash
            cls(c->c);
            break;

        case CMD_SET_BORDER:
            set_border(c->c);       // safe to call directly (writes sync tables)
            break;

        case CMD_PLOT:
            plot(c->x0, c->y0, c->c);
            break;

        case CMD_LINE:
            draw_line(c->x0, c->y0, c->x1, c->y1, c->c);
            break;

        case CMD_HLINE:
            draw_horizontal_line(c->y0, c->x0, c->x1, c->c);
            break;

        case CMD_CIRCLE:
            draw_circle(c->x0, c->y0, c->x1 /*r*/, c->c, c->filled);
            break;

        case CMD_TRIANGLE:
            draw_triangle(c->x0, c->y0, c->x1, c->y1,
                          c->x2, c->y2, c->c, c->filled);
            break;

        case CMD_POLYGON:
            draw_polygon(c->x0, c->y0, c->x1, c->y1,
                         c->x2, c->y2, c->x3, c->y3,
                         c->c, c->filled);
            break;

        case CMD_PRINT_CHAR:
            print_char(c->x0, c->y0, (int)c->str[0], c->bc, c->fc);
            break;

        case CMD_PRINT_STRING:
            print_string(c->x0, c->y0, (char *)c->str, c->bc, c->fc);
            break;

        case CMD_PRINT_STRING_2X: {
            int cx = c->x0;
            const char *s = c->str;
            while (*s) {
                print_char_2x(cx, c->y0, (unsigned char)*s, c->bc, c->fc);
                cx += 16;   // 8 px glyph × 2 = 16 px per character
                s++;
            }
            break;
        }

        case CMD_SCROLL_UP:
            scroll_up(c->c, c->scroll_rows);
            break;

        case CMD_BLIT:
            // pixel data already in gfx_blit_buf, copied by core0 before push
            blit((const void *)gfx_blit_buf, 0, 0, c->sw, c->sh,
                 c->x0, c->y0);
            __dmb();
            gfx_blit_busy = false;  // release buffer — core0 may write next sprite
            __sev();                // wake core0 if it is spinning in gfx_blit()
            break;

        case CMD_DEINIT:
            deinit_cvideo();
            __dmb();
            gfx_deinit_done = true;
            __sev();            // wake core0 from its spin in gfx_deinit()
            while (1) __wfe(); // park — video engine is stopped
            break;             // unreachable

        default:
            break;
    }
}

// ── core1 entry point ────────────────────────────────────────────────────────
static void core1_main(void) {
    // ALL video IRQ and DMA setup happens here — on core1 — so that
    // DMA_IRQ_1 and PIO0_IRQ_0 are owned by core1's NVIC.
    initialise_cvideo();

    // Allow MicroPython's flash write path to temporarily pause this core.
    // The lockout victim flag survives soft resets, so without this core1
    // won't ACK multicore_lockout_start_blocking() → webREPL/USB write hangs.
    // DMA/PIO are autonomous hardware and keep running during the lockout;
    // the dispatcher may miss a frame but that's acceptable.
    multicore_lockout_victim_init();

    gfx_cmd_t cmd;
    while (1) {
        if (gfx_queue_pop(&cmd)) {
            dispatch(&cmd);
            __sev();
        } else {
            __wfe();
        }
    }
}

// ── called once from core0 (before mp_main) ──────────────────────────────────
// MicroPython's CMakeLists.txt sets PICO_CORE1_STACK_SIZE=0, which makes
// multicore_launch_core1() unconditionally panic().  We must supply our own
// stack and call multicore_launch_core1_with_stack() directly.
static uint32_t core1_stack[1024];  // 4 KB — ample for initialise_cvideo() + dispatch loop

void gfx_core1_launch(void) {
    multicore_launch_core1_with_stack(core1_main, core1_stack, sizeof(core1_stack));
}
