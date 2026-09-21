# Contribution Rules

- This repository contains public integration code and user documentation for Xiaomi Pad 8 Pro (piano).
- Kernel drivers, DTS and kernel configuration belong in the independent Linux repository. Do not duplicate them here.
- Preserve upstream attribution and per-file licenses. Record imported code in `NOTICE`.
- Use explicit, pinned inputs. Do not depend on another tablet workspace, private paths, previous build outputs, device secrets or calibration from another unit.
- Report this device's tested behavior only. Research and successful compilation do not establish hardware support.
- Keep device-specific runtime changes packaged and use standard Ubuntu interfaces where possible.
- Do not publish raw device records, credentials, stock backups or firmware without a redistribution basis.
- Validate changes in proportion to their scope. Keep offline construction separate from hardware tests; build and packaging tools must not implicitly access or modify a device.
