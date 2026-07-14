#!/bin/bash
# CutStock als macOS .app bauen (pywebview)
cd "$(dirname "$0")"
source venv/bin/activate
pyinstaller desktop.spec --noconfirm
echo ""
echo "==> dist/CutStock.app ist bereit"
