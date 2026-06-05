# CutStock

**Minimize waste. Maximize every board, bar, and panel.**

CutStock is a desktop application for cut optimization (Verschnittoptimierung) that helps woodworkers, makers, and small workshops get the most out of their material. Whether you're cutting panels for a bookshelf or bars for a frame -- CutStock calculates the optimal cutting layout, tracks your stock, and exports print-ready cut plans as PDF.

![CutStock Optimization](docs/screenshot_platten.png)

> **[Deutsche Version](README.de.md)**

## Features

- **1D + 2D Optimization** -- bars (1D bin-packing) and panels (2D guillotine packing) with saw blade kerf
- **Three Algorithms** -- Fast (Greedy), Nested Guillotine (smart split direction), Thorough (Genetic Algorithm, ~95% utilization)
- **Grain Direction** -- respects wood grain per material and part (lengthwise, crosswise, or any)
- **Edge Trimming** -- configurable trim margin for damaged board edges
- **Stock Management** -- track inventory, auto-deduct used pieces, auto-add usable remnants
- **Project Management** -- organize parts by project, import/export as JSON
- **Visual Cut Plans** -- color-coded cutting diagrams with labels and dimensions
- **PDF Export** -- compact multi-page layout (2-column for bars, proportional for panels)
- **Print Preview** -- opens PDF in your system viewer before saving
- **Statistics** -- detailed waste analysis per stock piece and totals
- **Backup/Restore** -- full database + settings as ZIP
- **Multi-language** -- English, Deutsch, Francais, Italiano
- **5 Color Themes** -- Standard, Dark, Light, Blue-Grey, Warm
- **Cross-platform** -- macOS (.app), Windows (.exe), Linux
- **iCloud Sync** -- database and settings sync between Macs automatically

## Screenshots

### Material & Stock

Manage materials (panels, bars) with thickness, cross-section, grain direction, edge trim, and minimum remnant thresholds. Stock pieces are shown for the selected material.

![Material & Stock](docs/screenshot_material.png)

### Projects

Organize parts by project. Each part has a label, type, material, dimensions, quantity, and grain direction. Import/export projects as JSON.

![Projects](docs/screenshot_projekte.png)

### Optimization -- Bars

Select a project, material, saw blade, and algorithm. The optimizer calculates the best cutting layout and displays color-coded cut plans with statistics.

![Optimization Bars](docs/screenshot_optimierung.png)

### Optimization -- Panels

2D guillotine packing for panels. All cuts go edge-to-edge, keeping every remnant rectangular and reusable.

![Optimization Panels](docs/screenshot_platten.png)

### Settings

Configure language, color theme, unit (mm/cm), saw blades, and backup/restore.

![Settings](docs/screenshot_einstellungen.png)

## Algorithms

CutStock solves the classic [Cutting Stock Problem](https://en.wikipedia.org/wiki/Cutting_stock_problem) using three approaches:

### Why Guillotine Cuts?

All CutStock algorithms use **guillotine cuts** -- every cut goes completely from edge to edge. This is a deliberate choice:

| Approach | Material Utilization | Remnants | Required Tools |
|----------|---------------------|----------|----------------|
| **Guillotine** (CutStock) | ~85-95% | Always rectangular | Table saw, circular saw |
| **Free-Cut** | ~93-98% | L-shaped, T-shaped | CNC router required |

Guillotine cuts can be made with any standard saw. The remnants are always clean rectangles that can be stored and reused. The 5-10% better utilization of free-cut algorithms requires a CNC router and produces irregular remnants that are difficult to reuse -- not practical for most workshops.

### 1D -- Bars / Profiles

- **Fast (Greedy FFD):** First-Fit-Decreasing -- sorts parts by length, places each on the first bar that fits. Instant results.
- **Thorough (GA):** Genetic Algorithm -- evolves 80 permutations over 200 generations to find better combinations.

### 2D -- Panels / Boards

- **Fast (Greedy):** Best-Area-Fit guillotine packing. Always splits horizontally first (right + below).
- **Nested Guillotine:** Same as Greedy but tests **both split directions** (horizontal and vertical) at each cut and picks the one that creates the largest usable remnant. Better results on complex layouts with asymmetric parts.
- **Thorough (GA):** Genetic Algorithm -- optimizes both placement order and rotation decisions across 200 generations. Best results but takes 2-5 seconds.

### All algorithms respect:

- **Saw blade kerf** -- subtracted at every cut
- **Edge trimming** -- damaged edges removed before cutting
- **Grain direction** -- parts placed only in orientations that match the wood grain
- **Finite stock** -- uses smallest/remnant pieces first, reports parts that don't fit

## Download

Pre-built binaries for macOS and Windows are available on the [Releases page](https://github.com/orohde/CutStock/releases).

> **Important: Unsigned builds**
>
> The releases are **not code-signed** (no paid Apple/Microsoft developer certificate).
> Your operating system will show a security warning on first launch:
>
> - **macOS**: Right-click the app, select "Open", then click "Open" again to bypass Gatekeeper
> - **Windows**: Click "More info", then "Run anyway" to bypass SmartScreen
>
> This is normal for open-source software. The source code is fully available for review.

## Installation (from source)

### Prerequisites

- Python 3.12+
- macOS, Windows, or Linux

### Setup

```bash
git clone <repository-url>
cd CutStock
./setup.sh        # Creates venv, installs dependencies
```

### Run (Development)

```bash
./run.sh
```

### Build Standalone App

**macOS:**
```bash
./build.sh         # Creates dist/CutStock.app
```

**Windows:**
```bat
build_windows.bat   # Creates dist\CutStock\CutStock.exe
```

## Data Storage

| File | macOS | Windows |
|------|-------|---------|
| Database | `iCloud Drive/CutStock/cutstock.db` | `%APPDATA%\CutStock\cutstock.db` |
| Settings | `iCloud Drive/CutStock/settings.json` | `%APPDATA%\CutStock\settings.json` |

On macOS, the database and settings sync automatically via iCloud Drive between Macs. A heartbeat-based lock mechanism prevents concurrent access.

## Tech Stack

- **Python 3.12+** -- application logic
- **PySide6 (Qt 6)** -- cross-platform GUI
- **SQLite** -- local database (no server needed)
- **reportlab** -- PDF generation
- **PyInstaller** -- standalone app packaging

## Project Structure

```
CutStock/
  core/
    db.py          -- SQLite schema + repository pattern
    models.py      -- dataclasses (Material, Stock, Project, Part, ...)
    optimize.py    -- 1D/2D optimization algorithms (Greedy + GA)
    pdf.py         -- PDF export with cut plan drawings
    lock.py        -- iCloud-safe file locking
    settings.py    -- JSON-based settings
  ui/
    main_window.py -- main window with tabs
    tab_material_lager.py -- material + stock management
    tab_projekt.py -- project + parts management
    tab_optimierung.py -- optimization + visualization
    tab_einstellungen.py -- settings + saw blades + backup
    i18n.py        -- translations (EN/DE/FR/IT)
    units.py       -- mm/cm unit conversion
  tests/
    test_optimize.py -- algorithm tests
  assets/
    icon.jpg/icns/ico -- app icon
  run.py           -- entry point
```

## License

**CC BY-NC-SA 4.0** -- free for personal use, no commercial use, attribution required.

See [LICENSE](LICENSE) for details.

## Contributing

Contributions welcome! Please open an issue first to discuss what you'd like to change.

When adding a new language, see `ui/i18n.py` -- just add your language code to `LANGUAGES` and a translation for each key in `TRANSLATIONS`.
