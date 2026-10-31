# "Stock" tab

[← Manual](README.md)

The **Stock** tab answers the question "What is where?". On the left are the storage locations,
on the right the contents of the selected location. Adding and changing stock still happens in
the [Material](1-material.md) tab – this tab is about the locations and what is stored there.

## Locations

Locations are a fixed list (rack, panel cart, offcut box …). Every material is stored at exactly
**one** location, and all its pieces are there. Optionally a material gets its own **location for
offcuts** – in practice, offcuts from sawing are often kept somewhere else than full lengths
(bars on the wall, offcuts in the box below).

- **New** creates a location.
- **Rename** (or double-click) changes the name in one step – all materials show the new name.
- **Delete**: an empty location is deleted right away. If material is still stored there,
  CutStock asks where it should go instead. The last location cannot be deleted.

There is always at least one location; on first start CutStock creates "Stock".

Which location belongs to a material is set in the material dialog (Material tab → Edit →
*Storage location* and *Storage location for remnants*). It also offers **"+ New location …"** to create a location
right while creating a material.

## Contents of a location

On the right are the materials at the selected location, per size with quantity and piece codes.
"offcuts only" means only the offcuts of that material are stored here (its offcut location).
Pieces marked 🔒 are reserved by a saved plan.

- **Click a code** to open the piece: change its note or **Take out …**
- **Go to material** jumps to that material in the Material tab.
- **Labels** prints one label per piece at this location – handy for relabelling a rack.

## Taking a piece out

If a piece leaves stock without a plan (sold, used for something else, defective), open it and
choose **Take out …** with a reason:

| Reason | Meaning |
|--------|---------|
| Used | used for something else |
| Sold / given away | has left the workshop |
| Defective, disposed of | unusable, thrown away |
| Into the offcut bin | now kept without a code in the offcut bin (if switched on) |

If the piece is reserved by a plan, CutStock tells you – the person decides. If it is taken out
anyway, the plan then shows "No longer in stock: AP40-07 – consider optimizing again".

When sawing by plan you don't need to take anything out: ticking pieces off in the
[Optimization](5-optimization.md) tab deducts the piece and books the offcuts.

## Offcut bin

Pieces smaller than the material's minimum remnant size are normally thrown away. With
**Settings → Stock → "Keep offcuts in the offcut bin"** CutStock keeps them in the offcut bin
instead – as an overview, in case a project with small parts comes along.

- **Lower limit** ("Only offcuts from …"): smaller pieces are still thrown away.
  For panels the narrower side counts.
- Scrap has **no code** and no label, only material, size and quantity. In the workshop you simply
  write the length on the piece.
- Optimization does **not** use the offcut bin.
- The cut plan and the PDF say for every offcut where it goes: *back to stock*,
  *into the offcut bin* or *throw away*.
- **Take 1** takes one piece out of the bin, **Throw away** empties it for one material,
  **Empty bin** empties it completely.
- In the Material tab, "+ n in the offcut bin" is shown above the stock if there is something of
  that material in the bin.

Switching it off keeps the contents; the bin is shown as long as something is in it.

## Stock journal

Every stock booking is recorded – receiving, taking out (with reason), sawn by plan, offcut booked,
scrap, changes to locations – no matter whether it comes from the interface or via the
[REST API](api.md). The journal is currently available via the API (`GET /api/journal`).
