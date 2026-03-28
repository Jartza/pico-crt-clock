#!/usr/bin/env bash
# build.sh — out-of-tree firmware build with patch/revert for vanilla submodules.
# Patches are applied before the build and reverted on exit (success or failure).
# Run from anywhere; paths are relative to this script's location.

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"
MP_PORT="$ROOT/micropython/ports/rp2"
BOARD=RPI_PICO_W
BUILD_DIR="$ROOT/build-$BOARD"
MODULE_CMAKE="$SCRIPT_DIR/micropython.cmake"
PIOASM="$BUILD_DIR/pioasm/pioasm"
PIO_SRC="$ROOT/pico-mposite"

PATCH_MP="$SCRIPT_DIR/patches/micropython-no-thread.patch"
PATCH_PM="$SCRIPT_DIR/patches/pico-mposite.patch"

# ── patch helpers ──────────────────────────────────────────────────────────────
apply_patch() {
    local repo="$1" patchfile="$2"
    if git -C "$repo" apply --check "$patchfile" 2>/dev/null; then
        git -C "$repo" apply "$patchfile"
        echo "  applied: $(basename "$patchfile")"
    else
        echo "  already applied (skipping): $(basename "$patchfile")"
    fi
}

revert_patch() {
    local repo="$1" patchfile="$2"
    if git -C "$repo" apply --check -R "$patchfile" 2>/dev/null; then
        git -C "$repo" apply -R "$patchfile"
        echo "  reverted: $(basename "$patchfile")"
    fi
}

cleanup() {
    echo "Reverting patches to restore vanilla submodules..."
    revert_patch "$ROOT/micropython" "$PATCH_MP"
    revert_patch "$ROOT/pico-mposite" "$PATCH_PM"
}
trap cleanup EXIT

# ── 1. initialise micropython submodules (pico-sdk, tinyusb, etc.) ────────────
echo "Initialising MicroPython submodules..."
make -C "$MP_PORT" BOARD=$BOARD submodules

# ── 2. apply patches ──────────────────────────────────────────────────────────
echo "Applying patches..."
apply_patch "$ROOT/micropython" "$PATCH_MP"
apply_patch "$ROOT/pico-mposite" "$PATCH_PM"

# ── 3. build mpy-cross if needed ──────────────────────────────────────────────
if [ ! -f "$ROOT/micropython/mpy-cross/build/mpy-cross" ]; then
    echo "Building mpy-cross..."
    make -C "$ROOT/micropython/mpy-cross"
fi

# ── 4. cmake configure + pioasm ───────────────────────────────────────────────
if [ ! -f "$PIOASM" ]; then
    echo "Configuring cmake (build dir: $BUILD_DIR)..."
    cmake -S "$MP_PORT" -B "$BUILD_DIR" \
        -DPICO_BUILD_DOCS=0 \
        -DMICROPY_BOARD=$BOARD \
        -DUSER_C_MODULES="$MODULE_CMAKE" \
        -DMICROPY_C_HEAP_SIZE=65536

    echo "Building pioasm..."
    make -C "$BUILD_DIR" pioasmBuild
fi

echo "Generating PIO headers..."
"$PIOASM" "$PIO_SRC/cvideo_sync.pio" "$SCRIPT_DIR/cvideo_sync.pio.h"
"$PIOASM" "$PIO_SRC/cvideo_data.pio" "$SCRIPT_DIR/cvideo_data.pio.h"

# ── 5. build firmware ─────────────────────────────────────────────────────────
echo "Building MicroPython firmware with gfx module..."
make -C "$BUILD_DIR" -j$(nproc)

echo ""
echo "Done! Firmware at: $BUILD_DIR/firmware.uf2"
echo ""
echo "Flash with:"
echo "  cp $BUILD_DIR/firmware.uf2 /media/\$USER/RPI-RP2/"
echo ""
echo "Then copy Python files to the Pico filesystem:"
echo "  mpremote fs cp $SCRIPT_DIR/main.py :main.py"
echo "  mpremote fs cp $SCRIPT_DIR/clock.py :clock.py"
echo "  mpremote fs cp $SCRIPT_DIR/icons.py :icons.py"
echo "  mpremote fs cp $SCRIPT_DIR/config.py :config.py"
