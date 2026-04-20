#!/usr/bin/env python3
import builtins
import copy
import importlib
import io
import json
import os
import sys
import time as _time
import types
from datetime import datetime, timedelta, timezone

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")


ROOT = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(ROOT, "sim_screenshots")
IMG_DIR = os.path.join(os.path.dirname(ROOT), "img")
FIXED_UTC = datetime(2026, 4, 20, 12, 15, 0, tzinfo=timezone.utc)
FIXED_EPOCH = int(FIXED_UTC.timestamp())
README_SCALE = 3


class CaptureDone(BaseException):
    pass


class _MicropythonStub:
    viper = staticmethod(lambda f: f)
    native = staticmethod(lambda f: f)


class _Ptr:
    __slots__ = ("_a",)

    def __init__(self, a):
        self._a = a

    def __getitem__(self, i):
        return self._a[i]

    def __setitem__(self, i, v):
        self._a[i] = v


builtins.micropython = _MicropythonStub()
builtins.ptr32 = _Ptr
builtins.ptr16 = _Ptr
builtins.ptr8 = _Ptr

if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
os.chdir(ROOT)

import gfx  # noqa: E402
import pygame  # noqa: E402


_real_time = _time.time
_real_sleep = _time.sleep
_time.time = lambda: FIXED_EPOCH
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
    gfx._pump()
    _real_sleep(max(0.0, ms / 1000.0))


_time.ticks_ms = _ticks_ms
_time.ticks_diff = _ticks_diff
_time.ticks_add = _ticks_add
_time.sleep_ms = _sleep_ms


LOW_PINS = set()
_capture_target = 0
_capture_path = None
_present_count = 0
_orig_present = gfx._present


def _capture_present():
    global _present_count
    _orig_present()
    _present_count += 1
    if _capture_path and _present_count >= _capture_target:
        pygame.image.save(gfx._surface, _capture_path)
        raise CaptureDone()


gfx._present = _capture_present


def _response_bytes(payload):
    if isinstance(payload, bytes):
        return payload
    return json.dumps(payload, separators=(",", ":")).encode()


class _Response:
    def __init__(self, payload):
        self.content = _response_bytes(payload)
        self.raw = io.BytesIO(self.content)

    def json(self):
        return json.loads(self.content.decode())

    def close(self):
        pass


def _weather_daily_payload():
    days = ["2026-04-20", "2026-04-21", "2026-04-22", "2026-04-23", "2026-04-24", "2026-04-25", "2026-04-26"]
    return {
        "current": {"weather_code": 2, "wind_speed_10m": 6.2},
        "daily": {
            "time": days,
            "weather_code": [2, 61, 95, 3, 71, 1, 45],
            "temperature_2m_max": [11.4, 8.2, 6.9, 9.7, 2.5, 10.6, 7.4],
            "sunshine_duration": [32000, 8000, 5000, 14000, 6000, 22000, 3000],
            "daylight_duration": [50000, 50100, 50200, 50300, 50400, 50500, 50600],
            "precipitation_sum": [0.0, 3.8, 7.0, 0.5, 2.1, 0.0, 0.0],
            "precipitation_probability_mean": [5, 72, 88, 20, 55, 10, 15],
        },
    }


def _weather_hourly_payload():
    temps = [4.0, 3.8, 3.5, 3.1, 2.8, 2.6, 3.0, 4.2, 5.6, 7.1, 8.9, 9.8,
             10.4, 10.8, 10.6, 10.1, 9.2, 8.3, 7.5, 6.8, 6.1, 5.5, 5.0, 4.6]
    times = [f"2026-04-20T{h:02d}:00" for h in range(24)]
    return {"hourly": {"time": times, "temperature_2m": temps}}


def _guardian_payload():
    return {
        "response": {
            "results": [{
                "fields": {
                    "headline": "Arctic lights glow over southern Finland after strong solar wind",
                    "trailText": "<p>A bright aurora display reached unusually far south as clear skies opened late in the evening.</p>",
                    "body": (
                        "<p>Forecasters reported a burst of solar wind that pushed aurora activity across much of Finland.</p>"
                        "<p>Observers in coastal towns described moving curtains, bright arcs and brief pillars visible to the naked eye.</p>"
                        "<p>Conditions are expected to calm overnight, though another weaker display may remain possible before dawn.</p>"
                    ),
                }
            }]
        }
    }


def _kp_payload():
    base = datetime(2026, 4, 20, 12, 0, 0, tzinfo=timezone.utc)
    out = []
    for i, kp in enumerate((3.0, 4.2, 5.1, 6.4, 5.8, 4.6, 3.7, 2.9)):
        out.append({
            "time_tag": (base + timedelta(hours=3 * i)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "kp": kp,
            "observed": "predicted",
        })
    return out


def _elec_payload():
    rows = []
    start = datetime(2026, 4, 19, 21, 0, 0, tzinfo=timezone.utc)
    today = [62, 58, 51, 47, 44, 46, 55, 66, 78, 84, 93, 101,
             97, 88, 79, 73, 68, 71, 82, 96, 108, 99, 83, 70]
    tomorrow = [64, 60, 56, 52, 49, 51, 57, 69, 75, 80, 86, 90,
                92, 87, 79, 74, 70, 72, 76, 81, 85, 82, 74, 68]
    for i, price in enumerate(today + tomorrow):
        rows.append({
            "timestamp": int((start + timedelta(hours=i)).timestamp()),
            "price": price,
        })
    return {"success": True, "data": {"fi": rows}}


def _mock_get(url, timeout=10):
    del timeout
    if "open-meteo.com" in url and "&current=" in url:
        return _Response(_weather_daily_payload())
    if "open-meteo.com" in url and "&hourly=temperature_2m" in url:
        return _Response(_weather_hourly_payload())
    if "content.guardianapis.com/search" in url:
        return _Response(_guardian_payload())
    if "swpc.noaa.gov/products/noaa-planetary-k-index-forecast.json" in url:
        return _Response(_kp_payload())
    if "dashboard.elering.ee/api/nps/price" in url:
        return _Response(_elec_payload())
    raise RuntimeError("No mock for URL: {}".format(url))


class _Pin:
    IN = 0
    OUT = 1
    PULL_UP = 2

    def __init__(self, num, mode=None, pull=None):
        self.num = num

    def value(self, v=None):
        if v is None:
            return 0 if self.num in LOW_PINS else 1
        if v:
            LOW_PINS.discard(self.num)
        else:
            LOW_PINS.add(self.num)


class _ADC:
    def __init__(self, pin):
        self.pin = pin

    def read_u16(self):
        return 32768


def _install_mock_modules():
    machine = types.ModuleType("machine")
    machine.Pin = _Pin
    machine.ADC = _ADC
    machine.PWRON_RESET = 1
    machine.WDT_RESET = 3
    machine.reset_cause = lambda: machine.WDT_RESET + 1
    machine.soft_reset = lambda: None
    sys.modules["machine"] = machine

    network = types.ModuleType("network")
    network.STA_IF = 0

    class _WLAN:
        def active(self, v=None):
            return None

        def connect(self, ssid, pw):
            return None

        def isconnected(self):
            return True

        def config(self, key):
            return {"essid": "SimulatedWiFi"}.get(key, "")

        def ifconfig(self):
            return ("127.0.0.1", "255.255.255.0", "127.0.0.1", "8.8.8.8")

    network.WLAN = lambda _mode: _WLAN()
    sys.modules["network"] = network

    ntptime = types.ModuleType("ntptime")
    ntptime.settime = lambda: None
    sys.modules["ntptime"] = ntptime

    urequests = types.ModuleType("urequests")
    urequests.get = _mock_get
    sys.modules["urequests"] = urequests


def _make_config():
    base = importlib.import_module("config")
    cfg = types.ModuleType("config_local")
    for name in dir(base):
        if name.startswith("_"):
            continue
        setattr(cfg, name, copy.deepcopy(getattr(base, name)))
    cfg.NEWS_API_KEY = "SIMULATED"
    cfg.NEWS_SECTIONS = "world:1"
    cfg.NEWS_COUNT = 1
    cfg.NEWS_INTERVAL = 24 * 60 * 60
    cfg.NEWS_HOLD = 1
    cfg.NEWS_HOLD_SUM = 1
    cfg.NEWS_HOLD_AFTER = 1
    cfg.NEWS_SCROLL_SPEED = 1
    cfg.RSVP_WPM = 240
    cfg.USE_ADC_SPEED = False
    cfg.SCREENSAVER_SPEED = 0
    cfg.APPS = [
        ("weather", 10),
        ("news", 12, {"modes": {"default": "summary", 13: "full", 14: "rsvp"}}),
        ("sky", 11),
        ("electricity", 15, {"modes": {"default": "today", 13: "tomorrow"}}),
        ("torus", 16),
    ]
    return cfg


def _clear_modules():
    for name in (
        "common", "weather", "news", "sky", "electricity", "torus",
        "config_local",
    ):
        sys.modules.pop(name, None)


def _ensure_clean_dirs():
    for name in ("weathercache", "newscache", "skycache", "eleccache"):
        path = os.path.join(ROOT, name)
        if os.path.isdir(path):
            for fn in os.listdir(path):
                try:
                    os.remove(os.path.join(path, fn))
                except OSError:
                    pass


def _run_capture(module_name, out_name, present_target, low_pins=None, kwargs=None):
    global _capture_path, _capture_target, _present_count
    LOW_PINS.clear()
    if low_pins:
        LOW_PINS.update(low_pins)
    _clear_modules()
    sys.modules["config_local"] = _make_config()
    _install_mock_modules()
    _capture_path = os.path.join(OUT_DIR, out_name)
    _capture_target = present_target
    _present_count = 0
    module = importlib.import_module(module_name)
    try:
        module.run(None, **(kwargs or {}))
    except CaptureDone:
        pass
    finally:
        _capture_path = None


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs(IMG_DIR, exist_ok=True)
    _ensure_clean_dirs()
    captures = [
        ("weather", "weather.png", 7, None, None),
        ("news", "news_summary.png", 5, None, {"modes": {"default": "summary", 13: "full", 14: "rsvp"}}),
        ("news", "news_full.png", 5, {13}, {"modes": {"default": "summary", 13: "full", 14: "rsvp"}}),
        ("news", "news_rsvp.png", 16, {14}, {"modes": {"default": "summary", 13: "full", 14: "rsvp"}}),
        ("sky", "sky.png", 6, None, None),
        ("electricity", "electricity_today.png", 6, None, {"modes": {"default": "today", 13: "tomorrow"}}),
        ("electricity", "electricity_tomorrow.png", 6, {13}, {"modes": {"default": "today", 13: "tomorrow"}}),
        ("torus", "torus.png", 6, None, None),
    ]
    for module_name, out_name, present_target, low_pins, kwargs in captures:
        _run_capture(module_name, out_name, present_target, low_pins, kwargs)
        src = os.path.join(OUT_DIR, out_name)
        dst = os.path.join(IMG_DIR, "sim_" + out_name)
        surf = pygame.image.load(src)
        up = pygame.transform.scale(
            surf,
            (surf.get_width() * README_SCALE, surf.get_height() * README_SCALE),
        )
        pygame.image.save(up, dst)
        print(out_name)


if __name__ == "__main__":
    main()
