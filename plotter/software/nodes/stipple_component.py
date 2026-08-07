# STIPPLE / TSP-ART processor - fills closed regions with blue-noise dots whose
# density follows a noise field (dark/dense vs light/sparse), then optionally
# threads ONE continuous line through every dot (a travelling-salesman tour):
# an entire image rendered as a single unbroken stroke.
# TWO OUTPUTS:
#   pts      -> feed the DOTS block for a stippled dot field (pen taps)
#   out_crvs -> the TSP path as a single polyline, for a layer slot
# Use either or both. Sampling is Bridson Poisson-disk with a variable radius,
# so dots stay evenly spread instead of clumping.
# Inputs: crvs(list, closed), spacing(mm, min dot spacing in the DENSE areas),
#         contrast(1 = flat/even, 4 = strong light-dark variation),
#         scale(mm, size of the density blobs - noise mode only), seed(int),
#         image(file path: if given, dot density follows the PICTURE's tone
#               instead of noise - this is how you stipple a photograph),
#         tsp(bool, compute the tour - costs time on big point counts),
#         inset(mm), on(bool bypass)
import Rhino
import Rhino.Geometry as rg
import rhinoscriptsyntax as rs
import scriptcontext as sc
import math, clr
import System
import System.Drawing as SD
from System.Collections.Generic import List
try:
    sc.doc = ghdoc
except:
    pass


def load_image(path, maxdim):
    """-> (buffer, stride, w, h) of a 24bpp copy, or None. LockBits because
    GetPixel per sample would be far too slow."""
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


def image_tone(x, y, img, ix0, iy0, dw, dh):
    """0 = black (dense dots), 1 = white (sparse). Outside the frame -> white."""
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

clr.AddReferenceToFileAndPath(r"C:\Users\john.chandler\AppData\Roaming\McNeel\Rhinoceros\packages\7.0\Clipper2GH\1.3.2\Clipper2Lib.dll")
from Clipper2Lib import Paths64, Path64, Point64, Clipper, JoinType, EndType, FillRule


def nextrand(state):
    """LCG in 0..1; state is a one-item list so it mutates without globals"""
    state[0] = (state[0] * 1103515245 + 12345) & 0x7FFFFFFF
    return state[0] / 2147483647.0


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


def density_at(x, y, sc_mm, sd):
    """0..1 tone field: 0 = dark/dense dots, 1 = light/sparse"""
    n = vnoise(x / sc_mm, y / sc_mm, sd)
    n = n + 0.5 * vnoise(x / (sc_mm * 0.4), y / (sc_mm * 0.4), sd + 31)
    n = n / 1.5
    if n < 0.0:
        n = 0.0
    if n > 1.0:
        n = 1.0
    return n


def shrink_regions(curve_list, amount, scale):
    paths = Paths64()
    for c in curve_list:
        plc = c.ToPolyline(0.05, 0.2, 0.01, 1e6)
        if plc is None:
            continue
        path = Path64()
        for i in range(plc.PointCount - 1):
            p = plc.Point(i)
            path.Add(Point64(int(round(p.X * scale)), int(round(p.Y * scale))))
        paths.Add(path)
    norm = Clipper.Union(paths, FillRule.EvenOdd)
    sh = Clipper.InflatePaths(norm, -amount * scale, JoinType.Round, EndType.Polygon)
    out = []
    if sh is not None:
        for path in sh:
            if path.Count < 3:
                continue
            pts = List[rg.Point3d]()
            for pt in path:
                pts.Add(rg.Point3d(pt.X / scale, pt.Y / scale, 0))
            pts.Add(rg.Point3d(path[0].X / scale, path[0].Y / scale, 0))
            out.append(rg.PolylineCurve(pts))
    return out


SP = float(spacing) if spacing is not None else 2.0
if SP < 0.4:
    SP = 0.4
CON = float(contrast) if contrast is not None else 2.5
if CON < 1.0:
    CON = 1.0
SCL = float(scale) if scale is not None else 50.0
if SCL < 2.0:
    SCL = 2.0
SEED = int(seed) if seed is not None else 1
TSP = True if tsp is None else bool(tsp)
IMGPATH = None
if image is not None:
    try:
        IMGPATH = str(image).strip('"')
    except:
        IMGPATH = None
INS = float(inset) if inset is not None else 0.75
if INS < 0.0:
    INS = 0.0
ON = True if on is None else bool(on)
MAXPTS = 6000

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
elif cs:
    regions = cs
    if INS > 0.01:
        shrunk = shrink_regions(cs, INS, 1000.0)
        if shrunk:
            regions = shrunk

    bb = rg.BoundingBox.Empty
    for c in regions:
        bb.Union(c.GetBoundingBox(True))
    x0 = bb.Min.X
    y0 = bb.Min.Y
    wid = bb.Max.X - x0
    hei = bb.Max.Y - y0
    rmin = SP
    rmax = SP * CON
    # image tone drives density when supplied, otherwise the noise field does
    img = None
    imgnote = ''
    if IMGPATH:
        img = load_image(IMGPATH, 1400)
        if img is None:
            imgnote = ' (IMAGE FAILED TO LOAD - using noise)'
    idw = wid
    idh = hei
    if img is not None:
        ia = float(img[2]) / float(img[3])
        ba = wid / hei
        if ia > ba:
            idw = wid
            idh = wid / ia
        else:
            idh = hei
            idw = hei * ia
    ix0 = x0 + (wid - idw) / 2.0
    iy0 = y0 + (hei - idh) / 2.0

    # inside bitmap (native Contains is slow - do it once)
    gc = max(0.4, rmin * 0.5)
    nx = int(math.ceil(wid / gc)) + 2
    ny = int(math.ceil(hei / gc)) + 2
    plane = rg.Plane.WorldXY
    tol = 0.001
    inside = []
    for j in range(ny):
        row = []
        py = y0 + (j - 0.5) * gc
        for i in range(nx):
            px = x0 + (i - 0.5) * gc
            hits = 0
            p3 = rg.Point3d(px, py, 0)
            for c in regions:
                if c.Contains(p3, plane, tol) == rg.PointContainment.Inside:
                    hits += 1
            row.append((hits % 2) == 1)
        inside.append(row)

    # --- Bridson Poisson-disk with variable radius ---
    cell = rmin / 1.4142
    gnx = int(math.ceil(wid / cell)) + 2
    gny = int(math.ceil(hei / cell)) + 2
    grid = {}
    samples = []
    active = []
    rng = [(SEED * 2654435761) & 0x7FFFFFFF]
    reach = int(math.ceil(rmax / cell)) + 1

    # find a starting point inside the region
    for attempt in range(400):
        sx = x0 + nextrand(rng) * wid
        sy = y0 + nextrand(rng) * hei
        bi = int((sx - x0) / gc) + 1
        bj = int((sy - y0) / gc) + 1
        if 0 <= bj < ny and 0 <= bi < nx and inside[bj][bi]:
            samples.append((sx, sy))
            active.append(0)
            grid[(int((sx - x0) / cell), int((sy - y0) / cell))] = [0]
            break

    guard = 0
    while active and len(samples) < MAXPTS and guard < 400000:
        guard += 1
        ai = int(nextrand(rng) * len(active))
        if ai >= len(active):
            ai = len(active) - 1
        pi = active[ai]
        px = samples[pi][0]
        py = samples[pi][1]
        if img is not None:
            r_here = rmin + (rmax - rmin) * image_tone(px, py, img, ix0, iy0, idw, idh)
        else:
            r_here = rmin + (rmax - rmin) * density_at(px, py, SCL, SEED)
        placed = False
        for k in range(24):
            ang = nextrand(rng) * 2.0 * math.pi
            rad = r_here * (1.0 + nextrand(rng))
            cxp = px + math.cos(ang) * rad
            cyp = py + math.sin(ang) * rad
            bi = int((cxp - x0) / gc) + 1
            bj = int((cyp - y0) / gc) + 1
            if bj < 0 or bj >= ny or bi < 0 or bi >= nx or not inside[bj][bi]:
                continue
            if img is not None:
                r_c = rmin + (rmax - rmin) * image_tone(cxp, cyp, img, ix0, iy0, idw, idh)
            else:
                r_c = rmin + (rmax - rmin) * density_at(cxp, cyp, SCL, SEED)
            gi = int((cxp - x0) / cell)
            gj = int((cyp - y0) / cell)
            ok = True
            for dj in range(-reach, reach + 1):
                for di in range(-reach, reach + 1):
                    key = (gi + di, gj + dj)
                    if key not in grid:
                        continue
                    for si in grid[key]:
                        dx = samples[si][0] - cxp
                        dy = samples[si][1] - cyp
                        if dx * dx + dy * dy < r_c * r_c:
                            ok = False
                            break
                    if not ok:
                        break
                if not ok:
                    break
            if ok:
                samples.append((cxp, cyp))
                idx = len(samples) - 1
                if (gi, gj) not in grid:
                    grid[(gi, gj)] = []
                grid[(gi, gj)].append(idx)
                active.append(idx)
                placed = True
                break
        if not placed:
            active.pop(ai)

    for s in samples:
        pts.append(rg.Point3d(s[0], s[1], 0))

    # --- TSP tour: grid-accelerated nearest neighbour, then local 2-opt ---
    if TSP and len(samples) > 2:
        tgrid = {}
        tcell = rmax * 1.5
        for i in range(len(samples)):
            key = (int((samples[i][0] - x0) / tcell), int((samples[i][1] - y0) / tcell))
            if key not in tgrid:
                tgrid[key] = []
            tgrid[key].append(i)
        visited = []
        for i in range(len(samples)):
            visited.append(False)
        tour = [0]
        visited[0] = True
        cur = 0
        for step in range(len(samples) - 1):
            cx = samples[cur][0]
            cy = samples[cur][1]
            gi = int((cx - x0) / tcell)
            gj = int((cy - y0) / tcell)
            best = -1
            bestd = None
            ring = 1
            while best < 0 and ring < 200:
                for dj in range(-ring, ring + 1):
                    for di in range(-ring, ring + 1):
                        if max(abs(di), abs(dj)) != ring and ring > 1:
                            continue
                        key = (gi + di, gj + dj)
                        if key not in tgrid:
                            continue
                        for si in tgrid[key]:
                            if visited[si]:
                                continue
                            dx = samples[si][0] - cx
                            dy = samples[si][1] - cy
                            d = dx * dx + dy * dy
                            if bestd is None or d < bestd:
                                bestd = d
                                best = si
                ring += 1
            if best < 0:
                break
            visited[best] = True
            tour.append(best)
            cur = best
        # local 2-opt: uncross nearby segments (cheap, big visual win)
        for sweep in range(2):
            i = 1
            while i < len(tour) - 3:
                a1 = samples[tour[i - 1]]
                a2 = samples[tour[i]]
                jmax = i + 40
                if jmax > len(tour) - 2:
                    jmax = len(tour) - 2
                j = i + 2
                while j < jmax:
                    b1 = samples[tour[j]]
                    b2 = samples[tour[j + 1]]
                    d0 = math.hypot(a1[0] - a2[0], a1[1] - a2[1]) + math.hypot(b1[0] - b2[0], b1[1] - b2[1])
                    d1 = math.hypot(a1[0] - b1[0], a1[1] - b1[1]) + math.hypot(a2[0] - b2[0], a2[1] - b2[1])
                    if d1 < d0 - 0.0001:
                        seg = tour[i:j + 1]
                        seg.reverse()
                        tour = tour[:i] + seg + tour[j + 1:]
                        a2 = samples[tour[i]]
                    j += 1
                i += 1
        lp = List[rg.Point3d]()
        for ti in tour:
            lp.Add(rg.Point3d(samples[ti][0], samples[ti][1], 0))
        out_crvs.append(rg.PolylineCurve(lp))
    info = '%d dots, spacing %.2f-%.2fmm, density from %s%s%s' % (
        len(samples), rmin, rmax,
        ('IMAGE %dx%d' % (img[2], img[3])) if img is not None else ('noise scale %.0fmm' % SCL),
        (', TSP tour' if (TSP and len(samples) > 2) else ''), imgnote)

print('%d regions (%d open skipped) -> %d dots, %d path(s) | %s' % (len(cs), n_open, len(pts), len(out_crvs), info))
