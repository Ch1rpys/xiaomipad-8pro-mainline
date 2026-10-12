#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""One bounded read-only SSC nameservice query; shared with product readiness."""
import json
from pathlib import Path
import sys

# A source checkout uses ../qrtr.py; the relocatable bundle has ./qrtr.py.
sys.path.append(str(Path(__file__).resolve().parent.parent))
from qrtr import lookup

print(json.dumps(lookup()))
