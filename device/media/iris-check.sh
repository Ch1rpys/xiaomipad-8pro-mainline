#!/bin/sh
# SPDX-License-Identifier: MIT
if ! command -v python3 >/dev/null 2>&1; then
    echo 'IRIS_RESULT=UNAVAILABLE reason=missing python3; install python3 before the RAM boot'
    dmesg 2>&1 | grep -Ei 'iris|venus|hfi|firmware|vpu35' || :
    exit 2
fi
exec python3 "$(dirname "$0")/iris-check.py" "$@"
