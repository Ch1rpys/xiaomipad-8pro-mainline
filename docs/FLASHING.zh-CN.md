# Fastboot、切换与恢复

[English](FLASHING.md) ｜ [项目首页](../README.zh-CN.md) ｜ [安装](INSTALL.zh-CN.md)

Android 和 Ubuntu 都从 A 槽启动。切换就是把另一个系统的镜像组写入 `init_boot_a`、`vendor_boot_a`
和 `boot_a`，活动槽始终不变。本页说明切换工具、槽属性、Fastboot 恢复以及绝不能写入的分区。

## 绝不写入

- `vbmeta` 与 `dtbo`；
- 任何 `_b` 分区，也不要执行 `fastboot --set-active=b`：测试机的 B 槽是旧原厂链，无法启动 Android；
- `persist` 或其他校准、基带、固件分区；
- 其他平板的镜像、标定或地址。

每条命令都绑定到你的平板（`adb -s <SERIAL>`、`fastboot -s <SERIAL>`、`piano-switch.py --serial <SERIAL>`），
同一时间只用一个工具操作。离开 Android 时电量至少 40%，Linux 下不能充电。

## Fastboot

长按**电源 + 音量下**直到出现 Fastboot；任何状态（包括卡死）都有效。系统运行时也可以在 Android 中执行
`adb -s <SERIAL> reboot bootloader`，在 Ubuntu 中执行 `sudo piano-reboot-bootloader`。

```bash
fastboot devices                                  # 预期列出你的 <SERIAL>
fastboot -s <SERIAL> getvar current-slot          # 预期 "current-slot: a"
fastboot -s <SERIAL> getvar battery-soc-ok        # 预期 "battery-soc-ok: yes"
```

## 维护 RAM 镜像

发布目录的 `boot/boot-ram-maintenance.img` 是只在 RAM 中运行的 Linux，用于不能在已挂载系统中进行的 UFS 盘操作，
例如 [INSTALL.zh-CN.md 第 6 步](INSTALL.zh-CN.md#6-写入分区表平板上)的分区表写入。它不写任何分区，也不改变 A 槽。

```bash
fastboot -s <SERIAL> boot <release>/boot/boot-ram-maintenance.img    # 预期 "Booting OKAY"
python3 tools/piano-devmode-ssh.py --serial <SERIAL> --check         # 预期 "... 192.168.88.10 -> 192.168.88.2 ready"
telnet 192.168.88.2 2323                                              # root shell，无密码
```

| 会话中 | 作用 |
|---|---|
| （登录） | 打印内核、LUN 表、`Mounted from the UFS disks: none` 和 LUN 0 的 `sgdisk -p` |
| `piano-maint map` | 再打印一次该表 |
| `piano-maint status` | 空闲计数与时限、打开的会话、能否重启进入 Fastboot |
| `piano-maint keepalive`、`piano-maint idle SECONDS` | 重新计数；设置时限（30–3600 s） |
| `piano-maint fastboot` | 立即重启进入 Fastboot |
| `wget -O /run/FILE http://192.168.88.10:8000/FILE` | 从主机上的 `python3 -m http.server --bind 192.168.88.10 8000` 复制文件 |

10 分钟内没有打开的会话时，平板自行重启进入 Fastboot；会话只在连着线时计入。之后 `fastboot -s <SERIAL> reboot` 启动 A 槽。
工具：`sgdisk`、`sfdisk`、`lsblk`、`partx`、`blockdev`（Ubuntu 26.04 二进制）、BusyBox `dd`、`sha256sum` 和 `wget`。
所有命令以 root 运行：你让 `dd`、`sgdisk`、`sfdisk` 写盘时它们就会写盘。测试机已验证：启动、链路、LUN 表、空闲后自动重启进入 Fastboot、`piano-maint fastboot`，以及 [INSTALL 第 6 步](INSTALL.zh-CN.md#6-写入分区表平板上)的写入流程以当前分区表原样重写（2026-10-10）。

## 镜像组

镜像组是一个目录，含 `boot.img`、`init_boot.img`、`vendor_boot.img`（均为完整分区大小）和列出这三个文件的 `SHA256SUMS`。

| 镜像组 | 位置 |
|---|---|
| Android | 你的 A 槽备份（[INSTALL.zh-CN.md](INSTALL.zh-CN.md#2-备份)）；`init_boot` 为正在使用的、已打 root 补丁的镜像 |
| Ubuntu | 发布目录的 `boot/`；运行 `piano-boot-update` 之后为存储中的 `ubuntu/` |

平板上的存储目录 `/var/lib/piano/switch/` 保存 `android/`、`ubuntu/` 和 `ubuntu.prev/`（当前之前的 Ubuntu 镜像组）。
主机上保留 Android 镜像组和当前 Ubuntu 镜像组的副本。每次内核更新后，把新的 Ubuntu 镜像组复制到主机：

```bash
# 平板上
sudo cp -r /var/lib/piano/switch/ubuntu ~/ubuntu-set && sudo chown -R $USER: ~/ubuntu-set
# 主机上
scp -r <USER>@192.168.88.2:ubuntu-set ubuntu-set-current
(cd ubuntu-set-current && sha256sum -c SHA256SUMS)       # 预期三行 "OK"
```

A 槽的 Android root 补丁变化后（例如从 Magisk 换成 KernelSU），存储的 `android/` 不再一致，`to-android`
会写回旧的 `init_boot`。请用当前 A 槽镜像生成新的 Android 镜像组，并用
`sudo piano-boot-switch import-android --from <dir>` 存入。

## 在 Ubuntu 中：`piano-boot-switch`

| 命令 | 写入 | 结果 |
|---|---|---|
| `sudo piano-boot-switch status` | 不写 | A 槽内容（`android`、`ubuntu`、`ubuntu.prev`、`unknown`）、槽标志、备份 GPT 状态 |
| `sudo piano-boot-switch verify` | 不写 | 所有镜像组完好时退出码为 0 |
| `sudo piano-boot-switch to-android --dry-run` | 不写 | `"result": "would-write"` |
| `sudo piano-boot-switch to-android --reboot` | A 槽 | `"result": "written"`，随后启动 Android |
| `sudo piano-boot-switch to-ubuntu [--reboot]` | A 槽 | `written`；A 槽已是该镜像组时为 `unchanged` |
| `sudo piano-boot-switch import-android --from DIR` | 存储 | `"result": "imported"`；替换 `android/` |
| `sudo piano-boot-switch import-ubuntu [--from DIR]` | 存储 | `imported`；原 `ubuntu/` 变为 `ubuntu.prev/` |

- v0.1.0-preview 安装需要 piano-device-support 0.1+20261010.6 或更高版本，即 [INSTALL 第 10 步](INSTALL.zh-CN.md#10-安装本机文件)
  所装版本（0.1+20261010.3 对所有命令报 `serial-mismatch`）。
- 需要 `/etc/piano/` 中有本机的 `boot-profile.json` 和 `boot-partitions.json`；只在 A 槽为已知镜像组时写入，
  该镜像组同时作为回滚。每个分区都完整写入并读回；失败时写回原镜像组。
- `"result": "refused"` 表示什么都没写，`code` 与 `message` 说明原因。
  `rollback-failed` 或 `final-mismatch`：不要重启，从 Fastboot 恢复（见下文）。
- 测试机已验证：`status`、`verify`、两种导入、`to-ubuntu`、`to-android --reboot`。
  应用网格中的 **切换到 Android** 调用同一工具，尚未验证。

## 在 Android 中：KernelSU 模块

测试机已验证（2026-10-10）：安装、`--check`、执行动作（以 `dd` 写入 A 槽、槽属性保持，30 s 后经开发者模式连上 Ubuntu）。发布目录中的 `tools/piano-switch-ksu-<version>.zip` 需要
带 shell root 的 KernelSU-Next、与 A 槽一致的已存储 `android/` 镜像组，以及 Ubuntu 正常关机。

```bash
adb -s <SERIAL> push piano-switch-ksu-<version>.zip /data/local/tmp/
adb -s <SERIAL> shell su -c '/data/adb/ksud module install /data/local/tmp/piano-switch-ksu-<version>.zip'
adb -s <SERIAL> reboot
adb -s <SERIAL> shell su -c 'sh /data/adb/modules/piano-switch/piano-switch.sh --check'
# 预期 "CHECK OK: slot A holds the android set and the ubuntu set is ready; nothing written"
adb -s <SERIAL> shell su -c 'ksud module action piano-switch'   # 写入 A 槽并重启
```

退出码 3 表示写入与恢复都失败：不要重启，从 Fastboot 恢复 Android 镜像组。
详见 [device/android/piano-switch-ksu](../device/android/piano-switch-ksu/README.md)（英文）。

## 从主机：`piano-switch.py`

测试机已验证两个方向。在 Fastboot 中：

```bash
# 切到 Android
python3 tools/piano-switch.py --serial <SERIAL> --images <android-set> --rollback <ubuntu-set>
fastboot -s <SERIAL> reboot
# 切到 Ubuntu
python3 tools/piano-switch.py --serial <SERIAL> --images <ubuntu-set> --rollback <android-set>
fastboot -s <SERIAL> reboot
# 预期 "Active A boot triplet written; remain in Fastboot for a RAM readback before reboot."
```

- 首次写入前检查 `product: piano`、`unlocked: yes`、`current-slot: a`、三个分区大小和两组 `SHA256SUMS`。
  写入失败时写回回滚镜像组并报告错误。
- 三次写入不是原子操作：切换中途断电后，从 Fastboot 重新执行。
- 进入 Fastboot 前先关闭 Ubuntu；不要中断正在进行的写入。

## 槽属性

```bash
fastboot -s <SERIAL> getvar slot-successful:a     # 已标记时为 "yes"
fastboot -s <SERIAL> getvar slot-unbootable:a     # 预期 "no"
fastboot -s <SERIAL> getvar slot-retry-count:a    # 主机写入后为 7，每次未标记的启动减 1
```

| 事件 | 对 A 槽的影响 |
|---|---|
| 主机写入 `boot_a`（包括经 `piano-switch.py`） | 清除 successful，重试计数设为 7 |
| 启动尚未标记成功的槽 | ABL 将重试计数减 1；减到 0 时该槽变为不可启动 |
| Ubuntu 启动 | 启动完成后 `piano-slot-success.service` 将该槽标记为成功 |
| Android 启动 | Android 标记该槽 |
| 在任一系统内切换 | 不变 |

优先在系统内切换，它保留槽属性。在 Ubuntu 中可用 `sudo piano-slot-success --check` 查看状态，不会写入。

如果 Fastboot 显示 `slot-unbootable:a: yes`，执行 `fastboot -s <SERIAL> --set-active=a` 重置 A 槽计数，
然后切换或 `fastboot -s <SERIAL> reboot`。在测试机上这也提高了 B 槽的优先级；B 槽仍不使用。

## 平板无响应时

1. **已开启开发者模式**（在 Ubuntu 中 `sudo piano-devmode on`）：开机约 22 秒后，
   `python3 tools/piano-devmode-ssh.py --check` 应报告连接 `ready`。然后执行
   `python3 tools/piano-devmode-ssh.py -t <USER> sudo piano-reboot-bootloader`，或用
   `piano-boot-switch to-android --reboot` 切到 Android。
2. **否则**长按电源 + 音量下直到出现 Fastboot，再用 `piano-switch.py` 写入 Android 镜像组。
   在系统启动前卡住的启动没有计时器，会一直停在那里，直到按下组合键。

不要从主机重置 USB 设备，也不要对没有响应的平板重复发命令。

## 恢复原布局

v0.1 中移除 Ubuntu 并恢复原分区表既无工具，也无已验证的流程；这类写入所需的环境是[维护 RAM 镜像](#维护-ram-镜像)。请保留 [INSTALL.zh-CN.md](INSTALL.zh-CN.md#2-备份)
中的分区表备份和完整分区备份。
