// mod_gfx.c
// MicroPython C extension module "gfx".
// Runs on core0 — only pushes commands to the queue, never touches
// the framebuffer or cvideo internals directly.
//
// Python API:
//   import gfx
//   gfx.usb_ready()                  # True if a USB host has enumerated us
//   gfx.usb_disable()                # Physically disconnect from USB bus (standalone mode)
//   gfx.cls(colour)
//   gfx.wait_vblank()
//   gfx.set_border(colour)
//   gfx.plot(x, y, colour)
//   gfx.line(x0, y0, x1, y1, colour)
//   gfx.hline(y, x0, x1, colour)
//   gfx.circle(x, y, r, colour, filled)
//   gfx.triangle(x0,y0, x1,y1, x2,y2, colour, filled)
//   gfx.polygon(x0,y0, x1,y1, x2,y2, x3,y3, colour, filled)
//   gfx.print_char(x, y, char_int, bg_colour, fg_colour)
//   gfx.print_string(x, y, string, bg_colour, fg_colour)
//   gfx.scroll_up(colour, rows)
//   gfx.blit(buf, sw, sh, dx, dy)   # buf = bytes/bytearray, pixel values 0-15

#include "py/runtime.h"
#include "py/objstr.h"
#include "gfx_queue.h"
#include "gfx_core1.h"
#include "hardware/structs/usb.h"   // usb_hw, USB_SIE_CTRL_PULLUP_EN_BITS
#include "config.h"                 // opt_colour
// colour_base mirrors the definition in cvideo.h
#if opt_colour == 0
#define colour_base 0x10
#else
#define colour_base 0x00
#endif

// ── gfx.usb_ready() ──────────────────────────────────────────────────────────
// Returns True if a USB host has enumerated this device.
// On RP2040, a host assigns a non-zero device address during enumeration
// (SET_ADDRESS request, happens within ~200ms of plugging into a PC).
// A wall charger never sends SET_ADDRESS, so this stays False.
static mp_obj_t gfx_usb_ready(void) {
    return mp_obj_new_bool((usb_hw->dev_addr_ctrl & 0x7fu) != 0u);
}
static MP_DEFINE_CONST_FUN_OBJ_0(gfx_usb_ready_obj, gfx_usb_ready);

// ── gfx.usb_disable() ────────────────────────────────────────────────────────
// Removes the D+ pull-up resistor, signalling disconnect to the host.
// Identical to what TinyUSB's dcd_disconnect() does internally.
// After this, no USB traffic occurs until reset — safe to start video engine.
static mp_obj_t gfx_usb_disable(void) {
    usb_hw->sie_ctrl &= ~USB_SIE_CTRL_PULLUP_EN_BITS;
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_0(gfx_usb_disable_obj, gfx_usb_disable);

// ── gfx.init() ───────────────────────────────────────────────────────────────
// Launch the core1 video engine.  Call once before any other gfx function.
// Safe to call multiple times (subsequent calls are no-ops).
static bool gfx_core1_started = false;

static mp_obj_t gfx_init(void) {
    if (!gfx_core1_started) {
        gfx_core1_launch();
        gfx_core1_started = true;
    }
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_0(gfx_init_obj, gfx_init);

// ── helpers ──────────────────────────────────────────────────────────────────

// Push and block until the queue accepts (no-yield busy spin — fine for a
// Pico at 125MHz pushing a handful of draw calls; total wait is microseconds).
static void push(gfx_cmd_t *cmd) {
    gfx_queue_push_blocking(cmd);
}

static inline int16_t to_i16(mp_obj_t o) { return (int16_t)mp_obj_get_int(o); }
static inline uint8_t to_u8(mp_obj_t o)  { return (uint8_t)mp_obj_get_int(o); }

// ── gfx.deinit() ─────────────────────────────────────────────────────────────
// Stop the core1 video engine: disables PIO state machines, aborts DMA channels,
// kills IRQs and drives DAC GPIO pins to 0.  Core1 parks in __wfe() afterwards.
// Call this from the webREPL console before transferring files; the PIO/DMA
// activity is what prevents flash writes from completing cleanly.
// After deinit, use machine.reset() to restart the clock.
static mp_obj_t gfx_deinit(void) {
    if (!gfx_core1_started) return mp_const_none;
    gfx_cmd_t cmd = { .type = CMD_DEINIT };
    push(&cmd);
    while (!gfx_deinit_done) { __wfe(); }
    gfx_core1_started = false;
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_0(gfx_deinit_obj, gfx_deinit);

// ── gfx.cls(colour) ──────────────────────────────────────────────────────────
static mp_obj_t gfx_cls(mp_obj_t c_in) {
    gfx_cmd_t cmd = { .type = CMD_CLS, .c = to_u8(c_in) };
    push(&cmd);
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_1(gfx_cls_obj, gfx_cls);

// ── gfx.wait_vblank() ────────────────────────────────────────────────────────
static mp_obj_t gfx_wait_vblank(void) {
    gfx_cmd_t cmd = { .type = CMD_WAIT_VBLANK };
    push(&cmd);
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_0(gfx_wait_vblank_obj, gfx_wait_vblank);

// ── gfx.set_border(colour) ───────────────────────────────────────────────────
static mp_obj_t gfx_set_border(mp_obj_t c_in) {
    gfx_cmd_t cmd = { .type = CMD_SET_BORDER, .c = to_u8(c_in) };
    push(&cmd);
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_1(gfx_set_border_obj, gfx_set_border);

// ── gfx.plot(x, y, colour) ───────────────────────────────────────────────────
static mp_obj_t gfx_plot(mp_obj_t x, mp_obj_t y, mp_obj_t c) {
    gfx_cmd_t cmd = { .type = CMD_PLOT,
        .x0 = to_i16(x), .y0 = to_i16(y), .c = to_u8(c) };
    push(&cmd);
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_3(gfx_plot_obj, gfx_plot);

// ── gfx.line(x0, y0, x1, y1, colour) ────────────────────────────────────────
static mp_obj_t gfx_line(size_t n, const mp_obj_t *a) {
    gfx_cmd_t cmd = { .type = CMD_LINE,
        .x0 = to_i16(a[0]), .y0 = to_i16(a[1]),
        .x1 = to_i16(a[2]), .y1 = to_i16(a[3]),
        .c  = to_u8(a[4]) };
    push(&cmd);
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(gfx_line_obj, 5, 5, gfx_line);

// ── gfx.hline(y, x0, x1, colour) ────────────────────────────────────────────
static mp_obj_t gfx_hline(size_t n, const mp_obj_t *a) {
    gfx_cmd_t cmd = { .type = CMD_HLINE,
        .y0 = to_i16(a[0]), .x0 = to_i16(a[1]),
        .x1 = to_i16(a[2]), .c  = to_u8(a[3]) };
    push(&cmd);
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(gfx_hline_obj, 4, 4, gfx_hline);

// ── gfx.circle(x, y, r, colour, filled) ─────────────────────────────────────
static mp_obj_t gfx_circle(size_t n, const mp_obj_t *a) {
    gfx_cmd_t cmd = { .type = CMD_CIRCLE,
        .x0 = to_i16(a[0]), .y0 = to_i16(a[1]),
        .x1 = to_i16(a[2]),   // r stored in x1
        .c  = to_u8(a[3]),
        .filled = mp_obj_is_true(a[4]) };
    push(&cmd);
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(gfx_circle_obj, 5, 5, gfx_circle);

// ── gfx.triangle(x0,y0, x1,y1, x2,y2, colour, filled) ───────────────────────
static mp_obj_t gfx_triangle(size_t n, const mp_obj_t *a) {
    gfx_cmd_t cmd = { .type = CMD_TRIANGLE,
        .x0 = to_i16(a[0]), .y0 = to_i16(a[1]),
        .x1 = to_i16(a[2]), .y1 = to_i16(a[3]),
        .x2 = to_i16(a[4]), .y2 = to_i16(a[5]),
        .c  = to_u8(a[6]),
        .filled = mp_obj_is_true(a[7]) };
    push(&cmd);
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(gfx_triangle_obj, 8, 8, gfx_triangle);

// ── gfx.polygon(x0,y0, x1,y1, x2,y2, x3,y3, colour, filled) ────────────────
static mp_obj_t gfx_polygon(size_t n, const mp_obj_t *a) {
    gfx_cmd_t cmd = { .type = CMD_POLYGON,
        .x0 = to_i16(a[0]), .y0 = to_i16(a[1]),
        .x1 = to_i16(a[2]), .y1 = to_i16(a[3]),
        .x2 = to_i16(a[4]), .y2 = to_i16(a[5]),
        .x3 = to_i16(a[6]), .y3 = to_i16(a[7]),
        .c  = to_u8(a[8]),
        .filled = mp_obj_is_true(a[9]) };
    push(&cmd);
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(gfx_polygon_obj, 10, 10, gfx_polygon);

// ── gfx.print_char(x, y, char_int, bg, fg) ───────────────────────────────────
static mp_obj_t gfx_print_char(size_t n, const mp_obj_t *a) {
    gfx_cmd_t cmd = { .type = CMD_PRINT_CHAR,
        .x0 = to_i16(a[0]), .y0 = to_i16(a[1]),
        .bc = to_u8(a[3]),  .fc = to_u8(a[4]) };
    cmd.str[0] = (char)mp_obj_get_int(a[2]);
    push(&cmd);
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(gfx_print_char_obj, 5, 5, gfx_print_char);

// ── gfx.print_string(x, y, string, bg, fg) ───────────────────────────────────
static mp_obj_t gfx_print_string(size_t n, const mp_obj_t *a) {
    gfx_cmd_t cmd = { .type = CMD_PRINT_STRING,
        .x0 = to_i16(a[0]), .y0 = to_i16(a[1]),
        .bc = to_u8(a[3]),  .fc = to_u8(a[4]) };
    size_t len;
    const char *s = mp_obj_str_get_data(a[2], &len);
    if (len >= GFX_STR_MAXLEN) len = GFX_STR_MAXLEN - 1;
    memcpy(cmd.str, s, len);
    cmd.str[len] = '\0';
    push(&cmd);
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(gfx_print_string_obj, 5, 5, gfx_print_string);

// ── gfx.print_string_2x(x, y, string, bg, fg) ────────────────────────────────
// Same signature as print_string; each glyph is rendered at 16×16 px (2× scale).
static mp_obj_t gfx_print_string_2x(size_t n, const mp_obj_t *a) {
    gfx_cmd_t cmd = { .type = CMD_PRINT_STRING_2X,
        .x0 = to_i16(a[0]), .y0 = to_i16(a[1]),
        .bc = to_u8(a[3]),  .fc = to_u8(a[4]) };
    size_t len;
    const char *s = mp_obj_str_get_data(a[2], &len);
    if (len >= GFX_STR_MAXLEN) len = GFX_STR_MAXLEN - 1;
    memcpy(cmd.str, s, len);
    cmd.str[len] = '\0';
    push(&cmd);
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(gfx_print_string_2x_obj, 5, 5, gfx_print_string_2x);

// ── gfx.scroll_up(colour, rows) ──────────────────────────────────────────────
static mp_obj_t gfx_scroll_up(mp_obj_t c_in, mp_obj_t rows_in) {
    gfx_cmd_t cmd = { .type = CMD_SCROLL_UP,
        .c = to_u8(c_in), .scroll_rows = to_i16(rows_in) };
    push(&cmd);
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_2(gfx_scroll_up_obj, gfx_scroll_up);

// ── gfx.blit(buf, sw, sh, dx, dy) ────────────────────────────────────────────
// buf must be a bytes/bytearray of exactly sw*sh bytes.
// Copies into gfx_blit_buf on core0 before pushing — the GC can do what
// it likes with the Python object afterwards.
static mp_obj_t gfx_blit(size_t n, const mp_obj_t *a) {
    mp_buffer_info_t bi;
    mp_get_buffer_raise(a[0], &bi, MP_BUFFER_READ);

    int sw = mp_obj_get_int(a[1]);
    int sh = mp_obj_get_int(a[2]);
    int dx = mp_obj_get_int(a[3]);
    int dy = mp_obj_get_int(a[4]);

    size_t sz = (size_t)(sw * sh);
    if (sz > GFX_BLIT_BUFSIZE) {
        mp_raise_ValueError(MP_ERROR_TEXT("blit buffer too large"));
    }
    if (bi.len < sz) {
        mp_raise_ValueError(MP_ERROR_TEXT("blit buf too small for sw*sh"));
    }

    // Wait until core1 has finished reading gfx_blit_buf from the previous blit.
    // Typical wait is a few microseconds (time for core1 to run blit()); the
    // __wfe() avoids burning cycles — core1 does __sev() after clearing the flag.
    while (gfx_blit_busy) { __wfe(); }

    // Copy sprite pixels into the shared buffer (add colour_base offset here so
    // core1 never has to touch raw palette indices).
    const uint8_t *src = (const uint8_t *)bi.buf;
    for (size_t i = 0; i < sz; i++) {
        gfx_blit_buf[i] = src[i] + colour_base;
    }
    __dmb();            // pixel copy must be visible before busy flag and CMD_BLIT

    gfx_blit_busy = true;
    __dmb();            // busy flag must be visible before CMD_BLIT hits the queue

    gfx_cmd_t cmd = { .type = CMD_BLIT,
        .x0 = (int16_t)dx, .y0 = (int16_t)dy,
        .sw = (int16_t)sw, .sh = (int16_t)sh };
    push(&cmd);
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(gfx_blit_obj, 5, 5, gfx_blit);

// ── module table ─────────────────────────────────────────────────────────────
static const mp_rom_map_elem_t gfx_module_globals_table[] = {
    { MP_ROM_QSTR(MP_QSTR___name__),     MP_ROM_QSTR(MP_QSTR_gfx) },
    { MP_ROM_QSTR(MP_QSTR_usb_ready),    MP_ROM_PTR(&gfx_usb_ready_obj) },
    { MP_ROM_QSTR(MP_QSTR_usb_disable),  MP_ROM_PTR(&gfx_usb_disable_obj) },
    { MP_ROM_QSTR(MP_QSTR_init),         MP_ROM_PTR(&gfx_init_obj) },
    { MP_ROM_QSTR(MP_QSTR_deinit),       MP_ROM_PTR(&gfx_deinit_obj) },
    { MP_ROM_QSTR(MP_QSTR_cls),          MP_ROM_PTR(&gfx_cls_obj) },
    { MP_ROM_QSTR(MP_QSTR_wait_vblank),  MP_ROM_PTR(&gfx_wait_vblank_obj) },
    { MP_ROM_QSTR(MP_QSTR_set_border),   MP_ROM_PTR(&gfx_set_border_obj) },
    { MP_ROM_QSTR(MP_QSTR_plot),         MP_ROM_PTR(&gfx_plot_obj) },
    { MP_ROM_QSTR(MP_QSTR_line),         MP_ROM_PTR(&gfx_line_obj) },
    { MP_ROM_QSTR(MP_QSTR_hline),        MP_ROM_PTR(&gfx_hline_obj) },
    { MP_ROM_QSTR(MP_QSTR_circle),       MP_ROM_PTR(&gfx_circle_obj) },
    { MP_ROM_QSTR(MP_QSTR_triangle),     MP_ROM_PTR(&gfx_triangle_obj) },
    { MP_ROM_QSTR(MP_QSTR_polygon),      MP_ROM_PTR(&gfx_polygon_obj) },
    { MP_ROM_QSTR(MP_QSTR_print_char),   MP_ROM_PTR(&gfx_print_char_obj) },
    { MP_ROM_QSTR(MP_QSTR_print_string),    MP_ROM_PTR(&gfx_print_string_obj) },
    { MP_ROM_QSTR(MP_QSTR_print_string_2x), MP_ROM_PTR(&gfx_print_string_2x_obj) },
    { MP_ROM_QSTR(MP_QSTR_scroll_up),       MP_ROM_PTR(&gfx_scroll_up_obj) },
    { MP_ROM_QSTR(MP_QSTR_blit),         MP_ROM_PTR(&gfx_blit_obj) },
};
static MP_DEFINE_CONST_DICT(gfx_module_globals, gfx_module_globals_table);

const mp_obj_module_t gfx_module = {
    .base    = { &mp_type_module },
    .globals = (mp_obj_dict_t *)&gfx_module_globals,
};

MP_REGISTER_MODULE(MP_QSTR_gfx, gfx_module);
