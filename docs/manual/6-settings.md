# "Settings" tab

[← Manual](README.md)

The groups are on the left, the settings of the selected group on the right. Below every setting
one line explains what it does. Settings that depend on another one are greyed out while that one
is off (e.g. "Only offcuts from" without the offcut bin). Changes apply immediately, there is no
save button.

![Settings](../screenshot_einstellungen_en.png)

| Group | Settings |
|---------|---------------|
| General | Language (Deutsch, English, Français, Italiano), unit (mm, cm, decimal inches, fractional inches), colour scheme (auto, light, dark) |
| | **Fractional inches** – rounded to 1/16", optionally shown as feet and inches from 12" (`2' 1/4"`). You can type `1 3/4`, `1-3/4"`, `2' 1/4"` or `8ft`. Everything is stored in millimetres |
| Sawing | Saw blades with name and kerf; which one a material uses is set on the [material](1-material.md) |
| Stock | **Saved plans reserve their material** – planned pieces are not planned by other projects |
| | **Number lock period** – freed piece numbers are reused only after this many days (0 = right away) |
| | **Keep offcuts in the offcut bin** – sections below the minimum remnant size go into the [offcut bin](2-stock.md#offcut-bin) instead of the bin |
| | **Only offcuts from …** – smaller sections are still thrown away (panels: narrower side) |
| Labels & printer | Format (see below), custom size, [QR code and layout](#qr-codes), address for QR codes, chain printing, [direct printing](#direct-printing-brother-p-touch), preview |
| Data | Create or restore a backup (all data as ZIP) |
| Connections | REST API: enable, port, API key (see [REST API](api.md)) |
| Keyboard shortcuts | Click a key, press the new key |
| About & license | Version, check for updates, license status and license key |

Fixed keys: **1–6** switch tabs, **Enter** saves a dialog, **Esc** closes it.

## Label formats

| Group | Formats |
|---|---|
| A4 sheets | 70 × 36 mm (Avery 3475, 24 per sheet), 63.5 × 38.1 mm (Avery L7160, 21), 99.1 × 38.1 mm (Avery L7163, 14) |
| A4 sheets, small labels | 38.1 × 21.2 mm (Avery L7651, 65), 25.4 × 10 mm (Avery L7658, 189) |
| Rolls | 62 × 29 mm (Brother DK-11209), 90 × 38 mm (DK-11208), 100 × 62 mm (DK-11202), 89 × 36 mm (Dymo 99012), 90 × 29 mm (DK-11201) |
| Rolls, small labels | 54 × 17 mm (Brother DK-11204), 23 × 23 mm (DK-11221), 51 × 19 mm (Dymo 11355), 25 × 13 mm (Dymo 11353) |
| Continuous tape | 12, 29 and 62 mm wide (Brother DK-22214, DK-22210, DK-22205) – the length follows the content |
| P-touch tape (TZe) | 12, 18 and 24 mm (e.g. Brother PT-P710BT) – laminated, resists oil and abrasion; only the height the print head reaches is printed (9.9 / 15.8 / 18.1 mm) |
| Custom | your own size, at least 15 × 10 mm |

Any printer prints A4 sheets. Rolls and continuous tape are for label printers such as Brother QL or
Dymo: the PDF has one page per label in label size, printed via the print dialog with the
printer's driver.

**Small labels** show only what fits legibly, in this order: piece code or part, size,
material/location. Code and size are never cut off. On very flat labels one line remains, e.g.
"AP40-07 · 1200 mm". The **preview** shows a sample label exactly as it will be printed.

**Print continuous tape as a chain:** all labels go one after another onto one strip (up to 40 cm,
then the next one) with dashed cut marks. This saves tape, as P-touch printers leave about 2 cm
before every single print.

## Direct printing (Brother P-touch)

There is no Mac printer driver for the **Brother PT-P710BT** (P-touch Cube Plus), only Brother's
own apps. So CutStock drives the printer itself – no PDF, no Brother software:

1. Connect the printer to the Mac via **USB**, switch it on, load 12, 18 or 24 mm TZe tape.
2. In the **desktop app**, enable **Print directly** under Settings → Labels & printer. Below it
   you see the printer found and the loaded tape ("PT-P710BT, 12 mm tape loaded"); **Test print**
   prints the sample label. Before every print CutStock asks and shows how many labels and roughly
   how much tape it takes ("3 labels on 12 mm tape, about 21 cm of tape").
3. From then on all labels (label dialog, a piece's label, location labels, offcuts after cutting,
   scan view) go to the printer. The label dialog also offers **As PDF**.

CutStock reads the loaded tape from the printer and lays out the labels for it; the paper format
then only applies to the PDF, and the preview shows the tape.

**Saving tape:** the cutter sits about 2.5 cm from the print head – that much blank tape comes out
with every cut piece. By default CutStock cuts **after each label**. If you turn **Cut after each
label** off, all labels of a job go on **one strip** with dashed cut marks and only the end is cut
– that saves a good 2 cm of tape per label; separate them with scissors. For
small parts, 12 mm tape with the "Mini" layout is enough – the cheapest tape.

If the printer reports a problem (no tape, cover open, tape too narrow, printer busy – e.g.
because P-touch Editor is using it), CutStock shows it.

#### Brother QL on the network (e.g. QL-820NWB)

CutStock talks to a **Brother QL-800/810W/820NWB** on the network directly – also from the Docker
instance, without driver or print bridge:

1. Under Settings → Labels & printer, enter the address next to **Network printer (Brother QL)**,
   preferably the **IP address** (e.g. `10.10.30.96`; the Docker instance does not know “….local”
   names). **Check** then shows e.g. "QL-820NWB, 29 mm continuous loaded".
2. Turn on **Print directly**.

CutStock reads the loaded **DK roll** itself: continuous rolls (12–62 mm, length from the content)
and die-cut labels (e.g. 29 × 90 mm, 62 × 29 mm). For the **red/black roll** (DK-22251, 62 mm), tick
**Red/black roll loaded** – the QL does not report this over the network. The bold title line
(code and material or the location) is printed in red.

With both P-touch and QL set up, **Default printer** sets the preselection; the confirmation
before each print lets you pick the other one. The QL reports via IPP when a job is finished;
CutStock shows errors such as "cover open" or "no roll".

#### Print bridge (macOS only): printing from the Docker instance and the phone

> The print bridge is available **for macOS only** for now. On Windows, use the PDF.

When CutStock runs as a Docker instance on a server, the printer is usually attached to another
computer. That is what the **CutStock print bridge** is for: a small program for the Mac the
P-touch is connected to via USB. It shows as a printer icon in the menu bar, asks your instance
for print jobs and sends them to the printer. You can then print from any browser (Safari too)
and from the phone, e.g. from the scan view.

1. In CutStock under Settings → Labels & printer, click **Pair** next to **Print bridge**.
   CutStock shows a **pairing code** (e.g. `323E-M2M8-TYCS-2PHY-P4B6`).
2. Download the print bridge from cutstock.app and start it on the Mac with the printer. On first
   start it asks for your instance's **address** and the **pairing code** and adds itself as a
   login item (so it starts by itself from then on; can be turned off in its menu).
3. Turn on **Print directly**. Below it you then see e.g. "PT-P710BT at Workshop Mac, 12 mm tape
   loaded".

The bridge menu offers: status (ready, printing, no printer, no connection), **Pause**, **Open
CutStock**, **Set up …**, **Start at login**, **Quit**.

To avoid wasting tape: if the bridge does not pick up a job within a minute (computer off,
bridge paused), the job expires – nothing is printed later. A job is never printed twice. Before
each print the bridge checks the loaded tape. The computer with the printer must be on and logged
in; it does not print while asleep. **New code** invalidates the old pairing code, **Unpair**
switches the bridge off.

## QR codes

| Setting | Meaning |
|---|---|
| QR code on labels | Piece and location labels get a QR code (default: on). Part labels from the cut plan have none. |
| Layout | **Normal** – QR on the left, text beside it · **Mini** – QR and code (with size if it fits), for small parts and 12 mm tape · **QR only** – code in small type underneath (e.g. 23 × 23 mm) |
| Address for QR codes | Address at which the phone reaches CutStock, e.g. `https://cutstock.example`. **This address** takes the current one. Empty: only the code in the QR code (for hand scanners) |

The QR code is at least 7 mm. If it does not fit the label, CutStock prints text only and the
preview says so. How to scan: [Stock → Scanning QR codes](2-stock.md#scanning-qr-codes).
