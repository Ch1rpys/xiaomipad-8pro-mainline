# Persistent boot integration (initial device validation in progress)

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

The local filesystem installation and v4 boot from the active A slot have
been verified. Boot version/SPL and AVB properties must come from the local
stock image; an unlocked loader still needs a well-formed boot contract.
The user has confirmed a black physical panel despite a populated framebuffer.
Touch input and GPU startup also fail in this persistent configuration. This
is not a usable or fully validated installer release. Keep a recoverable debug
entry until actual panel output is confirmed; process state is not display
acceptance. Existing RAM diagnostics remain RAM-only images.
