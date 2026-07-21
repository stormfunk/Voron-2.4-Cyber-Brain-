# FLOW FIELD processor - fills closed regions with streamlines traced through a
# procedural noise field. Produces long, flowing, continuous strokes (few pen
# lifts) with the signature look of generative plotter art.
# Streamlines are kept evenly spaced (Jobard & Lefebvre style): a new line stops
# when it comes within `spacing` of an already-drawn one, so the field fills
# without clumping.
# PROCESSOR CONTRACT: closed curves in (`crvs`) -> flow linework out (`out_crvs`).
# Inputs: crvs(list, closed), spacing(mm between streamlines), scale(mm, size of
#         the field's swirls), turbulence(0-3, how much the field twists),
#         seed(int), inset(mm), on(bool bypass)
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


def lattice(ix, iy, sd):
    """deterministic 0..1 hash at an integer lattice point (pure function)"""
    n = (ix * 73856093) ^ (iy * 19349663) ^ (sd * 83492791)
    n = n & 0x7FFFFFFF
    n = (n * 1103515245 + 12345) & 0x7FFFFFFF
    return (n % 65536) / 65535.0


def vnoise(x, y, sd):
    """smooth value noise in 0..1 (bilinear + smoothstep between lattice points)"""
    ix = int(math.floor(x))
    iy = int(math.floor(y))
    fx = x - ix
    fy = y - iy
    ux = fx * fx * (3.0 - 2.0 * fx)
    uy = fy * fy * (3.0 - 2.0 * fy)
    v00 = lattice(ix, iy, sd)
    v10 = lattice(ix + 1, iy, sd)
    v01 = lattice(ix, iy + 1, sd)
    v11 = lattice(ix + 1, iy + 1, sd)
    a = v00 + (v10 - v00) * ux
    b = v01 + (v11 - v01) * ux
    return a + (b - a) * uy


def field_angle(x, y, sc_mm, turb, sd):
    """two-octave noise -> flow direction in radians (pure function)"""
    n = vnoise(x / sc_mm, y / sc_mm, sd)
    n = n + 0.5 * vnoise(x / (sc_mm * 0.45), y / (sc_mm * 0.45), sd + 17)
    return (n / 1.5) * turb * 2.0 * math.pi


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


SP = float(spacing) if spacing is not None else 2.0
if SP < 0.3:
    SP = 0.3
SCL = float(scale) if scale is not None else 60.0
if SCL < 1.0:
    SCL = 1.0
TURB = float(turbulence) if turbulence is not None else 1.0
SEED = int(seed) if seed is not None else 1
INS = float(inset) if inset is not None else 0.75
if INS < 0.0:
    INS = 0.0
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
    regions = cs
    if INS > 0.01:
        shrunk = shrink_regions(cs, INS, 1000.0)
        if shrunk:
            regions = shrunk

    bb = rg.BoundingBox.Empty
    for c in regions:
        bb.Union(c.GetBoundingBox(True))
    x0 = bb.Min.X
    y0 = bb.Min.Y
    wid = bb.Max.X - x0
    hei = bb.Max.Y - y0

    STEP = max(0.4, SP * 0.5)          # integration step
    MAXPTS = 400                       # per streamline
    TOTALCAP = 120000                  # global safety cap

    # --- precompute an inside-bitmap once (native Contains is the slow part) ---
    gc = max(STEP, SP * 0.5)
    nx = int(math.ceil(wid / gc)) + 2
    ny = int(math.ceil(hei / gc)) + 2
    plane = rg.Plane.WorldXY
    tol = 0.001
    inside = []
    for j in range(ny):
        row = []
        py = y0 + (j - 0.5) * gc
        for i in range(nx):
            px = x0 + (i - 0.5) * gc
            pt = rg.Point3d(px, py, 0)
            hits = 0
            for c in regions:
                if c.Contains(pt, plane, tol) == rg.PointContainment.Inside:
                    hits += 1
            row.append((hits % 2) == 1)
        inside.append(row)

    # --- occupancy grid for streamline separation ---
    og = max(SP, 0.3)
    onx = int(math.ceil(wid / og)) + 3
    ony = int(math.ceil(hei / og)) + 3
    occ = {}

    seeds = []
    ss = SP * 0.9
    sny = int(math.ceil(hei / ss)) + 1
    snx = int(math.ceil(wid / ss)) + 1
    for j in range(sny):
        for i in range(snx):
            seeds.append((x0 + i * ss, y0 + j * ss))

    made_pts = 0
    for sd_i in range(len(seeds)):
        if made_pts > TOTALCAP:
            break
        sxp = seeds[sd_i][0]
        syp = seeds[sd_i][1]
        gi = int((sxp - x0) / og) + 1
        gj = int((syp - y0) / og) + 1
        busy = False
        for dj in [-1, 0, 1]:
            for di in [-1, 0, 1]:
                if (gi + di, gj + dj) in occ:
                    for q in occ[(gi + di, gj + dj)]:
                        dx = q[0] - sxp
                        dy = q[1] - syp
                        if dx * dx + dy * dy < SP * SP:
                            busy = True
                            break
                if busy:
                    break
            if busy:
                break
        if busy:
            continue
        bi = int((sxp - x0) / gc) + 1
        bj = int((syp - y0) / gc) + 1
        if bj < 0 or bj >= ny or bi < 0 or bi >= nx or not inside[bj][bi]:
            continue

        # trace backwards then forwards from the seed
        chain = []
        for direction in [-1.0, 1.0]:
            px = sxp
            py = syp
            leg = []
            for k in range(MAXPTS):
                ang = field_angle(px, py, SCL, TURB, SEED)
                mx = px + math.cos(ang) * STEP * 0.5 * direction
                my = py + math.sin(ang) * STEP * 0.5 * direction
                ang2 = field_angle(mx, my, SCL, TURB, SEED)
                px = px + math.cos(ang2) * STEP * direction
                py = py + math.sin(ang2) * STEP * direction
                bi = int((px - x0) / gc) + 1
                bj = int((py - y0) / gc) + 1
                if bj < 0 or bj >= ny or bi < 0 or bi >= nx or not inside[bj][bi]:
                    break
                gi = int((px - x0) / og) + 1
                gj = int((py - y0) / og) + 1
                hit = False
                for dj in [-1, 0, 1]:
                    for di in [-1, 0, 1]:
                        key = (gi + di, gj + dj)
                        if key in occ:
                            for q in occ[key]:
                                dx = q[0] - px
                                dy = q[1] - py
                                if dx * dx + dy * dy < SP * SP:
                                    hit = True
                                    break
                        if hit:
                            break
                    if hit:
                        break
                if hit:
                    break
                leg.append((px, py))
            if direction < 0:
                leg.reverse()
                chain = leg + [(sxp, syp)]
            else:
                chain = chain + leg
        if len(chain) < 3:
            continue
        lp = List[rg.Point3d]()
        for q in chain:
            lp.Add(rg.Point3d(q[0], q[1], 0))
            gi = int((q[0] - x0) / og) + 1
            gj = int((q[1] - y0) / og) + 1
            if (gi, gj) not in occ:
                occ[(gi, gj)] = []
            occ[(gi, gj)].append(q)
        made_pts += len(chain)
        out_crvs.append(rg.PolylineCurve(lp))
    info = 'spacing %.2fmm, scale %.0fmm, turb %.2f, seed %d, %d pts' % (SP, SCL, TURB, SEED, made_pts)

print('%d regions (%d open skipped) -> %d streamline(s) | %s' % (len(cs), n_open, len(out_crvs), info))
