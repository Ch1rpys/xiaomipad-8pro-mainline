#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
# Adapted from the erhai integration project; see NOTICE.
set -euo pipefail

repo=$(cd -- "$(dirname -- "$0")/.." && pwd)
# Workspace layout: when this repo is checked out at <workspace>/public/<name>,
# shared inputs and build outputs live in the workspace root; standalone
# checkouts keep everything inside the repo. PIANO_WORKSPACE overrides both.
if [[ -f $repo/../../AGENTS.md && -d $repo/../../kernel/linux ]]; then
	ws=${PIANO_WORKSPACE:-$(cd -- "$repo/../.." && pwd)}
else
	ws=${PIANO_WORKSPACE:-$repo}
fi
src=${KERNEL_SOURCE:-"$ws/kernel/linux"}
out=${OUT_DIR:-"$ws/out/kernel-dev"}
jobs=${JOBS:-$(nproc)}
cross=${CROSS_COMPILE:-aarch64-linux-gnu-}
fragment="$src/$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["config"])' "$repo/kernel/source.json")"

if [[ ${1:-} == --help ]]; then
	echo "Usage: $0 (KERNEL_SOURCE, OUT_DIR, JOBS, CROSS_COMPILE optional)"
	exit 0
fi
[[ $# == 0 ]] || { echo "Unexpected arguments; use --help" >&2; exit 2; }
src=$(realpath "$src")
[[ $(git -C "$src" rev-parse --show-toplevel) == "$src" ]] || {
	echo 'Kernel source must have its own Git repository.' >&2
	exit 1
}
[[ -f $fragment ]]
mkdir -p "$out"
out=$(realpath "$out")
exec 9>"$out/.build.lock"
flock -n 9 || { echo "Build output is already in use: $out" >&2; exit 1; }

head=$(git -C "$src" rev-parse HEAD)
expected=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["commit"])' "$repo/kernel/source.json")
[[ "$head" == "$expected" ]] || { echo "Kernel HEAD does not match kernel/source.json" >&2; exit 1; }
base=$(git -C "$src" describe --tags --abbrev=0 --match 'v[0-9]*' HEAD)
[[ -z $(git -C "$src" status --porcelain --untracked-files=no) ]] || {
	echo 'Commit or snapshot tracked kernel changes before building.' >&2
	exit 1
}
export ARCH=arm64 CROSS_COMPILE="$cross"
export KBUILD_BUILD_USER=piano KBUILD_BUILD_HOST=builder KBUILD_BUILD_VERSION=1
export KBUILD_BUILD_TIMESTAMP
KBUILD_BUILD_TIMESTAMP=$(git -C "$src" show -s --format=%cI HEAD)
export KCFLAGS="-ffile-prefix-map=$src=/linux -ffile-prefix-map=$out=/kbuild"
export KAFLAGS="-Wa,--debug-prefix-map=$src=/linux -Wa,--debug-prefix-map=$out=/kbuild"
cc="${cross}gcc"
if command -v ccache >/dev/null; then
	cc="ccache $cc"
fi
args=(-C "$src" O="$out" "CC=$cc")
recipe=$(cat "$src/arch/arm64/configs/defconfig" "$fragment" | sha256sum | cut -d' ' -f1)
toolchain=$("${cross}gcc" --version | head -1)
identity=$(printf '%s\n' "$src" "$base" "$toolchain" "$cross" "$KCFLAGS" "$KAFLAGS" | sha256sum | cut -d' ' -f1)
if [[ -f $out/.build-input && $(cat "$out/.build-input") != "$identity" ]]; then
	echo 'Toolchain/source location changed; select a new OUT_DIR.' >&2
	exit 1
fi
printf '%s\n' "$identity" >"$out/.build-input"
if [[ ! -f $out/.config || ! -f $out/.recipe || $(cat "$out/.recipe") != "$recipe" ]]; then
	make "${args[@]}" defconfig >"$out/configure.log" 2>&1
	"$src/scripts/kconfig/merge_config.sh" -m -O "$out" "$out/.config" "$fragment" >>"$out/configure.log" 2>&1
	make "${args[@]}" olddefconfig >>"$out/configure.log" 2>&1
	printf '%s\n' "$recipe" >"$out/.recipe"
fi
while IFS= read -r setting; do
	case "$setting" in
	CONFIG_*=y)
		grep -Fxq "$setting" "$out/.config" || {
			echo "Requested built-in dependency missing: $setting" >&2; exit 1;
		}
		;;
	esac
done <"$fragment"

printf 'Building %s with %s (%s jobs)\n' "$head" "$toolchain" "$jobs"
make "${args[@]}" -j"$jobs" Image qcom/sm8750-qrd.dtb qcom/sm8750-mtp.dtb 2>&1 | tee "$out/build.log"
[[ $(git -C "$src" rev-parse HEAD) == "$head" && -z $(git -C "$src" status --porcelain --untracked-files=no) ]] || {
	echo 'Source changed during build; output must not be used.' >&2; exit 1;
}
python3 - "$out" "$head" "$toolchain" <<'PY'
import hashlib, json, pathlib, sys
out, head, compiler = pathlib.Path(sys.argv[1]), *sys.argv[2:]
files = ['arch/arm64/boot/Image', 'arch/arm64/boot/dts/qcom/sm8750-qrd.dtb', 'arch/arm64/boot/dts/qcom/sm8750-mtp.dtb', '.config']
result = {'status': 'OFFLINE_BUILD_ONLY', 'kernel_commit': head, 'compiler': compiler,
          'note': 'Offline platform compilation only. QRD/MTP DTBs are not piano boot inputs.',
          'files': {f: hashlib.sha256((out / f).read_bytes()).hexdigest() for f in files}}
(out / 'build-result.json').write_text(json.dumps(result, indent=2) + '\n')
PY
echo "Reference platform build complete: $out/build-result.json (not a tablet boot image)"
