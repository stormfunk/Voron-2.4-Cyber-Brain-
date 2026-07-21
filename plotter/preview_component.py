# PREVIEW component - THIN DISPLAY SHELL. The whole pipeline is PEN-SPACE
# (physical ink positions), so plan geometry is drawn COMPLETELY RAW - zero
# transforms. Context: bed outline, registered paper quad, ghost layers,
# FRONT marker - all in the same physical frame (matches the bed STL).
# What you see is literally the emission plan.
# Inputs: plan_pen1..plan_pen4(list crv), plan_dots(list pt), plan_signature(list crv),
#         ghosted(list crv), frame(str), dot_dwell(ms - scales preview dot size),
#         paper_mm(paper thickness - paper renders as a slab with TOP at Z=0)
# Outputs: out, bed, paper, labels, view_pen1..view_pen4, view_dots, view_signature, view_ghost
import Rhino.Geometry as rg
import rhinoscriptsyntax as rs
import scriptcontext as sc
import Rhino as _R
import math, json
from System.Collections.Generic import List
try:
    sc.doc = ghdoc
except:
    pass

BED = 350.0

fr = {"mode": "direct"}
if frame:
    try:
        fr = json.loads(str(frame))
    except:
        fr = {"mode": "direct"}

def txt(s, hgt, px, py):
    out2 = []
    try:
        te = rg.TextEntity()
        te.Plane = rg.Plane(rg.Point3d(0, 0, 0), rg.Vector3d.ZAxis)
        te.PlainText = s
        te.TextHeight = hgt
        tcs = te.CreateCurves(_R.RhinoDoc.ActiveDoc.DimStyles.Current, False)
        if tcs and len(tcs) > 0:
            bb = rg.BoundingBox.Empty
            for t in tcs:
                bb.Union(t.GetBoundingBox(True))
            hh = bb.Max.Y - bb.Min.Y
            sf = hgt/hh if hh > 0.01 else 1.0
            ct = rg.Point3d((bb.Min.X+bb.Max.X)/2.0, (bb.Min.Y+bb.Max.Y)/2.0, 0)
            for t in tcs:
                t.Transform(rg.Transform.Scale(ct, sf))
            b2 = rg.BoundingBox.Empty
            for t in tcs:
                b2.Union(t.GetBoundingBox(True))
            nc = rg.Point3d((b2.Min.X+b2.Max.X)/2.0, (b2.Min.Y+b2.Max.Y)/2.0, 0)
            mv = rg.Transform.Translation(px-nc.X, py-nc.Y, 0)
            for t in tcs:
                t.Transform(mv)
                out2.append(t)
    except:
        pass
    return out2

def shift_curves(lst):
    # pen-space pipeline: no shifting - just coerce for display
    out2 = []
    if lst:
        for c in lst:
            cc = c if isinstance(c, rg.Curve) else rs.coercecurve(c)
            if cc is not None:
                out2.append(cc)
    return out2

view_pen1 = shift_curves(plan_pen1)
view_pen2 = shift_curves(plan_pen2)
view_pen3 = shift_curves(plan_pen3)
view_pen4 = shift_curves(plan_pen4)
view_pen5 = shift_curves(plan_pen5)
view_pen6 = shift_curves(plan_pen6)
view_pen7 = shift_curves(plan_pen7)
view_pen8 = shift_curves(plan_pen8)
view_signature = shift_curves(plan_signature)
view_ghost = shift_curves(ghosted)

# dot size approximates ink bleed: longer dwell = fatter dot
DWELL = float(dot_dwell) if dot_dwell is not None else 50.0
if DWELL < 0.0:
    DWELL = 0.0
_dot_r = 0.6 + DWELL * 0.004      # 0ms->0.6mm, 50->0.8, 250->1.6, 500->2.6
view_dots = []
if plan_dots:
    for d in plan_dots:
        p3 = d if isinstance(d, rg.Point3d) else rs.coerce3dpoint(d)
        if p3 is None:
            continue
        view_dots.append(rg.Circle(rg.Point3d(p3), _dot_r).ToNurbsCurve())

# ---- pressure heat overlay: pressured strokes chopped into pieces, coloured
# by press depth (|Z|): cool grey-blue = light touch, hot red = full press.
# Drawn ON TOP of the normal pen views via a colour-per-piece Custom Preview.
import System.Drawing as SD
view_pressure = []
pressure_col = []
_praw = []          # (piece polyline pts, avg |z|)
_pmax = 0.0
for _plan in [plan_pen1, plan_pen2, plan_pen3, plan_pen4, plan_pen5, plan_pen6, plan_pen7, plan_pen8]:
    if not _plan:
        continue
    for c in _plan:
        cc = c if isinstance(c, rg.Curve) else rs.coercecurve(c)
        if cc is None:
            continue
        ok, pl = cc.TryGetPolyline()
        if not ok:
            continue
        _hasz = False
        for q in pl:
            if abs(q.Z) > 0.01:
                _hasz = True
                break
        if not _hasz:
            continue
        CH = 8
        i0 = 0
        while i0 < pl.Count - 1 and len(_praw) < 6000:
            i1 = i0 + CH
            if i1 > pl.Count - 1:
                i1 = pl.Count - 1
            zs = 0.0
            for k in range(i0, i1 + 1):
                zs += abs(pl[k].Z)
            za = zs / float(i1 - i0 + 1)
            if za > _pmax:
                _pmax = za
            _praw.append((i0, i1, pl, za))
            i0 = i1
if _praw and _pmax > 0.001:
    for item in _praw:
        lp = List[rg.Point3d]()
        for k in range(item[0], item[1] + 1):
            q = item[2][k]
            lp.Add(rg.Point3d(q.X, q.Y, 0.05))
        view_pressure.append(rg.PolylineCurve(lp))
        t = item[3] / _pmax
        r = int(120 + 120 * t)
        g = int(140 - 110 * t)
        b = int(200 - 170 * t)
        pressure_col.append(SD.Color.FromArgb(235, r, g, b))

bed = [rg.Rectangle3d(rg.Plane.WorldXY, rg.Interval(0, BED), rg.Interval(0, BED)).ToNurbsCurve()]
paper = []; labels = []
if fr.get("p0"):     # paper whenever corners known (frame is already pen-space)
    p0 = [fr["p0"][0], fr["p0"][1]]
    eu = fr["eu"]; ev = fr["ev"]
    wu = fr["wu"]; hv = fr["hv"]
    # paper as a thin slab: top face at Z=0 (the drawing plane), thickness below
    _pth = float(paper_mm) if paper_mm is not None else 0.1
    if _pth < 0.02:
        _pth = 0.02
    _ppl = rg.Plane(rg.Point3d(p0[0], p0[1], 0), rg.Vector3d(eu[0], eu[1], 0), rg.Vector3d(ev[0], ev[1], 0))
    _pbox = rg.Box(_ppl, rg.Interval(0, wu), rg.Interval(0, hv), rg.Interval(-_pth, 0))
    _pbrep = rg.Brep.CreateFromBox(_pbox)
    if _pbrep is not None:
        paper.append(_pbrep)
    else:
        q = List[rg.Point3d]()
        q.Add(rg.Point3d(p0[0], p0[1], 0))
        q.Add(rg.Point3d(p0[0]+eu[0]*wu, p0[1]+eu[1]*wu, 0))
        q.Add(rg.Point3d(p0[0]+eu[0]*wu+ev[0]*hv, p0[1]+eu[1]*wu+ev[1]*hv, 0))
        q.Add(rg.Point3d(p0[0]+ev[0]*hv, p0[1]+ev[1]*hv, 0))
        q.Add(rg.Point3d(p0[0], p0[1], 0))
        paper.append(rg.PolylineCurve(q))
    _lbl = [('P0', p0), ('P1', [p0[0]+eu[0]*wu, p0[1]+eu[1]*wu]), ('P2', [p0[0]+ev[0]*hv, p0[1]+ev[1]*hv])]
    for nm, pp in _lbl:
        labels.append(rg.Circle(rg.Point3d(pp[0], pp[1], 0), 4.0).ToNurbsCurve())
        for t in txt(nm, 9.0, pp[0], pp[1]-12):
            labels.append(t)

cxm = BED/2.0
pts = List[rg.Point3d]()
pts.Add(rg.Point3d(cxm-16, -14, 0)); pts.Add(rg.Point3d(cxm, -46, 0))
pts.Add(rg.Point3d(cxm+16, -14, 0)); pts.Add(rg.Point3d(cxm-16, -14, 0))
labels.append(rg.PolylineCurve(pts))
ft = txt('FRONT', 20.0, cxm, -82)
if ft:
    for t in ft:
        labels.append(t)
else:
    labels.append(rg.TextDot('FRONT', rg.Point3d(cxm, -64, 0)))

print('plan: %d+%d+%d+%d strokes, %d dots, %d sig, %d ghost' % (len(view_pen1), len(view_pen2), len(view_pen3), len(view_pen4), len(view_dots), len(view_signature), len(view_ghost)))
