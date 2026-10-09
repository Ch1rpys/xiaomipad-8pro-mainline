# Contribution Rules

- This repository contains public integration code and user documentation for Xiaomi Pad 8 Pro (piano).
- Kernel drivers, DTS and kernel configuration belong in the independent Linux repository. Do not duplicate them here.
- Preserve upstream attribution and per-file licenses. Record imported code in `NOTICE`.
- Use explicit, pinned inputs. Do not depend on another tablet workspace, private paths, previous build outputs, device secrets or calibration from another unit.
- Report this device's tested behavior only. Research and successful compilation do not establish hardware support.
- Keep hardware protocols and device userspace independent of the distribution, package manager, desktop and fixed user accounts. Use standard Linux subsystem interfaces; keep package recipes, service units and desktop policy as separate integration concerns.
- Ubuntu is the current target. Prefer distribution-provided third-party packages; when a capability is missing, pin upstream sources and minimal patches and record when the override can be removed. Reuse existing build systems instead of a custom dependency or service framework.
- Kernel ownership and built-in/module configuration are separate decisions. Boot-critical dependencies must be built in or fully available in the distribution initrd; ship modules matching the kernel. Do not carry the module-free RAM diagnostic configuration into the product by default.
- Keep image generation, distribution update hooks and device installation separate. Package by dependency, privilege, licensing and update lifecycle; share payload sources across package formats and keep diagnostic sessions out of default product services.
- Do not publish raw device records, credentials, stock backups or per-device data (serial, Bluetooth/Wi-Fi addresses, touch calibration). Stock firmware under `firmware/` is distributed by the owner's decision (2026-10-09) with the licence statement in `firmware/README.md`; nothing else from the stock build.
- Validate changes in proportion to their scope. Keep offline construction separate from hardware tests; build and packaging tools must not implicitly access or modify a device.
