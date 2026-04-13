"""
run_sim.py - Run the pico-crt-clock on a PC with mocked hardware.

    cd pico-crt-clock
    python run_sim.py [--c64font]

Options:
  --c64font   Use the Commodore 64 font instead of the default ZX Spectrum font.

GPIO simulation (switches between modes):
  a       pull GPIO for mode 0 (clock/weather) low
  b       pull GPIO for mode 1 (torus) low
  c/d     pull GPIO for mode 2/3 low (future modes)
  ESC     release all pins → default mode (clock/weather with no switch)

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

# -- handle --c64font before any other imports so gfx.py sees the env var ------
if '--c64font' in sys.argv:
    os.environ['GFX_FONT'] = 'c64'
    sys.argv.remove('--c64font')

import types
import json
import time as _time

# -- ensure pico-crt-clock/ is on the path ------------------------------------
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

os.chdir(_here)

# -- import gfx early so _sim_pins is available for the machine mock -----------
import gfx as _gfx

# -- patch the standard 'time' module with MicroPython-compatible helpers ------
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

# -- mock 'machine' module with GPIO pin simulation ----------------------------
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
        if idx == _gfx._desired_mode:
            self._sim._low = True   # restore mode that was active before reboot
        _gfx._sim_pins.append(self._sim)
        _gfx._update_caption()

    def value(self, v=None):
        if v is None:
            return self._sim.value()
        self._sim._low = not bool(v)

machine               = types.ModuleType('machine')
machine.Pin           = _Pin
machine.PWRON_RESET   = 1
machine.WDT_RESET     = 3
machine.reset_cause   = _reset_cause
machine.soft_reset    = _soft_reset
sys.modules['machine'] = machine

# -- mock 'network' module -----------------------------------------------------
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

# -- mock 'ntptime' module -----------------------------------------------------
ntptime         = types.ModuleType('ntptime')
ntptime.settime = lambda: None
sys.modules['ntptime'] = ntptime

# -- mock 'urequests' module ---------------------------------------------------
import urllib.request

class _Response:
    def __init__(self, data: bytes):
        self.content = data
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

# -- modules to clear on each soft_reset so they re-import fresh ---------------
_APP_MODULES = {'main', 'clock', 'torus', 'common'}

# -- compile main.py once; re-exec on every soft_reset -------------------------
with open(os.path.join(_here, 'main.py')) as f:
    _main_code = compile(f.read(), 'main.py', 'exec')

while True:
    # Clear app modules and sim pins — fresh boot
    for m in _APP_MODULES:
        sys.modules.pop(m, None)
    _gfx._sim_pins.clear()

    try:
        exec(_main_code, {'__name__': '__main__'})
    except _SoftReset:
        pass   # soft_reset() called — loop back for next boot
