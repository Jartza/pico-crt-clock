from machine import Pin, soft_reset

# Each mode has a dedicated GPIO with internal pull-up.
# Connect the matching switch position to GND to activate that mode.
# If no pin is pulled low, clock/weather runs as the default.
#
# Pin assignments — adjust to match your wiring:
#   GPIO 10 → clock/weather (also the default with no switch)
#   GPIO 11 → torus demo
_PINS = [
    Pin(10, Pin.IN, Pin.PULL_UP),   # mode 0: clock/weather
    Pin(11, Pin.IN, Pin.PULL_UP),   # mode 1: torus
    Pin(12, Pin.IN, Pin.PULL_UP),   # mode 2: news
]

mode = None
for i, pin in enumerate(_PINS):
    if not pin.value():
        mode = i
        break

if mode == 1:
    import torus; torus.run(_PINS[1])
elif mode == 2:
    import news; news.run(_PINS[2])
else:
    # mode 0 or no switch connected — default clock/weather
    import clock; clock.run(_PINS[0] if mode == 0 else None)

soft_reset()
