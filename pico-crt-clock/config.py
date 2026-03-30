WIFI_SSID = "wifiname"
WIFI_PASS = "password"

# Timezone: base UTC offset in whole hours (without DST).
# Examples: Finland/EET=2, Germany/CET=1, UK/GMT=0, EST=-5
UTC_OFFSET = 2

# Set to True to enable automatic DST adjustment (+1 h).
# Uses European rules: clocks forward last Sunday of March at 01:00 UTC,
# back last Sunday of October at 01:00 UTC.
# Set to False for fixed-offset timezones (e.g. UTC, IST, JST).
USE_DST = True

# Location for weather - Open-Meteo uses decimal degrees
LATITUDE  = 60.22   # Replace with your own coordinates
LONGITUDE = 24.03

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
