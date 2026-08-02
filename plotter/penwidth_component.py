# PEN WIDTHS - the line weight each pen actually lays down.
#
# Design-time metadata, so it lives here rather than on the printer (the
# machine never needs it; Grasshopper does, on every solve). Stored in
# pen_widths.json next to the definition.
# Feed `w` into anything that needs to know how fat the pen is:
#   THINOUT.spacing      - cull strokes the pen cannot separate
#   POINTILLISM.pen_width - spiral pitch for filled dots
#   HATCH/HILBERT.inset   - keep fills off their own boundary
# Set a pen: pick it, set `width`, press `save`. Reading needs no press.
# `px_per_mm` converts the stored widths into preview thicknesses t1..t8 for
# Custom Preview Lineweights. NOTE those are SCREEN PIXELS, so the preview
# shows relative weight faithfully but is not true-scale and does not track
# zoom - it is a reading aid, not a simulation.
# Inputs: pen(1-8), width(mm), save(button), px_per_mm
# Outputs: w (this pen's stored width), table (all of them), t1..t8 (px)
import json
import os

WFILE = r'C:\Users\john.chandler\voron_plotter\pen_widths.json'
PEN_NAMES = {1: 'BLACK FINE', 2: 'BLACK BOLD', 3: 'BLACK ROLLER', 4: 'RED FINE',
             5: 'CUSTOM 1', 6: 'CUSTOM 2', 7: 'CUSTOM 3', 8: 'CUSTOM 4'}
DEFAULT = 0.45

PN = int(pen) if pen is not None else 1
if PN < 1:
    PN = 1
if PN > 8:
    PN = 8
WD = float(width) if width is not None else DEFAULT
if WD < 0.01:
    WD = 0.01

data = {}
try:
    fh = open(WFILE)
    data = json.loads(fh.read())
    fh.close()
except:
    data = {}

if save:
    data[str(PN)] = round(WD, 3)
    try:
        fh = open(WFILE, 'w')
        fh.write(json.dumps(data))
        fh.close()
        note = 'SAVED pen %d = %.2fmm' % (PN, WD)
    except Exception as e:
        note = 'save failed: %s' % str(e)
else:
    note = ''

w = data.get(str(PN), DEFAULT)
rows = []
for n in range(1, 9):
    if str(n) in data:
        rows.append('%d[%s] %.2f' % (n, PEN_NAMES.get(n, '?'), data[str(n)]))
table = ' | '.join(rows) if rows else 'nothing saved yet (defaults to %.2fmm)' % DEFAULT

PPM = float(px_per_mm) if px_per_mm is not None else 6.0
if PPM < 0.1:
    PPM = 0.1
_t = []
for n in range(1, 9):
    _wn = data.get(str(n), DEFAULT)
    _px = int(round(_wn * PPM))
    if _px < 1:
        _px = 1
    _t.append(_px)
t1, t2, t3, t4, t5, t6, t7, t8 = _t

msg = 'pen %d [%s] = %.2fmm' % (PN, PEN_NAMES.get(PN, '?'), w)
if note:
    msg = note + '  ->  ' + table
else:
    msg = msg + '   |   ' + table
print(msg)
