#!/bin/bash
# CutStock Druckbrücke als macOS .app bauen (Symbol in der Menüleiste)
cd "$(dirname "$0")"
source venv/bin/activate
pyinstaller bruecke.spec --noconfirm
echo ""
echo "==> dist/CutStock Druckbrücke.app ist bereit"
