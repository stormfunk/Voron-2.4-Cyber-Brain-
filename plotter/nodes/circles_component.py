# CONCENTRIC CIRCLES generator - nested circles with DIRECT density control at
# three radial zones: centre (innermost), inner (mid-radius) and outer edge.
# Density = how tightly the rings pack. Higher density -> smaller gaps -> more
# rings crowded into that zone. The three values are smoothly blended along the
# radius, so you sculpt the distribution with three sliders.
#   density_center : t = 0   (the middle)
#   density_inner  : t = 0.5 (mid-radius)
#   density_outer  : t = 1   (outer edge)
# `graph` is an OPTIONAL freeform multiplier (wire a Graph Mapper if you want a
# custom profile on top of the three zones); unwired it is neutral.
# Output: crvs (concentric circle curves, ready for a LAYER slot or a processor)
import Rhino.Geometry as rg
import rhinoscriptsyntax as rs
import scriptcontext as sc
try:
    sc.doc = ghdoc
except:
    pass

CNT = int(count) if count is not None else 40
if CNT < 1:
    CNT = 1
SP = float(spacing) if spacing is not None else 5.0
if SP < 0.01:
    SP = 0.01
INNER = float(inner) if inner is not None else 2.0
if INNER < 0.0:
    INNER = 0.0
MING = float(min_gap) if min_gap is not None else 0.15
if MING < 0.0:
    MING = 0.0

DC = float(density_center) if density_center is not None else 1.0
DM = float(density_inner) if density_inner is not None else 1.0
DO = float(density_outer) if density_outer is not None else 1.0
if DC < 0.05:
    DC = 0.05
if DM < 0.05:
    DM = 0.05
if DO < 0.05:
    DO = 0.05

# centre point - from an XY pad, else bed centre
cx = 175.0
cy = 175.0
if center is not None:
    p = center if isinstance(center, rg.Point3d) else rs.coerce3dpoint(center)
    if p is not None:
        cx = p.X
        cy = p.Y

# optional freeform multiplier (Graph Mapper output); neutral if unwired
gv = []
if graph:
    for g in graph:
        try:
            gv.append(float(g))
        except:
            pass
if not gv:
    gv = [1.0]


def density_at(u):
    """smooth 3-point blend of the centre/inner/outer densities (pure - no free
    vars: reads the module-level DC/DM/DO, no closures)"""
    if u <= 0.5:
        f = u / 0.5
        f = f * f * (3.0 - 2.0 * f)
        return DC * (1.0 - f) + DM * f
    f = (u - 0.5) / 0.5
    f = f * f * (3.0 - 2.0 * f)
    return DM * (1.0 - f) + DO * f


def graph_at(u):
    vals = gv
    n = len(vals)
    if n == 1:
        return vals[0]
    x = u * (n - 1)
    i = int(x)
    if i >= n - 1:
        return vals[-1]
    f = x - i
    return vals[i] * (1.0 - f) + vals[i + 1] * f


crvs = []
radii = []
pl = rg.Plane.WorldXY
pl.Origin = rg.Point3d(cx, cy, 0)
r = INNER
for i in range(CNT):
    u = i / float(CNT - 1) if CNT > 1 else 0.0
    d = density_at(u)
    if d < 0.05:
        d = 0.05
    gap = SP / d * graph_at(u)
    if gap < MING:
        gap = MING
    r += gap
    crvs.append(rg.Circle(pl, r).ToNurbsCurve())
    radii.append(r)

print('%d circles, radii %.1f..%.1f mm | density c/i/o = %.2f/%.2f/%.2f%s' % (
    CNT, radii[0] if radii else 0.0, radii[-1] if radii else 0.0, DC, DM, DO,
    ' x graph' if len(gv) > 1 else ''))
