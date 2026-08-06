# MID-PLOT - everything you touch while the ink is wet, in one console.
#
# Was PEN CONTROL and PEN TRIM as two components in two groups. They are always
# used together: you pause, swap the pen, then nudge the new tip into alignment
# and resume. Splitting them meant two boxes and a hunt, mid-plot, with a pen
# drying in your hand.
#
#   pause / resume : PEN_PAUSE parks at the pen-load point and waits;
#                    PEN_RESUME continues (no un-retract, no re-park)
#   collet         : PEN_COLLET parks at the QR-collet fitting position
#   x/y +-         : shift the DRAWING by `step` mm, live, for the rest of the pass
#   z +-           : pen DOWN (press harder) / UP (lighter) by `z_step`
#   reset          : clear the X/Y trim. LEAVES Z alone on purpose - zeroing Z
#                    mid-plot would lift the pen clean off the paper.
#
# Klipper accumulates the adjusts and they persist to the end of the plot, so
# the current total is reported after every press - a trim you cannot see is a
# trim you will forget you dialled in.
# Inputs: pause, resume, collet, x_minus, x_plus, y_minus, y_plus, z_minus,
#         z_plus, reset (buttons), step (mm/press X/Y), z_step (mm/press Z)
import urllib
import urllib2
import json

HOST = 'http://192.168.1.23:7125'
STEP = float(step) if step is not None else 0.1
if STEP < 0.0:
    STEP = 0.0
ZSTEP = float(z_step) if z_step is not None else 0.025
if ZSTEP < 0.0:
    ZSTEP = 0.0


def send(cmd):
    url = HOST + '/printer/gcode/script?script=' + urllib.quote(cmd)
    return urllib2.urlopen(urllib2.Request(url, ''), timeout=25).getcode()


def read_trim():
    try:
        u = HOST + '/printer/objects/query?gcode_move=homing_origin'
        d = json.loads(urllib2.urlopen(u, timeout=6).read())
        o = d['result']['status']['gcode_move']['homing_origin']
        return (o[0], o[1], o[2])
    except:
        return None


msg = 'pause -> swap -> trim -> resume   (XY step %.2f, Z step %.3f)' % (STEP, ZSTEP)
did = None
try:
    # ---- pen handling ----
    if pause:
        send('PEN_PAUSE')
        did = 'PEN_PAUSE sent - parked at the load point'
    elif resume:
        send('PEN_RESUME')
        did = 'PEN_RESUME sent'
    elif collet:
        send('PEN_COLLET')
        did = 'PEN_COLLET sent - at the collet fitting position'
    # ---- live trim ----
    elif x_plus:
        send('SET_GCODE_OFFSET X_ADJUST=%.3f MOVE=1' % STEP); did = 'X +%.2f' % STEP
    elif x_minus:
        send('SET_GCODE_OFFSET X_ADJUST=%.3f MOVE=1' % -STEP); did = 'X -%.2f' % STEP
    elif y_plus:
        send('SET_GCODE_OFFSET Y_ADJUST=%.3f MOVE=1' % STEP); did = 'Y +%.2f' % STEP
    elif y_minus:
        send('SET_GCODE_OFFSET Y_ADJUST=%.3f MOVE=1' % -STEP); did = 'Y -%.2f' % STEP
    elif z_plus:
        send('SET_GCODE_OFFSET Z_ADJUST=%.3f MOVE=1' % ZSTEP)
        did = 'Z +%.3f (lift, lighter)' % ZSTEP
    elif z_minus:
        send('SET_GCODE_OFFSET Z_ADJUST=%.3f MOVE=1' % -ZSTEP)
        did = 'Z -%.3f (down, harder)' % ZSTEP
    elif reset:
        send('SET_GCODE_OFFSET X=0 Y=0 MOVE=1')
        did = 'X/Y trim reset (Z kept)'
    if did is not None:
        t = read_trim()
        if t is not None:
            msg = '%s  ->  trim  X %+.2f  Y %+.2f  Z %+.3f' % (did, t[0], t[1], t[2])
        else:
            msg = '%s (sent)' % did
except Exception as e:
    msg = 'FAILED: %s' % str(e)

print(msg)
