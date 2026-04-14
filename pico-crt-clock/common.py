import gfx
import time
import network
import ntptime
import machine
try:
    from config_local import *
except ImportError:
    from config import *


__all__ = [
    'gfx', 'time', 'ntptime',
    'BLACK', 'WHITE', 'WIFI_TIMEOUT_MS',
    '_weekday', '_last_sunday', '_utc_offset',
    'draw_banner', 'connect_wifi', 'reconnect_wifi', 'sync_ntp', 'check_pin_stable',
]

BLACK = 0
WHITE = 15
WIFI_TIMEOUT_MS = 30000

# Tomohiko Sakamoto's weekday formula; 0=Sunday, no mktime needed.
def _weekday(yr, mon, day):
    t = [0, 3, 2, 5, 0, 3, 5, 1, 4, 6, 2, 4]
    if mon < 3:
        yr -= 1
    return (yr + yr//4 - yr//100 + yr//400 + t[mon - 1] + day) % 7  # 0=Sunday

def _last_sunday(yr, mon):
    if mon in (1, 3, 5, 7, 8, 10, 12):
        last = 31
    elif mon in (4, 6, 9, 11):
        last = 30
    else:
        last = 29 if yr % 4 == 0 and (yr % 100 != 0 or yr % 400 == 0) else 28
    return last - _weekday(yr, mon, last)   # step back from last day to Sunday

def _utc_offset(utc_ts):
    base = UTC_OFFSET * 3600
    if not USE_DST:
        return base
    # European DST: +1 h from last Sunday of March 01:00 UTC
    # to last Sunday of October 01:00 UTC.
    t   = time.localtime(utc_ts)
    yr, mon, day, hour = t[0], t[1], t[2], t[3]
    ds  = _last_sunday(yr, 3)
    de  = _last_sunday(yr, 10)
    summer = (
        3 < mon < 10
        or (mon == 3  and (day > ds or (day == ds and hour >= 1)))
        or (mon == 10 and (day < de or (day == de and hour <  1)))
    )
    return base + 3600 if summer else base

def draw_banner(text):
    """Draw a centred status banner: black filled box + white border + text.
    Overlays on the current frame without clearing the screen."""
    tw  = len(text) * 8
    tx  = (256 - tw) // 2
    ty  = 92                        # vertically centred on 192 px screen
    bx0 = tx - 4;  bx1 = tx + tw + 3
    by0 = ty - 4;  by1 = ty + 11
    for y in range(by0, by1 + 1):  # black fill
        gfx.line(bx0, y, bx1, y, BLACK)
    gfx.line(bx0 - 1, by0 - 1, bx1 + 1, by0 - 1, WHITE)   # top
    gfx.line(bx0 - 1, by1 + 1, bx1 + 1, by1 + 1, WHITE)   # bottom
    gfx.line(bx0 - 1, by0 - 1, bx0 - 1, by1 + 1, WHITE)   # left
    gfx.line(bx1 + 1, by0 - 1, bx1 + 1, by1 + 1, WHITE)   # right
    gfx.print_string(tx, ty, text, BLACK, WHITE)

def connect_wifi():
    """Connect to WiFi, return wlan object or None on timeout.
    Returns immediately if already connected (e.g. after soft_reset mode switch).
    On first power-up shows SSID + IP for 4 s so the user can note the address."""
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if wlan.isconnected():
        return wlan
    draw_banner("Connecting WiFi...")
    wlan.connect(WIFI_SSID, WIFI_PASS)
    deadline = time.ticks_add(time.ticks_ms(), WIFI_TIMEOUT_MS)
    while time.ticks_diff(deadline, time.ticks_ms()) > 0:
        if wlan.isconnected():
            if machine.reset_cause() == machine.PWRON_RESET:
                # First power-up boot - show connection info for user to note IP
                gfx.cls(BLACK)
                gfx.print_string(8,  90, "Wifi connected:", BLACK, WHITE)
                gfx.print_string(8, 100, "SSID: {}".format(wlan.config('essid')), BLACK, WHITE)
                gfx.print_string(8, 110, "IP: {}".format(wlan.ifconfig()[0]), BLACK, WHITE)
                gfx.wait_vblank()   # present before sleeping
                time.sleep_ms(4000)
            return wlan
        time.sleep_ms(500)
    return None

def reconnect_wifi(wlan):
    """Reconnect if disconnected; shows banner while attempting."""
    if wlan is not None and not wlan.isconnected():
        draw_banner("Reconnecting WiFi...")
        try:
            wlan.connect(WIFI_SSID, WIFI_PASS)
            deadline = time.ticks_add(time.ticks_ms(), WIFI_TIMEOUT_MS)
            while time.ticks_diff(deadline, time.ticks_ms()) > 0:
                if wlan.isconnected():
                    break
                time.sleep_ms(500)
        except Exception:
            pass

def sync_ntp(clear=False):
    """Sync RTC from NTP. clear=True at boot for a clean screen; False overlays banner on running display."""
    if clear:
        gfx.cls(BLACK)
    draw_banner("NTP sync...")
    try:
        ntptime.settime()
        gfx.cls(BLACK)
        return True
    except Exception:
        gfx.cls(BLACK)
        return False

# For mode switching: require a pin mismatch to persist for threshold milliseconds
# before treating it as a real state change. The counter stores the first
# mismatch timestamp from time.ticks_ms(), so debounce duration is independent
# of loop speed.
def check_pin_stable(pin, expected, counter, threshold=250):
    if pin is None:
        return True, 0

    value = pin.value()
    if value == expected:
        return True, 0

    now = time.ticks_ms()
    if counter == 0:
        counter = now

    return time.ticks_diff(now, counter) < threshold, counter
