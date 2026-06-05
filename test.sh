#!/bin/bash
# Tests ausführen
cd "$(dirname "$0")"
source venv/bin/activate
python -m pytest tests/ -v
