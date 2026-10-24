#!/bin/bash
# SPDX-License-Identifier: MIT
# Runs inside the mounted image. /run and /tmp are disposable tmpfs mounts.
set -euo pipefail
export IN=/run/piano-inputs OUT=/run/piano-out T=/
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
# Keep the guest's POSIX shell semantics inside the policy. In particular,
# dpkg-query returns 1 for purged package globs even when its filtered output
# correctly says no unwanted kernels remain. The outer pipeline still checks
# both the worker and tee, and waits for both before the host unmounts.
/bin/sh -eu -c '
    . "$IN/params.sh"
    . "$IN/steps.sh"
    target_mounts() { :; }
    trim_target() { :; }
    rootfs_steps
' 2>&1 | tee "$OUT/install.log"
