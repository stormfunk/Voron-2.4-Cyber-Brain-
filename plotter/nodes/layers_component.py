# LAYER TABLE: one row per source. pen # >= 1 -> plots in that pass; 0 -> off
# (off layers flow out as `ghosted`).
#
# Items arrive as GUIDS, not geometry - the inputs carry no type hint, so what
# lands in the script is a reference, not a curve. The table used to pass those
# straight through and let Grasshopper resolve them on the way out, which works
# right up until one of them will not resolve: PRESSURE emitted 2012 invalid
# polylines among 16630, GhPython null-dereferenced marshalling them, and the
# whole table died with "Object reference not set to an instance of an object" -
# zero curves, no pass, and an error naming neither the slot nor the source. It
# read as "slot 4 is broken" when slot 4 was fine and the data was rotten.
#
# So: coerce every item to real geometry HERE, drop what will not resolve or is
# invalid, and say how many went. This is the one place every processor funnels
# through, so a single guard covers every slot and every generator added later.
import Rhino.Geometry as rg
import rhinoscriptsyntax as rs
import scriptcontext as sc
try:
    sc.doc = ghdoc
except:
    pass

curves = []; pens = []; ghosted = []
slots = [(curves1, pen1), (curves2, pen2), (curves3, pen3),
         (curves4, pen4), (curves5, pen5), (curves6, pen6)]
dropped = [0, 0, 0, 0, 0, 0]
for idx in range(len(slots)):
    lst, pn = slots[idx]
    pnum = 0 if pn is None else int(pn)
    if not lst:
        continue
    for c in lst:
        cc = None
        if isinstance(c, rg.Curve):
            cc = c
        else:
            try:
                cc = rs.coercecurve(c)
            except:
                cc = None
        if cc is None:
            dropped[idx] += 1
            continue
        try:
            if not cc.IsValid:
                dropped[idx] += 1
                continue
        except:
            dropped[idx] += 1
            continue
        if pnum >= 1:
            curves.append(cc)
            pens.append(pnum)
        else:
            ghosted.append(cc)

msg = '%d curves plotting, %d ghosted' % (len(curves), len(ghosted))
bad = []
for i in range(6):
    if dropped[i]:
        bad.append('slot %d: %d' % (i + 1, dropped[i]))
if bad:
    msg += ' | DROPPED invalid curves -> %s (that source is emitting rubbish)' % ', '.join(bad)
print(msg)
