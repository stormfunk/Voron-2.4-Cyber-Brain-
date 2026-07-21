# CENTRE ON PAGE - button utility for the "From graph" placement mode.
# Sets the ARTWORK position XY pad so the artwork's centre lands on the middle
# of the taught paper (or the bed centre if nothing has been taught).
#
# It reads paper_registration.json straight from disk rather than taking PLACE's
# `frame` output, because the pad FEEDS PLACE - wiring the frame back here would
# be a cycle. The pad is nudged from a scheduled solution (you cannot expire an
# upstream object mid-solve without Grasshopper complaining about recursion).
# Inputs: press(button)
import Grasshopper as gh
import json

REGFILE = r'C:\Users\john.chandler\voron_plotter\paper_registration.json'
PADNAME = 'ARTWORK position'
OFFY = -44.5          # pen sits 44.5mm in front of the nozzle (measured 2026-07-17)
BED = 350.0


def apply_centre(d):
    """Self-contained on purpose: re-reads everything rather than closing over
    outer variables (GhPython's nested-scope lookup is not reliable)."""
    import json as _j
    import Rhino.Geometry as _rg
    _cx = 175.0
    _cy = 175.0
    try:
        _fh = open(r'C:\Users\john.chandler\voron_plotter\paper_registration.json')
        _reg = _j.loads(_fh.read())
        _fh.close()
        _p0 = _reg['p0']
        _p1 = _reg['p1']
        _p2 = _reg['p2']
        _cx = _p0[0] + ((_p1[0] - _p0[0]) + (_p2[0] - _p0[0])) / 2.0
        _cy = _p0[1] + ((_p1[1] - _p0[1]) + (_p2[1] - _p0[1])) / 2.0 - 44.5
    except:
        pass
    for _o in d.Objects:
        try:
            if _o.GetType().Name != 'GH_MultiDimensionalSlider':
                continue
            if not str(_o.NickName).startswith('ARTWORK position'):
                continue
            _xi = _o.XInterval
            _yi = _o.YInterval
            _nx = (_cx - _xi.T0) / (_xi.T1 - _xi.T0)
            _ny = (_cy - _yi.T0) / (_yi.T1 - _yi.T0)
            if _nx < 0.0:
                _nx = 0.0
            if _nx > 1.0:
                _nx = 1.0
            if _ny < 0.0:
                _ny = 0.0
            if _ny > 1.0:
                _ny = 1.0
            _o.Value = _rg.Point3d(_nx, _ny, 0.0)
            _o.ExpireSolution(False)
        except:
            pass


out = 'press to centre the artwork on the page'
if press:
    cx = BED / 2.0
    cy = BED / 2.0
    src = 'BED centre (no registration taught)'
    try:
        fh = open(REGFILE)
        reg = json.loads(fh.read())
        fh.close()
        p0 = reg['p0']
        p1 = reg['p1']
        p2 = reg['p2']
        cx = p0[0] + ((p1[0] - p0[0]) + (p2[0] - p0[0])) / 2.0
        cy = p0[1] + ((p1[1] - p0[1]) + (p2[1] - p0[1])) / 2.0 + OFFY
        src = 'PAPER centre'
    except:
        pass
    ghd = ghenv.Component.OnPingDocument()
    if ghd is None:
        out = 'no document'
    else:
        ghd.ScheduleSolution(10, gh.Kernel.GH_Document.GH_ScheduleDelegate(apply_centre))
        out = 'centred on %s -> (%.1f, %.1f)   [set PLACEMENT to "From graph" to use it]' % (src, cx, cy)
print(out)
