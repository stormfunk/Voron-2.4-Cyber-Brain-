# -*- coding: utf-8 -*-
# PAPERCAM - optical paper registration from the bed camera.
#
# Replaces jogging the pen to three corners by hand: grab a frame, find the
# sheet, and hand the same three corners to the existing registration.
#
# The camera is fixed and the bed is flat, so image -> bed is exactly a
# HOMOGRAPHY (a plane-to-plane projective map, 8 degrees of freedom). That is
# what makes a single calibration hold: it absorbs the camera's tilt, its
# offset, and the lens's scale in one 3x3 matrix, and stays valid as long as
# nothing moves the camera. Autofocus is off in crowsnest (focus_absolute=2),
# which is what keeps that assumption true between sessions.
#
# CALIBRATE once: give four points you can see in the frame whose bed
# coordinates you know, as `calib_img` (pixels) and `calib_bed` (mm), then press
# `calibrate`. The matrix is written to camera_calibration.json and reused.
#
# DETECT: `capture` grabs a frame, thresholds it (paper is far brighter than the
# bed), takes the convex hull of the bright region, simplifies it to a quad and
# maps those corners through the homography into bed mm. `apply` writes them to
# paper_registration.json in the same shape the manual TEACH buttons produce, so
# everything downstream is unchanged.
#
# Outputs `corners` as front-left, front-right, back-left - the P0/P1/P2 the
# rest of the pipeline already expects.
# Inputs: url(snapshot), thresh(0-255, -1 = auto), min_area(fraction of frame),
#         calib_img(list of 4 image points), calib_bed(list of 4 bed points),
#         calibrate(button), capture(button), apply(button), debug(bool), on(bool)
import Rhino
import Rhino.Geometry as rg
import scriptcontext as sc
import math
import json
import System
import System.Drawing as SD
from System.Collections.Generic import List
try:
    sc.doc = ghdoc
except:
    pass

CALFILE = r'C:\Users\john.chandler\voron_plotter\camera_calibration.json'
REGFILE = r'C:\Users\john.chandler\voron_plotter\paper_registration.json'
DBGIMG = r'C:\Users\john.chandler\voron_plotter\screenshots\papercam_debug.png'


def solve8(M, rhs):
    """Gaussian elimination with partial pivoting on an 8x8 system"""
    n = len(rhs)
    a = []
    for i in range(n):
        row = list(M[i])
        row.append(rhs[i])
        a.append(row)
    for col in range(n):
        piv = col
        best = abs(a[col][col])
        for r in range(col + 1, n):
            if abs(a[r][col]) > best:
                best = abs(a[r][col]); piv = r
        if best < 1e-12:
            return None
        if piv != col:
            a[col], a[piv] = a[piv], a[col]
        d = a[col][col]
        for k in range(col, n + 1):
            a[col][k] /= d
        for r in range(n):
            if r == col:
                continue
            f = a[r][col]
            if f == 0.0:
                continue
            for k in range(col, n + 1):
                a[r][k] -= f * a[col][k]
    return [a[i][n] for i in range(n)]


def homography(src, dst):
    """4 correspondences -> 3x3 H with h33 = 1, mapping src -> dst.

    Each pair contributes two rows of the standard DLT system:
      x' = (h0 x + h1 y + h2) / (h6 x + h7 y + 1)
      y' = (h3 x + h4 y + h5) / (h6 x + h7 y + 1)
    cross-multiplied so the unknowns stay linear."""
    if len(src) < 4 or len(dst) < 4:
        return None
    M = []; rhs = []
    for i in range(4):
        x, y = src[i]
        u, v = dst[i]
        M.append([x, y, 1.0, 0.0, 0.0, 0.0, -u * x, -u * y]); rhs.append(u)
        M.append([0.0, 0.0, 0.0, x, y, 1.0, -v * x, -v * y]); rhs.append(v)
    h = solve8(M, rhs)
    if h is None:
        return None
    return [h[0], h[1], h[2], h[3], h[4], h[5], h[6], h[7], 1.0]


def apply_h(H, x, y):
    d = H[6] * x + H[7] * y + H[8]
    if abs(d) < 1e-12:
        return None
    return ((H[0] * x + H[1] * y + H[2]) / d,
            (H[3] * x + H[4] * y + H[5]) / d)


def grab(url):
    """one frame from the MJPG snapshot endpoint"""
    try:
        from System.Net import WebClient
        from System.IO import MemoryStream
        wc = WebClient()
        data = wc.DownloadData(url)
        ms = MemoryStream(data)
        bm = SD.Bitmap(ms)
        return bm
    except Exception, e:
        return None


def gray_of(bm, maxw):
    """downscaled 8-bit luminance as a flat list, plus its size"""
    from System.Drawing.Imaging import PixelFormat, ImageLockMode
    from System.Runtime.InteropServices import Marshal
    w = bm.Width; h = bm.Height
    f = 1.0
    if w > maxw:
        f = float(maxw) / float(w)
    tw = int(w * f); th = int(h * f)
    conv = SD.Bitmap(tw, th, PixelFormat.Format24bppRgb)
    g = SD.Graphics.FromImage(conv)
    g.InterpolationMode = SD.Drawing2D.InterpolationMode.HighQualityBilinear
    g.DrawImage(bm, 0, 0, tw, th)
    g.Dispose()
    d = conv.LockBits(SD.Rectangle(0, 0, tw, th), ImageLockMode.ReadOnly, PixelFormat.Format24bppRgb)
    stride = d.Stride
    nb = abs(stride) * th
    buf = System.Array.CreateInstance(System.Byte, nb)
    Marshal.Copy(d.Scan0, buf, 0, nb)
    conv.UnlockBits(d); conv.Dispose()
    out = []
    for yy in range(th):
        ro = yy * stride
        for xx in range(tw):
            i = ro + xx * 3
            out.append(int(0.114 * buf[i] + 0.587 * buf[i + 1] + 0.299 * buf[i + 2]))
    return out, tw, th, (float(w) / tw)


def otsu(gr):
    """threshold that best splits the histogram - paper vs bed, no tuning"""
    hist = [0] * 256
    for v in gr:
        hist[v] += 1
    tot = len(gr)
    sm = 0.0
    for i in range(256):
        sm += i * hist[i]
    sB = 0.0; wB = 0; best = -1.0; bt = 128
    for t in range(256):
        wB += hist[t]
        if wB == 0:
            continue
        wF = tot - wB
        if wF == 0:
            break
        sB += t * hist[t]
        mB = sB / wB
        mF = (sm - sB) / wF
        var = wB * wF * (mB - mF) * (mB - mF)
        if var > best:
            best = var; bt = t
    return bt


def hull_of(pts):
    """Andrew monotone chain convex hull"""
    p = sorted(set(pts))
    if len(p) < 3:
        return p
    lo = []
    for q in p:
        while len(lo) >= 2 and ((lo[-1][0]-lo[-2][0])*(q[1]-lo[-2][1]) - (lo[-1][1]-lo[-2][1])*(q[0]-lo[-2][0])) <= 0:
            lo.pop()
        lo.append(q)
    up = []
    for q in reversed(p):
        while len(up) >= 2 and ((up[-1][0]-up[-2][0])*(q[1]-up[-2][1]) - (up[-1][1]-up[-2][1])*(q[0]-up[-2][0])) <= 0:
            up.pop()
        up.append(q)
    return lo[:-1] + up[:-1]


def quad_from_hull(hull):
    """the 4 hull vertices enclosing the most area.

    A sheet photographed at an angle is a general quadrilateral, not a
    rectangle, so fitting a min-area RECTANGLE would systematically clip the
    corners. Picking the best 4 hull points keeps the true projected shape."""
    n = len(hull)
    if n < 4:
        return None
    if n > 40:
        step = n / 40 + 1
        hull = [hull[i] for i in range(0, n, step)]
        n = len(hull)
    best = None; bq = None
    for i in range(n):
        for j in range(i + 1, n):
            for k in range(j + 1, n):
                for l in range(k + 1, n):
                    q = [hull[i], hull[j], hull[k], hull[l]]
                    a = 0.0
                    for m in range(4):
                        x1, y1 = q[m]
                        x2, y2 = q[(m + 1) % 4]
                        a += x1 * y2 - x2 * y1
                    a = abs(a) * 0.5
                    if best is None or a > best:
                        best = a; bq = q
    return bq, best


def lock_rgb(bm):
    """full-resolution pixels, kept as a raw buffer - building a 900k-entry
    Python list just to sample a few hundred points would cost more than the
    whole detection"""
    from System.Drawing.Imaging import PixelFormat, ImageLockMode
    from System.Runtime.InteropServices import Marshal
    w = bm.Width; h = bm.Height
    conv = SD.Bitmap(w, h, PixelFormat.Format24bppRgb)
    g = SD.Graphics.FromImage(conv)
    g.DrawImage(bm, 0, 0, w, h)
    g.Dispose()
    d = conv.LockBits(SD.Rectangle(0, 0, w, h), ImageLockMode.ReadOnly, PixelFormat.Format24bppRgb)
    stride = d.Stride
    nb = abs(stride) * h
    buf = System.Array.CreateInstance(System.Byte, nb)
    Marshal.Copy(d.Scan0, buf, 0, nb)
    conv.UnlockBits(d); conv.Dispose()
    return buf, stride, w, h


def lum_at(buf, stride, w, h, x, y):
    """bilinear luminance. Nearest-neighbour quantises every scan to a whole
    pixel, which puts a floor under the corner accuracy no matter how finely
    the scan steps - it cost about 0.6mm on the bed before this."""
    xf = math.floor(x); yf = math.floor(y)
    xi = int(xf); yi = int(yf)
    if xi < 0 or yi < 0 or xi + 1 >= w or yi + 1 >= h:
        return None
    fx = x - xf; fy = y - yf
    i00 = yi * stride + xi * 3
    i10 = i00 + 3
    i01 = i00 + stride
    i11 = i01 + 3
    v00 = 0.114 * buf[i00] + 0.587 * buf[i00 + 1] + 0.299 * buf[i00 + 2]
    v10 = 0.114 * buf[i10] + 0.587 * buf[i10 + 1] + 0.299 * buf[i10 + 2]
    v01 = 0.114 * buf[i01] + 0.587 * buf[i01 + 1] + 0.299 * buf[i01 + 2]
    v11 = 0.114 * buf[i11] + 0.587 * buf[i11 + 1] + 0.299 * buf[i11 + 2]
    return (v00 * (1.0 - fx) * (1.0 - fy) + v10 * fx * (1.0 - fy)
            + v01 * (1.0 - fx) * fy + v11 * fx * fy)


def refine_quad(buf, stride, w, h, quad, t):
    """sub-pixel corners by fitting the four edges.

    The hull vertices of a thresholded mask land wherever the pixel grid
    happened to cross the paper, which at any sane downscale is a millimetre or
    two out. Instead, walk along each edge, scan ACROSS it to find where the
    brightness actually crosses the threshold (interpolating between the two
    straddling samples), least-squares fit a line through those crossings, and
    intersect neighbouring lines. Corner accuracy then comes from ~40 edge
    samples rather than from one pixel."""
    SPAN = 14.0        # how far either side of the nominal edge to look, px
    STEP = 0.25
    N = 44
    lines = []
    for e in range(4):
        ax, ay = quad[e]
        bx, by = quad[(e + 1) % 4]
        dx = bx - ax; dy = by - ay
        L = math.sqrt(dx*dx + dy*dy)
        if L < 1e-6:
            return None
        dx /= L; dy /= L
        nx = -dy; ny = dx
        got = []
        for k in range(N):
            f = 0.12 + 0.76 * (float(k) / (N - 1))   # keep clear of the corners
            px = ax + dx * L * f
            py = ay + dy * L * f
            prev = None; prevs = None
            cross = None
            s = -SPAN
            while s <= SPAN:
                v = lum_at(buf, stride, w, h, px + nx * s, py + ny * s)
                if v is None:
                    prev = None; s += STEP; continue
                if prev is not None and ((prev - t) * (v - t) < 0.0):
                    # linear interpolation to the exact crossing
                    fr = (t - prev) / (v - prev) if (v - prev) != 0 else 0.5
                    sc = prevs + fr * STEP
                    cross = (px + nx * sc, py + ny * sc)
                    break
                prev = v; prevs = s
                s += STEP
            if cross:
                got.append(cross)
        if len(got) < 6:
            return None
        # total-least-squares line through the crossings
        mx = 0.0; my = 0.0
        for q in got:
            mx += q[0]; my += q[1]
        mx /= len(got); my /= len(got)
        sxx = 0.0; syy = 0.0; sxy = 0.0
        for q in got:
            ddx = q[0] - mx; ddy = q[1] - my
            sxx += ddx*ddx; syy += ddy*ddy; sxy += ddx*ddy
        th = 0.5 * math.atan2(2.0 * sxy, sxx - syy)
        lines.append((mx, my, math.cos(th), math.sin(th)))
    out = []
    for e in range(4):
        x1, y1, c1, s1 = lines[(e - 1) % 4]
        x2, y2, c2, s2 = lines[e]
        den = c1 * s2 - s1 * c2
        if abs(den) < 1e-9:
            return None
        tt = ((x2 - x1) * s2 - (y2 - y1) * c2) / den
        out.append((x1 + c1 * tt, y1 + s1 * tt))
    # out[e] is the meeting of edge e-1 and edge e, i.e. quad vertex e
    return out


URL = str(url) if url else 'http://192.168.1.23:8080/?action=snapshot'
THRESH = int(thresh) if thresh is not None else -1
MINA = float(min_area) if min_area is not None else 0.02
DEBUG = True if debug is None else bool(debug)
ON = True if on is None else bool(on)

corners = []
info = ''
H = None
try:
    _fh = open(CALFILE)
    _cal = json.loads(_fh.read())
    _fh.close()
    H = _cal.get('H')
except:
    H = None

if not ON:
    info = '[BYPASSED]'
else:
    did = False
    # ---- calibrate ----
    if calibrate:
        did = True
        ip = []; bp = []
        try:
            for q in (calib_img or []):
                ip.append((float(q.X), float(q.Y)))
            for q in (calib_bed or []):
                bp.append((float(q.X), float(q.Y)))
        except:
            pass
        if len(ip) < 4 or len(bp) < 4:
            info = 'calibration needs 4 image points and 4 bed points (got %d and %d)' % (len(ip), len(bp))
        else:
            Hn = homography(ip[:4], bp[:4])
            if Hn is None:
                info = 'calibration failed - the 4 image points must not be collinear'
            else:
                # residual on the points themselves, as a sanity number
                err = 0.0
                for i in range(4):
                    m = apply_h(Hn, ip[i][0], ip[i][1])
                    err += math.sqrt((m[0]-bp[i][0])**2 + (m[1]-bp[i][1])**2)
                err /= 4.0
                _fh = open(CALFILE, 'w')
                _fh.write(json.dumps({'H': Hn, 'note': 'image px -> bed mm'}))
                _fh.close()
                H = Hn
                info = 'CALIBRATED - mean residual %.3f mm on the 4 reference points' % err

    # ---- capture + detect ----
    if capture and not did:
        did = True
        if H is None:
            info = 'not calibrated yet - set calib_img / calib_bed and press calibrate'
        else:
            bm = grab(URL)
            if bm is None:
                info = 'no frame from %s (printer off, or wrong URL?)' % URL
            else:
                gr, gw, gh_, scl = gray_of(bm, 640)
                t = otsu(gr) if THRESH < 0 else THRESH
                pts = []
                for yy in range(gh_):
                    ro = yy * gw
                    for xx in range(gw):
                        if gr[ro + xx] > t:
                            pts.append((xx, yy))
                frac = float(len(pts)) / float(gw * gh_)
                if frac < MINA:
                    info = 'nothing bright enough found (%.1f%% of frame over threshold %d)' % (frac * 100.0, t)
                elif frac > 0.9:
                    info = 'almost the whole frame is bright (threshold %d) - is the bed lit too evenly?' % t
                else:
                    hl = hull_of(pts)
                    res = quad_from_hull(hl)
                    if res is None:
                        info = 'could not fit a quad to the bright region'
                    else:
                        quad, area = res
                        # image px are in the DOWNSCALED frame; undo that
                        full = [(q[0] * scl, q[1] * scl) for q in quad]
                        # then pull the corners onto the real edges, sub-pixel
                        refined = None
                        try:
                            _b, _s, _w, _h = lock_rgb(bm)
                            refined = refine_quad(_b, _s, _w, _h, full, float(t))
                        except:
                            refined = None
                        if refined:
                            full = refined
                        bed = []
                        for (qx, qy) in full:
                            m = apply_h(H, qx, qy)
                            if m:
                                bed.append(m)
                        if len(bed) < 4:
                            info = 'homography could not map the corners'
                        else:
                            # name them the way the pipeline expects:
                            # P0 front-left, P1 front-right, P2 back-left
                            cy = sum([q[1] for q in bed]) / 4.0
                            cx = sum([q[0] for q in bed]) / 4.0
                            front = [q for q in bed if q[1] <= cy]
                            back = [q for q in bed if q[1] > cy]
                            if len(front) == 2 and len(back) == 2:
                                front.sort()
                                back.sort()
                                p0 = front[0]; p1 = front[1]; p2 = back[0]
                                corners = [rg.Point3d(p0[0], p0[1], 0),
                                           rg.Point3d(p1[0], p1[1], 0),
                                           rg.Point3d(p2[0], p2[1], 0)]
                                w_mm = math.sqrt((p1[0]-p0[0])**2 + (p1[1]-p0[1])**2)
                                h_mm = math.sqrt((p2[0]-p0[0])**2 + (p2[1]-p0[1])**2)
                                skew = math.degrees(math.atan2(p1[1]-p0[1], p1[0]-p0[0]))
                                info = ('FOUND paper %.1f x %.1f mm, skew %+.2f deg | '
                                        'threshold %d (%s), %.0f%% of frame | '
                                        'P0 %.1f,%.1f  P1 %.1f,%.1f  P2 %.1f,%.1f') % (
                                    w_mm, h_mm, skew, t, 'auto' if THRESH < 0 else 'manual',
                                    frac * 100.0, p0[0], p0[1], p1[0], p1[1], p2[0], p2[1])
                            else:
                                info = 'corners did not split cleanly front/back - check the calibration'
                        if DEBUG:
                            try:
                                g2 = SD.Graphics.FromImage(bm)
                                pen = SD.Pen(SD.Color.Lime, 3.0)
                                for m in range(4):
                                    a = full[m]; b = full[(m + 1) % 4]
                                    g2.DrawLine(pen, float(a[0]), float(a[1]), float(b[0]), float(b[1]))
                                g2.Dispose()
                                bm.Save(DBGIMG, SD.Imaging.ImageFormat.Png)
                            except:
                                pass
                bm.Dispose()

    # ---- apply ----
    if apply and not did:
        did = True
        if len(corners) < 3:
            info = 'nothing to apply - press capture first'
        else:
            try:
                _fh = open(REGFILE, 'w')
                _fh.write(json.dumps({'p0': [corners[0].X, corners[0].Y],
                                      'p1': [corners[1].X, corners[1].Y],
                                      'p2': [corners[2].X, corners[2].Y]}))
                _fh.close()
                info = 'written to paper_registration.json - PULL registration to load it'
            except Exception, e:
                info = 'could not write registration: %s' % str(e)

    if not did:
        if H is None:
            info = 'idle - NOT CALIBRATED'
        else:
            info = 'idle - calibrated, press capture'

print(info)
