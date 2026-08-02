# PEN TRIM - live X / Y / Z alignment nudge, the babystepping panel for pens.
# The pen mount shifts a fat pen vs a thin pen (mostly Y, a little X), and each
# pen sits at a slightly different height. Nudge here and the shift applies live
# (SET_GCODE_OFFSET ..._ADJUST MOVE=1) to the rest of the pass.
#   x_minus / x_plus : shift drawing -X / +X by `step`
#   y_minus / y_plus : shift drawing -Y / +Y by `step`
#   z_minus / z_plus : pen DOWN (press harder) / UP (lighter) by `z_step`
#   reset            : clear X/Y trim to 0. LEAVES Z alone on purpose - zeroing
#                      Z mid-plot would lift the pen off the paper.
# Klipper accumulates the adjusts (they persist to end of plot / restart).
# Reports the current total trim on all three axes after each press.
# Inputs: x_minus, x_plus, y_minus, y_plus, z_minus, z_plus, reset (buttons),
#         step (mm/press, X/Y), z_step (mm/press, Z)
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
    return urllib2.urlopen(urllib2.Request(url, ''), timeout=8).getcode()


def read_trim():
    try:
        u = HOST + '/printer/objects/query?gcode_move=homing_origin'
        d = json.loads(urllib2.urlopen(u, timeout=6).read())
        o = d['result']['status']['gcode_move']['homing_origin']
        return (o[0], o[1], o[2])
    except:
        return None


msg = 'X/Y/Z trim: align a freshly-swapped pen (XY step %.2f, Z step %.3f)' % (STEP, ZSTEP)
did = None
try:
    if x_plus:
        send('SET_GCODE_OFFSET X_ADJUST=%.3f MOVE=1' % STEP)
        did = 'X +%.2f' % STEP
    elif x_minus:
        send('SET_GCODE_OFFSET X_ADJUST=%.3f MOVE=1' % -STEP)
        did = 'X -%.2f' % STEP
    elif y_plus:
        send('SET_GCODE_OFFSET Y_ADJUST=%.3f MOVE=1' % STEP)
        did = 'Y +%.2f' % STEP
    elif y_minus:
        send('SET_GCODE_OFFSET Y_ADJUST=%.3f MOVE=1' % -STEP)
        did = 'Y -%.2f' % STEP
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
