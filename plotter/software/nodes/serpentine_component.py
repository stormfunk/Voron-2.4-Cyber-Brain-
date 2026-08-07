# SERPENTINE processor - scanline fill with alternate lines joined at the ends
# (boustrophedon). Same look as a parallel-line hatch, but the pen stays DOWN
# and snakes back and forth: hundreds of pen lifts become a handful. The
# practical workhorse fill.
# Nested closed curves are holes (even-odd). Where a hole or a concave edge
# breaks the snake, `join` decides whether to keep the pen down (small gap) or
# lift and start a new stroke (large gap - e.g. across a void).
# PROCESSOR CONTRACT: closed curves in (`crvs`) -> fill linework out (`out_crvs`).
# Inputs: crvs(list, closed), spacing(mm between lines), angle(deg),
#         join(mm, max end-to-end gap to keep the pen down; 0 = never join),
#         inset(mm), keep_edge(bool), on(bool bypass)
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


SP = float(spacing) if spacing is not None else 1.5
if SP < 0.25:
    SP = 0.25
ANG = float(angle) if angle is not None else 0.0
JOIN = float(join) if join is not None else 6.0
if JOIN < 0.0:
    JOIN = 0.0
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
    cxm = (bb.Min.X + bb.Max.X) / 2.0
    cym = (bb.Min.Y + bb.Max.Y) / 2.0
    half = 0.6 * math.sqrt((bb.Max.X - bb.Min.X) ** 2 + (bb.Max.Y - bb.Min.Y) ** 2) + SP
    ar = math.radians(ANG)
    dvx = math.cos(ar)
    dvy = math.sin(ar)
    nx = -dvy
    ny = dvx
    nlines = int((2.0 * half) / SP) + 1
    tol = 0.001
    segs2 = []

    # collect every scanline segment, indexed by line
    segs = []
    byline = {}
    for k in range(nlines):
        off = -half + k * SP
        bx = cxm + nx * off
        by = cym + ny * off
        pa = rg.Point3d(bx - dvx * half, by - dvy * half, 0)
        pb = rg.Point3d(bx + dvx * half, by + dvy * half, 0)
        lc = rg.LineCurve(pa, pb)
        ts = []
        for c in regions:
            xev = rg.Intersect.Intersection.CurveCurve(lc, c, tol, tol)
            if xev is not None:
                for ev in xev:
                    ts.append(ev.ParameterA)
        if len(ts) < 2:
            continue
        ts.sort()
        segs = []
        i = 0
        while i < len(ts) - 1:
            t0 = ts[i]
            t1 = ts[i + 1]
            p0 = lc.PointAt(t0)
            p1 = lc.PointAt(t1)
            if p0.DistanceTo(p1) > 0.15:
                segs.append((p0, p1))
            i += 2
        for s in segs:
            idx = len(segs2)
            segs2.append((k, s[0], s[1]))
            if k not in byline:
                byline[k] = []
            byline[k].append(idx)

    # greedy snake: from the end of the current segment, hop to the nearest
    # unused segment within the next couple of scanlines. On a plain region
    # that is a pure boustrophedon; around a hole it finishes one side, lifts
    # once, then snakes back up the other.
    n_seg = len(segs2)
    used = []
    for i in range(n_seg):
        used.append(False)
    remaining = n_seg
    run = []
    ck = 0
    guard = 0
    while remaining > 0 and guard < 200000:
        guard += 1
        if not run:
            start = -1
            for i in range(n_seg):
                if not used[i]:
                    start = i
                    break
            if start < 0:
                break
            used[start] = True
            remaining -= 1
            run = [segs2[start][1], segs2[start][2]]
            ck = segs2[start][0]
            continue
        endp = run[-1]
        best = -1
        bestd = None
        bestflip = False
        for kk in [ck, ck + 1, ck + 2]:
            if kk not in byline:
                continue
            for i in byline[kk]:
                if used[i]:
                    continue
                d0 = endp.DistanceTo(segs2[i][1])
                d1 = endp.DistanceTo(segs2[i][2])
                if d1 < d0:
                    d = d1
                    fl = True
                else:
                    d = d0
                    fl = False
                if bestd is None or d < bestd:
                    bestd = d
                    best = i
                    bestflip = fl
        if best >= 0 and JOIN > 0.0 and bestd <= JOIN:
            used[best] = True
            remaining -= 1
            if bestflip:
                run.append(segs2[best][2])
                run.append(segs2[best][1])
            else:
                run.append(segs2[best][1])
                run.append(segs2[best][2])
            ck = segs2[best][0]
        else:
            if len(run) > 1:
                lp = List[rg.Point3d]()
                for q in run:
                    lp.Add(q)
                out_crvs.append(rg.PolylineCurve(lp))
            run = []
    if len(run) > 1:
        lp = List[rg.Point3d]()
        for q in run:
            lp.Add(q)
        out_crvs.append(rg.PolylineCurve(lp))
    info = 'spacing %.2fmm, angle %.0f, %d segments, join %.1fmm' % (SP, ANG, n_seg, JOIN)

print('%d regions (%d open skipped) -> %d stroke(s) | %s' % (len(cs), n_open, len(out_crvs), info))
