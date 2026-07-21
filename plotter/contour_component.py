# CONTOUR / ISO-LINE processor - treats the region as terrain (a procedural
# noise height field) and draws its contour lines: topographic-map linework.
# Marching squares on a grid, then the raw segments are chained end-to-end into
# long continuous contours (a whole level often plots as a handful of strokes).
# PROCESSOR CONTRACT: closed curves in (`crvs`) -> contour lines out (`out_crvs`).
# Inputs: crvs(list, closed), levels(int, number of contour lines),
#         scale(mm, size of the hills), detail(mm, grid step - smaller = smoother
#         but slower), seed(int), inset(mm), keep_edge(bool), on(bool bypass)
import Rhino
import Rhino.Geometry as rg
import rhinoscriptsyntax as rs
import scriptcontext as sc
import math, clr
from System.Collections.Generic import List
try:
    sc.doc = ghdoc
except:
    pass

clr.AddReferenceToFileAndPath(r"C:\Users\john.chandler\AppData\Roaming\McNeel\Rhinoceros\packages\7.0\Clipper2GH\1.3.2\Clipper2Lib.dll")
from Clipper2Lib import Paths64, Path64, Point64, Clipper, JoinType, EndType, FillRule


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


def height_at(x, y, sc_mm, sd):
    """three-octave fBm terrain in roughly 0..1 (pure function)"""
    h = vnoise(x / sc_mm, y / sc_mm, sd)
    h = h + 0.5 * vnoise(x / (sc_mm * 0.5), y / (sc_mm * 0.5), sd + 11)
    h = h + 0.25 * vnoise(x / (sc_mm * 0.25), y / (sc_mm * 0.25), sd + 23)
    return h / 1.75


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


LEV = int(levels) if levels is not None else 12
if LEV < 1:
    LEV = 1
if LEV > 60:
    LEV = 60
SCL = float(scale) if scale is not None else 45.0
if SCL < 2.0:
    SCL = 2.0
DET = float(detail) if detail is not None else 1.5
if DET < 0.4:
    DET = 0.4
SEED = int(seed) if seed is not None else 1
INS = float(inset) if inset is not None else 0.75
if INS < 0.0:
    INS = 0.0
EDGE = True if keep_edge is None else bool(keep_edge)
ON = True if on is None else bool(on)

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
info = ''
if not ON:
    out_crvs = cs
    info = '[BYPASSED]'
elif cs:
    if EDGE:
        for c in cs:
            out_crvs.append(c)

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
    nx = int(math.ceil(wid / DET)) + 1
    ny = int(math.ceil(hei / DET)) + 1
    if nx > 700:
        nx = 700
    if ny > 700:
        ny = 700
    sx = wid / float(nx)
    sy = hei / float(ny)

    plane = rg.Plane.WorldXY
    tol = 0.001
    # sample the height field and region membership on the grid
    H = []
    INMASK = []
    for j in range(ny + 1):
        hrow = []
        mrow = []
        py = y0 + j * sy
        for i in range(nx + 1):
            px = x0 + i * sx
            hrow.append(height_at(px, py, SCL, SEED))
            p3 = rg.Point3d(px, py, 0)
            hits = 0
            for c in regions:
                if c.Contains(p3, plane, tol) == rg.PointContainment.Inside:
                    hits += 1
            mrow.append((hits % 2) == 1)
        H.append(hrow)
        INMASK.append(mrow)

    hmin = 1e9
    hmax = -1e9
    for j in range(ny + 1):
        for i in range(nx + 1):
            if INMASK[j][i]:
                if H[j][i] < hmin:
                    hmin = H[j][i]
                if H[j][i] > hmax:
                    hmax = H[j][i]
    if hmax <= hmin:
        hmax = hmin + 1.0

    # marching squares: edge pairs per case (e0 bottom, e1 right, e2 top, e3 left)
    TABLE = {0: [], 1: [(0, 3)], 2: [(0, 1)], 3: [(1, 3)], 4: [(1, 2)],
             5: [(0, 3), (1, 2)], 6: [(0, 2)], 7: [(2, 3)], 8: [(2, 3)],
             9: [(0, 2)], 10: [(0, 1), (2, 3)], 11: [(1, 2)], 12: [(1, 3)],
             13: [(0, 1)], 14: [(0, 3)], 15: []}

    n_seg_total = 0
    for lv in range(LEV):
        L = hmin + (hmax - hmin) * (lv + 0.5) / LEV
        segs = []
        for j in range(ny):
            for i in range(nx):
                if not (INMASK[j][i] and INMASK[j][i + 1] and INMASK[j + 1][i] and INMASK[j + 1][i + 1]):
                    continue
                v00 = H[j][i]
                v10 = H[j][i + 1]
                v11 = H[j + 1][i + 1]
                v01 = H[j + 1][i]
                idx = 0
                if v00 > L:
                    idx |= 1
                if v10 > L:
                    idx |= 2
                if v11 > L:
                    idx |= 4
                if v01 > L:
                    idx |= 8
                pairs = TABLE[idx]
                if not pairs:
                    continue
                ax = x0 + i * sx
                ay = y0 + j * sy
                bx = ax + sx
                by = ay + sy
                ept = {}
                if abs(v10 - v00) > 1e-12:
                    ept[0] = (ax + (L - v00) / (v10 - v00) * sx, ay)
                if abs(v11 - v10) > 1e-12:
                    ept[1] = (bx, ay + (L - v10) / (v11 - v10) * sy)
                if abs(v11 - v01) > 1e-12:
                    ept[2] = (ax + (L - v01) / (v11 - v01) * sx, by)
                if abs(v01 - v00) > 1e-12:
                    ept[3] = (ax, ay + (L - v00) / (v01 - v00) * sy)
                for pr in pairs:
                    if pr[0] in ept and pr[1] in ept:
                        _a = ept[pr[0]]
                        _b = ept[pr[1]]
                        # skip degenerate segments (level through a cell corner
                        # makes both edge points coincide -> invalid curves)
                        if (_a[0]-_b[0])**2 + (_a[1]-_b[1])**2 > 1e-8:
                            segs.append((_a, _b))
        n_seg_total += len(segs)
        if not segs:
            continue

        # chain segments into continuous contours via an endpoint hash
        q = DET * 0.25
        if q < 1e-6:
            q = 1e-6
        endmap = {}
        for si in range(len(segs)):
            for e in [0, 1]:
                p = segs[si][e]
                key = (int(round(p[0] / q)), int(round(p[1] / q)))
                if key not in endmap:
                    endmap[key] = []
                endmap[key].append((si, e))
        used = []
        for si in range(len(segs)):
            used.append(False)
        for si in range(len(segs)):
            if used[si]:
                continue
            used[si] = True
            chain = [segs[si][0], segs[si][1]]
            for endsel in [1, 0]:
                grew = True
                while grew:
                    grew = False
                    p = chain[-1] if endsel == 1 else chain[0]
                    key = (int(round(p[0] / q)), int(round(p[1] / q)))
                    if key not in endmap:
                        continue
                    for pair in endmap[key]:
                        sj = pair[0]
                        ej = pair[1]
                        if used[sj]:
                            continue
                        other = segs[sj][1 - ej]
                        used[sj] = True
                        if endsel == 1:
                            chain.append(other)
                        else:
                            chain.insert(0, other)
                        grew = True
                        break
            # drop duplicate consecutive vertices (quantised endpoints can
            # merge), then emit only genuinely drawable chains
            clean = [chain[0]]
            for pnt in chain[1:]:
                if (pnt[0]-clean[-1][0])**2 + (pnt[1]-clean[-1][1])**2 > 1e-8:
                    clean.append(pnt)
            _tot = 0.0
            for k in range(1, len(clean)):
                _tot += math.sqrt((clean[k][0]-clean[k-1][0])**2 + (clean[k][1]-clean[k-1][1])**2)
            if len(clean) >= 2 and _tot > 0.1:
                lp = List[rg.Point3d]()
                for pnt in clean:
                    lp.Add(rg.Point3d(pnt[0], pnt[1], 0))
                out_crvs.append(rg.PolylineCurve(lp))
    info = '%d levels, scale %.0fmm, grid %dx%d, %d segments chained' % (LEV, SCL, nx, ny, n_seg_total)

print('%d regions (%d open skipped) -> %d contour(s) | %s' % (len(cs), n_open, len(out_crvs), info))
