# HILBERT FILL processor - fills closed regions with a space-filling Hilbert
# curve. Unlike scanline hatch (one pen lift per line), a Hilbert fill is ONE
# CONTINUOUS STROKE per region: minimal lifts, fast, and a distinctive woven
# texture. Nested closed curves become holes (even-odd containment).
# PROCESSOR CONTRACT: closed curves in (`crvs`) -> fill linework out (`out_crvs`).
# Inputs: crvs(list, closed), order(int 1-8, density: line spacing = side/2^order),
#         inset(mm, keeps the fill off the boundary ~ half pen width),
#         join(mm, rejoin fragments whose gap is under this - the curve zigzags
#              across the boundary and would otherwise shatter into hundreds of
#              strokes; keep it well under your smallest hole so joins never
#              bridge a void. 0 = no joining),
#         keep_edge(bool, also output the region outline), on(bool bypass)
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


def hilbert_xy(order_n, d):
    """d-th point (0..n*n-1) on a Hilbert curve filling an n x n grid,
    n = 2**order_n. Pure function - no free variables (GhPython scope safety)."""
    n = 1 << order_n
    x = 0
    y = 0
    t = d
    s = 1
    while s < n:
        rx = 1 & (t // 2)
        ry = 1 & (t ^ rx)
        if ry == 0:
            if rx == 1:
                x = s - 1 - x
                y = s - 1 - y
            tmp = x
            x = y
            y = tmp
        x = x + s * rx
        y = y + s * ry
        t = t // 4
        s = s * 2
    return x, y


def shrink_regions(curve_list, amount, scale):
    """Clipper2 inset, normalising winding via even-odd union first so nested
    curves stay holes instead of exploding outward."""
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


ORD = int(order) if order is not None else 5
if ORD < 1:
    ORD = 1
if ORD > 8:
    ORD = 8
INS = float(inset) if inset is not None else 0.75
if INS < 0.0:
    INS = 0.0
JOIN = float(join) if join is not None else 2.0
if JOIN < 0.0:
    JOIN = 0.0
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
    wid = bb.Max.X - bb.Min.X
    hei = bb.Max.Y - bb.Min.Y
    side = max(wid, hei) * 1.02
    if side < 0.001:
        side = 1.0
    cx = (bb.Min.X + bb.Max.X) / 2.0
    cy = (bb.Min.Y + bb.Max.Y) / 2.0
    ox = cx - side / 2.0
    oy = cy - side / 2.0
    n = 1 << ORD
    cell = side / float(n)
    total = n * n

    # walk the Hilbert sequence, keeping runs of points inside the region.
    # even-odd containment -> nested curves read as holes.
    tol = 0.001
    plane = rg.Plane.WorldXY
    run = []
    prev_pt = None
    prev_in = False
    for d in range(total):
        gx, gy = hilbert_xy(ORD, d)
        px = ox + (gx + 0.5) * cell
        py = oy + (gy + 0.5) * cell
        pt = rg.Point3d(px, py, 0)
        hits = 0
        for c in regions:
            if c.Contains(pt, plane, tol) == rg.PointContainment.Inside:
                hits += 1
        isin = (hits % 2) == 1

        if isin and not prev_in:
            # entering: trim back to the boundary crossing
            entry = None
            if prev_pt is not None:
                seg = rg.LineCurve(prev_pt, pt)
                best_t = None
                for c in regions:
                    xev = rg.Intersect.Intersection.CurveCurve(seg, c, tol, tol)
                    if xev is not None:
                        for ev in xev:
                            if best_t is None or ev.ParameterA > best_t:
                                best_t = ev.ParameterA
                if best_t is not None:
                    entry = seg.PointAt(best_t)
            # rejoin to the previous run if the excursion was tiny (a boundary
            # zigzag), otherwise flush and start a fresh stroke
            gap_pt = entry if entry is not None else pt
            if run and JOIN > 0.0 and run[-1].DistanceTo(gap_pt) <= JOIN:
                if entry is not None:
                    run.append(entry)
                run.append(pt)
            else:
                if len(run) > 1:
                    lp = List[rg.Point3d]()
                    for q in run:
                        lp.Add(q)
                    out_crvs.append(rg.PolylineCurve(lp))
                run = []
                if entry is not None:
                    run.append(entry)
                run.append(pt)
        elif isin and prev_in:
            run.append(pt)
        elif (not isin) and prev_in:
            # leaving: extend to the boundary, hold the run open in case the
            # curve comes straight back (JOIN decides at the next entry)
            seg = rg.LineCurve(prev_pt, pt)
            best_t = None
            for c in regions:
                xev = rg.Intersect.Intersection.CurveCurve(seg, c, tol, tol)
                if xev is not None:
                    for ev in xev:
                        if best_t is None or ev.ParameterA < best_t:
                            best_t = ev.ParameterA
            if best_t is not None:
                run.append(seg.PointAt(best_t))
            if JOIN <= 0.0:
                if len(run) > 1:
                    lp = List[rg.Point3d]()
                    for q in run:
                        lp.Add(q)
                    out_crvs.append(rg.PolylineCurve(lp))
                run = []
        prev_pt = pt
        prev_in = isin
    if len(run) > 1:
        lp = List[rg.Point3d]()
        for q in run:
            lp.Add(q)
        out_crvs.append(rg.PolylineCurve(lp))
    info = 'order %d (%dx%d), line spacing %.2fmm, %d pts, join %.1fmm' % (ORD, n, n, cell, total, JOIN)

print('%d regions (%d open skipped) -> %d stroke(s) | %s' % (len(cs), n_open, len(out_crvs), info))
