# DASH processor - template for curves->curves processing blocks.
# THE PROCESSOR CONTRACT: input `crvs` (list of curves, art-space mm) -> output
# `out_crvs` (list of curves). Splice between any generator and a LAYER slot;
# blocks chain in any order. `on` = bypass toggle (False passes curves through
# untouched, so a chain can be A/B'd without rewiring).
# DASH: walks each curve emitting alternating dash/gap segments.
# Inputs: crvs(list), dash(mm), gap(mm), phase(mm, slides the pattern), on(bool)
import Rhino.Geometry as rg
import rhinoscriptsyntax as rs
import scriptcontext as sc
try:
    sc.doc = ghdoc
except:
    pass

DASH = float(dash) if dash is not None else 6.0
if DASH < 0.2:
    DASH = 0.2
GAP = float(gap) if gap is not None else 3.0
if GAP < 0.0:
    GAP = 0.0
PHASE = float(phase) if phase is not None else 0.0
ON = True if on is None else bool(on)

cs = []
if crvs:
    for c in crvs:
        cc = c if isinstance(c, rg.Curve) else rs.coercecurve(c)
        if cc is not None:
            cs.append(cc)

out_crvs = []
if not ON or GAP <= 0.01:
    out_crvs = cs                      # bypass
else:
    period = DASH + GAP
    for c in cs:
        clen = c.GetLength()
        if clen is None or clen < 0.05:
            continue
        s = -(PHASE % period)
        made = 0
        while s < clen:
            a = s
            b = s + DASH
            if a < 0.0:
                a = 0.0
            if b > clen:
                b = clen
            if b > a + 0.05:
                ok_a = c.LengthParameter(a)
                ok_b = c.LengthParameter(b)
                # LengthParameter returns (bool, t) in IronPython
                ta = ok_a[1] if isinstance(ok_a, tuple) else ok_a
                tb = ok_b[1] if isinstance(ok_b, tuple) else ok_b
                seg = c.Trim(ta, tb)
                if seg is not None:
                    out_crvs.append(seg)
                    made += 1
            s += period
print('%d curves -> %d dashes (dash %.1f / gap %.1f)%s' % (len(cs), len(out_crvs), DASH, GAP, '' if ON else ' [BYPASSED]'))
