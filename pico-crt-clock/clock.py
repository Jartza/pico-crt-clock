import urequests
import json
from config import *
from common import *

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

# Screen layout
# Time  2x font (16 px/char): "HH:MM:SS" = 8x16 = 128 px  -> x=(256-128)/2=64
# Date  1x font (8 px/char):  centred dynamically (no leading zeroes, length varies)
# Temp  2x font:              centred (up to 4 chars, e.g. "+37C")
# Forecast: 3 columns, 32 px icon width, 40 px outer margins
#   left edges: 40, 112, 184  (40+32+40+32+40+32+40 = 256 ok)
TIME_Y         = 0
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

# Weekday constants for date display.  Adjust to your locale as needed.
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

_WIND_LABEL = {"ms": "m/s", "kmh": "km/h", "mph": "mph", "kn": "kn"}
WIND_LABEL  = _WIND_LABEL.get(WIND_UNIT, WIND_UNIT)
TEMP_FMT    = "{:+d}" if TEMP_UNIT == "C" else "{:d}"

wlan = None   # set in run()

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

def _day_icons(wmo_code, sunshine_s, daylight_s, precip_sum_mm, precip_prob):
    """Derive (sky_icon, precip_icon) from daily aggregates."""
    if daylight_s and daylight_s > 0:
        sun_frac = sunshine_s / daylight_s
    else:
        sun_frac = 0.0
    if sun_frac >= 0.5:
        sky_ic = sky_sun
    elif sun_frac >= 0.15:
        sky_ic = sky_partly
    else:
        sky_ic = sky_cloud

    if wmo_code >= 95:
        prc_ic = precip_thunder
    elif wmo_code in range(71, 78) or wmo_code in (85, 86):
        prc_ic = precip_snow    if precip_sum_mm >= 0.5 and precip_prob >= 30 else None
    elif wmo_code in range(51, 56):
        prc_ic = precip_drizzle if precip_sum_mm >= 0.3 and precip_prob >= 25 else None
    elif wmo_code in range(61, 66) or wmo_code in (80, 81, 82):
        prc_ic = precip_rain    if precip_sum_mm >= 1.0 and precip_prob >= 35 else None
    elif wmo_code in (45, 48):
        prc_ic = precip_fog
    else:
        prc_ic = None

    if prc_ic is not None and sky_ic == sky_sun:
        sky_ic = sky_partly

    return sky_ic, prc_ic

def fetch_weather():
    reconnect_wifi(wlan)
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
        cur_temp   = round(data['hourly']['temperature_2m'][time.localtime()[3]])
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
            sunshine_s  = daily['sunshine_duration'][i]
            daylight_s  = daily['daylight_duration'][i]
            precip_mm   = daily['precipitation_sum'][i]
            precip_prob = daily['precipitation_probability_mean'][i]
            sky_ic, prc_ic = _day_icons(code, sunshine_s, daylight_s, precip_mm, precip_prob)
            days.append((sky_ic, prc_ic, (TEMP_FMT + "{}").format(tmax, TEMP_UNIT), day_name))
        return cur_temp, wind_speed, days
    except Exception:
        return None, None, None

def run(pin=None):
    global wlan

    gfx.init()
    gfx.set_border(0)
    gfx.cls(BLACK)

    wlan = connect_wifi()
    if wlan is None:
        gfx.cls(BLACK)
        gfx.print_string(8, 90, "WiFi failed!", BLACK, WHITE)
        time.sleep_ms(2000)

    if not sync_ntp(clear=True):
        gfx.cls(BLACK)
        gfx.print_string(10, 90, "NTP failed!", BLACK, WHITE)
        time.sleep_ms(2000)

    cur_temp   = None
    wind_speed = None
    weather    = [(sky_cloud, None, "---", "---")] * 3

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

    last_sec       = -1
    last_day       = _boot_day
    last_start_day = 1 if FORECAST_NEXT_DAY_HOUR > 0 and _boot_h >= FORECAST_NEXT_DAY_HOUR else 0
    last_move      = time.ticks_ms()
    ox, oy = 0, 0
    vx, vy = 1, 1

    while pin is None or not pin.value():
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

        if day != last_day:
            last_day = day
            try:
                ntptime.settime()
            except Exception:
                pass

        start_day = 1 if FORECAST_NEXT_DAY_HOUR > 0 and h >= FORECAST_NEXT_DAY_HOUR else 0
        _wi = 30 if cur_temp is None else WEATHER_INTERVAL
        if now - last_weather_ts >= _wi or start_day != last_start_day:
            raw = fetch_weather()
            ct, ws, days = parse_weather(raw, start_day)
            if days:
                cur_temp    = ct
                wind_speed  = ws
                weather     = days
            last_weather_ts  = now
            last_start_day   = start_day

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
