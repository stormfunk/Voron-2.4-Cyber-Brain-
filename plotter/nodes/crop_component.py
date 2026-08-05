# CROP processor - clips curves to one or more closed crop shapes of any form
# (circles, rectangles, blobs, text outlines, anything closed).
#
# Multiple crop shapes are combined EVEN-ODD, so a shape nested inside another
# reads as a hole - drop a small circle inside a big one and you crop to a ring.
# Curves are split at every boundary crossing and each piece is kept or dropped
# on its own, so a stroke can enter and leave the crop region repeatedly.
# The pressure channel (point Z) survives, since splitting preserves it.
# PROCESSOR CONTRACT: curves in (`crvs`) -> cropped curves out (`out_crvs`).
# Inputs: crvs(list, any curves), crop(list, CLOSED crop shapes),
#         mode(0 keep inside / 1 keep outside), on(bool bypass)
import Rhino
import Rhino.Geometry as rg
import rhinoscriptsyntax as rs
import scriptcontext as sc
from System.Collections.Generic import List
try:
    sc.doc = ghdoc
except:
    pass

MODE = int(mode) if mode is not None else 0
ON = True if on is None else bool(on)
TOL = 0.001
PLANE = rg.Plane.WorldXY

cs = []
if crvs:
    for c in crvs:
        cc = c if isinstance(c, rg.Curve) else rs.coercecurve(c)
        if cc is not None:
            cs.append(cc)

bounds = []
n_open = 0
if crop:
    for c in crop:
        cc = c if isinstance(c, rg.Curve) else rs.coercecurve(c)
        if cc is None:
            continue
        if not cc.IsClosed:
            n_open += 1
            continue
        bounds.append(cc)

# bounding boxes of the crop shapes, for cheap rejection
bbs = []
for b in bounds:
    bbs.append(b.GetBoundingBox(True))
bb_all = rg.BoundingBox.Empty
for b in bbs:
    bb_all.Union(b)

out_crvs = []
info = ''
if not ON:
    out_crvs = cs
    info = '[BYPASSED]'
elif not bounds:
    out_crvs = cs
    info = 'no closed crop shape - passing through untouched'
elif cs:
    n_split = 0
    n_whole = 0
    n_dropped = 0
    for c in cs:
        cbb = c.GetBoundingBox(True)
        # cheap reject: entirely clear of every crop shape
        if not cbb.IsValid:
            continue
        away = True
        for b in bbs:
            if not (cbb.Min.X > b.Max.X or cbb.Max.X < b.Min.X or
                    cbb.Min.Y > b.Max.Y or cbb.Max.Y < b.Min.Y):
                away = False
                break
        if away:
            if MODE == 1:
                out_crvs.append(c)
                n_whole += 1
            else:
                n_dropped += 1
            continue

        ts = []
        for b in bounds:
            xev = rg.Intersect.Intersection.CurveCurve(c, b, TOL, TOL)
            if xev is not None:
                for ev in xev:
                    ts.append(ev.ParameterA)
        pieces = None
        if ts:
            ts.sort()
            tl = List[float]()
            for t in ts:
                tl.Add(t)
            pieces = c.Split(tl)
        if pieces is None or len(pieces) == 0:
            pieces = [c]
        else:
            n_split += 1

        for pc in pieces:
            if pc is None:
                continue
            try:
                mid = pc.PointAtNormalizedLength(0.5)
            except:
                mid = pc.PointAtStart
            probe = rg.Point3d(mid.X, mid.Y, 0.0)   # test in plan, ignore pressure Z
            hits = 0
            for b in bounds:
                if b.Contains(probe, PLANE, TOL) == rg.PointContainment.Inside:
                    hits += 1
            inside = (hits % 2) == 1
            keep = inside if MODE == 0 else (not inside)
            if keep and pc.GetLength() > 0.05:
                out_crvs.append(pc)
            else:
                n_dropped += 1
    info = '%d crop shape(s)%s, keep %s | %d curves split, %d passed whole, %d pieces dropped' % (
        len(bounds), (' (%d open ignored)' % n_open) if n_open else '',
        'OUTSIDE' if MODE == 1 else 'INSIDE', n_split, n_whole, n_dropped)

print('%d curves -> %d | %s' % (len(cs), len(out_crvs), info))
