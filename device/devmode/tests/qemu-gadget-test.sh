#!/bin/sh
# SPDX-License-Identifier: MIT
# Run devmode-gadget against real configfs in an arm64 QEMU guest whose only
# USB device controller is dummy_hcd, with the CDC NCM host driver on the
# guest's dummy host side.  Checks start/start/stop/stop, rebuilding an
# unbound leftover, refusal of a controller held by another gadget or of a
# missing controller, the USB identity and MAC seen by the host side, and
# that stop removes both network interfaces.  QEMU only: no DWC3, Type-C,
# VBUS or host computer is involved.
# usage: qemu-gadget-test.sh QEMU IMAGE BUSYBOX OUTDIR dummy_hcd.ko MODULE.ko...
# The modules are loaded in the given order: dummy_hcd, then the CDC NCM host
# driver and its dependencies (e.g. mii, usbnet, cdc_ether, cdc_ncm).  IMAGE
# and the modules must come from one kernel build with configfs and the NCM
# gadget function built in.
set -eu
[ "$#" -ge 6 ] || { sed -n '3,15p' "$0" >&2; exit 2; }
qemu=$1 image=$2 busybox=$3 out=$4
shift 4
[ "${1##*/}" = dummy_hcd.ko ] || { echo 'the first module must be dummy_hcd.ko' >&2; exit 2; }
here=$(cd "$(dirname "$0")" && pwd)
repo=$here/../../..
mkdir "$out"
root=$out/initramfs
mkdir -p "$root/bin" "$root/etc" "$root/lib/modules" "$root/usr/libexec/piano" "$root/proc" "$root/sys" \
	"$root/dev" "$root/run"
install -m 0755 "$busybox" "$root/bin/busybox"
install -m 0755 "$repo/packaging/piano-device-support/usr/libexec/piano/devmode-gadget" "$root/usr/libexec/piano/"
load=
for m in "$@"; do
	install -m 0644 "$m" "$root/lib/modules/"
	load="$load /lib/modules/${m##*/}"
done
echo "$load" >"$root/etc/modules-order"
# Same generation as tools/build-device-debs.py.
python3 -c 'import json,sys; print("".join(f"PIANO_{k.upper()}={v}\n" for k, v in json.load(open(sys.argv[1])).items()), end="")' \
	"$repo/initramfs/network.json" >"$root/etc/piano-network"
cat >"$root/init" <<'EOF'
#!/bin/busybox sh
/bin/busybox --install -s /bin
export PATH=/bin
mount -t proc proc /proc
mount -t sysfs sysfs /sys
mount -t devtmpfs devtmpfs /dev
mount -t configfs configfs /sys/kernel/config
mount -t tmpfs tmpfs /run
. /etc/piano-network
G=/usr/libexec/piano/devmode-gadget
C=/sys/kernel/config/usb_gadget
fails=0
check() { if eval "$2"; then echo "DEVMODE_PASS $1"; else echo "DEVMODE_FAIL $1"; fails=$((fails + 1)); fi; }
iface() { for n in /sys/class/net/*; do [ "$(cat "$n/address")" = "$1" ] && echo "${n##*/}"; done; return 0; }
# Test harness only: enumeration and netdev removal are asynchronous.
settle() { i=0; while [ "$i" -lt 100 ]; do eval "$1" && return 0; sleep 0.1; i=$((i + 1)); done; return 1; }
usbattr() { d=$(readlink -f "/sys/class/net/$1/device"); while [ "$d" != / ]; do [ -e "$d/idVendor" ] && { cat "$d/$2"; return; }; d=${d%/*}; done; }
run() { out=$("$G" "$@" 2>&1); rc=$?; echo "$out" | sed 's/^/  gadget: /'; return 0; }
for m in $(cat /etc/modules-order); do insmod "$m" || { echo "DEVMODE_FAIL insmod $m"; fails=$((fails + 1)); }; done

run; check usage-exit-2 '[ "$rc" = 2 ]'
run start; check start-1 '[ "$rc" = 0 ] && [ "$(cat $C/piano-devmode/UDC)" = dummy_udc.0 ]'
check host-link 'settle "[ -n \"\$(iface $PIANO_HOST_MAC)\" ]"'
h=$(iface "$PIANO_HOST_MAC"); d=$(iface "$PIANO_DEVICE_MAC")
echo "  host side $h, device side $d"
check device-link '[ -n "$d" ]'
check usb-identity '[ "$(usbattr "$h" idVendor):$(usbattr "$h" idProduct):$(usbattr "$h" serial)" = 1d6b:0104:piano-offline-devmode ]'
check usb-strings '[ "$(usbattr "$h" manufacturer)/$(usbattr "$h" product)" = "piano Linux development/Developer mode" ]'
hidx=$(cat "/sys/class/net/$h/ifindex")
run start; check start-2-idempotent '[ "$rc" = 0 ] && echo "$out" | grep -q "already bound to dummy_udc.0"'
check no-reenumeration '[ "$(cat /sys/class/net/$h/ifindex)" = "$hidx" ]'
run stop; check stop-1 '[ "$rc" = 0 ] && [ ! -e $C/piano-devmode ]'
check links-removed 'settle "[ -z \"\$(iface $PIANO_HOST_MAC)\$(iface $PIANO_DEVICE_MAC)\" ]"'
run stop; check stop-2-idempotent '[ "$rc" = 0 ]'

mkdir "$C/piano-devmode" "$C/piano-devmode/strings/0x409" "$C/piano-devmode/functions/ncm.usb0"
run start; check rebuild-unbound-leftover '[ "$rc" = 0 ] && [ "$(cat $C/piano-devmode/UDC)" = dummy_udc.0 ]'
run stop; check stop-3 '[ "$rc" = 0 ] && [ ! -e $C/piano-devmode ]'

mkdir "$C/other" "$C/other/configs/c.1" "$C/other/functions/ncm.x"
ln -s "$C/other/functions/ncm.x" "$C/other/configs/c.1/"
echo dummy_udc.0 >"$C/other/UDC"
run start; check refuse-busy-udc '[ "$rc" = 1 ] && echo "$out" | grep -q "already used by gadget $C/other" && [ ! -e $C/piano-devmode ]'
echo '' >"$C/other/UDC"; rm "$C/other/configs/c.1/ncm.x"; rmdir "$C/other/configs/c.1" "$C/other/functions/ncm.x" "$C/other"

rmmod dummy_hcd
run start; check refuse-no-udc '[ "$rc" = 1 ] && echo "$out" | grep -q "no USB device controller" && [ ! -e $C/piano-devmode ]'
echo "DEVMODE_RESULT fails=$fails"
poweroff -f
EOF
chmod 0755 "$root/init"
(cd "$root" && find . | LC_ALL=C sort | cpio -o -H newc --quiet) | gzip -9n >"$out/initramfs.cpio.gz"
"$qemu" -machine virt -cpu max -accel tcg,thread=multi -smp 2 -m 768M -nodefaults -display none -monitor none \
	-serial stdio -nic none -no-reboot -kernel "$image" -initrd "$out/initramfs.cpio.gz" \
	-append 'console=ttyAMA0 rdinit=/init panic=1 androidboot.serialno=offline-devmode' </dev/null >"$out/console.log" 2>&1 || true
grep '^DEVMODE_\|^  ' "$out/console.log" | tr -d '\r'
grep -q '^DEVMODE_RESULT fails=0' "$out/console.log"
