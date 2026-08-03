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


def load_source(path, maxdim):
    """the image, scaled so its longest side is at most maxdim"""
    try:
        src = SD.Bitmap(path)
        w = src.Width
        h = src.Height
        if w <= maxdim and h <= maxdim:
            return src
        f = float(maxdim) / float(max(w, h))
        tw = int(w * f)
        th = int(h * f)
        if tw < 1:
            tw = 1
        if th < 1:
            th = 1
        conv = SD.Bitmap(tw, th, SD.Imaging.PixelFormat.Format24bppRgb)
        gfx = SD.Graphics.FromImage(conv)
        gfx.InterpolationMode = SD.Drawing2D.InterpolationMode.HighQualityBilinear
        gfx.DrawImage(src, 0, 0, tw, th)
        gfx.Dispose()
        src.Dispose()
        return conv
    except:
        return None


def region_grid(bmp, gw, gh, dx, dy, dw, dh):
    """Resample the image straight onto the region grid, once, in native code.

    The old path read 4 subsamples per region (36 image reads per cell, plus
    coordinate math and tuple lookups in the innermost loop) which cost 6.6s of
    this component's 12.7s. At normal cell sizes a region spans barely one image
    pixel, so that subsampling was mostly re-reading the same pixel anyway.
    Letting GDI+ scale the image to exactly one pixel per region does the
    filtering properly AND leaves one array read per region.
    Anything outside the image reads white, which is what the old bounds check
    fell back to."""
    try:
        from System.Drawing.Imaging import PixelFormat, ImageLockMode
        from System.Runtime.InteropServices import Marshal
        grid = SD.Bitmap(gw, gh, PixelFormat.Format24bppRgb)
        gfx = SD.Graphics.FromImage(grid)
        gfx.Clear(SD.Color.White)
        gfx.InterpolationMode = SD.Drawing2D.InterpolationMode.HighQualityBilinear
        gfx.PixelOffsetMode = SD.Drawing2D.PixelOffsetMode.HighQuality
        gfx.DrawImage(bmp, SD.RectangleF(dx, dy, dw, dh))
        gfx.Dispose()
        data = grid.LockBits(SD.Rectangle(0, 0, gw, gh), ImageLockMode.ReadOnly,
                             PixelFormat.Format24bppRgb)
        stride = data.Stride
        nbytes = abs(stride) * gh
        buf = System.Array.CreateInstance(System.Byte, nbytes)
        Marshal.Copy(data.Scan0, buf, 0, nbytes)
        grid.UnlockBits(data)
        grid.Dispose()
        return (buf, stride)
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
    bmp = load_source(IMGPATH, 1600) if IMGPATH else None
    if bmp is None:
        info = 'NO IMAGE (set the image file path)'
    else:
        rowh = CELL * ASP
        cap = CELL * 0.78
        # ---- character coverage vectors, measured once from the real strokes ----
        # Both the cell and the glyph are described in ABSOLUTE terms: how much
        # ink sits in each region, 0..1. Do not normalise the cell by its own
        # peak - that throws away how dark the cell is, so every smooth region
        # of a photo becomes "uniformly full" and matches whichever glyph covers
        # all nine bins (in practice 'O', for every single cell). Comparing
        # absolute against absolute makes a dark cell pick a dense glyph and a
        # light one pick a sparse glyph, with the distribution still deciding
        # between glyphs of similar weight.
        chars = []
        raw = []
        gmax = 0.0
        dropped = []
        for ch in CHARSET:
            if ch == ' ':
                continue
            v = char_vector(ch, CELL, rowh, cap)
            tot = 0.0
            for q in v:
                tot += q
            if tot <= 0.0:
                dropped.append(ch)      # no glyph in the font - cannot be drawn
                continue
            chars.append(ch)
            raw.append(v)
            # calibrate against the DENSEST glyph's mean coverage, so the set
            # spans 0..1 the same way ink does. Scaling by the largest single
            # bin instead leaves every coverage value well below typical ink,
            # and then the densest glyph is nearest for every cell.
            m = tot / len(v)
            if m > gmax:
                gmax = m
        if gmax <= 0.0:
            gmax = 1.0
        shapes = []
        covsq = []
        dens = []
        for v in raw:
            cov = [q / gmax for q in v]
            ns = 0.0
            tot = 0.0
            for q in cov:
                ns += q * q
                tot += q
            shapes.append(cov)
            covsq.append(ns)
            dens.append(tot / len(cov))
        nch = len(chars)

        bb = rg.BoundingBox.Empty
        for c in cs:
            bb.Union(c.GetBoundingBox(True))
        x0 = bb.Min.X
        y0 = bb.Min.Y
        wid = bb.Max.X - x0
        hei = bb.Max.Y - y0
        idw = wid
        idh = hei
        ia = float(bmp.Width) / float(bmp.Height)
        ba = wid / hei if hei > 0.001 else 1.0
        if ia > ba:
            idh = wid / ia
        else:
            idw = hei * ia
        ix0 = x0 + (wid - idw) / 2.0
        iy0 = y0 + (hei - idh) / 2.0
        ncol = int(wid / CELL)
        nrow = int(hei / rowh)
        if ncol < 1:
            ncol = 1
        if nrow < 1:
            nrow = 1

        # one grid pixel per sampling region, image placed in its fitted rect.
        # grid row 0 is the TOP, so world-y (which runs up) is flipped on read.
        GW = ncol * NR
        GH = nrow * NR
        dx = (ix0 - x0) / CELL * NR
        dw = idw / CELL * NR
        jh = idh / rowh * NR
        j0 = (iy0 - y0) / rowh * NR
        dy = GH - (j0 + jh)
        grid = region_grid(bmp, GW, GH, dx, dy, dw, jh)
        bmp.Dispose()
        if grid is None:
            info = 'image resample failed'
        else:
            gbuf = grid[0]
            gstride = grid[1]

            # ---- auto-levels ----
            # Luminance weights red at 0.299, so a saturated red field reads as
            # "dark" (ink ~0.66) even though it is visually bright. An image like
            # a red sky then lands entirely in the top of the ink range and every
            # cell matches the densest glyph - the charset collapses to one
            # character. Stretch the ink range actually present onto 0..1 so the
            # whole set gets used. Measured only inside the image's own rect, so
            # the white margin around it cannot drag the low end down.
            # gamma still applies on top of this.
            hbin = [0] * 256
            c_lo = int(dx)
            c_hi = int(dx + dw)
            r_lo = int(dy)
            r_hi = int(dy + jh)
            if c_lo < 0: c_lo = 0
            if r_lo < 0: r_lo = 0
            if c_hi > GW: c_hi = GW
            if r_hi > GH: r_hi = GH
            nsamp = 0
            for rr2 in range(r_lo, r_hi, 2):
                ro = rr2 * gstride
                for cc2 in range(c_lo, c_hi, 2):
                    idx = ro + cc2 * 3
                    lum = (0.114 * gbuf[idx] + 0.587 * gbuf[idx + 1]
                           + 0.299 * gbuf[idx + 2]) * 0.00392156862745098
                    ink0 = lum if INV else 1.0 - lum
                    b2 = int(ink0 * 255.0)
                    if b2 < 0: b2 = 0
                    if b2 > 255: b2 = 255
                    hbin[b2] += 1
                    nsamp += 1
            lo = 0.0
            hi = 1.0
            if nsamp > 0:
                cut = int(nsamp * 0.01)
                acc = 0
                for b2 in range(256):
                    acc += hbin[b2]
                    if acc > cut:
                        lo = b2 / 255.0
                        break
                acc = 0
                for b2 in range(255, -1, -1):
                    acc += hbin[b2]
                    if acc > cut:
                        hi = b2 / 255.0
                        break
            if hi - lo < 0.05:          # near-flat image: leave it alone
                lo = 0.0
                hi = 1.0
            inv_span = 1.0 / (hi - lo)

            plane = rg.Plane.WorldXY
            tol = 0.001
            n_ch = 0
            flat = GAM == 1.0
            sv = [0.0] * (NR * NR)
            for r in range(nrow):
                cy = y0 + r * rowh
                base_j = r * NR
                for cnum in range(ncol):
                    cx = x0 + cnum * CELL
                    ctr = rg.Point3d(cx + CELL * 0.5, cy + rowh * 0.5, 0)
                    hits = 0
                    for c in cs:
                        if c.Contains(ctr, plane, tol) == rg.PointContainment.Inside:
                            hits += 1
                    if (hits % 2) == 0:
                        continue
                    # ---- read this cell's NR x NR regions, one array hit each ----
                    tot = 0.0
                    col0 = cnum * NR
                    for gy in range(NR):
                        ro = (GH - 1 - (base_j + gy)) * gstride + col0 * 3
                        gb = gy * NR
                        for gx in range(NR):
                            idx = ro + gx * 3
                            lum = (0.114 * gbuf[idx] + 0.587 * gbuf[idx + 1]
                                   + 0.299 * gbuf[idx + 2]) * 0.00392156862745098
                            ink = lum if INV else 1.0 - lum
                            ink = (ink - lo) * inv_span
                            if ink < 0.0:
                                ink = 0.0
                            elif ink > 1.0:
                                ink = 1.0
                            if not flat:
                                ink = math.pow(ink, GAM)
                            sv[gb + gx] = ink
                            tot += ink
                    mean = tot / (NR * NR)
                    if mean < 0.02:
                        continue                   # effectively blank
                    # `edge` trades structure against tone: 1 = match the full
                    # spatial distribution, 0 = match only overall darkness (the
                    # plain luminance ramp). Expanding |sv-cov|^2 to
                    # |sv|^2 - 2.sv.cov + |cov|^2 lets |sv|^2, constant across
                    # candidates, drop out of the argmin - leaving a dot product.
                    best = 0
                    bestd = None
                    dw2 = (1.0 - EDGE) * (NR * NR)
                    for ci in range(nch):
                        csh = shapes[ci]
                        dot = (sv[0] * csh[0] + sv[1] * csh[1] + sv[2] * csh[2]
                               + sv[3] * csh[3] + sv[4] * csh[4] + sv[5] * csh[5]
                               + sv[6] * csh[6] + sv[7] * csh[7] + sv[8] * csh[8])
                        dd2 = mean - dens[ci]
                        d = EDGE * (covsq[ci] - 2.0 * dot) + dw2 * dd2 * dd2
                        if bestd is None or d < bestd:
                            bestd = d
                            best = ci
                    _hist[chars[best]] = _hist.get(chars[best], 0) + 1
                    for pl in strokefont.text(chars[best], cx + CELL * 0.5,
                                              cy + rowh * 0.18, cap, 0.0, 'center'):
                        lp = List[rg.Point3d]()
                        for q in pl:
                            lp.Add(rg.Point3d(q[0], q[1], 0))
                        if lp.Count > 1:
                            out_crvs.append(rg.PolylineCurve(lp))
                    n_ch += 1
            info = '%d chars on %dx%d grid, cell %.1fmm, %d-dim shape match, edge %.2f, %d glyphs, %d strokes | auto-levels %.2f-%.2f' % (
                n_ch, ncol, nrow, CELL, NR * NR, EDGE, nch, len(out_crvs), lo, hi)
            if dropped:
                info += ' | NOT IN FONT, ignored: %s' % ''.join(dropped)

print(info)
