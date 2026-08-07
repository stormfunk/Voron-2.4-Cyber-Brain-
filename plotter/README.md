# Voron 2.4 Pen Plotter

A pen plotter that uses a small linear rail, a couple of magnets, some pen
springs and some old nails for very precise and repeatable multi-colour pen
plotting. It's set up to fit the fan mounting holes of my Voron 2.4 archetype
toolhead, but should fit pretty much any printer with slight adjustment to the
mounting holes.

A removable pen toolhead built around the Archetype interface. It replaces the
hotend fan for plotting, a two screw swap, and needs no permanent changes to the
Voron. A short MGN9 rail (left over from a [TAP](https://github.com/VoronDesign/Voron-Tap)
build) constrains the pen carrier, twin springs give compliant drawing pressure,
and a self-centring collet keeps different pen diameters on the same axis.

**This page is the mount**: how it works, what to buy, what to print, how it
goes together. The software that drives it lives in
**[`software/`](software/README.md)** — a Rhino Grasshopper pipeline that turns
linework into multi-pen G-code, plus the Klipper macros for registration, pen
swaps and per-pen calibration.

![assembled pen-plotter mount](hardware/pen_mount/images/assembled-axo.png)

There's a dimensioned assembly drawing in
[`Pen Mount Ortho V3.pdf`](hardware/pen_mount/Pen%20Mount%20Ortho%20V3.pdf), one A3 sheet
with the orthographic views, balloons against the parts list and a titleblock.
Worth having open while you assemble, and it's the reference to check a printed
part against if something doesn't seat.

It's specific to the Archetype toolhead. Not a general-purpose adapter, and it
won't fit a stock Stealthburner or a Dragon Burner without rework.

---

## Mechanism

1. **Archetype interface.** The purple rear bracket shows the current archetype
   hotend mount I'm using (Mjolnir configuration with Rapido Ultra UHF).
2. **Linear guidance.** The 50 mm MGN9 rail and MGN9H carriage are the same
   parts the Voron TAP nozzle-levelling design uses. They allow only vertical
   pen motion, which keeps out the lateral play that shows up as doubled or
   offset lines.
3. **Compliant pressure.** Two compression springs preload the moving carrier.
   Klipper commands nominal Z contact and the springs absorb bed and paper
   variation. Pressure modulation is just a little more Z compression.
4. **Repeatable pen axis.** The split collet closes concentrically around the
   barrel as the threaded lock nut tightens, so different barrel diameters stay
   centred instead of being pushed against one side of a clamp.
5. **Fast changes and calibration.** A magnetic quick release makes multi-pen
   swaps tool-free, and the software stores a separate XYZ datum per pen to
   correct length and small re-seating differences.

The pen tip sits roughly **52 mm in front of the nozzle datum**. Grasshopper
works in pen coordinates throughout and only applies that offset when G-code is
written.

![exploded axonometric view](hardware/pen_mount/images/exploded-axo-front.png)

<p align="center">
  <img src="hardware/pen_mount/images/exploded-axo-reverse.png" alt="reverse exploded axonometric view" width="49%">
  <img src="hardware/pen_mount/images/exploded-side.png" alt="exploded side view" width="49%">
</p>

### Why it's built this way

**Magnetic quick release.** The pen carrier is held on magnetically, so a pen
change is a pull and a push rather than screws. A plot with four pens stops four
times, and any fastener that needs a tool turns each of those into a chance to
nudge the machine.

**Linear bearing from the Voron TAP system.** Known-good, widely available, and
no play in the direction that matters.

**Sprung on the rail.** Pen springs sit on the rail so the pen floats under
constant force instead of being driven to a hard Z. It tracks paper that isn't
perfectly flat, and a small Z error turns into a small pressure change rather
than a crash or a skipped line. `pen_down_z` sets nominal contact and the spring
absorbs the rest.

That spring is why the GCODE component has a `preload` parameter. At draw height
the tip is pressed about 1 mm into the paper by spring compression, so **travel
hop has to exceed the preload** or the pen never leaves the page and drags a
line through every travel move. 4 mm is a sane hop.

**Self-centering collet.** Pens of different barrel diameters land on the same
axis instead of leaning to whichever side a clamp pushes them. Without it every
pen change is also a lateral datum change, and the tool table can't correct for
that because it stores an offset per pen, not per insertion.

**Frog face on top.** No function. It is a small frog. It is on top.

![collet and lock-nut detail](hardware/pen_mount/images/collet-detail.png)

---

## Bill of materials

> **Complete download:** [Pen Holder QR V3: Collet Update](https://github.com/stormfunk/Voron-2.4-Cyber-Brain-/releases/tag/pen-holder-qr-v3.0.0)
> contains the full printable set as one ZIP.

| Qty | Part | Specification / repository file | Purpose |
|---:|---|---|---|
| 1 | Archetype toolhead interface | Existing Archetype mount; purple part shown above | Fixed connection to the Voron toolhead |
| 1 | Linear rail | MGN9, 50 mm long, as used by the Voron TAP nozzle-levelling design | Vertical guide |
| 1 | Linear carriage | MGN9H, matching the Voron TAP carriage | Low-play moving bearing block |
| 2 | Compression springs | Approx. 4.4 mm OD × 25.5 mm free length in the CAD | Compliant pen preload |
| 2 | Guide fasteners | Approx. M2.5 × 50 mm in the CAD; verify against printed holes | Spring and carrier guidance |
| 1 pair | Neodymium magnets | Size to suit the modelled quick-release pockets (10mm x 4mm) | Repeatable, tool-free carrier attachment |
| 1 set | M3 mounting hardware | Lengths to suit the Archetype interface and MGN9 rail | Rail and bracket fastening |
| 1 | Rail mount | [`01_Linear Rail Mount.stl`](hardware/pen_mount/01_Linear%20Rail%20Mount.stl) | Fixed rail support |
| 1 | Moving carriage body | [`02_Linear Rail Carriage.stl`](hardware/pen_mount/02_Linear%20Rail%20Carriage.stl) | Spring-loaded carrier body |
| 1 | Collet holder | [`03_Collet Holder.stl`](hardware/pen_mount/03_Collet%20Holder.stl) | Threaded housing for the collet system |
| 1 | Collet lock nut | [`04_Collet Lock Nut.stl`](hardware/pen_mount/04_Collet%20Lock%20Nut.stl) | Closes and locks the collet |
| 1 | Default collet | [`Collet Default.stl`](hardware/pen_mount/Collet%20Default.stl) | **Start here. Fits most pens** |
| Optional | Sized collet | [5 mm](hardware/pen_mount/Collet%205mm.stl), [7 mm](hardware/pen_mount/Collet%207mm.stl), [9 mm](hardware/pen_mount/Collet%209mm.stl), [11 mm](hardware/pen_mount/Collet%2011mm.stl), [13 mm](hardware/pen_mount/Collet%2013mm.stl), or [15 mm](hardware/pen_mount/Collet%2015mm.stl) | For a known barrel diameter. Print only the size you need |
| 1 | Pen or marker | Use the default collet first; switch to a labelled size only when needed | Drawing cool shit |

The spring, magnet and fastener dimensions reflect the current CAD. Check the
printed pockets and holes before ordering if you've changed slicer compensation
or exported the geometry yourself.

---

## Printing

The V3 export uses functional filenames. For a normal build, print the four
numbered core parts plus `Collet Default.stl`, which should fit most pens. The
5–15 mm labelled collets are alternatives for a known barrel diameter, not
additional parts you need. Sizes below are the measured STL bounding boxes,
handy for plate layout:

| File | Part | Qty | Triangles | Bounding box (mm) |
|---|---|---:|---:|---|
| `01_Linear Rail Mount.stl` | Rail mount | 1 | 3,020 | 34.3 × 17.7 × 68.8 |
| `02_Linear Rail Carriage.stl` | Moving carriage body | 1 | 3,238 | 35.0 × 17.0 × 34.6 |
| `03_Collet Holder.stl` | Collet holder | 1 | 13,888 | 35.0 × 36.9 × 34.6 |
| `04_Collet Lock Nut.stl` | Collet lock nut | 1 | 11,728 | 33.1 × 33.1 × 22.7 |
| `Collet Default.stl` | General-purpose collet | 1 | 2,700 | 22.4 × 22.4 × 30.6 |
| `Collet 5mm.stl` | Fixed-size collet | Optional | 3,150 | 22.3 × 22.3 × 30.6 |
| `Collet 7mm.stl` | Fixed-size collet | Optional | 2,734 | 22.3 × 22.3 × 30.6 |
| `Collet 9mm.stl` | Fixed-size collet | Optional | 2,702 | 22.3 × 22.3 × 30.6 |
| `Collet 11mm.stl` | Fixed-size collet | Optional | 2,790 | 22.3 × 22.3 × 30.6 |
| `Collet 13mm.stl` | Fixed-size collet | Optional | 2,798 | 22.3 × 22.3 × 30.6 |
| `Collet 15mm.stl` | Fixed-size collet | Optional | 2,798 | 22.3 × 22.3 × 30.6 |

---

## Datums

The tool table stores an XYZ datum per pen, measured by touching the tip to the
calibration dot. That covers pens being different lengths and sitting at
different depths, but it's one offset per pen, not per insertion, so the mount
has to make re-seating repeatable on its own. Across a pen-out / home / QGL /
pen-in cycle the same pen came back to within 0.6 mm.

Pen 1 is the datum everything else is measured against, so re-seating pen 1
shifts the lot with nothing to compensate. If absolute position matters,
re-touch the dot after fitting it.

`toolhead draw height` in the GCODE component has to equal pen 1's stored datum.
The tool table only holds differences between pens, so how far the mount holds a
pen below the nozzle lives in that one number. Change the mount and you have to
update it, or nothing touches the paper.

Calibrating a pen is a software procedure. It's covered in the
[pen tool table](software/README.md#pen-tool-table) section of the main README.
