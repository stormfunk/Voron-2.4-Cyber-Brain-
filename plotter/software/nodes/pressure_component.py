# PRESSURE processor - writes the PRESSURE CHANNEL into curves.
#
# HOW PRESSURE TRAVELS: a point's Z coordinate is its pen-pressure offset in mm.
# NEGATIVE Z = press harder (the spring mount compresses further). PLACE scales
# XY only, so Z survives fitting; GCODE adds it to the draw height when it emits
# each move. Because it rides on the geometry itself it survives resampling and
# chaining - stack several PRESSURE blocks and their effects ADD.
#
# Modes:
#   0 curvature - press harder through tight turns (calligraphic weight)
#   1 proximity - press harder where strokes crowd together (builds density)
#   2 image     - press harder where the picture is dark (photographic tone)
#   3 noise     - organic drifting weight
# PROCESSOR CONTRACT: curves in (`crvs`) -> same curves, pressure written.
# Inputs: crvs(list), mode(0-3), amount(mm of extra press at full strength),
#         detail(mm, resample spacing - how finely pressure can vary),
#         scale(mm, feature size for noise / search radius for proximity),
#         image(file path, mode 2), invert(bool), on(bool bypass)
import Rhino
import Rhino.Geometry as rg
import rhinoscriptsyntax as rs
import scriptcontext as sc
import math
import System
import System.Drawing as SD
from System.Collections.Generic import List
try:
    sc.doc = ghdoc
except:
    pass


def lattice(ix, iy, sd):
    n = (ix * 73856093) ^ (iy * 19349663) ^ (sd * 83492791)
    n = n & 0x7FFFFFFF
    n = (n * 1103515245 + 12345) & 0x7FFFFFFF
    return (n % 65536) / 65535.0


def vnoise(x, y, sd):
    ix = int(math.floor(x))
    iy = int(math.floor(y))
    fx = x - ix
    fy = y - iy
    ux = fx * fx * (3.0 - 2.0 * fx)
    uy = fy * fy * (3.0 - 2.0 * fy)
    v00 = lattice(ix, iy, sd)
    v10 = lattice(ix + 1, iy, sd)
    v01 = lattice(ix, iy + 1, sd)
    v11 = lattice(ix + 1, iy + 1, sd)
    a = v00 + (v10 - v00) * ux
    b = v01 + (v11 - v01) * ux
    return a + (b - a) * uy


def load_image(path, maxdim):
    """-> (byte buffer, stride, w, h) of a 24bpp copy, or None.
    LockBits + direct indexing: GetPixel per sample would be far too slow."""
    try:
        from System.Drawing.Imaging import PixelFormat, ImageLockMode
        from System.Runtime.InteropServices import Marshal
        src = SD.Bitmap(path)
        w = src.Width
        h = src.Height
        sc_f = 1.0
        if w > maxdim or h > maxdim:
            sc_f = float(maxdim) / float(max(w, h))
        tw = int(w * sc_f)
        th = int(h * sc_f)
        if tw < 1:
            tw = 1
        if th < 1:
            th = 1
        conv = SD.Bitmap(tw, th, PixelFormat.Format24bppRgb)
        gfx = SD.Graphics.FromImage(conv)
        gfx.DrawImage(src, 0, 0, tw, th)
        gfx.Dispose()
        src.Dispose()
        rect = SD.Rectangle(0, 0, tw, th)
        data = conv.LockBits(rect, ImageLockMode.ReadOnly, PixelFormat.Format24bppRgb)
        stride = data.Stride
        nbytes = abs(stride) * th
        buf = System.Array.CreateInstance(System.Byte, nbytes)
        Marshal.Copy(data.Scan0, buf, 0, nbytes)
        conv.UnlockBits(data)
        conv.Dispose()
        return (buf, stride, tw, th)
    except:
        return None


MODE = int(mode) if mode is not None else 0
AMT = float(amount) if amount is not None else 0.5
DET = float(detail) if detail is not None else 1.0
if DET < 0.2:
    DET = 0.2
SCL = float(scale) if scale is not None else 40.0
if SCL < 0.5:
    SCL = 0.5
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
        if cc is not None:
            cs.append(cc)

out_crvs = []
info = ''
if not ON:
    out_crvs = cs
    info = '[BYPASSED]'
elif cs:
    # 1) resample every curve so pressure can vary along it
    polys = []
    for c in cs:
        L = c.GetLength()
        n = int(L / DET)
        if n < 1:
            n = 1
        ts = c.DivideByCount(n, True)
        pl = []
        if ts is None:
            pl.append(c.PointAtStart)
            pl.append(c.PointAtEnd)
            polys.append((c, pl, None))
        else:
            tl = []
            for t in ts:
                pl.append(c.PointAt(t))
                tl.append(t)
            polys.append((c, pl, tl))

    bb = rg.BoundingBox.Empty
    for item in polys:
        for p in item[1]:
            bb.Union(p)

    img = None
    imgnote = ''
    if MODE == 2:
        if IMGPATH:
            img = load_image(IMGPATH, 1400)
            if img is None:
                imgnote = ' (IMAGE FAILED TO LOAD)'
        else:
            imgnote = ' (NO IMAGE PATH)'
    ox = bb.Min.X
    oy = bb.Min.Y
    bw = bb.Max.X - ox
    bh = bb.Max.Y - oy
    if bw < 1e-6:
        bw = 1.0
    if bh < 1e-6:
        bh = 1.0
    dw = bw
    dh = bh
    if img is not None:
        ia = float(img[2]) / float(img[3])
        ba = bw / bh
        if ia > ba:
            dw = bw
            dh = bw / ia
        else:
            dh = bh
            dw = bh * ia
    ix0 = ox + (bw - dw) / 2.0
    iy0 = oy + (bh - dh) / 2.0

    # 2) proximity mode needs a spatial index of every point
    phash = {}
    if MODE == 1:
        for ci in range(len(polys)):
            for p in polys[ci][1]:
                key = (int(p.X / SCL), int(p.Y / SCL))
                if key not in phash:
                    phash[key] = []
                phash[key].append((p.X, p.Y, ci))

    # 3) raw value per point
    vals = []
    kmax = 0.0
    for ci in range(len(polys)):
        crv = polys[ci][0]
        pl = polys[ci][1]
        tl = polys[ci][2]
        row = []
        for pi in range(len(pl)):
            p = pl[pi]
            v = 0.0
            if MODE == 0:
                if tl is not None:
                    try:
                        k = crv.CurvatureAt(tl[pi])
                        v = k.Length
                    except:
                        v = 0.0
                if v > kmax:
                    kmax = v
            elif MODE == 1:
                gi = int(p.X / SCL)
                gj = int(p.Y / SCL)
                best = None
                for dj in [-1, 0, 1]:
                    for di in [-1, 0, 1]:
                        key = (gi + di, gj + dj)
                        if key not in phash:
                            continue
                        for q in phash[key]:
                            if q[2] == ci:
                                continue
                            dx = q[0] - p.X
                            dy = q[1] - p.Y
                            d = math.sqrt(dx * dx + dy * dy)
                            if best is None or d < best:
                                best = d
                if best is not None and best < SCL:
                    v = 1.0 - (best / SCL)
            elif MODE == 2:
                if img is not None:
                    u = (p.X - ix0) / dw
                    w2 = (p.Y - iy0) / dh
                    if 0.0 <= u <= 1.0 and 0.0 <= w2 <= 1.0:
                        px = int(u * (img[2] - 1))
                        py = int((1.0 - w2) * (img[3] - 1))
                        idx = py * img[1] + px * 3
                        b = img[0][idx]
                        g = img[0][idx + 1]
                        r = img[0][idx + 2]
                        lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255.0
                        v = 1.0 - lum          # dark = more pressure
            else:
                v = vnoise(p.X / SCL, p.Y / SCL, 1)
            row.append(v)
        vals.append(row)

    # curvature normalises against the 90th percentile so one hairpin
    # doesn't flatten everything else
    if MODE == 0:
        allk = []
        for row in vals:
            for v in row:
                allk.append(v)
        allk.sort()
        ref = kmax
        if allk:
            ref = allk[int(len(allk) * 0.9)]
        if ref <= 1e-9:
            ref = 1.0
        for ri in range(len(vals)):
            for pi in range(len(vals[ri])):
                v = vals[ri][pi] / ref
                if v > 1.0:
                    v = 1.0
                vals[ri][pi] = v

    # 4) write Z (negative = press harder), ADDING to any existing pressure
    npts = 0
    vmin = 9e9
    vmax = -9e9
    for ci in range(len(polys)):
        pl = polys[ci][1]
        lp = List[rg.Point3d]()
        for pi in range(len(pl)):
            v = vals[ci][pi]
            if v < 0.0:
                v = 0.0
            if v > 1.0:
                v = 1.0
            if INV:
                v = 1.0 - v
            z = pl[pi].Z - AMT * v
            if z < vmin:
                vmin = z
            if z > vmax:
                vmax = z
            lp.Add(rg.Point3d(pl[pi].X, pl[pi].Y, z))
            npts += 1
        out_crvs.append(rg.PolylineCurve(lp))
    mnames = {0: 'curvature', 1: 'proximity', 2: 'image', 3: 'noise'}
    info = '%s, amount %.2fmm, detail %.1fmm, %d pts, Z %.2f..%.2f%s' % (
        mnames.get(MODE, '?'), AMT, DET, npts, vmin, vmax, imgnote)

print('%d curves -> %d pressured | %s' % (len(cs), len(out_crvs), info))
