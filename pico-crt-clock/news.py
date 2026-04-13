import urequests
import gc
import os
from config import *
from common import *

# ── Layout ────────────────────────────────────────────────────────────────────
# Title:  2 lines × 2× font (16 px/char wide, 16 px tall) → 16 chars/line
# Sep:    1 px white line at y=33
# Body:   1× font (8 px/char wide, 8 px tall) → 32 chars/line, 19 lines visible
TITLE_Y1    = 0
TITLE_Y2    = 16
SEP_Y       = 33
BODY_START  = 40
LINE_H      = 8
BODY_LINES  = (192 - BODY_START) // LINE_H   # 19
CHARS_TITLE = 256 // 16   # 16
CHARS_BODY  = 256 // 8    # 32

HOLD_MS         = NEWS_HOLD       * 1000
HOLD_AFTER_MS   = NEWS_HOLD_AFTER * 1000
SCROLL_DELAY_MS = NEWS_SCROLL_SPEED

NEWS_DIR = 'newscache'
_CHUNK   = 64   # bytes per read when scanning JSON

wlan = None

# ── Text ──────────────────────────────────────────────────────────────────────
# Map non-ASCII characters the font can't render to ASCII equivalents.
_CHARMAP = {
    '\u00a9': '(c)', '\u00ae': '(R)',           # © ®
    '\u2013': '-',   '\u2014': '-',              # en/em dash
    '\u2018': "'",   '\u2019': "'",              # curly single quotes
    '\u201c': '"',   '\u201d': '"',              # curly double quotes
    '\u2022': '*',   '\u00b7': '*',              # bullet
    '\u00e0': 'a',   '\u00e1': 'a',  '\u00e2': 'a',  '\u00e4': 'a',  '\u00e5': 'a',
    '\u00e6': 'ae',  '\u00e7': 'c',
    '\u00e8': 'e',   '\u00e9': 'e',  '\u00ea': 'e',  '\u00eb': 'e',
    '\u00ec': 'i',   '\u00ed': 'i',  '\u00ee': 'i',  '\u00ef': 'i',
    '\u00f1': 'n',
    '\u00f2': 'o',   '\u00f3': 'o',  '\u00f4': 'o',  '\u00f6': 'o',  '\u00f8': 'o',
    '\u00f9': 'u',   '\u00fa': 'u',  '\u00fb': 'u',  '\u00fc': 'u',
    '\u00c0': 'A',   '\u00c1': 'A',  '\u00c2': 'A',  '\u00c4': 'A',  '\u00c5': 'A',
    '\u00c6': 'AE',  '\u00c7': 'C',
    '\u00c8': 'E',   '\u00c9': 'E',  '\u00ca': 'E',  '\u00cb': 'E',
    '\u00d6': 'O',   '\u00d8': 'O',
    '\u00dc': 'U',   '\u00df': 'ss',
    '\u2026': '...',                             # ellipsis
}

def _sanitize(text):
    """Replace non-ASCII characters with ASCII equivalents or drop them."""
    out = []
    for ch in text:
        if ord(ch) < 128:
            out.append(ch)
        elif ch in _CHARMAP:
            out.append(_CHARMAP[ch])
    return ''.join(out)

def _word_wrap(text, width):
    """Wrap text at word boundaries; hard-break words longer than width."""
    words = text.split()
    lines = []
    line  = ''
    for word in words:
        if len(word) > width:
            if line:
                lines.append(line)
                line = ''
            while len(word) > width:
                lines.append(word[:width])
                word = word[width:]
            line = word
        elif line and len(line) + 1 + len(word) > width:
            lines.append(line)
            line = word
        else:
            line = (line + ' ' + word).strip()
    if line:
        lines.append(line)
    return lines

def _json_str(f, key):
    """Extract first JSON string "key":"value" from open file f.
    Reads in _CHUNK pieces; returns decoded string or '' if not found."""
    needle = '"' + key + '":"'
    carry  = ''
    out    = []
    found  = False
    while True:
        chunk = f.read(_CHUNK)
        data  = carry + chunk
        carry = ''
        if not found:
            idx = data.find(needle)
            if idx < 0:
                carry = data[-(len(needle) - 1):]
                if not chunk:
                    break
                continue
            data  = data[idx + len(needle):]
            found = True
        i = 0
        while i < len(data):
            c = data[i]
            if c == '\\':
                if i + 1 < len(data):
                    nc = data[i + 1]
                    out.append('"'  if nc == '"'  else
                               '\\' if nc == '\\' else
                               ' '  if nc in 'nrt' else nc)
                    i += 2
                else:
                    carry = '\\'
                    i += 1
            elif c == '"':
                return ''.join(out)
            else:
                out.append(c)
                i += 1
        if not chunk:
            break
    return ''.join(out)

def _json_body_wrap(src, key, dst, width):
    """Stream JSON string 'key' from file src, word-wrap at width, write lines to dst.
    Reads src in _CHUNK pieces; never holds more than one word+line in RAM."""
    needle = '"' + key + '":"'
    carry  = ''
    found  = False
    word   = ''
    line   = ''
    with open(src) as f:
        while True:
            chunk = f.read(_CHUNK)
            data  = carry + chunk
            carry = ''
            if not found:
                idx = data.find(needle)
                if idx < 0:
                    carry = data[-(len(needle) - 1):]
                    if not chunk:
                        break
                    continue
                data  = data[idx + len(needle):]
                found = True
            i = 0
            done = False
            while i < len(data):
                c = data[i]
                if c == '\\':
                    if i + 1 < len(data):
                        nc = data[i + 1]
                        ch = ('"'  if nc == '"'  else
                              '\\' if nc == '\\' else
                              ' '  if nc in 'nrt' else nc)
                        i += 2
                    else:
                        carry = '\\'
                        i += 1
                        continue
                else:
                    ch = c
                    i += 1
                if ch == '"':
                    done = True
                    break
                if ord(ch) >= 128:
                    word += _CHARMAP.get(ch, '')
                    continue
                if ch in ' \t\n\r':
                    if word:
                        while len(word) > width:
                            if line:
                                dst.write(line + '\n')
                                line = ''
                            dst.write(word[:width] + '\n')
                            word = word[width:]
                        if not line:
                            line = word
                        elif len(line) + 1 + len(word) <= width:
                            line += ' ' + word
                        else:
                            dst.write(line + '\n')
                            line = word
                        word = ''
                else:
                    word += ch
            if done or not chunk:
                break
    # flush remaining word and line
    if word:
        while len(word) > width:
            if line:
                dst.write(line + '\n')
                line = ''
            dst.write(word[:width] + '\n')
            word = word[width:]
        if not line:
            line = word
        elif len(line) + 1 + len(word) <= width:
            line += ' ' + word
        else:
            dst.write(line + '\n')
            line = word
    if line:
        dst.write(line + '\n')

# ── Fetch & store ─────────────────────────────────────────────────────────────
def _fetch_and_store():
    """Fetch articles one at a time, streaming each response to flash then scanning
    it with _CHUNK-byte reads. No large contiguous heap allocation needed.
    Returns number of articles stored, 0 on failure."""
    reconnect_wifi(wlan)
    draw_banner("Fetching news, blanking...")
    time.sleep_ms(2000)
    gfx.cls(BLACK)
    try:
        sections = [s.strip() for s in NEWS_SECTIONS.split(',') if s.strip()]

        try:
            os.mkdir(NEWS_DIR)
        except OSError:
            pass
        for fn in os.listdir(NEWS_DIR):
            if fn.startswith('news_') and fn.endswith('.txt'):
                os.remove(NEWS_DIR + '/' + fn)

        count = 0
        for page in range(1, NEWS_COUNT + 1):
            for section in sections:
                gc.collect()
                r = urequests.get(
                    "https://content.guardianapis.com/search"
                    "?section={}&show-fields=headline,bodyText"
                    "&page-size=1&page={}&api-key={}".format(
                        section, page, NEWS_API_KEY),
                    timeout=30)
                # Stream response to flash in 512-byte chunks (no large allocation)
                with open('_ntmp', 'wb') as f:
                    while True:
                        chunk = r.raw.read(512)
                        if not chunk:
                            break
                        f.write(chunk)
                r.close()
                gc.collect()

                # Extract headline as a short string (safe in RAM)
                with open('_ntmp') as f:
                    headline = _sanitize(_json_str(f, 'headline').strip())
                gc.collect()

                if not headline:
                    os.remove('_ntmp')
                    continue

                # Write article file: title lines, separator, then stream body
                tlines  = _word_wrap(headline, CHARS_TITLE)[:2]
                outpath = '{}/news_{:02d}.txt'.format(NEWS_DIR, count)
                with open(outpath, 'w') as out:
                    out.write((tlines[0] if tlines else '') + '\n')
                    out.write((tlines[1] if len(tlines) > 1 else '') + '\n')
                    out.write('---\n')
                    _json_body_wrap('_ntmp', 'bodyText', out, CHARS_BODY)
                os.remove('_ntmp')
                count += 1
                del headline, tlines
                gc.collect()

        return count
    except Exception as e:
        print("news fetch error:", e)
        return 0

def _list_files():
    try:
        fnames = sorted(fn for fn in os.listdir(NEWS_DIR)
                        if fn.startswith('news_') and fn.endswith('.txt'))
        return [NEWS_DIR + '/' + fn for fn in fnames]
    except OSError:
        return []

# ── Drawing ───────────────────────────────────────────────────────────────────
def _draw_header(t1, t2):
    """Redraw pinned title + separator each scroll step with minimal flicker.
    Draws each element in black one pixel above (erasing the scrolled copy),
    then redraws at the correct position."""
    x1 = (256 - len(t1) * 16) // 2
    gfx.print_string_2x(x1, TITLE_Y1 - 1, t1, BLACK, BLACK)
    gfx.print_string_2x(x1, TITLE_Y1,     t1, BLACK, WHITE)
    if t2:
        x2 = (256 - len(t2) * 16) // 2
        gfx.print_string_2x(x2, TITLE_Y2 - 1, t2, BLACK, BLACK)
        gfx.print_string_2x(x2, TITLE_Y2,     t2, BLACK, WHITE)
    gfx.line(0, SEP_Y - 1, 255, SEP_Y - 1, BLACK)
    gfx.line(0, SEP_Y,     255, SEP_Y,     WHITE)

def _poll_pin(pin, ms):
    """Sleep up to ms milliseconds, returning True immediately if pin released."""
    deadline = time.ticks_add(time.ticks_ms(), ms)
    while time.ticks_diff(deadline, time.ticks_ms()) > 0:
        if pin is not None and pin.value():
            return True
        time.sleep_ms(50)
    return False

# ── Article display ───────────────────────────────────────────────────────────
def _show_article(filename, pin):
    """Display one article with smooth scroll if content exceeds screen height.
    Returns False if pin was released (user switched mode), True otherwise."""
    with open(filename) as f:
        t1 = f.readline().rstrip()
        t2 = f.readline().rstrip()
        f.readline()   # skip '---'

        # Initial screen: cls clears everything, then draw title + body directly
        gfx.cls(BLACK)
        gfx.print_string_2x((256 - len(t1) * 16) // 2, TITLE_Y1, t1, BLACK, WHITE)
        if t2:
            gfx.print_string_2x((256 - len(t2) * 16) // 2, TITLE_Y2, t2, BLACK, WHITE)
        gfx.line(0, SEP_Y, 255, SEP_Y, WHITE)
        shown = 0
        for _ in range(BODY_LINES):
            line = f.readline()
            if not line:
                break
            gfx.print_string(0, BODY_START + shown * LINE_H, line.rstrip(), BLACK, WHITE)
            shown += 1

        # Peek: is there more content beyond the initial screen?
        nxt     = f.readline()
        nxtline = nxt.rstrip() if nxt else None

        gfx.wait_vblank()   # present the initial frame before any hold begins
        if _poll_pin(pin, HOLD_MS):
            return False
        if nxtline is None:
            # fits on one screen — initial hold was enough, move on
            return True

        # Smooth scroll: 1 px/frame, new body line every LINE_H pixels
        sub_px = 0
        while nxtline is not None:
            if pin is not None and pin.value():
                return False
            gfx.wait_vblank()
            gfx.scroll_up(BLACK, 1)
            _draw_header(t1, t2)
            sub_px += 1
            if sub_px == LINE_H:
                sub_px = 0
                gfx.print_string(0, 192 - LINE_H, nxtline, BLACK, WHITE)
                nxt     = f.readline()
                nxtline = nxt.rstrip() if nxt else None
            time.sleep_ms(SCROLL_DELAY_MS)

    if _poll_pin(pin, HOLD_AFTER_MS):
        return False
    return True

# ── Entry point ───────────────────────────────────────────────────────────────
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
        return

    sync_ntp()

    # Seed last_fetch_ts from the mtime of cached files so a re-entry within
    # NEWS_INTERVAL doesn't trigger an unnecessary fetch.  Falls back to 0
    # (fetch immediately) if no files exist or filesystem lacks timestamp support.
    files = _list_files()
    try:
        last_fetch_ts = os.stat(files[0])[8] if files else 0
    except OSError:
        last_fetch_ts = 0

    while pin is None or not pin.value():
        now   = time.time()
        files = _list_files()

        if not files or now - last_fetch_ts >= NEWS_INTERVAL:
            n = _fetch_and_store()
            if n > 0:
                last_fetch_ts = time.time()
            files = _list_files()

        if not files:
            gfx.cls(BLACK)
            gfx.print_string(16, 92, "News unavailable", BLACK, WHITE)
            if _poll_pin(pin, 60000):
                return
            continue

        for filename in files:
            if pin is not None and pin.value():
                return
            if not _show_article(filename, pin):
                return
