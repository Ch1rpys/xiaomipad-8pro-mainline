# Persistent boot integration

The persistent desktop kernel variant enables the reviewed UFS path and ext4.
`build-kernel-deb.py --boot-dtb` carries its audited ABL DTB with the matching
kernel and modules. The device package adds the platform initrd entry, input
service, local firmware, and distro kernel/initrd hooks.

`tools/build-persistent-boot.py` constructs v4 boot/init_boot/vendor_boot images
from the installed distro initrd, the device's original header geometry and
rollback indices, its root PARTUUID, local Bluetooth address and signing key.
It writes regular files only. Normal images have no development console or
expiry timer; both require explicit debug options. A v2 image is also emitted
for bounded testing against the persistent root before changing the boot slot.

`piano-boot-switch` is a Linux-side primitive, currently awaiting device write
validation. It verifies the current piano identity, active A slot, UFS LUN/GPT
GUIDs and geometry, both complete image sets, and every written partition's
full readback. It refuses unknown current contents and attempts the verified
rollback set on an I/O failure. Three-partition replacement is not atomic.
Per-device maps and images are installation inputs; they are never public
payloads. `tools/piano-switch.py` is the host Fastboot recovery writer and
intentionally leaves Fastboot running for a separate RAM readback.

The local filesystem installation and v4 boot from the active A slot work
on the test unit. Boot version/SPL and AVB properties must come from the local
stock image; an unlocked loader still needs a well-formed boot contract.
With the full module set, sync_state releases the boot-time power, clock and
interconnect state. The display therefore depends on the kernel DTS declaring
the firmware scanout's power domains, clocks and bandwidth on the
simple-framebuffer node, and the GPU on its MX and GMXC power-domain votes.
ABL decrements the slot's retry counter on every boot and the Ubuntu side
does not yet mark the slot successful; see
[docs/STATUS.md](../../docs/STATUS.md#known-issues). The installer is not
published. Existing RAM diagnostics remain RAM-only images.

## Suspend is disabled in the first release

Suspend and resume have not been validated on piano. The kernel offers
`s2idle` and `deep`, but neither wake path has been exercised, and a stuck
resume can only be cleared with a forced reboot. `piano-device-support`
therefore ships one policy in two standard places:

- `/usr/lib/systemd/sleep.conf.d/50-piano-first-release.conf` sets
  `AllowSuspend`, `AllowHibernation`, `AllowHybridSleep` and
  `AllowSuspendThenHibernate` to `no`, so logind refuses every sleep request
  from any desktop, key handler or command line.
- `/usr/share/glib-2.0/schemas/50_piano-first-release.gschema.override` sets
  the GNOME idle actions (`sleep-inactive-ac-type`,
  `sleep-inactive-battery-type`) to `'nothing'`, so the session does not
  request suspend. A GSettings vendor override is used because the GDM and
  gnome-initial-setup dconf profiles have no system database; the distro
  `glib-compile-schemas` trigger compiles it.

Lock screen and power-button settings are unchanged. Ubuntu's power-button
action is the interactive end-session dialog; a `suspend` action would fall
back to that dialog because logind reports suspend as unavailable. UPower's
critical-battery action falls back from hybrid sleep and hibernation to
power-off. An administrator can re-enable sleep for testing with a same-named
file in `/etc/systemd/sleep.conf.d/`. Both files are removed once s2idle and
deep suspend/resume are validated on piano.
