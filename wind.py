#!/usr/bin/env -S uv run --quiet
# /// script
# dependencies = ["numpy", "pillow"]
# ///
"""windcode-theme: animated wind-field chat backgrounds for T3 Code.

A grid of small letters, faint everywhere, lit where gusts of wind pass over
it, with letters quietly changing in place. After Claude Code's "New session"
texture; the gust field follows the one behind the Gospel Scholar Archive's landing page
(warped value-noise fbm with thin wind threads). No Anthropic code.

T3 themes take CSS only (no scripts, at most 20,000 characters), so:
  - the glyph grid is a small SVG tile, repeated;
  - the gust field is computed here once, into a small PNG that tiles;
  - the page's CSS animates mask positions: the wind drifts at 34 px/s, two
    copies of the field at different sizes and speeds intersect so gusts
    reshape as they travel, and a sparse cell mask jumps every 0.4 s to swap
    letters in place.
Animation must live in the page's CSS: Chromium shows an animated SVG used as
a background image as a still picture.

  ./wind.py        # (needs uv) writes themes/*.json and preview/preview.html
"""
import base64, io, json, os, random, urllib.parse

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "themes")
PREVIEW = os.path.join(HERE, "preview")

LATIN = "abcdefghijklmnopqrstuvxyzABCDEFGHIJKLMNOPQRSTUVXYZ0123456789"
ARCHIVE = ("ΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡΣΤΥΦΧΨΩαβγδεζηθικλμνξοπρστυφχψω"
           "אבגדהוזחטיכלמנסעפצקרשת" + LATIN + "§¶†‡·:;")
CODE = LATIN + "{}[]()<>=+-*/;:._#$%&|~"

STYLES = {
    # Closest to the Claude Code texture: grey letters, a slow wind.
    "wind": dict(name="Wind", appearance="dark", canvas="#000000", accent="#1AADFF",
                 glyphs=LATIN, ink="#e8e6dc", ambient=.03, lit=.13, scale=(500, 175), threshold=(.45, .66), period=59, seed=7,
                 glass="#17171acc", sheen="#ffffff0d", edge="#ffffff14"),
    # gsa-dash's own Field: the archive's alphabets.
    "archive": dict(name="Archive Wind", appearance="dark", canvas="#000000", accent="#1AADFF",
                    glyphs=ARCHIVE, ink="#efe9d8", ambient=.03, lit=.14, scale=(500, 175), threshold=(.45, .66), period=59, seed=11,
                    glass="#17171acc", sheen="#ffffff0d", edge="#ffffff14"),
    # Waves: long swells of blue-lit code characters rolling sideways.
    "tide": dict(name="Tide", appearance="dark", canvas="#000000", accent="#1AADFF",
                 glyphs=CODE, ink="#7fd0ff", ambient=.03, lit=.15, scale=(1000, 100), threshold=(.45, .66), period=59, seed=3,
                 glass="#0f1a24cc", sheen="#bfe6ff10", edge="#bfe6ff1a"),
    # Light: ink letters on paper, the same wind.
    "paper": dict(name="Paper Wind", appearance="light", canvas="#f4f1e8", accent="#1a7fd1",
                  glyphs=LATIN, ink="#2b2a26", ambient=.035, lit=.12, scale=(500, 175), threshold=(.45, .66), period=59, seed=5,
                  glass="#e9e5d8cc", sheen="#ffffff66", edge="#0000001a"),
}

CELL_W, CELL_H, FONT = 5, 10, 7
TILE_COLS, TILE_ROWS = 72, 26
MASKS = [(2000, 1400), (1600, 1120)]   # the same gust field twice, at two sizes; lit only where both are
RES = 10                               # gust field pixel = RES css px (it is smooth, so it upscales cleanly)
LANDING = 1.4                          # landing page brightness, relative to chats
FPS = 24                               # mask steps per second; keeps repaints cheap


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def url(svg):
    return 'url("data:image/svg+xml,' + urllib.parse.quote(svg, safe=" =:/;,.-_'()") + '")'


def tile(st, rnd):
    w, h = TILE_COLS * CELL_W, TILE_ROWS * CELL_H
    rows = "".join(
        f'<tspan x="0" y="{r * CELL_H + 8}" textLength="{w}" lengthAdjust="spacing">'
        f'{esc("".join(rnd.choice(st["glyphs"]) for _ in range(TILE_COLS)))}</tspan>'
        for r in range(TILE_ROWS))
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}">'
            f'<text font-family="ui-monospace,Menlo,monospace" font-size="{FONT}" fill="{st["ink"]}">{rows}</text></svg>')


def _vnoise(x, y, px, py, rng):
    """Value noise, periodic over px by py lattice cells."""
    t = rng.random((py, px))
    ix, iy = np.floor(x).astype(int), np.floor(y).astype(int)
    fx, fy = x - ix, y - iy
    fx, fy = fx * fx * (3 - 2 * fx), fy * fy * (3 - 2 * fy)
    h = lambda a, b: t[(iy + b) % py, (ix + a) % px]
    return (h(0, 0) * (1 - fx) + h(1, 0) * fx) * (1 - fy) + (h(0, 1) * (1 - fx) + h(1, 1) * fx) * fy


def gust_field(st, seed):
    """gsa-dash's cloud (field.js VERT: warp, 4-octave fbm, wind threads), made to tile seamlessly.

    Returns a PNG data URL: white, with alpha = how lit each spot is."""
    W, H = MASKS[0]
    rng = np.random.default_rng(seed)
    x, y = np.meshgrid((np.arange(W // RES) + .5) * RES, (np.arange(H // RES) + .5) * RES)
    # warp: a slow low-frequency field bends the wind (field.js: p/420, strength 90)
    wx = _vnoise(x / 400, y / 350, W // 400, H // 350, rng) - .5
    wy = _vnoise(x / 400, y / 350, W // 400, H // 350, rng) - .5
    x, y = x + wx * 90, y + wy * 90
    sx, sy = st["scale"]                       # field.js gust: 460 x 170 px
    cx, cy = W // sx, H // sy
    cloud, a, n = 0, .5, 0
    for k in range(4):
        f = 2 ** k
        cloud = cloud + a * _vnoise(x / sx * f, y / sy * f, cx * f, cy * f, rng)
        n += a; a *= .52
    cloud = cloud / n
    # threads: thin streaks along the wind (field.js: q / (160, 26))
    th = _vnoise(x / (W / 12), y / (H / 54), 12, 54, rng)
    thread = 1 - np.clip(np.abs(th - .5) / .22, 0, 1) ** 2 * (3 - 2 * np.clip(np.abs(th - .5) / .22, 0, 1))
    cloud = cloud + .07 * (thread - .5)
    lo, hi = st["threshold"]
    v = np.clip((cloud - lo) / (hi - lo), 0, 1)
    v = v * v * (3 - 2 * v)
    alpha = (np.round(v * 7) * 36.4).astype(np.uint8)       # 8 levels compress well
    img = Image.new("LA", (W // RES, H // RES), 255)
    img.putalpha(Image.fromarray(alpha, "L"))
    buf = io.BytesIO(); img.save(buf, "PNG", optimize=True)
    return 'url("data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode() + '")', float((v > .3).mean())


SPARK = (100, 130)       # flicker tile: 20 x 13 cells
SPARK_DENSITY = .09      # share of cells showing their other letter at any moment
FLICK_STEPS, FLICK_S = 16, .4   # the flicker pattern jumps every FLICK_S seconds


def spark_tiles(rnd):
    """Two masks on the cell grid: a few cells on (where letters swap), and its inverse."""
    w, h = SPARK
    cells = [(x, y) for x in range(0, w, CELL_W) for y in range(0, h, CELL_H) if rnd.random() < SPARK_DENSITY]
    d = "".join(f"M{x} {y}h{CELL_W}v{CELL_H}h-{CELL_W}z" for x, y in cells)
    on = f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}"><path d="{d}"/></svg>'
    off = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}">'
           f'<path fill-rule="evenodd" d="M0 0h{w}v{h}H0z{d}"/></svg>')
    return on, off


def css(st):
    rnd = random.Random(st["seed"])
    p = st["period"]
    (w1, h1), (w2, h2) = MASKS
    gust, cover = gust_field(st, st["seed"])
    st["cover"] = cover
    on, off = spark_tiles(rnd)
    A = '[data-workspace-area="conversation"]'
    S = '[data-slot="sidebar-inner"]'
    c = st["canvas"]
    calm = f"radial-gradient(ellipse 60% 70% at 50% 50%,{c}d0,{c}66 65%,{c}00)"
    amb = round(st["ambient"] / st["lit"], 2)
    base = f"linear-gradient(#000000{int(amb * 255):02x},#000000{int(amb * 255):02x})"
    sw, sh = SPARK
    sizes = f"{sw}px {sh}px,100% 100%,{w1}px {h1}px,{w2}px {h2}px"
    # the flicker: where the cell mask jumps to, and which other letter shows there
    ys = [rnd.randrange(1, sh // CELL_H) * CELL_H for _ in range(FLICK_STEPS)]
    shifts = [(rnd.randrange(1, 12) * CELL_W, rnd.randrange(1, 9) * CELL_H) for _ in range(FLICK_STEPS)]
    flick = FLICK_STEPS * FLICK_S
    ky = "".join(f"{i * 100 / FLICK_STEPS:.2f}%{{-webkit-mask-position-y:{y}px,0,0,0}}" for i, y in enumerate(ys))
    kb = "".join(f"{i * 100 / FLICK_STEPS:.2f}%{{background-position:0 0,{x}px {y}px}}" for i, (x, y) in enumerate(shifts))
    return (
        f":root{{--wg:{url(tile(st, rnd))};--wd:{gust};--won:{url(on)};--woff:{url(off)}}}"
        f"{A}{{position:relative;isolation:isolate}}"
        # a new thread's empty timeline is painted solid; let the wind through
        f"{A} [data-timeline-loading]{{background:transparent!important}}"
        # brighter on the new-thread page, where there is nothing to read past it
        f"{A}:has([data-timeline-loading=true])::before,{A}:has([data-timeline-loading=true])::after{{opacity:{st['lit'] * LANDING:.3f}}}"
        # ::after shows the letters, ::before shows the other letter in the cells that are flickering
        f"{A}::before,{A}::after{{content:'';position:absolute;inset:0;z-index:-1;pointer-events:none;"
        f"opacity:{st['lit']};background-image:{calm},var(--wg);background-size:100% 100%,auto;"
        f"mask-size:{sizes};mask-composite:intersect,add,intersect,add;"
        f"animation:t3wx {p}s steps({p * FPS}) infinite,t3wy {flick:g}s step-end infinite}}"
        f"{A}::after{{mask-image:var(--woff),{base},var(--wd),var(--wd)}}"
        f"{A}::before{{mask-image:var(--won),{base},var(--wd),var(--wd);"
        f"animation:t3wx {p}s steps({p * FPS}) infinite,t3wy {flick:g}s step-end infinite,t3wb {flick:g}s step-end infinite}}"
        f"@keyframes t3wx{{0%{{-webkit-mask-position-x:0,0,0,0}}100%{{-webkit-mask-position-x:0,0,-{w1}px,-{w2}px}}}}"
        f"@keyframes t3wy{{{ky}}}@keyframes t3wb{{{kb}}}"
        # the sidebar: plain glass (letters behind it, blurred, read too big and too white)
        f"{S}{{position:relative;isolation:isolate;background:linear-gradient(180deg,{st['sheen']},transparent 35%),{st['glass']}!important;"
        f"box-shadow:inset -1px 0 0 {st['edge']}}}"
        f"@media (prefers-reduced-motion:reduce){{{A}::before,{A}::after{{animation:none}}}}"
    )


def main():
    os.makedirs(OUT, exist_ok=True)
    os.makedirs(PREVIEW, exist_ok=True)
    cards = []
    for key, st in STYLES.items():
        c = css(st)
        t = {"version": 1, "name": st["name"], "appearance": st["appearance"],
             "canvas": st["canvas"], "accent": st["accent"],
             "colors": {"sidebar": st["glass"][:7]}, "css": c}
        json.dump(t, open(os.path.join(OUT, f"{st['name'].lower().replace(' ', '-')}.json"), "w"), ensure_ascii=False)
        print(f"{key:8} css {len(c):6} chars, lit {st['cover']:.0%}")
        assert len(c) <= 20000, key
        fg = "#e8e6dc" if st["appearance"] == "dark" else "#2b2a26"
        scoped = c.replace('[data-workspace-area="conversation"]', f'#{key}')
        cards.append(f"""<style>{scoped}</style><figure><div class="win" id="{key}" style="background:{st['canvas']};color:{fg}">
<div class="msg user">Can you check whether the Air reconnected after the update?</div>
<div class="msg">Yes. Both Macs are on the same Nightly build and the Air answers again.</div>
<div class="composer" style="border-color:{st['accent']}55">Ask anything…</div></div>
<figcaption><b>{st['name']}</b> · {st['appearance']}</figcaption></figure>""")
    open(os.path.join(PREVIEW, "preview.html"), "w").write(f"""<!doctype html><meta charset="utf-8"><title>Wind Backgrounds</title>
<style>body{{margin:0;padding:16px;background:#0b0b0a;color:#ddd;font:14px/1.45 system-ui}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,520px),1fr));gap:16px}}
figure{{margin:0}}figcaption{{padding:6px 2px;color:#aaa}}
.win{{height:340px;border-radius:12px;overflow:hidden;padding:24px 28px;box-sizing:border-box;border:1px solid #ffffff14}}
.msg{{max-width:440px;margin:0 auto 14px;position:relative}}.user{{background:#ffffff12;padding:8px 12px;border-radius:12px;width:fit-content;margin-left:auto;margin-right:calc(50% - 220px)}}
.composer{{position:absolute;left:50%;bottom:20px;transform:translateX(-50%);width:min(440px,80%);border:1px solid;border-radius:14px;padding:12px;opacity:.75}}</style>
<div class="grid">{''.join(cards)}</div>""")


if __name__ == "__main__":
    main()
