"""
run_sim.py - Run the pico-crt-clock on a PC with mocked hardware.

    cd pico-crt-clock
    python run_sim.py [--c64font]

Options:
  --c64font   Use the Commodore 64 font instead of the default ZX Spectrum font.

GPIO simulation (switches between modes):
  a/b/c/d pull the GPIO for APPS entry 0/1/2/3 low (first 4 entries, in order)
  n       cycle the selected app's local-detail switch through its configured positions
  ESC     release all pins -> default mode (APPS[0] with no switch)

  Pressing a key latches that mode until ESC is pressed, mirroring a physical
  sliding switch.  soft_reset() triggers an automatic reboot into the new mode.

What is mocked
--------------
gfx        -> gfx.py in the same directory (pygame renderer)
machine    -> Pin (GPIO stub, reads from gfx._sim_pins), soft_reset
network    -> always connected, SSID "SimulatedWiFi"
ntptime    -> no-op (PC clock is already correct UTC)
urequests  -> urllib.request wrapper (fetches real weather from Open-Meteo)
time.*     -> MicroPython extras: ticks_ms/diff/add, sleep_ms
             time.localtime -> time.gmtime so the manual UTC offset works
             correctly (avoids double timezone conversion)

Requires: pip install pygame
"""

import sys
import os

# Handle --c64font before any other imports so gfx.py sees the env var.
if '--c64font' in sys.argv:
    os.environ['GFX_FONT'] = 'c64'
    sys.argv.remove('--c64font')

import types
import json
import time as _time

# Ensure pico-crt-clock/ is on the path.
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

os.chdir(_here)

# Import gfx early so _sim_pins is available for the machine mock.
import gfx as _gfx

# Patch the standard 'time' module with MicroPython-compatible helpers.
_time.localtime = _time.gmtime

def _ticks_ms():
    return int(_time.monotonic() * 1000) & 0x3FFF_FFFF

def _ticks_diff(a, b):
    diff = (a - b) & 0x3FFF_FFFF
    if diff >= 0x2000_0000:
        diff -= 0x4000_0000
    return diff

def _ticks_add(t, delta):
    return (t + delta) & 0x3FFF_FFFF

def _sleep_ms(ms):
    _gfx._pump()
    _time.sleep(max(0.0, ms / 1000.0))

_time.ticks_ms   = _ticks_ms
_time.ticks_diff = _ticks_diff
_time.ticks_add  = _ticks_add
_time.sleep_ms   = _sleep_ms

# Mock 'machine' module with GPIO pin simulation.
class _SoftReset(BaseException):
    pass

_did_soft_reset = False

def _soft_reset():
    global _did_soft_reset
    _did_soft_reset = True
    raise _SoftReset()

def _reset_cause():
    return machine.PWRON_RESET if not _did_soft_reset else machine.WDT_RESET + 1

class _Pin:
    IN      = 0
    OUT     = 1
    PULL_UP = 2

    def __init__(self, num, mode=None, pull=None):
        self._sim = _gfx._SimPin()
        idx = len(_gfx._sim_pins)
        N   = _gfx._mode_pin_count
        if idx < N:
            if idx == _gfx._desired_mode:
                self._sim._low = True   # restore mode pin that was active before reboot
        elif idx == N:
            self._sim._low = (len(_gfx._detail_gpios) >= 1 and _gfx._detail_mode == 1)
        elif idx == N + 1:
            self._sim._low = (len(_gfx._detail_gpios) >= 2 and _gfx._detail_mode == 2)
        _gfx._sim_pins.append(self._sim)
        _gfx._update_caption()

    def value(self, v=None):
        if v is None:
            return self._sim.value()
        self._sim._low = not bool(v)

class _ADC:
    def __init__(self, pin):
        pass
    def read_u16(self):
        return _gfx._adc_value

machine               = types.ModuleType('machine')
machine.Pin           = _Pin
machine.ADC           = _ADC
machine.PWRON_RESET   = 1
machine.WDT_RESET     = 3
machine.reset_cause   = _reset_cause
machine.soft_reset    = _soft_reset
sys.modules['machine'] = machine

# Mock 'network' module.
class _WLAN:
    def active(self, v=None):    pass
    def connect(self, ssid, pw): pass
    def isconnected(self):       return True
    def config(self, key):
        return {'essid': 'SimulatedWiFi'}.get(key, '')
    def ifconfig(self):
        return ('127.0.0.1', '255.255.255.0', '127.0.0.1', '8.8.8.8')

network        = types.ModuleType('network')
network.STA_IF = 0
network.WLAN   = lambda _mode: _WLAN()
sys.modules['network'] = network

# Mock 'ntptime' module.
ntptime         = types.ModuleType('ntptime')
ntptime.settime = lambda: None
sys.modules['ntptime'] = ntptime

# Mock 'urequests' module.
import urllib.request
import io

class _Response:
    def __init__(self, data: bytes):
        self.content = data
        self.raw = io.BytesIO(data)
    def json(self):
        return json.loads(self.content.decode())
    def close(self):
        pass

def _get(url, timeout=10):
    req = urllib.request.Request(
        url, headers={'User-Agent': 'pico-crt-clock-sim/1.0'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return _Response(r.read())

urequests         = types.ModuleType('urequests')
urequests.get     = _get
sys.modules['urequests'] = urequests

# Read APPS so the sim knows how many mode pins main.py will create.
try:
    from config_local import APPS as _APPS
except ImportError:
    from config import APPS as _APPS
_gfx._mode_pin_count = len(_APPS)

def _detail_gpios_for(entry):
    extras = entry[2] if len(entry) > 2 else {}
    modes = extras.get("modes", {})
    gpios = sorted(k for k in modes if isinstance(k, int))
    return tuple(gpios[:2])

_gfx._app_detail_gpios = tuple(_detail_gpios_for(entry) for entry in _APPS)
_gfx._select_detail_gpios(_gfx._desired_mode)

# Modules to clear on each soft_reset so they re-import fresh.
_APP_MODULES = {
    'main', 'common', 'config', 'config_local',
    'weather', 'news', 'torus', 'sky', 'electricity',
}

# Compile main.py once; re-exec on every soft_reset.
with open(os.path.join(_here, 'main.py')) as f:
    _main_code = compile(f.read(), 'main.py', 'exec')

while True:
    # Clear app modules and sim pins - fresh boot
    for m in _APP_MODULES:
        sys.modules.pop(m, None)
    _gfx._sim_pins.clear()

    try:
        exec(_main_code, {'__name__': '__main__'})
    except _SoftReset:
        pass   # soft_reset() called - loop back for next boot
