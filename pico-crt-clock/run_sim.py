"""
run_sim.py — Run clock.py on Linux PC with mocked hardware modules.

    cd pico-crt-clock
    python run_sim.py

Requires: pip install pygame
Optional: pip install requests   (falls back to urllib if absent)

What is mocked
--------------
gfx        → gfx.py in the same directory (pygame renderer)
network    → always connected, SSID "SimulatedWiFi"
ntptime    → no-op (PC clock is already correct UTC)
urequests  → urllib.request wrapper (fetches real weather from Open-Meteo)
time.*     → MicroPython extras: ticks_ms/diff/add, sleep_ms
             time.localtime → time.gmtime so the manual UTC offset in clock.py
             works correctly (avoids double timezone conversion)
"""

import sys
import os
import types
import json
import time as _time
import urllib.request

# ── ensure pico-crt-clock/ is on the path so "import gfx" finds gfx.py ───────
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

# ── patch the standard 'time' module with MicroPython-compatible helpers ───────
# clock.py applies its own UTC→local offset, so localtime must return UTC.
_time.localtime = _time.gmtime

def _ticks_ms():
    return int(_time.monotonic() * 1000) & 0x3FFF_FFFF   # 29-bit like MicroPython

def _ticks_diff(a, b):
    # Signed difference; correct for typical intervals well under the wraparound.
    diff = (a - b) & 0x3FFF_FFFF
    if diff >= 0x2000_0000:
        diff -= 0x4000_0000
    return diff

def _ticks_add(t, delta):
    return (t + delta) & 0x3FFF_FFFF

def _sleep_ms(ms):
    import gfx as _gfx   # pump events during sleep so the window stays responsive
    _gfx._pump()
    _time.sleep(max(0.0, ms / 1000.0))

_time.ticks_ms   = _ticks_ms
_time.ticks_diff = _ticks_diff
_time.ticks_add  = _ticks_add
_time.sleep_ms   = _sleep_ms

# ── mock 'network' module ─────────────────────────────────────────────────────
class _WLAN:
    def active(self, v=None):   pass
    def connect(self, ssid, pw): pass
    def isconnected(self):      return True
    def config(self, key):
        return {'essid': 'SimulatedWiFi'}.get(key, '')
    def ifconfig(self):
        return ('127.0.0.1', '255.255.255.0', '127.0.0.1', '8.8.8.8')

network       = types.ModuleType('network')
network.STA_IF = 0
network.WLAN   = lambda _mode: _WLAN()
sys.modules['network'] = network

# ── mock 'ntptime' module ─────────────────────────────────────────────────────
ntptime = types.ModuleType('ntptime')
ntptime.settime = lambda: None   # PC clock is already set
sys.modules['ntptime'] = ntptime

# ── mock 'urequests' module ───────────────────────────────────────────────────
class _Response:
    def __init__(self, data: bytes):
        self._data = data
    def json(self):
        return json.loads(self._data.decode())
    def close(self):
        pass

def _get(url, timeout=10):
    req = urllib.request.Request(
        url, headers={'User-Agent': 'pico-crt-clock-sim/1.0'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return _Response(r.read())

urequests     = types.ModuleType('urequests')
urequests.get = _get
sys.modules['urequests'] = urequests

# ── run clock.py ──────────────────────────────────────────────────────────────
os.chdir(_here)
with open(os.path.join(_here, 'clock.py')) as f:
    code = f.read()

exec(compile(code, 'clock.py', 'exec'), {'__name__': '__main__'})
