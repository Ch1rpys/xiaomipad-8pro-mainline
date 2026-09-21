# Contributing

Read AGENTS.md before making changes. The project is in research, with no tested
piano boot image or installation workflow.

Keep drivers, DTS and kernel configuration in the independent Linux tree.
Keep Ubuntu integration and user-facing build tools here. Use relative or explicit
input paths, preserve third-party attribution, and avoid dependencies on private
workspaces or previous build output.

Document tested behavior and known limitations. Compilation, emulation, service
activation and evidence from another tablet are not proof of piano hardware support.
Validate changes according to their scope.

Use standard Linux and Ubuntu interfaces, add only necessary device-specific
behavior, and document the condition under which temporary workarounds can be removed.
Remote contribution and release endpoints will be added when established.
