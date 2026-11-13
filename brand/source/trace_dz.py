"""Traces the original DZ raster logo into clean vector paths (potracer).

Writes dz_mark_paths.json (used by build_brand.py). Needs: pip install potracer pillow numpy.
The node disc, its cyan dot and the trace line are drawn on top as exact circles and a line.
"""
import numpy as np, potrace
from PIL import Image, ImageFilter
import os
HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, '..', 'originals', 'dz-logo-original.png')
S = 4  # upscale factor

def mask(v, blur=1.2):
    """v: float 0..1 coverage per pixel (keeps the anti-aliasing); upscale, smooth, threshold."""
    im = Image.fromarray((np.clip(v, 0, 1)*255).astype(np.uint8), 'L').resize((v.shape[1]*S, v.shape[0]*S), Image.BICUBIC)
    im = im.filter(ImageFilter.GaussianBlur(S*blur))
    return np.array(im) > 127

def to_path(bm, tol=0.4, alphamax=1.1, turd=60):
    plist = potrace.Bitmap(~bm).trace(   # potracer traces the False pixels
        turdsize=turd, turnpolicy=potrace.POTRACE_TURNPOLICY_MINORITY,
                                      alphamax=alphamax, opticurve=True, opttolerance=tol)
    out = []
    for curve in plist:
        sp = curve.start_point; out.append(f"M{sp.x/S:.2f} {sp.y/S:.2f}")
        for seg in curve.segments:
            if seg.is_corner:
                out.append(f"L{seg.c.x/S:.2f} {seg.c.y/S:.2f}L{seg.end_point.x/S:.2f} {seg.end_point.y/S:.2f}")
            else:
                out.append(f"C{seg.c1.x/S:.2f} {seg.c1.y/S:.2f} {seg.c2.x/S:.2f} {seg.c2.y/S:.2f} {seg.end_point.x/S:.2f} {seg.end_point.y/S:.2f}")
        out.append("Z")
    return "".join(out)

a = np.array(Image.open(SRC).convert('RGBA')).astype(int)
r, g, b, al = a[..., 0], a[..., 1], a[..., 2], a[..., 3]
white = (al > 128) & (r + g + b > 600)
shape = (al > 128)                       # everything opaque: tubes + white cores + node
blue = shape & ~white
mn = np.minimum(np.minimum(r, g), b)
v_blue = (al/255.0) * np.clip((235 - mn) / 150.0, 0, 1)
v_shape = al/255.0
# white inner lines; the glow around the node is neither blue nor white, so it drops out
v_white = (al/255.0) * np.clip((mn - 150) / 80.0, 0, 1)
v_shape = np.clip(v_blue + v_white, 0, 1)
NODE_C, NODE_R = (566.0, 273.0), 26.0     # measured on the original; drawn as exact circles on top
import json, sys
out = sys.argv[1] if len(sys.argv) > 1 else "dz_mark_paths.json"
json.dump({"source": "originals/dz-logo-original.png", "tubes": to_path(mask(v_blue), tol=0.8),
           "silhouette": to_path(mask(v_shape), tol=0.8), "node": {"c": NODE_C, "r": NODE_R, "dot": 11, "trace_from": [508, 272]}},
          open(out, "w"))

