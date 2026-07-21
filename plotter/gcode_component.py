# GCODE component source - loaded into the GH GhPython component "GCODE".
# COORDINATE CONVENTION: the whole pipeline (PLACE outputs, plans, preview) is
# PEN-SPACE = physical ink positions. The pen->nozzle offset is applied HERE,
# only when formatting emitted G-code words (emit X = x - OFFX, Y = y - OFFY).
# PURE CONVERTER: expects curves/dots ALREADY PLACED in final pen coordinates
# (normally by the PLACE component; wire absolute-coordinate curves straight in
# to bypass placement entirely). `frame` json from PLACE carries placement info
# for the signature band, header and paper warnings.
# MULTI-PEN: parallel `pens` list groups strokes into passes; between passes the
# head presents for a pen swap (PEN_PAUSE PEN=n) and each pass draws its own
# calibration circle row (JC logo only on the first pass).
# Inputs: curves(list, placed), pens(list int), frame(str json), pen_down_z, pen_up_z,
#   draw_feed, travel_feed, resolution, do_qgl, do_mesh, write, accel, spikeyness,
#   pen_load, paper, hop, load_x, load_y, plot(button), preload, dots(list placed),
#   dot_dwell, dots_pen(int, 0=dots off), cal_sig, sig_x, sig_y, sig_art
# Outputs: out(manifest), gcode_preview, plan_pen1..plan_pen4 (planned strokes per
#   pen), plan_dots, plan_signature - the preview draws THESE, so what you see is
#   literally what will be emitted.
import Rhino.Geometry as rg
import rhinoscriptsyntax as rs
import scriptcontext as sc
import os, math, json
from System.Collections.Generic import List
try:
    sc.doc = ghdoc
except:
    pass

PDZ = float(pen_down_z) if pen_down_z is not None else 2.0
if PDZ < 1.0:
    PDZ = 1.0
PUZ = float(pen_up_z) if pen_up_z is not None else 8.0
# pressure channel gain: scales every curve's Z (the pressure carrier) at
# emission time, so the whole effect can be tuned without re-running the
# PRESSURE processors. 0 = ignore pressure entirely and plot flat.
PGAIN = float(pressure_gain) if pressure_gain is not None else 1.0
if PGAIN < 0.0:
    PGAIN = 0.0
# tip wear compensation (fast-wearing media: pastel, chalk, graphite stick).
# Z drops by `wear` mm for every METRE drawn, so contact pressure stays even
# as the tip shortens. Resets at each pass (pen swap = fresh tip).
WEAR = float(wear) if wear is not None else 0.0
if WEAR < 0.0:
    WEAR = 0.0
DF = int(draw_feed) if draw_feed is not None else 3000
TF = int(travel_feed) if travel_feed is not None else 6000
RES = float(resolution) if resolution is not None else 1.0
AC = int(accel) if accel is not None else 3000
# speed_profile: 0 Careful, 1 Normal, 2 Fast, 3 Custom (use the sliders above)
SPEED_PROFILES = {0: ('Careful', 1500, 4000, 1500), 1: ('Normal', 3000, 6000, 3000), 2: ('Fast', 4500, 9000, 5000)}
PROF = int(speed_profile) if speed_profile is not None else 3
PROF_NAME = 'Custom'
if PROF in SPEED_PROFILES:
    PROF_NAME, DF, TF, AC = SPEED_PROFILES[PROF]
SPIKE = float(spikeyness) if spikeyness is not None else 0.0
if SPIKE < 0.0: SPIKE = 0.0
if SPIKE > 1.0: SPIKE = 1.0
_base_scv = 8.0 + 4.0 * RES
if _base_scv > 24.0: _base_scv = 24.0
SCV = _base_scv * (1.0 - 0.95 * SPIKE)
if SCV < 0.5: SCV = 0.5
PAPER = float(paper) if paper is not None else 0.1
HOP = float(hop) if hop is not None else 3.0
# pen-load point is computed automatically AFTER placement is known: just
# outside the paper's front edge so the seating dot lands on waste bed,
# never the artwork (and bare-bed seating is what the PAPER comp assumes).
PRELOAD = float(preload) if preload is not None else 0.0
if PRELOAD < 0.0: PRELOAD = 0.0
# ritual: checklist of start-sequence steps (list of strings)
RIT = []
if ritual:
    for r in ritual:
        RIT.append(str(r).lower())
if ritual is None:
    RIT = ['qgl', 'outline', 'sig', 'penload']    # unwired fallback
QGL = 'qgl' in RIT
MESH = 'mesh' in RIT
PENLOAD = 'penload' in RIT
WRITE = False if write is None else bool(write)
PLOT = False if plot is None else bool(plot)
OFFX = 0.0      # pen tip offset from nozzle (hardware constant, matches PLACE)
OFFY = -44.5    # measured 2026-07-17 by 4-point bed calibration (was -54.5)
DWELL = float(dot_dwell) if dot_dwell is not None else 50.0
if DWELL < 0.0: DWELL = 0.0
DPEN = int(dots_pen) if dots_pen is not None else 2
# THE PERMANENT PEN PALETTE (order = pass/draw order)
PEN_NAMES = {1: 'BLACK', 2: 'RED', 3: 'GREEN', 4: 'BLUE', 5: 'YELLOW', 6: 'ORANGE', 7: 'AQUA', 8: 'PINK'}
def penname(n):
    return PEN_NAMES.get(n, 'PEN%d' % n)

CALSIG = 'sig' in RIT
# outline: before any pen pause, slowly trace the bounding box of everything
# that will be inked (hovering, pen not yet loaded) to verify paper alignment
OUTLINE = 'outline' in RIT
OUTLINE_F = 3600     # brisk but watchable (mm/min)
OUTLINE_DWELL = 250  # ms pause at each corner
# signature placement: nudge with sig_x/sig_y (mm); sig_art anchors it to the
# artwork bounds corner instead of the paper corner
SIGX = float(sig_x) if sig_x is not None else 0.0
SIGY = float(sig_y) if sig_y is not None else 0.0
SIGART = False if sig_art is None else bool(sig_art)
CAL_N = 5
CAL_R = 2.0
CAL_GAP = 8.0
CAL_PAUSE = 500

BED = 350.0
Z_SPEED = 900.0
DRAW_Z = PDZ + PAPER - PRELOAD
if DRAW_Z < 0.5: DRAW_Z = 0.5
HOP_Z = DRAW_Z + HOP
out_dir = r'C:\Users\john.chandler\voron_plotter'
out_file = os.path.join(out_dir, 'plot.gcode')

# placement frame from PLACE (or default when curves are wired in directly)
fr = {"mode": "direct", "scale": 1.0, "pwarn": 0, "bwarn": 0}
if frame:
    try:
        fr = json.loads(str(frame))
    except:
        fr = {"mode": "direct", "scale": 1.0, "pwarn": 0, "bwarn": 0}

def sample(crv):
    pts = []
    c = crv if isinstance(crv, rg.Curve) else rs.coercecurve(crv)
    if c is None:
        return pts
    ts = c.DivideByLength(RES, True)
    if ts:
        for t in ts:
            pts.append(c.PointAt(t))
    spt = c.PointAtStart; ept = c.PointAtEnd
    if len(pts) == 0 or pts[0].DistanceTo(spt) > 1e-6:
        pts.insert(0, spt)
    if len(pts) == 0 or pts[-1].DistanceTo(ept) > 1e-6:
        pts.append(ept)
    return pts

# ---- strokes tagged with pen numbers (already in final coords) ----
# PRESSURE CHANNEL: a curve's Z coordinate is a pressure offset in mm.
# Z=0 normal; negative = press harder (spring compresses); positive = lighter.
polys = []
xs = []; ys = []
press_pens = []
src = curves if curves else []
plist = pens if pens else []
for i in range(len(src)):
    p = sample(src[i])
    if len(p) >= 2:
        pn = 1
        if i < len(plist) and plist[i] is not None:
            try:
                pn = int(plist[i])
            except:
                pn = 1
        if pn < 1: pn = 1
        polys.append([p, pn])
        for pt in p:
            xs.append(pt.X); ys.append(pt.Y)
            if abs(pt.Z) > 0.01 and pn not in press_pens:
                press_pens.append(pn)

dpts = []
if dots:
    for d in dots:
        if isinstance(d, rg.Point3d):
            dpts.append(rg.Point3d(d))
        else:
            _p3 = rs.coerce3dpoint(d)
            if _p3 is not None:
                dpts.append(rg.Point3d(_p3))
    for d in dpts:
        xs.append(d.X); ys.append(d.Y)
if DPEN < 1:
    dpts = []

# ---- warnings (pen-space coords: machine travel is checked in nozzle frame) ----
warn = ''
if xs and (min(xs)-OFFX < 0 or min(ys)-OFFY < 0 or max(xs)-OFFX > BED or max(ys)-OFFY > BED):
    warn = '; WARNING: exceeds machine travel'
if fr.get("bwarn", 0):
    warn = (warn + '; WARNING: pen exceeds bed') if warn else '; WARNING: pen exceeds bed'
pwarn = '; NOTE: 1:1 art exceeds paper usable area' if fr.get("pwarn", 0) else ''

# ---- auto pen-load point (pen space): outside the paper front edge ----
LOADCLEAR = 15.0
if fr.get("p0") and fr.get("wu"):
    _lp0 = fr["p0"]; _leu = fr["eu"]; _lev = fr["ev"]
    LX = _lp0[0] + _leu[0]*(fr["wu"]/2.0) - _lev[0]*LOADCLEAR
    LY = _lp0[1] + _leu[1]*(fr["wu"]/2.0) - _lev[1]*LOADCLEAR
elif xs:
    LX = (min(xs)+max(xs))/2.0
    LY = min(ys) - 20.0
else:
    LX = 175.0; LY = 40.0
if LX < 10.0: LX = 10.0
if LX > 340.0: LX = 340.0
if LY < 5.0: LY = 5.0
if LY > 290.0: LY = 290.0

# ---- passes ----
_pset = []
for pl in polys:
    if pl[1] not in _pset:
        _pset.append(pl[1])
if dpts and DPEN not in _pset:
    _pset.append(DPEN)
passes = sorted(_pset)

# ---- calibration signature ----
def _sigmap_local(lu, lv):
    if fr.get("mode") == "reg" and not SIGART:
        # anchored to the paper corner, in the paper's own (possibly rotated) frame
        _p0 = fr["p0"]; _eu = fr["eu"]; _ev = fr["ev"]; _rm = fr.get("regm", 10.0)
        _u = _rm + SIGX + lu; _v = 1.0 + SIGY + lv
        return (_p0[0] + _eu[0]*_u + _ev[0]*_v, _p0[1] + _eu[1]*_u + _ev[1]*_v)
    else:
        # anchored to the artwork bounds corner (axis-aligned), below the art
        _bx = (min(xs) if xs else 30.0)
        _by = ((min(ys) - 13.0) if ys else 30.0)
        if _by < 2.0: _by = 2.0
        return (_bx + SIGX + lu, _by + SIGY + lv)

cal_sig_polys = []
cal_rows = {}
if CALSIG and passes:
    _W = 10.0; _H = 9.0; _g = 1.4
    _sig_local = []
    for i in range(4):
        _lx = i*_g; _rx = _W - i*_g; _b = i*_g
        _fr2 = 1.0 + (3-i)*0.9
        _mx = (_rx-_lx)/2.0 - 0.05
        if _fr2 > _mx: _fr2 = _mx
        _st = [(_lx, _b + _fr2 + 1.5)]
        for s in range(7):
            _t = math.radians(180.0 + 90.0*s/6.0)
            _st.append((_lx+_fr2+_fr2*math.cos(_t), _b+_fr2+_fr2*math.sin(_t)))
        for s in range(7):
            _t = math.radians(270.0 + 90.0*s/6.0)
            _st.append((_rx-_fr2+_fr2*math.cos(_t), _b+_fr2+_fr2*math.sin(_t)))
        _st.append((_rx, _H))
        _sig_local.append(_st)
    _ccx = _W + 3.0 + 4.5; _ccy = _H/2.0
    for _r in [4.5, 3.0, 1.5]:
        _arc = []
        for s in range(25):
            _t = math.radians(35.0 + 290.0*s/24.0)
            _arc.append((_ccx + _r*math.cos(_t), _ccy + _r*math.sin(_t)))
        _sig_local.append(_arc)
    for _st in _sig_local:
        cal_sig_polys.append([_sigmap_local(q[0], q[1]) for q in _st])
    _circ_u0 = _ccx + 4.5 + 4.0
    _rowlen = CAL_N*CAL_GAP + 6.0
    for k in range(len(passes)):
        _marks = []
        for kk in range(CAL_N):
            _cu = _circ_u0 + k*_rowlen + CAL_R + kk*CAL_GAP
            _circ = []
            for s in range(21):
                _t = 6.283185307 * s / 20.0
                _circ.append(_sigmap_local(_cu + CAL_R*math.cos(_t), 4.0 + CAL_R*math.sin(_t)))
            _marks.append((_circ, _sigmap_local(_cu, 4.0)))
        cal_rows[k] = _marks
    _all = []
    for _st in cal_sig_polys:
        for q in _st: _all.append(q)
    for k in cal_rows:
        for _mk in cal_rows[k]:
            for q in _mk[0]: _all.append(q)
    for q in _all:
        if q[0] < 0 or q[1] < 0 or q[0] > BED or q[1] > BED:
            cal_sig_polys = []
            cal_rows = {}
            break

# ---- per-pass greedy ordering ----
pass_strokes = {}
for k in range(len(passes)):
    pn = passes[k]
    mine = []
    for pl in polys:
        if pl[1] == pn:
            mine.append(pl[0])
    if k in cal_rows and cal_rows[k]:
        cx = cal_rows[k][0][1][0]; cy = cal_rows[k][0][1][1]
    else:
        cx = LX; cy = LY      # load point, pen space
    rem = list(mine)
    ordered = []
    while rem:
        bi = 0; brev = False; bd = None
        for i in range(len(rem)):
            q0 = rem[i][0]; q1 = rem[i][-1]
            d0 = (q0.X-cx)*(q0.X-cx) + (q0.Y-cy)*(q0.Y-cy)
            d1 = (q1.X-cx)*(q1.X-cx) + (q1.Y-cy)*(q1.Y-cy)
            if bd is None or d0 < bd:
                bd = d0; bi = i; brev = False
            if d1 < bd:
                bd = d1; bi = i; brev = True
        pl = rem.pop(bi)
        if brev:
            pl = list(reversed(pl))
        ordered.append(pl)
        cx = pl[-1].X; cy = pl[-1].Y
    mydots = []
    if dpts and passes[k] == DPEN:
        _remd = list(dpts)
        while _remd:
            _bi = 0; _bd = None
            for i in range(len(_remd)):
                _d = (_remd[i].X-cx)*(_remd[i].X-cx) + (_remd[i].Y-cy)*(_remd[i].Y-cy)
                if _bd is None or _d < _bd:
                    _bd = _d; _bi = i
            _p = _remd.pop(_bi)
            mydots.append(_p)
            cx = _p.X; cy = _p.Y
    pass_strokes[k] = (ordered, mydots)

# ---- distance + time estimate ----
draw_d = 0.0; trav_d = 0.0; ndots_total = 0; nstrokes_total = 0
for k in pass_strokes:
    ordered, mydots = pass_strokes[k]
    px = LX; py = LY
    for pl in ordered:
        trav_d += math.sqrt((pl[0].X-px)*(pl[0].X-px) + (pl[0].Y-py)*(pl[0].Y-py))
        for i in range(1, len(pl)):
            draw_d += pl[i-1].DistanceTo(pl[i])
        px = pl[-1].X; py = pl[-1].Y
    for p in mydots:
        trav_d += math.sqrt((p.X-px)*(p.X-px) + (p.Y-py)*(p.Y-py))
        px = p.X; py = p.Y
    ndots_total += len(mydots)
    nstrokes_total += len(ordered)
z_d = (nstrokes_total + ndots_total)*2.0*HOP + len(passes)*2.0*(PUZ+10.0)
dwell_min = ndots_total*DWELL/60000.0
cal_min = 0.0
if cal_rows:
    _sig_d = 0.0
    for _st in cal_sig_polys:
        for i in range(1, len(_st)):
            _sig_d += math.sqrt((_st[i][0]-_st[i-1][0])**2 + (_st[i][1]-_st[i-1][1])**2)
    cal_min = _sig_d/float(DF) + (len(passes)*CAL_N*6.283185307*CAL_R)/float(DF) + (len(passes)*CAL_N*4.0*HOP)/Z_SPEED + (len(passes)*(2.0*CAL_N+2)*CAL_PAUSE)/60000.0
outline_min = 0.0
if OUTLINE and xs:
    outline_min = (2.0*((max(xs)-min(xs)) + (max(ys)-min(ys))))/float(OUTLINE_F) + (5.0*OUTLINE_DWELL + 1000.0)/60000.0
mins = draw_d/float(DF) + trav_d/float(TF) + z_d/Z_SPEED + dwell_min + cal_min + outline_min + (len(passes)-1)*0.5
est = '%.1f min (draw %.1fm, travel %.1fm)' % (mins, draw_d/1000.0, trav_d/1000.0)

# ---- build g-code ----
L = []
L.append('; Voron pen-plot (moves only, no heat) - MULTI-PEN')
L.append('; === settings ===')
L.append('; draw_height=%.3f paper=%.2f preload=%.2f -> draw_z=%.3f | hop=%.1f clearance=%.1f' % (PDZ, PAPER, PRELOAD, DRAW_Z, HOP, PUZ))
L.append('; draw=%d travel=%d mm/min | accel=%d | res=%.2f mm | scv=%.1f (spikeyness %.2f)' % (DF, TF, AC, RES, SCV, SPIKE))
L.append('; pen-load point (auto, off-paper): (%.0f,%.0f) | pen_offset=(%.1f,%.1f) qgl=%s mesh=%s' % (LX, LY, OFFX, OFFY, QGL, MESH))
if fr.get("mode") == "reg":
    L.append('; PLACEMENT: registered paper, %s scale=%.3f margin=%.1f p0=(%.1f,%.1f)' % ('FIT' if fr.get("fit", 1) else '1:1', fr.get("scale", 1.0), fr.get("regm", 10.0), fr["p0"][0], fr["p0"][1]))
elif fr.get("mode") == "centered":
    L.append('; PLACEMENT: bed-centered (pen-offset compensated)')
    if fr.get("noregfile", 0):
        L.append('; registration requested but paper_registration.json missing')
else:
    L.append('; PLACEMENT: direct (curves wired in already in machine coords)')
if pwarn:
    L.append(pwarn)
for k in range(len(passes)):
    ordered, mydots = pass_strokes[k]
    L.append('; PASS %d: pen %d [%s] -> %d strokes, %d dots' % (k+1, passes[k], penname(passes[k]), len(ordered), len(mydots)))
L.append('; est %s' % est)
if warn:
    L.append(warn)
L.append('CLEAR_PAUSE')
L.append('SET_GCODE_OFFSET Z=0')
L.append('G21')
L.append('G90')
# conditional homing + QGL (printer-side macro): skips whatever is already valid
L.append('PLOT_HOME_QGL QGL=%d' % (1 if QGL else 0))
if MESH:
    # declare the plot region as an exclude_object so ADAPTIVE meshing scans
    # only it (no objects declared = Klipper falls back to FULL bed scan).
    # Region = everything drawn (strokes+dots+signature) in nozzle coords,
    # extended to cover the pen's contact zone (pen = nozzle + offset).
    _rxs = list(xs); _rys = list(ys)
    for _st in cal_sig_polys:
        for q in _st:
            _rxs.append(q[0]); _rys.append(q[1])
    for k in cal_rows:
        for _mk in cal_rows[k]:
            for q in _mk[0]:
                _rxs.append(q[0]); _rys.append(q[1])
    if _rxs:
        # union of pen-contact zone (raw) and nozzle-travel zone (raw - offset)
        _mx0 = min(min(_rxs), min(_rxs)-OFFX); _mx1 = max(max(_rxs), max(_rxs)-OFFX)
        _my0 = min(min(_rys), min(_rys)-OFFY); _my1 = max(max(_rys), max(_rys)-OFFY)
        if _mx0 < 0: _mx0 = 0.0
        if _my0 < 0: _my0 = 0.0
        if _mx1 > BED: _mx1 = BED
        if _my1 > BED: _my1 = BED
        _mcx = (_mx0+_mx1)/2.0; _mcy = (_my0+_my1)/2.0
        L.append('EXCLUDE_OBJECT_DEFINE NAME=plot_area CENTER=%.1f,%.1f POLYGON=[[%.1f,%.1f],[%.1f,%.1f],[%.1f,%.1f],[%.1f,%.1f]]' % (
            _mcx, _mcy, _mx0, _my0, _mx1, _my0, _mx1, _my1, _mx0, _my1))
    L.append('BED_MESH_CALIBRATE ADAPTIVE=1')
L.append('SET_VELOCITY_LIMIT ACCEL=%d SQUARE_CORNER_VELOCITY=%.1f' % (AC, SCV))
if OUTLINE:
    # bounding box of everything inked: strokes + dots + signature
    _oxs = list(xs); _oys = list(ys)
    for _st in cal_sig_polys:
        for q in _st:
            _oxs.append(q[0]); _oys.append(q[1])
    for k in cal_rows:
        for _mk in cal_rows[k]:
            for q in _mk[0]:
                _oxs.append(q[0]); _oys.append(q[1])
    if _oxs:
        _ox0 = min(_oxs); _ox1 = max(_oxs)
        _oy0 = min(_oys); _oy1 = max(_oys)
        _oz = PUZ + 2.0
        L.append('; ---- alignment outline: tracing plot bounds (no pen loaded) ----')
        L.append('SET_DISPLAY_TEXT MSG="Outlining plot bounds - check alignment"')
        L.append('G1 Z%.3f F1200' % _oz)
        L.append('G0 X%.3f Y%.3f F%d' % (_ox0-OFFX, _oy0-OFFY, TF))
        L.append('G4 P%d' % OUTLINE_DWELL)
        L.append('G1 X%.3f Y%.3f F%d' % (_ox1-OFFX, _oy0-OFFY, OUTLINE_F))
        L.append('G4 P%d' % OUTLINE_DWELL)
        L.append('G1 X%.3f Y%.3f F%d' % (_ox1-OFFX, _oy1-OFFY, OUTLINE_F))
        L.append('G4 P%d' % OUTLINE_DWELL)
        L.append('G1 X%.3f Y%.3f F%d' % (_ox0-OFFX, _oy1-OFFY, OUTLINE_F))
        L.append('G4 P%d' % OUTLINE_DWELL)
        L.append('G1 X%.3f Y%.3f F%d' % (_ox0-OFFX, _oy0-OFFY, OUTLINE_F))
        L.append('M400')
        L.append('G4 P1000')
for k in range(len(passes)):
    pn = passes[k]
    ordered, mydots = pass_strokes[k]
    L.append('; ======== PASS %d of %d : PEN %d [%s] ========' % (k+1, len(passes), pn, penname(pn)))
    if k > 0 or PENLOAD:
        L.append('PEN_PAUSE Z=%.3f X=%.1f Y=%.1f PEN=%d COLOR=%s   ; load pen %d [%s], seat to bed, PEN_RESUME' % (PDZ, LX - OFFX, LY - OFFY, pn, penname(pn), pn, penname(pn)))
        L.append('G1 Z%.3f F1200' % (PUZ + 10.0))
        L.append('M400')
    L.append('G1 Z%.3f F%d' % (PUZ, TF))
    if k in cal_rows and cal_rows[k]:
        L.append('; -- calibration row (pen %d [%s]): dial in Z now --' % (pn, penname(pn)))
        L.append('SET_DISPLAY_TEXT MSG="Pen %d [%s] marks - babystep Z now"' % (pn, penname(pn)))
        if k == 0 and cal_sig_polys:
            for _st in cal_sig_polys:
                L.append('G0 X%.3f Y%.3f F%d' % (_st[0][0]-OFFX, _st[0][1]-OFFY, TF))
                L.append('G1 Z%.3f F1200' % DRAW_Z)
                for q in _st[1:]:
                    L.append('G1 X%.3f Y%.3f F%d' % (q[0]-OFFX, q[1]-OFFY, DF))
                L.append('G1 Z%.3f F1200' % HOP_Z)
                L.append('G4 P%d' % CAL_PAUSE)
        for _mk in cal_rows[k]:
            _circ = _mk[0]
            L.append('G0 X%.3f Y%.3f F%d' % (_circ[0][0]-OFFX, _circ[0][1]-OFFY, TF))
            L.append('G1 Z%.3f F1200' % DRAW_Z)
            for q in _circ[1:]:
                L.append('G1 X%.3f Y%.3f F%d' % (q[0]-OFFX, q[1]-OFFY, DF))
            L.append('G1 Z%.3f F1200' % HOP_Z)
            L.append('G4 P%d' % CAL_PAUSE)
        for _mi in range(len(cal_rows[k])-1, -1, -1):
            _ctr = cal_rows[k][_mi][1]
            L.append('G0 X%.3f Y%.3f F%d' % (_ctr[0]-OFFX, _ctr[1]-OFFY, TF))
            L.append('G1 Z%.3f F1200' % DRAW_Z)
            L.append('G4 P%d' % max(int(DWELL), 100))
            L.append('G1 Z%.3f F1200' % HOP_Z)
            L.append('G4 P%d' % CAL_PAUSE)
        L.append('SET_DISPLAY_TEXT MSG="Plotting pass %d (pen %d [%s])..."' % (k+1, pn, penname(pn)))
    _wdist = 0.0        # mm drawn this pass, for tip wear comp (fresh tip per pass)
    for pl in ordered:
        L.append('G0 X%.3f Y%.3f F%d' % (pl[0].X-OFFX, pl[0].Y-OFFY, TF))
        _z0 = DRAW_Z + pl[0].Z * PGAIN - WEAR * _wdist / 1000.0
        if _z0 < 0.5: _z0 = 0.5
        if _z0 > HOP_Z: _z0 = HOP_Z
        L.append('G1 Z%.3f F%d' % (_z0, TF))
        _zc = _z0
        _pv = pl[0]
        for pt in pl[1:]:
            _wdist += _pv.DistanceTo(pt)
            _pv = pt
            _zt = DRAW_Z + pt.Z * PGAIN - WEAR * _wdist / 1000.0
            if _zt < 0.5: _zt = 0.5
            if _zt > HOP_Z: _zt = HOP_Z
            if abs(_zt - _zc) > 0.005:
                L.append('G1 X%.3f Y%.3f Z%.3f F%d' % (pt.X-OFFX, pt.Y-OFFY, _zt, DF))
                _zc = _zt
            else:
                L.append('G1 X%.3f Y%.3f F%d' % (pt.X-OFFX, pt.Y-OFFY, DF))
        L.append('G1 Z%.3f F%d' % (HOP_Z, TF))
    if mydots:
        L.append('; -- dots (pen %d) --' % pn)
        for p in mydots:
            L.append('G0 X%.3f Y%.3f F%d' % (p.X-OFFX, p.Y-OFFY, TF))
            _zd = DRAW_Z + p.Z * PGAIN - WEAR * _wdist / 1000.0
            if _zd < 0.5: _zd = 0.5
            if _zd > HOP_Z: _zd = HOP_Z
            L.append('G1 Z%.3f F1200' % _zd)
            if DWELL > 0:
                L.append('G4 P%d' % int(DWELL))
            L.append('G1 Z%.3f F1200' % HOP_Z)
    L.append('G1 Z%.3f F%d' % (PUZ + 10.0, TF))
# finish centered-X toward the back: clears the paper area for removal while
# staying 50mm shy of the Y350 extreme where the pen mount hits the frame.
# Steppers stay energized so homing/QGL survive for a follow-up plot.
L.append('G0 X175.0 Y300.0 F%d' % TF)
L.append('PEN_RESTORE_LIMITS')
L.append('SET_DISPLAY_TEXT MSG="Plot complete"')

nL = len(L)
prev = list(L[:26])
if nL > 30:
    prev.append('   ... (%d lines total - full file on WRITE) ...' % nL)
    prev.extend(L[-4:])
gcode_preview = '\n'.join(prev)

# ---- plan geometry: EXACTLY what will be emitted, for the preview ----
plan_pen1 = []; plan_pen2 = []; plan_pen3 = []; plan_pen4 = []
plan_pen5 = []; plan_pen6 = []; plan_pen7 = []; plan_pen8 = []
_buckets = [plan_pen1, plan_pen2, plan_pen3, plan_pen4, plan_pen5, plan_pen6, plan_pen7, plan_pen8]
for k in range(len(passes)):
    ordered, mydots = pass_strokes[k]
    pn = passes[k]
    _bi = pn - 1
    if _bi < 0: _bi = 0
    if _bi > 7: _bi = 7
    for pl in ordered:
        _lp = List[rg.Point3d]()
        for pt in pl:
            _lp.Add(rg.Point3d(pt))
        _buckets[_bi].append(rg.PolylineCurve(_lp))
plan_dots = []
for k in range(len(passes)):
    for p in pass_strokes[k][1]:
        plan_dots.append(rg.Point3d(p))
plan_signature = []
for _st in cal_sig_polys:
    _lp = List[rg.Point3d]()
    for q in _st:
        _lp.Add(rg.Point3d(q[0], q[1], 0))
    plan_signature.append(rg.PolylineCurve(_lp))
for k in cal_rows:
    for _mk in cal_rows[k]:
        _lp = List[rg.Point3d]()
        for q in _mk[0]:
            _lp.Add(rg.Point3d(q[0], q[1], 0))
        plan_signature.append(rg.PolylineCurve(_lp))
        plan_signature.append(rg.Circle(rg.Point3d(_mk[1][0], _mk[1][1], 0), 0.5).ToNurbsCurve())
# pen-load point marker (where the seating dot may land)
if passes:
    plan_signature.append(rg.Circle(rg.Point3d(LX, LY, 0), 2.5).ToNurbsCurve())
    plan_signature.append(rg.Circle(rg.Point3d(LX, LY, 0), 0.4).ToNurbsCurve())

# ---- job manifest ----
# how the size was arrived at - never call it "1:1" once a scale multiplier
# is in play, that reads as a contradiction next to the number
_sc = fr.get("scale", 1.0)
if fr.get("fit", 0):
    _how = 'FIT'
elif abs(_sc - 1.0) < 0.001:
    _how = '1:1'
else:
    _how = 'SCALED %d%%' % int(round(_sc * 100.0))

_mode_txt = 'DIRECT passthrough (curves plot at their Rhino coords, pen-compensated)'
if fr.get("mode") == "reg":
    _mode_txt = 'REGISTERED paper, %s scale %.2f' % (_how, _sc)
elif fr.get("mode") == "centered":
    _mode_txt = 'BED-CENTERED, %s scale %.2f' % (_how, _sc)
elif fr.get("mode") == "graph":
    _mode_txt = 'FROM GRAPH, centre (%.1f, %.1f), %s scale %.2f' % (
        fr.get("gx", 0.0), fr.get("gy", 0.0), _how, _sc)
if fr.get("locked", 0):
    _mode_txt += ' [PLACEMENT LOCKED]'
_man = []
_man.append('JOB: %d pass(es) | est %s' % (len(passes), est))
_man.append('placement: %s' % _mode_txt)
for k in range(len(passes)):
    ordered, mydots = pass_strokes[k]
    _dd = 0.0
    for pl in ordered:
        for i in range(1, len(pl)):
            _dd += pl[i-1].DistanceTo(pl[i])
    _man.append('PASS %d - pen %d [%s]: %d strokes (%.1fm)%s' % (k+1, passes[k], penname(passes[k]), len(ordered), _dd/1000.0, (', %d dots' % len(mydots)) if mydots else ''))
_man.append('speeds: %s (draw %d / travel %d / accel %d)' % (PROF_NAME, DF, TF, AC))
if WEAR > 0.0001:
    _mx = 0.0
    for k in range(len(passes)):
        _dd2 = 0.0
        for pl in pass_strokes[k][0]:
            for i in range(1, len(pl)):
                _dd2 += pl[i-1].DistanceTo(pl[i])
        if _dd2 > _mx: _mx = _dd2
    _man.append('tip wear comp: %.2f mm/m -> Z drops up to %.3f mm by pass end (reset each pen)' % (WEAR, WEAR*_mx/1000.0))
_man.append('signature: %s' % ('ON (JC + %d cal rows)' % len(cal_rows) if cal_rows else 'off'))
if MESH and xs:
    _man.append('mesh: adaptive over plot area only (pen offset included)')
if OUTLINE and xs:
    _man.append('alignment outline: ON (slow bbox trace before pen load)')
if press_pens:
    if PGAIN > 0.001:
        _man.append('pressure: gain %.2f on pen(s) %s' % (PGAIN, str(sorted(press_pens))))
    else:
        _man.append('pressure: present on pen(s) %s but gain 0 - plotting FLAT' % str(sorted(press_pens)))
if pwarn:
    _man.append('!! ART EXCEEDS PAPER (1:1) !!')
if warn:
    _man.append('!! OUT OF BOUNDS - PLOT blocked !!')
if fr.get("noregfile", 0):
    _man.append('!! registration requested but no file - centered fallback !!')
st = '\n'.join(_man)

gcode = None
if WRITE or PLOT:
    gcode = '\n'.join(L) + '\n'
if WRITE:
    try:
        if not os.path.isdir(out_dir):
            os.makedirs(out_dir)
    except:
        pass
    fh = open(out_file, 'w')
    fh.write(gcode)
    fh.close()
    st += '\nWROTE ' + out_file
if PLOT:
    if warn:
        st += '\nPLOT BLOCKED: out of bounds!'
    else:
        try:
            from System.Net import WebClient
            from System.Text import Encoding
            b = '----GHPenPlotBoundary'
            body = '--' + b + '\r\n'
            body += 'Content-Disposition: form-data; name="root"\r\n\r\ngcodes\r\n'
            body += '--' + b + '\r\n'
            body += 'Content-Disposition: form-data; name="file"; filename="plot.gcode"\r\n'
            body += 'Content-Type: text/plain\r\n\r\n'
            body += gcode
            body += '\r\n--' + b + '--\r\n'
            wc = WebClient()
            wc.Headers.Add('Content-Type', 'multipart/form-data; boundary=' + b)
            wc.UploadData('http://192.168.1.23:7125/server/files/upload', 'POST', Encoding.UTF8.GetBytes(body))
            wc2 = WebClient()
            wc2.UploadString('http://192.168.1.23:7125/printer/print/start?filename=plot.gcode', 'POST', '')
            st += '\nUPLOADED + PLOT STARTED on Voron'
        except Exception as ue:
            st += '\nPLOT FAILED: ' + str(ue)
print(st)
