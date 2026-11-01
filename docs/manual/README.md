# CutStock – Manual

The manual is split by the tabs of the user interface. Each page describes one tab:
what you see there, what you do there and the terms that go with it.

| Key | Tab | What for |
|-----|-----|----------|
| 1 | [Material](1-material.md) | Create materials, stock per material, defects, labels |
| 2 | [Stock](2-stock.md) | Manage storage locations, see what is where, take pieces out, offcut bin |
| 3 | [Projects](3-projects.md) | Projects and their parts |
| 4 | [Parts](4-parts.md) | Open parts of all projects, cut jobs, finished parts |
| 5 | [Optimization](5-optimization.md) | Calculate cut plans, saw, tick off, PDF, workshop mode |
| 6 | [Settings](6-settings.md) | Language, units, labels, stock, REST API, backup, saw blades |

For programs, scanners and machines: [REST API](api.md).

## Desktop app: in the browser, but local

The desktop app (macOS, Windows) opens in your default browser. It is not an online service:
CutStock runs entirely on your own computer, the browser only shows the interface. No internet
connection is needed, and your data stays on your computer (on the Mac optionally synced between
your Macs via iCloud). To quit, use the "Quit" button at the top right.

## Terms

- **Material** – a raw material, e.g. "Alu profile 40x40" (bar) or "MDF 19 mm" (panel).
- **Short code** – short name of the material used in piece codes, e.g. `AP40`.
- **Piece** – a single board, bar or panel in stock, with a code like `AP40-07`.
  The code is on the label or written onto the material.
- **Offcut (remnant)** – a piece left over after sawing that is at least the material's minimum
  remnant size. Offcuts go back to stock and keep the code of their board.
- **Scrap** – anything smaller than the minimum remnant size. It is thrown away or, if switched
  on, kept without a code in the **offcut bin**.
- **Location** – where a material is stored (rack, cart, box). Every material has exactly one,
  plus optionally a location of its own for its offcuts.
- **Plan** – the saved result of an optimization for one project and one material.
  A plan reserves the pieces it intends to use.
