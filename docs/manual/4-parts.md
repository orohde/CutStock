# "Parts" tab

[← Manual](README.md)

This tab shows everything your projects **still need to have cut** – sorted by material, because
you always cut one material at a time. Here you pick parts from different projects and cut them
together.

![Parts](../screenshot_teile_en.png)

## Open parts

- The top line shows how many pieces in how many projects are still open.
- One group per material (expand/collapse) with the number of parts and pieces and a rough stock
  estimate: **Enough stock** or **About n bars/panels short**. The estimate only adds up length or
  area; the optimization gives the exact answer.
- Filter by material and project. Finished parts are hidden ("show finished too").
- The project name links to the project.

Below the project name you see what is already happening with the part:

- **in combined plan …** – this project's material is cut in a combined plan; the part can't be
  selected here. A click selects the combined plan.
- **n in cut job "…"** – that many pieces are already in a cut job. The "open" column then shows
  how many are still free.
- **n planned as filler parts** – lies uncut in another project's plan.
- **n finished parts · use** – see below.

## Cut now

Tick parts – the quantity ("cut") is preset to everything still free and can be changed. A bar
with the selection appears at the bottom:

- **Cut now →** creates a **cut job** and jumps straight to the
  [Optimization](5-optimization.md), which calculates it right away.
- **Cut into remnants of …** takes the parts along as filler parts in another project's plan
  (see [Optimization → Filler parts](5-optimization.md#filler-parts)). This only works with parts
  of one material.

Cut parts count **directly for their own project**. Only what is cut beyond the open quantity
goes to the **finished parts**.

## Cut jobs

Running cut jobs are listed at the top of the tab with their progress ("3 of 5 cut"),
**Continue cutting** (opens the optimization) and **Delete**. Anything already cut stays booked to
the projects when a job is deleted. Once a job is fully cut, CutStock offers to delete it. In the
optimization, cut jobs appear in the project selection, not in the Projects tab.

## Finished parts

Finished parts in stock that no project has counted yet – e.g. because more was cut than was
open. Once the part has open pieces again, **use** counts them as cut (here or in the plan in the
Optimization tab). They can be corrected by hand in the "Edit part" dialog (Projects tab).
