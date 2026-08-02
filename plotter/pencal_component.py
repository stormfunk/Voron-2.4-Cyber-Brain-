# PEN TOOL TABLE - per-pen XYZ calibration, like CNC tool offsets.
#
# A pen's calibration belongs to the PEN SLOT, not to the plotting order, so
# re-ordering passes never invalidates it. Once every pen you use is calibrated,
# swapping mid-plot needs no babystepping: the machine already knows exactly
# where each tip sits.
#
# Per pen:
#   1) collet  -> parks high so you can fit the pen from underneath
#   2) cal_pos -> drops to the calibration point at nominal draw height
#   3) adjust the pen in the collet (or jog Z) until the tip just touches
#   4) store   -> saves that exact position as this pen's datum
# Pen 1 is the datum; the others are stored relative to it.
#
# COMMIT folds a live trim into the stored datum: if you babystep mid-plot to
# fix a pen sitting high, commit makes that correction permanent instead of
# losing it at the end of the job. Nothing moves when it runs. Pen 1 is the
# datum so it cannot absorb a trim - that error belongs in pen_down_z.
# Inputs: collet, cal_pos, store, apply, commit, table, clear (buttons), pen(1-8)
import urllib
import urllib2

HOST = 'http://192.168.1.23:7125'
PEN = int(pen) if pen is not None else 1
if PEN < 1:
    PEN = 1
if PEN > 8:
    PEN = 8


def send(cmd):
    url = HOST + '/printer/gcode/script?script=' + urllib.quote(cmd)
    return urllib2.urlopen(urllib2.Request(url, ''), timeout=60).getcode()


def read_table():
    import json
    try:
        u = HOST + '/printer/objects/query?save_variables=variables'
        d = json.loads(urllib2.urlopen(u, timeout=8).read())
        v = d['result']['status']['save_variables']['variables']
        ref = v.get('pen_cal_1')
        rows = []
        for n in range(1, 9):
            me = v.get('pen_cal_%d' % n)
            if not me:
                continue
            if ref and n != 1:
                rows.append('pen %d: dX%+.2f dY%+.2f dZ%+.2f' % (
                    n, me[0] - ref[0], me[1] - ref[1], me[2] - ref[2]))
            else:
                rows.append('pen %d: X%.2f Y%.2f Z%.2f (datum)' % (n, me[0], me[1], me[2]))
        if not rows:
            return 'no pens calibrated yet'
        return ' | '.join(rows)
    except Exception as e:
        return 'table read failed: %s' % str(e)


msg = 'PEN %d selected  |  %s' % (PEN, read_table())
try:
    if collet:
        send('PEN_COLLET')
        msg = 'at collet position - fit pen %d from underneath, then CAL POS' % PEN
    elif cal_pos:
        send('PEN_CAL_POS')
        msg = 'at cal point - set pen %d tip so it just touches, then STORE' % PEN
    elif store:
        send('PEN_CALIBRATE PEN=%d' % PEN)
        msg = 'PEN %d STORED  |  %s' % (PEN, read_table())
    elif apply:
        send('PEN_APPLY PEN=%d' % PEN)
        msg = 'pen %d offsets applied  |  %s' % (PEN, read_table())
    elif commit:
        if PEN == 1:
            msg = ('pen 1 is the DATUM - a trim on it cannot be stored (it would '
                   'just re-zero itself). Adjust pen_down_z instead, or re-run '
                   'STORE at the cal dot to move the datum.')
        else:
            send('PEN_COMMIT PEN=%d' % PEN)
            msg = 'pen %d trim committed to its datum  |  %s' % (PEN, read_table())
    elif table:
        send('PEN_TABLE')
        msg = 'TABLE: %s' % read_table()
    elif clear:
        send('PEN_CLEAR_CAL PEN=%d' % PEN)
        msg = 'pen %d cleared  |  %s' % (PEN, read_table())
except Exception as e:
    msg = 'FAILED: %s' % str(e)

print(msg)
