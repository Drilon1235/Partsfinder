"""Builds the DZ IT Services brand kit (marks, lockups, icons) as SVG/PNG/ICO.

Run from anywhere: python brand/source/build_brand.py
Needs: pip install fonttools brotli; rsvg-convert (librsvg) and ImageMagick `convert` on PATH.
"""
import math, os, subprocess, json
from fontTools.ttLib import TTFont
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.normpath(os.path.join(HERE, ".."))   # the brand/ folder
T, W = 56, 12           # tube width, core line width (DZ proportions)
C = dict(ink="#0F2235", deep="#1F4E79", blue="#2A6DB0", azure="#3E86CE", sky="#41A0DC",
         teal="#3BA6B8", node="#58CEEC", white="#FFFFFF", night="#0B1624")
FONT = os.path.join(OUT, "fonts", "space-grotesk-latin-{w}-normal.woff2")  # needs: pip install fonttools brotli

def f(p): return f"{p[0]:.1f} {p[1]:.1f}"
def apt(cx, cy, r, deg):
    a = math.radians(deg); return (cx + r*math.cos(a), cy + r*math.sin(a))

# ---------------------------------------------------------------- text -> path
def text_path(text, size, weight=700, x=0, y=0, tracking=0.0):
    font = TTFont(FONT.format(w=weight)); gs = font.getGlyphSet(); cmap = font.getBestCmap()
    upm = font["head"].unitsPerEm; s = size/upm; ds = []; cx = x
    for ch in text:
        g = cmap.get(ord(ch));
        if g is None: continue
        pen = SVGPathPen(gs)
        gs[g].draw(TransformPen(pen, (s, 0, 0, -s, cx, y)))
        ds.append(pen.getCommands()); cx += gs[g].width*s + tracking*size
    return " ".join(ds), cx - x - tracking*size

# ---------------------------------------------------------------- tube marks
class Mark:
    """Stroked 'tubes' drawn in order; each later tube cuts a gap into earlier ones."""
    def __init__(self, vb, tubes, extras="", grad=("#41A0DC", "#2E78B8", "#1F4E79"), t=T, w=W):
        self.vb, self.tubes, self.extras, self.grad, self.t, self.w = vb, tubes, extras, grad, t, w
    def svg(self, mode="color", inner=False, core=True):
        x, y, wdt, hgt = self.vb; t, w = self.t, self.w
        big = f'<rect x="{x-100}" y="{y-100}" width="{wdt+200}" height="{hgt+200}" fill="#fff"/>'
        defs = [f'''<linearGradient id="g" gradientUnits="userSpaceOnUse" x1="{x}" y1="{y}" x2="{x+wdt*0.35}" y2="{y+hgt}">
  <stop offset="0" stop-color="{self.grad[0]}"/><stop offset=".5" stop-color="{self.grad[1]}"/><stop offset="1" stop-color="{self.grad[2]}"/></linearGradient>
 <linearGradient id="tr" x1="0" x2="1"><stop offset="0" stop-color="{C['node']}" stop-opacity="0"/><stop offset="1" stop-color="{C['node']}"/></linearGradient>
 <radialGradient id="glow"><stop offset="0" stop-color="{C['node']}" stop-opacity=".55"/><stop offset="1" stop-color="{C['node']}" stop-opacity="0"/></radialGradient>''']
        body = []
        stroke = {"color": "url(#g)", "white": C["white"], "ink": C["ink"]}[mode]
        for i, (d, cap) in enumerate(self.tubes):
            later = self.tubes[i+1:]
            cuts = "".join(f'<path d="{ld}" fill="none" stroke="#000" stroke-width="{t+16}" stroke-linecap="{lc}" stroke-linejoin="round"/>' for ld, lc in later)
            core_cut = "" if (mode == "color" or not core) else f'<path d="{d}" fill="none" stroke="#000" stroke-width="{w}" stroke-linecap="{cap}" stroke-linejoin="round"/>'
            defs.append(f'<mask id="m{i}" maskUnits="userSpaceOnUse" x="{x-100}" y="{y-100}" width="{wdt+200}" height="{hgt+200}">{big}{cuts}{core_cut}</mask>')
            core_line = f'<path d="{d}" fill="none" stroke="#fff" stroke-width="{w}" stroke-linecap="{cap}" stroke-linejoin="round"/>' if mode == "color" else ""
            body.append(f'<g mask="url(#m{i})"><path d="{d}" fill="none" stroke="{stroke}" stroke-width="{t}" stroke-linecap="{cap}" stroke-linejoin="round"/>{core_line}</g>')
        extras = self.extras(mode) if callable(self.extras) else self.extras
        content = f'<defs>{"".join(defs)}</defs>{"".join(body)}{extras}'
        if inner: return content
        return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{x} {y} {wdt} {hgt}">{content}</svg>'

def node(mode, pos, frm, r=14):
    fill = {"color": C["node"], "white": C["white"], "ink": C["ink"]}[mode]
    tr = "url(#trn)" if mode == "color" else fill
    trg = (f'<linearGradient id="trn" gradientUnits="userSpaceOnUse" x1="{frm[0]:.1f}" y1="0" x2="{pos[0]:.1f}" y2="0">'
           f'<stop offset="0" stop-color="{C["node"]}" stop-opacity="0"/><stop offset="1" stop-color="{C["node"]}"/></linearGradient>')
    glow = (f'<defs>{trg}</defs>' if mode == "color" else "")
    glow += f'<circle cx="{pos[0]}" cy="{pos[1]}" r="{r*2.2:.0f}" fill="url(#glow)"/>' if mode == "color" else ""
    return (f'{glow}<path d="M {f(frm)} L {pos[0]-r} {pos[1]}" stroke="{tr}" stroke-width="{r*0.43:.1f}" stroke-linecap="round"/>'
            f'<circle cx="{pos[0]}" cy="{pos[1]}" r="{r}" fill="{fill}"/>')

# ---- DZ: traced from the original logo (see trace_dz.py), node drawn as exact circles
class TracedMark:
    """Same interface as Mark, for the DZ logo traced from the original raster file."""
    def __init__(self, data, vb=(52, 47, 556, 302)):
        self.d, self.vb = data, vb
    def svg(self, mode="color", inner=False, core=True):
        x, y, w, h = self.vb; nd = self.d["node"]; (cx, cy), r = nd["c"], nd["r"]
        col = {"color": "url(#dzg)", "white": C["white"], "ink": C["ink"]}[mode]
        defs = (f'<linearGradient id="dzg" gradientUnits="userSpaceOnUse" x1="0" y1="{y}" x2="0" y2="{y + h}">'
                f'<stop offset="0" stop-color="#42A4D8"/><stop offset=".45" stop-color="#2F7FBF"/><stop offset="1" stop-color="#1F4E79"/></linearGradient>')
        body = []
        # the inner lines are see-through: on white they look like the original; on dark use the -white mark
        body.append(f'<path d="{self.d["silhouette"] if not core else self.d["tubes"]}" fill="{col}" fill-rule="evenodd"/>')
        tx = nd["trace_from"][0]
        if mode == "color":
            defs += (f'<radialGradient id="dzglow"><stop offset=".55" stop-color="{C["node"]}" stop-opacity=".35"/>'
                     f'<stop offset="1" stop-color="{C["node"]}" stop-opacity="0"/></radialGradient>'
                     f'<linearGradient id="dztr" gradientUnits="userSpaceOnUse" x1="{tx}" y1="0" x2="{cx}" y2="0">'
                     f'<stop offset="0" stop-color="{C["node"]}" stop-opacity="0"/><stop offset="1" stop-color="{C["node"]}"/></linearGradient>')
            body.append(f'<circle cx="{cx}" cy="{cy + 4}" r="{r*1.6:.0f}" fill="url(#dzglow)"/>'
                        f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="url(#dzg)"/>'
                        f'<path d="M {tx} {cy} L {cx} {cy}" stroke="url(#dztr)" stroke-width="4" stroke-linecap="round"/>'
                        f'<circle cx="{cx}" cy="{cy}" r="{nd["dot"]}" fill="{C["node"]}"/>')
        else:
            ring = (f'<path fill-rule="evenodd" fill="{col}" d="M {cx - r} {cy} a {r} {r} 0 1 0 {2*r} 0 a {r} {r} 0 1 0 {-2*r} 0 Z '
                    f'M {cx - nd["dot"] - 5} {cy} a {nd["dot"] + 5} {nd["dot"] + 5} 0 1 1 {2*(nd["dot"] + 5)} 0 a {nd["dot"] + 5} {nd["dot"] + 5} 0 1 1 {-2*(nd["dot"] + 5)} 0 Z"/>')
            dot = f'<circle cx="{cx}" cy="{cy}" r="{nd["dot"]}" fill="{col}"/>'
            body.append(ring + dot if core else f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{col}"/>')
        content = f'<defs>{defs}</defs>{"".join(body)}'
        if inner: return content
        return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{x} {y} {w} {h}">{content}</svg>'

def dz_mark():
    return TracedMark(json.load(open(os.path.join(HERE, "dz_mark_paths.json"))))

# ---- Partsfinder: lens + handle, nut inside, node at the end of the handle
def partsfinder_mark():
    c, r = (128, 128), 84
    lens = f"M {c[0]-r} {c[1]} A {r} {r} 0 1 1 {c[0]+r} {c[1]} A {r} {r} 0 1 1 {c[0]-r} {c[1]}"
    a = apt(*c, r, 45); b = (a[0]+46, a[1]+46)
    handle = f"M {f(a)} L {f(b)}"
    def extras(mode):
        hexfill = {"color": "url(#g)", "white": C["white"], "ink": C["ink"]}[mode]
        hr = 40; pts = [apt(*c, hr, 60*k) for k in range(6)]
        hexd = "M " + " L ".join(f(p) for p in pts) + " Z"
        hole = "#fff" if mode == "color" else "none"
        inner = (f'<path d="{hexd}" fill="{hexfill}" stroke="{hexfill}" stroke-width="10" stroke-linejoin="round" mask="url(#hole)"/>'
                 f'<mask id="hole"><rect x="0" y="0" width="400" height="400" fill="#fff"/><circle cx="{c[0]}" cy="{c[1]}" r="17" fill="#000"/></mask>')
        nd = (b[0]+44, b[1]+44)
        dot = {"color": C["node"], "white": C["white"], "ink": C["ink"]}[mode]
        glow = f'<circle cx="{nd[0]:.1f}" cy="{nd[1]:.1f}" r="30" fill="url(#glow)"/>' if mode == "color" else ""
        return inner + glow + f'<circle cx="{nd[0]:.1f}" cy="{nd[1]:.1f}" r="15" fill="{dot}"/>'
    return Mark((0, 0, 330, 330), [(lens, "round"), (handle, "round")], extras, t=50, w=11)

# ---- Stepix: isometric cube + three BOM rows (node + line)
def stepix_mark():
    c, s = (118, 165), 92
    V = [apt(*c, s, -90 + 60*k) for k in range(6)]  # top, upper-right, lower-right, bottom, lower-left, upper-left
    hexd = "M " + " L ".join(f(p) for p in V) + " Z"
    yd = f"M {f(V[5])} L {f(c)} L {f(V[1])} M {f(c)} L {f(V[3])}"
    def extras(mode):
        col = {"color": C["node"], "white": C["white"], "ink": C["ink"]}[mode]
        line = {"color": "url(#g)", "white": C["white"], "ink": C["ink"]}[mode]
        out = []
        for i, yy in enumerate((105, 165, 225)):
            out.append(f'<circle cx="252" cy="{yy}" r="13" fill="{col}"/>'
                       f'<path d="M 280 {yy} L {330 - 18*i} {yy}" stroke="{line}" stroke-width="20" stroke-linecap="round"/>')
        return "".join(out)
    return Mark((-5, 40, 360, 250), [(hexd + " " + yd, "round")], extras, t=34, w=8)

MARKS = {"dz": dz_mark(), "partsfinder": partsfinder_mark(), "stepix": stepix_mark()}

def write(path, s):
    os.makedirs(os.path.dirname(path), exist_ok=True); open(path, "w").write(s)

def png(svg_path, png_path, w):
    subprocess.run(["rsvg-convert", "-w", str(w), svg_path, "-o", png_path], check=True)

# ---------------------------------------------------------------- lockups
def lockup(name, word, sub, mode="color"):
    m = MARKS[name]; x, y, w, h = m.vb
    scale = 120 / h; mw = w*scale
    tcol = (C["deep"] if word.isupper() else C["ink"]) if mode != "white" else C["white"]; scol = C["blue"] if mode != "white" else C["sky"]
    caps = word.isupper()
    wd, ww = text_path(word, 64 if caps else 76, 500 if caps else 700, 0, 0, 0.14 if caps else -0.01)
    sd, sw = text_path(sub, 22, 500, 0, 0, 0.12) if sub else ("", 0)
    tx = mw + 34; total = tx + max(ww, sw) + 6
    inner = m.svg(mode, inner=True)
    texty = 78 if sub else 86
    sub_el = f'<path transform="translate({tx+2} 114)" d="{sd}" fill="{scol}"/>' if sub else ""
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {total:.0f} 130">'
            f'<g transform="translate(0 5) scale({scale:.4f}) translate({-x} {-y})">{inner}</g>'
            f'<path transform="translate({tx} {texty})" d="{wd}" fill="{tcol}"/>{sub_el}</svg>')

def dz_stacked(mode="color"):
    m = MARKS["dz"]; x, y, w, h = m.vb
    col = C["deep"] if mode != "white" else C["white"]
    td, tw = text_path("IT SERVICES", 84, 500, 0, 0, 0.14)
    W = max(w, tw) + 20; X = x + w/2 - W/2
    tx = x + (w - tw) / 2
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{X:.1f} {y} {W:.1f} {h + 130}">{m.svg(mode, inner=True)}'
            f'<path transform="translate({tx:.1f} {y + h + 104})" d="{td}" fill="{col}"/></svg>')

# ---------------------------------------------------------------- app icons
def app_icon(name, core=True):
    m = MARKS[name]
    if not core and name == "stepix":      # small sizes: the cube alone stays readable
        m = Mark((10, 60, 216, 210), m.tubes, "", t=m.t - 6, w=m.w)
    x, y, w, h = m.vb
    S = 1024; pad = (190 if name != "dz" else 150) if core else 90; avail = S - 2*pad
    sc = avail / max(w, h); ox = (S - w*sc)/2; oy = (S - h*sc)/2
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {S} {S}"><defs>'
            f'<linearGradient id="tile" x1="0" y1="0" x2="0.4" y2="1"><stop offset="0" stop-color="#3E8FD6"/>'
            f'<stop offset=".55" stop-color="#2A6DB0"/><stop offset="1" stop-color="#173F66"/></linearGradient></defs>'
            f'<rect x="32" y="32" width="{S-64}" height="{S-64}" rx="220" fill="url(#tile)"/>'
            f'<g transform="translate({ox:.1f} {oy:.1f}) scale({sc:.4f}) translate({-x} {-y})">{m.svg("white", inner=True, core=core)}</g></svg>')

if __name__ == "__main__":
    for n, m in MARKS.items():
        for mode in ("color", "white", "ink"):
            suffix = "" if mode == "color" else f"-{mode}"
            write(f"{OUT}/logos/{n}-mark{suffix}.svg", m.svg(mode))
        write(f"{OUT}/icons/{n}-app-icon.svg", app_icon(n))
        write(f"{OUT}/icons/{n}-app-icon-small.svg", app_icon(n, core=False))
    for mode in ("color", "white"):
        suffix = "" if mode == "color" else "-white"
        write(f"{OUT}/logos/dz-it-services-stacked{suffix}.svg", dz_stacked(mode))
        write(f"{OUT}/logos/dz-it-services-horizontal{suffix}.svg", lockup("dz", "IT SERVICES", "", mode))
        write(f"{OUT}/logos/partsfinder-logo{suffix}.svg", lockup("partsfinder", "Partsfinder", "BY DZ IT SERVICES", mode))
        write(f"{OUT}/logos/stepix-logo{suffix}.svg", lockup("stepix", "Stepix", "BY DZ IT SERVICES", mode))

def exports():
    import shutil
    ic = f"{OUT}/icons"
    for n in MARKS:
        pngs = []
        for s in (16, 24, 32, 48, 64, 128, 256, 512, 1024):
            src = f"{ic}/{n}-app-icon-small.svg" if s <= 48 else f"{ic}/{n}-app-icon.svg"
            p = f"{ic}/png/{n}-{s}.png"; os.makedirs(os.path.dirname(p), exist_ok=True); png(src, p, s)
            if s <= 256: pngs.append(p)
        subprocess.run(["convert", *pngs, f"{ic}/{n}.ico"], check=True)
    for base in ("dz-it-services-stacked", "dz-it-services-horizontal", "partsfinder-logo", "stepix-logo", "dz-mark", "partsfinder-mark", "stepix-mark"):
        os.makedirs(f"{OUT}/logos/png", exist_ok=True)
        png(f"{OUT}/logos/{base}.svg", f"{OUT}/logos/png/{base}.png", 1200)
    # fonts/ and originals/ are kept by hand; see brand/BRAND.md

if __name__ == "__main__":
    exports()
