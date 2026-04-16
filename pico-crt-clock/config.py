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
