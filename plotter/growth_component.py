# DIFFERENTIAL GROWTH processor - a closed loop that repels itself, pulls on its
# own neighbours and subdivides as it stretches, folding into coral / brain /
# intestinal forms. Grows inside the input region and is stopped by its walls,
# so the region acts as a mould.
# Output is ONE continuous closed stroke - ideal for plotting.
# PROCESSOR CONTRACT: closed curves in (`crvs`) -> grown curve out (`out_crvs`).
# Inputs: crvs(list, closed - the container), iterations(int, growth steps),
#         detail(mm, edge length before an edge splits - smaller = finer folds),
#         repulsion(mm, personal space between strands), seed(int),
#         inset(mm), keep_edge(bool), on(bool bypass)
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


def nextrand(state):
    state[0] = (state[0] * 1103515245 + 12345) & 0x7FFFFFFF
    return state[0] / 2147483647.0


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


ITER = int(iterations) if iterations is not None else 150
if ITER < 1:
    ITER = 1
if ITER > 600:
    ITER = 600
DET = float(detail) if detail is not None else 2.0
if DET < 0.4:
    DET = 0.4
REP = float(repulsion) if repulsion is not None else 3.0
if REP < 0.2:
    REP = 0.2
SEED = int(seed) if seed is not None else 1
INS = float(inset) if inset is not None else 0.75
if INS < 0.0:
    INS = 0.0
EDGE = True if keep_edge is None else bool(keep_edge)
ON = True if on is None else bool(on)
MAXNODES = 2500

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
    wid = bb.Max.X - x0
    hei = bb.Max.Y - y0
    cxm = x0 + wid * 0.5
    cym = y0 + hei * 0.5

    # inside bitmap - the container walls
    gc = max(0.4, DET * 0.4)
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
            hits = 0
            p3 = rg.Point3d(px, py, 0)
            for c in regions:
                if c.Contains(p3, plane, tol) == rg.PointContainment.Inside:
                    hits += 1
            row.append((hits % 2) == 1)
        inside.append(row)

    # seed ring at the centre. Start it GENEROUS and already node-dense: a tiny
    # seed gets flooded with injected nodes faster than repulsion can spread
    # them, which piles a tangle in the middle instead of folding cleanly.
    r0 = min(wid, hei) * 0.22
    if r0 < DET * 2.0:
        r0 = DET * 2.0
    n0 = int(2.0 * math.pi * r0 / DET)
    if n0 < 16:
        n0 = 16
    nodes = []
    for i in range(n0):
        a = 2.0 * math.pi * i / n0
        nodes.append([cxm + math.cos(a) * r0, cym + math.sin(a) * r0])

    rng = [(SEED * 2654435761) & 0x7FFFFFFF]
    ATTR = 0.22
    REPF = 0.45
    JIT = 0.06
    GROW = 0.022          # fraction of nodes injected per iteration
    cellsz = REP

    for it in range(ITER):
        n = len(nodes)
        if n < 3:
            break
        # spatial hash for this step
        hgrid = {}
        for i in range(n):
            key = (int(nodes[i][0] / cellsz), int(nodes[i][1] / cellsz))
            if key not in hgrid:
                hgrid[key] = []
            hgrid[key].append(i)

        moves = []
        for i in range(n):
            moves.append([0.0, 0.0])
        for i in range(n):
            xi = nodes[i][0]
            yi = nodes[i][1]
            ip = (i - 1) % n
            inx = (i + 1) % n
            # attraction: slide toward the midpoint of my neighbours
            mx = (nodes[ip][0] + nodes[inx][0]) * 0.5
            my = (nodes[ip][1] + nodes[inx][1]) * 0.5
            moves[i][0] += (mx - xi) * ATTR
            moves[i][1] += (my - yi) * ATTR
            # repulsion from nearby strands
            gi = int(xi / cellsz)
            gj = int(yi / cellsz)
            for dj in [-1, 0, 1]:
                for di in [-1, 0, 1]:
                    key = (gi + di, gj + dj)
                    if key not in hgrid:
                        continue
                    for jn in hgrid[key]:
                        if jn == i or jn == ip or jn == inx:
                            continue
                        dx = xi - nodes[jn][0]
                        dy = yi - nodes[jn][1]
                        d2 = dx * dx + dy * dy
                        if d2 < 1e-9 or d2 > REP * REP:
                            continue
                        d = math.sqrt(d2)
                        f = (REP - d) / REP * REPF
                        moves[i][0] += (dx / d) * f
                        moves[i][1] += (dy / d) * f
            moves[i][0] += (nextrand(rng) - 0.5) * JIT
            moves[i][1] += (nextrand(rng) - 0.5) * JIT

        # clamp each step: all nodes move simultaneously, so an unclamped shove
        # lets crowded nodes leap PAST each other and knot the loop permanently
        lim = DET * 0.30
        for i in range(n):
            mag = math.sqrt(moves[i][0] * moves[i][0] + moves[i][1] * moves[i][1])
            if mag > lim and mag > 1e-9:
                moves[i][0] = moves[i][0] / mag * lim
                moves[i][1] = moves[i][1] / mag * lim
            nxp = nodes[i][0] + moves[i][0]
            nyp = nodes[i][1] + moves[i][1]
            bi = int((nxp - x0) / gc) + 1
            bj = int((nyp - y0) / gc) + 1
            if 0 <= bj < ny and 0 <= bi < nx and inside[bj][bi]:
                nodes[i][0] = nxp
                nodes[i][1] = nyp

        # GROWTH: split stretched edges, AND inject new nodes at random edges.
        # The injection is what actually drives the folding - the loop gains
        # more nodes than its current outline can hold, repulsion shoves them
        # apart, and the perimeter has to buckle.
        if len(nodes) < MAXNODES:
            n = len(nodes)
            inject = int(n * GROW) + 1
            picks = {}
            for t in range(inject):
                pk = int(nextrand(rng) * n)
                if pk >= n:
                    pk = n - 1
                picks[pk] = True
            grown = []
            for i in range(n):
                grown.append(nodes[i])
                jn = (i + 1) % n
                dx = nodes[jn][0] - nodes[i][0]
                dy = nodes[jn][1] - nodes[i][1]
                dlen = math.sqrt(dx * dx + dy * dy)
                if dlen > DET or (i in picks):
                    grown.append([nodes[i][0] + dx * 0.5, nodes[i][1] + dy * 0.5])
                if len(grown) >= MAXNODES:
                    break
            nodes = grown

    lp = List[rg.Point3d]()
    for q in nodes:
        lp.Add(rg.Point3d(q[0], q[1], 0))
    if nodes:
        lp.Add(rg.Point3d(nodes[0][0], nodes[0][1], 0))
    if lp.Count > 3:
        out_crvs.append(rg.PolylineCurve(lp))
    info = '%d iterations -> %d nodes, detail %.1fmm, repulsion %.1fmm, seed %d' % (ITER, len(nodes), DET, REP, SEED)

print('%d regions (%d open skipped) -> %d stroke(s) | %s' % (len(cs), n_open, len(out_crvs), info))
