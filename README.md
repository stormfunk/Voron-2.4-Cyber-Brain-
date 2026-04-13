# Voron 2.4 350mm - "Cyber Brain"

Klipper configuration for a Voron 2.4 350mm CoreXY 3D printer.

## Hardware

| Component | Detail |
|---|---|
| Frame | Voron 2.4 350mm |
| Controller | BTT Octopus V1.1 |
| Toolhead board | Nitehawk 36 |
| Probe | Cartographer 3D (scan + touch) |
| Extruder | Direct drive |
| Nozzle | Stainless steel, 0.4mm |
| LEDs | 50x GRB Neopixel strip (PB0) |
| Bed plates | Smooth PEI, Textured PEI, CryoGrip |
| Web UI | Mainsail |

## Config Structure



## Key Features

- **Cartographer 3D probe** with scan mode for bed mesh and touch mode for Z calibration
- **Per-plate Z offsets** passed from OrcaSlicer via PRINT_START parameter
- **KAMP** adaptive bed meshing and line purge
- **LED effects** - idle (dim white), heating (red-orange pulse), cooling (blue-aqua pulse), printing (80% white), complete (green flash)
- **Fast QGL** - two-pass quad gantry leveling (coarse then fine)
- **Conditional homing** (_CG28) to skip re-homing when already homed
- **Auto-backup** to GitHub with merge conflict handling
- **Timelapse** support via Moonraker

## Print Start Sequence

1. Heat bed, preheat nozzle to 150C
2. Home, clear bed mesh
3. Cool nozzle if over 150C (for Cartographer touch accuracy)
4. Wait for bed temp, then preheat nozzle
5. Quad gantry level (QGL)
6. Adaptive bed mesh (KAMP)
7. Clean nozzle, Cartographer touch calibration
8. Apply per-plate Z offset
9. Heat to print temp, purge line, start printing
