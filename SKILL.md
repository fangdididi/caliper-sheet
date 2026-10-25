---
name: caliper-sheet
description: Turn a real physical part you can hold (a broken clip, a bracket, a knob, a spacer, a mount) into a checked, true-scale dimensioned drawing that someone can print, machine or order from. Use when the user wants to measure an object to remake, 3D print, replace or commission it, or asks for a "drawing", "spec" or "measurements" of a physical thing.
---

# Caliper Sheet

**Languages:** English | [中文](SKILL.zh-CN.md)

## What this is

Caliper Sheet is a measuring workflow for physical parts. You start with an object on the desk and end with three things:

1. a **measurement log** (`part.json`) where every size has a code, a role, the tool it came from and the raw readings;
2. a **check report** that says, per size, whether the numbers can be trusted, and gives one verdict for the whole part: `READY`, `DRAFT_ONLY` or `MEASURE_AGAIN`;
3. a **one-page drawing** (SVG, third-angle projection) printed at true scale, so the user can lay the real part on the paper and see whether the drawing matches before anyone cuts material.

## The problem it solves

When people measure a part to remake it, the mistakes are boring and expensive:

- one caliper reading is trusted, but the jaws were tilted or the plastic squashed;
- a ruler is used on a size that has to fit within a tenth of a millimetre;
- sizes are measured edge-to-edge in a chain, the small errors add up, and the holes end up in the wrong place;
- an old part is really in inches, so 12.7 gets "rounded" to 13 and nothing fits;
- a size nobody could reach (a hidden flat, an internal undercut) is quietly guessed;
- the drawing looks fine on screen but was never compared to the real object.

This skill makes each of those mistakes visible before they become scrap.

## When to use it

Use it when the user:

- wants to replace a broken or lost part and has the old one (or its mate);
- wants to 3D print, laser cut, CNC or hand-make a copy or an adapter;
- needs to send measurements to a workshop, a seller or a friend with a printer;
- asks to "measure this", "make a drawing of this", "what size is this hole".

Do not use it for things the user cannot physically hold or measure (a building, a part known only from a photo of a listing). For those, say plainly that the result would be a guess and offer a photo-based estimate marked as such.

## What you need

- The part, and its mating part if there is one (the shaft a knob sits on, the rail a clip snaps to).
- A measuring tool. A digital caliper (0.01–0.02 mm) is the default. A steel ruler (0.5 mm) or tape (1 mm) is fine for free sizes only.
- Python 3.8+ to run `scripts/partsheet.py` (standard library only). The workflow still works by hand without it.

## Step by step

### 1. Write the part card

Ask, in one short message, only what changes the drawing:

- What is it and what does it attach to?
- What will be made from the drawing: a print, a machined part, a bought replacement, or only a record?
- Which surfaces touch other parts? Those are the sizes that matter.
- Units the user thinks in, and which tools they actually have.

Record it in `part.json` under `part` (`id`, `name`, `units`, `purpose`, `material`).

### 2. Pick datums before measuring

Choose up to three reference faces, usually the flat face the part sits on (A), a straight edge (B), and a perpendicular edge or a hole centre (C). Measure positions **from a datum** (X1 = datum A to hole 1, X2 = datum A to hole 2), not from feature to feature. Chained edge-to-edge sizes stack their errors; datum sizes do not. Use chains only as a cross-check (step 5).

### 3. Give every size a code and a role

Codes keep the drawing clean and let you write formulas:

| Prefix | Meaning |
|---|---|
| `L`, `W`, `T` | overall length, width, thickness |
| `X`, `Y` | position from a datum |
| `D` | diameter (holes, bosses, shafts) |
| `R` | radius |
| `P` | pitch between repeated features |
| `S` | other spacing |
| `F` | across-flats size (D-shafts, hex) |

Roles set the tolerance used for every check (change them in `tolerances` if the job needs it):

| Role | Default | Meaning |
|---|---|---|
| `mating` | ±0.1 mm | touches or locates another part |
| `clearance` | ±0.3 mm | must not hit anything, small slack is fine |
| `free` | ±0.5 mm | cosmetic or non-critical |

### 4. Measure three times, record raw readings

For each size, take three readings, re-seating the tool each time (close the jaws, open, re-place, read). Write all three into `readings`. Do not average in your head; the script takes the median and the spread.

Tips that save the most re-work:

- Zero the caliper with the jaws closed before each session.
- Use the jaw flats for outside sizes, the knife tips for inside sizes, the depth rod for depths.
- Soft plastic: close the jaws until they just touch, do not squeeze.
- Holes: measure at three angles; the spread tells you if the hole is worn oval.
- If a size cannot be reached, write `"tbd": true`. Never guess a hidden size.

Sizes that follow from others go in as formulas (`"formula": "X1 + P1"`, `"formula": "W1 / 2"`), using only codes, numbers, `+ - * /` and brackets.

### 5. Run the check

```bash
python3 scripts/partsheet.py check part.json
```

It reports, per size:

- `REMEASURE`: the readings disagree by more than three times the tool's resolution (or 0.05 mm). Measure again; something moved.
- `TOOL_TOO_COARSE`: the tool reads more coarsely than half the tolerance (a ruler on a mating size). Use a better tool.
- `FEW_READINGS`: a mating size has fewer than three readings.
- `TBD_ON_MATING` and `DERIVED_TBD`: a size that matters is unknown.
- `NON_POSITIVE`: a formula gives zero or less, usually a wrong formula.

And hints, which never change a value:

- `IMPERIAL?`: the size sits on a 1/64-inch grid but not on a half-millimetre grid (12.70 is 1/2 in). Ask whether the part is imperial before rounding anything.
- `LOOKS_LIKE`: a hole matches a standard metric clearance hole or tap drill (3.4 is an M3 normal-fit clearance hole). Mention it; let the user decide whether to snap to it.

Chains (`"chains"`) add up their parts and compare with the measured overall size: `CLOSES` within the root-sum-square of the tolerances, `LOOSE` within the worst case, `CLOSURE_FAIL` beyond it. A failed chain means at least one size in it is wrong.

The verdict:

- `MEASURE_AGAIN` (exit code 2): a mating size has a blocking flag, or a chain fails. Do not draw for manufacture yet.
- `DRAFT_ONLY`: everything measured is sound, but a mating size is still TBD. Draw it, label it a draft.
- `READY`: draw it.

### 6. Draw the sheet

```bash
python3 scripts/partsheet.py svg part.json -o sheet.svg
python3 scripts/partsheet.py table part.json > dimensions.md
```

`body` names the codes of the bounding block (`L`, `W`, `T`); `features` lists holes (`d`, `x`, `y`, `through` or `depth`) and slots (`x`, `y`, `len`, `w`). The sheet has top, front and right views in third-angle projection, dimension lines labelled with codes, a value table, a title block with scale and verdict, and a 50 mm check bar. Parts that fit stay at 1:1; large parts drop to 1:2, 1:5 or 1:10; parts under 15 mm are enlarged.

For shapes the script cannot draw (curves, bosses, ribs), keep the measurement log and checks, and draw the sheet by hand or in CAD using the same codes and table. The log stays the source of truth.

### 7. Prove it on paper

Print the SVG at 100 % (no "fit to page"). Measure the check bar with the same caliper: it must read 50 mm times the scale. Then lay the real part on the 1:1 views. Edges and holes should line up within the role tolerance. If they do not, find the size, re-measure, re-run.

### 8. Hand it off

Give the user: the sheet, the dimension table, the verdict, every open flag in plain words, and "make notes" that are separate from the measured values, for example "FDM prints holes about 0.2 mm small; enlarge D1 in the slicer model, not on this drawing." Measured values describe the object; make notes describe the process.

## Examples

**Shelf bracket plate (READY).** Two M3 holes, measured from datum A, pitch 60 mm. The chain X1 + P1 + S1 closes against L1 within 0.04 mm. The only flag is a ruler used on a free size, which is allowed. The hole matches an M3 normal-fit clearance hole. See `examples/shelf-bracket.json` and `examples/shelf-bracket.svg`.

**Dryer knob insert (MEASURE_AGAIN).** The D-shaft bore readings are 6.12, 6.38 and 6.05: the spread of 0.33 mm shows a worn or oval bore, so measure the shaft instead. The flat size is TBD. The outer sizes land on 3/4 in and 1/2 in, so the part is probably imperial; ask before rounding. See `examples/knob-insert.json`.

## Rules

- Never invent a size. Unknown is `[TBD]`.
- Never round away a reading the user gave; snapping to a standard is a suggestion the user accepts.
- Never silently convert units; flag possible inches and ask.
- Keep measured values and make allowances separate.
- A drawing that has not been compared with the real part on paper is a draft.
