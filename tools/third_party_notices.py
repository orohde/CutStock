#!/usr/bin/env python3
"""Erzeugt THIRD_PARTY_NOTICES.txt mit den Lizenztexten aller mitgelieferten Fremdbestandteile.

Die Desktop-App (PyInstaller) und das Docker-Image liefern Python und die
Laufzeit-Abhängigkeiten mit aus. Deren Lizenzen verlangen, dass die Lizenztexte
beiliegen.

Neu erzeugen, wenn sich requirements-web.txt ändert. Nutzung (in einer sauberen
venv, damit keine Test-/Build-Tools mitgezählt werden):
    python3 -m venv /tmp/notices-venv
    /tmp/notices-venv/bin/pip install -r requirements-web.txt
    /tmp/notices-venv/bin/python tools/third_party_notices.py
"""

from __future__ import annotations

import importlib.metadata as md
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "THIRD_PARTY_NOTICES.txt"
VENDOR_LICENSE = ROOT / "web" / "static" / "vendor" / "LICENSE.txt"

# Werkzeuge der venv selbst, nicht Teil der ausgelieferten App
SKIP = {"pip", "setuptools", "wheel"}

SEP = "=" * 78


def license_files(dist: md.Distribution) -> list[tuple[str, str]]:
    """Liefert (Dateiname, Inhalt) aller Lizenz-/Notice-Dateien einer Distribution."""
    result = []
    for f in dist.files or []:
        name = f.name.upper()
        if not any(k in name for k in ("LICEN", "COPYING", "NOTICE", "AUTHORS")):
            continue
        if f.suffix in (".py", ".pyc", ".so", ".pyd"):
            continue
        try:
            text = Path(f.locate()).read_text(encoding="utf-8", errors="replace")
        except (FileNotFoundError, IsADirectoryError):
            continue
        if text.strip():
            result.append((str(f), text.strip()))
    return result


def python_license() -> str:
    ver = f"python{sys.version_info.major}.{sys.version_info.minor}"
    for p in (Path(sys.base_prefix) / "lib" / ver / "LICENSE.txt",
              Path(sys.base_prefix) / "LICENSE.txt"):
        if p.exists():
            return p.read_text(encoding="utf-8").strip()
    raise SystemExit("Python-Lizenztext nicht gefunden")


def main() -> None:
    dists = sorted(
        (d for d in md.distributions() if d.metadata["Name"].lower() not in SKIP),
        key=lambda d: d.metadata["Name"].lower(),
    )

    parts = [
        "CutStock -- Third-Party Notices",
        "",
        "CutStock itself is licensed under the terms in LICENSE. The desktop app and",
        "the Docker image include the following third-party components, which are",
        "licensed under their own terms as reproduced below.",
        "",
        SEP,
        "SAP Fundamental Library Styles, SAP Theming Base Content (Horizon theme, 72 font)",
        "Location: web/static/vendor/",
        "Copyright (c) SAP SE or an SAP affiliate company and contributors",
        "License: Apache-2.0",
        SEP,
        "",
        VENDOR_LICENSE.read_text(encoding="utf-8").strip(),
        "",
        SEP,
        "Python (bundled in the desktop app)",
        "License: PSF-2.0",
        SEP,
        "",
        python_license(),
        "",
    ]

    missing = []
    for d in dists:
        name, version = d.metadata["Name"], d.version
        lic = d.metadata.get("License-Expression") or d.metadata.get("License") or ""
        if len(lic) > 80:  # manche Pakete packen den ganzen Lizenztext ins Feld
            lic = ""
        files = license_files(d)
        if not files:
            missing.append(name)
        parts += [SEP, f"{name} {version}", f"License: {lic or 'see below'}", SEP, ""]
        for fname, text in files:
            parts += [f"--- {fname} ---", "", text, ""]

    OUT.write_text("\n".join(parts) + "\n", encoding="utf-8")
    print(f"{OUT.name}: {len(dists)} Pakete geschrieben")
    if missing:
        print(f"WARNUNG: keine Lizenzdatei gefunden für: {', '.join(missing)}")


if __name__ == "__main__":
    main()
