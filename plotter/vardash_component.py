# VARIABLE DASH processor - dashing whose ink/gap balance CHANGES along the
# stroke. The period (dash+gap) stays constant so the rhythm reads as even,
# but the fraction of each period that is inked is driven by:
#   mode 0: position along the line (0% at the start -> 100% at the end)
#   mode 1: proximity to attractors (points and/or curves in `attract`)
# At driver = 0 the line is nearly solid; at driver = 1 it thins to `min_ink`.
# `invert` flips the direction (dissolve near vs far / start vs end).
# Pressure Z survives - pieces are sampled from the source curve.
# PROCESSOR CONTRACT: curves in (`crvs`) -> dashed curves out (`out_crvs`).
# `scatter` (0-1) de-synchronises the pattern across an array of lines: each
# curve gets a random phase shift (deterministic per curve index, so plots are
# repeatable) and each dash a little length jitter - kills the moire "columns"
# you get when parallel lines all dash in lockstep.
# Inputs: crvs(list), dash(mm), gap(mm), mode(0/1), attract(list, pts/crvs),
#         radius(mm, proximity falloff), min_ink(0-0.9, ink fraction at full
#         effect), scatter(0-1), invert(bool), on(bool bypass)
import Rhino
import Rhino.Geometry as rg
import rhinoscriptsyntax as rs
import scriptcontext as sc
import math
from System.Collections.Generic import List
try:
    sc.doc = ghdoc
except:
    pass

DASH = float(dash) if dash is not None else 6.0
if DASH < 0.3:
    DASH = 0.3
GAP = float(gap) if gap is not None else 3.0
if GAP < 0.1:
    GAP = 0.1
MODE = int(mode) if mode is not None else 0
RAD = float(radius) if radius is not None else 50.0
if RAD < 1.0:
    RAD = 1.0
MINI = float(min_ink) if min_ink is not None else 0.08
if MINI < 0.0:
    MINI = 0.0
if MINI > 0.9:
    MINI = 0.9
SCAT = float(scatter) if scatter is not None else 0.35
if SCAT < 0.0:
    SCAT = 0.0
if SCAT > 1.0:
    SCAT = 1.0
INV = False if invert is None else bool(invert)
ON = True if on is None else bool(on)
PERIOD = DASH + GAP
MAXI = 0.96                     # ink fraction at zero effect (nearly solid)
STEP = 0.8                      # sampling step along ink pieces, mm

cs = []
if crvs:
    for c in crvs:
        cc = c if isinstance(c, rg.Curve) else rs.coercecurve(c)
        if cc is not None:
            cs.append(cc)

# attractors: points and curves both welcome
apts = []
acrvs = []
if attract:
    for a in attract:
        if isinstance(a, rg.Point3d):
            apts.append(rg.Point3d(a.X, a.Y, 0))
            continue
        p3 = rs.coerce3dpoint(a)
        if p3 is not None:
            apts.append(rg.Point3d(p3.X, p3.Y, 0))
            continue
        ac = a if isinstance(a, rg.Curve) else rs.coercecurve(a)
        if ac is not None:
            acrvs.append(ac)

out_crvs = []
info = ''
if not ON:
    out_crvs = cs
    info = '[BYPASSED]'
elif cs:
    n_pieces = 0
    for ci in range(len(cs)):
        c = cs[ci]
        L = c.GetLength()
        if L < 0.05:
            continue
        # deterministic per-curve LCG for phase + jitter (repeatable plots)
        rst = ((ci + 1) * 2654435761 + 12345) & 0x7FFFFFFF
        rst = (rst * 1103515245 + 12345) & 0x7FFFFFFF
        phase = (rst / 2147483647.0) * PERIOD * SCAT
        s = -phase          # virtual pattern start before the curve begins
        ink = True
        guard = 0
        while s < L - 0.02 and guard < 20000:
            guard += 1
            s_eval = s if s > 0.0 else 0.0
            ok, t = c.LengthParameter(s_eval)
            if not ok:
                break
            pt = c.PointAt(t)
            # driver value 0..1 at this position
            if MODE == 1:
                d = 1e9
                probe = rg.Point3d(pt.X, pt.Y, 0)
                for ap in apts:
                    dd = probe.DistanceTo(ap)
                    if dd < d:
                        d = dd
                for ac in acrvs:
                    rc2, t2 = ac.ClosestPoint(probe)
                    if rc2:
                        q = ac.PointAt(t2)
                        dd = math.sqrt((q.X-probe.X)**2 + (q.Y-probe.Y)**2)
                        if dd < d:
                            d = dd
                if d > 1e8:
                    v = 0.0
                else:
                    v = 1.0 - d / RAD
                    if v < 0.0:
                        v = 0.0
                    if v > 1.0:
                        v = 1.0
            else:
                v = s / L
            if INV:
                v = 1.0 - v
            duty = MAXI - (MAXI - MINI) * v
            ink_len = PERIOD * duty
            gap_len = PERIOD - ink_len
            # per-segment length jitter
            if SCAT > 0.001:
                rst = (rst * 1103515245 + 12345) & 0x7FFFFFFF
                jit = 1.0 + ((rst / 2147483647.0) * 2.0 - 1.0) * 0.5 * SCAT
                ink_len = ink_len * jit
                gap_len = gap_len * jit
            if ink:
                e = s + ink_len
                s0 = s if s > 0.0 else 0.0        # clip the phase-shifted start
                e0 = e if e < L else L
                if e0 - s0 > 0.05:
                    n = int((e0 - s0) / STEP)
                    if n < 1:
                        n = 1
                    lp = List[rg.Point3d]()
                    for k in range(n + 1):
                        ok2, tk = c.LengthParameter(s0 + (e0 - s0) * k / float(n))
                        if ok2:
                            lp.Add(c.PointAt(tk))
                    if lp.Count >= 2:
                        out_crvs.append(rg.PolylineCurve(lp))
                        n_pieces += 1
                s = e
            else:
                s = s + gap_len
            ink = not ink
    info = 'P=%.1fmm, ink %.0f%%..%.0f%%, %s%s, scatter %.2f, %d pieces' % (
        PERIOD, MINI*100, MAXI*100,
        ('proximity r=%.0fmm (%d pts, %d crvs)' % (RAD, len(apts), len(acrvs))) if MODE == 1 else 'along length',
        ' [inverted]' if INV else '', SCAT, n_pieces)

print('%d curves -> %d dashes | %s' % (len(cs), len(out_crvs), info))
