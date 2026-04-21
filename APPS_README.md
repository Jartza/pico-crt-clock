# App Engineering Guide

This document complements the main [README](README.md). The top-level README
explains what the firmware is and how to build it; this guide focuses on how
the bundled apps are put together and which patterns have proven useful on
RP2040 + MicroPython + composite video.

It is aimed mainly at people writing their own apps for this firmware base, but
it also works as a more detailed catalog of the bundled examples.

## Bundled Apps At A Glance

| App | What it shows | Why it is a useful reference |
|---|---|---|
| Weather | Clock, current temperature, wind, and 3-day forecast | Simple dashboard layout with cached network data and pre-generated sprites |
| News | Guardian articles in full, summary, or RSVP mode | Best example of streaming to flash, article caching, and reducing flicker in a scrolling UI |
| Sky | Time/date, sunrise/sunset, moon phase, and KP forecast | Good model for day-level caching and avoiding unsafe float-heavy astronomy math |
| Electricity | 24-hour spot-price bar chart with optional tomorrow view | Best example of chart rendering under blit-size and heap constraints |
| Torus | Animated 3D torus demo | Shows how far precomputation and integer math can go when Python needs to draw every frame |

## Cross-App Patterns

These are the main lessons repeated across the bundled apps.

- Prefer flash-backed caches over keeping large network payloads in RAM. The weather, news, sky, and electricity apps all fetch into cache files and then load only what they need.
- Give the user a short escape window before starting a fetch. Weather, sky, and electricity all show a banner and poll the mode pin before beginning network I/O and flash writes.
- Reuse prebuilt draw buffers when a shape repeats. On RP2040, a few `gfx.blit()` calls are often cheaper and steadier than redrawing the same geometry in Python every frame.
- Keep per-frame work small. Stable headers, cached tiles, and “redraw only when state changes” logic matter more on hardware than they do in the simulator.
- Treat RP2040 MicroPython math as single-precision. If a formula depends on very large floating-point values, reduce the epoch or precompute it elsewhere.

## Weather

Weather is the simplest example of a network-backed dashboard app.

- It stores the two Open-Meteo responses separately in `weathercache/` and reuses them until `WEATHER_INTERVAL` expires, which keeps mode switches from triggering unnecessary refetches.
- It loads `icons.bin` once at startup and slices it through a `memoryview`, so the app can reuse fixed 32x16 icon assets without allocating fresh buffers.
- It extracts today's hourly temperatures into a compact 24-value list for hour-change updates instead of reparsing the full hourly JSON every second.
- The screen is mostly static. Each redraw paints the whole dashboard, but the layout is simple and sprite-heavy, so it stays within acceptable cost.
- The burn-in screensaver moves the whole composition as one block rather than redrawing a different layout.

Why it matters for new apps:

- Good starting point for any app with a mostly static dashboard and a small amount of periodically refreshed network data.
- Shows the simplest “cache to flash, parse into compact Python structures, then redraw from that” pattern.

## News

News is the most demanding bundled app from both RAM and flicker perspectives.

- It fetches Guardian responses one article at a time and writes them to temporary files, rather than keeping the whole feed in RAM.
- It parses and stores article content into local text files in `newscache/`, including separate summary files, so display mode switches do not need to hit the network again.
- Cached article ordering metadata lives in `newscache/index.txt`, and the current article index is stored in RP2040 watchdog scratch registers instead of a flash-backed state file. That avoids extra flash churn during article browsing.
- Full-mode scrolling is optimized around the video frame boundary: non-drawing work such as building the header line is done before `gfx.wait_vblank()`, and the actual scroll + header redraw + incoming line draw are grouped tightly after sync.
- The header line itself is cached by minute/article context, so it is not rebuilt on every scroll step.
- RSVP mode reduces redraw cost by only clearing and repainting the word row while keeping the header structure stable.

Why it matters for new apps:

- Use this as the model when an app needs large fetched content, multiple presentation modes, or scroll-heavy rendering.
- The main lesson is to move as much work as possible out of the hot display loop, and to persist navigation state without writing a file every time.

## Sky

Sky is a compact example of caching computed visuals and constraining math for RP2040.

- It keeps NOAA KP data in `skycache/` and refreshes it only when stale.
- It caches day-level astronomy values, so sunrise/sunset strings, moon age, illumination, and phase name are not recomputed every frame.
- The moon is rendered into a reusable `bytearray` sprite and then blitted, with only the outline drawn live on top.
- The sunrise/sunset and moon-phase code avoids large Julian-day floats and instead uses reduced-epoch calculations near year 2000. That is important because this MicroPython build uses single-precision floats.
- Like weather and electricity, it keeps the whole layout inside a smaller safe area and moves that block with a gentle screensaver offset to reduce burn-in risk.

Why it matters for new apps:

- Good reference for apps with medium-cost math and one or two expensive visuals that can be cached.
- If you are doing astronomy, calendars, or other date-heavy calculations, copy the “reduced epoch, cache per day” mindset rather than trusting desktop-style formulas unchanged.

## Electricity

Electricity is the strongest example of designing around `gfx.blit()` limits.

- Price data is fetched into a temporary file first, validated, then renamed into `eleccache/prices.json`. That avoids leaving a half-written cache behind.
- API timestamps are converted to local time before grouping by hour, and sub-hour source rows are averaged into local hourly values.
- Tomorrow data is hidden unless a full 24-hour local day is available, which avoids misleading partial charts.
- The chart is not redrawn bar-by-bar every frame. Instead, it is built into a set of reusable tile buffers sized to stay under the native blit buffer limit (`sw * sh <= 4096`) and then blitted back to the screen.
- The app only rebuilds that chart cache when the underlying view changes, such as a new hour, a day change, or a view-mode switch.

Why it matters for new apps:

- Use this as the reference when a UI contains charts, repeated geometry, or any other display element that is expensive to redraw procedurally.
- The core lesson is to split large visuals into reusable tiles that fit the blit limits instead of trying to paint the whole widget from scratch every refresh.

## Torus

Torus is not a utility app, but it is still useful as a performance reference.

- Geometry, normals, and lookup tables are precomputed into `torus.bin` on the host side and loaded once at boot.
- Runtime animation uses integer phase counters and LUT lookups instead of calling trig functions every frame.
- The heavy per-frame math lives in `@micropython.viper` helpers, while Python stays responsible for orchestration and final draw calls.
- The effect still redraws the frame continuously, but it does so using precomputed data structures and integer math wherever possible.

Why it matters for new apps:

- Good reference if an app needs animation or transformation-heavy rendering.
- The key idea is to push expensive math and static data generation out of the live frame loop, either into host-generated assets or into tight integer-heavy helpers.

## Patterns For New Apps

If you are adding your own app, the bundled examples suggest a few practical defaults.

- Start with a static or mostly static layout. Add animation only after the basic app is stable on hardware.
- Cache fetched payloads to flash and derive smaller Python-side structures from them.
- When a visual repeats, pre-render it into a sprite or tile and `blit` it.
- Redraw on state changes when possible, not just because the main loop iterated.
- Keep hot paths boring: avoid repeated string assembly, large JSON work, or complex math inside a per-frame loop.
- Test on real hardware early. The simulator is useful for logic and layout, but flicker, float precision, and heap pressure often show up only on RP2040.
