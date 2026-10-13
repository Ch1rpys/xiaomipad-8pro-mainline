# Bluetooth address at first boot

A generic boot image cannot contain a unit's Bluetooth address. The installer
already places that unit's address in `/etc/piano/bluetooth-address` before the
first GNOME boot. `bluetooth-address.py` passes it through the standard Linux
MGMT `Set Public Address` command only when the onboard WCN7860 is
unconfigured and reports that missing option. It then re-enumerates the HCI
index before BlueZ starts. Configured controllers are left alone.

The support package installs an `ExecStartPre` drop-in for the distribution's
`bluetooth.service`. The helper uses its existing CAP_NET_ADMIN; it needs no
mount privilege, new daemon, private account or boot image update. The address
file remains a private installation input. Missing/invalid input fails clearly;
no default or generated address is substituted.

This adapts the MIT helper from Project-SunUEFI commit
`6a8763d010adb00b18911d6d12e6dd02869f98b9`; see `NOTICE` for the exact path,
author and changes. Run `python3 device/bluetooth/test_address.py` for MGMT
error, controller-selection and re-enumeration regressions. Those tests are
software coverage, not pairing/audio acceptance.
