# CHROMATIC ABERRATION processor - duplicates input curves into up to 6 copies
# offset progressively along a direction. Wire step1..step6 into LAYER slots in
# your ink sequence (e.g. red, orange, white, light blue, dark blue, black) -
# step1 sits at the input position, each next step shifts one step_mm further
# along the direction. Higher pen numbers plot later = overprint on top, so put
# the "core" colour (black) on the highest pen.
# PROCESSOR CONTRACT variant: curves in -> SIX curve outputs (per colour step).
# Inputs: crvs(list), angle(deg, 0 = +X), step_mm(offset between steps),
#         steps(int 1-6, active outputs), on(bool bypass: step1 = passthrough)
import Rhino.Geometry as rg
import rhinoscriptsyntax as rs
import scriptcontext as sc
import math
try:
    sc.doc = ghdoc
except:
    pass

ANG = float(angle) if angle is not None else 0.0
STEP = float(step_mm) if step_mm is not None else 1.2
if STEP < 0.05:
    STEP = 0.05
N = int(steps) if steps is not None else 6
if N < 1: N = 1
if N > 6: N = 6
ON = True if on is None else bool(on)

cs = []
if crvs:
    for c in crvs:
        cc = c if isinstance(c, rg.Curve) else rs.coercecurve(c)
        if cc is not None:
            cs.append(cc)

_dx = math.cos(math.radians(ANG))
_dy = math.sin(math.radians(ANG))

_outs = [[], [], [], [], [], []]
if not ON:
    _outs[0] = cs                        # bypass: originals on step1 only
else:
    for k in range(N):
        xf = rg.Transform.Translation(_dx*STEP*k, _dy*STEP*k, 0)
        for c in cs:
            d = c.DuplicateCurve()
            d.Transform(xf)
            _outs[k].append(d)

step1 = _outs[0]
step2 = _outs[1]
step3 = _outs[2]
step4 = _outs[3]
step5 = _outs[4]
step6 = _outs[5]
print('%d curves -> %d steps x %.2fmm at %.0fdeg%s' % (len(cs), N if ON else 1, STEP, ANG, '' if ON else ' [BYPASSED]'))
