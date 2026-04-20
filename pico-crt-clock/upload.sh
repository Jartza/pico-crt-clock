#!/usr/bin/env bash
# upload.sh - Copy all Python and binary files to the Pico filesystem.
# Run after flashing firmware. Requires mpremote to be installed.
# Usage: ./upload.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

FILES=(
    main.py
    common.py
    weather.py
    news.py
    sky.py
    electricity.py
    torus.py
    icons.bin
    torus.bin
)

echo "Uploading files to Pico..."
for f in "${FILES[@]}"; do
    src="$SCRIPT_DIR/$f"
    if [ -f "$src" ]; then
        echo "  $f"
        mpremote fs cp "$src" ":$f"
    else
        echo "  $f (skipped, not found)"
    fi
done

# config.py is user-edited — ask before overwriting
echo ""
read -r -p "Upload config.py? (skip if already configured on device) [y/N] " ans
case "$ans" in
    [yY]*) echo "  config.py"; mpremote fs cp "$SCRIPT_DIR/config.py" ":config.py" ;;
    *)     echo "  config.py (skipped)" ;;
esac

echo "Done."
