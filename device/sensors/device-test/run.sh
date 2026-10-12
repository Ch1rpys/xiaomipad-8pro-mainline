#!/bin/sh
# SPDX-License-Identifier: MIT
set -eu
export PYTHONDONTWRITEBYTECODE=1
exec python3 "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)/run.py" "$@"
