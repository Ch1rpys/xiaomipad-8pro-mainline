// SPDX-License-Identifier: GPL-2.0-only
/*
 * restart2 ARG: reboot(2) with LINUX_REBOOT_CMD_RESTART2 and ARG, as
 * systemctl --reboot-argument=ARG does; BusyBox reboot has no argument.
 * With nvmem-reboot-mode bound, "bootloader" makes ABL start Fastboot.
 * Built against the kernel's nolibc (tools/include/nolibc); the caller
 * syncs first. No other effect: it returns 1 only if the call fails.
 */
int main(int argc, char **argv)
{
	if (argc != 2)
		return 2;
	return _sys_reboot(LINUX_REBOOT_MAGIC1, LINUX_REBOOT_MAGIC2,
			   LINUX_REBOOT_CMD_RESTART2, argv[1]) ? 1 : 0;
}
