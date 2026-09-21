#!/bin/sh
# SPDX-License-Identifier: MIT
# Adapted from the liuqin mainline project; see NOTICE.

set -eu

project_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
extract_dir="$project_root/tools/local/aosp-mkbootimg"
commit=954bc3ead5e679005fddf3484d247f2557b3c2c9
url="https://android.googlesource.com/platform/system/tools/mkbootimg"
mkbootimg_sha256=37d84b3d162e0bc62e36c1f4e1c63c85ea0caa9f29be023eb2f8efe006ad948c
unpack_sha256=06b54dd9a07c5281778e29e234e76f6e3faee8bf0c904a5ef88fdee30eeed12e

if [ ! -d "$extract_dir/.git" ]; then
	git init -q "$extract_dir"
fi
# Gitiles-generated archive bytes can change while the source tree is unchanged.
if ! git -C "$extract_dir" cat-file -e "$commit^{commit}" 2>/dev/null; then
	git -C "$extract_dir" fetch --depth 1 "$url" "$commit"
fi
if [ -n "$(git -C "$extract_dir" status --porcelain)" ]; then
	echo "Refusing to change a modified tool checkout: $extract_dir" >&2
	exit 1
fi
git -C "$extract_dir" checkout -q --detach "$commit"
echo "$mkbootimg_sha256  $extract_dir/mkbootimg.py" | sha256sum --check
echo "$unpack_sha256  $extract_dir/unpack_bootimg.py" | sha256sum --check

printf 'AOSP tag: android-16.0.0_r4\ncommit: %s\n' "$commit"
python3 "$extract_dir/mkbootimg.py" --help >/dev/null
python3 "$extract_dir/unpack_bootimg.py" --help >/dev/null
