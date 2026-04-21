import urequests
import gc
import os
import machine
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

# RSVP (rapid serial visual presentation) layout
# Header occupies y=0..39 (unchanged, drawn with _draw_header).
# Word is rendered in 2x font at y=RSVP_WORD_Y, centered vertically in the body region.
# ORP (optimal recognition point) letter's left edge sits at RSVP_ORP_X so the eye
# locks onto a fixed column across words of varying length.
RSVP_WORD_Y  = 108
RSVP_ORP_X   = 120
RSVP_PIN_COL = 127   # pinpoint column: ORP left edge + 7
RSVP_MAX_LEN = 16    # word chars that fit at 2x font (16 px/char * 16 = 256)
COLOUR6      = 6     # mid-gray background for ORP highlight

# News detail switch modes.  The mapping between GPIO pins and modes is set
# per-device from the APPS config entry's "modes" dict (see config.py).
MODE_FULL    = 0
MODE_SUMMARY = 1
MODE_RSVP    = 2

_MODE_NAME_TO_CONST = {
    "full":    MODE_FULL,
    "summary": MODE_SUMMARY,
    "rsvp":    MODE_RSVP,
}

def _check_detail_swap(p13, c13, e13, p14, c14, e14):
    """Poll both detail pins. Return (swap, c13, e13, c14, e14) where swap is True
    if either pin has changed to a new stable value. Caller recomputes mode."""
    swap = False
    if p13 is not None:
        active, c13 = check_pin_stable(p13, e13, c13)
        if not active:
            swap = True
    if p14 is not None:
        active, c14 = check_pin_stable(p14, e14, c14)
        if not active:
            swap = True
    if swap:
        v13 = p13.value() if p13 is not None else 1
        v14 = p14.value() if p14 is not None else 1
        if p14 is not None and v14 == 0:
            e13, e14 = 1, 0
        elif p13 is not None and v13 == 0:
            e13, e14 = 0, 1
        else:
            e13, e14 = 1, 1
        c13 = 0
        c14 = 0
    return swap, c13, e13, c14, e14

NEWS_DIR = 'newscache'
_CHUNK   = 64   # bytes per read when scanning JSON
NEWS_META = NEWS_DIR + '/index.txt'
_TMP_JSON_PREFIX = '_tmp_news_'
_WATCHDOG_BASE = 0x40058000
_SCRATCH_MAGIC = _WATCHDOG_BASE + 0x0C
_SCRATCH_INDEX = _WATCHDOG_BASE + 0x10
_SCRATCH_NEWS_MAGIC = 0x4E455753   # "NEWS"

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

def _pub_sort_key(dt):
    """Return a sortable UTC timestamp key from an ISO8601 datetime string."""
    if len(dt) >= 19:
        return dt[0:4] + dt[5:7] + dt[8:10] + dt[11:13] + dt[14:16] + dt[17:19]
    return '00000000000000'

def _tmp_json_path(seq):
    return '{}/{}{:02d}.json'.format(NEWS_DIR, _TMP_JSON_PREFIX, seq)

def _write_atomic(path, text):
    tmp = path + '.tmp'
    with open(tmp, 'w') as f:
        f.write(text)
    try:
        os.remove(path)
    except OSError:
        pass
    os.rename(tmp, path)

def _basename(path):
    idx = path.rfind('/')
    return path[idx + 1:] if idx >= 0 else path

def _clear_news_cache():
    try:
        names = os.listdir(NEWS_DIR)
    except OSError:
        return
    for fn in names:
        if ((fn.startswith('news_') and fn.endswith('.txt'))
                or fn.startswith(_TMP_JSON_PREFIX)
                or fn in ('index.txt', 'index.txt.tmp')):
            try:
                os.remove(NEWS_DIR + '/' + fn)
            except OSError:
                pass

def _store_metadata(entries):
    lines = []
    for fname, pubkey, section in entries:
        lines.append('{}|{}|{}\n'.format(fname, pubkey, section))
    _write_atomic(NEWS_META, ''.join(lines))

def _save_current(idx):
    machine.mem32[_SCRATCH_MAGIC] = _SCRATCH_NEWS_MAGIC
    machine.mem32[_SCRATCH_INDEX] = idx

def _load_current(files):
    if not files:
        return 0
    if machine.mem32[_SCRATCH_MAGIC] != _SCRATCH_NEWS_MAGIC:
        return 0
    want = machine.mem32[_SCRATCH_INDEX]
    if want < 0 or want >= len(files):
        return 0
    return want

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
    gc.collect()
    try:
        sections = [s.strip() for s in NEWS_SECTIONS.split(',') if s.strip()]

        try:
            os.mkdir(NEWS_DIR)
        except OSError:
            pass
        _clear_news_cache()

        # Parse "section:count" pairs; fall back to NEWS_COUNT if no count given
        sec_counts = []
        for s in sections:
            if ':' in s:
                name, cnt = s.rsplit(':', 1)
                sec_counts.append((name.strip(), int(cnt.strip())))
            else:
                sec_counts.append((s, NEWS_COUNT))

        total = 0
        for _, sec_n in sec_counts:
            total += sec_n

        fetched = []
        seq = 0
        for section, sec_n in sec_counts:
            for page in range(1, sec_n + 1):
                draw_banner("Fetching news...", "{:02d}/{:02d}".format(seq + 1, total))
                gc.collect()
                r = None
                tmppath = _tmp_json_path(seq)
                try:
                    r = urequests.get(
                        "https://content.guardianapis.com/search"
                        "?section={}&type=article&tag=tone/news&order-by=newest"
                        "&show-fields=headline,trailText,body"
                        "&page-size=1&page={}&api-key={}".format(
                            section, page, NEWS_API_KEY),
                        timeout=30)
                    # Stream response to flash in small chunks so Python heap use stays flat.
                    with open(tmppath, 'wb') as f:
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
                with open(tmppath) as f:
                    headline = _sanitize(_json_str(f, 'headline').strip())
                with open(tmppath) as f:
                    pubkey = _pub_sort_key(_json_str(f, 'webPublicationDate').strip())
                gc.collect()

                if not headline:
                    try:
                        os.remove(tmppath)
                    except OSError:
                        pass
                    seq += 1
                    continue

                tlines = _word_wrap(headline, CHARS_TITLE)[:2]
                fetched.append((pubkey, seq, section, tlines, tmppath))
                del headline, tlines
                seq += 1
                gc.collect()
        gfx.cls(BLACK)
        fetched.sort(reverse=True)

        count = 0
        meta = []
        for pubkey, _, section, tlines, tmppath in fetched:
            draw_banner("Parsing news...", "{:02d}/{:02d}".format(count + 1, total))
            # Write summary file: title + section + trailText (HTML, same stripper as body)
            sumpath = '{}/news_{:02d}_sum.txt'.format(NEWS_DIR, count)
            with open(sumpath, 'w') as out:
                out.write((tlines[0] if tlines else '') + '\n')
                out.write((tlines[1] if len(tlines) > 1 else '') + '\n')
                out.write(section + '\n')
                out.write('---\n')
                _json_body_wrap(tmppath, 'trailText', out, CHARS_BODY, 0)
            gc.collect()

            # Write full article file: title + section + HTML body streamed and stripped
            base = 'news_{:02d}.txt'.format(count)
            outpath = NEWS_DIR + '/' + base
            with open(outpath, 'w') as out:
                out.write((tlines[0] if tlines else '') + '\n')
                out.write((tlines[1] if len(tlines) > 1 else '') + '\n')
                out.write(section + '\n')
                out.write('---\n')
                _json_body_wrap(tmppath, 'body', out, CHARS_BODY, NEWS_BODY_LINES)
            try:
                os.remove(tmppath)
            except OSError:
                pass
            meta.append((base, pubkey, section))
            count += 1
            gc.collect()

        if count:
            _store_metadata(meta)
            _save_current(0)
        return count
    except Exception as e:
        # no traceback on Pico
        print("news fetch error: {}: {}".format(type(e).__name__, e))
        try:
            for fn in os.listdir(NEWS_DIR):
                if fn.startswith(_TMP_JSON_PREFIX):
                    os.remove(NEWS_DIR + '/' + fn)
        except OSError:
            pass
        return 0

def _list_files():
    try:
        files = []
        with open(NEWS_META) as f:
            while True:
                line = f.readline()
                if not line:
                    break
                parts = line.rstrip().split('|')
                if not parts or not parts[0]:
                    continue
                full = NEWS_DIR + '/' + parts[0]
                try:
                    os.stat(full)
                    files.append(full)
                except OSError:
                    pass
        if files:
            return files
    except OSError:
        pass
    try:
        fnames = sorted(fn for fn in os.listdir(NEWS_DIR)
                        if fn.startswith('news_') and fn.endswith('.txt')
                        and '_sum' not in fn)
        return [NEWS_DIR + '/' + fn for fn in fnames]
    except OSError:
        return []

# Drawing
def _header_line(section='', idx=None, total=None):
    """Return the header clock line with article counter at the upper left."""
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
    if idx is not None and total is not None:
        line = '{}/{}  {}'.format(idx + 1, total, line)
    if len(line) > CHARS_BODY:
        line = line[:CHARS_BODY]
    return line

def _draw_header(t1, t2, section='', idx=None, total=None):
    """Redraw pinned clock + title + separator each scroll step.
    Clears the full header rows before redrawing to avoid stale text."""
    clk = _header_line(section, idx, total)

    # Clear scrolling artifacts
    for yy in range(CLOCK_Y, CLOCK_Y + 8):
        gfx.hline(yy, 0, 255, BLACK)
    gfx.line(0, TITLE_Y1 - 1, 255, TITLE_Y1 - 1, BLACK)
    gfx.line(0, TITLE_Y2 - 1, 255, TITLE_Y2 - 1, BLACK)
    gfx.line(0, SEP_Y - 1, 255, SEP_Y - 1, BLACK)
    gfx.line(0, SEP_Y + 6, 255, SEP_Y + 6, BLACK)

    # Draw date/time, header lines and separator
    gfx.line(0, SEP_Y,     255, SEP_Y,     7)
    gfx.print_string(0, CLOCK_Y, clk, BLACK, WHITE)
    gfx.print_string((256 - len(t1)  * 8) // 2, TITLE_Y1, t1,  BLACK, WHITE)
    if t2:
        gfx.print_string((256 - len(t2) * 8) // 2, TITLE_Y2, t2, BLACK, WHITE)

# Article display
def _show_article(filename, pin, mode_counter, mode_expected,
                  p13=None, c13=0, e13=1,
                  p14=None, c14=0, e14=1,
                  hold_ms=None, idx=None, total=None):
    """Display one article with smooth scroll if content exceeds screen height.
    Returns (result, mode_counter, c13, e13, c14, e14)."""

    if hold_ms is None:
        hold_ms = HOLD_MS

    with open(filename) as f:
        t1      = f.readline().rstrip()
        t2      = f.readline().rstrip()
        section = f.readline().rstrip()   # section name (e.g. "world")
        f.readline()                      # skip '---'

        # Initial screen: cls clears everything, then draw header + body directly
        gfx.cls(BLACK)
        clk = _header_line(section, idx, total)
        gfx.print_string(0, CLOCK_Y, clk, BLACK, WHITE)
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
                return 'MODE', mode_counter, c13, e13, c14, e14
            swap, c13, e13, c14, e14 = _check_detail_swap(p13, c13, e13, p14, c14, e14)
            if swap:
                gfx.cls(BLACK)
                return 'SWAP', mode_counter, c13, e13, c14, e14
            time.sleep_ms(10)
        if nxtline is None:
            # fits on one screen - initial hold was enough, move on
            return None, mode_counter, c13, e13, c14, e14

        # Smooth scroll: 1 px/frame, new body line every LINE_H pixels.
        # Print the incoming line at 192-sub_px each frame so it rises into
        # view clipped at the bottom edge rather than popping in all at once.
        sub_px = 0
        while nxtline is not None:
            active, mode_counter = check_pin_stable(pin, mode_expected, mode_counter)
            if not active:
                return 'MODE', mode_counter, c13, e13, c14, e14
            swap, c13, e13, c14, e14 = _check_detail_swap(p13, c13, e13, p14, c14, e14)
            if swap:
                gfx.cls(BLACK)
                return 'SWAP', mode_counter, c13, e13, c14, e14
            gfx.wait_vblank()
            gfx.scroll_up(BLACK, 1)
            _draw_header(t1, t2, section, idx, total)
            sub_px += 1
            gfx.print_string(0, 192 - sub_px, nxtline, BLACK, WHITE)
            if sub_px == LINE_H:
                sub_px = 0
                nxt     = f.readline()
                nxtline = nxt.rstrip() if nxt else None
            time.sleep_ms(read_speed_adc() if USE_ADC_SPEED else SCROLL_DELAY_MS)

    deadline = time.ticks_add(time.ticks_ms(), HOLD_AFTER_MS)
    while time.ticks_diff(deadline, time.ticks_ms()) > 0:
        active, mode_counter = check_pin_stable(pin, mode_expected, mode_counter)
        if not active:
            return 'MODE', mode_counter, c13, e13, c14, e14
        swap, c13, e13, c14, e14 = _check_detail_swap(p13, c13, e13, p14, c14, e14)
        if swap:
            gfx.cls(BLACK)
            return 'SWAP', mode_counter, c13, e13, c14, e14
        time.sleep_ms(10)
    return None, mode_counter, c13, e13, c14, e14

# RSVP helpers
def _orp_index(word_len):
    """Spritz-style Optimal Recognition Point position for a word of this length."""
    if word_len <= 1: return 0
    if word_len <= 5: return 1
    if word_len <= 9: return 2
    if word_len <= 13: return 3
    return 4

def _current_wpm():
    """Reading speed in words per minute, overridden live by the ADC pot when enabled."""
    adc = read_speed_adc()
    if adc is None:
        return RSVP_WPM
    return 100 + (adc * 500) // 255

def _tokenize_body(f):
    """Stream words from the article body. Each yield is (word, multiplier) where
    multiplier is an extra fraction of base_ms to hold the current tick:
      0.0  - plain word
      0.5  - after comma / semicolon / colon
      1.0  - after sentence terminator (. ! ?)
      2.0  - paragraph break (empty word, pause only)
    Words longer than RSVP_MAX_LEN are truncated with '~' so they still fit the 2x layout."""
    while True:
        line = f.readline()
        if not line:
            return
        s = line.rstrip()
        if not s:
            yield '', 2.0
            continue
        for word in s.split():
            last = word[-1]
            if last in '.!?':
                mult = 1.0
            elif last in ',;:':
                mult = 0.5
            else:
                mult = 0.0
            if len(word) > RSVP_MAX_LEN:
                word = word[:RSVP_MAX_LEN - 1] + '~'
            yield word, mult

def _draw_rsvp_pinpoint():
    """Short vertical pinpoint marks above/below the word row at the fixed ORP
    column. Optional full-width horizontal rails (Spritz-style reading window)
    when RSVP_RAILS is True."""
    y_top_out = RSVP_WORD_Y - 10
    y_top_in  = RSVP_WORD_Y - 3    # inner end: 2 px before the glyph
    y_bot_in  = RSVP_WORD_Y + 18   # inner end: 2 px below the glyph
    y_bot_out = RSVP_WORD_Y + 25
    gfx.line(RSVP_PIN_COL, y_top_out, RSVP_PIN_COL, y_top_in, WHITE)
    gfx.line(RSVP_PIN_COL, y_bot_in,  RSVP_PIN_COL, y_bot_out, WHITE)
    if RSVP_RAILS:
        gfx.hline(y_top_out, 0, 255, WHITE)
        gfx.hline(y_bot_out, 0, 255, WHITE)

def _show_article_rsvp(filename, pin, mode_counter, mode_expected,
                       p13, c13, e13, p14, c14, e14,
                       idx=None, total=None):
    """Display one article RSVP-style: one word per tick in 2x font, ORP letter
    highlighted with a color-6 background, pinpoint marks at the fixed ORP column.
    Returns (result, mode_counter, c13, e13, c14, e14)."""
    with open(filename) as f:
        t1      = f.readline().rstrip()
        t2      = f.readline().rstrip()
        section = f.readline().rstrip()
        f.readline()   # skip '---'

        gfx.cls(BLACK)
        _draw_header(t1, t2, section, idx, total)
        _draw_rsvp_pinpoint()

        for word, mult in _tokenize_body(f):
            base_ms  = 60000 // _current_wpm()
            total_ms = int(base_ms * (1.0 + mult))

            gfx.wait_vblank()
            # Clear only the 16 px word row, leaving header and pinpoints intact.
            for yy in range(RSVP_WORD_Y, RSVP_WORD_Y + 16):
                gfx.hline(yy, 0, 255, BLACK)
            if word:
                orp    = _orp_index(len(word))
                word_x = RSVP_ORP_X - orp * 16
                for i, ch in enumerate(word):
                    bg = COLOUR6 if i == orp else BLACK
                    gfx.print_string_2x(word_x + i * 16, RSVP_WORD_Y, ch, bg, WHITE)
            # Refresh header so the clock and article counter stay live, and
            # re-stroke the pinpoints in case _draw_header painted over them.
            _draw_header(t1, t2, section, idx, total)
            _draw_rsvp_pinpoint()

            deadline = time.ticks_add(time.ticks_ms(), total_ms)
            while time.ticks_diff(deadline, time.ticks_ms()) > 0:
                active, mode_counter = check_pin_stable(pin, mode_expected, mode_counter)
                if not active:
                    return 'MODE', mode_counter, c13, e13, c14, e14
                swap, c13, e13, c14, e14 = _check_detail_swap(p13, c13, e13, p14, c14, e14)
                if swap:
                    gfx.cls(BLACK)
                    return 'SWAP', mode_counter, c13, e13, c14, e14
                time.sleep_ms(5)

    # End-of-article: same inter-article pause as scroll mode.
    deadline = time.ticks_add(time.ticks_ms(), HOLD_AFTER_MS)
    while time.ticks_diff(deadline, time.ticks_ms()) > 0:
        active, mode_counter = check_pin_stable(pin, mode_expected, mode_counter)
        if not active:
            return 'MODE', mode_counter, c13, e13, c14, e14
        swap, c13, e13, c14, e14 = _check_detail_swap(p13, c13, e13, p14, c14, e14)
        if swap:
            gfx.cls(BLACK)
            return 'SWAP', mode_counter, c13, e13, c14, e14
        time.sleep_ms(10)
    return None, mode_counter, c13, e13, c14, e14

# Entry point
def run(pin=None, modes=None):
    """Run the news reader.

    modes dict shape:
      "default": "full" | "summary" | "rsvp"   - mode when no mapped pin is low
      <int gpio>: "full" | "summary" | "rsvp"  - mode activated when that pin is low
    Any GPIO key is optional - omit both and news stays locked on the default mode.
    """
    global wlan
    from machine import Pin as _Pin

    gfx.init()
    gfx.set_border(0)
    gfx.cls(BLACK)

    if modes is None:
        # Matches pre-refactor behaviour: p13 low = summary, p14 low = full, neither = rsvp.
        modes = {"default": "rsvp", 13: "summary", 14: "full"}
    default_mode = _MODE_NAME_TO_CONST[modes.get("default", "rsvp")]

    # Build up to two detail pins from the integer keys of modes, preserving
    # the module's existing p13/p14 plumbing (first detail gpio -> p13, second -> p14).
    _gpios = sorted((k, _MODE_NAME_TO_CONST[v]) for k, v in modes.items() if isinstance(k, int))
    p13 = _Pin(_gpios[0][0], _Pin.IN, _Pin.PULL_UP) if len(_gpios) >= 1 else None
    p14 = _Pin(_gpios[1][0], _Pin.IN, _Pin.PULL_UP) if len(_gpios) >= 2 else None
    m13 = _gpios[0][1] if len(_gpios) >= 1 else None
    m14 = _gpios[1][1] if len(_gpios) >= 2 else None

    def _detail_mode(v13, v14):
        if p14 is not None and v14 == 0:
            return m14
        if p13 is not None and v13 == 0:
            return m13
        return default_mode

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
    mode_counter  = 0
    # Initial detail pin state: read from actual pins so no spurious SWAP fires at boot.
    # None pins report as "high" so they never contribute to mode changes.
    e13 = p13.value() if p13 is not None else 1
    e14 = p14.value() if p14 is not None else 1
    if p14 is not None and e14 == 0:
        e13, e14 = 1, 0
    elif p13 is not None and e13 == 0:
        e13, e14 = 0, 1
    else:
        e13, e14 = 1, 1
    c13 = 0
    c14 = 0

    current_saved = None
    while True:
        active, mode_counter = check_pin_stable(pin, mode_expected, mode_counter)
        if not active:
            return

        now   = time.time()
        files = _list_files()

        if not files or now - last_fetch_ts >= NEWS_INTERVAL:
            draw_banner("Fetching news...")
            deadline = time.ticks_add(time.ticks_ms(), 2000)
            escaped = False
            while time.ticks_diff(deadline, time.ticks_ms()) > 0:
                active, mode_counter = check_pin_stable(pin, mode_expected, mode_counter)
                if not active:
                    return
                swap, c13, e13, c14, e14 = _check_detail_swap(p13, c13, e13, p14, c14, e14)
                if swap:
                    escaped = True
                    break
                time.sleep_ms(10)
            if escaped:
                continue
            n = _fetch_and_store()
            if n > 0:
                last_fetch_ts = time.time()
                current_saved = -1
            files = _list_files()

        if not files:
            gfx.cls(BLACK)
            gfx.print_string(16, 92, "News unavailable", BLACK, WHITE)
            deadline = time.ticks_add(time.ticks_ms(), 60000)
            while time.ticks_diff(deadline, time.ticks_ms()) > 0:
                active, mode_counter = check_pin_stable(pin, mode_expected, mode_counter)
                if not active:
                    return
                swap, c13, e13, c14, e14 = _check_detail_swap(p13, c13, e13, p14, c14, e14)
                if swap:
                    break
                time.sleep_ms(10)
            continue

        idx = _load_current(files)
        while idx < len(files):
            active, mode_counter = check_pin_stable(pin, mode_expected, mode_counter)
            if not active:
                return
            mode = _detail_mode(e13, e14)
            base = files[idx]
            if current_saved != idx:
                _save_current(idx)
                current_saved = idx
            if mode == MODE_RSVP:
                result, mode_counter, c13, e13, c14, e14 = _show_article_rsvp(
                    base, pin, mode_counter, mode_expected,
                    p13, c13, e13, p14, c14, e14, idx, len(files))
            elif mode == MODE_SUMMARY:
                spath = base[:-4] + '_sum.txt'
                try:
                    os.stat(spath)
                    show_file = spath
                except OSError:
                    show_file = base   # fall back to full if no summary cached
                result, mode_counter, c13, e13, c14, e14 = _show_article(
                    show_file, pin, mode_counter, mode_expected,
                    p13, c13, e13, p14, c14, e14, HOLD_SUM_MS, idx, len(files))
            else:   # MODE_FULL
                result, mode_counter, c13, e13, c14, e14 = _show_article(
                    base, pin, mode_counter, mode_expected,
                    p13, c13, e13, p14, c14, e14, HOLD_MS, idx, len(files))
            if result == 'MODE':
                return
            elif result == 'SWAP':
                pass   # re-show same article in new mode
            else:
                idx += 1
        if idx >= len(files):
            _save_current(0)
            current_saved = 0
