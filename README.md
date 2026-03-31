# pico-crt-clock

[MicroPython](https://github.com/micropython/micropython) firmware running
on first core of a Raspberry Pi Pico W,
driving a composite PAL CRT TV via a resistor-ladder DAC, using
[pico-mposite](https://github.com/breakintoprogram/pico-mposite) as the video
engine running on the second RP2040 core.

Displays a live clock, current temperature and wind speed, and a 3-day weather
forecast with icons, fetched from [Open-Meteo](https://open-meteo.com) (no API
key required).

---

## Gallery

| CRT display | PC simulator |
|---|---|
| ![Clock running on a small CRT TV](img/small_crt.jpg) | ![PC simulator screenshot](img/sim_screen.png) |

https://github.com/user-attachments/assets/1162584c-b029-4f1c-9379-bf67870d685d

---

## Hardware

| Item | Detail |
|---|---|
| MCU board | Raspberry Pi Pico W (WiFi used for NTP and weather) |
| Display | Any TV or monitor accepting a composite PAL signal |
| DAC | See [Video output options](#video-output-options) below |

The firmware maps palette indices **0 (black) ... 15 (white)** to 5-bit DAC
values. The exact mapping depends on the hardware variant — see below.

> **Important:** The firmware is calibrated for the hardware variant it was
> built for. Build with `./build.sh <variant>` and flash only to a Pico
> running the matching hardware. Mismatching firmware and hardware will produce
> incorrect signal levels.

---

## Video output options

Three hardware variants are supported. Choose one and build the matching
firmware with `./build.sh <variant>`.

| Variant | `build.sh` arg | Hardware | Notes |
|---|---|---|---|
| Ladder | `ladder` | R-2R resistor ladder only | Simple; not 75 Ω matched — for initial testing |
| Ladder + buffer | `buffer` | R-2R ladder + 2SC1815 emitter follower | Better impedance match; software LUT corrects levels |
| Summing amp | `amp` | Weighted resistor network + THS7314 | Recommended; clean, standards-correct output |

### Ladder (basic)

The simplest option: five resistors on GP0–GP4 form an R-2R ladder DAC.

![R-2R ladder DAC schematic](img/ladder.png)

| Value | Meaning |
|---|---|
| 0x00 | Sync tip |
| 0x0D | Black (blanking level) |
| 0x1F | White (peak luminance) |

The ladder presents roughly 110 Ω output impedance. Real composite inputs
terminate at 75 Ω, so connecting the ladder directly creates a voltage divider
that shifts and attenuates all levels. This is fine for a quick smoke-test
but will look wrong on a real display. Use the `buffer` or `amp` variant for
correct signal levels.

### Ladder + buffer (`buffer`)

Build the ladder above, then add a 2SC1815 NPN emitter follower between the
ladder output and the display. The buffer lowers the output impedance to
approximately 75 Ω. A corrected 16-entry colour LUT in the firmware
compensates for the remaining level shift caused by the ladder's output
impedance.

![Video buffer schematic](img/vidbuf.png)

| Part | Value | Function |
|---|---|---|
| C2 | 1 µF | AC-couples the DAC signal into the base bias network |
| R11 | 10 kΩ | Pull-up to 3V3; sets base bias with R12 |
| R12 | 10 kΩ | Pull-down to GND; sets base bias midpoint |
| Q2 | 2SC1815 | NPN emitter follower; unity voltage gain, low output impedance |
| R13 | 68 Ω | Emitter resistor; sets the operating point to ~15 mA emitter current |
| C3 | 220–470 µF | AC output coupling cap; **330 µF minimum** — 220 µF may give a soft picture |

| Value | Meaning |
|---|---|
| 0x01 | Sync tip |
| 0x0B | Black (blanking level) |
| 0x1F | White (peak luminance) |

### Summing amp — recommended (`amp`)

A weighted resistor network sums the 5-bit GPIO output into a voltage, which
a THS7314 video amplifier IC drives onto the composite output at correct
amplitude and 75 Ω impedance. No LUT correction needed — the back porch level
is set to exactly `colour_base` (0x10) in firmware.

![THS7314 video amplifier schematic](img/video_amp.png)

| Part | Value | Function |
|---|---|---|
| R1 | 100 kΩ | GPIO0 (LSB) summing resistor |
| R2 | 47 kΩ | GPIO1 summing resistor |
| R3 | 24 kΩ | GPIO2 summing resistor |
| R4 | 12 kΩ | GPIO3 summing resistor |
| R5 | 15 kΩ | GPIO4 (MSB) summing resistor |
| R6 | 2 kΩ | Shunt resistor; converts summed current to voltage at CH1.IN |
| U1 | THS7314 | Triple SD video amplifier; fixed 2× gain; drives 75 Ω loads |
| R7 | 75 Ω | Series output resistor; forms 75 Ω source impedance with U1 |
| C1 | 330–470 µF | AC output coupling cap to composite connector |
| C2 | 100 nF | Supply bypass cap on VS+ |

The THS7314 fixed 2× gain compensates for the 6 dB loss of the 75 Ω
source/load divider, so the signal arrives at the display at correct composite
amplitude. Most CRT TVs and composite monitors have built-in 75 Ω termination;
if yours does not, add a 75 Ω resistor from the connector to ground at the
display end.

| Value | Meaning |
|---|---|
| 0x01 | Sync tip |
| 0x10 | Black (blanking level) |
| 0x1F | White (peak luminance) |

---

## Repository layout

```
pico-crt-clock/           project sources; build from here
  build.sh                  one-shot build + patch script
  micropython.cmake         build-system glue (USER_C_MODULES)
  gfx_queue.h               shared ring buffer + command struct (core0 <-> core1)
  gfx_core1.c               core1 entry point and command dispatcher
  gfx_core1.h               gfx_core1_launch() declaration
  mod_gfx.c                 MicroPython C extension module "gfx"
  main.py                   boot stub: imports clock, catches SystemExit
  clock.py                  clock/weather application logic
  config.py                 WiFi credentials, location, display options
  icons.py                  pre-generated weather icon bytearrays
  make_icons.py             PC-side icon generator (run to regenerate icons.py)
  gfx.py                    PC simulator mock of the gfx C extension (pygame)
  run_sim.py                runner for PC testing without hardware
  patches/
    micropython-no-thread.patch   disables MicroPython threading (see below)
    pico-mposite-common.patch     pico-mposite patch applied to all variants (DMA IRQ, FIFO, SRAM, GPIO drive, deinit)
    pico-mposite-buffer.patch     additional patch for buffer variant (HSHI + colour LUT)
    pico-mposite-amp.patch        additional patch for amp variant (HSHI only)

micropython/          vanilla MicroPython (submodule)
pico-mposite/         vanilla pico-mposite (submodule)
pico-sdk/             vanilla pico-sdk (submodule)
```

`cvideo_sync.pio.h` and `cvideo_data.pio.h` are generated by pioasm during the
build and are not committed.

---

## Architecture

The RP2040 has two cores. Core1 runs the pico-mposite video engine exclusively,
generating the composite PAL signal via PIO state machines and DMA. Core0 runs
MicroPython with a custom `gfx` C extension module (`mod_gfx.c`).

When `clock.py` calls a `gfx` function, `mod_gfx.c` encodes it as a command and
pushes it into a shared ring buffer (`gfx_queue`). Core1 loops on that queue,
popping commands and dispatching them to the pico-mposite drawing functions
(`gfx_core1.c`). The two cores communicate only through the queue; all video
IRQs (`DMA_IRQ_1`, `PIO0_IRQ_0`) are owned by core1.

**Key design points**

- All video IRQs (`DMA_IRQ_1`, `PIO0_IRQ_0`) are registered from core1 so they
  fire on core1's NVIC and cannot affect core0 interrupt latency.
- `patches/pico-mposite-common.patch` redirects DMA from `DMA_IRQ_0` to
  `DMA_IRQ_1` (avoiding conflict with MicroPython's shared DMA_IRQ_0 handler),
  adds `FJOIN_TX` to double the TX FIFO depth on both PIO SMs, places ISRs in
  SRAM with `__not_in_flash_func`, sets GP0-GP4 drive strength to 2 mA / slow
  slew to reduce switching noise, and adds `deinit_cvideo()`. Applied first for
  all variants. The variant-specific patches (`pico-mposite-buffer.patch`,
  `pico-mposite-amp.patch`) apply on top and carry only the HSHI value and
  colour LUT changes specific to that hardware.
- `patches/micropython-no-thread.patch` sets `MICROPY_PY_THREAD = 0`; the
  threading ISR on `SIO_IRQ_PROC0` would consume the FIFO acknowledgement that
  `multicore_launch_core1()` blocks on, hanging core0.
- Core1 is launched with an explicit 4 KB static stack because MicroPython sets
  `PICO_CORE1_STACK_SIZE = 0`, which makes `multicore_launch_core1()` panic.
- `multicore_lockout_victim_init()` is called on core1 so MicroPython's flash
  write path (webREPL, USB MSC) can safely pause core1; without it the lockout
  handshake deadlocks. DMA/PIO keep running during the lockout.
- Back-to-back `gfx.blit()` calls are safe: core0 spins on `gfx_blit_busy`
  until core1 has consumed the previous sprite, then copies the next one.

---

## Prerequisites

- ARM cross-compiler: `gcc-arm-none-eabi`
- `cmake`, `make`, `git`, `python3`

On Debian/Ubuntu:

```bash
sudo apt install gcc-arm-none-eabi cmake make git python3
```

## Build

All submodules are kept vanilla. `build.sh` applies the patches before
building and reverts them on exit via `trap` — they are always restored even
if the build fails.

Pass the hardware variant as the first argument:

```bash
cd pico-crt-clock
./build.sh ladder   # plain R-2R ladder
./build.sh buffer   # ladder + 2SC1815 emitter follower buffer
./build.sh amp      # weighted summing network + THS7314 (recommended)
```

Running `./build.sh` without an argument prints a usage summary and exits.

The script:
1. Initialises top-level submodules (micropython, pico-mposite, pico-sdk) and MicroPython's own submodules (tinyusb, ...)
2. Applies `patches/micropython-no-thread.patch`, `patches/pico-mposite-common.patch`, and (for `buffer`/`amp`) the variant-specific patch on top
3. Builds `mpy-cross` if needed
4. Runs cmake (out-of-tree into `../build-RPI_PICO_W-<variant>/`), builds pioasm,
   generates `cvideo_sync.pio.h` / `cvideo_data.pio.h`
5. Builds the full firmware with the `gfx` user C module
6. Reverts both patches (via `trap EXIT`)

Each variant gets its own build directory, so you can build all three without
a clean in between.

Output: `build-RPI_PICO_W-<variant>/firmware.uf2`

### Flash

Hold BOOTSEL, plug in USB, release. Then (example for `amp`):

```bash
cp build-RPI_PICO_W-amp/firmware.uf2 /media/$USER/RPI-RP2/
```

### Deploy Python files

After the Pico reboots, connect to PC:

```bash
mpremote fs cp pico-crt-clock/main.py    :main.py
mpremote fs cp pico-crt-clock/clock.py   :clock.py
mpremote fs cp pico-crt-clock/icons.py   :icons.py
mpremote fs cp pico-crt-clock/config.py  :config.py
```

Edit `config.py` first - it contains your WiFi credentials and all display
options: location (lat/lon), timezone, DST, temperature and wind units,
date format, and 12/24 hour clock.

To find your coordinates, right-click your location in
[Google Maps](https://maps.google.com) and click the latitude/longitude
that appears at the top of the context menu — it copies to the clipboard.
Alternatively use [latlong.net](https://www.latlong.net).

If you change icons, regenerate `icons.py` on the PC first:

```bash
cd pico-crt-clock && python make_icons.py
```

---

## PC simulator

```bash
cd pico-crt-clock
pip install pygame   # one-time
python run_sim.py
```

`gfx.py` is a pygame-based mock of the `gfx` C extension. Network calls are
always-connected mocks; weather is fetched live from Open-Meteo.
Set `SCALE` in `gfx.py` to resize the window (default 3x).

---

## Python API

```python
import gfx

# Lifecycle
gfx.init()                              # Launch core1 video engine (call once)
gfx.deinit()                            # Stop video engine; core1 parks in WFE

# Display control
gfx.cls(colour)                         # Clear screen; waits for vblank first
gfx.wait_vblank()                       # Block until next vertical blank
gfx.set_border(colour)                  # Set overscan border colour

# Drawing  - colour is 0 (black) ... 15 (white)
gfx.plot(x, y, colour)
gfx.line(x0, y0, x1, y1, colour)
gfx.hline(y, x0, x1, colour)
gfx.circle(x, y, r, colour, filled)
gfx.triangle(x0, y0, x1, y1, x2, y2, colour, filled)
gfx.polygon(x0, y0, x1, y1, x2, y2, x3, y3, colour, filled)

# Text - colour indices as above; bg/fg are background/foreground
gfx.print_char(x, y, char_int, bg, fg)
gfx.print_string(x, y, string, bg, fg)       # 1x scale (8x8 px per glyph)
gfx.print_string_2x(x, y, string, bg, fg)    # 2x scale (16x16 px per glyph)
gfx.scroll_up(colour, rows)

# Sprites
gfx.blit(buf, sw, sh, dx, dy)
# buf  - bytes or bytearray, sw*sh bytes, one byte per pixel (values 0-15)
# sw   - sprite width in pixels
# sh   - sprite height in pixels
# dx   - destination X on screen
# dy   - destination Y on screen
# gfx.blit() adds colour_base (0x10) automatically.
# Maximum sprite size: 256x32 px (GFX_BLIT_BUFSIZE = 8192 bytes).
# Back-to-back blits are safe - core0 waits on gfx_blit_busy automatically.
```

### Colour palette

The display is monochrome. Colour indices map linearly to luminance:

```
0  = black
7  = mid-grey
15 = white
```

---

## Screen geometry

Default video mode: **256 x 192 pixels**, PAL(ish) timing (~312 lines, 50 Hz).
Coordinate origin is top-left.

---

## Known limitations

- **Queue depth** - the command ring buffer holds 64 entries. Pushing more than
  64 commands without core1 draining them will block core0 indefinitely.
