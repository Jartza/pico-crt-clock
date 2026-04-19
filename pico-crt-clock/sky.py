import json
import gc
import os
import math
try:
    from config_local import *
except ImportError:
    from config import *
from common import *


SKY_DIR      = 'skycache'
KP_CACHE     = SKY_DIR + '/kp.json'
SYN_MONTH    = 29.53058867   # mean synodic month, days

# Layout: treat the screen as a 224 x 176 safe area centred in 256 x 192.
# Everything sits inside x=16..240 and y=8..184 so the screensaver can drift
# +/-16 px horizontally and +/-8 px vertically without clipping content off
# the CRT (where the outer border pixels are usually lost anyway).
SAFE_X   = 16
TIME_Y   = 8            # 2x time, centred in the safe area
DATE_Y   = 24           # date row (1x), directly below time
MOON_CX  = 40           # moon disc centre x (left edge of safe area + radius)
MOON_CY  = 60           # moon disc centre y
MOON_R   = 24           # moon radius (48 px disc)
MOON_TX  = 80           # text column next to moon
SUN_Y    = 96           # sun row 1
AUR_Y    = 120          # aurora header row
AUR_X    = 16           # chart left edge (= SAFE_X)
AUR_W    = 224          # chart width in pixels (8 bars * 28 px, full safe width)
SS_OX_MAX = 16
SS_OY_MAX = 8
MOON_DARK = 3           # grey shade for the unlit side (earthshine feel)

PHASE_NAMES = (
    "New", "Wax cresc", "First qtr", "Wax gibb",
    "Full", "Wan gibb", "Last qtr", "Wan cresc",
)

wlan = None


def _julian_day(y, mo, d):
    """Julian day at 00:00 UTC for the given Gregorian date."""
    if mo <= 2:
        y -= 1
        mo += 12
    a = y // 100
    b = 2 - a + a // 4
    return int(365.25 * (y + 4716)) + int(30.6001 * (mo + 1)) + d + b - 1524.5


def _sun_rise_set(y, mo, d, lat_deg, lon_deg):
    """Standard NOAA/Meeus sunrise equation.  Returns (rise_min, set_min) as
    minutes past UTC midnight, ('up','up') for polar day, or (None, None) for
    polar night.  Accurate to about 1 min in temperate latitudes."""
    # The equation expects JD at noon of the target day (astronomical convention).
    # _julian_day gives midnight, so add 0.5.
    jd_noon = _julian_day(y, mo, d) + 0.5
    n       = jd_noon - 2451545.0 + 0.0008
    j_star  = n - lon_deg / 360.0
    mean_m  = math.radians((357.5291 + 0.98560028 * j_star) % 360)
    eq_ctr  = (1.9148 * math.sin(mean_m)
               + 0.0200 * math.sin(2 * mean_m)
               + 0.0003 * math.sin(3 * mean_m))
    lam     = math.radians((math.degrees(mean_m) + eq_ctr + 180 + 102.9372) % 360)
    j_tran  = (2451545.0 + j_star
               + 0.0053 * math.sin(mean_m)
               - 0.0069 * math.sin(2 * lam))
    sin_dec = math.sin(lam) * math.sin(math.radians(23.44))
    cos_dec = math.cos(math.asin(sin_dec))
    lat_r   = math.radians(lat_deg)
    den     = math.cos(lat_r) * cos_dec
    if den == 0:
        return None, None
    cos_h = (math.sin(math.radians(-0.833)) - math.sin(lat_r) * sin_dec) / den
    if cos_h < -1:
        return 'up', 'up'
    if cos_h > 1:
        return None, None
    h_deg  = math.degrees(math.acos(cos_h))
    j_rise = j_tran - h_deg / 360.0
    j_set  = j_tran + h_deg / 360.0
    def _mins(j):
        return int(((j - 0.5) % 1) * 24 * 60 + 0.5)
    return _mins(j_rise), _mins(j_set)


def _moon_age(y, mo, d):
    """Days since last new moon.  Epoch: 2000-01-06 18:14 UTC (JD 2451550.26),
    rounded to the Meeus-referenced value 2451550.1."""
    return (_julian_day(y, mo, d) - 2451550.1) % SYN_MONTH


def _moon_illumination(age):
    """Illuminated fraction, 0 at new, 1 at full."""
    return (1 - math.cos(2 * math.pi * age / SYN_MONTH)) / 2


def _phase_name(age):
    return PHASE_NAMES[int(age / SYN_MONTH * 8 + 0.5) % 8]


def _fmt_hm(utc_min):
    """Convert 'minutes past UTC midnight' to a HH:MM local-time string.
    Returns '--:--' for None and '--:-- up' for polar day markers."""
    if utc_min is None:
        return "--:--"
    if utc_min == 'up':
        return "always"
    # Add today's UTC offset (uses same DST helper as the rest of the project).
    now = time.time()
    local_min = (utc_min + _utc_offset(now) // 60) % (24 * 60)
    return "{:02d}:{:02d}".format(local_min // 60, local_min % 60)


def _daylight_str(rise, sett):
    if rise == 'up' or sett == 'up':
        return "24h"
    if rise is None or sett is None:
        return "0h"
    dur = (sett - rise) % (24 * 60)
    return "{:d}h{:02d}m".format(dur // 60, dur % 60)


def _load_kp():
    """Return list of (time_tag_str, kp_float) for future-facing predictions,
    limited to the next ~24 h (8 three-hour slots).  None on failure.
    Accepts any non-'observed' entry so NOAA's 'estimated' slots for today
    count alongside 'predicted' slots for later days."""
    try:
        with open(KP_CACHE) as f:
            data = json.load(f)
    except Exception:
        return None
    out = []
    for r in data:
        kp = r.get('kp')
        if kp is None:
            continue
        if r.get('observed') == 'observed':
            continue
        out.append((r['time_tag'], float(kp)))
        if len(out) >= 8:
            break
    return out if out else None


def _cache_age():
    try:
        return time.time() - os.stat(KP_CACHE)[8]
    except OSError:
        return None


def _fetch_kp():
    reconnect_wifi(wlan)
    gc.collect()
    if DEINIT_GFX_DURING_FETCH:
        gfx.deinit()
    try:
        try:
            os.mkdir(SKY_DIR)
        except OSError:
            pass
        stream_get(
            "https://services.swpc.noaa.gov/products/noaa-planetary-k-index-forecast.json",
            KP_CACHE)
        gc.collect()
        if DEINIT_GFX_DURING_FETCH:
            gfx.init()
        return _load_kp()
    except Exception:
        if DEINIT_GFX_DURING_FETCH:
            gfx.init()
        return None


def _fetch_escape_wait(pin):
    """Let the user bail out before a fetch starts (mirrors weather.py behaviour)."""
    draw_banner("Sky fetch (no signal)" if DEINIT_GFX_DURING_FETCH
                else "Sky fetch (glitches)")
    deadline = time.ticks_add(time.ticks_ms(), 4000)
    counter  = 0
    while time.ticks_diff(deadline, time.ticks_ms()) > 0:
        active, counter = check_pin_stable(pin, 0, counter)
        if not active:
            return True
        time.sleep_ms(10)
    return False


def _draw_moon(cx, cy, r, age):
    """Paint a filled greyscale moon showing the illuminated fraction.
    Dark side = MOON_DARK (dim grey, like earthshine); lit side = WHITE.
    A WHITE circle outline keeps the disc shape visible even when dark."""
    fraction    = age / SYN_MONTH           # 0..1
    phase_angle = 2 * math.pi * fraction    # 0 new, pi full, 2pi back to new
    k           = math.cos(phase_angle)     # +1 new, -1 full
    waxing      = fraction < 0.5
    r2          = r * r
    for py in range(-r, r + 1):
        row_half = int((r2 - py * py) ** 0.5)
        if row_half <= 0:
            continue
        bound = int(round(k * row_half))
        if bound > row_half:  bound = row_half
        if bound < -row_half: bound = -row_half
        if waxing:
            # Lit on right (px > bound), dark on left.
            if bound > -row_half:
                gfx.hline(cy + py, cx - row_half, cx + bound,       MOON_DARK)
            if bound < row_half:
                gfx.hline(cy + py, cx + bound + 1, cx + row_half,   WHITE)
        else:
            # Lit on left (px < -bound), dark on right.
            if bound < row_half:
                gfx.hline(cy + py, cx + bound + 1, cx + row_half,   MOON_DARK)
            if bound > -row_half:
                gfx.hline(cy + py, cx - row_half, cx + bound,       WHITE)
    gfx.circle(cx, cy, r, WHITE, False)


def _draw_kp_bars(x, y, w, h, kp_data):
    """Bar-chart KP forecast.  Each bar is one 3-hour slot; taller = more active."""
    if not kp_data:
        gfx.print_string(x, y + h // 2 - 4, "no data", BLACK, 6)
        return
    n      = min(len(kp_data), 8)
    bar_w  = w // n
    max_kp = 9.0
    thr_y  = y + h - int(SKY_AURORA_KP_VISIBLE / max_kp * h)
    for i in range(n):
        _, kp = kp_data[i]
        bh    = int(kp / max_kp * h)
        by    = y + h - bh
        col   = WHITE if kp >= SKY_AURORA_KP_VISIBLE else 8
        for yy in range(by, y + h):
            gfx.hline(yy, x + i * bar_w, x + (i + 1) * bar_w - 2, col)
    gfx.hline(thr_y, x, x + w, 6)   # threshold line


def _draw_all(ox, oy, t_str, d_str, rise_str, set_str, dl_str,
              age, illum_pct, ph_name, kp_data, peak_kp):
    gfx.cls(BLACK)
    gfx.print_string_2x((256 - len(t_str) * 16) // 2 + ox, TIME_Y + oy,
                        t_str, BLACK, WHITE)
    gfx.print_string((256 - len(d_str) * 8) // 2 + ox, DATE_Y + oy,
                     d_str, BLACK, WHITE)

    _draw_moon(MOON_CX + ox, MOON_CY + oy, MOON_R, age)

    gfx.print_string(MOON_TX + ox, MOON_CY - 14 + oy, ph_name, BLACK, WHITE)
    gfx.print_string(MOON_TX + ox, MOON_CY -  2 + oy,
                     "age {:.1f}d".format(age), BLACK, WHITE)
    gfx.print_string(MOON_TX + ox, MOON_CY + 10 + oy,
                     "lit {:d}%".format(illum_pct), BLACK, WHITE)

    # Sun row 1: "rise HH:MM  set HH:MM" (21 chars, 168 px)
    gfx.print_string(SAFE_X + ox, SUN_Y + oy,
                     "sunrise {}  sunset {}".format(rise_str, set_str), BLACK, WHITE)
    # Sun row 2: "daylight NhNNm" (up to 15 chars, 120 px)
    gfx.print_string(SAFE_X + ox, SUN_Y + 8 + oy,
                     "daylight {}".format(dl_str), BLACK, WHITE)

    # Aurora header + threshold in one short string
    gfx.print_string(SAFE_X + ox, AUR_Y + oy,
                     "Aurora (KP>={})".format(SKY_AURORA_KP_VISIBLE),
                     BLACK, WHITE)
    _draw_kp_bars(AUR_X + ox, AUR_Y + 10 + oy, AUR_W, 26, kp_data)
    if peak_kp is not None:
        verdict = "visible" if peak_kp >= SKY_AURORA_KP_VISIBLE else "unlikely"
        gfx.print_string(SAFE_X + ox, AUR_Y + 40 + oy,
                         "peak KP {:.1f} {}".format(peak_kp, verdict),
                         BLACK, WHITE)


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

    # Warm the KP cache if it's stale.
    age = _cache_age()
    if age is None or age > SKY_INTERVAL:
        if _fetch_escape_wait(pin):
            return
        kp_data       = _fetch_kp()
        last_fetch_ts = time.time()
    else:
        kp_data       = _load_kp()
        last_fetch_ts = time.time() - int(age)

    ox, oy   = 0, 0
    vx, vy   = 1, 1
    last_s   = -1
    last_mv  = time.ticks_ms()
    pincnt   = 0

    while True:
        active, pincnt = check_pin_stable(pin, 0, pincnt)
        if not active:
            return

        now = time.time()
        t   = time.localtime(now + _utc_offset(now))
        yr, mo, dy = t[0], t[1], t[2]
        hr, mi, se = t[3], t[4], t[5]

        if se != last_s:
            last_s = se
            if CLOCK_12H:
                h12 = hr % 12 or 12
                t_str = "{}:{:02d}:{:02d}{}".format(
                    h12, mi, se, "am" if hr < 12 else "pm")
            else:
                t_str = "{:02d}:{:02d}:{:02d}".format(hr, mi, se)
            dp = {'D': str(dy), 'M': str(mo), 'Y': str(yr)}
            d_str = DATE_SEP.join(dp[c] for c in DATE_ORDER)

            r_utc, s_utc = _sun_rise_set(yr, mo, dy, LATITUDE, LONGITUDE)
            rise_str = _fmt_hm(r_utc)
            set_str  = _fmt_hm(s_utc)
            dl_str   = _daylight_str(r_utc, s_utc)

            age   = _moon_age(yr, mo, dy)
            illum = int(_moon_illumination(age) * 100 + 0.5)
            ph    = _phase_name(age)
            peak  = max((k for _, k in kp_data), default=None) if kp_data else None

            _draw_all(ox, oy, t_str, d_str, rise_str, set_str, dl_str,
                      age, illum, ph, kp_data, peak)

        # Screensaver: gentle DVD bounce so static blocks (moon, sparkline)
        # don't burn into the CRT.
        ss_speed = (read_speed_adc() >> 3) if USE_ADC_SPEED else SCREENSAVER_SPEED
        if ss_speed < 999 and time.ticks_diff(time.ticks_ms(), last_mv) >= (ss_speed * 50):
            last_mv = time.ticks_ms()
            ox += vx;  oy += vy
            if ox >=  SS_OX_MAX: ox =  SS_OX_MAX;  vx = -1
            elif ox <= -SS_OX_MAX: ox = -SS_OX_MAX; vx = 1
            if oy >=  SS_OY_MAX: oy =  SS_OY_MAX;  vy = -1
            elif oy <= -SS_OY_MAX: oy = -SS_OY_MAX; vy = 1
            last_s = -1   # force redraw next tick

        # Periodic refetch
        if time.time() - last_fetch_ts >= SKY_INTERVAL:
            if _fetch_escape_wait(pin):
                return
            new_kp = _fetch_kp()
            if new_kp:
                kp_data = new_kp
            last_fetch_ts = time.time()
            last_s = -1   # force redraw after fetch

        time.sleep_ms(10)
