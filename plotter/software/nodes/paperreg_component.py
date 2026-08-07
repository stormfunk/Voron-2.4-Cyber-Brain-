# PAPER REGISTRATION - teach the printer where the sheet actually is, and read
# the answer back. One console for the whole story.
#
# Workflow: home, load a pen, then jog the PEN TIP to each paper corner in turn
# and press the matching TEACH button. Three corners define the sheet's origin,
# width, height, rotation and skew.
#
# PULL used to be its own component (REGSYNC) sitting beside this one, which was
# always odd: teaching a corner ALREADY pulls automatically so the preview can
# update live, so the separate box only existed for the manual case. Same job,
# same group, one output - it belongs here.
#
#   jog buttons    : move the toolhead by `jog` mm (X-/X+/Y-/Y+), Z by `jog_z`
#   teach_fl/fr/bl : store the current position as front-left / front-right /
#                    back-left, then auto-pull so the paper outline updates
#   pull           : re-read the taught corners from the printer by hand
#   home           : G28 (do this first - jogging needs a homed machine)
#
# Outputs `reg_json`: a one-line summary of the registration currently on file,
# which PLACE consumes and the receipt panel displays.
# Inputs: home, jog_xm, jog_xp, jog_ym, jog_yp, jog_zd, jog_zu,
#         teach_fl, teach_fr, teach_bl, pull (buttons), jog(mm), jog_z(mm)
import urllib
import urllib2
import json
import math

HOST = 'http://192.168.1.23:7125'
REGFILE = r'C:\Users\john.chandler\voron_plotter\paper_registration.json'


def pull_registration():
    """fetch the taught corners and write the registration file. Returns a short
    status string. Missing corners are tolerated - a half-taught paper keeps the
    corners it has so the preview can update after EACH teach."""
    try:
        u = HOST + '/printer/objects/query?save_variables=variables'
        d = json.loads(urllib2.urlopen(u, timeout=8).read())
        v = d['result']['status']['save_variables']['variables']
        got = {}
        for k, nm in [('paper_p0', 'p0'), ('paper_p1', 'p1'), ('paper_p2', 'p2')]:
            if k in v and v[k]:
                got[nm] = v[k]
        if len(got) < 3:
            try:
                fh = open(REGFILE)
                old = json.loads(fh.read())
                fh.close()
                for nm in ['p0', 'p1', 'p2']:
                    if nm not in got and nm in old:
                        got[nm] = old[nm]
            except:
                pass
        if len(got) < 3:
            return 'pulled %d/3 corners (teach the rest)' % len(got)
        fh = open(REGFILE, 'w')
        fh.write(json.dumps({'p0': got['p0'], 'p1': got['p1'], 'p2': got['p2']}))
        fh.close()
        ux = got['p1'][0] - got['p0'][0]
        uy = got['p1'][1] - got['p0'][1]
        vx = got['p2'][0] - got['p0'][0]
        vy = got['p2'][1] - got['p0'][1]
        w = math.sqrt(ux * ux + uy * uy)
        h = math.sqrt(vx * vx + vy * vy)
        rot = math.degrees(math.atan2(uy, ux))
        return 'paper now %.0fx%.0fmm rot %.1fdeg' % (w, h, rot)
    except Exception as e:
        return 'pull failed: %s' % str(e)


JOG = float(jog) if jog is not None else 5.0
if JOG < 0.0:
    JOG = 0.0
JOGZ = float(jog_z) if jog_z is not None else 1.0
if JOGZ < 0.0:
    JOGZ = 0.0


def send(cmd):
    url = HOST + '/printer/gcode/script?script=' + urllib.quote(cmd)
    return urllib2.urlopen(urllib2.Request(url, ''), timeout=10).getcode()


def pos():
    try:
        u = HOST + '/printer/objects/query?toolhead=position,homed_axes'
        d = json.loads(urllib2.urlopen(u, timeout=6).read())
        t = d['result']['status']['toolhead']
        return (t['position'][0], t['position'][1], t['position'][2], t['homed_axes'])
    except:
        return None


msg = 'jog the PEN TIP to a corner, then TEACH  (jog %.1fmm, Z %.1fmm)' % (JOG, JOGZ)
did = None
taught = False
try:
    if home:
        send('G28'); did = 'homed'
    elif jog_xm:
        send('G91'); send('G0 X%.3f F6000' % -JOG); send('G90'); did = 'X -%.1f' % JOG
    elif jog_xp:
        send('G91'); send('G0 X%.3f F6000' % JOG); send('G90'); did = 'X +%.1f' % JOG
    elif jog_ym:
        send('G91'); send('G0 Y%.3f F6000' % -JOG); send('G90'); did = 'Y -%.1f' % JOG
    elif jog_yp:
        send('G91'); send('G0 Y%.3f F6000' % JOG); send('G90'); did = 'Y +%.1f' % JOG
    elif jog_zd:
        send('G91'); send('G0 Z%.3f F900' % -JOGZ); send('G90'); did = 'Z -%.1f' % JOGZ
    elif jog_zu:
        send('G91'); send('G0 Z%.3f F900' % JOGZ); send('G90'); did = 'Z +%.1f' % JOGZ
    elif teach_fl:
        send('PAPER_SET_FL'); did = 'TAUGHT front-left (P0)'; taught = True
    elif teach_fr:
        send('PAPER_SET_FR'); did = 'TAUGHT front-right (P1)'; taught = True
    elif teach_bl:
        send('PAPER_SET_BL'); did = 'TAUGHT back-left (P2)'; taught = True
    elif pull:
        did = 'PULLED'; taught = True
    if taught:
        msg = '%s  ->  %s' % (did, pull_registration())
    elif did is not None:
        p = pos()
        if p is not None:
            msg = '%s  |  nozzle X %.1f Y %.1f Z %.1f  (homed: %s)' % (
                did, p[0], p[1], p[2], p[3] if p[3] else 'NO')
        else:
            msg = '%s (sent)' % did
except Exception as e:
    msg = 'FAILED: %s' % str(e)

# ---- always report the registration currently on file -----------------------
# This is what PLACE reads. It is emitted on EVERY solve, not only after a pull,
# so a fresh session already knows where the paper is.
try:
    fh = open(REGFILE)
    reg = json.loads(fh.read())
    fh.close()
    ux = reg['p1'][0] - reg['p0'][0]; uy = reg['p1'][1] - reg['p0'][1]
    vx = reg['p2'][0] - reg['p0'][0]; vy = reg['p2'][1] - reg['p0'][1]
    w = math.sqrt(ux * ux + uy * uy); h = math.sqrt(vx * vx + vy * vy)
    rot = math.degrees(math.atan2(uy, ux))
    reg_json = ('paper %.0fx%.0fmm rot %.1fdeg | P0(%.1f,%.1f) P1(%.1f,%.1f) P2(%.1f,%.1f)'
                % (w, h, rot, reg['p0'][0], reg['p0'][1], reg['p1'][0],
                   reg['p1'][1], reg['p2'][0], reg['p2'][1]))
except Exception as e:
    reg_json = 'no valid registration file (%s)' % str(e)

print(msg)
