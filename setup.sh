#!/bin/bash
# Ersteinrichtung: venv anlegen und Dependencies installieren
cd "$(dirname "$0")"
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install pyinstaller
echo ""
echo "==> Setup fertig. Starten mit: ./run.sh"
echo "    Bauen mit:  ./build.sh"
echo "    Testen mit:  ./test.sh"
