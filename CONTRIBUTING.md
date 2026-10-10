# Contributing

Read AGENTS.md and docs/AGENT-GUIDE.md before making changes. Ubuntu is installed
next to Android on one test unit and boots from slot A; installation is manual
(docs/INSTALL.md) and the release is a developer preview. Hardware status is in the
README support matrix and docs/STATUS.md.

Keep drivers, DTS and kernel configuration in the independent Linux tree.
Keep distribution-independent device userspace, distribution integration and user-facing build tools here. Use relative or explicit
input paths, preserve third-party attribution, and avoid dependencies on private
workspaces or previous build output.

Document tested behavior and known limitations. Compilation, emulation, service
activation and evidence from another tablet are not proof of piano hardware support.
Validate changes according to their scope.

Use standard Linux subsystem interfaces, add only necessary device-specific
behavior, and document the condition under which temporary workarounds can be removed.
Prefer upstream and distribution packages. Keep package-manager hooks, service
management and desktop preferences out of hardware protocols and processing code.
Changes for another distribution should mainly concern packaging and system integration;
kernel/modules, firmware and userspace interfaces still require compatible versions.
Report problems and send changes through GitHub issues and pull requests on
https://github.com/yzddmr6/xiaomipad-8pro-mainline; kernel changes go to
https://github.com/yzddmr6/linux-sm8750-piano (branch `piano/dev`). Remove serial
numbers, Bluetooth/Wi-Fi addresses, calibration and other personal data from logs first.
