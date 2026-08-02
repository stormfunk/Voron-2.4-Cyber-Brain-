# POINTILLISM - turns an image into dots inside the given region(s).
#
# A pen tap is always the same size, so tone has to come from somewhere. Three
# strategies, pick with `mode`:
#   0 density  - uniform dots, SPACING follows tone (dark = more dots).
#                Best for pen taps: wire `pts` into the DOTS block.
#   1 halftone - regular screen grid, dot SIZE follows tone. The classic
#                newsprint look. Rotate the screen with `angle` (45 is standard).
#   2 scatter  - jittered positions, size AND density follow tone. Painterly.
# Modes 1/2 output drawable circles on `out_crvs` (spiral-filled when a dot is
# fatter than the pen, so it reads solid); mode 0 leans on `pts`.
# Both outputs are always produced, so you can plot taps and circles together.
# Inputs: crvs(list, closed regions), image(file path), mode(0/1/2),
#         cell(mm, dot pitch), min_dot/max_dot(mm radius), gamma(tone curve),
#         pen_width(mm, spiral pitch), invert(bool), seed(int), on(bool bypass)
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


def load_image(path, maxdim):
    """-> (buffer, stride, w, h) of a 24bpp copy. LockBits + direct indexing;
    GetPixel per sample is far too slow."""
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


def tone_at(x, y, img, ix0, iy0, dw, dh):
    """0 = black, 1 = white. Outside the picture reads as white (no ink)."""
    u = (x - ix0) / dw
    v = (y - iy0) / dh
    if u < 0.0 or u > 1.0 or v < 0.0 or v > 1.0:
        return 1.0
    px = int(u * (img[2] - 1))
    py = int((1.0 - v) * (img[3] - 1))
    idx = py * img[1] + px * 3
    b = img[0][idx]
    g = img[0][idx + 1]
    r = img[0][idx + 2]
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255.0


def spiral_dot(cx, cy, rad, pitch):
    """one continuous spiral from the centre out - a filled dot in a single
    stroke, no pen lifts inside the dot"""
    pts = List[rg.Point3d]()
    if pitch < 0.05:
        pitch = 0.05
    turns = rad / pitch
    steps = int(turns * 16.0)
    if steps < 8:
        steps = 8
    if steps > 400:
        steps = 400
    for i in range(steps + 1):
        f = float(i) / steps
        a = f * turns * 6.283185307
        r = f * rad
        pts.Add(rg.Point3d(cx + r * math.cos(a), cy + r * math.sin(a), 0))
    for i in range(21):
        a = 6.283185307 * i / 20.0
        pts.Add(rg.Point3d(cx + rad * math.cos(a), cy + rad * math.sin(a), 0))
    return rg.PolylineCurve(pts)


MODE = int(mode) if mode is not None else 0
CELL = float(cell) if cell is not None else 2.0
if CELL < 0.2:
    CELL = 0.2
RMIN = float(min_dot) if min_dot is not None else 0.15
if RMIN < 0.0:
    RMIN = 0.0
RMAX = float(max_dot) if max_dot is not None else 1.0
if RMAX < RMIN:
    RMAX = RMIN
GAM = float(gamma) if gamma is not None else 1.0
if GAM < 0.05:
    GAM = 0.05
# white point: tones lighter than this make NO ink, and what remains is
# re-stretched over the full range. Kills the faint halo a render's soft
# background shadow leaves behind, without flattening the object's own tones.
WCUT = float(white_cut) if white_cut is not None else 0.0
if WCUT < 0.0:
    WCUT = 0.0
if WCUT > 0.95:
    WCUT = 0.95
PW = float(pen_width) if pen_width is not None else 0.4
INV = False if invert is None else bool(invert)
SEED = int(seed) if seed is not None else 1
ON = True if on is None else bool(on)
MAXDOTS = 20000

IMGPATH = None
if image is not None:
    try:
        IMGPATH = str(image).strip('"')
    except:
        IMGPATH = None

cs = []
n_open = 0
if crvs:
    for c in crvs:
        cc = c if isinstance(c, rg.Curve) else rs.coercecurve(c)
        if cc is None:
            continue
        if not cc.IsClosed:
            n_open += 1
            continue
        cs.append(cc)

out_crvs = []
pts = []
info = ''
if not ON:
    out_crvs = cs
    info = '[BYPASSED]'
elif not cs:
    info = 'no closed region - give it an area to fill'
else:
    img = load_image(IMGPATH, 1400) if IMGPATH else None
    if img is None:
        info = 'NO IMAGE (set the image file path)'
    else:
        bb = rg.BoundingBox.Empty
        for c in cs:
            bb.Union(c.GetBoundingBox(True))
        x0 = bb.Min.X
        y0 = bb.Min.Y
        wid = bb.Max.X - x0
        hei = bb.Max.Y - y0
        # fit the picture into the region, aspect preserved
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

        plane = rg.Plane.WorldXY
        tol = 0.001
        # ---- inside bitmap: native Curve.Contains per grid point is the
        # bottleneck (tens of thousands of calls on a fine cell), so sample the
        # region ONCE onto a grid and look it up afterwards. ----
        _gc = CELL
        if _gc < 1.2:
            _gc = 1.2                        # region edges are smooth; a fine
                                             # mask buys nothing but probe cost
        _bnx = int(wid / _gc) + 3
        _bny = int(hei / _gc) + 3
        if _bnx * _bny > 200000:            # keep the probe grid sane
            _gc = math.sqrt(wid * hei / 200000.0)
            _bnx = int(wid / _gc) + 3
            _bny = int(hei / _gc) + 3
        inside = []
        for j in range(_bny):
            row = []
            py = y0 + (j - 1) * _gc
            for i in range(_bnx):
                px = x0 + (i - 1) * _gc
                p3 = rg.Point3d(px, py, 0)
                hits = 0
                for c in cs:
                    if c.Contains(p3, plane, tol) == rg.PointContainment.Inside:
                        hits += 1
                row.append((hits % 2) == 1)
            inside.append(row)
        rng = [(SEED * 2654435761 + 12345) & 0x7FFFFFFF]
        ar = math.radians(float(angle) if angle is not None else 45.0)
        ca = math.cos(ar)
        sa = math.sin(ar)
        # Iterate ONLY the grid cells that can land inside the region. A naive
        # sweep of the full rotated square (diagonal-sized) wastes ~90% of its
        # steps outside the area - map the bbox corners into grid space instead.
        cxm = x0 + wid / 2.0
        cym = y0 + hei / 2.0
        _gi0 = None; _gi1 = None; _gj0 = None; _gj1 = None
        for _cx4, _cy4 in [(x0, y0), (x0 + wid, y0), (x0, y0 + hei), (x0 + wid, y0 + hei)]:
            _rx = _cx4 - cxm
            _ry = _cy4 - cym
            _lx = _rx * ca + _ry * sa           # inverse rotation
            _ly = -_rx * sa + _ry * ca
            _a = _lx / CELL
            _b = _ly / CELL
            if _gi0 is None or _a < _gi0: _gi0 = _a
            if _gi1 is None or _a > _gi1: _gi1 = _a
            if _gj0 is None or _b < _gj0: _gj0 = _b
            if _gj1 is None or _b > _gj1: _gj1 = _b
        _gi0 = int(math.floor(_gi0)) - 1; _gi1 = int(math.ceil(_gi1)) + 1
        _gj0 = int(math.floor(_gj0)) - 1; _gj1 = int(math.ceil(_gj1)) + 1
        n_dot = 0
        for gj in range(_gj0, _gj1 + 1):
            for gi in range(_gi0, _gi1 + 1):
                if n_dot >= MAXDOTS:
                    break
                lx = gi * CELL
                ly = gj * CELL
                if MODE != 1:
                    rng[0] = (rng[0] * 1103515245 + 12345) & 0x7FFFFFFF
                    jx = (rng[0] / 2147483647.0 - 0.5) * CELL
                    rng[0] = (rng[0] * 1103515245 + 12345) & 0x7FFFFFFF
                    jy = (rng[0] / 2147483647.0 - 0.5) * CELL
                    lx += jx
                    ly += jy
                px = cxm + lx * ca - ly * sa
                py = cym + lx * sa + ly * ca
                bi = int((px - x0) / _gc) + 1
                bj = int((py - y0) / _gc) + 1
                if bj < 0 or bj >= _bny or bi < 0 or bi >= _bnx:
                    continue
                if not inside[bj][bi]:
                    continue
                lum = tone_at(px, py, img, ix0, iy0, idw, idh)
                ink = 1.0 - lum
                if INV:
                    ink = lum
                if WCUT > 0.0:
                    if ink <= WCUT:
                        continue
                    ink = (ink - WCUT) / (1.0 - WCUT)
                ink = math.pow(ink, GAM)
                if MODE == 0:
                    # density: keep or drop this cell by tone, uniform dot
                    rng[0] = (rng[0] * 1103515245 + 12345) & 0x7FFFFFFF
                    if (rng[0] / 2147483647.0) > ink:
                        continue
                    pts.append(rg.Point3d(px, py, 0))
                    if RMIN > 0.01:
                        out_crvs.append(rg.Circle(rg.Point3d(px, py, 0), RMIN).ToNurbsCurve())
                    n_dot += 1
                else:
                    if MODE == 2:
                        rng[0] = (rng[0] * 1103515245 + 12345) & 0x7FFFFFFF
                        if (rng[0] / 2147483647.0) > ink:
                            continue
                    rad = RMIN + (RMAX - RMIN) * ink
                    if rad < 0.05 or ink < 0.02:
                        continue
                    pts.append(rg.Point3d(px, py, 0))
                    # only spiral when the dot genuinely needs more than one
                    # ring to fill - below that a single circle is cleaner than
                    # a one-turn scribble
                    if rad > PW * 1.6:
                        out_crvs.append(spiral_dot(px, py, rad, PW))
                    else:
                        out_crvs.append(rg.Circle(rg.Point3d(px, py, 0), rad).ToNurbsCurve())
                    n_dot += 1
        mnames = {0: 'density (taps)', 1: 'halftone grid', 2: 'scatter'}
        info = '%s, cell %.2fmm, dots %.2f-%.2fmm, gamma %.2f, image %dx%d%s' % (
            mnames.get(MODE, '?'), CELL, RMIN, RMAX, GAM, img[2], img[3],
            ' [capped]' if n_dot >= MAXDOTS else '')

print('%d region(s)%s -> %d dots, %d drawable | %s' % (
    len(cs), (' (%d open ignored)' % n_open) if n_open else '', len(pts), len(out_crvs), info))
