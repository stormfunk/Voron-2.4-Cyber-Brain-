# TITLEBLOCK - imports the plotter titleblock SVG and lays it on the registered
# paper, scaled to the sheet and rotated with it.
#
# The SVG is authored as pure single-stroke polylines at 180 x 40 mm with one
# top-level group per ink (`pen-1`, `pen-2`, `pen-3`). Each ink comes out on its
# own output so you can send it to whichever plotter pen you like.
# SVG's Y axis points DOWN, so it is flipped on import.
# Only M/L path commands and <circle> are parsed - that is all the design uses.
# Inputs: svg(file path), frame(json from PLACE), on(bool), margin(mm inset from
#         the paper edge), height(mm, 0 = keep the SVG's own proportion)
# Outputs: ink_a = the black linework (SVG pen-1)
#          ink_b = the accent inks merged (SVG pen-2 amber + pen-3 green)
# Two outputs so the block needs only two plotter pens; pick them with the two
# dropdowns beside it.
import Rhino.Geometry as rg
import scriptcontext as sc
import math
import re
import json
from System.Collections.Generic import List
try:
    sc.doc = ghdoc
except:
    pass

ON = True if on is None else bool(on)
MARGIN = float(margin) if margin is not None else 8.0
if MARGIN < 0.0:
    MARGIN = 0.0
HFORCE = float(height) if height is not None else 0.0
# fill: stretch the title zone so the block spans the sheet at the chosen
# height. Off = plain uniform scale (keeps the 180x40 proportion).
FILL = True if fill is None else bool(fill)
SVGW = 180.0
SVGH = 40.0
FONTDIR = r'C:\Users\john.chandler\voron_plotter'
WFILE = r'C:\Users\john.chandler\voron_plotter\pen_widths.json'

path = None
if svg is not None:
    try:
        path = str(svg).strip('"')
    except:
        path = None


def _d_to_polys(d):
    out = []
    cur = []
    for cmd, sx, sy in re.findall(r'([ML])\s*(-?[\d.]+)[\s,]+(-?[\d.]+)', d):
        p = (float(sx), float(sy))
        if cmd == 'M':
            if len(cur) > 1:
                out.append(cur)
            cur = [p]
        else:
            cur.append(p)
    if len(cur) > 1:
        out.append(cur)
    return out


def parse_ink(txt, gid, skip_ids):
    """polylines from one top-level <g id="pen-N"> block, plus the bounding box
    of every id we intend to redraw as live text"""
    out = []
    boxes = {}
    i = txt.find('id="%s"' % gid)
    if i < 0:
        return out, boxes
    j = txt.find('<g id="pen-', i + 10)
    if j < 0:
        j = len(txt)
    blk = txt[i:j]
    for pid, d in re.findall(r'<path\s+id="([^"]+)"\s+d="([^"]+)"', blk):
        polys = _d_to_polys(d)
        if pid in skip_ids:
            xs2 = []; ys2 = []
            for pl in polys:
                for q in pl:
                    xs2.append(q[0]); ys2.append(q[1])
            if xs2:
                boxes[pid] = (min(xs2), min(ys2), max(xs2), max(ys2))
            continue                    # dropped - live text replaces it
        for pl in polys:
            out.append(pl)
    # paths without an id (none in this file, but be safe)
    for d in re.findall(r'<path\s+d="([^"]+)"', blk):
        for pl in _d_to_polys(d):
            out.append(pl)
    for cx, cy, r in re.findall(r'<circle[^>]*cx="(-?[\d.]+)"[^>]*cy="(-?[\d.]+)"[^>]*r="(-?[\d.]+)"', blk):
        cx = float(cx); cy = float(cy); r = float(r)
        ring = []
        for k in range(33):
            a = 6.283185307 * k / 32.0
            ring.append((cx + r * math.cos(a), cy + r * math.sin(a)))
        out.append(ring)
    return out, boxes


ink1 = []
ink2 = []
ink3 = []
info = ''
if not ON:
    info = '[OFF]'
elif not path:
    info = 'no SVG path set'
else:
    txt = ''
    try:
        fh = open(path)
        txt = fh.read()
        fh.close()
    except Exception as e:
        txt = ''
        info = 'could not read SVG: %s' % str(e)
    if txt:
        # ---- live values ----------------------------------------------------
        # Each entry: svg id -> (text, alignment). The placeholder polylines for
        # these ids are dropped and redrawn with the stroke font at the same
        # position and cap height, so the block reports the real job.
        import sys
        if FONTDIR not in sys.path:
            sys.path.append(FONTDIR)
        import strokefont
        reload(strokefont)

        fr0 = {}
        try:
            fr0 = json.loads(frame) if frame else {}
        except:
            fr0 = {}
        # scale / paper straight from the placement frame
        _sc = fr0.get('scale', 1.0)
        if fr0.get('fit', 0):
            s_scale = 'FIT %d%%' % int(round(_sc * 100.0))
        elif abs(_sc - 1.0) < 0.001:
            s_scale = '1:1'
        else:
            s_scale = 'SCALED %d%%' % int(round(_sc * 100.0))
        if fr0.get('wu'):
            s_paper = '%d X %d' % (int(round(fr0['wu'])), int(round(fr0['hv'])))
        else:
            s_paper = 'UNREGISTERED'
        # Duration and the pen index are worked out HERE rather than read from
        # the manifest: the block is part of the job it describes, so taking
        # GCODE's output would make this component depend on itself.
        PEN_NAMES = {1: 'BLACK FINE', 2: 'BLACK BOLD', 3: 'BLACK ROLLER', 4: 'RED FINE',
                     5: 'CUSTOM 1', 6: 'CUSTOM 2', 7: 'CUSTOM 3', 8: 'CUSTOM 4'}
        s_dur = ''
        pen_rows = []
        _seen = []
        if art_pens:
            for q in art_pens:
                try:
                    v = int(q)
                except:
                    continue
                if v >= 1 and v not in _seen:
                    _seen.append(v)
        for v in sorted(_seen):
            pen_rows.append((str(v), PEN_NAMES.get(v, 'PEN %d' % v)))
        _dl = 0.0
        if art:
            for c in art:
                try:
                    _dl += c.GetLength()
                except:
                    pass
        _df = float(draw_feed) if draw_feed else 3000.0
        if _df > 1.0 and _dl > 0.0:
            # drawing time plus a travel/lift allowance - close enough for a stamp
            s_dur = 'EST %.1f MIN' % (_dl / _df * 1.45)
        widths = {}
        try:
            fh2 = open(WFILE)
            widths = json.loads(fh2.read())
            fh2.close()
        except:
            widths = {}
        import System
        s_date = System.DateTime.Now.ToString('yyyy.MM.dd')

        vals = {}
        vals['val-title'] = (str(title) if title else 'UNTITLED', 'left')
        vals['val-title-ghost'] = (str(title) if title else 'UNTITLED', 'left')
        vals['val-subtitle'] = (str(subtitle) if subtitle else '', 'left')
        vals['c-val-0'] = (s_date, 'right')
        vals['c-val-1'] = (str(sheet) if sheet else 'PLOT 001', 'right')
        vals['c-val-2'] = (s_scale, 'right')
        vals['c-val-3'] = (s_paper, 'right')
        vals['d-val-dur'] = (s_dur, 'right')
        vals['ft-val-plotter'] = ('VORON 2.4', 'left')
        # columns too narrow to take an arbitrary string - text is shrunk to fit
        maxw = {'d-ink-0': 10.6, 'd-ink-1': 10.6, 'd-ink-2': 10.6, 'd-ink-3': 10.6,
                'd-no-0': 3.2, 'd-no-1': 3.2, 'd-no-2': 3.2, 'd-no-3': 3.2,
                'd-mm-0': 7.0, 'd-mm-1': 7.0, 'd-mm-2': 7.0, 'd-mm-3': 7.0,
                'd-val-dur': 32.0, 'ft-val-plotter': 32.0,
                'c-val-0': 31.0, 'c-val-1': 31.0, 'c-val-2': 31.0, 'c-val-3': 31.0,
                'val-title': 60.0, 'val-title-ghost': 60.0, 'val-subtitle': 50.0}
        for r in range(4):
            if r < len(pen_rows):
                pn, nm = pen_rows[r]
                vals['d-no-%d' % r] = ('%02d' % int(pn), 'left')
                vals['d-ink-%d' % r] = (nm[:11], 'left')
                vals['d-mm-%d' % r] = ('%.2f' % float(widths.get(str(int(pn)), 0.45)), 'left')
            else:
                vals['d-no-%d' % r] = ('', 'left')
                vals['d-ink-%d' % r] = ('', 'left')
                vals['d-mm-%d' % r] = ('', 'left')

        raw = []
        allboxes = {}
        for gid in ['pen-1', 'pen-2', 'pen-3']:
            polys, boxes = parse_ink(txt, gid, vals)
            raw.append(polys)
            for k in boxes:
                allboxes[k] = (boxes[k], len(raw) - 1)
        # draw the replacements into the ink layer the placeholder came from
        for vid in vals:
            if vid not in allboxes:
                continue
            (bx0, by0, bx1, by1), ink_i = allboxes[vid]
            s, al = vals[vid]
            if not s:
                continue
            cap = by1 - by0
            if cap < 0.5:
                cap = 1.5
            mw = maxw.get(vid)
            if mw:
                got = strokefont.measure(s, cap, 0.14)
                if got > mw and got > 0.01:
                    cap = cap * (mw / got)      # shrink to fit its column
            ax = bx1 if al == 'right' else bx0
            for pl in strokefont.text(s, ax, by0, cap, 0.14, al):
                raw[ink_i].append([(px, by1 + by0 - py) for px, py in pl])  # back to SVG Y-down
        # ---- where does it go? ----
        fr = {}
        try:
            fr = json.loads(frame) if frame else {}
        except:
            fr = {}
        sc_f = 1.0
        if fr.get('p0') and fr.get('wu'):
            p0 = fr['p0']; eu = fr['eu']; ev = fr['ev']
            wu = float(fr['wu']); hv = float(fr['hv'])
            avail = wu - 2.0 * MARGIN
            if avail < 1.0:
                avail = wu
            sc_f = avail / SVGW
            if HFORCE > 0.01:
                sc_f = HFORCE / SVGH
            ou = MARGIN + (avail - SVGW * sc_f) / 2.0
            ov = MARGIN
            mode = 'on paper %.0fx%.0f' % (wu, hv)
        else:
            # no registration - sit it on the bed, bottom centre
            BED = 350.0
            avail = BED - 2.0 * MARGIN
            sc_f = avail / SVGW
            if HFORCE > 0.01:
                sc_f = HFORCE / SVGH
            p0 = [MARGIN, MARGIN]
            eu = [1.0, 0.0]
            ev = [0.0, 1.0]
            ou = (avail - SVGW * sc_f) / 2.0
            ov = 0.0
            mode = 'no registration - bed bottom'
        # ---- elastic width ----
        # The design pins every column except the title zone, which "absorbs
        # 100% of any width change". So scale UNIFORMLY (text never distorts),
        # then push everything right of the title zone outward to fill the
        # sheet - the title box stretches, its contents stay put.
        SPLIT = 78.0                      # title zone B ends here in SVG mm
        extra = 0.0
        if FILL and avail > 0.0:
            extra = avail - SVGW * sc_f
            if extra < 0.0:
                extra = 0.0
            ou = MARGIN                   # elastic: start at the margin
        outs = [ink1, ink2, ink3]
        n = 0
        for k in range(3):
            for poly in raw[k]:
                lp = List[rg.Point3d]()
                for q in poly:
                    u = ou + q[0] * sc_f
                    if q[0] >= SPLIT:
                        u += extra        # pinned-right columns slide outward
                    v = ov + (SVGH - q[1]) * sc_f       # SVG Y runs downward
                    lp.Add(rg.Point3d(p0[0] + eu[0] * u + ev[0] * v,
                                      p0[1] + eu[1] * u + ev[1] * v, 0))
                if lp.Count > 1:
                    outs[k].append(rg.PolylineCurve(lp))
                    n += 1
        info = '%d strokes (A %d / B %d), %.0f x %.0f mm%s, %s' % (
            n, len(ink1), len(ink2) + len(ink3), SVGW * sc_f + extra, SVGH * sc_f,
            (' (title zone stretched +%.0f)' % extra) if extra > 0.5 else '', mode)

# The block places ITSELF in paper coordinates, so it must not run through
# PLACE (it would be placed twice) and must not run through LAYERS (that feeds
# PLACE, which feeds this component's `frame` - a cycle). It merges straight
# into GCODE instead, carrying its own pen numbers.
PA = int(pen_a) if pen_a is not None else 1
PB = int(pen_b) if pen_b is not None else 1
crvs = []
pens = []
for c in ink1:
    crvs.append(c)
    pens.append(PA)
for c in (ink2 + ink3):
    crvs.append(c)
    pens.append(PB)

print(info)
