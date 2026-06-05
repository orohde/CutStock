#!/bin/bash
# CutStock im Entwicklungsmodus starten
cd "$(dirname "$0")"
source venv/bin/activate
python run.py
