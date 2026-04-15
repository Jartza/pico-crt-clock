import urequests
import gc
import os
try:
    from config_local import *
except ImportError:
    from config import *
from common import *

# Layout
# Clock:  y=0,  1x font -> time + date on one line
# Gap:    y=8-15 (empty)
# Title:  y=16 and y=24, 1x font -> 32 chars/line
# Sep:    1 px white line at y=33  (unchanged)
# Body:   1x font, 32 chars/line, 19 lines visible  (unchanged)
CLOCK_Y     = 0
TITLE_Y1    = 16
TITLE_Y2    = 24
SEP_Y       = 33
BODY_START  = 40
LINE_H      = 8
BODY_LINES  = (192 - BODY_START) // LINE_H   # 19
CHARS_TITLE = 256 // 8    # 32  (1x font, same as body)
CHARS_BODY  = 256 // 8    # 32

HOLD_MS         = NEWS_HOLD       * 1000
HOLD_SUM_MS     = NEWS_HOLD_SUM   * 1000
HOLD_AFTER_MS   = NEWS_HOLD_AFTER * 1000
SCROLL_DELAY_MS = NEWS_SCROLL_SPEED

NEWS_DIR = 'newscache'
_CHUNK   = 64   # bytes per read when scanning JSON

wlan = None

# Text
# Map non-ASCII characters the font can't render to ASCII equivalents.
_CHARMAP = {
    '\u00a9': '(c)', '\u00ae': '(R)',            # copyright, registered trademark
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

# HTML entity map for the body field
_HTML_ENT = {
    'amp': '&', 'lt': '<', 'gt': '>', 'quot': '"', 'apos': "'", 'nbsp': ' ',
}

def _entity_char(e):
    """Decode an HTML entity name/number to a displayable ASCII string."""
    if e.startswith('#x') or e.startswith('#X'):
        try:    ch = chr(int(e[2:], 16))
        except: return ''
    elif e.startswith('#'):
        try:    ch = chr(int(e[1:]))
        except: return ''
    else:
        ch = _HTML_ENT.get(e, '')
    if not ch:             return ''
    if ord(ch) < 128:      return ch
    return _CHARMAP.get(ch, '')

def _json_body_wrap(src, key, dst, width, max_lines=0):
    """Stream JSON string 'key' from file src (HTML content), strip tags,
    use </p> as paragraph separator, decode entities, word-wrap, write to dst.
    Reads src in _CHUNK pieces; never holds more than one word+line in RAM.
    max_lines: stop after this many lines and append a truncation notice (0=unlimited)."""
    needle = '"' + key + '":"'
    carry  = ''
    found  = False
    word   = ''
    line   = ''
    in_tag = False
    tag    = ''
    in_ent = False
    entity = ''
    lines  = 0
    trunc  = False

    with open(src) as f:
        while not trunc:
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
            while i < len(data) and not done and not trunc:
                c = data[i]
                # JSON escape
                if c == '\\':
                    if i + 1 < len(data):
                        nc = data[i + 1]
                        ch = ('"'  if nc == '"'  else
                              '\\' if nc == '\\' else
                              '\n' if nc == 'n'  else
                              ' '  if nc in 'rt' else nc)
                        i += 2
                    else:
                        carry = '\\'
                        i += 1
                        continue
                else:
                    ch = c
                    i += 1
                    if ch == '"':       # unescaped " = end of JSON string value
                        done = True
                        break
                # HTML tag
                if in_tag:
                    if ch == '>':
                        low = tag.strip().lower()
                        if low.startswith('/p'):
                            # </p>: flush word -> line, write line + blank separator
                            if word:
                                while len(word) > width and not trunc:
                                    if line:
                                        dst.write(line + '\n'); lines += 1; line = ''
                                        if max_lines and lines >= max_lines: trunc = True; break
                                    dst.write(word[:width] + '\n'); lines += 1
                                    if max_lines and lines >= max_lines: trunc = True; break
                                    word = word[width:]
                                if not trunc:
                                    if not line:                              line = word
                                    elif len(line)+1+len(word) <= width:     line += ' '+word
                                    else: dst.write(line+'\n'); lines += 1; line = word
                                    if max_lines and lines >= max_lines:     trunc = True
                                word = ''
                            if not trunc and line:
                                dst.write(line + '\n'); lines += 1; line = ''
                                if max_lines and lines >= max_lines: trunc = True
                            if not trunc:
                                dst.write('\n'); lines += 1
                                if max_lines and lines >= max_lines: trunc = True
                        elif low.lstrip('/').startswith('br'):
                            # <br>: flush word + line, no blank separator
                            if word:
                                if not line:                             line = word
                                elif len(line)+1+len(word) <= width:    line += ' '+word
                                else:
                                    if not trunc:
                                        dst.write(line+'\n'); lines += 1
                                        if max_lines and lines >= max_lines: trunc = True
                                    line = word
                                word = ''
                            if not trunc and line:
                                dst.write(line+'\n'); lines += 1
                                if max_lines and lines >= max_lines: trunc = True
                                line = ''
                        in_tag = False; tag = ''
                    elif len(tag) < 16:
                        tag += ch
                    continue
                # HTML entity
                if in_ent:
                    if ch == ';':
                        rep = _entity_char(entity); entity = ''; in_ent = False
                        if rep: word += rep
                    elif len(entity) > 8:
                        entity = ''; in_ent = False
                    else:
                        entity += ch
                    continue
                # Normal character
                if ch == '<':   in_tag = True; tag = ''
                elif ch == '&': in_ent = True; entity = ''
                elif ord(ch) >= 128: word += _CHARMAP.get(ch, '')
                elif ch in ' \t\n\r':
                    if word:
                        while len(word) > width and not trunc:
                            if line:
                                dst.write(line + '\n'); lines += 1; line = ''
                                if max_lines and lines >= max_lines: trunc = True; break
                            dst.write(word[:width] + '\n'); lines += 1
                            if max_lines and lines >= max_lines: trunc = True; break
                            word = word[width:]
                        if not trunc:
                            if not line:                              line = word
                            elif len(line)+1+len(word) <= width:     line += ' '+word
                            else: dst.write(line+'\n'); lines += 1; line = word
                            if max_lines and lines >= max_lines:     trunc = True
                        word = ''
                else:
                    word += ch
            if done or not chunk:
                break

    if trunc:
        dst.write('\n\n[article truncated]\n')
    else:
        # flush remaining word and line
        if word:
            while len(word) > width:
                if line: dst.write(line + '\n'); line = ''
                dst.write(word[:width] + '\n')
                word = word[width:]
            if not line:                              line = word
            elif len(line)+1+len(word) <= width:     line += ' '+word
            else:                                     dst.write(line+'\n'); line = word
        if line:
            dst.write(line + '\n')

# Fetch and store
def _fetch_and_store():
    """Fetch articles one at a time, streaming each response to flash then scanning
    it with _CHUNK-byte reads. No large contiguous heap allocation needed.
    Returns number of articles stored, 0 on failure."""
    reconnect_wifi(wlan)
    draw_banner("Fetching news (black screen)")
    gc.collect()
    time.sleep_ms(4000)
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

        # Parse "section:count" pairs; fall back to NEWS_COUNT if no count given
        sec_counts = []
        for s in sections:
            if ':' in s:
                name, cnt = s.rsplit(':', 1)
                sec_counts.append((name.strip(), int(cnt.strip())))
            else:
                sec_counts.append((s, NEWS_COUNT))

        count = 0
        for section, sec_n in sec_counts:
            for page in range(1, sec_n + 1):
                gc.collect()
                r = None
                try:
                    r = urequests.get(
                        "https://content.guardianapis.com/search"
                        "?section={}&type=article&tag=tone/news&order-by=newest"
                        "&show-fields=headline,trailText,body"
                        "&page-size=1&page={}&api-key={}".format(
                            section, page, NEWS_API_KEY),
                        timeout=30)
                    # Stream response to flash in small chunks so Python heap use stays flat.
                    with open('_ntmp', 'wb') as f:
                        while True:
                            chunk = r.raw.read(512)
                            if not chunk:
                                break
                            f.write(chunk)
                finally:
                    # Close the socket/TLS stream even if reading or writing fails.
                    # Those resources live outside the MicroPython heap, so gc.mem_free()
                    # can look healthy while lwIP/CYW43 is out of memory.
                    if r is not None:
                        try:
                            r.close()
                        except Exception:
                            pass
                        r = None
                gc.collect()

                # Extract headline as a short string (safe in RAM)
                with open('_ntmp') as f:
                    headline = _sanitize(_json_str(f, 'headline').strip())
                gc.collect()

                if not headline:
                    os.remove('_ntmp')
                    continue

                tlines = _word_wrap(headline, CHARS_TITLE)[:2]

                # Write summary file: title + section + trailText (HTML, same stripper as body)
                sumpath = '{}/news_{:02d}_sum.txt'.format(NEWS_DIR, count)
                with open(sumpath, 'w') as out:
                    out.write((tlines[0] if tlines else '') + '\n')
                    out.write((tlines[1] if len(tlines) > 1 else '') + '\n')
                    out.write(section + '\n')
                    out.write('---\n')
                    _json_body_wrap('_ntmp', 'trailText', out, CHARS_BODY, 0)
                gc.collect()

                # Write full article file: title + section + HTML body streamed and stripped
                outpath = '{}/news_{:02d}.txt'.format(NEWS_DIR, count)
                with open(outpath, 'w') as out:
                    out.write((tlines[0] if tlines else '') + '\n')
                    out.write((tlines[1] if len(tlines) > 1 else '') + '\n')
                    out.write(section + '\n')
                    out.write('---\n')
                    _json_body_wrap('_ntmp', 'body', out, CHARS_BODY, NEWS_BODY_LINES)
                os.remove('_ntmp')
                count += 1
                del headline, tlines
                gc.collect()
        return count
    except Exception as e:
        # no traceback on Pico
        print("news fetch error: {}: {}".format(type(e).__name__, e))
        return 0

def _list_files():
    try:
        fnames = sorted(fn for fn in os.listdir(NEWS_DIR)
                        if fn.startswith('news_') and fn.endswith('.txt')
                        and '_sum' not in fn)
        return [NEWS_DIR + '/' + fn for fn in fnames]
    except OSError:
        return []

# Drawing
def _header_time(section=''):
    """Return a formatted local-time + date + section string for the header clock line."""
    ts = time.time()
    t  = time.localtime(ts + _utc_offset(ts))
    h, m = t[3], t[4]
    if CLOCK_12H:
        sfx  = 'am' if h < 12 else 'pm'
        h    = h % 12 or 12
        tstr = '{}:{:02d}{}'.format(h, m, sfx)
    else:
        tstr = '{:02d}:{:02d}'.format(h, m)
    d, mo, yr = t[2], t[1], t[0]
    sep = DATE_SEP
    if DATE_ORDER == 'MDY':   dstr = '{}{}{}{}{}'.format(mo, sep, d,  sep, yr)
    elif DATE_ORDER == 'YMD': dstr = '{}{}{}{}{}'.format(yr, sep, mo, sep, d)
    else:                     dstr = '{}{}{}{}{}'.format(d,  sep, mo, sep, yr)
    line = tstr + '  ' + dstr
    if section:
        line += '  ' + section[0].upper() + section[1:]
    return line

def _draw_header(t1, t2, section=''):
    """Redraw pinned clock + title + separator each scroll step.
    Clock at y=0: print_string background is enough (scroll artifact falls off-screen).
    Title lines: full-width line erase at y-1 before each print (title may be shorter
    than the full row, leaving columns outside the string width uncleared otherwise).
    Separator: explicit erase at SEP_Y-1 (gfx.line has no background)."""
    clk = _header_time(section)

    # Clear scrolling artifacts
    gfx.line(0, TITLE_Y1 - 1, 255, TITLE_Y1 - 1, BLACK)
    gfx.line(0, TITLE_Y2 - 1, 255, TITLE_Y2 - 1, BLACK)
    gfx.line(0, SEP_Y - 1, 255, SEP_Y - 1, BLACK)
    gfx.line(0, SEP_Y + 6, 255, SEP_Y + 6, BLACK)
    gfx.line(0, SEP_Y + 7, 255, SEP_Y + 7, BLACK)

    # Draw date/time, header lines and separator
    gfx.line(0, SEP_Y,     255, SEP_Y,     7)
    gfx.print_string((256 - len(clk) * 8) // 2, CLOCK_Y,  clk, BLACK, WHITE)
    gfx.print_string((256 - len(t1)  * 8) // 2, TITLE_Y1, t1,  BLACK, WHITE)
    if t2:
        gfx.print_string((256 - len(t2) * 8) // 2, TITLE_Y2, t2, BLACK, WHITE)

# Article display
def _show_article(filename, pin, mode_counter, mode_expected,
                  detail_pin=None, detail_counter=0, detail_expected=1, hold_ms=None):
    """Display one article with smooth scroll if content exceeds screen height.
    Returns (result, mode_counter, detail_counter, detail_expected)."""

    if hold_ms is None:
        hold_ms = HOLD_MS

    with open(filename) as f:
        t1      = f.readline().rstrip()
        t2      = f.readline().rstrip()
        section = f.readline().rstrip()   # section name (e.g. "world")
        f.readline()                      # skip '---'

        # Initial screen: cls clears everything, then draw header + body directly
        gfx.cls(BLACK)
        clk = _header_time(section)
        gfx.print_string((256 - len(clk) * 8) // 2, CLOCK_Y,  clk, BLACK, WHITE)
        gfx.print_string((256 - len(t1)  * 8) // 2, TITLE_Y1, t1,  BLACK, WHITE)
        if t2:
            gfx.print_string((256 - len(t2) * 8) // 2, TITLE_Y2, t2, BLACK, WHITE)
        gfx.line(0, SEP_Y, 255, SEP_Y, 7)
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
        deadline = time.ticks_add(time.ticks_ms(), hold_ms)
        while time.ticks_diff(deadline, time.ticks_ms()) > 0:
            active, mode_counter = check_pin_stable(pin, mode_expected, mode_counter)
            if not active:
                return 'MODE', mode_counter, detail_counter, detail_expected
            active, detail_counter = check_pin_stable(detail_pin, detail_expected, detail_counter)
            if not active:
                gfx.cls(BLACK)
                detail_expected = detail_pin.value()
                return 'SWAP', mode_counter, 0, detail_expected
            time.sleep_ms(10)
        if nxtline is None:
            # fits on one screen - initial hold was enough, move on
            return None, mode_counter, detail_counter, detail_expected

        # Smooth scroll: 1 px/frame, new body line every LINE_H pixels.
        # Print the incoming line at 192-sub_px each frame so it rises into
        # view clipped at the bottom edge rather than popping in all at once.
        sub_px = 0
        while nxtline is not None:
            active, mode_counter = check_pin_stable(pin, mode_expected, mode_counter)
            if not active:
                return 'MODE', mode_counter, detail_counter, detail_expected
            active, detail_counter = check_pin_stable(detail_pin, detail_expected, detail_counter)
            if not active:
                gfx.cls(BLACK)
                detail_expected = detail_pin.value()
                return 'SWAP', mode_counter, 0, detail_expected
            gfx.wait_vblank()
            gfx.scroll_up(BLACK, 1)
            _draw_header(t1, t2, section)
            sub_px += 1
            gfx.print_string(0, 192 - sub_px, nxtline, BLACK, WHITE)
            if sub_px == LINE_H:
                sub_px = 0
                nxt     = f.readline()
                nxtline = nxt.rstrip() if nxt else None
            time.sleep_ms(SCROLL_DELAY_MS)

    deadline = time.ticks_add(time.ticks_ms(), HOLD_AFTER_MS)
    while time.ticks_diff(deadline, time.ticks_ms()) > 0:
        active, mode_counter = check_pin_stable(pin, mode_expected, mode_counter)
        if not active:
            return 'MODE', mode_counter, detail_counter, detail_expected
        active, detail_counter = check_pin_stable(detail_pin, detail_expected, detail_counter)
        if not active:
            gfx.cls(BLACK)
            detail_expected = detail_pin.value()
            return 'SWAP', mode_counter, 0, detail_expected
        time.sleep_ms(10)
    return None, mode_counter, detail_counter, detail_expected

# Entry point
def run(pin=None):
    global wlan
    from machine import Pin as _Pin

    gfx.init()
    gfx.set_border(0)
    gfx.cls(BLACK)

    # GPIO 13: detail switch - low = show full article, high (default) = summary
    detail_pin = _Pin(13, _Pin.IN, _Pin.PULL_UP)

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

    mode_expected = 0
    mode_counter = 0
    detail_expected = detail_pin.value()
    detail_counter = 0

    while True:
        active, mode_counter = check_pin_stable(pin, mode_expected, mode_counter)
        if not active:
            return

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
            deadline = time.ticks_add(time.ticks_ms(), 60000)
            while time.ticks_diff(deadline, time.ticks_ms()) > 0:
                active, mode_counter = check_pin_stable(pin, mode_expected, mode_counter)
                if not active:
                    return
                active, detail_counter = check_pin_stable(detail_pin, detail_expected, detail_counter)
                if not active:
                    detail_expected = detail_pin.value()
                    break
                time.sleep_ms(10)
            continue

        idx = 0
        while idx < len(files):
            active, mode_counter = check_pin_stable(pin, mode_expected, mode_counter)
            if not active:
                return
            # Select file based on detail switch: high = summary (default), low = full article
            base = files[idx]
            if detail_expected:   # high = summary mode (hardware default, pull-up)
                spath = base[:-4] + '_sum.txt'
                try:
                    os.stat(spath)
                    show_file = spath
                except OSError:
                    show_file = base   # fall back to full if no summary cached
            else:
                show_file = base       # low = full article mode (switch to GND)
            hold = HOLD_SUM_MS if show_file != base else HOLD_MS
            result, mode_counter, detail_counter, detail_expected = _show_article(
                show_file, pin, mode_counter, mode_expected, detail_pin,
                detail_counter, detail_expected, hold)
            if result == 'MODE':
                return
            elif result == 'SWAP':
                pass   # re-show same article in new mode
            else:
                idx += 1
