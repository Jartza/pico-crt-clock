#!/usr/bin/env bash
# build.sh - out-of-tree firmware build with patch/revert for vanilla submodules.
# Patches are applied before the build and reverted on exit (success or failure).
# Run from anywhere; paths are relative to this script's location.
#
# Usage: ./build.sh <variant>
#
#   ladder   Plain R-2R resistor ladder DAC (for basic testing; not 75 Ω matched)
#   buffer   R-2R ladder + 2SC1815 emitter follower buffer
#   amp      Weighted resistor summing network + THS7314 video amplifier (recommended)
#
# See README.md for hardware schematics and component values for each variant.
# You MUST build and flash the firmware that matches your hardware.

set -e

usage() {
    cat <<'EOF'

Usage: ./build.sh <variant>

  ladder   Plain R-2R resistor ladder DAC
             No extra components beyond the 5 resistors.
             Works for initial testing but output is not 75 Ω matched.

  buffer   R-2R ladder + 2SC1815 emitter follower buffer
             Adds a transistor buffer between the ladder and the display.
             Better impedance match; corrected colour LUT for accurate levels.

  amp      Weighted resistor summing network + THS7314 video amplifier
             Recommended for clean, standards-correct composite output.
             Fixed 2x gain compensates for 75 Ω source/load divider loss.

See README.md for full hardware schematics and component lists.

WARNING: The firmware is calibrated for its hardware variant.
         Flashing the wrong variant will produce incorrect signal levels.

EOF
    exit 1
}

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"
MP_PORT="$ROOT/micropython/ports/rp2"
BOARD=RPI_PICO_W
MODULE_CMAKE="$SCRIPT_DIR/micropython.cmake"
PIO_SRC="$ROOT/pico-mposite"

PATCH_MP="$SCRIPT_DIR/patches/micropython-no-thread.patch"

# -- validate variant ----------------------------------------------------------
VARIANT="${1:-}"
case "$VARIANT" in
    ladder|buffer|amp) ;;
    "") usage ;;
    *) echo "Error: unknown variant '$VARIANT'"; usage ;;
esac

BUILD_DIR="$ROOT/build-$BOARD-$VARIANT"
PIOASM="$BUILD_DIR/pioasm/pioasm"

# pico-mposite patches: common applies to all variants; variant patch (if any)
# applies on top and carries only the colour handling / HSHI differences.
PATCH_PM_COMMON="$SCRIPT_DIR/patches/pico-mposite-common.patch"
PATCH_PM_VARIANT=""
case "$VARIANT" in
    buffer) PATCH_PM_VARIANT="$SCRIPT_DIR/patches/pico-mposite-buffer.patch" ;;
    amp)    PATCH_PM_VARIANT="$SCRIPT_DIR/patches/pico-mposite-amp.patch"    ;;
esac

# cmake extra flags for variants that need them
CMAKE_EXTRA=""
[ "$VARIANT" = "buffer" ] && CMAKE_EXTRA="-DUSE_COLOUR_LUT=1"

# -- patch helpers --------------------------------------------------------------
apply_patch() {
    local repo="$1" patchfile="$2"
    if git -C "$repo" apply --check --ignore-whitespace "$patchfile" 2>/dev/null; then
        git -C "$repo" apply --ignore-whitespace --whitespace=nowarn "$patchfile"
        echo "  applied: $(basename "$patchfile")"
    else
        echo "  already applied (skipping): $(basename "$patchfile")"
    fi
}

revert_patch() {
    local repo="$1" patchfile="$2"
    if git -C "$repo" apply --check --ignore-whitespace -R "$patchfile" 2>/dev/null; then
        git -C "$repo" apply --ignore-whitespace --whitespace=nowarn -R "$patchfile"
        echo "  reverted: $(basename "$patchfile")"
    fi
}

cleanup() {
    echo "Reverting patches to restore vanilla submodules..."
    revert_patch "$ROOT/micropython" "$PATCH_MP"
    # Revert variant before common (reverse application order)
    [ -n "$PATCH_PM_VARIANT" ] && revert_patch "$ROOT/pico-mposite" "$PATCH_PM_VARIANT"
    revert_patch "$ROOT/pico-mposite" "$PATCH_PM_COMMON"
}
trap cleanup EXIT

# -- 1. initialise submodules --------------------------------------------------
echo "Initialising submodules..."
git -C "$ROOT" submodule update --init
make -C "$MP_PORT" BOARD=$BOARD submodules

# -- 2. apply patches ----------------------------------------------------------
echo "Applying patches (variant: $VARIANT)..."
apply_patch "$ROOT/micropython" "$PATCH_MP"
apply_patch "$ROOT/pico-mposite" "$PATCH_PM_COMMON"
[ -n "$PATCH_PM_VARIANT" ] && apply_patch "$ROOT/pico-mposite" "$PATCH_PM_VARIANT"

# -- 3. build mpy-cross if needed ----------------------------------------------
if [ ! -f "$ROOT/micropython/mpy-cross/build/mpy-cross" ]; then
    echo "Building mpy-cross..."
    make -C "$ROOT/micropython/mpy-cross"
fi

# -- 4. cmake configure + pioasm -----------------------------------------------
if [ ! -f "$PIOASM" ]; then
    echo "Configuring cmake (build dir: $BUILD_DIR, variant: $VARIANT)..."
    cmake -S "$MP_PORT" -B "$BUILD_DIR" \
        -DPICO_BUILD_DOCS=0 \
        -DMICROPY_BOARD=$BOARD \
        -DUSER_C_MODULES="$MODULE_CMAKE" \
        -DMICROPY_C_HEAP_SIZE=65536 \
        $CMAKE_EXTRA

    echo "Building pioasm..."
    make -C "$BUILD_DIR" pioasmBuild
fi

echo "Generating PIO headers..."
"$PIOASM" "$PIO_SRC/cvideo_sync.pio" "$SCRIPT_DIR/cvideo_sync.pio.h"
"$PIOASM" "$PIO_SRC/cvideo_data.pio" "$SCRIPT_DIR/cvideo_data.pio.h"

# -- 5. build firmware ---------------------------------------------------------
echo "Building MicroPython firmware with gfx module (variant: $VARIANT)..."
make -C "$BUILD_DIR" -j$(nproc)

echo ""
echo "Done! Firmware at: $BUILD_DIR/firmware.uf2"
echo ""
echo "WARNING: This firmware is built for the '$VARIANT' hardware variant."
echo "         Flash it only to a Pico running the matching hardware."
echo ""
echo "Flash with:"
echo "  cp $BUILD_DIR/firmware.uf2 /media/\$USER/RPI-RP2/"
echo ""
echo "Then copy Python files to the Pico filesystem:"
echo "  mpremote fs cp $SCRIPT_DIR/main.py :main.py"
echo "  mpremote fs cp $SCRIPT_DIR/clock.py :clock.py"
echo "  mpremote fs cp $SCRIPT_DIR/icons.py :icons.py"
echo "  mpremote fs cp $SCRIPT_DIR/config.py :config.py"
