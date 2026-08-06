# PEN TAPS - choose a point source and assign it a pen, in one box.
#
# Was two components wired in series (DOTSPICK -> DOTS) inside the same group,
# which is two boxes and two labels for one idea: "which dots, and which pen".
#
# Taps are DWELLS, not strokes: every point is one press of the pen. A halftone
# POINTILLISM pass emits ~10k of them, so the source list defaults to OFF and
# the info line shouts when the count gets expensive.
#
# src: 0 = OFF (channel dead, costs nothing)
#      1 = GEN (warped mesh)   2 = POINTILLISM.pts   3 = STIPPLE.pts
#
# pen 0 = OFF emits NOTHING - not an empty list of dots that still exist. Dots
# that will not plot must never reach PLACE, or they still count toward the
# artwork bounding box and shove the centring of everything else off. Same rule
# the LAYER TABLE uses for pen 0.
#
# PROCESSOR CONTRACT: candidate point streams in, placed-ready dots out.
# Inputs: pts_gen, pts_point, pts_stip (list), src (int 0-3), pen (int 0-8)
import Rhino.Geometry as rg
import rhinoscriptsyntax as rs
import scriptcontext as sc
try:
    sc.doc = ghdoc
except:
    pass

S = 0
try:
    if src is not None:
        S = int(float(str(src)))
except:
    S = 0
if S < 0: S = 0
if S > 3: S = 3
PN = 0 if pen is None else int(pen)

NAMES = ['OFF', 'GEN (warped mesh)', 'POINTILLISM', 'STIPPLE']
cands = [None, pts_gen, pts_point, pts_stip]
sel = cands[S] if S else None
raw = [p for p in sel if p is not None] if sel else []

# ingest: points, or small closed curves/circles (use their centre)
dots = []
if raw and PN >= 1:
    for d in raw:
        if isinstance(d, rg.Point3d):
            dots.append(rg.Point3d(d)); continue
        p3 = rs.coerce3dpoint(d)
        if p3 is not None:
            dots.append(rg.Point3d(p3)); continue
        c = d if isinstance(d, rg.Curve) else rs.coercecurve(d)
        if c is not None:
            bb = c.GetBoundingBox(True)
            dots.append(rg.Point3d((bb.Min.X + bb.Max.X) / 2.0,
                                   (bb.Min.Y + bb.Max.Y) / 2.0, 0))

if S == 0:
    info = 'PEN TAPS: source OFF - no pen taps'
elif PN < 1:
    info = 'PEN TAPS: %s has %d points but pen is OFF -> none emitted (kept out of placement)' % (
        NAMES[S], len(raw))
else:
    info = 'PEN TAPS: %s -> %d taps on pen %d' % (NAMES[S], len(dots), PN)
    if not raw:
        info += ' | source is empty - is that component off in the PLOT RECIPE?'
    elif len(dots) > 3000:
        info += ' | that is a LOT of pen presses - check the time estimate before plotting'
print(info)
