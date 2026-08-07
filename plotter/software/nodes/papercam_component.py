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
# Corners from the last capture, staged so APPLY can be a separate press.
PENDFILE = r'C:\Users\john.chandler\voron_plotter\paper_pending.json'
DBGIMG = r'C:\Users\john.chandler\voron_plotter\screenshots\papercam_debug.png'

# --- find_marks tuning, in pixels of a 1280-wide frame ---------------------
# A tape patch runs about 5-9k px at this working distance; the bounds are set
# either side of that. The upper one also catches a patch that has merged with
# a reflection on the bed, which is worth losing rather than measuring.
PATCH_MIN = 1500
# Upper bound as a FRACTION of the frame, because a "patch" may be a scrap of
# tape holding one mark or a whole sheet of paper holding the entire grid - an
# A4 sheet measured 418662px here, over 45% of the frame. An absolute limit had
# to be guessed and was wrong twice. A ceiling is still needed so a
# frame-filling reflection cannot be mistaken for the work.
PATCH_MAX_FRAC = 0.75
# Size band for one drawn mark, in pixels of a 1280-wide frame. A 9mm cross in
# fine liner runs 40-90px here. The upper bound rejects a blob that is really
# several marks joined by a dragged travel line, or a shadow.
INK_MIN = 20
INK_MAX = 4000
# Two detections closer than this are the same mark seen via overlapping patch
# boxes. Marks are ~100mm apart on the bed (>250px here), so this is far below
# any real spacing and cannot merge two genuine marks.
DEDUP_PX = 8.0
# Density radius for locating the crossing. Roughly a quarter of a MARKD mark
# as projected here: large enough to span both strokes, small enough that the
# peak stays at the crossing rather than drifting along an arm.
PEAK_R = 7.0

# Outlier rejection. A mark can be dragged off centre by a fold in the tape or
# a stray pen line, and one bad mark at 11.9mm pulled an 8-mark fit to 6.2mm
# RMS. Marks are dropped worst-first while the worst still exceeds this and
# enough remain to keep the fit over-determined - a homography has 8 degrees of
# freedom, so 4 points is exact and says nothing about accuracy.
FIT_TOL_MM = 1.5
FIT_MIN_MARKS = 6
# Above this, the fit is not noisy - it is WRONG, with marks paired to the
# wrong grid cells. A real calibration on this rig lands under 1mm, so anything
# near this limit means the layout was misread rather than measured badly.
CAL_MAX_MM = 5.0
# Ink-area sanity. Every mark is the same drawn shape, so areas should cluster;
# anything more than this factor from the median is bloom or tape shading, not
# ink. Kept loose because perspective genuinely varies mark size across the bed.
AREA_TOL = 3.0


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


def homography_n(src, dst):
    """least-squares homography from N>=4 correspondences.

    Four points give an exact fit, which means it fits any error in those four
    perfectly and tells you nothing. With more marks the system is
    over-determined, so the residual per mark becomes a real measurement - of
    lens distortion, of a mark drawn slightly off, of the camera having shifted.
    Solved through the normal equations (A^T A x = A^T b) on the same 8-unknown
    DLT rows."""
    n = len(src)
    if n < 4 or len(dst) < n:
        return None
    if n == 4:
        return homography(src, dst)
    ATA = []
    for i in range(8):
        ATA.append([0.0] * 8)
    ATb = [0.0] * 8
    for i in range(n):
        x, y = src[i]
        u, v = dst[i]
        rows = ([x, y, 1.0, 0.0, 0.0, 0.0, -u * x, -u * y],
                [0.0, 0.0, 0.0, x, y, 1.0, -v * x, -v * y])
        rhs = (u, v)
        for r in range(2):
            row = rows[r]
            for a in range(8):
                if row[a] == 0.0:
                    continue
                ATb[a] += row[a] * rhs[r]
                for b2 in range(8):
                    if row[b2] != 0.0:
                        ATA[a][b2] += row[a] * row[b2]
    h = solve8(ATA, ATb)
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


def send_gcode(host, cmd):
    """fire a command at Moonraker and wait for the motion to finish"""
    try:
        import urllib
        import urllib2
        u = host + '/printer/gcode/script?script=' + urllib.quote(cmd)
        urllib2.urlopen(urllib2.Request(u, ''), timeout=60)
        return True
    except:
        return False


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


def blobs(gr, w, h, t, amin, amax):
    """dark connected regions whose area falls in a band.

    The bed is dark too, so a plain dark threshold catches everything - but the
    bed comes out as one enormous component and a drawn mark as a small round
    one, so filtering on area is what separates them. It also means this works
    whether the marks are on one big sheet or on separate scraps of tape."""
    seen = [False] * (w * h)
    out = []
    for sy in range(h):
        base = sy * w
        for sx in range(w):
            i = base + sx
            if seen[i] or gr[i] > t:
                continue
            stack = [i]
            seen[i] = True
            cells = []
            over = False
            while stack:
                p = stack.pop()
                cells.append(p)
                if len(cells) > amax:
                    over = True
                    break
                py = p // w
                px = p - py * w
                if px > 0:
                    q = p - 1
                    if not seen[q] and gr[q] <= t:
                        seen[q] = True; stack.append(q)
                if px < w - 1:
                    q = p + 1
                    if not seen[q] and gr[q] <= t:
                        seen[q] = True; stack.append(q)
                if py > 0:
                    q = p - w
                    if not seen[q] and gr[q] <= t:
                        seen[q] = True; stack.append(q)
                if py < h - 1:
                    q = p + w
                    if not seen[q] and gr[q] <= t:
                        seen[q] = True; stack.append(q)
            if over or len(cells) < amin:
                continue
            n = len(cells)
            x0 = w; x1 = -1; y0 = h; y1 = -1
            sxs = 0.0; sys = 0.0
            for p in cells:
                py = p // w
                px = p - py * w
                sxs += px; sys += py
                if px < x0: x0 = px
                if px > x1: x1 = px
                if py < y0: y0 = py
                if py > y1: y1 = py
            bw = x1 - x0 + 1.0
            bh = y1 - y0 + 1.0
            # An X covers only about a fifth of its bounding box (2*L*w / L^2),
            # against ~0.79 for a filled disc - so the fill test has to be loose
            # enough to admit a cross while still rejecting long thin strokes
            # and the huge single blob the bed itself forms. The squareness test
            # below does most of the discriminating for an X.
            fill = n / (bw * bh)
            if fill < 0.10 or fill > 0.95:
                continue
            if bw / bh > 2.0 or bh / bw > 2.0:
                continue
            out.append((sxs / n, sys / n, n, x0, y0, x1, y1))
    return out


def find_marks(gr, w, h):
    """centre of every drawn mark, located on its own patch of white.

    One global threshold cannot do this. The bed is dark, the tape is white and
    the ink is mid-grey, so the single Otsu split that separates bed from tape
    puts the ink on the SAME side as the tape: measured here, bed ~40, tape
    ~250, felt-tip X ~210, with Otsu landing at 125. Every mark was invisible.

    Lighting makes it worse. A bloom on the lower bed reaches 209, near enough
    to the tape that the two merge - one such blob came out at 28713px and was
    discarded for being oversized, taking two real marks with it.

    Hence two stages. A second Otsu, run over only the pixels the first called
    bright, splits tape (240+) from bloom (<210) and yields the tape patches.
    Each patch then gets its OWN Otsu across its interior, which adapts to how
    darkly that particular mark was drawn - the nine here needed cuts from 167
    to 246, and no single fixed value caught them all.

    The interior is taken from the patch's convex hull shrunk toward its
    centre, not from its bounding box. A box around a patch of tape also
    contains bed, and bed is darker than any ink, so it dominates the result.
    Shrinking also drops the tape's own shaded border.

    The centre is the peak of local ink density rather than the centroid of all
    the ink. An X's strokes overlap only where they cross, so the crossing
    carries about twice the density of either arm, and a stray pen line or a
    fold in the tape moves that peak far less than it moves a plain centroid.

    Returns (marks, t) where each mark is (x, y, ink_px) in the given raster.
    """
    t1 = otsu(gr)
    bright = []
    for v in gr:
        if v > t1:
            bright.append(v)
    if not bright:
        return [], t1
    t = otsu(bright)

    seen = [False] * (w * h)
    patches = []
    patch_max = int(w * h * PATCH_MAX_FRAC)
    for sy in range(h):
        base = sy * w
        for sx in range(w):
            i = base + sx
            if seen[i] or gr[i] <= t:
                continue
            stack = [i]
            seen[i] = True
            over = False
            # Accumulate the bounding box during the fill and keep NO per-pixel
            # lists. A sheet of paper is over 400k pixels, and building a cell
            # list plus a list of (x,y) tuples for it cost more time than the
            # whole rest of detection - enough to time the call out. Nothing
            # downstream needs the pixels themselves, only the box.
            n = 0
            x0 = w; x1 = -1; y0 = h; y1 = -1
            while stack:
                p = stack.pop()
                n += 1
                if n > patch_max:
                    over = True
                    break
                py = p // w
                px = p - py * w
                if px < x0: x0 = px
                if px > x1: x1 = px
                if py < y0: y0 = py
                if py > y1: y1 = py
                if px > 0:
                    q = p - 1
                    if not seen[q] and gr[q] > t:
                        seen[q] = True; stack.append(q)
                if px < w - 1:
                    q = p + 1
                    if not seen[q] and gr[q] > t:
                        seen[q] = True; stack.append(q)
                if py > 0:
                    q = p - w
                    if not seen[q] and gr[q] > t:
                        seen[q] = True; stack.append(q)
                if py < h - 1:
                    q = p + w
                    if not seen[q] and gr[q] > t:
                        seen[q] = True; stack.append(q)
            if over or n < PATCH_MIN:
                continue
            bw = x1 - x0 + 1.0
            bh = y1 - y0 + 1.0
            if bw / bh > 2.2 or bh / bw > 2.2:
                continue
            # a patch running off the frame is clipped, so its outline is not
            # the real one - and the machine's own bright parts at the frame
            # edges look just like work until they are excluded this way
            if x0 <= 1 or y0 <= 1 or x1 >= w - 2 or y1 >= h - 2:
                continue
            patches.append((x0, y0, x1, y1))

    out = []
    for (x0, y0, x1, y1) in patches:
        # A mark is a HOLE in the bright region. Ink is darker than the
        # threshold that found the paper, so the marks are exactly the dark
        # pixels enclosed by the patch - no second threshold needed, and
        # enclosure is a structural test rather than a tuned one.
        #
        # This replaced a per-pixel neighbourhood test that measured how much
        # of a window was paper. That worked, but it ran over every pixel of
        # the patch's bounding box, and on a full sheet (~450k px) it was slow
        # enough to time the call out. Enclosure gets the same answer from one
        # scan plus a flood fill over the few dark pixels.
        #
        # A patch may hold one mark or the whole grid: a scrap of tape holds
        # one, a sheet of paper holds nine. So every enclosed blob is a
        # candidate, not just the largest.
        bw_ = x1 - x0 + 1
        bh_ = y1 - y0 + 1
        dark = {}
        for yy in range(y0, y1 + 1):
            ro = yy * w
            base = (yy - y0) * bw_ - x0
            for xx in range(x0, x1 + 1):
                v = gr[ro + xx]
                if v <= t:
                    dark[base + xx] = v
        seen2 = {}
        for key in dark:
            if key in seen2:
                continue
            stack = [key]
            seen2[key] = True
            blob = []
            edge = False
            while stack:
                q = stack.pop()
                blob.append(q)
                qy = q // bw_
                qx = q - qy * bw_
                if qx == 0 or qy == 0 or qx == bw_ - 1 or qy == bh_ - 1:
                    edge = True
                for (r, ok) in ((q - 1, qx > 0), (q + 1, qx < bw_ - 1),
                                (q - bw_, qy > 0), (q + bw_, qy < bh_ - 1)):
                    if ok and (r in dark) and (r not in seen2):
                        seen2[r] = True
                        stack.append(r)
            # A dark region reaching the bounding box is the bed AROUND the
            # patch, not a mark drawn inside it. That single test is what
            # separates ink from background here.
            if edge or len(blob) < INK_MIN or len(blob) > INK_MAX:
                continue
            bpts = []
            for q in blob:
                qy = q // bw_
                wt = t - dark[q]
                if wt < 1.0:
                    wt = 1.0
                bpts.append((x0 + q - qy * bw_, y0 + qy, wt))
            # Peak of local ink density, not the centroid of the blob. An X's
            # strokes overlap only where they cross, so the crossing carries
            # about twice the density of either arm, and a stray line or a
            # smudge shifts that peak far less than it shifts a centroid.
            best = -1.0
            bx0 = 0.0; by0 = 0.0
            for a in range(len(bpts)):
                ax, ay, aw = bpts[a]
                s = 0.0
                for b in range(len(bpts)):
                    px, py, pw = bpts[b]
                    dx = px - ax; dy = py - ay
                    if dx * dx + dy * dy <= PEAK_R * PEAK_R:
                        s += pw
                if s > best:
                    best = s; bx0 = ax; by0 = ay
            sx = 0.0; sy = 0.0; sw = 0.0; cnt = 0
            for (px, py, pw) in bpts:
                dx = px - bx0; dy = py - by0
                if dx * dx + dy * dy <= 4.0 * PEAK_R * PEAK_R:
                    sx += px * pw; sy += py * pw; sw += pw; cnt += 1
            if sw <= 0.0:
                continue
            out.append((sx / sw, sy / sw, cnt))

    # Drop duplicates. Patches are kept as bounding BOXES, and boxes overlap:
    # anything closed drawn on the sheet splits it into an inner area and an
    # outer ring whose boxes both contain every mark, so each mark is found
    # once per patch. Two nested borders reported 18 marks for 9 and the grid
    # match failed with "a column band holds 6 marks".
    uniq = []
    for (mx, my, cnt) in out:
        hit = -1
        for k in range(len(uniq)):
            if abs(uniq[k][0] - mx) < DEDUP_PX and abs(uniq[k][1] - my) < DEDUP_PX:
                hit = k
                break
        if hit < 0:
            uniq.append((mx, my, cnt))
        elif cnt > uniq[hit][2]:
            uniq[hit] = (mx, my, cnt)     # keep the best-resolved copy
    return uniq, t


def biggest_region(gr, w, h, t):
    """pixels of the bright connected region with the largest BOUNDING BOX.

    The sheet is ONE object, but the old approach took every pixel over the
    threshold and hulled the lot. Anything else pale in frame then joins the
    sheet: here the three tape marks sitting below it merged in and produced a
    single 123k-pixel blob spanning the frame from top edge to bottom, whose
    quad was meaningless. Labelling first fixes that.

    Selection is by bounding box, NOT by pixel count, and the difference
    matters as soon as anything closed is drawn on the sheet. A border splits
    the paper into an inner area and an outer ring; the inner area has more
    pixels, so a count-based choice returns the INSIDE OF THE DRAWING as though
    it were the sheet. That is exactly what happened here - a capture reported
    "paper 267.5 x 183.5mm, skew -0.78" when the sheet is 295.8 x 211.2 at
    +0.70: it had measured the border, and the next plot would have registered
    to it. The ring always spans the true outline, so its box always wins.
    """
    seen = [False] * (w * h)
    best = []
    bestarea = -1
    for sy in range(h):
        base = sy * w
        for sx in range(w):
            i = base + sx
            if seen[i] or gr[i] <= t:
                continue
            stack = [i]
            seen[i] = True
            cells = []
            while stack:
                q = stack.pop()
                cells.append(q)
                qy = q // w
                qx = q - qy * w
                if qx > 0:
                    r = q - 1
                    if not seen[r] and gr[r] > t:
                        seen[r] = True; stack.append(r)
                if qx < w - 1:
                    r = q + 1
                    if not seen[r] and gr[r] > t:
                        seen[r] = True; stack.append(r)
                if qy > 0:
                    r = q - w
                    if not seen[r] and gr[r] > t:
                        seen[r] = True; stack.append(r)
                if qy < h - 1:
                    r = q + w
                    if not seen[r] and gr[r] > t:
                        seen[r] = True; stack.append(r)
            x0 = w; x1 = -1; y0 = h; y1 = -1
            for q in cells:
                qy = q // w
                qx = q - qy * w
                if qx < x0: x0 = qx
                if qx > x1: x1 = qx
                if qy < y0: y0 = qy
                if qy > y1: y1 = qy
            area = (x1 - x0 + 1) * (y1 - y0 + 1)
            if area > bestarea:
                bestarea = area
                best = cells
    out = []
    for q in best:
        qy = q // w
        out.append((q - qy * w, qy))
    return out


def grid_match(pts, gxs, gys):
    """pair each detection with a grid position, by row and column order.

    This replaces fitting a rough homography to the four EXTREME detections and
    assuming those are the four grid corners. That assumption holds only while
    all four corners are actually found. Lose one - the bloom swallowed the
    bottom-left mark here - and the extremes are no longer corners, so every
    pairing downstream shifts. It made removing a bad mark make the fit WORSE,
    which is the opposite of what outlier rejection is supposed to do: dropping
    the two contaminated marks took the result from 1.1mm to 12.7mm RMS.

    Ordering survives a missing mark where corner identity does not. The marks
    form a regular grid viewed at a modest angle, so the gaps BETWEEN rows are
    far larger than the scatter WITHIN a row, and likewise for columns. Cutting
    the sorted coordinates at the n-1 largest gaps recovers each mark's (column,
    row) index directly - no fit, no corner assumption, and a hole in the grid
    simply leaves a cell empty instead of corrupting its neighbours.

    Returns (src, dst, msg). src/dst are empty when the layout cannot be read.
    """
    n = len(gxs)
    if len(pts) < 4:
        return [], [], 'only %d mark(s)' % len(pts)

    idx = [[0] * len(pts), [0] * len(pts)]
    for axis in (0, 1):
        order = []
        for i in range(len(pts)):
            order.append((pts[i][axis], i))
        order.sort()
        gaps = []
        for k in range(1, len(order)):
            gaps.append((order[k][0] - order[k - 1][0], k))
        gaps.sort()
        cuts = []
        for k in range(len(gaps) - (n - 1), len(gaps)):
            if k >= 0:
                cuts.append(gaps[k][1])
        cuts.sort()
        band = 0
        for k in range(len(order)):
            if band < len(cuts) and k == cuts[band]:
                band += 1
            idx[axis][order[k][1]] = band

    # A band holding more than n marks means a whole row or column went
    # undetected and the cuts landed inside a band instead of between two -
    # the indices are then meaningless, so say so rather than fit to them.
    for axis in (0, 1):
        counts = [0] * n
        for i in range(len(pts)):
            b = idx[axis][i]
            if b < n:
                counts[b] += 1
        for b in range(n):
            if counts[b] > n:
                return [], [], 'a %s band holds %d marks - a whole line is missing' % (
                    'column' if axis == 0 else 'row', counts[b])

    # Image axes vs bed axes, VERIFIED PHYSICALLY - do not "tidy" these.
    #
    #   further right in frame -> HIGHER bed X   (no flip)
    #   further down  in frame -> LOWER  bed Y   (flipped)
    #
    # X was originally flipped here too, on assumption, and that single wrong
    # sign silently mirrored the whole calibration. Nothing caught it: a 3x3
    # grid is symmetric under reflection, so a mirrored homography fits the
    # marks exactly as well as the true one - both to 0.33mm. Residuals CANNOT
    # detect this, and neither can any check made against the marks themselves.
    #
    # What it broke was everything measured off the camera afterwards. The
    # paper's skew came back with the wrong sign, so a border built to match it
    # was rotated by TWICE the skew (2 x 0.64 = 1.28 deg, measured 1.3), and
    # offset by however far the sheet sat off the mirror axis. The marks still
    # looked perfect throughout, which is what made it so hard to find.
    #
    # Confirmed the only way it can be: the toolhead was commanded to bed X60
    # and photographed. It appeared where the mirrored map read X313.
    # Re-verify this way after ANY change to camera mounting or orientation.
    cell = {}
    for i in range(len(pts)):
        ci = idx[0][i]; ri = idx[1][i]
        if ci >= n or ri >= n:
            continue
        key = ri * n + ci
        if key in cell:
            cell[key] = None          # two marks in one cell: trust neither
        else:
            cell[key] = i
    src = []; dst = []
    for key in sorted(cell.keys()):
        i = cell[key]
        if i is None:
            continue
        ri = key // n; ci = key - ri * n
        src.append(pts[i])
        dst.append((gxs[ci], gys[n - 1 - ri]))
    if len(src) < 4:
        return [], [], 'only %d mark(s) landed in distinct grid cells' % len(src)
    return src, dst, '%d of %d cells' % (len(src), n * n)


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


# crowsnest's own port (8080) is NOT reachable from outside the pi - only the
# nginx proxy path is. Verified: :8080 refuses the connection, /webcam/ answers.
#   overhead cam -> /webcam/    (cam bedcam,  USB port 1.1)
#   low side cam -> /webcam2/   (cam lifecam, USB port 1.2)
URL = str(url) if url else 'http://192.168.1.23/webcam/?action=snapshot'
HOST = 'http://192.168.1.23:7125'
PARK = True if park is None else bool(park)
PARKCMD = str(park_cmd) if park_cmd else 'PLOT_CAM_PARK'
THRESH = int(thresh) if thresh is not None else -1
MINA = float(min_area) if min_area is not None else 0.02
DEBUG = True if debug is None else bool(debug)
ON = True if on is None else bool(on)

# Chamber light, driven straight from here rather than through a macro, so that
# recalibrating needs nothing installed on the printer.
#
# The strip goes ON, at full, and the ROOM light must be OFF. Both halves
# matter, and the second one is the one that bites.
#
# The bed is smooth, so a light source does not illuminate it so much as
# reflect off it - and any source at the wrong angle puts a specular patch
# straight into the lens. A room lamp did exactly that: it washed out the lower
# third of the frame, took the whole bottom row of marks with it, and merged
# two patches into a single 137k-pixel blob. Crucially it looked identical with
# the chamber strip at 0 and at 1.0, which is what proves the strip was never
# the culprit. Kill the lamp and the strip becomes the only source - fixed,
# repeatable, and mounted where its reflection misses the lens.
#
# Brightness was then swept over the strip's range with the room dark. Full was
# clearly best: 8 marks and 5.7% clipping, against a degenerate 4-point fit at
# quarter brightness and a failed match at half.
#
# Do not judge any of this by average frame brightness. Auto-exposure holds the
# mean near constant - ~105 from full brightness to off - while the glare
# changes completely. Judge it by how many marks survive.
LIGHT_CAPTURE = 'SET_LED LED=daylight RED=1 GREEN=1 BLUE=1 SYNC=0 TRANSMIT=1'
# Auto-exposure needs a moment to re-settle after the light changes; grabbing
# immediately returns a frame metered for the old lighting.
CAM_SETTLE_MS = 2500

# ---- calibration target ----
# Marks are DRAWN rather than stuck on and measured: the machine already knows
# exactly where it put the pen, so their coordinates are exact by construction,
# and the calibration ends up mapping the camera to MACHINE coordinates - where
# the toolhead actually goes - rather than to the bed as an object.
# The pen sits 58mm in front of the nozzle, so it can only reach Y 0..292.
BEDX = 350.0
PENY = 292.0
GRIDN = int(grid_n) if grid_n is not None else 3
if GRIDN < 2: GRIDN = 2
if GRIDN > 5: GRIDN = 5
INSET = float(inset) if inset is not None else 45.0
MARKD = float(mark_d) if mark_d is not None else 9.0
if MARKD < 3.0: MARKD = 3.0
_gx = []
_gy = []
for i in range(GRIDN):
    f = float(i) / (GRIDN - 1)
    _gx.append(INSET + (BEDX - 2.0 * INSET) * f)
    _gy.append(INSET + (PENY - 2.0 * INSET) * f)
GRID = []
for yy in _gy:
    for xx in _gx:
        GRID.append((xx, yy))

# Marks are an X, not a filled disc. A spiral-filled disc floods as soon as the
# pen is wider than the spiral pitch - a 1mm felt nib on a 0.4mm pitch is 2.5x
# overlap and just makes a blob, which carries no more positional information
# than a cross and a great deal more ink. The centroid of a symmetric X is its
# crossing point, so detection is unchanged in principle and far cheaper to draw.
target_crvs = []
for (mx, my) in GRID:
    r = MARKD * 0.5
    for (ax, ay, bx, by) in ((-r, -r, r, r), (-r, r, r, -r)):
        lp = List[rg.Point3d]()
        lp.Add(rg.Point3d(mx + ax, my + ay, 0))
        lp.Add(rg.Point3d(mx + bx, my + by, 0))
        target_crvs.append(rg.PolylineCurve(lp))

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
        parked = ''
        if PARK:
            parked = 'parked | ' if send_gcode(HOST, PARKCMD) else 'PARK FAILED | '
        if send_gcode(HOST, LIGHT_CAPTURE):
            System.Threading.Thread.Sleep(CAM_SETTLE_MS)
            parked = parked + 'lit | '
        bm = grab(URL)
        if bm is None:
            info = 'no frame from %s' % URL
        else:
            # Full resolution, not the 640 used for finding a sheet. A pen
            # stroke is about one pixel wide here, so halving the raster blurs
            # it into the tape and the marks stop existing - at 640 this frame
            # yielded 5 blobs, none of them a mark.
            gr, gw, gh_, scl = gray_of(bm, 1280)
            found, t = find_marks(gr, gw, gh_)
            if len(found) < 4:
                info = ('%sfound only %d mark(s) - need at least 4. '
                        'tape threshold %d. Is the target drawn, and is every '
                        'patch fully inside the frame?') % (parked, len(found), t)
            else:
                # Detections are all the same drawn shape, so one whose ink area
                # is far from the family median is not a mark - it is bloom or
                # tape shading. Two such here came in at 463 and 495px against a
                # median of 50, and both sat well off their crossing.
                areas = []
                for q in found:
                    areas.append(q[2])
                areas.sort()
                amed = areas[len(areas) // 2]
                pts = []
                nrej = 0
                for q in found:
                    if q[2] > amed * AREA_TOL or q[2] * AREA_TOL < amed:
                        nrej += 1
                        continue
                    pts.append((q[0] * scl, q[1] * scl))
                src, dst, mmsg = grid_match(pts, _gx, _gy)
                if not src:
                    info = '%scould not read the grid layout: %s (%d marks, %d rejected on area)' % (
                        parked, mmsg, len(pts), nrej)
                else:
                        # Refit, dropping the worst mark each round. A single
                        # bad detection is common - a fold in the tape or a pen
                        # line crossing the mark - and one at 11.9mm was enough
                        # to pull an otherwise good 8-mark fit out to 6.2mm RMS.
                        nfound = len(src)
                        dropped = []
                        Hn = None
                        res = []
                        while True:
                            Hn = homography_n(src, dst)
                            if Hn is None:
                                break
                            res = []
                            for i in range(len(src)):
                                m = apply_h(Hn, src[i][0], src[i][1])
                                res.append(math.sqrt((m[0]-dst[i][0])**2 + (m[1]-dst[i][1])**2))
                            wi = 0
                            for i in range(len(res)):
                                if res[i] > res[wi]:
                                    wi = i
                            if res[wi] <= FIT_TOL_MM or len(src) <= FIT_MIN_MARKS:
                                break
                            dropped.append((dst[wi][0], dst[wi][1], res[wi]))
                            del src[wi]
                            del dst[wi]
                        res_worst = 0.0
                        for e in res:
                            if e > res_worst:
                                res_worst = e
                        if Hn is None:
                            info = '%ssolve failed - marks may be collinear' % parked
                        elif res_worst > CAL_MAX_MM:
                            # A fit this bad is not a noisy calibration, it is a
                            # WRONG one - marks paired to the wrong grid cells.
                            # It happened when clutter on the sheet hid a whole
                            # row: 6 marks in 2 rows got split across 3 bands
                            # and saved a 29mm-residual map without complaint.
                            info = ('%sNOT SAVED - worst residual %.1f mm (limit %.1f). '
                                    'That is a mis-pairing, not noise: %d marks in too few '
                                    'rows or columns. Clear the sheet and re-plot the target. '
                                    '%d detected, %d rejected on area, matched %s') % (
                                parked, res_worst, CAL_MAX_MM, len(src),
                                len(found), nrej, mmsg)
                        elif len(src) < FIT_MIN_MARKS:
                            # A homography has 8 degrees of freedom, so 4 points
                            # give exactly 8 equations and fit PERFECTLY whatever
                            # they are - residual 0.000mm, and completely
                            # unconstrained between them. That reads as a great
                            # calibration and is worthless, so refuse to save it
                            # rather than report a number that cannot be wrong.
                            info = ('%sNOT SAVED - only %d mark(s) survived, need %d. '
                                    'A fit this small cannot be checked: with 4 points the '
                                    'residual is always 0.000mm. %d detected, %d rejected on '
                                    'area, matched %s | tape threshold %d') % (
                                parked, len(src), FIT_MIN_MARKS, len(found), nrej, mmsg, t)
                        else:
                            res_s = sorted(res)
                            _fh = open(CALFILE, 'w')
                            _fh.write(json.dumps({'H': Hn, 'marks': len(src),
                                                  'worst_mm': res_s[-1],
                                                  'dropped': len(dropped),
                                                  'note': 'image px -> bed mm'}))
                            _fh.close()
                            H = Hn
                            drop_s = ''
                            for (dx_, dy_, de_) in dropped:
                                drop_s += ' | DROPPED bed %.0f,%.0f at %.2fmm' % (dx_, dy_, de_)
                            info = ('%sCALIBRATED on %d of %d marks | %d detected, '
                                    '%d rejected on area, matched %s | residual mean %.3f mm, '
                                    'worst %.3f mm | tape threshold %d%s') % (
                                parked, len(src), len(GRID), len(found), nrej, mmsg,
                                sum(res) / len(res), res_s[-1], t, drop_s)
            bm.Dispose()

    # ---- capture + detect ----
    if capture and not did:
        did = True
        if H is None:
            info = 'not calibrated yet - set calib_img / calib_bed and press calibrate'
        else:
            # An overhead camera looks straight through the gantry, so the beam
            # has to be moved off the sheet before the frame is any use. The
            # back strip is already the exclusion zone the pen cannot reach, so
            # parking there costs no printable area. PLOT_CAM_PARK ends in M400
            # so this returns only once the motion has actually finished.
            parked = ''
            if PARK:
                if send_gcode(HOST, PARKCMD):
                    parked = 'parked | '
                else:
                    parked = 'PARK FAILED (printer off?) | '
            bm = grab(URL)
            if bm is None:
                info = 'no frame from %s (printer off, or wrong URL?)' % URL
            else:
                gr, gw, gh_, scl = gray_of(bm, 640)
                if THRESH < 0:
                    # Two passes, as in find_marks. One Otsu splits bed from
                    # everything pale, which puts the sheet and any glare on the
                    # same side; a second pass over only the bright half then
                    # separates paper from reflection.
                    t1 = otsu(gr)
                    _br = []
                    for v in gr:
                        if v > t1:
                            _br.append(v)
                    t = otsu(_br) if _br else t1
                else:
                    t = THRESH
                pts = biggest_region(gr, gw, gh_, t)
                frac = float(len(pts)) / float(gw * gh_)
                # A sheet running off the edge has no corner there to find, and
                # the quad silently becomes the frame boundary instead of the
                # paper. Better to say so than to register to the wrong thing.
                offedge = []
                for (qx, qy) in pts:
                    if qx <= 0 or qy <= 0 or qx >= gw - 1 or qy >= gh_ - 1:
                        offedge.append(1)
                        break
                if frac < MINA:
                    info = 'nothing bright enough found (%.1f%% of frame over threshold %d)' % (frac * 100.0, t)
                elif frac > 0.9:
                    info = 'almost the whole frame is bright (threshold %d) - is the bed lit too evenly?' % t
                elif offedge:
                    info = ('the sheet runs off the edge of the frame (%.1f%% of frame, threshold %d) - '
                            'its corners are outside the picture, so slide it clear of the edges') % (
                        frac * 100.0, t)
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
                                # Stage them. A GH solve rebuilds `corners` from
                                # scratch, and capture claims the solve, so by
                                # the time APPLY is pressed the list is empty
                                # again and it can only ever answer "press
                                # capture first". Writing them here is what lets
                                # the two buttons be pressed one after the other.
                                try:
                                    _pf = open(PENDFILE, 'w')
                                    _pf.write(json.dumps({'p0': [p0[0], p0[1]],
                                                          'p1': [p1[0], p1[1]],
                                                          'p2': [p2[0], p2[1]]}))
                                    _pf.close()
                                except:
                                    pass
                                w_mm = math.sqrt((p1[0]-p0[0])**2 + (p1[1]-p0[1])**2)
                                h_mm = math.sqrt((p2[0]-p0[0])**2 + (p2[1]-p0[1])**2)
                                skew = math.degrees(math.atan2(p1[1]-p0[1], p1[0]-p0[0]))
                                # local scale from the homography at each corner -
                                # tells you how much a pixel is worth there, which
                                # is the honest measure of how far to trust it
                                mmpx = []
                                for (qx, qy) in full:
                                    a = apply_h(H, qx, qy)
                                    b1 = apply_h(H, qx + 1.0, qy)
                                    b2 = apply_h(H, qx, qy + 1.0)
                                    if a and b1 and b2:
                                        d1 = math.sqrt((b1[0]-a[0])**2 + (b1[1]-a[1])**2)
                                        d2 = math.sqrt((b2[0]-a[0])**2 + (b2[1]-a[1])**2)
                                        mmpx.append(0.5 * (d1 + d2))
                                sc_txt = ''
                                if mmpx:
                                    sc_txt = ' | %.3f-%.3f mm/px at the corners' % (min(mmpx), max(mmpx))
                                info = ('%sFOUND paper %.1f x %.1f mm, skew %+.2f deg | '
                                        'threshold %d (%s), %.0f%% of frame%s | '
                                        'P0 %.1f,%.1f  P1 %.1f,%.1f  P2 %.1f,%.1f') % (
                                    parked, w_mm, h_mm, skew, t, 'auto' if THRESH < 0 else 'manual',
                                    frac * 100.0, sc_txt, p0[0], p0[1], p1[0], p1[1], p2[0], p2[1])
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
        pend = None
        if len(corners) >= 3:
            pend = {'p0': [corners[0].X, corners[0].Y],
                    'p1': [corners[1].X, corners[1].Y],
                    'p2': [corners[2].X, corners[2].Y]}
        else:
            # fall back to whatever the last capture staged
            try:
                _pf = open(PENDFILE)
                pend = json.loads(_pf.read())
                _pf.close()
            except:
                pend = None
        if pend is None:
            info = 'nothing to apply - press capture first'
        else:
            try:
                _fh = open(REGFILE, 'w')
                _fh.write(json.dumps(pend))
                _fh.close()
                info = ('written to paper_registration.json: P0 %.1f,%.1f  P1 %.1f,%.1f  '
                        'P2 %.1f,%.1f - PULL registration to load it') % (
                    pend['p0'][0], pend['p0'][1], pend['p1'][0], pend['p1'][1],
                    pend['p2'][0], pend['p2'][1])
            except Exception, e:
                info = 'could not write registration: %s' % str(e)

    if not did:
        if H is None:
            info = 'idle - NOT CALIBRATED'
        else:
            info = 'idle - calibrated, press capture'

print(info)
