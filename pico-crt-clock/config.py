WIFI_SSID = "wifiname"
WIFI_PASS = "password"

# The Guardian open platform API key - get a free key at https://open-platform.theguardian.com
NEWS_API_KEY = "YOUR_GUARDIAN_API_KEY_HERE"

# Guardian sections to fetch from, with optional per-section article count.
# Format: "section:count,section:count,..." - count falls back to NEWS_COUNT if omitted.
# Examples: technology, science, world, business, environment, politics, sport, culture
NEWS_SECTIONS = "world:6,technology:4,politics:6"

# Default articles per section (used when no count given in NEWS_SECTIONS)
NEWS_COUNT = 4

# How often to refresh news (seconds); free tier allows 5000 req/day
NEWS_INTERVAL = 2 * 60 * 60

# Seconds to hold the initial screen (also the only hold if article fits on one screen)
NEWS_HOLD = 15

# Seconds to hold summary (trailText) articles - these are short and never scroll
NEWS_HOLD_SUM = 8

# Seconds to hold after scrolling finishes (only applies when scrolling occurred)
NEWS_HOLD_AFTER = 3

# Max body lines stored per article (0 = unlimited).
# ~21 lines fill one screen; 105 is about 5 screens of content.
NEWS_BODY_LINES = 105

# Scroll speed: extra milliseconds of delay per pixel (larger = slower)
# 125 is about 1 row of text per second.
NEWS_SCROLL_SPEED = 125

# RSVP (rapid serial visual presentation) reading speed in words per minute.
# Used when the news detail switch is in the third position.  Comfortable range
# is 200-400; experienced speed readers can handle 500-600.
RSVP_WPM = 300

# Set True to draw full-width horizontal rails above and below the RSVP word
# row (Spritz-style reading window).  The small vertical pointer marks at the
# highlighted letter always remain regardless of this setting.
RSVP_RAILS = False

# Timezone: base UTC offset in whole hours (without DST).
# Examples: Finland/EET=2, Germany/CET=1, UK/GMT=0, EST=-5
UTC_OFFSET = 2

# Set to True to enable automatic DST adjustment (+1 h).
# Uses European rules: clocks forward last Sunday of March at 01:00 UTC,
# back last Sunday of October at 01:00 UTC.
# Set to False for fixed-offset timezones (e.g. UTC, IST, JST).
USE_DST = True

# Location for weather - Open-Meteo uses decimal degrees
LATITUDE  = 60.48   # Replace with your own coordinates
LONGITUDE = 24.11

# How often to refresh weather data (seconds)
WEATHER_INTERVAL = 30 * 60

# Hour (local, 0-23) after which the forecast shifts to show tomorrow first
FORECAST_NEXT_DAY_HOUR = 18

# Set to True for 12-hour clock with am/pm suffix; False for 24-hour clock.
CLOCK_12H = False

# Date format: order of components (D=day, M=month, Y=year) and separator.
# Examples: "DMY" + "." -> "28.3.2026"   "MDY" + "/" -> "3/28/2026"   "YMD" + "-" -> "2026-3-28"
DATE_ORDER = "DMY"
DATE_SEP   = "."

# Temperature unit: "C" (Celsius) or "F" (Fahrenheit)
TEMP_UNIT = "C"

# Wind speed unit: "ms" (m/s), "kmh" (km/h), "mph", "kn" (knots)
WIND_UNIT = "ms"

# Screen saver speed: 0 = fastest, 20 = move screen 1px/1px once per second
# 999 = disabled (never move the screen)
SCREENSAVER_SPEED = 2

# Set USE_ADC_SPEED = True to use a potentiometer on GPIO 26 to adjust the
# weather clock screensaver speed and newsreader scroll speed instead of the
# configured values above.
USE_ADC_SPEED = False

# Apps available on this device, in switch-position order.
# Each entry is a tuple: (module_name, gpio) or (module_name, gpio, extras_dict).
# Pull a GPIO to GND via your mode-select switch to activate that app.  If no
# switch is pressed, the FIRST entry runs as the default.
#
# To run fewer apps: comment out lines you don't want.  To remap GPIOs to
# match your wiring: edit the numbers.  First entry = default app.
#
# The news entry's "modes" dict maps GPIO numbers to the reading mode they
# activate when pulled to GND, with "default" as the mode used when no mapped
# pin is pulled low.  Valid modes are "full", "summary", "rsvp".  Wire any
# subset of pins - e.g. {"default": "full"} with no GPIO keys locks news to
# full-article mode and needs no detail switch.
#
# The electricity app also accepts a "modes" dict. Use one shared detail GPIO
# to switch between {"default": "today", 13: "tomorrow"} if you want the same
# secondary switch style as news.
APPS = [
    ("weather", 10),
    ("news",    12, {"modes": {"default": "summary", 13: "full", 14: "rsvp"}}),
    ("sky",     11),
    # ("electricity", 15),          # uncomment and wire a 4th switch position to enable
    # ("torus",       11),          # legacy 3D demo; swap for "sky" above if wanted
]

# --- sky ---
# Aurora / KP-index forecast refresh interval (seconds)
SKY_INTERVAL          = 30 * 60
# KP threshold at which aurora is likely visible for your latitude.
# Rough guide: KP 5+ for 60 deg N, KP 6+ for 55 deg N, KP 3+ for 70 deg N.
SKY_AURORA_KP_VISIBLE = 5

# --- electricity ---
# Nord Pool price area: fi, ee, lv, lt, se1..se4, no1..no5, dk1, dk2
ELEC_AREA             = "fi"
# True = show consumer total price; False = raw spot only.
ELEC_SHOW_TOTAL       = True
# These only apply when ELEC_SHOW_TOTAL is True. Set any to 0 to skip it.
# ELEC_VAT_PCT is applied to the raw spot component only. Electricity tax,
# transfer, and margin should already include VAT, as that is how they are
# normally announced to consumers.
# In April 2026, Finnish VAT is 25.5%, electricity tax is 2.92 c/kWh (incl VAT),
# Caruna transfer fee is 5.26 c/kWh (incl VAT)
ELEC_VAT_PCT          = 25.5
ELEC_TAX_CKWH         = 2.92
ELEC_TRANSFER_CKWH    = 5.26
ELEC_MARGIN_CKWH      = 0.59
# Threshold values in c/kWh - bars below CHEAP are light grey, above
# EXPENSIVE are white, in between are mid grey.
ELEC_CHEAP_CKWH       = 15.0
ELEC_EXPENSIVE_CKWH   = 25.0
# Draw horizontal rule lines at the threshold levels
ELEC_DRAW_THRESHOLDS  = True
# Local release time for the next day's Nord Pool prices. Once this time has
# passed, electricity.py will refetch if tomorrow is still missing.
ELEC_TOMORROW_RELEASE_HOUR   = 14
ELEC_TOMORROW_RELEASE_MINUTE = 30
