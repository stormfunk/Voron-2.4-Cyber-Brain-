# HATCH processor - turns CLOSED regions into solid pen fills.
# Two modes: 0 = parallel line hatch (even-odd, holes supported: nest a closed
# curve inside another and it becomes a void), 1 = concentric fill (successive
# insets via the Clipper2 polygon engine - crash-proof offsets).
# PROCESSOR CONTRACT: closed curves in (`crvs`) -> fill linework out (`out_crvs`).
# Inputs: crvs(list, closed), spacing(mm), angle(deg, lines mode), mode(0/1),
#         inset(mm, first offset from the edge ~ half pen width), keep_edge(bool),
#         on(bool bypass)
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

def _to_paths(curve_list, scale):
    """closed curves -> Paths64, normalized via even-odd union so nested
    curves become proper holes with correct winding"""
    paths = Paths64()
    for c in curve_list:
        plc = c.ToPolyline(0.05, 0.2, 0.01, 1e6)
        if plc is None:
            continue
        path = Path64()
        for i in range(plc.PointCount - 1):
            p = plc.Point(i)
            path.Add(Point64(int(round(p.X*scale)), int(round(p.Y*scale))))
        paths.Add(path)
    return Clipper.Union(paths, FillRule.EvenOdd)

SP = float(spacing) if spacing is not None else 1.5
if SP < 0.25:
    SP = 0.25
ANG = float(angle) if angle is not None else 45.0
MODE = int(mode) if mode is not None else 0
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
if not ON:
    out_crvs = cs
elif cs:
    if EDGE:
        for c in cs:
            out_crvs.append(c)
    if MODE == 1:
        # ---- concentric fill via Clipper2 insets ----
        SCALE = 1000.0
        paths = _to_paths(cs, SCALE)
        d = INS if INS > 0.01 else SP
        rounds = 0
        while rounds < 2000:
            sh = Clipper.InflatePaths(paths, -d*SCALE, JoinType.Round, EndType.Polygon)
            if sh is None or sh.Count == 0:
                break
            for path in sh:
                if path.Count < 3:
                    continue
                pts = List[rg.Point3d]()
                for pt in path:
                    pts.Add(rg.Point3d(pt.X/SCALE, pt.Y/SCALE, 0))
                pts.Add(rg.Point3d(path[0].X/SCALE, path[0].Y/SCALE, 0))
                out_crvs.append(rg.PolylineCurve(pts))
            d += SP
            rounds += 1
    else:
        # ---- parallel line hatch, even-odd across ALL region curves ----
        bb = rg.BoundingBox.Empty
        for c in cs:
            bb.Union(c.GetBoundingBox(True))
        cxm = (bb.Min.X+bb.Max.X)/2.0
        cym = (bb.Min.Y+bb.Max.Y)/2.0
        half = 0.6*math.sqrt((bb.Max.X-bb.Min.X)**2 + (bb.Max.Y-bb.Min.Y)**2) + SP
        ar = math.radians(ANG)
        dvx = math.cos(ar); dvy = math.sin(ar)
        nx = -dvy; ny = dvx
        # shrink the region by `inset` first so hatch lines stay off the edge
        regions = cs
        if INS > 0.01:
            SCALE = 1000.0
            paths = _to_paths(cs, SCALE)
            sh = Clipper.InflatePaths(paths, -INS*SCALE, JoinType.Round, EndType.Polygon)
            regions = []
            if sh is not None:
                for path in sh:
                    if path.Count < 3:
                        continue
                    pts = List[rg.Point3d]()
                    for pt in path:
                        pts.Add(rg.Point3d(pt.X/SCALE, pt.Y/SCALE, 0))
                    pts.Add(rg.Point3d(path[0].X/SCALE, path[0].Y/SCALE, 0))
                    regions.append(rg.PolylineCurve(pts))
        nlines = int((2.0*half)/SP) + 1
        made = 0
        for k in range(nlines):
            off = -half + k*SP
            bx = cxm + nx*off; by = cym + ny*off
            pa = rg.Point3d(bx - dvx*half, by - dvy*half, 0)
            pb = rg.Point3d(bx + dvx*half, by + dvy*half, 0)
            lc = rg.LineCurve(pa, pb)
            ts = []
            for c in regions:
                xev = rg.Intersect.Intersection.CurveCurve(lc, c, 0.001, 0.001)
                if xev is not None:
                    for ev in xev:
                        ts.append(ev.ParameterA)
            if len(ts) < 2:
                continue
            ts.sort()
            i = 0
            while i < len(ts) - 1:
                t0 = ts[i]; t1 = ts[i+1]
                seg = lc.Trim(t0, t1)
                if seg is not None and seg.GetLength() > 0.15:
                    out_crvs.append(seg)
                    made += 1
                i += 2
print('%d regions (%d open skipped) -> %d fill curves | mode=%s sp=%.2f' % (
    len(cs), n_open, len(out_crvs), 'concentric' if MODE == 1 else 'lines', SP))
