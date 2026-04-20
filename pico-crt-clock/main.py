from machine import Pin, soft_reset
import time
try:
    from config_local import APPS
except ImportError:
    from config import APPS

# Build one pull-up input pin per app entry; the first pin that reads low
# selects that app.  If nothing is pulled low, APPS[0] runs as the default.
_pins = [(entry, Pin(entry[1], Pin.IN, Pin.PULL_UP)) for entry in APPS]

time.sleep(0.1)  # debounce delay for mode switches

selected = None
for entry, pin in _pins:
    if not pin.value():
        selected = (entry, pin)
        break
if selected is None:
    selected = (_pins[0][0], None)   # no switch pressed -> default, no pin to watch

entry, pin = selected
module_name = entry[0]
extras      = entry[2] if len(entry) > 2 else {}

mod = __import__(module_name)
mod.run(pin, **extras)
soft_reset()
