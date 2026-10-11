#!/bin/bash
# SPDX-License-Identifier: MIT
# Runs inside the mounted image. /run and /tmp are disposable tmpfs mounts.
set -euo pipefail
IN=/run/piano-inputs
OUT=/run/piano-out
T=/
. "$IN/params.sh"
. "$IN/steps.sh"
mkdir -p "$OUT"
finish() {
	status=$?
	trap - EXIT
	set +e
	echo "PIANO_ROOTFS_EXIT status=$status" | tee -a "$OUT/install.log"
	sync -f /
	exit "$status"
}
trap finish EXIT
# The helper has already bound proc/sys/dev/pts; retain the shared milestone.
target_mounts() { :; }
rootfs_steps 2>&1 | tee "$OUT/install.log"
