# SPDX-License-Identifier: MIT
# Sourced by the KernelSU-Next module installer.
[ "$(getprop ro.product.device)" = piano ] || abort "! This module is only for the Xiaomi Pad 8 Pro (piano)"
ui_print "- After the next reboot, check with:"
ui_print "  su -c sh /data/adb/modules/piano-switch/piano-switch.sh --check"
