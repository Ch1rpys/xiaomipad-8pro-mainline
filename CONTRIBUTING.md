# Contributing

Read AGENTS.md before making changes. Supervised RAM boot and desktop sessions
have run on piano; an installable product and installation workflow are not yet validated.

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
Remote contribution and release endpoints will be added when established.
