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
# Optional variant fragment merged after the pinned one, e.g.
# CONFIG_FRAGMENT_EXTRA=arch/arm64/configs/piano-ufs-ro-diag.config (or
# piano-gpu-diag.config). It must be
# a tracked file in the kernel source and needs its own OUT_DIR.
extra=${CONFIG_FRAGMENT_EXTRA:-}

if [[ ${1:-} == --help ]]; then
	echo "Usage: $0 (KERNEL_SOURCE, OUT_DIR, JOBS, CROSS_COMPILE, CONFIG_FRAGMENT_EXTRA optional)"
	exit 0
fi
[[ $# == 0 ]] || { echo "Unexpected arguments; use --help" >&2; exit 2; }
src=$(realpath "$src")
[[ $(git -C "$src" rev-parse --show-toplevel) == "$src" ]] || {
	echo 'Kernel source must have its own Git repository.' >&2
	exit 1
}
[[ -f $fragment ]]
fragments=("$fragment")
if [[ -n $extra ]]; then
	git -C "$src" ls-files --error-unmatch -- "$extra" >/dev/null 2>&1 || {
		echo "CONFIG_FRAGMENT_EXTRA must be a tracked kernel source path: $extra" >&2; exit 1;
	}
	fragments+=("$src/$extra")
fi
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
recipe=$(cat "$src/arch/arm64/configs/defconfig" "${fragments[@]}" | sha256sum | cut -d' ' -f1)
toolchain=$("${cross}gcc" --version | head -1)
identity=$(printf '%s\n' "$src" "$base" "$toolchain" "$cross" "$KCFLAGS" "$KAFLAGS" | sha256sum | cut -d' ' -f1)
if [[ -f $out/.build-input && $(cat "$out/.build-input") != "$identity" ]]; then
	echo 'Toolchain/source location changed; select a new OUT_DIR.' >&2
	exit 1
fi
printf '%s\n' "$identity" >"$out/.build-input"
if [[ ! -f $out/.config || ! -f $out/.recipe || $(cat "$out/.recipe") != "$recipe" ]]; then
	make "${args[@]}" defconfig >"$out/configure.log" 2>&1
	"$src/scripts/kconfig/merge_config.sh" -m -O "$out" "$out/.config" "${fragments[@]}" >>"$out/configure.log" 2>&1
	printf '%s\n' "$recipe" >"$out/.recipe"
fi
# Source updates can add Kconfig symbols without changing the board fragment.
make "${args[@]}" olddefconfig >>"$out/configure.log" 2>&1
while IFS= read -r setting; do
	case "$setting" in
	CONFIG_*=y)
		grep -Fxq "$setting" "$out/.config" || {
			echo "Requested built-in dependency missing: $setting" >&2; exit 1;
		}
		;;
	esac
done < <(cat "${fragments[@]}")

printf 'Building %s with %s (%s jobs)\n' "$head" "$toolchain" "$jobs"
make "${args[@]}" -j"$jobs" Image qcom/sm8750-xiaomi-piano.dtb \
	qcom/sm8750-xiaomi-piano-gpu-diag.dtb qcom/sm8750-xiaomi-piano-power-diag.dtb \
	qcom/sm8750-xiaomi-piano-thp-diag.dtb qcom/sm8750-xiaomi-piano-ufs-ro-diag.dtb 2>&1 | tee "$out/build.log"
[[ $(git -C "$src" rev-parse HEAD) == "$head" && -z $(git -C "$src" status --porcelain --untracked-files=no) ]] || {
	echo 'Source changed during build; output must not be used.' >&2; exit 1;
}
python3 - "$out" "$head" "$toolchain" "$src" "${fragments[@]}" <<'PY'
import hashlib, json, pathlib, sys
out, head, compiler, src = pathlib.Path(sys.argv[1]), sys.argv[2], sys.argv[3], pathlib.Path(sys.argv[4])
files = ['arch/arm64/boot/Image', 'arch/arm64/boot/dts/qcom/sm8750-xiaomi-piano.dtb',
         'arch/arm64/boot/dts/qcom/sm8750-xiaomi-piano-gpu-diag.dtb',
         'arch/arm64/boot/dts/qcom/sm8750-xiaomi-piano-power-diag.dtb',
         'arch/arm64/boot/dts/qcom/sm8750-xiaomi-piano-thp-diag.dtb',
         'arch/arm64/boot/dts/qcom/sm8750-xiaomi-piano-ufs-ro-diag.dtb', '.config']
result = {'status': 'OFFLINE_BUILD_ONLY', 'kernel_commit': head, 'compiler': compiler,
          'config_fragments': [str(pathlib.Path(f).relative_to(src)) for f in sys.argv[5:]],
          'note': 'RAM-only piano skeleton. Building does not establish hardware support.',
          'files': {f: hashlib.sha256((out / f).read_bytes()).hexdigest() for f in files}}
(out / 'build-result.json').write_text(json.dumps(result, indent=2) + '\n')
PY
echo "Piano kernel build complete: $out/build-result.json (boot packaging is separate)"
