# PAW FILL processor - scatters cat-paw prints across CLOSED regions.
#
# A motif fill rather than a line fill: instead of covering the region with
# strokes, it tiles it with one repeated drawn shape. Same contract as the other
# region fills, so it chains with them - hatch a shape, then paw-print over it.
#
# Each paw is 5 closed curves (heel pad + 4 toes), drawn as OUTLINES because
# that is what a pen actually does. Set `fill` above zero to add concentric
# insets inside each pad and darken them toward the solid look of the source
# artwork.
#
# Placement is a staggered grid with jitter rather than pure random scatter.
# Pure random clumps - it puts two paws on top of each other and leaves holes
# elsewhere - and on a plotter a clump is not just ugly, it is a blot where the
# pen goes over the same paper repeatedly. The grid guarantees the spacing and
# the jitter removes the regularity.
#
# Paws are kept WHOLE: a candidate is dropped unless it fits entirely inside the
# region. Clipping a paw at the boundary leaves recognisable fragments (half a
# toe, a sliced heel) that read as mistakes, where a missing paw reads as
# deliberate spacing.
#
# PROCESSOR CONTRACT: closed curves in (`crvs`) -> paw linework out (`out_crvs`).
# Inputs: crvs(list, closed), size(mm, paw height), spacing(mm, grid pitch),
#         jitter(0..1), spin(deg, random rotation range), vary(0..1, size
#         variation), fill(mm, 0 = outline only), seed(int), keep_edge(bool),
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

_HAVE_CLIP = False
try:
    clr.AddReferenceToFileAndPath(r"C:\Users\john.chandler\AppData\Roaming\McNeel\Rhinoceros\packages\7.0\Clipper2GH\1.3.2\Clipper2Lib.dll")
    from Clipper2Lib import Paths64, Path64, Point64, Clipper, JoinType, EndType, FillRule
    _HAVE_CLIP = True
except:
    _HAVE_CLIP = False

SIZE = float(size) if size is not None else 12.0
if SIZE < 1.0:
    SIZE = 1.0
# 0 means auto, not zero pitch. A slider cannot send "blank", so the value that
# would otherwise be meaningless is the one that asks for the default.
SP = float(spacing) if spacing is not None else 0.0
if SP <= 0.0:
    SP = SIZE * 1.55
if SP < SIZE * 0.6:
    SP = SIZE * 0.6          # below this they collide however the jitter falls
JIT = float(jitter) if jitter is not None else 0.45
if JIT < 0.0: JIT = 0.0
if JIT > 1.0: JIT = 1.0
SPIN = float(spin) if spin is not None else 360.0
VARY = float(vary) if vary is not None else 0.18
if VARY < 0.0: VARY = 0.0
if VARY > 0.9: VARY = 0.9
FILL = float(fill) if fill is not None else 0.0
if FILL < 0.0: FILL = 0.0
SEED = int(seed) if seed is not None else 1
EDGE = True if keep_edge is None else bool(keep_edge)
ON = True if on is None else bool(on)

# Deterministic LCG. Python's `random` carries state between solves, so the
# same definition would re-scatter every time anything upstream changed - and a
# plot you have half-drawn must not move because you nudged a slider.
_rs = [(SEED * 1103515245 + 12345) & 0x7fffffff]
def _rnd():
    _rs[0] = (_rs[0] * 1103515245 + 12345) & 0x7fffffff
    return _rs[0] / float(0x7fffffff)

# ---- the motif ---------------------------------------------------------------
# Heel is a rounded triangle, apex up. An earlier version dipped the top-centre
# control point inward to suggest the lobes a real pad has; interpolated through
# only ten points that read as a notch bitten out of the pad, not as a lobe. At
# 12mm drawn with a 0.3mm nib none of that detail survives anyway, so the shape
# is kept clean and the silhouette does the work.
# Twelve points rather than ten, with a close pair either side of the apex, so
# the interpolation rounds the top instead of driving it to a spike. A pointed
# pad reads as a leaf; the blunt apex is what makes it a paw.
_HEEL = [(0.00, 0.00), (0.08, -0.03), (0.19, -0.17), (0.28, -0.35),
         (0.26, -0.47), (0.14, -0.52), (0.00, -0.53), (-0.14, -0.52),
         (-0.26, -0.47), (-0.28, -0.35), (-0.19, -0.17), (-0.08, -0.03)]
# (angle from vertical, toe half-width, toe half-height). Middle toes sit
# higher and larger than the outer pair, which is what makes it read as a paw
# rather than four dots on an arc.
#
# Sized and spread so adjacent toes do not touch. Overlapping toes are not just
# ugly here: every crossing is a spot the pen inks twice, which on absorbent
# paper blots and on the plot itself doubles the travel.
_TOES = [(-63.0, 0.062, 0.085), (-23.0, 0.070, 0.095),
         (23.0, 0.070, 0.095), (63.0, 0.062, 0.085)]
_TOE_R = 0.34
_TOE_Y = -0.10

def _paw_unit():
    """the 5 closed curves of one paw, normalised to 1.0 tall about the origin"""
    out = []
    pts = List[rg.Point3d]()
    for (x, y) in _HEEL:
        pts.Add(rg.Point3d(x, y, 0))
    pts.Add(rg.Point3d(_HEEL[0][0], _HEEL[0][1], 0))
    # PERIODIC closure. A plain interpolated curve joined with MakeClosed meets
    # itself at the seam without matching tangents, which put a visible cusp
    # right on the apex - the most looked-at point of the whole motif. Periodic
    # knots make the seam continuous, so where it starts stops mattering.
    heel = None
    try:
        heel = rg.Curve.CreateInterpolatedCurve(pts, 3, rg.CurveKnotStyle.ChordPeriodic)
    except:
        heel = None
    if heel is None:
        heel = rg.Curve.CreateInterpolatedCurve(pts, 3)
        if heel is not None:
            heel.MakeClosed(0.001)
    if heel is not None:
        out.append(heel)
    for (adeg, rx, ry) in _TOES:
        a = math.radians(adeg)
        cx = _TOE_R * math.sin(a)
        cy = _TOE_Y + _TOE_R * math.cos(a)
        pl = rg.Plane(rg.Point3d(cx, cy, 0), rg.Vector3d.ZAxis)
        pl.Rotate(a, rg.Vector3d.ZAxis, rg.Point3d(cx, cy, 0))
        out.append(rg.Ellipse(pl, rx, ry).ToNurbsCurve())
    # Normalise so `size` genuinely means the drawn height in mm. Without this
    # the control points quietly set the scale, and every tweak to the motif
    # would change what the size slider meant.
    bb = rg.BoundingBox.Empty
    for c in out:
        bb.Union(c.GetBoundingBox(True))
    h = bb.Max.Y - bb.Min.Y
    if h > 0.001:
        k = 1.0 / h
        cy = (bb.Max.Y + bb.Min.Y) * 0.5
        xf = (rg.Transform.Scale(rg.Plane.WorldXY, k, k, 1.0)
              * rg.Transform.Translation(0, -cy, 0))
        for c in out:
            c.Transform(xf)
    return out

_UNIT = _paw_unit()

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

def _inside(px, py):
    """even-odd across every region curve, so a closed curve nested inside
    another is a hole and gets no paws - same convention as HATCH"""
    hits = 0
    p = rg.Point3d(px, py, 0)
    for c in cs:
        try:
            if c.Contains(p, rg.Plane.WorldXY, 0.001) == rg.PointContainment.Inside:
                hits += 1
        except:
            pass
    return (hits % 2) == 1

out_crvs = []
info = ''
n_paw = 0
n_drop = 0
if not ON:
    out_crvs = cs
    info = '[BYPASSED]'
elif not cs:
    info = 'needs closed regions'
else:
    if EDGE:
        for c in cs:
            out_crvs.append(c)
    bb = rg.BoundingBox.Empty
    for c in cs:
        bb.Union(c.GetBoundingBox(True))
    # radius that certainly contains a paw at full jittered size, used both to
    # test containment and to keep the grid clear of the boundary
    rmax = 0.52 * SIZE * (1.0 + VARY)
    nx = int((bb.Max.X - bb.Min.X) / SP) + 2
    ny = int((bb.Max.Y - bb.Min.Y) / (SP * 0.87)) + 2
    for iy in range(ny):
        for ix in range(nx):
            # staggered rows: half a pitch every other row, which is how a
            # hex packing beats a square grid for looking unplanned
            sx = bb.Min.X + (ix + (0.5 if (iy % 2) else 0.0)) * SP
            sy = bb.Min.Y + iy * SP * 0.87
            px = sx + (_rnd() - 0.5) * SP * JIT
            py = sy + (_rnd() - 0.5) * SP * JIT
            rot = math.radians(_rnd() * SPIN)
            scl = SIZE * (1.0 + (_rnd() - 0.5) * 2.0 * VARY)
            # cheap reject first: centre out of the region, or too close to the
            # edge for the whole paw to fit
            if not _inside(px, py):
                n_drop += 1
                continue
            ok = True
            for k in range(12):
                a = k * math.pi / 6.0
                if not _inside(px + rmax*math.cos(a), py + rmax*math.sin(a)):
                    ok = False
                    break
            if not ok:
                n_drop += 1
                continue
            xf = (rg.Transform.Translation(px, py, 0)
                  * rg.Transform.Rotation(rot, rg.Vector3d.ZAxis, rg.Point3d(0, 0, 0))
                  * rg.Transform.Scale(rg.Plane.WorldXY, scl, scl, 1.0))
            pads = []
            for u in _UNIT:
                d = u.DuplicateCurve()
                d.Transform(xf)
                pads.append(d)
                out_crvs.append(d)
            n_paw += 1
            # ---- optional concentric darkening inside each pad ----
            if FILL > 0.01 and _HAVE_CLIP:
                SCALE = 1000.0
                for pad in pads:
                    paths = Paths64()
                    plc = pad.ToPolyline(0.05, 0.2, 0.01, 1e6)
                    if plc is None:
                        continue
                    path = Path64()
                    for i in range(plc.PointCount - 1):
                        q = plc.Point(i)
                        path.Add(Point64(int(round(q.X*SCALE)), int(round(q.Y*SCALE))))
                    paths.Add(path)
                    paths = Clipper.Union(paths, FillRule.EvenOdd)
                    d = FILL
                    rounds = 0
                    while rounds < 200:
                        sh = Clipper.InflatePaths(paths, -d*SCALE, JoinType.Round, EndType.Polygon)
                        if sh is None or sh.Count == 0:
                            break
                        for pth in sh:
                            if pth.Count < 3:
                                continue
                            ip = List[rg.Point3d]()
                            for pt in pth:
                                ip.Add(rg.Point3d(pt.X/SCALE, pt.Y/SCALE, 0))
                            ip.Add(rg.Point3d(pth[0].X/SCALE, pth[0].Y/SCALE, 0))
                            out_crvs.append(rg.PolylineCurve(ip))
                        d += FILL
                        rounds += 1
    info = '%d paws, %d rejected for not fitting | size %.1fmm pitch %.1fmm jitter %.2f' % (
        n_paw, n_drop, SIZE, SP, JIT)
    if FILL > 0.01 and not _HAVE_CLIP:
        info += ' | FILL IGNORED: Clipper2 not loaded, outlines only'
    if n_open:
        info += ' | %d open curve(s) skipped' % n_open
    if n_paw == 0:
        info += ' | nothing placed - region may be smaller than one paw'

print(info)
