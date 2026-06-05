#!/bin/bash
# CutStock als macOS .app bauen
cd "$(dirname "$0")"
source venv/bin/activate
pyinstaller cutmaster.spec --noconfirm
echo ""
echo "==> dist/CutStock.app ist bereit"
