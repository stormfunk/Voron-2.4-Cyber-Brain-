# TONE REGIONS - an image cut into closed tone bands, so photographs can drive
# the region fills.
#
# Every fill in this pipeline (HATCH, PAWFILL, HILBERT, ...) takes CLOSED curves
# and fills what is inside. The image processors all went the other way - ASCII,
# POINTILLISM and SEPARATION each turn an image straight into marks - so there
# was no way to hatch a photograph. This is the missing link: image in, closed
# regions out, one set per tone band.
#
# Two outputs, and both are useful on their own:
#   out_crvs - every band boundary as linework. A posterised portrait in
#              outline, drawable as-is.
#   bands    - a tree, one branch per band, darkest first. Feed branch 0 into a
#              tight hatch, branch 2 into a loose one, branch 3 into PAWFILL.
#
# Bands are cut by DIFFERENCE, not by nesting. Contouring at a threshold gives
# "everything darker than L", so the bands would sit inside one another and any
# fill would be laid two, three, four times over the darkest areas - a blot on
# paper and a waste of plotting time. Subtracting the next threshold down leaves
# bands that tile the region exactly once.
#
# The sampling grid is padded with a border of background value so that every
# contour closes inside the grid. An unclosed chain is fine for CONTOUR, which
# only draws lines; here it would be a region with no inside.
#
# PROCESSOR CONTRACT: closed curves in (`crvs`) -> band boundaries out
# (`out_crvs`), plus `bands` as a tree.
# Inputs: crvs(list, closed), image(file path), nbands(int), detail(mm grid),
#         invert(bool), gamma(float, <1 opens shadows), inset(mm),
#         keep_edge(bool), on(bool bypass)
import Rhino
import Rhino.Geometry as rg
import rhinoscriptsyntax as rs
import scriptcontext as sc
import math, clr, System
from System.Collections.Generic import List
import Grasshopper as gh
from Grasshopper import DataTree
from Grasshopper.Kernel.Data import GH_Path
try:
    sc.doc = ghdoc
except:
    pass

clr.AddReference("System.Drawing")
import System.Drawing as SD
clr.AddReferenceToFileAndPath(r"C:\Users\john.chandler\AppData\Roaming\McNeel\Rhinoceros\packages\7.0\Clipper2GH\1.3.2\Clipper2Lib.dll")
from Clipper2Lib import Paths64, Path64, Point64, Clipper, JoinType, EndType, FillRule

SCALE = 1000.0

NB = int(nbands) if nbands is not None else 4
if NB < 2: NB = 2
if NB > 10: NB = 10
DET = float(detail) if detail is not None else 1.2
if DET < 0.3: DET = 0.3
INV = False if invert is None else bool(invert)
# Blur radius in mm, applied to the sampled grid before contouring. Fur, hair
# and film grain sit right on the band thresholds and each speck becomes its own
# closed loop: an unsmoothed photo of a cat produced 675 regions, most of them
# smaller than the pen. Blurring first is what turns a photograph into shapes
# rather than confetti.
SMOOTH = float(smooth) if smooth is not None else 1.5
if SMOOTH < 0.0: SMOOTH = 0.0
# Drop regions below this area. Even after blurring there is a tail of specks;
# anything the pen cannot draw as a recognisable shape is just travel time and
# a dot of ink. Applies to holes as well as islands.
MINA = float(min_area) if min_area is not None else 4.0
if MINA < 0.0: MINA = 0.0
GAM = float(gamma) if gamma is not None else 1.0
if GAM < 0.1: GAM = 0.1
if GAM > 4.0: GAM = 4.0
INS = float(inset) if inset is not None else 0.0
if INS < 0.0: INS = 0.0
EDGE = False if keep_edge is None else bool(keep_edge)
ON = True if on is None else bool(on)
IMG = None
if image is not None:
    try:
        IMG = str(image).strip('"')
    except:
        IMG = None

cs = []
n_open = 0
if crvs:
    for c in crvs:
        cc = c if isinstance(c, rg.Curve) else rs.coercecurve(c)
        if cc is None:
            continue
        if not cc.IsClosed:
            n_open += 1
            continue
        cs.append(cc)

out_crvs = []
bands = DataTree[object]()
info = ''

if not ON:
    out_crvs = cs
    info = '[BYPASSED]'
elif not cs:
    info = 'needs closed regions'
elif not IMG:
    info = 'needs an image file'
else:
    bmp = None
    try:
        bmp = SD.Bitmap(IMG)
    except:
        bmp = None
    if bmp is None:
        info = 'could not open %s' % IMG
    else:
        bb = rg.BoundingBox.Empty
        for c in cs:
            bb.Union(c.GetBoundingBox(True))
        x0 = bb.Min.X; y0 = bb.Min.Y
        wid = bb.Max.X - x0; hei = bb.Max.Y - y0
        nx = int(math.ceil(wid / DET)) + 1
        ny = int(math.ceil(hei / DET)) + 1
        # Hard cap. The grid is scanned once per band, so cost grows as
        # nx*ny*bands - at 700 square that is a quarter of a billion cell tests
        # in IronPython and the solve never returns.
        CAP = 340
        clipped = (nx > CAP or ny > CAP)
        if nx > CAP: nx = CAP
        if ny > CAP: ny = CAP
        sx = wid / float(nx); sy = hei / float(ny)

        # ---- downsample the image to the grid, once, in native code ----------
        # Point-sampling one pixel per grid node aliases badly on fur: a hard
        # edge lands on or between nodes and the band boundary crawls. Averaging
        # is what a photo needs - but doing it in Python via GetPixel is around
        # a million calls at this grid size and never returns. Drawing the image
        # into a grid-sized bitmap makes GDI+ do the filtering, then LockBits
        # reads the result in one go.
        iw = bmp.Width; ih = bmp.Height
        sc_img = min(wid / float(iw), hei / float(ih))   # contain, centred
        dw = iw * sc_img; dh = ih * sc_img
        ox = x0 + (wid - dw) * 0.5
        oy = y0 + (hei - dh) * 0.5
        gw = nx + 1; gh_ = ny + 1
        small = SD.Bitmap(gw, gh_, SD.Imaging.PixelFormat.Format24bppRgb)
        gfx = SD.Graphics.FromImage(small)
        gfx.Clear(SD.Color.White)            # outside the photo reads as white
        gfx.InterpolationMode = SD.Drawing2D.InterpolationMode.HighQualityBicubic
        dx0 = (ox - x0) / sx
        dy0 = (oy - y0) / sy
        dxw = dw / sx
        dyh = dh / sy
        # model Y runs up, image Y runs down: flip by drawing bottom-anchored
        gfx.DrawImage(bmp, SD.RectangleF(float(dx0), float(gh_ - dy0 - dyh),
                                         float(dxw), float(dyh)))
        gfx.Dispose()
        bmp.Dispose()
        from System.Drawing.Imaging import ImageLockMode, PixelFormat
        from System.Runtime.InteropServices import Marshal
        dat = small.LockBits(SD.Rectangle(0, 0, gw, gh_), ImageLockMode.ReadOnly,
                             PixelFormat.Format24bppRgb)
        stride = dat.Stride
        nbytes = abs(stride) * gh_
        buf = System.Array.CreateInstance(System.Byte, nbytes)
        Marshal.Copy(dat.Scan0, buf, 0, nbytes)
        small.UnlockBits(dat)
        small.Dispose()
        L = []
        for j in range(gh_):
            row = []
            ro = (gh_ - 1 - j) * stride      # row 0 of L is the BOTTOM of the image
            for i in range(gw):
                b = buf[ro + i*3]; g_ = buf[ro + i*3 + 1]; r = buf[ro + i*3 + 2]
                row.append((0.299*r + 0.587*g_ + 0.114*b) / 255.0)
            L.append(row)

        # ---- blur the sampled grid ------------------------------------------
        # Separable box blur, three passes, which approximates a Gaussian well
        # enough and costs O(n) per pass instead of O(r^2) per pixel.
        rad = int(round(SMOOTH / max(sx, sy)))
        if rad > 0:
            for _pass in range(3):
                for j in range(gh_):
                    row = L[j]
                    acc = []
                    run = 0.0
                    for i in range(gw):
                        run += row[i]
                        acc.append(run)
                    nr = []
                    for i in range(gw):
                        a = i - rad - 1; b = i + rad
                        if b > gw - 1: b = gw - 1
                        hi_ = acc[b]
                        lo_ = acc[a] if a >= 0 else 0.0
                        nr.append((hi_ - lo_) / float(b - (a if a >= 0 else -1)))
                    L[j] = nr
                for i in range(gw):
                    acc = []
                    run = 0.0
                    for j in range(gh_):
                        run += L[j][i]
                        acc.append(run)
                    for j in range(gh_):
                        a = j - rad - 1; b = j + rad
                        if b > gh_ - 1: b = gh_ - 1
                        hi_ = acc[b]
                        lo_ = acc[a] if a >= 0 else 0.0
                        L[j][i] = (hi_ - lo_) / float(b - (a if a >= 0 else -1))

        # region membership on the same grid
        plane = rg.Plane.WorldXY
        tol = 0.001
        regions = cs
        M = []
        for j in range(ny + 1):
            mrow = []
            py = y0 + j * sy
            for i in range(nx + 1):
                p3 = rg.Point3d(x0 + i * sx, py, 0)
                hits = 0
                for c in regions:
                    if c.Contains(p3, plane, tol) == rg.PointContainment.Inside:
                        hits += 1
                mrow.append((hits % 2) == 1)
            M.append(mrow)

        # auto-levels across what is actually inside the region, so a photo that
        # never reaches black or white still uses every band
        lo = 1e9; hi = -1e9
        for j in range(ny + 1):
            for i in range(nx + 1):
                if M[j][i]:
                    if L[j][i] < lo: lo = L[j][i]
                    if L[j][i] > hi: hi = L[j][i]
        if hi <= lo:
            hi = lo + 1e-6
        for j in range(ny + 1):
            for i in range(nx + 1):
                t = (L[j][i] - lo) / (hi - lo)
                if t < 0.0: t = 0.0
                if t > 1.0: t = 1.0
                if GAM != 1.0:
                    t = math.pow(t, GAM)
                L[j][i] = (1.0 - t) if INV else t

        # ---- pad the grid with a ring of "light" ------------------------------
        # Without this, a dark area running off the edge of the photo produces an
        # OPEN chain, and closing it later joins its two ends with a straight
        # line across the picture - which is why the first attempt on a
        # full-bleed photo came back as two flat shades instead of a cat. One
        # ring of maximum-value nodes guarantees every contour closes inside the
        # grid, and it closes along the picture edge where it belongs.
        PADV = 1.0
        for j in range(len(L)):
            L[j].insert(0, PADV)
            L[j].append(PADV)
        L.insert(0, [PADV] * (len(L[0])))
        L.append([PADV] * (len(L[0])))
        nx = nx + 2
        ny = ny + 2
        x0 = x0 - sx
        y0 = y0 - sy

        TABLE = {0: [], 1: [(0, 3)], 2: [(0, 1)], 3: [(1, 3)], 4: [(1, 2)],
                 5: [(0, 3), (1, 2)], 6: [(0, 2)], 7: [(2, 3)], 8: [(2, 3)],
                 9: [(0, 2)], 10: [(0, 1), (2, 3)], 11: [(1, 2)], 12: [(1, 3)],
                 13: [(0, 1)], 14: [(0, 3)], 15: []}

        # region as Clipper paths, used to trim every band
        rpaths = Paths64()
        for c in regions:
            plc = c.ToPolyline(0.05, 0.2, 0.01, 1e6)
            if plc is None: continue
            pth = Path64()
            for i in range(plc.PointCount - 1):
                p = plc.Point(i)
                pth.Add(Point64(int(round(p.X*SCALE)), int(round(p.Y*SCALE))))
            rpaths.Add(pth)
        rpaths = Clipper.Union(rpaths, FillRule.EvenOdd)
        if INS > 0.01:
            sh = Clipper.InflatePaths(rpaths, -INS*SCALE, JoinType.Round, EndType.Polygon)
            if sh is not None and sh.Count > 0:
                rpaths = sh

        # ---- one closed contour set per threshold ----------------------------
        # threshold k separates band k-1 from band k; darkest first
        prev = None
        nseg = 0
        for k in range(NB):
            if k == NB - 1:
                cur = None                    # lightest band is "the remainder"
            else:
                lev = (k + 1) / float(NB)
                segs = []
                for j in range(ny):
                    for i in range(nx):
                        v00 = L[j][i]; v10 = L[j][i+1]
                        v11 = L[j+1][i+1]; v01 = L[j+1][i]
                        idx = 0
                        if v00 > lev: idx |= 1
                        if v10 > lev: idx |= 2
                        if v11 > lev: idx |= 4
                        if v01 > lev: idx |= 8
                        pairs = TABLE[idx]
                        if not pairs: continue
                        ax = x0 + i*sx; ay = y0 + j*sy
                        bx = ax + sx; by = ay + sy
                        ept = {}
                        if abs(v10-v00) > 1e-12: ept[0] = (ax + (lev-v00)/(v10-v00)*sx, ay)
                        if abs(v11-v10) > 1e-12: ept[1] = (bx, ay + (lev-v10)/(v11-v10)*sy)
                        if abs(v11-v01) > 1e-12: ept[2] = (ax + (lev-v01)/(v11-v01)*sx, by)
                        if abs(v01-v00) > 1e-12: ept[3] = (ax, ay + (lev-v00)/(v01-v00)*sy)
                        for pr in pairs:
                            if pr[0] in ept and pr[1] in ept:
                                _a = ept[pr[0]]; _b = ept[pr[1]]
                                if (_a[0]-_b[0])**2 + (_a[1]-_b[1])**2 > 1e-10:
                                    segs.append((_a, _b))
                nseg += len(segs)
                # chain into loops
                q = min(sx, sy) * 0.25
                if q < 1e-6: q = 1e-6
                endmap = {}
                for si in range(len(segs)):
                    for e in (0, 1):
                        p = segs[si][e]
                        key = (int(round(p[0]/q)), int(round(p[1]/q)))
                        if key not in endmap: endmap[key] = []
                        endmap[key].append((si, e))
                used = [False]*len(segs)
                cur = Paths64()
                for si in range(len(segs)):
                    if used[si]: continue
                    used[si] = True
                    chain = [segs[si][0], segs[si][1]]
                    for endsel in (1, 0):
                        grew = True
                        while grew:
                            grew = False
                            p = chain[-1] if endsel == 1 else chain[0]
                            key = (int(round(p[0]/q)), int(round(p[1]/q)))
                            if key not in endmap: continue
                            for pair in endmap[key]:
                                sj = pair[0]; ej = pair[1]
                                if used[sj]: continue
                                used[sj] = True
                                oth = segs[sj][1-ej]
                                if endsel == 1: chain.append(oth)
                                else: chain.insert(0, oth)
                                grew = True
                                break
                    if len(chain) < 4: continue
                    pth = Path64()
                    last = None
                    for pnt in chain:
                        key = (int(round(pnt[0]*SCALE)), int(round(pnt[1]*SCALE)))
                        if key == last: continue
                        pth.Add(Point64(key[0], key[1]))
                        last = key
                    if pth.Count >= 3:
                        cur.Add(pth)
                if cur.Count:
                    cur = Clipper.Union(cur, FillRule.EvenOdd)

            # band k = (everything darker than this threshold) minus the band
            # already claimed by the darker thresholds
            if cur is None:
                band = Clipper.Difference(rpaths, prev, FillRule.NonZero) if prev is not None else rpaths
            else:
                inside = Clipper.Intersect(cur, rpaths, FillRule.NonZero)
                if prev is None:
                    band = inside
                else:
                    band = Clipper.Difference(inside, prev, FillRule.NonZero)
                prev = inside
            pathk = GH_Path(k)
            made = 0
            dropped = 0
            if band is not None:
                for pth in band:
                    if pth.Count < 3: continue
                    if MINA > 0.0:
                        # Clipper area is signed (holes wind the other way), so
                        # test the magnitude - a speck is a speck either way
                        a_mm = abs(Clipper.Area(pth)) / (SCALE * SCALE)
                        if a_mm < MINA:
                            dropped += 1
                            continue
                    lp = List[rg.Point3d]()
                    for pt in pth:
                        lp.Add(rg.Point3d(pt.X/SCALE, pt.Y/SCALE, 0))
                    lp.Add(rg.Point3d(pth[0].X/SCALE, pth[0].Y/SCALE, 0))
                    pc = rg.PolylineCurve(lp)
                    bands.Add(pc, pathk)
                    out_crvs.append(pc)
                    made += 1
            if made == 0:
                bands.AddRange([], pathk)

        if EDGE:
            for c in cs:
                out_crvs.append(c)
        counts = []
        for k in range(NB):
            counts.append(str(bands.Branch(GH_Path(k)).Count))
        info = '%d bands (darkest first): %s curves | grid %dx%d, blur %.1fmm (%d cells), min area %.1fmm2 | levels %.2f-%.2f' % (
            NB, '/'.join(counts), nx, ny, SMOOTH, rad, MINA, lo, hi)
        if clipped:
            info += ' | GRID CAPPED at %d - raise `detail` for a coarser but faster pass' % CAP
        if n_open:
            info += ' | %d open curve(s) skipped' % n_open

print(info)
