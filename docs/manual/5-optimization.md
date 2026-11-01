# "Optimization" tab

[← Manual](README.md)

This is where cut plans are made – and where pieces are ticked off while sawing.

![Optimization bars](../screenshot_optimierung_en.png)

## What to cut? – the work list

On the left is everything that can be cut, in three groups:

- **Combined plans** – one entry each (see [Combined plan](#combined-plan)),
- **Cut jobs** – from the [Parts](4-parts.md#cut-jobs) tab,
- **Projects** – expandable if they use several materials, with one line per material.

Every line shows its status:

| Status | Meaning |
|---|---|
| no plan yet | There are open parts but no cutting plan yet |
| plan ready · 0/12 | Plan calculated, nothing cut yet (cut/pieces in the plan) |
| in progress · 5/12 | Cutting is under way |
| plan outdated | Parts or material changed, or parts were cut elsewhere meanwhile |
| in combined plan | This material is cut in the combined plan – a click opens it |
| in cut job … | All open parts are already in this cut job – a click opens it (with several: "in 3 cut jobs", the names are in the tooltip) |
| planned elsewhere | All open parts are already in another plan (e.g. as filler parts) |
| finished | Everything cut (only with "show finished too") |

Search by name or material at the top. Drag the handle between list and plan to change the list's
width; it is remembered. The selection is kept, also when switching tabs. Jumps from
other tabs ("Cut now →", "Continue cutting", "Optimize" on a combined plan) select the matching
entry here.

## On the right: status and one main action

The top right shows the name, material, open parts and pieces. Below it there is always just
**one** blue main action, depending on the status:

| Status | Main action |
|---|---|
| no plan yet | **Calculate cutting plan** |
| plan ready / in progress | **To the saw →** (opens [workshop mode](#workshop-mode)) |
| plan outdated | **Recalculate** – the reason is shown above the plan |
| finished | none – only PDF and labels |

Next to it: **Fill remnants…** (see [Filler parts](#filler-parts)), **PDF export**, **Labels**
and the **More** menu with *Recalculate*, *Mark everything as cut…* (asks first) and
*Discard plan* (releases reserved pieces).

**Restart project** (progress back to 0, plans removed, stock stays) is in the
[Projects](3-projects.md) tab.

If the material of the selected project is also needed in other projects and there is no combined
plan yet, a hint appears: "… is also needed in 'X' – cut together?". **Create combined plan**
creates it with these projects and selects it.

### Settings

When you select an entry, the settings are expanded; collapsed, one line sums them up, e.g.
"Alu chop saw 2.8 mm · Standard · remnants first off":

- **Saw blade** – the material's saw blade is preselected (see [Material](1-material.md)).
  Calculating with a different one makes that the material's new default.
- **Calculation** – for bars **Standard** or **Thorough**, for panels **Fast**, **Standard**
  (guillotine with smart split direction) or **Thorough** (genetic algorithm, takes longer).
- **Remnants first** – plan offcuts first, then full bars/panels.
- **Max. per bar** – at most this many parts per bar, leaves room for filler parts.

Every calculation is saved as a **plan**. The plan reserves its pieces that haven't been started
yet, so other projects don't plan them (can be switched off under Settings → Stock).
Notices appear when parts or material changed since the calculation, or when a planned piece is no
longer in stock (with its code, e.g. "No longer in stock: AP40-07").

### Key figures

One line above the plan: "6 full bars + 2 offcuts · 24 parts · 95 % used · waste 2 %". If parts
don't fit the stock, a red box below lists the missing parts and the shopping list (see
[Material requirements](#material-requirements)).

## The plan

Every bar/panel has a header line: what to take ("Take AP40-07 · Rack Alu"), how many parts are on
it and **where every offcut goes**:

- **back to stock** – from the minimum remnant size on; the largest offcut keeps the board's code
  and is then stored at the material's offcut location,
- **into the offcut bin** – smaller, but above the lower limit, if the offcut bin is switched on
  (see [Stock](2-stock.md#offcut-bin)),
- **throw away** – everything else.

Clicking a part in the plan ticks it off as cut. With the first part of a board, the piece is
deducted from stock, offcuts are booked and scrap goes into the offcut bin. Unticking reverts it.

Bars are drawn **to the same scale** in the plan: the longest fills the width, shorter ones are
correspondingly shorter. Very short bars are drawn a bit wider and then get a dashed outline. The
magnifier and workshop mode show each bar at full width.

## Panels

2D guillotine packing: every cut goes from edge to edge, so offcuts remain rectangles. The
numbered cutting sequence below each plan says exactly where to saw – the saw blade width is
already included.

![Optimization panels](../screenshot_platten_en.png)

## Filler parts

If there is waste at the end of a bar or on a panel, CutStock fills it with parts from other
projects (**Fill remnants…**). It never uses more material. Filler parts are hatched, carry their
project and count for their own project once cut (any extra go to the finished parts).

![Filler parts](../screenshot_fuellteile_en.png)

## Combined plan

If the same material is needed in several projects, a combined plan cuts them together. It is at
the top of the work list; when selected it shows its projects with checkboxes. **Compare** shows
the savings against separate plans, **Calculate cutting plan** calculates the ticked projects
together.
Every project gets its own color; ticked-off parts count in their project. Creating,
renaming, changing members and deleting also works in the [Projects](3-projects.md#combined-plans)
tab, box "Combined plans".

![Combined plan](../screenshot_sammelplan_en.png)

## Material requirements

If the stock isn't enough, CutStock shows a shopping list in the red box; **Add to stock** adds it
right away.

## Workshop mode

**To the saw →** opens the full screen for a tablet at the saw: one bar/panel per page with piece code and location, big
touch targets, progress, "next" marker. New offcuts are shown with their code and can be printed
as labels right away.

![Workshop mode](../screenshot_werkstatt_en.png)

## PDF

Parts list with quantities, material requirements with piece codes and location, identical cutting
patterns combined; every pattern says where its offcuts go.
