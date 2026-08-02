# -*- coding: utf-8 -*-
# ASCII SHADER - renders an image as drawn characters, matched by SHAPE.
#
# A luminance ramp (map cell brightness -> one char from " .-=+*%#@") throws away
# everything except average darkness, so edges turn to mush. Instead each cell is
# sampled in a 3x3 grid of regions, giving a 9-component "shape vector", and the
# character whose own ink distribution best matches that vector is chosen. An
# edge running bottom-left to top-right lights up those regions and picks "/";
# a horizontal edge picks "-" or "_"; a vertical one picks "|". Density still
# falls out of it, because a dark cell matches a dense glyph.
# Character vectors are measured from the real stroke geometry, so they stay
# true if the font changes. (Technique after alexharri.com/blog/ascii-rendering.)
# PROCESSOR CONTRACT: closed region(s) in (`crvs`) -> character strokes out.
# Inputs: crvs(list, closed), image(file path), cell(mm character pitch),
#         charset(str, characters allowed - order irrelevant), gamma(tone curve),
#         aspect(row pitch / cell), edge(0-1 shape-vs-density weighting),
#         invert(bool), on(bool bypass)
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

FONTDIR = r'C:\Users\john.chandler\voron_plotter'
if FONTDIR not in sys.path:
    sys.path.append(FONTDIR)
import strokefont
reload(strokefont)

NR = 3          # sampling grid per cell (NR x NR regions -> NR*NR dimensions)


def load_image(path, maxdim):
    try:
        from System.Drawing.Imaging import PixelFormat, ImageLockMode
        from System.Runtime.InteropServices import Marshal
        src = SD.Bitmap(path)
        w = src.Width
        h = src.Height
        f = 1.0
        if w > maxdim or h > maxdim:
            f = float(maxdim) / float(max(w, h))
        tw = int(w * f)
        th = int(h * f)
        if tw < 1:
            tw = 1
        if th < 1:
            th = 1
        conv = SD.Bitmap(tw, th, PixelFormat.Format24bppRgb)
        gfx = SD.Graphics.FromImage(conv)
        gfx.DrawImage(src, 0, 0, tw, th)
        gfx.Dispose()
        src.Dispose()
        data = conv.LockBits(SD.Rectangle(0, 0, tw, th), ImageLockMode.ReadOnly, PixelFormat.Format24bppRgb)
        stride = data.Stride
        nbytes = abs(stride) * th
        buf = System.Array.CreateInstance(System.Byte, nbytes)
        Marshal.Copy(data.Scan0, buf, 0, nbytes)
        conv.UnlockBits(data)
        conv.Dispose()
        return (buf, stride, tw, th)
    except:
        return None


def char_vector(ch, cw, chh, cap):
    """ink density per region for one glyph, measured off its real strokes.
    Returns NR*NR accumulated stroke length, binned over the cell box."""
    bins = [0.0] * (NR * NR)
    polys = strokefont.text(ch, cw * 0.5, chh * 0.18, cap, 0.0, 'center')
    step = 0.08
    for pl in polys:
        for i in range(1, len(pl)):
            ax, ay = pl[i - 1]
            bx, by = pl[i]
            seg = math.sqrt((bx - ax) ** 2 + (by - ay) ** 2)
            n = int(seg / step) + 1
            for k in range(n):
                t = (k + 0.5) / n
                x = ax + (bx - ax) * t
                y = ay + (by - ay) * t
                gx = int(x / cw * NR)
                gy = int(y / chh * NR)
                if gx < 0: gx = 0
                if gx >= NR: gx = NR - 1
                if gy < 0: gy = 0
                if gy >= NR: gy = NR - 1
                bins[gy * NR + gx] += seg / n
    return bins


CELL = float(cell) if cell is not None else 4.0
if CELL < 0.8:
    CELL = 0.8
CHARSET = str(charset) if charset else " .'-_|/\\^=+*ox#%@"
GAM = float(gamma) if gamma is not None else 1.0
if GAM < 0.05:
    GAM = 0.05
ASP = float(aspect) if aspect is not None else 1.35
if ASP < 0.4:
    ASP = 0.4
EDGE = float(edge) if edge is not None else 0.65
if EDGE < 0.0:
    EDGE = 0.0
if EDGE > 1.0:
    EDGE = 1.0
INV = False if invert is None else bool(invert)
ON = True if on is None else bool(on)

IMGPATH = None
if image is not None:
    try:
        IMGPATH = str(image).strip('"')
    except:
        IMGPATH = None

cs = []
if crvs:
    for c in crvs:
        cc = c if isinstance(c, rg.Curve) else rs.coercecurve(c)
        if cc is not None and cc.IsClosed:
            cs.append(cc)

out_crvs = []
info = ''
if not ON:
    out_crvs = cs
    info = '[BYPASSED]'
elif not cs:
    info = 'needs a closed region to fill'
else:
    img = load_image(IMGPATH, 1200) if IMGPATH else None
    if img is None:
        info = 'NO IMAGE (set the image file path)'
    else:
        rowh = CELL * ASP
        cap = CELL * 0.78
        # ---- character vectors, measured once from the real strokes ----
        # SHAPE is normalised (divide by the glyph's own peak) so a thin "/"
        # competes with a dense "@" on distribution rather than being drowned
        # out by it; DENSITY is kept separately and reintroduced by `edge`.
        chars = []
        shapes = []
        dens = []
        dmax = 0.0
        for ch in CHARSET:
            if ch == ' ':
                continue
            v = char_vector(ch, CELL, rowh, cap)
            mx = 0.0
            tot = 0.0
            for q in v:
                tot += q
                if q > mx:
                    mx = q
            if mx <= 0.0:
                continue
            chars.append(ch)
            shapes.append([q / mx for q in v])
            m = tot / len(v)
            dens.append(m)
            if m > dmax:
                dmax = m
        if dmax <= 0.0:
            dmax = 1.0
        for i in range(len(dens)):
            dens[i] = dens[i] / dmax

        bb = rg.BoundingBox.Empty
        for c in cs:
            bb.Union(c.GetBoundingBox(True))
        x0 = bb.Min.X
        y0 = bb.Min.Y
        wid = bb.Max.X - x0
        hei = bb.Max.Y - y0
        idw = wid
        idh = hei
        ia = float(img[2]) / float(img[3])
        ba = wid / hei if hei > 0.001 else 1.0
        if ia > ba:
            idh = wid / ia
        else:
            idw = hei * ia
        ix0 = x0 + (wid - idw) / 2.0
        iy0 = y0 + (hei - idh) / 2.0
        ncol = int(wid / CELL)
        nrow = int(hei / rowh)
        plane = rg.Plane.WorldXY
        tol = 0.001
        n_ch = 0
        for r in range(nrow):
            cy = y0 + r * rowh
            for cnum in range(ncol):
                cx = x0 + cnum * CELL
                ctr = rg.Point3d(cx + CELL * 0.5, cy + rowh * 0.5, 0)
                hits = 0
                for c in cs:
                    if c.Contains(ctr, plane, tol) == rg.PointContainment.Inside:
                        hits += 1
                if (hits % 2) == 0:
                    continue
                # ---- sample this cell into the same NR x NR regions ----
                sv = []
                tot = 0.0
                for gy in range(NR):
                    for gx in range(NR):
                        acc = 0.0
                        for sy in range(2):
                            for sx in range(2):
                                x = cx + CELL * (gx + (sx + 0.5) / 2.0) / NR
                                y = cy + rowh * (gy + (sy + 0.5) / 2.0) / NR
                                u = (x - ix0) / idw
                                v2 = (y - iy0) / idh
                                if u < 0.0 or u > 1.0 or v2 < 0.0 or v2 > 1.0:
                                    acc += 1.0
                                    continue
                                px = int(u * (img[2] - 1))
                                py = int((1.0 - v2) * (img[3] - 1))
                                idx = py * img[1] + px * 3
                                b = img[0][idx]
                                g = img[0][idx + 1]
                                rr = img[0][idx + 2]
                                acc += (0.299 * rr + 0.587 * g + 0.114 * b) / 255.0
                        lum = acc / 4.0
                        ink = 1.0 - lum
                        if INV:
                            ink = lum
                        ink = math.pow(ink, GAM)
                        sv.append(ink)
                        tot += ink
                mean = tot / (NR * NR)
                if mean < 0.02:
                    continue                       # effectively blank
                mx = 0.0
                for q in sv:
                    if q > mx:
                        mx = q
                if mx <= 0.0:
                    continue
                sh = [q / mx for q in sv]
                # `edge` trades structure against tone: 1 = pick purely on the
                # shape of the cell, 0 = pick purely on how dark it is (the old
                # luminance-ramp behaviour). The density term is weighted by the
                # number of regions so the two halves are comparable.
                best = -1
                bestd = None
                for ci in range(len(chars)):
                    d = 0.0
                    csh = shapes[ci]
                    for i in range(len(sh)):
                        dd = sh[i] - csh[i]
                        d += dd * dd
                    dd2 = mean - dens[ci]
                    d = EDGE * d + (1.0 - EDGE) * (NR * NR) * dd2 * dd2
                    if bestd is None or d < bestd:
                        bestd = d
                        best = ci
                ch = chars[best]
                for pl in strokefont.text(ch, cx + CELL * 0.5, cy + rowh * 0.18, cap, 0.0, 'center'):
                    lp = List[rg.Point3d]()
                    for q in pl:
                        lp.Add(rg.Point3d(q[0], q[1], 0))
                    if lp.Count > 1:
                        out_crvs.append(rg.PolylineCurve(lp))
                n_ch += 1
        info = '%d chars on %dx%d grid, cell %.1fmm, %d-dim shape match, edge %.2f, set "%s", %d strokes' % (
            n_ch, ncol, nrow, CELL, NR * NR, EDGE, CHARSET, len(out_crvs))

print(info)
