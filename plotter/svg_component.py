# -*- coding: utf-8 -*-
# SVG IMPORT - vector artwork from anywhere into the plot pipeline.
#
# Reads a real-world .svg (Illustrator, Inkscape, Figma, plotter libraries) and
# emits plotter curves with a pen number each. Everything is flattened to
# polylines because that is what the pen draws anyway; `tol` sets how finely
# curves and arcs are sampled.
#
# Covers the parts of SVG that describe a line: every path command including
# relative forms, arcs and the smooth/shorthand curves, plus rect/circle/
# ellipse/line/polyline/polygon, and transforms composed down the whole element
# tree. Fills are ignored - a pen plotter draws outlines.
#
# PEN ASSIGNMENT (`pen_mode`):
#   0 EVERYTHING -> `pen`
#   1 BY LAYER   -> each top-level <g> becomes the next pen (Illustrator and
#                   Inkscape both write layers as top-level groups)
#   2 BY COLOUR  -> each distinct stroke colour becomes the next pen, in the
#                   order first seen
# Modes 1 and 2 wrap after 8, and report the mapping so you know what loads when.
#
# GENERATOR CONTRACT: file in -> `out_crvs` + `out_pens` out, `on` bypass.
# Inputs: file(path), size(mm on the longest side, 0 = the file's own size),
#         pen_mode(0/1/2), pen(1-8, used by mode 0), tol(mm flattening
#         tolerance), origin(bool: place min corner at 0,0), on(bool bypass)
import Rhino
import Rhino.Geometry as rg
import scriptcontext as sc
import math
import re
import xml.etree.ElementTree as ET
from System.Collections.Generic import List
try:
    sc.doc = ghdoc
except:
    pass

NUM = re.compile(r'[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?')
CMD = re.compile(r'([MmZzLlHhVvCcSsQqTtAa])')
XF = re.compile(r'(matrix|translate|scale|rotate|skewX|skewY)\s*\(([^)]*)\)')
UNIT = {'mm': 1.0, 'cm': 10.0, 'in': 25.4, 'pt': 25.4 / 72.0, 'pc': 25.4 / 6.0,
        'px': 25.4 / 96.0, '': 25.4 / 96.0}


def nums(s):
    out = []
    for m in NUM.finditer(s):
        t = m.group(0)
        if t in ('.', '-', '+', '-.', '+.'):
            continue
        out.append(float(t))
    return out


def to_mm(v):
    """a length attribute like '210mm' or '793.7' -> mm"""
    if v is None:
        return None
    v = str(v).strip()
    for u in ('mm', 'cm', 'in', 'pt', 'pc', 'px'):
        if v.endswith(u):
            n = nums(v)
            return (n[0] * UNIT[u]) if n else None
    n = nums(v)
    return n[0] * UNIT[''] if n else None


def mat_mul(m, n):
    """compose m then n as (a,b,c,d,e,f); apply(m*n, p) == apply(m, apply(n, p))"""
    a1, b1, c1, d1, e1, f1 = m
    a2, b2, c2, d2, e2, f2 = n
    return (a1 * a2 + c1 * b2,
            b1 * a2 + d1 * b2,
            a1 * c2 + c1 * d2,
            b1 * c2 + d1 * d2,
            a1 * e2 + c1 * f2 + e1,
            b1 * e2 + d1 * f2 + f1)


def parse_xf(s):
    m = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    if not s:
        return m
    for kind, body in XF.findall(s):
        v = nums(body)
        if kind == 'matrix' and len(v) >= 6:
            t = (v[0], v[1], v[2], v[3], v[4], v[5])
        elif kind == 'translate':
            t = (1.0, 0.0, 0.0, 1.0, v[0] if v else 0.0, v[1] if len(v) > 1 else 0.0)
        elif kind == 'scale':
            sx = v[0] if v else 1.0
            sy = v[1] if len(v) > 1 else sx
            t = (sx, 0.0, 0.0, sy, 0.0, 0.0)
        elif kind == 'rotate':
            a = math.radians(v[0]) if v else 0.0
            ca = math.cos(a); sa = math.sin(a)
            t = (ca, sa, -sa, ca, 0.0, 0.0)
            if len(v) >= 3:
                cx = v[1]; cy = v[2]
                t = mat_mul((1.0, 0.0, 0.0, 1.0, cx, cy),
                            mat_mul(t, (1.0, 0.0, 0.0, 1.0, -cx, -cy)))
        elif kind == 'skewX':
            t = (1.0, 0.0, math.tan(math.radians(v[0] if v else 0.0)), 1.0, 0.0, 0.0)
        elif kind == 'skewY':
            t = (1.0, math.tan(math.radians(v[0] if v else 0.0)), 0.0, 1.0, 0.0, 0.0)
        else:
            continue
        m = mat_mul(m, t)
    return m


def bez3(p0, p1, p2, p3, tol):
    """cubic -> points. Segment count from the control polygon, which bounds
    the true arc length, so the sampling never under-resolves a tight curve."""
    L = (math.sqrt((p1[0]-p0[0])**2 + (p1[1]-p0[1])**2)
         + math.sqrt((p2[0]-p1[0])**2 + (p2[1]-p1[1])**2)
         + math.sqrt((p3[0]-p2[0])**2 + (p3[1]-p2[1])**2))
    n = int(L / tol) + 2
    if n > 400:
        n = 400
    out = []
    for i in range(1, n + 1):
        t = float(i) / n
        u = 1.0 - t
        out.append((u*u*u*p0[0] + 3*u*u*t*p1[0] + 3*u*t*t*p2[0] + t*t*t*p3[0],
                    u*u*u*p0[1] + 3*u*u*t*p1[1] + 3*u*t*t*p2[1] + t*t*t*p3[1]))
    return out


def bez2(p0, p1, p2, tol):
    L = (math.sqrt((p1[0]-p0[0])**2 + (p1[1]-p0[1])**2)
         + math.sqrt((p2[0]-p1[0])**2 + (p2[1]-p1[1])**2))
    n = int(L / tol) + 2
    if n > 400:
        n = 400
    out = []
    for i in range(1, n + 1):
        t = float(i) / n
        u = 1.0 - t
        out.append((u*u*p0[0] + 2*u*t*p1[0] + t*t*p2[0],
                    u*u*p0[1] + 2*u*t*p1[1] + t*t*p2[1]))
    return out


def arc_to(p0, rx, ry, rot, large, sweep, p1, tol):
    """SVG endpoint-parameterised arc -> points (F.6.5 of the spec)"""
    if rx == 0.0 or ry == 0.0:
        return [p1]
    rx = abs(rx); ry = abs(ry)
    phi = math.radians(rot)
    cs = math.cos(phi); sn = math.sin(phi)
    dx2 = (p0[0] - p1[0]) / 2.0
    dy2 = (p0[1] - p1[1]) / 2.0
    x1 = cs * dx2 + sn * dy2
    y1 = -sn * dx2 + cs * dy2
    # scale the radii up if they cannot span the chord
    lam = (x1*x1) / (rx*rx) + (y1*y1) / (ry*ry)
    if lam > 1.0:
        s = math.sqrt(lam)
        rx *= s; ry *= s
    num = rx*rx*ry*ry - rx*rx*y1*y1 - ry*ry*x1*x1
    den = rx*rx*y1*y1 + ry*ry*x1*x1
    if den == 0.0:
        return [p1]
    if num < 0.0:
        num = 0.0
    co = math.sqrt(num / den)
    if large == sweep:
        co = -co
    cx1 = co * rx * y1 / ry
    cy1 = -co * ry * x1 / rx
    cx = cs * cx1 - sn * cy1 + (p0[0] + p1[0]) / 2.0
    cy = sn * cx1 + cs * cy1 + (p0[1] + p1[1]) / 2.0
    def ang(ux, uy, vx, vy):
        d = math.sqrt((ux*ux + uy*uy) * (vx*vx + vy*vy))
        if d == 0.0:
            return 0.0
        c = (ux*vx + uy*vy) / d
        if c < -1.0: c = -1.0
        if c > 1.0: c = 1.0
        a = math.acos(c)
        if ux*vy - uy*vx < 0.0:
            a = -a
        return a
    th0 = ang(1.0, 0.0, (x1 - cx1) / rx, (y1 - cy1) / ry)
    dth = ang((x1 - cx1) / rx, (y1 - cy1) / ry, (-x1 - cx1) / rx, (-y1 - cy1) / ry)
    if not sweep and dth > 0.0:
        dth -= 2.0 * math.pi
    elif sweep and dth < 0.0:
        dth += 2.0 * math.pi
    rmax = rx if rx > ry else ry
    n = int(abs(dth) * rmax / tol) + 2
    if n > 400:
        n = 400
    out = []
    for i in range(1, n + 1):
        th = th0 + dth * float(i) / n
        ex = rx * math.cos(th); ey = ry * math.sin(th)
        out.append((cs * ex - sn * ey + cx, sn * ex + cs * ey + cy))
    return out


def path_polys(d, tol):
    """path `d` -> list of point lists, in the element's own coordinates"""
    toks = CMD.split(d)
    polys = []
    cur = []
    cx = 0.0; cy = 0.0        # current point
    sx = 0.0; sy = 0.0        # sub-path start
    px = 0.0; py = 0.0        # last cubic control, for S
    qx = 0.0; qy = 0.0        # last quadratic control, for T
    prev = ''
    i = 1
    while i < len(toks):
        c = toks[i]
        args = nums(toks[i + 1]) if i + 1 < len(toks) else []
        i += 2
        rel = c.islower()
        C = c.upper()
        if C == 'M':
            j = 0
            while j + 1 < len(args) + 1 and j + 1 <= len(args) - 1 + 1:
                if j + 1 > len(args) - 1:
                    break
                x = args[j]; y = args[j + 1]
                if rel:
                    x += cx; y += cy
                if j == 0:
                    if len(cur) > 1:
                        polys.append(cur)
                    cur = [(x, y)]
                    sx = x; sy = y
                else:
                    cur.append((x, y))     # extra pairs after M are implicit L
                cx = x; cy = y
                j += 2
        elif C == 'Z':
            if len(cur) > 1:
                cur.append((sx, sy))
                polys.append(cur)
            cur = [(sx, sy)]
            cx = sx; cy = sy
        elif C == 'L':
            j = 0
            while j + 1 < len(args) + 1 and j + 1 <= len(args) - 1 + 1:
                if j + 1 > len(args) - 1:
                    break
                x = args[j]; y = args[j + 1]
                if rel:
                    x += cx; y += cy
                cur.append((x, y)); cx = x; cy = y
                j += 2
        elif C == 'H':
            for v in args:
                x = cx + v if rel else v
                cur.append((x, cy)); cx = x
        elif C == 'V':
            for v in args:
                y = cy + v if rel else v
                cur.append((cx, y)); cy = y
        elif C == 'C':
            j = 0
            while j + 5 < len(args):
                x1 = args[j]; y1 = args[j+1]; x2 = args[j+2]
                y2 = args[j+3]; x = args[j+4]; y = args[j+5]
                if rel:
                    x1 += cx; y1 += cy; x2 += cx; y2 += cy; x += cx; y += cy
                for q in bez3((cx, cy), (x1, y1), (x2, y2), (x, y), tol):
                    cur.append(q)
                px = x2; py = y2; cx = x; cy = y
                j += 6
        elif C == 'S':
            j = 0
            while j + 3 < len(args):
                x2 = args[j]; y2 = args[j+1]; x = args[j+2]; y = args[j+3]
                if rel:
                    x2 += cx; y2 += cy; x += cx; y += cy
                if prev in ('C', 'S'):
                    x1 = 2.0 * cx - px; y1 = 2.0 * cy - py
                else:
                    x1 = cx; y1 = cy
                for q in bez3((cx, cy), (x1, y1), (x2, y2), (x, y), tol):
                    cur.append(q)
                px = x2; py = y2; cx = x; cy = y
                j += 4
        elif C == 'Q':
            j = 0
            while j + 3 < len(args):
                x1 = args[j]; y1 = args[j+1]; x = args[j+2]; y = args[j+3]
                if rel:
                    x1 += cx; y1 += cy; x += cx; y += cy
                for q in bez2((cx, cy), (x1, y1), (x, y), tol):
                    cur.append(q)
                qx = x1; qy = y1; cx = x; cy = y
                j += 4
        elif C == 'T':
            j = 0
            while j + 1 < len(args):
                x = args[j]; y = args[j+1]
                if rel:
                    x += cx; y += cy
                if prev in ('Q', 'T'):
                    x1 = 2.0 * cx - qx; y1 = 2.0 * cy - qy
                else:
                    x1 = cx; y1 = cy
                for q in bez2((cx, cy), (x1, y1), (x, y), tol):
                    cur.append(q)
                qx = x1; qy = y1; cx = x; cy = y
                j += 2
        elif C == 'A':
            j = 0
            while j + 6 < len(args):
                rx = args[j]; ry = args[j+1]; rot = args[j+2]
                la = args[j+3] != 0.0; sw = args[j+4] != 0.0
                x = args[j+5]; y = args[j+6]
                if rel:
                    x += cx; y += cy
                for q in arc_to((cx, cy), rx, ry, rot, la, sw, (x, y), tol):
                    cur.append(q)
                cx = x; cy = y
                j += 7
        prev = C
    if len(cur) > 1:
        polys.append(cur)
    return polys


def shape_polys(tag, at, tol):
    """rect / circle / ellipse / line / polyline / polygon -> point lists"""
    def f(k, dv=0.0):
        v = at.get(k)
        if v is None:
            return dv
        n = nums(v)
        return n[0] if n else dv
    if tag == 'rect':
        x = f('x'); y = f('y'); w = f('width'); h = f('height')
        rx = f('rx', -1.0); ry = f('ry', -1.0)
        if rx < 0 and ry < 0:
            rx = 0.0; ry = 0.0
        elif rx < 0:
            rx = ry
        elif ry < 0:
            ry = rx
        if rx > w / 2.0: rx = w / 2.0
        if ry > h / 2.0: ry = h / 2.0
        if w <= 0 or h <= 0:
            return []
        if rx <= 0 or ry <= 0:
            return [[(x, y), (x+w, y), (x+w, y+h), (x, y+h), (x, y)]]
        d = ('M%f,%f H%f A%f,%f 0 0 1 %f,%f V%f A%f,%f 0 0 1 %f,%f '
             'H%f A%f,%f 0 0 1 %f,%f V%f A%f,%f 0 0 1 %f,%f Z') % (
            x+rx, y, x+w-rx, rx, ry, x+w, y+ry, y+h-ry, rx, ry, x+w-rx, y+h,
            x+rx, rx, ry, x, y+h-ry, y+ry, rx, ry, x+rx, y)
        return path_polys(d, tol)
    if tag == 'circle':
        cx = f('cx'); cy = f('cy'); r = f('r')
        if r <= 0:
            return []
        n = int(2.0 * math.pi * r / tol) + 8
        if n > 720: n = 720
        return [[(cx + r*math.cos(2.0*math.pi*i/n), cy + r*math.sin(2.0*math.pi*i/n))
                 for i in range(n + 1)]]
    if tag == 'ellipse':
        cx = f('cx'); cy = f('cy'); rx = f('rx'); ry = f('ry')
        if rx <= 0 or ry <= 0:
            return []
        rmax = rx if rx > ry else ry
        n = int(2.0 * math.pi * rmax / tol) + 8
        if n > 720: n = 720
        return [[(cx + rx*math.cos(2.0*math.pi*i/n), cy + ry*math.sin(2.0*math.pi*i/n))
                 for i in range(n + 1)]]
    if tag == 'line':
        return [[(f('x1'), f('y1')), (f('x2'), f('y2'))]]
    if tag in ('polyline', 'polygon'):
        v = nums(at.get('points', ''))
        pts = []
        for i in range(0, len(v) - 1, 2):
            pts.append((v[i], v[i+1]))
        if len(pts) < 2:
            return []
        if tag == 'polygon':
            pts.append(pts[0])
        return [pts]
    return []


def prop(at, name):
    v = at.get(name)
    st = at.get('style', '')
    if st:
        m = re.search(r'(?:^|;)\s*' + name + r'\s*:\s*([^;]+)', st)
        if m:
            v = m.group(1).strip()
    if v is None:
        return None
    v = v.strip().lower()
    if v in ('none', 'transparent'):
        return None
    return v


def colour_of(at):
    """stroke first, then fill. Plenty of real artwork (most Illustrator
    exports) carries its colour as a fill on a closed shape and never sets a
    stroke at all - and the pen outlines it either way, so fill is the right
    fallback rather than 'no colour'."""
    c = prop(at, 'stroke')
    if c:
        return c
    return prop(at, 'fill')


def hidden(at):
    if at.get('display') == 'none':
        return True
    st = at.get('style', '')
    if 'display:none' in st.replace(' ', ''):
        return True
    if 'visibility:hidden' in st.replace(' ', ''):
        return True
    return False


PATH_TAGS = ('path', 'rect', 'circle', 'ellipse', 'line', 'polyline', 'polygon')
# containers whose contents are templates or metadata, never drawn where they sit
SKIP_TAGS = ('defs', 'clipPath', 'mask', 'marker', 'symbol', 'pattern',
             'title', 'desc', 'metadata', 'style', 'script', 'filter')

SVGFILE = None
if file is not None:
    try:
        SVGFILE = str(file).strip('"')
    except:
        SVGFILE = None
SIZE = float(size) if size is not None else 0.0
if SIZE < 0.0:
    SIZE = 0.0
PMODE = int(pen_mode) if pen_mode is not None else 0
PEN = int(pen) if pen is not None else 1
if PEN < 1: PEN = 1
if PEN > 8: PEN = 8
TOL = float(tol) if tol is not None else 0.2
if TOL < 0.01:
    TOL = 0.01
ORIGIN = True if origin is None else bool(origin)
ON = True if on is None else bool(on)

out_crvs = []
out_pens = []
info = ''
if not ON:
    info = '[BYPASSED]'
elif not SVGFILE:
    info = 'no file - point `file` at an .svg'
else:
    try:
        tree = ET.parse(SVGFILE)
        root = tree.getroot()
    except Exception, e:
        root = None
        info = 'could not read the SVG: %s' % str(e)
    if root is not None:
        # ---- document scale: user units -> mm ----
        vb = nums(root.get('viewBox', '') or '')
        w_mm = to_mm(root.get('width'))
        h_mm = to_mm(root.get('height'))
        if len(vb) >= 4 and vb[2] > 0 and vb[3] > 0:
            vbw = vb[2]; vbh = vb[3]; vbx = vb[0]; vby = vb[1]
        else:
            vbw = w_mm / UNIT[''] if w_mm else 100.0
            vbh = h_mm / UNIT[''] if h_mm else 100.0
            vbx = 0.0; vby = 0.0
        if w_mm and vbw > 0:
            u2mm = w_mm / vbw
        elif h_mm and vbh > 0:
            u2mm = h_mm / vbh
        else:
            u2mm = UNIT['']           # bare numbers are px
        # ---- walk the tree, composing transforms ----
        layers = []
        colours = []
        raw = []                      # (points, layer_index, colour)
        stack = [(root, (1.0, 0.0, 0.0, 1.0, 0.0, 0.0), -1, None)]
        # children of the root in document order are the "layers"
        top = []
        for ch in list(root):
            top.append(ch)
        n_hidden = 0
        for li in range(len(top)):
            el = top[li]
            work = [(el, parse_xf(root.get('transform')), li, colour_of(root.attrib))]
            while work:
                node, m, lay, inh = work.pop()
                at = node.attrib
                if hidden(at):
                    n_hidden += 1
                    continue
                tag = node.tag
                if '}' in tag:
                    tag = tag.split('}')[1]
                if tag in SKIP_TAGS:
                    continue
                m2 = mat_mul(m, parse_xf(at.get('transform')))
                # presentation attributes inherit, so a <g fill="#f00"> colours
                # every path beneath it that does not set its own
                col = colour_of(at) or inh
                if tag in PATH_TAGS:
                    if tag == 'path':
                        pls = path_polys(at.get('d', ''), TOL / max(u2mm, 1e-9))
                    else:
                        pls = shape_polys(tag, at, TOL / max(u2mm, 1e-9))
                    for pl in pls:
                        pts = []
                        for (x, y) in pl:
                            pts.append((m2[0]*x + m2[2]*y + m2[4],
                                        m2[1]*x + m2[3]*y + m2[5]))
                        raw.append((pts, lay, col))
                else:
                    kids = list(node)
                    for q in range(len(kids) - 1, -1, -1):
                        work.append((kids[q], m2, lay, col))
            nm = el.get('{http://www.inkscape.org/namespaces/inkscape}label') or el.get('id') or ('group %d' % (li + 1))
            layers.append(nm)
        # Only layers that actually drew something get a pen. A <defs> block or an
        # empty group would otherwise consume an index and shift every real layer.
        drew = []
        for pts, lay, col in raw:
            if lay not in drew:
                drew.append(lay)
        drew.sort()
        lay_pen = {}
        for i in range(len(drew)):
            lay_pen[drew[i]] = (i % 8) + 1
        layers = [layers[i] for i in drew if i < len(layers)]
        # ---- fit / place ----
        if raw:
            xs = []; ys = []
            for pts, lay, col in raw:
                for (x, y) in pts:
                    xs.append(x); ys.append(y)
            x0 = min(xs); x1 = max(xs); y0 = min(ys); y1 = max(ys)
            w_u = x1 - x0; h_u = y1 - y0
            s = u2mm
            if SIZE > 0.0:
                big = w_u if w_u > h_u else h_u
                if big > 0:
                    s = SIZE / big
            ox = -x0 * s if ORIGIN else (vbx * -s)
            oy = y1 * s if ORIGIN else (vby + vbh) * s
            seen = []
            for pts, lay, col in raw:
                lp = List[rg.Point3d]()
                for (x, y) in pts:
                    # SVG y runs down the page; the bed's runs up
                    lp.Add(rg.Point3d(x * s + ox, oy - y * s, 0))
                if lp.Count < 2:
                    continue
                if PMODE == 1:
                    pn = lay_pen.get(lay, PEN)
                elif PMODE == 2:
                    key = col if col else '(no stroke)'
                    if key not in seen:
                        seen.append(key)
                    pn = (seen.index(key) % 8) + 1
                else:
                    pn = PEN
                out_crvs.append(rg.PolylineCurve(lp))
                out_pens.append(pn)
            tot = 0.0
            for c in out_crvs:
                tot += c.GetLength()
            bits = ['%d curves, %.2fm of line' % (len(out_crvs), tot / 1000.0)]
            bits.append('%.1f x %.1f mm' % (w_u * s, h_u * s))
            bits.append('tol %.2fmm' % TOL)
            if PMODE == 1:
                bits.append('by layer: ' + ', '.join(
                    ['pen%d=%s' % ((i % 8) + 1, layers[i][:14]) for i in range(len(layers))]))
            elif PMODE == 2:
                bits.append('by colour: ' + ', '.join(
                    ['pen%d=%s' % ((i % 8) + 1, seen[i]) for i in range(len(seen))]))
            else:
                bits.append('all on pen %d' % PEN)
            if n_hidden:
                bits.append('%d hidden element(s) skipped' % n_hidden)
            info = ' | '.join(bits)
        else:
            info = 'parsed, but found no drawable geometry'

print(info)
