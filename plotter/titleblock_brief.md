# Design Brief — Parametric Plotter Titleblock

## What this is for

A titleblock that gets drawn by a **pen plotter** (a Voron 2.4 running a fibre-tip
pen instead of a hot end) at the edge of an A4-ish sheet, beneath generative
linework artwork. It will be rebuilt parametrically in Grasshopper afterwards,
so the design needs to be *measurable and modular*, not a flat picture.

Deliver **vector SVG**. Everything is drawn as a line by a physical pen — there
is no fill, no raster, no gradient. Think of it as instructions for a plotter
arm, not pixels.

## Hard technical constraints (these are not stylistic preferences)

- **Strokes only. No filled shapes.** A "solid black rectangle" must be drawn as
  hatching (parallel lines) or crosshatch. If you want a dense area, draw it as
  closely-spaced parallel lines and say so.
- **Pen width is 0.45 mm.** Design at that nominal stroke weight. Two lines
  closer than ~0.5 mm merge into one blob of ink and are wasted plot time.
- **Minimum feature size ~1 mm.** Anything finer disappears into the nib.
- **Text**: strongly prefer **single-stroke / engraving-style lettering**
  (Hershey, stick fonts) over outlined typefaces. If you use outlined type,
  cap height must be ≥ 4 mm and it will be drawn as hollow outlines — which
  actually suits the aesthetic, so that is a valid choice for headline text.
- **Up to 3 ink colours**, each a separate pen: default **black + orange/amber
  + one accent**. Put each colour on its own named SVG layer. Colour is
  expressed by pen choice, not by shading.
- **Keep the ink budget modest.** The titleblock should not take longer to draw
  than the artwork above it. Rough target: under ~8 m of total line length.
- Pure 2D, flat-on. No perspective, no drop shadows, no glow, no transparency,
  no anti-aliasing effects, no bitmap textures.

## Size and layout behaviour

- Design to a **180 × 40 mm** horizontal strip sitting along the bottom of the
  sheet, with a 10 mm margin from the paper edge.
- It must **scale proportionally to different paper sizes**, so build it on a
  clear proportional grid and avoid anything that only works at one exact size.
- Tell me which elements are **pinned to which edge** (e.g. "title block pinned
  left, status bar stretches to fill, code stamp pinned right") so the
  parametric version can stretch correctly rather than scaling everything
  uniformly.

## Aesthetic direction

**Neon Genesis Evangelion computer-UI / MAGI terminal.** Low-resolution CRT
sci-fi: the look of a 1990s anime imagining a 2015 supercomputer.

Language to hit:
- Rigid **rectangular framing** — nested boxes, thick outer rules against
  hairline inner divisions, hard corners, no rounded edges anywhere.
- **Extreme typographic contrast**: very large condensed all-caps headline text
  next to tiny dense monospaced data rows.
- Wide letterspacing on labels. Type set in strict horizontal bands.
- **Japanese katakana or kanji as secondary annotation** alongside English —
  small, in the margins, as texture and labelling.
- Deadpan technical language: `ANALYSIS`, `PATTERN`, `CODE`, `STATUS`,
  `SYNC RATIO`, `REC`, numeric IDs, timestamps.
- **Warning/caution motifs** — hazard triangles, striped bars (drawn as diagonal
  hatch), crosshairs, reticles, target brackets, corner registration marks.
- Bars, ticks, scales, and gauge-like readouts that imply live telemetry.
- Asymmetry and information density: it should look like a functioning readout,
  not a tidy drafting stamp.

⚠️ **Evoke, don't copy.** Do not reproduce the NERV logo, the fig-leaf mark, or
any actual trademark from the series. Invent original marks in the same visual
language.

Because it's drawn in ink on paper, lean into what suits linework: hatching
where a screen would use flat colour, outlines where a screen would use solid
type, and the natural "scanline" quality of parallel ruled lines.

## Content it must contain

Static labels plus placeholder values (I will substitute the values
parametrically, so put the *changeable text* on its own layer):

| Field | Example placeholder |
|---|---|
| Artwork title | `PATTERN-07 / LAKE RIPPLES` |
| Date | `2026.07.21` |
| Sheet / plot number | `PLOT 014` |
| Scale | `1:1` or `FIT 83%` |
| Paper size | `A4 / 295 × 205` |
| Pen list | up to 4 rows: number, colour name, line weight |
| Plot duration | `EST 27.3 MIN` |
| Maker's mark | `JC` |
| A decorative code stamp | e.g. `MAGI-02 / SYS.OK` |

Include a couple of purely decorative telemetry elements (a bar gauge, a small
grid, a reticle) — they carry the aesthetic and give me modular pieces to reuse.

## Deliverable

- **SVG**, millimetre units, artboard exactly 180 × 40 mm.
- **Named layers/groups**, at minimum:
  - `FRAME` — outer and inner rules
  - `LABELS` — static text (field names)
  - `VALUES` — placeholder dynamic text (I will replace these)
  - `GRAPHICS` — reticles, hazard marks, gauges, decorative elements
  - `HATCH` — any area drawn as parallel-line shading
  - one layer per ink colour if using more than one pen
- Keep strokes as **open paths where possible**; avoid stacking duplicate
  coincident lines.
- A short note listing the **proportional rules** (what stretches, what stays
  fixed, what pins to which edge).

## One-line summary

An Evangelion MAGI-terminal titleblock, drawn entirely in pen strokes:
hard rectangular framing, huge condensed caps against tiny dense data rows,
katakana annotations, hazard hatching and reticles — technical, high-contrast,
and unmistakably CRT.
