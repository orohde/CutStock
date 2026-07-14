#!/bin/bash
# CutStock im Entwicklungsmodus starten (Desktop-Fenster)
cd "$(dirname "$0")"
source venv/bin/activate
python desktop.py
