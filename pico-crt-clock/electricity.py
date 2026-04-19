import json
import gc
import os
try:
    from config_local import *
except ImportError:
    from config import *
from common import *


ELEC_DIR    = 'eleccache'
PRICE_CACHE = ELEC_DIR + '/prices.json'

# Layout: treat the screen as a 224 x 176 safe area centred in 256 x 192.
# Everything sits inside x=16..240 and y=8..184 so the screensaver can drift
# +/-16 px horizontally and +/-8 px vertically without clipping anything.
SAFE_X    = 16
TIME_Y    = 8            # 2x time, centred
DATE_Y    = 24           # date row (1x)
CHART_Y   = 40           # chart top
CHART_H   = 116          # chart body height (pixels)
BAR_W     = 9            # px per bar; 24 * 9 = 216 - fits inside 224 safe width
CHART_X0  = SAFE_X + (224 - 24 * BAR_W) // 2   # centre chart inside safe area
FOOTER_Y  = 160          # first footer row
SS_OX_MAX = 16
SS_OY_MAX = 8

# Greyscale shades for bar tiers: cheap / mid / expensive.
COL_CHEAP     = 5
COL_MID       = 10
COL_EXPENSIVE = 15    # WHITE
COL_GRID      = 6
COL_NOW       = 15

wlan = None


def _iso_z(epoch):
    """Format a UTC epoch time as 'YYYY-MM-DDTHH:MM:SS.000Z' for Elering API."""
    t = time.gmtime(epoch)
    return "{:04d}-{:02d}-{:02d}T{:02d}:{:02d}:{:02d}.000Z".format(
        t[0], t[1], t[2], t[3], t[4], t[5])


def _apply_markup(spot_ckwh):
    """Return displayed c/kWh given the raw spot price, applying VAT + tax +
    transfer per the Finnish convention (VAT on everything) when ELEC_SHOW_TOTAL
    is True."""
    if not ELEC_SHOW_TOTAL:
        return spot_ckwh
    return (spot_ckwh + ELEC_TAX_CKWH + ELEC_TRANSFER_CKWH) * (1 + ELEC_VAT_PCT / 100)


def _load_prices():
    """Return dict mapping local-hour-of-day-str -> c/kWh for today, or None
    on failure.  Keys are 0-23 as ints (local hour index)."""
    try:
        with open(PRICE_CACHE) as f:
            payload = json.load(f)
    except Exception:
        return None
    rows = payload.get('data', {}).get(ELEC_AREA, [])
    if not rows:
        return None
    now     = time.time()
    off_sec = _utc_offset(now)
    lt      = time.localtime(now + off_sec)
    today_key = (lt[0], lt[1], lt[2])
    out = {}
    for row in rows:
        ts = row.get('timestamp')
        if ts is None:
            continue
        # API returns seconds since epoch (UTC); shift to local to find hour-of-day.
        local_ts = ts + off_sec
        rt       = time.gmtime(local_ts)
        if (rt[0], rt[1], rt[2]) != today_key:
            continue
        spot_ckwh = float(row.get('price', 0)) / 10.0   # EUR/MWh -> c/kWh
        out[rt[3]] = _apply_markup(spot_ckwh)
    return out if out else None


def _fetch_prices():
    reconnect_wifi(wlan)
    gc.collect()
    if DEINIT_GFX_DURING_FETCH:
        gfx.deinit()
    try:
        try:
            os.mkdir(ELEC_DIR)
        except OSError:
            pass
        # Fetch a 48h window from today local-midnight to 48h later; gives us
        # today and tomorrow (when day-ahead prices have been published).
        now     = time.time()
        off_sec = _utc_offset(now)
        lt      = time.localtime(now + off_sec)
        local_midnight_utc = now + off_sec - (lt[3] * 3600 + lt[4] * 60 + lt[5])
        local_midnight_utc -= off_sec   # convert back to UTC epoch
        start_iso = _iso_z(local_midnight_utc)
        end_iso   = _iso_z(local_midnight_utc + 2 * 86400)
        url = "https://dashboard.elering.ee/api/nps/price?start={}&end={}".format(
            start_iso, end_iso)
        stream_get(url, PRICE_CACHE)
        gc.collect()
        if DEINIT_GFX_DURING_FETCH:
            gfx.init()
        return _load_prices()
    except Exception:
        if DEINIT_GFX_DURING_FETCH:
            gfx.init()
        return None


def _fetch_escape_wait(pin):
    draw_banner("Elec fetch (no signal)" if DEINIT_GFX_DURING_FETCH
                else "Elec fetch (glitches)")
    deadline = time.ticks_add(time.ticks_ms(), 4000)
    counter  = 0
    while time.ticks_diff(deadline, time.ticks_ms()) > 0:
        active, counter = check_pin_stable(pin, 0, counter)
        if not active:
            return True
        time.sleep_ms(10)
    return False


def _tier_colour(price):
    if price < ELEC_CHEAP_CKWH:
        return COL_CHEAP
    if price > ELEC_EXPENSIVE_CKWH:
        return COL_EXPENSIVE
    return COL_MID


def _draw_chart(ox, oy, prices, cur_hour):
    """Draw a 24-bar chart of today's hourly prices."""
    if not prices:
        msg = "no price data"
        x   = SAFE_X + (224 - len(msg) * 8) // 2 + ox
        gfx.print_string(x, CHART_Y + CHART_H // 2 - 4 + oy,
                         msg, BLACK, COL_GRID)
        return 0.0, 0.0, None

    vals  = list(prices.values())
    max_p = max(vals)
    min_p = min(vals)

    # Scale: the top of the chart = max of (today's peak, expensive threshold)
    # with 10% headroom.  This keeps both threshold rule lines visible inside
    # the chart on quiet days, and lets bars grow tall on price-spike days
    # without squishing the thresholds against the top edge.
    scale_max = max(max_p, ELEC_EXPENSIVE_CKWH) * 1.1

    chart_right = CHART_X0 + 24 * BAR_W
    chart_bot   = CHART_Y + CHART_H

    def _y_for(price):
        return chart_bot - int((price / scale_max) * CHART_H) + oy

    if ELEC_DRAW_THRESHOLDS:
        gfx.hline(_y_for(ELEC_CHEAP_CKWH),
                  CHART_X0 + ox, chart_right - 1 + ox, COL_GRID)
        gfx.hline(_y_for(ELEC_EXPENSIVE_CKWH),
                  CHART_X0 + ox, chart_right - 1 + ox, COL_GRID)

    for h in range(24):
        price = prices.get(h)
        if price is None:
            continue
        top_y = _y_for(price)
        x0    = CHART_X0 + h * BAR_W + ox
        x1    = x0 + BAR_W - 2
        col   = _tier_colour(price)
        for yy in range(top_y, chart_bot + oy):
            gfx.hline(yy, x0, x1, col)

    # Current-hour marker: small vertical line right above the bar top so
    # it's obvious which hour is "now" regardless of the bar's tier colour.
    if 0 <= cur_hour < 24 and cur_hour in prices:
        top_y = _y_for(prices[cur_hour])
        mx    = CHART_X0 + cur_hour * BAR_W + (BAR_W - 2) // 2 + ox
        gfx.line(mx, top_y - 6, mx, top_y - 2, COL_NOW)

    return min_p, max_p, prices.get(cur_hour)


def _cheapest_upcoming(prices, cur_hour):
    remaining = [(h, p) for h, p in prices.items() if h >= cur_hour]
    if not remaining:
        return None, None
    return min(remaining, key=lambda x: x[1])


def _draw_all(ox, oy, t_str, d_str, prices, cur_hour):
    gfx.cls(BLACK)
    gfx.print_string_2x((256 - len(t_str) * 16) // 2 + ox, TIME_Y + oy,
                        t_str, BLACK, WHITE)
    gfx.print_string((256 - len(d_str) * 8) // 2 + ox, DATE_Y + oy,
                     d_str, BLACK, WHITE)

    min_p, max_p, cur_p = _draw_chart(ox, oy, prices, cur_hour)

    if prices:
        # Line 1: now / min / max.  28 chars at worst (two-digit values) fits
        # the 224 px safe width exactly.
        bits = []
        if cur_p is not None:
            bits.append("now {:.1f}".format(cur_p))
        bits.append("min {:.1f}".format(min_p))
        bits.append("max {:.1f}".format(max_p))
        gfx.print_string(SAFE_X + ox, FOOTER_Y + oy,
                         "  ".join(bits), BLACK, WHITE)

        # Line 2: area + markup tag + cheapest upcoming slot if known.
        tag = "all inc" if ELEC_SHOW_TOTAL else "raw spot"
        line2 = "{}  {}  c/kWh".format(ELEC_AREA, tag)
        ch, cp = _cheapest_upcoming(prices, cur_hour)
        if ch is not None and ch != cur_hour:
            line2 += "  cheap@{:02d}:{:.1f}".format(ch, cp)
        gfx.print_string(SAFE_X + ox, FOOTER_Y + 10 + oy,
                         line2, BLACK, COL_MID)


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

    # Day-ahead prices publish once per day and never change during the day,
    # so we only refetch when the cache is missing the current local hour -
    # i.e. the cache is from a previous day (or empty on first boot).
    cur_hr_now = time.localtime(time.time() + _utc_offset(time.time()))[3]
    prices     = _load_prices()
    if prices is None or cur_hr_now not in prices:
        if _fetch_escape_wait(pin):
            return
        prices = _fetch_prices()

    ox, oy   = 0, 0
    vx, vy   = 1, 1
    last_s   = -1
    last_hr  = -1
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
            _draw_all(ox, oy, t_str, d_str, prices, hr)

        ss_speed = (read_speed_adc() >> 3) if USE_ADC_SPEED else SCREENSAVER_SPEED
        if ss_speed < 999 and time.ticks_diff(time.ticks_ms(), last_mv) >= (ss_speed * 50):
            last_mv = time.ticks_ms()
            ox += vx;  oy += vy
            if ox >=  SS_OX_MAX: ox =  SS_OX_MAX;  vx = -1
            elif ox <= -SS_OX_MAX: ox = -SS_OX_MAX; vx = 1
            if oy >=  SS_OY_MAX: oy =  SS_OY_MAX;  vy = -1
            elif oy <= -SS_OY_MAX: oy = -SS_OY_MAX; vy = 1
            last_s = -1

        # Only re-check on hour changes, so we don't hammer the API on any
        # transient parse failure.  When the hour rolls over (usually across
        # midnight into a new day), re-read the cache first - we may have
        # already fetched tomorrow's prices with the prior 48 h window - and
        # only hit the network if the new hour really isn't in our data.
        if hr != last_hr:
            last_hr = hr
            if prices is None or hr not in prices:
                fresh = _load_prices()
                if fresh and hr in fresh:
                    prices = fresh
                else:
                    if _fetch_escape_wait(pin):
                        return
                    new_prices = _fetch_prices()
                    if new_prices:
                        prices = new_prices
                last_s = -1

        time.sleep_ms(10)
