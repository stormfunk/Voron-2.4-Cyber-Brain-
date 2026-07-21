# PLACE component - the placement/mapping stage.
# Art-space curves/dots -> PEN-SPACE (physical) coordinates: output geometry is
# where INK physically lands on the bed. The pen->nozzle offset is applied by
# GCODE only when formatting emitted moves. Preview draws pen-space raw.
# LOCK: freezes the current mapping to placement_lock.json. While locked, layers
# can be toggled on/off or content changed and NOTHING shifts - the stored
# transform is applied verbatim. Unlocking deletes the lock file (live mapping).
# BYPASS (direct mode): no fitting/centering at all - input coordinates are
# taken literally as PEN positions on the bed (where ink lands); the only
# transform applied is the pen->nozzle offset compensation. Draw at bed coords
# in Rhino, plot exactly there. Overrides registration/centering/lock.
# Inputs: curves(list), pens(list), dots(list), ghosted(list, pen-0 layers),
#         pmode(0 registered / 1 bed-centred / 2 direct / 3 from graph),
#         graph(point from the XY pad - artwork centre in pen-space mm, pmode 3),
#         fit_paper(bool), reg_margin(mm), lock(bool), reg_sync(str)
# Outputs: placed_curves, placed_pens, placed_dots, placed_ghost, frame(json)
import Rhino.Geometry as rg
import rhinoscriptsyntax as rs
import scriptcontext as sc
import os, math, json
try:
    sc.doc = ghdoc
except:
    pass

BED = 350.0
OFFX = 0.0      # pen tip offset from nozzle (hardware constant)
OFFY = -44.5    # measured 2026-07-17 by 4-point bed calibration (was -54.5)
REGFILE = r'C:\Users\john.chandler\voron_plotter\paper_registration.json'
LOCKFILE = r'C:\Users\john.chandler\voron_plotter\placement_lock.json'
# pmode: 0 = registered paper, 1 = bed centered, 2 = direct (Rhino coords),
#        3 = from graph (the XY pad places the artwork's centre, pen-space mm)
PM = int(pmode) if pmode is not None else 0
UREG = (PM == 0)
BYPASS = (PM == 2)
GRAPH = (PM == 3)
GX = 175.0
GY = 175.0
if graph is not None:
    try:
        _gp = graph if isinstance(graph, rg.Point3d) else rs.coerce3dpoint(graph)
        if _gp is not None:
            GX = _gp.X
            GY = _gp.Y
    except:
        pass
REGM = float(reg_margin) if reg_margin is not None else 10.0
if REGM < 0.0:
    REGM = 0.0
FIT = True if fit_paper is None else bool(fit_paper)
LOCK = False if lock is None else bool(lock)
# scale multiplier, applied ON TOP of whatever the mode works out:
# FIT on  -> fraction of the fitted size (100% = fill the paper as before)
# FIT off -> absolute scale (100% = 1:1 actual size)
# Ignored in DIRECT mode, where coordinates are taken literally by definition.
SCALE = float(scale) if scale is not None else 1.0
if SCALE < 0.001:
    SCALE = 0.001

def _coerce_curves(lst, plist):
    cs = []; cp = []
    if lst:
        for i in range(len(lst)):
            cc = lst[i] if isinstance(lst[i], rg.Curve) else rs.coercecurve(lst[i])
            if cc is None:
                continue
            pn = 1
            if plist is not None and i < len(plist) and plist[i] is not None:
                try:
                    pn = int(plist[i])
                except:
                    pn = 1
            cs.append(cc); cp.append(pn)
    return cs, cp

cs, cpn = _coerce_curves(curves, pens)
gh_cs, _ = _coerce_curves(ghosted, None)
dp = []
if dots:
    for d in dots:
        if isinstance(d, rg.Point3d):
            dp.append(rg.Point3d(d))
        else:
            _p3 = rs.coerce3dpoint(d)
            if _p3 is not None:
                dp.append(rg.Point3d(_p3))

xs = []; ys = []
for cc in cs:
    bb = cc.GetBoundingBox(True)
    xs.append(bb.Min.X); xs.append(bb.Max.X)
    ys.append(bb.Min.Y); ys.append(bb.Max.Y)
for p in dp:
    xs.append(p.X); ys.append(p.Y)

reg = None
if UREG or BYPASS or GRAPH:   # non-registered modes still load the taught paper
                              # so the preview can show it for orientation
    try:
        fh = open(REGFILE)
        reg = json.loads(fh.read())
        fh.close()
    except:
        reg = None

# ---- live mapping ----
fr = {"mode": "centered", "scale": 1.0, "offx": OFFX, "offy": OFFY, "pwarn": 0, "bwarn": 0}
xfm = rg.Transform.Identity
if BYPASS:
    # direct: input coords ARE pen positions - pen-space pipeline means no
    # transform at all here (GCODE compensates to nozzle at emission)
    xfm = rg.Transform.Identity
    fr = {"mode": "direct", "scale": 1.0, "offx": OFFX, "offy": OFFY, "pwarn": 0, "bwarn": 0}
    if xs and (min(xs) < 0 or min(ys) < 0 or max(xs) > BED or max(ys) > BED):
        fr["bwarn"] = 1
    if reg:
        # taught paper (nozzle coords in the file) shown in PEN space for orientation
        _bp0 = reg['p0']; _bp1 = reg['p1']; _bp2 = reg['p2']
        _bux = _bp1[0]-_bp0[0]; _buy = _bp1[1]-_bp0[1]
        _bvx = _bp2[0]-_bp0[0]; _bvy = _bp2[1]-_bp0[1]
        _bwu = math.sqrt(_bux*_bux+_buy*_buy); _bhv = math.sqrt(_bvx*_bvx+_bvy*_bvy)
        fr["p0"] = [_bp0[0] + OFFX, _bp0[1] + OFFY]
        fr["eu"] = [_bux/_bwu, _buy/_bwu]
        fr["ev"] = [_bvx/_bhv, _bvy/_bhv]
        fr["wu"] = _bwu; fr["hv"] = _bhv
elif GRAPH and xs:
    # free placement: the XY pad is the artwork's CENTRE in pen-space mm.
    # FIT still scales to the taught paper if there is one; position is yours.
    s_ = 1.0
    if FIT and reg:
        _p0 = reg['p0']; _p1 = reg['p1']; _p2 = reg['p2']
        _wu = math.sqrt((_p1[0]-_p0[0])**2 + (_p1[1]-_p0[1])**2)
        _hv = math.sqrt((_p2[0]-_p0[0])**2 + (_p2[1]-_p0[1])**2)
        _uw = _wu - 2.0*REGM; _vh = _hv - 2.0*REGM
        _aw = max(xs)-min(xs); _ah = max(ys)-min(ys)
        if _aw > 0.001 and _ah > 0.001 and _uw > 0 and _vh > 0:
            s_ = min(_uw/_aw, _vh/_ah)
    s_ = s_ * SCALE
    _cx = (min(xs)+max(xs))/2.0
    _cy = (min(ys)+max(ys))/2.0
    xfm = rg.Transform.Translation(GX - _cx*s_, GY - _cy*s_, 0) * rg.Transform.Scale(rg.Plane.WorldXY, s_, s_, 1.0)
    fr = {"mode": "graph", "scale": s_, "offx": OFFX, "offy": OFFY, "pwarn": 0, "bwarn": 0,
          "gx": GX, "gy": GY, "fit": 1 if FIT else 0}
    _hw = (max(xs)-min(xs))*s_/2.0
    _hh = (max(ys)-min(ys))*s_/2.0
    if (GX-_hw) < 0 or (GY-_hh) < 0 or (GX+_hw) > BED or (GY+_hh) > BED:
        fr["bwarn"] = 1
    if reg:
        _bp0 = reg['p0']; _bp1 = reg['p1']; _bp2 = reg['p2']
        _bux = _bp1[0]-_bp0[0]; _buy = _bp1[1]-_bp0[1]
        _bvx = _bp2[0]-_bp0[0]; _bvy = _bp2[1]-_bp0[1]
        _bwu = math.sqrt(_bux*_bux+_buy*_buy); _bhv = math.sqrt(_bvx*_bvx+_bvy*_bvy)
        fr["p0"] = [_bp0[0] + OFFX, _bp0[1] + OFFY]
        fr["eu"] = [_bux/_bwu, _buy/_bwu]
        fr["ev"] = [_bvx/_bhv, _bvy/_bhv]
        fr["wu"] = _bwu; fr["hv"] = _bhv
elif reg and xs:
    p0r = reg['p0']; p1r = reg['p1']; p2r = reg['p2']
    ux = p1r[0]-p0r[0]; uy = p1r[1]-p0r[1]
    vx = p2r[0]-p0r[0]; vy = p2r[1]-p0r[1]
    wu = math.sqrt(ux*ux+uy*uy); hv = math.sqrt(vx*vx+vy*vy)
    eux = ux/wu; euy = uy/wu
    evx = vx/hv; evy = vy/hv
    aw = max(xs)-min(xs); ah = max(ys)-min(ys)
    uw = wu - 2.0*REGM; vh = hv - 2.0*REGM
    s_ = 1.0
    if FIT and aw > 0.001 and ah > 0.001:
        s_ = min(uw/aw, vh/ah)
    s_ = s_ * SCALE
    # warn whenever the FINAL size overflows the usable paper - covers a
    # scaled-up FIT as well as plain 1:1 oversize art
    if aw*s_ > uw + 0.01 or ah*s_ > vh + 0.01:
        fr["pwarn"] = 1
    offu = REGM + (uw - aw*s_)/2.0
    offv = REGM + (vh - ah*s_)/2.0
    mnx = min(xs); mny = min(ys)
    # composed transform (struct field assignment on rg.Transform is unreliable
    # in IronPython): scale about origin -> offset in paper-local -> paper plane
    # target = taught paper frame in PEN space (taught corners are nozzle coords;
    # ink lands at nozzle + offset)
    _tgt = rg.Plane(rg.Point3d(p0r[0] + OFFX, p0r[1] + OFFY, 0), rg.Vector3d(eux, euy, 0), rg.Vector3d(evx, evy, 0))
    # XY-only scale: curve Z is the pressure channel and must survive FIT scaling
    xfm = rg.Transform.PlaneToPlane(rg.Plane.WorldXY, _tgt) * rg.Transform.Translation(offu - mnx*s_, offv - mny*s_, 0) * rg.Transform.Scale(rg.Plane.WorldXY, s_, s_, 1.0)
    fr = {"mode": "reg", "scale": s_, "p0": [p0r[0] + OFFX, p0r[1] + OFFY], "eu": [eux, euy], "ev": [evx, evy],
          "wu": wu, "hv": hv, "regm": REGM, "offx": OFFX, "offy": OFFY,
          "pwarn": fr["pwarn"], "bwarn": 0, "fit": 1 if FIT else 0}
elif xs:
    # center the INK on the bed (pen space: no offset terms)
    _cx = (min(xs)+max(xs))/2.0
    _cy = (min(ys)+max(ys))/2.0
    xfm = rg.Transform.Translation(BED/2.0 - _cx*SCALE, BED/2.0 - _cy*SCALE, 0) * rg.Transform.Scale(rg.Plane.WorldXY, SCALE, SCALE, 1.0)
    fr["scale"] = SCALE
    _hw = (max(xs)-min(xs))*SCALE/2.0
    _hh = (max(ys)-min(ys))*SCALE/2.0
    if (BED/2.0-_hw) < 0 or (BED/2.0-_hh) < 0 or (BED/2.0+_hw) > BED or (BED/2.0+_hh) > BED:
        fr["bwarn"] = 1
    if UREG and reg is None:
        fr["noregfile"] = 1

# ---- placement lock (not applicable in direct/bypass mode; lock file is
# left untouched so flipping back to LOCK resumes the frozen mapping) ----
lockmsg = ''
if BYPASS:
    fr["locked"] = 0
    lockmsg = 'DIRECT'
elif LOCK:
    stored = None
    try:
        fh = open(LOCKFILE)
        stored = json.loads(fh.read())
        fh.close()
    except:
        stored = None
    if stored:
        m = stored["m"]
        xfm = rg.Transform.Identity
        xfm.M00 = m[0]; xfm.M01 = m[1]; xfm.M03 = m[2]
        xfm.M10 = m[3]; xfm.M11 = m[4]; xfm.M13 = m[5]
        fr = stored["frame"]
        lockmsg = 'LOCKED (stored)'
    else:
        try:
            fh = open(LOCKFILE, 'w')
            fh.write(json.dumps({"m": [xfm.M00, xfm.M01, xfm.M03, xfm.M10, xfm.M11, xfm.M13], "frame": fr}))
            fh.close()
            lockmsg = 'LOCKED (captured now)'
        except Exception as e:
            lockmsg = 'LOCK SAVE FAILED: ' + str(e)
    fr["locked"] = 1
else:
    if os.path.isfile(LOCKFILE):
        try:
            os.remove(LOCKFILE)
        except:
            pass
    fr["locked"] = 0

out_c = []
for cc in cs:
    d = cc.DuplicateCurve()
    d.Transform(xfm)
    out_c.append(d)
out_g = []
for cc in gh_cs:
    d = cc.DuplicateCurve()
    d.Transform(xfm)
    out_g.append(d)
out_d = []
for p in dp:
    q = rg.Point3d(p)
    q.Transform(xfm)
    out_d.append(q)

# NOTE: output names must NOT match any input name (GhPython would emit the
# raw input variable instead of these).
placed_curves = out_c
placed_pens = cpn
placed_dots = out_d
placed_ghost = out_g
frame = json.dumps(fr)
print('%s: %d curves, %d dots, %d ghost | scale %.3f %s' % (fr["mode"], len(out_c), len(out_d), len(out_g), fr.get("scale", 1.0), lockmsg))
