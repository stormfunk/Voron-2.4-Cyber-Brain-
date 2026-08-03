# -*- coding: utf-8 -*-
# COLOUR SEPARATION - an image split into one plottable pass per pen.
#
# Each pen lays a translucent film of its own ink. On white paper that is
# SUBTRACTIVE: a pen does not add its colour, it removes the rest. So the
# separation works in absorption space (absorb = 1 - colour), where laying
# several inks on the same spot adds their absorptions together, and the job is
# to find how much of each ink reproduces the pixel:
#
#     minimise | sum_i ( x_i * absorb_i ) - absorb_target |^2 ,  0 <= x_i <= 1
#
# solved per cell by a few sweeps of coordinate descent (fast, always in range,
# and needs no matrix code). x_i is that pen's coverage 0..1 for the cell.
#
# Coverage is then drawn as a halftone: a dot whose AREA is proportional to
# coverage, on a grid rotated to that pen's own screen angle. Rotating each
# pen's screen is what stops the passes forming moire against each other - the
# same reason process printing uses 15/75/0/45 degrees.
#
# Inks are whatever pens you actually own: wire the colour swatches from the pen
# legend into `inks` and the matching pen numbers into `pens`. Separation is
# against those real colours, so a black/red/green set separates as a
# black/red/green set rather than pretending to be CMYK.
#
# GENERATOR CONTRACT: closed region(s) in (`crvs`) -> `out_crvs` + `out_pens`.
# Inputs: crvs(list, closed), image(file path), inks(list of colours),
#         pens(list of ints, parallel to inks), cell(mm halftone pitch),
#         angles(list of degrees, optional - defaults to process-style screens),
#         gamma(tone curve), max_ink(cap on total coverage per cell),
#         method(0 dots / 1 line screen), on(bool bypass)
import Rhino
import Rhino.Geometry as rg
import rhinoscriptsyntax as rs
import scriptcontext as sc
import math
import sys
import System
import System.Drawing as SD
from System.Collections.Generic import List
try:
    sc.doc = ghdoc
except:
    pass

# process-style screen angles, extended for up to 8 inks
DEF_ANGLES = [15.0, 75.0, 0.0, 45.0, 30.0, 60.0, 7.5, 82.5]


def load_rgb(path, maxdim):
    """image -> (bytes, stride, w, h) for point sampling"""
    try:
        from System.Drawing.Imaging import PixelFormat, ImageLockMode
        from System.Runtime.InteropServices import Marshal
        src = SD.Bitmap(path)
        w = src.Width; h = src.Height
        f = 1.0
        if w > maxdim or h > maxdim:
            f = float(maxdim) / float(max(w, h))
        tw = int(w * f); th = int(h * f)
        if tw < 1: tw = 1
        if th < 1: th = 1
        conv = SD.Bitmap(tw, th, PixelFormat.Format24bppRgb)
        g = SD.Graphics.FromImage(conv)
        g.InterpolationMode = SD.Drawing2D.InterpolationMode.HighQualityBilinear
        g.DrawImage(src, 0, 0, tw, th)
        g.Dispose(); src.Dispose()
        d = conv.LockBits(SD.Rectangle(0, 0, tw, th), ImageLockMode.ReadOnly,
                          PixelFormat.Format24bppRgb)
        stride = d.Stride
        nb = abs(stride) * th
        buf = System.Array.CreateInstance(System.Byte, nb)
        Marshal.Copy(d.Scan0, buf, 0, nb)
        conv.UnlockBits(d); conv.Dispose()
        return (buf, stride, tw, th)
    except:
        return None


def as_rgb(c):
    """a GH colour, a System.Drawing.Color, or '#rrggbb' -> (r, g, b) floats"""
    try:
        return (float(c.R), float(c.G), float(c.B))
    except:
        pass
    try:
        v = c.Value
        return (float(v.R), float(v.G), float(v.B))
    except:
        pass
    try:
        s = str(c).strip().lstrip('#')
        if len(s) == 6:
            return (float(int(s[0:2], 16)), float(int(s[2:4], 16)), float(int(s[4:6], 16)))
    except:
        pass
    return None


def spiral_dot(cx, cy, r, w):
    """a filled disc drawn the way a pen fills one: a spiral in from the rim,
    stepping by the pen's own width so the ink just meets"""
    if r <= w * 0.55:
        return [(cx - r * 0.5, cy), (cx + r * 0.5, cy)]
    pts = []
    turns = int(r / max(w, 0.05)) + 1
    steps = int(2.0 * math.pi * r / max(w * 0.9, 0.05)) + 8
    if steps > 900:
        steps = 900
    for i in range(steps + 1):
        t = float(i) / steps
        rr = r * (1.0 - t)
        a = 2.0 * math.pi * turns * t
        pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
    return pts


CELL = float(cell) if cell is not None else 3.0
if CELL < 0.4:
    CELL = 0.4
GAM = float(gamma) if gamma is not None else 1.0
if GAM < 0.05:
    GAM = 0.05
MAXINK = float(max_ink) if max_ink is not None else 2.2
if MAXINK < 0.2:
    MAXINK = 0.2
METHOD = int(method) if method is not None else 0
ON = True if on is None else bool(on)

IMG = None
if image is not None:
    try:
        IMG = str(image).strip('"')
    except:
        IMG = None

# pen widths drive how tightly each dot is filled
widths = {}
try:
    import json
    _fh = open(r'C:\Users\john.chandler\voron_plotter\pen_widths.json')
    widths = json.loads(_fh.read())
    _fh.close()
except:
    widths = {}

cs = []
if crvs:
    for c in crvs:
        cc = c if isinstance(c, rg.Curve) else rs.coercecurve(c)
        if cc is not None and cc.IsClosed:
            cs.append(cc)

INKS = []
PENS = []
if inks:
    for i in range(len(inks)):
        rgbv = as_rgb(inks[i])
        if rgbv is None:
            continue
        pnum = 1
        if pens and i < len(pens) and pens[i] is not None:
            try:
                pnum = int(pens[i])
            except:
                pnum = 1
        INKS.append(rgbv)
        PENS.append(pnum)
ANG = []
if angles:
    for a in angles:
        try:
            ANG.append(float(a))
        except:
            pass

out_crvs = []
out_pens = []
info = ''
if not ON:
    info = '[BYPASSED]'
elif not cs:
    info = 'needs a closed region to separate into'
elif not INKS:
    info = 'wire pen colours into `inks` (and matching pen numbers into `pens`)'
elif not IMG:
    info = 'no image'
else:
    img = load_rgb(IMG, 1400)
    if img is None:
        info = 'could not read the image'
    else:
        ibuf, istride, iw, ih = img
        nink = len(INKS)
        # ink absorption vectors, 0..1 per channel
        A = []
        for (r, g, b) in INKS:
            A.append((1.0 - r / 255.0, 1.0 - g / 255.0, 1.0 - b / 255.0))
        AA = []
        for a in A:
            AA.append(a[0]*a[0] + a[1]*a[1] + a[2]*a[2])
        bb = rg.BoundingBox.Empty
        for c in cs:
            bb.Union(c.GetBoundingBox(True))
        x0 = bb.Min.X; y0 = bb.Min.Y
        wid = bb.Max.X - x0; hei = bb.Max.Y - y0
        # fit the image into the region, preserving aspect
        idw = wid; idh = hei
        ia = float(iw) / float(ih)
        ba = wid / hei if hei > 0.001 else 1.0
        if ia > ba:
            idh = wid / ia
        else:
            idw = hei * ia
        ix0 = x0 + (wid - idw) / 2.0
        iy0 = y0 + (hei - idh) / 2.0
        plane = rg.Plane.WorldXY
        tol = 0.001
        diag = math.sqrt(wid*wid + hei*hei)
        ccx = x0 + wid / 2.0; ccy = y0 + hei / 2.0
        counts = [0] * nink
        cov_sum = [0.0] * nink
        ncell = 0
        lut = {}
        for pi in range(nink):
            ang = math.radians(ANG[pi] if pi < len(ANG) else DEF_ANGLES[pi % 8])
            ca = math.cos(ang); sa = math.sin(ang)
            pw = 0.3
            w = widths.get(str(PENS[pi]))
            if w:
                pw = float(w)
            nu = int(diag / CELL) + 2
            for iu in range(-nu, nu + 1):
                for iv in range(-nu, nu + 1):
                    u = iu * CELL; v = iv * CELL
                    px = ccx + u * ca - v * sa
                    py = ccy + u * sa + v * ca
                    if px < x0 or px > x0 + wid or py < y0 or py > y0 + hei:
                        continue
                    pt = rg.Point3d(px, py, 0)
                    hits = 0
                    for c in cs:
                        if c.Contains(pt, plane, tol) == rg.PointContainment.Inside:
                            hits += 1
                    if (hits % 2) == 0:
                        continue
                    uu = (px - ix0) / idw
                    vv = (py - iy0) / idh
                    if uu < 0.0 or uu > 1.0 or vv < 0.0 or vv > 1.0:
                        continue
                    sxp = int(uu * (iw - 1))
                    syp = int((1.0 - vv) * (ih - 1))
                    idx = syp * istride + sxp * 3
                    bch = ibuf[idx]; gch = ibuf[idx + 1]; rch = ibuf[idx + 2]
                    # Solve once per quantised colour, not once per cell. Real
                    # images use a few hundred distinct 4-bit colours, so this
                    # turns tens of thousands of solves into a few hundred and
                    # buys the sweep count needed for convergence.
                    ckey = (rch >> 4) * 289 + (gch >> 4) * 17 + (bch >> 4)
                    xs = lut.get(ckey)
                    if xs is None:
                        t0 = 1.0 - rch / 255.0
                        t1 = 1.0 - gch / 255.0
                        t2 = 1.0 - bch / 255.0
                        if GAM != 1.0:
                            t0 = math.pow(t0, GAM); t1 = math.pow(t1, GAM); t2 = math.pow(t2, GAM)
                        xs = [0.0] * nink
                        # 16 sweeps, inks in the order given. A near-black ink
                        # correlates with every other, so 4 sweeps leaves black
                        # over-assigned (pure red came out 23% black). Reordering
                        # to solve pale inks first fixes that but then builds
                        # black out of red+green instead of using the black pen -
                        # more ink, muddier. Converging properly fixes both.
                        for _sweep in range(16):
                            for j in range(nink):
                                if AA[j] < 1e-9:
                                    continue
                                r0 = t0; r1 = t1; r2 = t2
                                for m2 in range(nink):
                                    if m2 == j:
                                        continue
                                    r0 -= xs[m2] * A[m2][0]
                                    r1 -= xs[m2] * A[m2][1]
                                    r2 -= xs[m2] * A[m2][2]
                                xj = (r0*A[j][0] + r1*A[j][1] + r2*A[j][2]) / AA[j]
                                if xj < 0.0: xj = 0.0
                                if xj > 1.0: xj = 1.0
                                xs[j] = xj
                        tot = 0.0
                        for q in xs:
                            tot += q
                        if tot > MAXINK and tot > 0.0:
                            sc2 = MAXINK / tot
                            for j in range(nink):
                                xs[j] *= sc2
                        lut[ckey] = xs
                    x = xs[pi]
                    if pi == 0:
                        ncell += 1
                    if x < 0.04:
                        continue
                    cov_sum[pi] += x
                    counts[pi] += 1
                    if METHOD == 1:
                        # line screen: a dash across the cell, length by coverage
                        half = CELL * 0.5 * x
                        lp = List[rg.Point3d]()
                        lp.Add(rg.Point3d(px - half * ca, py - half * sa, 0))
                        lp.Add(rg.Point3d(px + half * ca, py + half * sa, 0))
                        out_crvs.append(rg.PolylineCurve(lp))
                        out_pens.append(PENS[pi])
                    else:
                        # dot AREA tracks coverage, so radius goes as its root
                        rad = CELL * 0.5 * math.sqrt(x)
                        pts = spiral_dot(px, py, rad, pw)
                        lp = List[rg.Point3d]()
                        for (qx, qy) in pts:
                            lp.Add(rg.Point3d(qx, qy, 0))
                        if lp.Count > 1:
                            out_crvs.append(rg.PolylineCurve(lp))
                            out_pens.append(PENS[pi])
        tl = 0.0
        for c in out_crvs:
            tl += c.GetLength()
        bits = ['%d strokes, %.2fm of line' % (len(out_crvs), tl / 1000.0)]
        bits.append('%d cells at %.1fmm' % (ncell, CELL))
        bits.append('method %s' % ('line screen' if METHOD == 1 else 'halftone dots'))
        for pi in range(nink):
            avg = (cov_sum[pi] / counts[pi]) if counts[pi] else 0.0
            bits.append('pen%d rgb(%d,%d,%d) @%.0fdeg: %d marks, mean cover %.0f%%' % (
                PENS[pi], int(INKS[pi][0]), int(INKS[pi][1]), int(INKS[pi][2]),
                ANG[pi] if pi < len(ANG) else DEF_ANGLES[pi % 8], counts[pi], avg * 100.0))
        info = ' | '.join(bits)

print(info)
