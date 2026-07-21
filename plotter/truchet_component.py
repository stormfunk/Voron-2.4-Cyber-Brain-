# TRUCHET processor - fills closed regions with randomly rotated Truchet tiles.
# Each tile carries two quarter-arcs (or two diagonals) joining edge midpoints,
# so neighbouring tiles link up into long meandering loops - woven labyrinths
# from almost no code. Touching ends are chained into continuous strokes, so a
# whole field plots with very few pen lifts.
# PROCESSOR CONTRACT: closed curves in (`crvs`) -> tile linework out (`out_crvs`).
# Inputs: crvs(list, closed), cell(mm tile size), seed(int), style(0 arcs,
#         1 diagonals), inset(mm), keep_edge(bool), on(bool bypass)
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


def tile_flip(ix, iy, sd):
    """deterministic 0/1 per tile (pure function)"""
    n = (ix * 73856093) ^ (iy * 19349663) ^ (sd * 83492791)
    n = n & 0x7FFFFFFF
    n = (n * 1103515245 + 12345) & 0x7FFFFFFF
    return (n >> 16) & 1


def arc_pts(cx, cy, r, a0, a1, n):
    """polyline points along an arc (pure function)"""
    out = []
    for i in range(n + 1):
        a = a0 + (a1 - a0) * (float(i) / n)
        out.append((cx + math.cos(a) * r, cy + math.sin(a) * r))
    return out


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


CELL = float(cell) if cell is not None else 8.0
if CELL < 0.5:
    CELL = 0.5
SEED = int(seed) if seed is not None else 1
STYLE = int(style) if style is not None else 0
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
info = ''
if not ON:
    out_crvs = cs
    info = '[BYPASSED]'
elif cs:
    if EDGE:
        for c in cs:
            out_crvs.append(c)

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
    ncx = int(math.ceil((bb.Max.X - x0) / CELL))
    ncy = int(math.ceil((bb.Max.Y - y0) / CELL))
    plane = rg.Plane.WorldXY
    tol = 0.001
    arcseg = 8
    r = CELL * 0.5

    # build tile strokes, keeping only tiles whose centre is inside the region
    strokes = []
    n_tiles = 0
    for jy in range(ncy):
        for ix in range(ncx):
            tx = x0 + ix * CELL
            ty = y0 + jy * CELL
            ctr = rg.Point3d(tx + r, ty + r, 0)
            hits = 0
            for c in regions:
                if c.Contains(ctr, plane, tol) == rg.PointContainment.Inside:
                    hits += 1
            if (hits % 2) == 0:
                continue
            n_tiles += 1
            flip = tile_flip(ix, jy, SEED)
            if STYLE == 1:
                if flip == 0:
                    strokes.append([(tx, ty + r), (tx + r, ty)])
                    strokes.append([(tx + r, ty + CELL), (tx + CELL, ty + r)])
                else:
                    strokes.append([(tx, ty + r), (tx + r, ty + CELL)])
                    strokes.append([(tx + r, ty), (tx + CELL, ty + r)])
            else:
                if flip == 0:
                    strokes.append(arc_pts(tx, ty, r, 0.0, math.pi * 0.5, arcseg))
                    strokes.append(arc_pts(tx + CELL, ty + CELL, r, math.pi, math.pi * 1.5, arcseg))
                else:
                    strokes.append(arc_pts(tx + CELL, ty, r, math.pi * 0.5, math.pi, arcseg))
                    strokes.append(arc_pts(tx, ty + CELL, r, math.pi * 1.5, math.pi * 2.0, arcseg))

    # chain strokes that share endpoints into continuous runs (fewer pen lifts)
    jt = CELL * 0.05
    used = [False] * len(strokes)
    for si in range(len(strokes)):
        if used[si]:
            continue
        used[si] = True
        chain = list(strokes[si])
        # grow from BOTH ends - arcs meet at edge midpoints, so a Truchet field
        # links into long meandering loops if you follow them both ways
        for endsel in [1, 0]:
            grew = True
            while grew:
                grew = False
                if endsel == 1:
                    ex = chain[-1][0]
                    ey = chain[-1][1]
                else:
                    ex = chain[0][0]
                    ey = chain[0][1]
                for sj in range(len(strokes)):
                    if used[sj]:
                        continue
                    s = strokes[sj]
                    fwd = (abs(s[0][0] - ex) < jt and abs(s[0][1] - ey) < jt)
                    bwd = (abs(s[-1][0] - ex) < jt and abs(s[-1][1] - ey) < jt)
                    if not fwd and not bwd:
                        continue
                    used[sj] = True
                    piece = list(s)
                    if bwd:
                        piece.reverse()
                    if endsel == 1:
                        chain = chain + piece[1:]
                    else:
                        piece.reverse()
                        chain = piece[:-1] + chain
                    grew = True
                    break
        lp = List[rg.Point3d]()
        for q in chain:
            lp.Add(rg.Point3d(q[0], q[1], 0))
        out_crvs.append(rg.PolylineCurve(lp))
    info = 'cell %.1fmm, %d tiles, style %s, seed %d' % (CELL, n_tiles, 'diagonals' if STYLE == 1 else 'arcs', SEED)

print('%d regions (%d open skipped) -> %d stroke(s) | %s' % (len(cs), n_open, len(out_crvs), info))
