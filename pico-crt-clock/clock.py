import gfx
import time
import network
import ntptime
import urequests
import json
from config import *

with open('icons.bin', 'rb') as _f:
    _icons = _f.read()
_iv = memoryview(_icons)
sky_sun        = _iv[0*512:1*512]
sky_partly     = _iv[1*512:2*512]
sky_cloud      = _iv[2*512:3*512]
precip_rain    = _iv[3*512:4*512]
precip_snow    = _iv[4*512:5*512]
precip_drizzle = _iv[5*512:6*512]
precip_thunder = _iv[6*512:7*512]
precip_fog     = _iv[7*512:8*512]
del _f, _iv

# pico-mposite palette indices - B/W display
BLACK = 0
WHITE = 15

WIFI_TIMEOUT_MS = 30000

# Screen layout
# Time  2x font (16 px/char): "HH:MM:SS" = 8x16 = 128 px  -> x=(256-128)/2=64
# Date  1x font (8 px/char):  centred dynamically (no leading zeroes, length varies)
# Temp  2x font:              centred (up to 4 chars, e.g. "+37C")
# Forecast: 3 columns, 32 px icon width, 40 px outer margins
#   left edges: 40, 112, 184  (40+32+40+32+40+32+40 = 256 ok)
TIME_Y = 0
DATE_Y         = 18
TODAY_Y        = 40
FORECAST_X     = [40, 112, 184]
FORECAST_Y     = 68     # top of forecast block (day label)
GRAYBAR_Y      = 160    # grayscale calibration bar (256x32 px)

# Burn-in screensaver - DVD-style diagonal bounce.
# Worst-case content width is 4 chars for both C ("+50C") and F ("110F" - no plus,
# since sub-zero Fahrenheit never reaches 3 digits in any realistic climate).
#   left=24, right=232, top=0, bottom=129  ->  ox in [-24,+24], oy in [0,63]
SS_OX_MAX = 24
SS_OY_MAX = 63

# Weekday constants for date display and DST handling.  Adjust to your locale as needed.
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

_WIND_LABEL = {"ms": "m/s", "kmh": "km/h", "mph": "mph", "kn": "kn"}
WIND_LABEL  = _WIND_LABEL.get(WIND_UNIT, WIND_UNIT)
TEMP_FMT    = "{:+d}" if TEMP_UNIT == "C" else "{:d}"

gfx.init()
gfx.set_border(0)
gfx.cls(BLACK)

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

# Window drawing helper: all content is redrawn every frame, so we can just issue
# one cls() and then blit text/icons without extra vblank waits (cls() includes
# an implicit wait_vblank, so the first blit after it is guaranteed to be in the next
# field). All subsequent drawing commands go straight to the queue and core1 renders
# them in C before the next field.
def draw_all(time_str, date_str, cur_temp, wind_speed, weather_days, ox=0, oy=0):
    gfx.cls(BLACK)
    tx = (256 - len(time_str) * 16) // 2 + ox
    gfx.print_string_2x(tx, TIME_Y + oy, time_str, BLACK, WHITE)
    gfx.print_string((256 - len(date_str) * 8) // 2 + ox, DATE_Y + oy, date_str, BLACK, WHITE)
    if cur_temp is not None:
        if wind_speed is not None:
            ts = (TEMP_FMT + "{}  {:d}{}").format(cur_temp, TEMP_UNIT, wind_speed, WIND_LABEL)
        else:
            ts = (TEMP_FMT + "{}").format(cur_temp, TEMP_UNIT)
        tx = 128 + ox - len(ts) * 8
        gfx.print_string_2x(tx, TODAY_Y + oy, ts, BLACK, WHITE)
        bx0 = tx - 3
        bx1 = tx + len(ts) * 16 + 3
        by0 = TODAY_Y + oy - 5
        by1 = TODAY_Y + oy + 19
        gfx.line(bx0, by0, bx1, by0, WHITE)   # top
        gfx.line(bx0, by1, bx1, by1, WHITE)   # bottom
        gfx.line(bx0, by0, bx0, by1, WHITE)   # left
        gfx.line(bx1, by0, bx1, by1, WHITE)   # right
    for i, (sky_ic, prc_ic, temp_str, day_name) in enumerate(weather_days):
        ix = FORECAST_X[i] + ox
        fy = FORECAST_Y + oy
        gfx.print_string(ix + 4, fy, day_name, BLACK, WHITE)
        gfx.blit(sky_ic, 32, 16, ix, fy + 10)
        if prc_ic is not None:
            gfx.blit(prc_ic, 32, 16, ix, fy + 27)
        tx = ix + (32 - len(temp_str) * 16) // 2
        gfx.print_string_2x(tx, fy + 45, temp_str, BLACK, WHITE)

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

# WiFi connection with status messages.
def connect_wifi():
    gfx.cls(BLACK)
    gfx.print_string(10, 90, "Connecting WiFi...", BLACK, WHITE)
    time.sleep_ms(1000)
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    wlan.connect(WIFI_SSID, WIFI_PASS)
    deadline = time.ticks_add(time.ticks_ms(), WIFI_TIMEOUT_MS)
    while time.ticks_diff(deadline, time.ticks_ms()) > 0:
        if wlan.isconnected():
            return wlan
        time.sleep_ms(500)
    return None

# NTP sync - needed for correct local time and daily weather refresh.
def sync_ntp():
    gfx.cls(BLACK)
    gfx.print_string(10, 90, "NTP sync...", BLACK, WHITE)
    try:
        ntptime.settime()
        gfx.cls(BLACK)
        return True
    except Exception:
        gfx.cls(BLACK)
        return False

# Weather - Open-Meteo, no API key needed
# WMO weather codes: 0=clear, 1-3=cloudy, 45/48=fog, 51-55=drizzle,
# 61-65=rain, 71-77=snow, 80-82=showers, 85-86=snow showers, 95-99=thunder
def _day_icons(wmo_code, sunshine_s, daylight_s, precip_sum_mm, precip_prob):
    """Derive (sky_icon, precip_icon) from daily aggregates.
    Sky is based on sunshine fraction (physics-based, not worst-case WMO code).
    Precip type comes from WMO code; visibility is gated by both precip_sum
    and precipitation_probability_mean (both thresholds must be met)."""
    # Sky icon: sunshine fraction of daylight hours
    if daylight_s and daylight_s > 0:
        sun_frac = sunshine_s / daylight_s
    else:
        sun_frac = 0.0          # polar night guard
    if sun_frac >= 0.5:
        sky_ic = sky_sun
    elif sun_frac >= 0.15:
        sky_ic = sky_partly
    else:
        sky_ic = sky_cloud

    # Precip icon: type from WMO code, visibility gated by actual sum AND probability
    if wmo_code >= 95:
        prc_ic = precip_thunder              # always show thunderstorm
    elif wmo_code in range(71, 78) or wmo_code in (85, 86):
        prc_ic = precip_snow    if precip_sum_mm >= 0.5 and precip_prob >= 30 else None
    elif wmo_code in range(51, 56):
        prc_ic = precip_drizzle if precip_sum_mm >= 0.3 and precip_prob >= 25 else None
    elif wmo_code in range(61, 66) or wmo_code in (80, 81, 82):
        prc_ic = precip_rain    if precip_sum_mm >= 1.0 and precip_prob >= 35 else None
    elif wmo_code in (45, 48):
        prc_ic = precip_fog
    else:
        prc_ic = None           # clear, partly cloudy, etc.

    # Don't show sun + rain: downgrade sky to partly if precip is present
    if prc_ic is not None and sky_ic == sky_sun:
        sky_ic = sky_partly

    return sky_ic, prc_ic

def fetch_weather():
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
    draw_banner("Fetching weather...")
    url = (
        "https://api.open-meteo.com/v1/forecast"
        "?latitude={}&longitude={}"
        "&current=weather_code,wind_speed_10m"
        "&hourly=temperature_2m"
        "&daily=weather_code,temperature_2m_max,sunshine_duration,daylight_duration,precipitation_sum,precipitation_probability_mean"
        "&forecast_days=7&timezone=auto"
        "&temperature_unit={}&wind_speed_unit={}"
    ).format(LATITUDE, LONGITUDE,
             "fahrenheit" if TEMP_UNIT == "F" else "celsius",
             WIND_UNIT)
    try:
        r = urequests.get(url, timeout=30)
        data = r.json()
        r.close()
        return data
    except Exception:
        return None

def parse_weather(data, start_day=0):
    """Returns (cur_temp_int, wind_speed_int, [(sky_ic, prc_ic, temp_str, day_name), ...])
    or (None, None, None) on failure."""
    if data is None:
        return None, None, None
    try:
        _now = time.time()
        _lt  = time.localtime(_now + _utc_offset(_now))
        _ts  = "{:04d}-{:02d}-{:02d}T{:02d}:00".format(_lt[0], _lt[1], _lt[2], _lt[3])
        _hi  = next((i for i, t in enumerate(data['hourly']['time']) if t == _ts), 0)
        cur_temp   = round(data['hourly']['temperature_2m'][_hi])
        wind_speed = round(data['current']['wind_speed_10m'])
        daily      = data['daily']
        days = []
        n = len(daily['time'])
        for i in range(start_day, min(start_day + 3, n)):
            code     = daily['weather_code'][i]
            tmax     = round(daily['temperature_2m_max'][i])
            date_str = daily['time'][i]             # "YYYY-MM-DD"
            yr  = int(date_str[0:4])
            mon = int(date_str[5:7])
            day = int(date_str[8:10])
            # Sakamoto gives 0=Sunday; shift to DAYS index (0=Mon ... 6=Sun)
            day_name = DAYS[(_weekday(yr, mon, day) + 6) % 7]
            sunshine_s = daily['sunshine_duration'][i]
            daylight_s = daily['daylight_duration'][i]
            precip_mm  = daily['precipitation_sum'][i]
            precip_prob = daily['precipitation_probability_mean'][i]
            sky_ic, prc_ic = _day_icons(code, sunshine_s, daylight_s, precip_mm, precip_prob)
            days.append((sky_ic, prc_ic, (TEMP_FMT + "{}").format(tmax, TEMP_UNIT), day_name))
        return cur_temp, wind_speed, days
    except Exception:
        return None, None, None

# Startup sequence: connect WiFi, sync NTP, fetch initial weather.  Show status
wlan = connect_wifi()
if wlan is None:
    gfx.cls(BLACK)
    gfx.print_string(8, 90, "WiFi failed!", BLACK, WHITE)
    time.sleep_ms(2000)
else:
    gfx.cls(BLACK)
    ssid_str = "SSID: {}".format(wlan.config('essid'))
    ip_str   = "IP: {}".format(wlan.ifconfig()[0])
    gfx.print_string(8, 90, "Wifi connected:", BLACK, WHITE)
    gfx.print_string(8, 100, ssid_str, BLACK, WHITE)
    gfx.print_string(8, 110, ip_str, BLACK, WHITE)
    time.sleep_ms(2000)

if not sync_ntp():
    gfx.cls(BLACK)
    gfx.print_string(10, 90, "NTP failed!", BLACK, WHITE)
    time.sleep_ms(2000)

cur_temp   = None
wind_speed = None
weather    = [(sky_cloud, None, "---", "---")] * 3   # shown if first fetch fails

_boot_t  = time.time()
_boot_lt = time.localtime(_boot_t + _utc_offset(_boot_t))
_boot_h  = _boot_lt[3]
_boot_day = _boot_lt[2]
raw = fetch_weather()
ct, ws, days = parse_weather(raw, 1 if FORECAST_NEXT_DAY_HOUR > 0 and _boot_h >= FORECAST_NEXT_DAY_HOUR else 0)
if days:
    cur_temp   = ct
    wind_speed = ws
    weather    = days
last_weather_ts = time.time()

# Main loop: update time every second, refresh weather every WEATHER_INTERVAL seconds
# or on day change, and move screensaver every 300 ms.  All content is redrawn every
# frame. cls() does wait for vblank, so there is no flicker as the drawing usually
# finishes before the next field starts.
last_sec       = -1
last_day       = _boot_day
last_h         = _boot_h
last_start_day = 1 if FORECAST_NEXT_DAY_HOUR > 0 and _boot_h >= FORECAST_NEXT_DAY_HOUR else 0
last_move      = time.ticks_ms()
ox, oy     = 0, 0
vx, vy     = 1, 1     # start moving right + down; oy is clamped to [0, SS_OY_MAX]

while True:
    now = time.time()
    t   = time.localtime(now + _utc_offset(now))
    yr, mon, day = t[0], t[1], t[2]
    h,  m,   s   = t[3], t[4], t[5]

    if CLOCK_12H:
        h12 = h % 12 or 12
        time_str = "{}:{:02d}:{:02d}{}".format(h12, m, s, "am" if h < 12 else "pm")
    else:
        time_str = "{:02d}:{:02d}:{:02d}".format(h, m, s)
    _dp = {'D': str(day), 'M': str(mon), 'Y': str(yr)}
    date_str = DATE_SEP.join(_dp[c] for c in DATE_ORDER)

    # Day change: trigger silent NTP re-sync for RTC drift
    if day != last_day:
        last_day = day
        try:
            ntptime.settime()
        except Exception:
            pass

    # Periodic weather refresh; retry every 30 s if no data yet, else WEATHER_INTERVAL
    start_day = 1 if FORECAST_NEXT_DAY_HOUR > 0 and h >= FORECAST_NEXT_DAY_HOUR else 0
    _wi = 30 if cur_temp is None else WEATHER_INTERVAL
    if now - last_weather_ts >= _wi or start_day != last_start_day:
        raw = fetch_weather()
        ct, ws, days = parse_weather(raw, start_day)
        if days:            # keep old data on failure
            cur_temp    = ct
            wind_speed  = ws
            weather     = days
        last_weather_ts  = now
        last_start_day   = start_day
        last_h           = h

    # Hour change: re-parse cached data to pick the new hourly temperature
    elif h != last_h:
        last_h = h
        if raw is not None:
            ct, _, _ = parse_weather(raw, start_day)
            if ct is not None:
                cur_temp = ct

    # Advance screensaver position every SCREENSAVER_SPEED*50 ms (e.g. 100 ms for speed=2).
    # or disable movement if SCREENSAVER_SPEED is 999 or more.
    if SCREENSAVER_SPEED < 999 and time.ticks_diff(time.ticks_ms(), last_move) >= (SCREENSAVER_SPEED * 50):
        last_move = time.ticks_ms()
        ox += vx
        oy += vy
        if ox >= SS_OX_MAX:
            ox = SS_OX_MAX;  vx = -1
        elif ox <= -SS_OX_MAX:
            ox = -SS_OX_MAX; vx =  1
        if oy >= SS_OY_MAX:
            oy = SS_OY_MAX;  vy = -1
        elif oy <= 0:
            oy = 0;          vy =  1
        last_sec = s

    draw_all(time_str, date_str, cur_temp, wind_speed, weather, ox, oy)
    time.sleep_ms(10)
