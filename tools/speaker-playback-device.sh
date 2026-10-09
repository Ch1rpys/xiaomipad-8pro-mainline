#!/bin/sh
# SPDX-License-Identifier: MIT
#
# Unattended speaker playback probe, run as root ON THE TABLET (developer-mode
# SSH), for example:
#   tools/piano-devmode-ssh.py USER -- sudo sh -s -- /run/piano-spk/tone.wav \
#       < tools/speaker-playback-device.sh > speaker-run.log
# The host judges the log with tools/speaker-playback-check.py judge.
#
# Safety rules (unattended runs):
# - amplifier gain at most UNATTENDED_AMP_MAX = 160 of 255 (0.375 dB steps,
#   -35.6 dB below the amplifier maximum); the tone file is made by
#   "speaker-playback-check.py tone", peak at most -20 dBFS. The script stops
#   before playing if any amplifier reads back above the limit or the kernel
#   cap (215) is missing.
# - raw ALSA only (hw:CARD,0), no sound server; one 3 s tone.
# - watchdog: 5 s after the stream starts it interrupts, then kills aplay; if
#   the PCM is still open after that, it unbinds the four amplifiers, which
#   puts them into shutdown through their reset lines.
# Nothing here writes amplifier registers directly; register reads go through
# the driver's regmap (debugfs), which serialises with the driver.
set -u
TONE=${1:?tone.wav}
CARD_NAME=Xiaomi-Pad-8-Pro
UNATTENDED_AMP_MAX=160
KERNEL_AMP_CAP=215
WATCHDOG_S=5
AMPS="Top Left:35 Top Right:37 Bottom Left:34 Bottom Right:36"
REGS="00 03 04 06 10 11 16 17"

say() { printf '%s\n' "$*"; }
uptime_s() { cut -d' ' -f1 /proc/uptime; }

say "start uptime=$(uptime_s) kernel=$(uname -r)"
CARD=$(awk -v n="$CARD_NAME" '$0 ~ (" - " n "$") {print $1; exit}' /proc/asound/cards)
if [ -z "$CARD" ]; then say "fatal no-card"; exit 2; fi
say "card index=$CARD id=$(cat /proc/asound/card$CARD/id)"
[ -e /proc/asound/card$CARD/pcm0p ] && say "pcm0p present=1" || { say "fatal no-pcm0p"; exit 2; }

mountpoint -q /sys/kernel/debug || mount -t debugfs debugfs /sys/kernel/debug
amp_dev() { # $1 = address (hex, no 0x)
	for d in /sys/bus/i2c/drivers/fs19xx/*-00$1; do [ -e "$d" ] && basename "$d"; done
}
dump_regs() { # $1 = tag
	for a in $AMPS; do
		addr=${a##*:}; dev=$(amp_dev "$addr")
		if [ -z "$dev" ]; then say "amp addr=0x$addr bound=0"; continue; fi
		# One pass over the file: regmap reads every register once.
		snap=$(cat /sys/kernel/debug/regmap/$dev/registers 2>/dev/null)
		line="regs tag=$1 addr=0x$addr t=$(uptime_s)"
		for r in $REGS; do
			v=$(printf '%s\n' "$snap" | grep -i "^$r:" | awk '{print $2}')
			line="$line r$r=${v:-NA}"
		done
		say "$line"
	done
}
gauges() { # $1 = tag; one line, current_now of every bq27 battery in uA
	line="gauge tag=$1 t=$(uptime_s)"
	for p in /sys/class/power_supply/bq27*; do
		[ -r "$p/current_now" ] && line="$line $(basename $p)=$(cat $p/current_now)"
	done
	say "$line"
}
sample_gauges() { # $1 = tag, $2 = samples (5 Hz)
	i=0
	while [ $i -lt $2 ]; do gauges "$1"; sleep 0.2; i=$((i + 1)); done
}

for a in $AMPS; do
	pos=${a%%:*}; addr=${a##*:}; dev=$(amp_dev "$addr")
	say "amp addr=0x$addr pos=\"$pos\" bound=$([ -n "$dev" ] && echo 1 || echo 0) dev=${dev:-none}"
done
dump_regs idle

# Volume: unattended value, read back, refuse to play above the limits.
for a in $AMPS; do
	pos=${a%%:*}
	amixer -c "$CARD" -q cset name="$pos Amp Volume" $UNATTENDED_AMP_MAX >/dev/null 2>&1
	info=$(amixer -c "$CARD" cget name="$pos Amp Volume" 2>/dev/null)
	max=$(printf '%s\n' "$info" | sed -n 's/.*max=\([0-9]*\).*/\1/p' | head -1)
	val=$(printf '%s\n' "$info" | sed -n 's/^ *: values=\([0-9]*\).*/\1/p' | head -1)
	say "volume pos=\"$pos\" max=${max:-NA} value=${val:-NA}"
	if [ -z "$val" ] || [ "$val" -gt $UNATTENDED_AMP_MAX ] || [ -z "$max" ] || [ "$max" -gt $KERNEL_AMP_CAP ]; then
		say "fatal volume-limit pos=\"$pos\""; exit 3
	fi
done
amixer -c "$CARD" -q cset name='SECONDARY_TDM_RX_0 Audio Mixer MultiMedia1' 1 && say "route set=1" || say "route set=0"

dmesg_mark=$(uptime_s)
sample_gauges before 15

aplay -D "hw:$CARD,0" -f S16_LE -c 4 -r 48000 "$TONE" >/tmp/piano-spk-aplay.log 2>&1 &
APLAY=$!
t0=$(uptime_s)
say "aplay pid=$APLAY t0=$t0"
(
	sleep $WATCHDOG_S
	if kill -0 $APLAY 2>/dev/null; then
		echo "watchdog fired=1 t=$(uptime_s)"
		kill -INT $APLAY 2>/dev/null; sleep 0.5; kill -KILL $APLAY 2>/dev/null; sleep 0.5
		if ! grep -q closed /proc/asound/card$CARD/pcm0p/sub0/status 2>/dev/null; then
			for d in /sys/bus/i2c/drivers/fs19xx/*-003[4-7]; do
				[ -e "$d" ] && echo "$(basename $d)" > /sys/bus/i2c/drivers/fs19xx/unbind
			done
			echo "watchdog unbound=1"
		fi
	fi
) &
WATCHDOG=$!
sleep 0.5; dump_regs play; gauges play
grep -h . /proc/asound/card$CARD/pcm0p/sub0/hw_params 2>/dev/null | sed 's/^/hw_params /'
sample_gauges play 8
dump_regs play
wait $APLAY; rc=$?
t1=$(uptime_s)
say "aplay rc=$rc t1=$t1"
sed 's/^/aplay-out /' /tmp/piano-spk-aplay.log
kill $WATCHDOG 2>/dev/null; wait $WATCHDOG 2>/dev/null
say "pcm status=$(head -1 /proc/asound/card$CARD/pcm0p/sub0/status 2>/dev/null)"
sample_gauges after 15
dump_regs after
dmesg | awk -v m="$dmesg_mark" '{ t = $0; sub(/^\[ */, "", t); sub(/\].*/, "", t); if (t + 0 >= m) print "dmesg " $0 }'
say "end uptime=$(uptime_s)"
