# BORDER / FRAME - a tunable rule around the artwork.
#
# Every plot that reads as a finished print has one, and until now it meant
# hand-drawing a rectangle in Rhino and internalising it - which meant it never
# tracked the artwork when the size or the placement changed. This takes the
# same rect the image processors already use and draws a proper border from it,
# so the frame and the picture stay in step by construction.
#
# Drawn in ARTWORK space, before PLACE. That is deliberate: the frame is part of
# the drawing, so it scales, rotates and lands with everything else. A border
# generated after placement would sit in machine coordinates and drift off the
# page the moment `fit to paper` changed.
#
#   inset   mm in from the rect edge. NEGATIVE pushes the frame outside it, which
#           is usually what you want - a border touching the artwork looks like
#           a mistake.
#   lines   how many concentric rules
#   gap     mm between them
#   radius  corner radius, 0 = square
#   corners 0 plain | 1 corner ticks | 2 crosses | 3 open corners (crop marks)
#   tick    length in mm of the ticks, crosses, or the corner gap in mode 3
#
# PROCESSOR CONTRACT: a rect in, border curves out (`out_crvs`) -> a LAYER slot.
# Inputs: rect(curve), inset(mm), lines(int), gap(mm), radius(mm),
#         corners(int 0-3), tick(mm), on(bool bypass)
import Rhino.Geometry as rg
import rhinoscriptsyntax as rs
import scriptcontext as sc
try:
    sc.doc = ghdoc
except:
    pass

ON = True if on is None else bool(on)
INSET = float(inset) if inset is not None else -6.0
N = int(lines) if lines is not None else 2
if N < 1: N = 1
if N > 12: N = 12
GAP = float(gap) if gap is not None else 2.0
if GAP < 0.0: GAP = 0.0
RAD = float(radius) if radius is not None else 0.0
if RAD < 0.0: RAD = 0.0
CORN = int(corners) if corners is not None else 0
if CORN < 0: CORN = 0
if CORN > 3: CORN = 3
TICK = float(tick) if tick is not None else 4.0
if TICK < 0.0: TICK = 0.0

out_crvs = []
info = ''

rc = None
if rect is not None:
    rc = rect if isinstance(rect, rg.Curve) else rs.coercecurve(rect)

if not ON:
    info = '[BYPASSED]'
elif rc is None:
    info = 'needs a rect (wire the artwork frame)'
else:
    bb = rc.GetBoundingBox(True)
    x0 = bb.Min.X; y0 = bb.Min.Y; x1 = bb.Max.X; y1 = bb.Max.Y
    made = 0
    skipped = 0
    for i in range(N):
        d = INSET + i * GAP
        ax0 = x0 + d; ay0 = y0 + d; ax1 = x1 - d; ay1 = y1 - d
        w = ax1 - ax0; h = ay1 - ay0
        # An inset deep enough to invert the rect would fold the border inside
        # out. Stop rather than emit a knot the pen has to draw.
        if w <= 0.5 or h <= 0.5:
            skipped += 1
            continue
        if CORN == 3:
            # open corners: four separate rules, each held back from the corner
            t = TICK
            if t * 2.0 >= w: t = (w - 0.5) / 2.0
            if t * 2.0 >= h: t = min(t, (h - 0.5) / 2.0)
            if t < 0.0: t = 0.0
            segs = [((ax0 + t, ay0), (ax1 - t, ay0)),
                    ((ax1, ay0 + t), (ax1, ay1 - t)),
                    ((ax1 - t, ay1), (ax0 + t, ay1)),
                    ((ax0, ay1 - t), (ax0, ay0 + t))]
            for a, b in segs:
                ln = rg.LineCurve(rg.Point3d(a[0], a[1], 0), rg.Point3d(b[0], b[1], 0))
                out_crvs.append(ln); made += 1
        else:
            pl = rg.Polyline([rg.Point3d(ax0, ay0, 0), rg.Point3d(ax1, ay0, 0),
                              rg.Point3d(ax1, ay1, 0), rg.Point3d(ax0, ay1, 0),
                              rg.Point3d(ax0, ay0, 0)])
            crv = pl.ToNurbsCurve()
            if RAD > 0.0:
                r = RAD
                if r > (w / 2.0 - 0.1): r = w / 2.0 - 0.1
                if r > (h / 2.0 - 0.1): r = h / 2.0 - 0.1
                if r > 0.0:
                    f = rg.Curve.CreateFilletCornersCurve(crv, r, 0.001, 0.001)
                    if f is not None:
                        crv = f
            out_crvs.append(crv); made += 1
            if CORN in (1, 2) and i == 0:
                # ticks / crosses ride on the OUTERMOST rule only - repeating them
                # on every concentric line reads as noise, not as a corner mark
                for cx, cy, sx, sy in ((ax0, ay0, -1.0, -1.0), (ax1, ay0, 1.0, -1.0),
                                       (ax1, ay1, 1.0, 1.0), (ax0, ay1, -1.0, 1.0)):
                    out_crvs.append(rg.LineCurve(
                        rg.Point3d(cx, cy, 0), rg.Point3d(cx + sx * TICK, cy, 0)))
                    out_crvs.append(rg.LineCurve(
                        rg.Point3d(cx, cy, 0), rg.Point3d(cx, cy + sy * TICK, 0)))
                    made += 2
                    if CORN == 2:
                        out_crvs.append(rg.LineCurve(
                            rg.Point3d(cx - sx * TICK, cy, 0), rg.Point3d(cx, cy, 0)))
                        out_crvs.append(rg.LineCurve(
                            rg.Point3d(cx, cy - sy * TICK, 0), rg.Point3d(cx, cy, 0)))
                        made += 2
    STYLE = ['plain', 'corner ticks', 'crosses', 'open corners']
    info = 'FRAME: %d curves | %d rule(s) inset %.1f gap %.1f, %s' % (
        len(out_crvs), N - skipped, INSET, GAP, STYLE[CORN])
    if RAD > 0.0:
        info += ', radius %.1f' % RAD
    if skipped:
        info += ' | %d rule(s) dropped - inset deeper than the rect is wide' % skipped
    if INSET > 0.0:
        info += ' | inset is POSITIVE so the frame sits INSIDE the artwork'
print(info)
