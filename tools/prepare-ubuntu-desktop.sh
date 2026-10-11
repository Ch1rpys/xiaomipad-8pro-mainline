#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Adapted from the liuqin official Desktop ISO extractor; see NOTICE.
set -euo pipefail
if [[ ${1:-} == --help ]]; then
	echo 'Usage: UBUNTU_ISO=... OUT_DIR=... prepare-ubuntu-desktop.sh'
	exit 0
fi
[[ $# == 0 ]] || exit 2
iso=${UBUNTU_ISO:?set UBUNTU_ISO to the original Ubuntu 26.04 Desktop ARM64 ISO}
out=${OUT_DIR:?set OUT_DIR to a casper layer output directory}
repo=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
pins=$(python3 - "$repo/ubuntu/desktop-layers.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
print(d['iso_sha256'], d['files']['minimal.squashfs'], d['files']['minimal.standard.squashfs'])
PY
)
read -r iso_hash base_hash desktop_hash <<<"$pins"
printf '%s  %s\n' "$iso_hash" "$iso" | sha256sum --check --status
command -v 7z >/dev/null
mkdir -p "$out"
out=$(realpath "$out")
exec 9>"$out/.extract.lock"
flock -n 9 || { echo 'Desktop layer output is already in use.' >&2; exit 1; }
# Use only the base and Desktop layers, not the language-pruning overlay.
for layer in minimal minimal.standard; do
	case "$layer" in minimal) expected=$base_hash ;; *) expected=$desktop_hash ;; esac
	file="$out/$layer.squashfs"
	if [[ -f $file ]] && printf '%s  %s\n' "$expected" "$file" | sha256sum --check --status; then
		continue
	fi
	7z x -so "$iso" "casper/$layer.squashfs" >"$file.part" 2>"$out/$layer.extract.log"
	printf '%s  %s\n' "$expected" "$file.part" | sha256sum --check --status
	mv "$file.part" "$file"
done
python3 - "$out" "$iso_hash" "$base_hash" "$desktop_hash" <<'PY'
import json
from pathlib import Path
import sys
out, iso_hash, base_hash, desktop_hash = sys.argv[1:]
result = {
    'scope': 'Verified original Ubuntu Desktop layers, not an installed piano system',
    'release': '26.04 LTS', 'architecture': 'arm64',
    'url': 'https://cdimage.ubuntu.com/ubuntu/releases/26.04/release/ubuntu-26.04-desktop-arm64.iso',
    'iso_sha256': iso_hash,
    'layer_order': ['minimal.squashfs', 'minimal.standard.squashfs'],
    'files': {'minimal.squashfs': base_hash, 'minimal.standard.squashfs': desktop_hash},
}
(Path(out) / 'layers.json').write_text(json.dumps(result, indent=2) + '\n')
PY
echo "Official Desktop layers prepared in $out; no user, device package or boot image added."
