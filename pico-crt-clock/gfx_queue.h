// gfx_queue.h
// Shared between core0 (MicroPython) and core1 (video engine).
// All state in this file lives in .bss / static SRAM - never in GC heap.

#pragma once
#include <stdint.h>
#include <stdbool.h>

// Tunables
#define GFX_QUEUE_SIZE   64          // must be power-of-2 for the mask trick
#define GFX_BLIT_BUFSIZE (64 * 64)  // max sprite: 64x64 px
#define GFX_STR_MAXLEN   64

// Command type
typedef enum {
    CMD_CLS = 0,
    CMD_PLOT,
    CMD_LINE,
    CMD_HLINE,          // internal optimisation, also useful from Python
    CMD_CIRCLE,
    CMD_TRIANGLE,
    CMD_POLYGON,
    CMD_PRINT_CHAR,
    CMD_PRINT_STRING,
    CMD_PRINT_STRING_2X,    // double-size (16x16 px per glyph)
    CMD_SCROLL_UP,
    CMD_BLIT,
    CMD_SET_BORDER,
    CMD_WAIT_VBLANK,    // core1 drains this by blocking until lower border starts
    CMD_DEINIT,         // stop PIO/DMA/IRQs; core1 parks after this
} gfx_cmd_type_t;

// Command payload
// One struct covers every command; unused fields are zero.
typedef struct {
    gfx_cmd_type_t type;
    int16_t  x0, y0, x1, y1, x2, y2, x3, y3;
    uint8_t  c;          // colour
    uint8_t  bc, fc;     // background / foreground (print)
    uint8_t  filled;     // bool for circle/triangle/polygon
    int16_t  sw, sh;     // blit source width/height  (dx,dy -> x0,y0)
    int16_t  scroll_rows;
    char     str[GFX_STR_MAXLEN];
} gfx_cmd_t;

// Ring buffer (single-producer core0, single-consumer core1)
#define GFX_QUEUE_MASK (GFX_QUEUE_SIZE - 1)

typedef struct {
    gfx_cmd_t        buf[GFX_QUEUE_SIZE];
    volatile uint32_t head;   // written by core0
    volatile uint32_t tail;   // written by core1
} gfx_queue_t;

extern gfx_queue_t gfx_queue;

// Static blit pixel buffer - core0 fills this, core1 reads it.
// gfx_blit_busy is set true by core0 just before pushing CMD_BLIT and
// cleared by core1 after blit() returns.  Core0 spins on it before each
// copy, so back-to-back gfx.blit() calls in Python need only one
// wait_vblank() before the first one - not one per icon.
extern volatile uint8_t gfx_blit_buf[GFX_BLIT_BUFSIZE];
extern volatile bool    gfx_blit_busy;
extern volatile bool    gfx_deinit_done;  // set by core1 after CMD_DEINIT completes
extern volatile bool    gfx_flash_freeze_requested;
extern volatile bool    gfx_flash_frozen;
extern volatile bool    gfx_core1_online;

// Inline queue helpers (safe to call from either core)

// Push a command from core0.  Returns false if the queue is full.
// Caller should spin/yield if it gets false (shouldn't happen in practice
// for a clock display, but handle it cleanly).
static inline bool gfx_queue_push(const gfx_cmd_t *cmd) {
    uint32_t next = (gfx_queue.head + 1) & GFX_QUEUE_MASK;
    if (next == gfx_queue.tail) return false;   // full
    gfx_queue.buf[gfx_queue.head] = *cmd;
    __dmb();                                     // data visible before head moves
    gfx_queue.head = next;
    return true;
}

// Pop a command on core1.  Returns false if the queue is empty.
static inline bool gfx_queue_pop(gfx_cmd_t *out) {
    if (gfx_queue.tail == gfx_queue.head) return false;
    *out = gfx_queue.buf[gfx_queue.tail];
    __dmb();
    gfx_queue.tail = (gfx_queue.tail + 1) & GFX_QUEUE_MASK;
    return true;
}

static inline bool gfx_queue_empty(void) {
    return gfx_queue.tail == gfx_queue.head;
}

// Convenience: push and spin until accepted (core0 use only)
static inline void gfx_queue_push_blocking(const gfx_cmd_t *cmd) {
    while (!gfx_queue_push(cmd)) {
        __wfe();   // sleep until an event (core1 will __sev() after each pop)
    }
    __sev();       // wake core1 from __wfe() so it processes the new command
}
