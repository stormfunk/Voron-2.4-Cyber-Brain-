# ================================================================
# Voron Pen-Plotter Pipeline  -  paste into ONE GhPython component
# Curves -> pen-plotter G-code (moves only, NO heat) for Voron 2.4 (350 bed)
# ----------------------------------------------------------------
# Add these INPUTS on the component (zoom in, click the + ; rename each).
# All are optional - safe defaults are used if an input isn't wired yet:
#   count        num   number of concentric circles        [8]
#   spacing      num   mm between circles                   [12]
#   pen_down_z   num   Z where the pen touches paper        [2.0]   <-- your Z offset
#   pen_up_z     num   Z for travel / pen lifted            [8.0]
#   draw_feed    num   drawing feedrate mm/min              [3000]
#   travel_feed  num   travel feedrate mm/min               [6000]
#   resolution   num   curve sampling step mm               [1.0]
#   do_qgl       bool  run QUAD_GANTRY_LEVEL at start       [True]
#   do_mesh      bool  run BED_MESH_CALIBRATE at start      [False]
#   write        bool  actually write the .gcode file       [False]
# OUTPUTS: a = gcode text (wire to a panel) ,  out = status line
# ================================================================
import Rhino.Geometry as rg
import os

# --- make every optional input safe whether or not it's been added/wired ---
def _num(v, d):
    try:
        return float(v)
    except:
        return d
def _flag(v, d):
    return d if v is None else bool(v)

try: count
except NameError: count = None
try: spacing
except NameError: spacing = None
try: pen_down_z
except NameError: pen_down_z = None
try: pen_up_z
except NameError: pen_up_z = None
try: draw_feed
except NameError: draw_feed = None
try: travel_feed
except NameError: travel_feed = None
try: resolution
except NameError: resolution = None
try: do_qgl
except NameError: do_qgl = None
try: do_mesh
except NameError: do_mesh = None
try: write
except NameError: write = None

CNT   = int(_num(count, 8))
SP    = _num(spacing, 12.0)
PDZ   = _num(pen_down_z, 2.0)
PUZ   = _num(pen_up_z, 8.0)
DF    = int(_num(draw_feed, 3000))
TF    = int(_num(travel_feed, 6000))
RES   = _num(resolution, 1.0)
QGL   = _flag(do_qgl, True)
MESH  = _flag(do_mesh, False)
WRITE = _flag(write, False)

BED      = 350.0
OUT_DIR  = r'C:\Users\john.chandler\voron_plotter'
OUT_FILE = os.path.join(OUT_DIR, 'plot.gcode')

# --- 1) generate curves  (concentric circles; edit this block for other art) ---
curves = []
for i in range(1, CNT + 1):
    curves.append(rg.Circle(rg.Plane.WorldXY, i * SP).ToNurbsCurve())

# --- 2) sample each curve into points ---
def sample(c):
    pts = []
    ts = c.DivideByLength(RES, True)
    if ts:
        for t in ts:
            pts.append(c.PointAt(t))
    sp = c.PointAtStart; ep = c.PointAtEnd
    if not pts or pts[0].DistanceTo(sp) > 1e-6: pts.insert(0, sp)
    if not pts or pts[-1].DistanceTo(ep) > 1e-6: pts.append(ep)
    return pts

polys = []; xs = []; ys = []
for c in curves:
    p = sample(c)
    if len(p) >= 2:
        polys.append(p)
        for pt in p:
            xs.append(pt.X); ys.append(pt.Y)

# center artwork on the bed
dx = (BED/2.0 - (min(xs)+max(xs))/2.0) if xs else 0.0
dy = (BED/2.0 - (min(ys)+max(ys))/2.0) if ys else 0.0

warn = ''
if xs and ((min(xs)+dx) < 0 or (min(ys)+dy) < 0 or (max(xs)+dx) > BED or (max(ys)+dy) > BED):
    warn = '; WARNING: toolpath exceeds bed bounds'

# --- 3) build pen-plotter g-code (calibration only, NO heating) ---
L = []
L.append('; Voron pen-plot  (moves only, no heat)')
L.append('; polylines=%d  resolution=%s mm' % (len(polys), RES))
if warn: L.append(warn)
L.append('CLEAR_PAUSE')
L.append('SET_GCODE_OFFSET Z=0')
L.append('G21')                    # mm
L.append('G90')                    # absolute
L.append('G28')                    # home all
if QGL:
    L.append('QUAD_GANTRY_LEVEL')  # level gantry  (the step that was missing)
    L.append('G28 Z')              # re-home Z after QGL
if MESH:
    L.append('BED_MESH_CALIBRATE ADAPTIVE=1')
L.append('G1 Z%.3f F%d' % (PUZ, TF))          # pen up
for pl in polys:
    L.append('G0 X%.3f Y%.3f F%d' % (pl[0].X+dx, pl[0].Y+dy, TF))  # travel to start
    L.append('G1 Z%.3f F%d' % (PDZ, TF))                          # pen down
    for pt in pl[1:]:
        L.append('G1 X%.3f Y%.3f F%d' % (pt.X+dx, pt.Y+dy, DF))   # draw
    L.append('G1 Z%.3f F%d' % (PUZ, TF))                          # pen up
L.append('G1 Z%.3f F%d' % (PUZ + 10.0, TF))   # extra lift
L.append('G0 X0 Y%d F%d' % (int(BED), TF))    # park at back-left
L.append('M84')                               # steppers off
gcode = '\n'.join(L) + '\n'

# --- outputs ---
a = gcode
if WRITE:
    try:
        if not os.path.isdir(OUT_DIR): os.makedirs(OUT_DIR)
    except: pass
    fh = open(OUT_FILE, 'w'); fh.write(gcode); fh.close()
    out = 'WROTE %s  (%d lines, %d polylines)%s' % (OUT_FILE, len(L), len(polys), (' | '+warn if warn else ''))
else:
    out = 'preview only - set write=True to save. %d lines, %d polylines%s' % (len(L), len(polys), (' | '+warn if warn else ''))
