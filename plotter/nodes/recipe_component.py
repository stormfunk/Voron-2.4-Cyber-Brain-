# PLOT RECIPE - one checklist that decides which processors are in the plot.
#
# There were 23 bypass toggles spread over the full height and width of the
# canvas, so "what is in this plot?" could only be answered by a tour. Worse,
# the tour lied: nine processors read `on = True` while sitting LOCKED, which
# means disabled - the toggle said yes and the component never ran at all.
#
# This is the single source of truth. Tick a processor and it participates;
# untick it and it bypasses. The check list is the control, the outputs are
# just plumbing.
#
# LOCKED is reported, never hidden. A component can be disabled from its right-
# click menu, and no amount of ticking here will wake it - so anything ticked
# but locked is called out by name in the info line. That is the exact class of
# bug this board exists to kill, and it would be absurd to reintroduce it.
#
# PROCESSOR CONTRACT: a list of picked names in, one boolean per processor out.
# Inputs: picked (list of strings from the PLOT RECIPE check list)
NAMES = ['TONE', 'POINTILLISM', 'ASCII', 'STIPPLE', 'SEPARATE',
         'HATCH', 'HILBERT', 'FLOWFIELD', 'SERPENTINE', 'CONTOUR',
         'TRUCHET', 'GROWTH', 'PAWFILL',
         'DASH', 'VARDASH', 'CROP', 'PRESSURE', 'CA',
         'THINOUT', 'TITLEBLOCK', 'SVGIN', 'FRAME']

sel = set()
if picked:
    for v in picked:
        if v is None:
            continue
        try:
            sel.add(str(v).strip().strip('"').strip("'").upper())
        except:
            pass

vals = {}
for n in NAMES:
    vals[n] = (n in sel)

# outputs, in the same order as NAMES
o_tone = vals['TONE']; o_point = vals['POINTILLISM']; o_ascii = vals['ASCII']
o_stipple = vals['STIPPLE']; o_sep = vals['SEPARATE']
o_hatch = vals['HATCH']; o_hilbert = vals['HILBERT']; o_flow = vals['FLOWFIELD']
o_serp = vals['SERPENTINE']; o_contour = vals['CONTOUR']; o_truchet = vals['TRUCHET']
o_growth = vals['GROWTH']; o_paw = vals['PAWFILL']
o_dash = vals['DASH']; o_vardash = vals['VARDASH']; o_crop = vals['CROP']
o_press = vals['PRESSURE']; o_ca = vals['CA']
o_thin = vals['THINOUT']; o_title = vals['TITLEBLOCK']; o_svg = vals['SVGIN']
o_frame = vals['FRAME']

# Which of the ticked components are actually disabled on the canvas? Reading
# the document is the only way to know - `on` is an input, Locked is a property
# of the object, and nothing in the dataflow can see it.
#
# Reading the document from inside a solve is fragile, and this is the careful
# way to do it. Deleting objects on the canvas mutates doc.Objects and schedules
# a solution at the same time, so a plain `for o in doc.Objects` can be halfway
# through enumerating a collection that is being changed underneath it - which
# surfaces as an error on an unrelated component at the exact moment you delete
# something. Snapshot first, and treat a failed snapshot as "cannot check now"
# rather than as a problem worth reporting: this is a convenience warning, and
# it must never be the reason a solve goes red.
locked_on = []
unknown = []
checked = True
try:
    _doc = ghenv.Component.OnPingDocument()
    _objs = []
    if _doc is not None:
        try:
            _objs = list(_doc.Objects)
        except:
            _objs = []
            checked = False
    else:
        checked = False
    _live = {}
    for _o in _objs:
        try:
            _nk = (_o.NickName or '')
        except:
            continue
        if _nk in vals:
            _live[_nk] = _o
    if checked:
        for n in NAMES:
            if not vals[n]:
                continue
            c = _live.get(n)
            if c is None:
                unknown.append(n)
            else:
                try:
                    if c.Locked:
                        locked_on.append(n)
                except:
                    pass
except:
    checked = False
    locked_on = []
    unknown = []

on_names = [n for n in NAMES if vals[n]]
info = 'PLOT RECIPE: %d of %d live -> %s' % (
    len(on_names), len(NAMES), (', '.join(on_names) if on_names else 'nothing'))
if locked_on:
    info += ' | TICKED BUT DISABLED (right-click > Enable): %s' % ', '.join(locked_on)
if unknown:
    info += ' | not found on canvas: %s' % ', '.join(unknown)
extra = sorted(sel - set(NAMES))
if extra:
    info += ' | unrecognised picks ignored: %s' % ', '.join(extra)
print(info)
