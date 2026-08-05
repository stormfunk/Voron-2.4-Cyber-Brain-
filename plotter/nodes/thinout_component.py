# THINOUT - drops linework the pen cannot actually distinguish.
#
# When strokes run closer together than the pen is wide, the second one lays
# ink on top of the first: no visual gain, full plot-time cost. This walks the
# curves and removes any PORTION that falls within `spacing` of ink already
# committed, keeping the parts that still contribute.
#
# Longest strokes are processed first by default, so the major linework
# survives and the redundant short stuff is what gets culled (process in the
# incoming order instead by turning `longest_first` off).
# A stroke is never culled by itself - only by previously kept strokes - so a
# curve cannot erase its own start.
# The pressure channel (point Z) survives; fragments are cut from the source.
# Sits in the MAIN FLOW between LAYERS and PLACE. Give it the pen list and it
# culls each pen against ITSELF only - a red stroke beside a black one is not
# redundant ink - and uses that pen's own width from pen_widths.json, so a
# 0.8mm roller culls far harder than a 0.3mm liner. `spacing` is the fallback
# when a pen has no stored width (or when no pens are wired).
# PROCESSOR CONTRACT: curves in (`crvs`) -> thinned curves out (`out_crvs`),
# with `out_pens` kept in step so it can feed PLACE directly.
# Inputs: crvs(list), pens(list int), spacing(mm fallback), min_len(mm, discard
#         shorter fragments), longest_first(bool), on(bool bypass)
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

SP = float(spacing) if spacing is not None else 0.4
if SP < 0.05:
    SP = 0.05
MINL = float(min_len) if min_len is not None else 1.5
if MINL < 0.0:
    MINL = 0.0
LONGEST = True if longest_first is None else bool(longest_first)
ON = True if on is None else bool(on)

cs = []
cp = []
if crvs:
    for i in range(len(crvs)):
        cc = crvs[i] if isinstance(crvs[i], rg.Curve) else rs.coercecurve(crvs[i])
        if cc is None:
            continue
        pn = 0
        if pens and i < len(pens) and pens[i] is not None:
            try:
                pn = int(pens[i])
            except:
                pn = 0
        cs.append(cc)
        cp.append(pn)

# per-pen widths, so each pen culls at its own line weight
widths = {}
try:
    import json
    _fh = open(r'C:\Users\john.chandler\voron_plotter\pen_widths.json')
    widths = json.loads(_fh.read())
    _fh.close()
except:
    widths = {}


def pen_space(pn):
    w = widths.get(str(pn))
    if w:
        return float(w)
    return SP


out_crvs = []
out_pens = []
info = ''
if not ON:
    out_crvs = cs
    out_pens = cp
    info = '[BYPASSED] %d curves pass through' % len(cs)
elif cs:
    order = []
    for i in range(len(cs)):
        order.append((cs[i].GetLength(), i))
    if LONGEST:
        order.sort()
        order.reverse()
    grids = {}                # committed ink per pen, hashed at that pen's width
    len_in = 0.0
    len_out = 0.0
    n_drop = 0
    for od in order:
        c = cs[od[1]]
        pn = cp[od[1]]
        SPP = pen_space(pn)
        HC = SPP * 0.5              # occupancy cell: half the pen width
        if HC < 0.05:
            HC = 0.05
        step = HC
        sp2 = SPP * SPP
        if pn not in grids:
            grids[pn] = {}
        grid = grids[pn]
        L = c.GetLength()
        len_in += L
        n = int(L / step)
        if n < 1:
            n = 1
        ts = c.DivideByCount(n, True)
        pts = []
        if ts:
            for t in ts:
                pts.append(c.PointAt(t))
        else:
            pts = [c.PointAtStart, c.PointAtEnd]
        # split into runs of points that are NOT already covered
        runs = []
        cur = []
        for p in pts:
            # Occupancy is a BOOLEAN grid at half the pen width, not a bucket of
            # points: storing points made this quadratic (dense artwork puts
            # thousands into one bucket and every new point rescanned them all).
            gi = int(p.X / HC)
            gj = int(p.Y / HC)
            hit = False
            for dj in [-1, 0, 1]:
                for di in [-1, 0, 1]:
                    if (gi + di, gj + dj) in grid:
                        hit = True
                        break
                if hit:
                    break
            if hit:
                if len(cur) > 1:
                    runs.append(cur)
                cur = []
            else:
                cur.append(p)
        if len(cur) > 1:
            runs.append(cur)
        # emit the survivors and commit their ink
        for run in runs:
            rl = 0.0
            for k in range(1, len(run)):
                rl += run[k - 1].DistanceTo(run[k])
            if rl < MINL:
                n_drop += 1
                continue
            lp = List[rg.Point3d]()
            for p in run:
                lp.Add(p)
            out_crvs.append(rg.PolylineCurve(lp))
            out_pens.append(pn)
            len_out += rl
            for p in run:
                grid[(int(p.X / HC), int(p.Y / HC))] = 1
    _pct = (100.0 * (len_in - len_out) / len_in) if len_in > 0.001 else 0.0
    _pens = sorted(grids.keys())
    _sp = ', '.join(['p%d@%.2f' % (q, pen_space(q)) for q in _pens])
    info = '%d -> %d strokes, ink %.2fm -> %.2fm (%.0f%% removed), %d tiny fragments dropped | per-pen %s' % (
        len(cs), len(out_crvs), len_in / 1000.0, len_out / 1000.0, _pct, n_drop, _sp)

print(info if info else 'no curves')
