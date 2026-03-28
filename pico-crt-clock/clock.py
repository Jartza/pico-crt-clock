import gfx
import time
import network
import ntptime
import urequests
import json
from icons import sky_sun, sky_partly, sky_cloud, precip_drizzle, precip_rain, precip_snow, precip_thunder
from config import WIFI_SSID, WIFI_PASS, LATITUDE, LONGITUDE, WEATHER_INTERVAL, FORECAST_NEXT_DAY_HOUR

# pico-mposite palette indices — B/W display
BLACK = 0
WHITE = 15

WIFI_TIMEOUT_MS = 30000

# Screen layout
# Time  2× font (16 px/char): "HH:MM:SS" = 8×16 = 128 px  → x=(256-128)/2=64
# Date  1× font (8 px/char):  centred dynamically (no leading zeroes, length varies)
# Temp  2× font:              centred (up to 4 chars, e.g. "+37C")
# Forecast: 3 columns, 32 px icon width, 40 px outer margins
#   left edges: 40, 112, 184  (40+32+40+32+40+32+40 = 256 ✓)
TIME_X, TIME_Y = 64, 0
DATE_Y         = 18
TODAY_Y        = 40
FORECAST_X     = [40, 112, 184]
FORECAST_Y     = 68     # top of forecast block (day label)
GRAYBAR_Y      = 160    # grayscale calibration bar (256×32 px)

# Burn-in screensaver — DVD-style diagonal bounce.
# Worst-case content extents (4-char forecast temp "+37C"/"-10C"):
#   left=24, right=232, top=0, bottom=129  →  ox ∈ [−24,+24], oy ∈ [0,63]
SS_OX_MAX = 24
SS_OY_MAX = 63

# Weekday constants for date display and DST handling.  Adjust to your locale as needed.
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

# Boot mode detection: if USB host is present, skip graphics init and main loop to
# leave REPL available for debugging.  Otherwise, start the clock app.
USB_TIMEOUT_MS = 2000
usb_host = False

deadline = time.ticks_add(time.ticks_ms(), USB_TIMEOUT_MS)
while time.ticks_diff(deadline, time.ticks_ms()) > 0:
    if gfx.usb_ready():
        usb_host = True
        break
    time.sleep_ms(50)

if usb_host:
    print("USB host detected — REPL mode, video engine not started.")

else:
    gfx.usb_disable()
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

    # Finnish/European DST.
    # Adjust dates to your own location or remove DST handling if not needed.
    # DST handling is hardcoded for simplicity. In Finland, and most of the
    # Europe, DST starts on the last Sunday of March at 03:00 (clocks go
    # forward to 04:00) and ends on the last Sunday of October at 04:00
    # (clocks go back to 03:00).
    def _utc_offset(utc_ts):
        t   = time.localtime(utc_ts)
        yr, mon, day, hour = t[0], t[1], t[2], t[3]
        ds  = _last_sunday(yr, 3)
        de  = _last_sunday(yr, 10)
        summer = (
            3 < mon < 10
            or (mon == 3  and (day > ds or (day == ds and hour >= 1)))
            or (mon == 10 and (day < de or (day == de and hour <  1)))
        )
        return 3 * 3600 if summer else 2 * 3600

    # Window drawing helper: all content is redrawn every frame, so we can just issue
    # one cls() and then blit text/icons without extra vblank waits (cls() includes
    # an implicit wait_vblank, so the first blit after it is guaranteed to be in the next
    # field). All subsequent drawing commands go straight to the queue and core1 renders
    # them in C before the next field.
    def draw_all(time_str, date_str, cur_temp, wind_speed, weather_days, ox=0, oy=0):
        gfx.cls(BLACK)
        gfx.print_string_2x(TIME_X + ox, TIME_Y + oy, time_str, BLACK, WHITE)
        gfx.print_string((256 - len(date_str) * 8) // 2 + ox, DATE_Y + oy, date_str, BLACK, WHITE)
        if cur_temp is not None:
            if wind_speed is not None:
                ts = "{:+d}C  {:d}m/s".format(cur_temp, wind_speed)
            else:
                ts = "{:+d}C".format(cur_temp)
            tx = 128 + ox - len(ts) * 8
            gfx.print_string_2x(tx, TODAY_Y + oy, ts, BLACK, WHITE)
            bx0 = tx - 3
            bx1 = tx + len(ts) * 16 + 3
            by0 = TODAY_Y + oy - 3
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

    # NTP sync — needed for correct local time and daily weather refresh.
    def sync_ntp():
        gfx.cls(BLACK)
        gfx.print_string(10, 90, "NTP sync...", BLACK, WHITE)
        try:
            ntptime.settime()
            return True
        except Exception:
            return False

    # Weather - Open-Meteo, no API key needed
    # WMO weather codes: 0=clear, 1-3=cloudy, 45/48=fog, 51-55=drizzle,
    # 61-65=rain, 71-77=snow, 80-82=showers, 85-86=snow showers, 95-99=thunder
    def _wmo_icons(code):
        """Map WMO code → (sky_icon, precip_icon).  precip_icon may be None."""
        if code == 0:
            return sky_sun,    None
        elif code <= 1:
            return sky_sun,    None
        elif code <= 2:
            return sky_partly, None
        elif code <= 3:
            return sky_cloud,  None
        elif code <= 48:
            return sky_cloud,  precip_drizzle  # fog — show as fine precip
        elif code <= 55:
            return sky_cloud,  precip_drizzle
        elif code <= 65:
            return sky_cloud,  precip_rain
        elif code <= 77:
            return sky_cloud,  precip_snow
        elif code <= 82:
            return sky_cloud,  precip_rain
        elif code <= 86:
            return sky_cloud,  precip_snow
        else:
            return sky_cloud,  precip_thunder   # thunderstorm

    def fetch_weather(show_msg=False):
        if show_msg:
            gfx.cls(BLACK)
            gfx.print_string(52, 92, "Fetching weather...", BLACK, WHITE)
        url = (
            "https://api.open-meteo.com/v1/forecast"
            "?latitude={}&longitude={}"
            "&current=temperature_2m,weather_code,wind_speed_10m"
            "&daily=weather_code,temperature_2m_max"
            "&forecast_days=7&timezone=Europe%2FHelsinki"
            "&wind_speed_unit=ms"
        ).format(LATITUDE, LONGITUDE)
        try:
            r = urequests.get(url, timeout=20)
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
            cur_temp   = round(data['current']['temperature_2m'])
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
                # Sakamoto gives 0=Sunday; shift to DAYS index (0=Mon … 6=Sun)
                day_name = DAYS[(_weekday(yr, mon, day) + 6) % 7]
                sky_ic, prc_ic = _wmo_icons(code)
                days.append((sky_ic, prc_ic, "{:+d}C".format(tmax), day_name))
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
    _boot_h  = time.localtime(_boot_t + _utc_offset(_boot_t))[3]
    raw = fetch_weather(show_msg=True)
    ct, ws, days = parse_weather(raw, 1 if _boot_h >= FORECAST_NEXT_DAY_HOUR else 0)
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
    last_day       = -1
    last_start_day = 1 if _boot_h >= FORECAST_NEXT_DAY_HOUR else 0
    last_move      = time.ticks_ms()
    ox, oy     = 0, 0
    vx, vy     = 1, 1     # start moving right + down; oy is clamped to [0, SS_OY_MAX]

    while True:
        now = time.time()
        t   = time.localtime(now + _utc_offset(now))
        yr, mon, day = t[0], t[1], t[2]
        h,  m,   s   = t[3], t[4], t[5]

        time_str = "{:02d}:{:02d}:{:02d}".format(h, m, s)
        date_str = "{}.{}.{:04d}".format(day, mon, yr)

        # Day change: trigger weather refresh and silent NTP re-sync for RTC drift
        if day != last_day:
            last_day = day
            last_weather_ts = now - WEATHER_INTERVAL
            try:
                ntptime.settime()
            except Exception:
                pass

        # Periodic weather refresh
        start_day = 1 if h >= FORECAST_NEXT_DAY_HOUR else 0
        if now - last_weather_ts >= WEATHER_INTERVAL or start_day != last_start_day:
            raw = fetch_weather()
            ct, ws, days = parse_weather(raw, start_day)
            if days:            # keep old data on failure
                cur_temp    = ct
                wind_speed  = ws
                weather     = days
            last_weather_ts  = now
            last_start_day   = start_day

        # Advance screensaver and redraw every 300 ms
        if time.ticks_diff(time.ticks_ms(), last_move) >= 300:
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

        time.sleep_ms(100)
