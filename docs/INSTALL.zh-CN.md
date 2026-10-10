# 安装 v0.1.0-preview

[English](INSTALL.md) ｜ [项目首页](../README.zh-CN.md) ｜ [Fastboot、切换与恢复](FLASHING.zh-CN.md)

本指南手工把 v0.1.0-preview 发布版本安装到小米平板 8 Pro（`piano`）的 Android 旁边。
v0.1 只能手工安装，尚无安装器；写入新分区表（[第 6 步](#6-写入分区表平板上)）在发布目录的维护 RAM 镜像中进行。
开始前请通读全文。

## 先读

- **会清除全部 Android 数据。** `userdata` 被缩小并重建，`metadata` 被清空。
- **只测试过一台。** 型号 25091RP04C（国行）、512 GB UFS、A 槽原厂版本 `OS3.0.303.0.WPYCNXM`。
  其他型号、容量和原厂版本未测试；预构建启动镜像组只适用于 `OS3.0.303.0.WPYCNXM`。
- **Bootloader 必须已解锁**，通过小米官方流程。
- **先备份**（[第 2 步](#2-备份)）。原厂 A 槽镜像是回到 Android 的依据。
- **Linux 下不能充电。** 在 Android 中充电，离开 Android 时电量至少 40%。
- **不要刷写 `vbmeta`、`dtbo`、任何 `_b` 分区、`persist` 或其他校准、基带、固件分区，也不要执行
  `fastboot --set-active=b`。** 测试机的 B 槽是旧原厂链，无法启动 Android。
- **全程守在平板旁。** 任何状态下长按电源 + 音量下都能进入 Fastboot；正式镜像没有调试控制台。
- **每条命令都带序列号**（`adb -s <SERIAL>`、`fastboot -s <SERIAL>`、`piano-switch.py --serial <SERIAL>`），
  同一时间只用一个工具操作平板。
- **出错就停。** 一次状态查询失败后不要重发写入，已成功写入的分区不要重刷，正在进行的写入不要中断。

因尚无项目工具而使用标准命令的步骤标为*手工*。

## 准备

| 项目 | 说明 |
|---|---|
| 小米平板 8 Pro，原厂 `OS3.0.303.0.WPYCNXM`，A 槽活动 | Android 中可用 `adb` |
| Android root | 用 Magisk 或 KernelSU-Next 修补 `init_boot_a`，用于读取分区（*手工*，按该项目的说明操作） |
| 小米磁吸键盘 | 安装本机触控标定之前唯一的输入方式（[第 10 步](#10-安装本机文件)） |
| Linux x86_64 主机 | Android platform-tools（`adb`、`fastboot`）、Python 3、`openssl`、`uuidgen`、`sgdisk`、`sfdisk`、`losetup`、`mkfs.ext4`、`img2simg`、`sha256sum`、`telnet` |
| AOSP `avbtool.py` | 来自 AOSP `external/avb`（尚无获取脚本） |
| 本仓库 | 检出到发布版 `RELEASE-NOTES.md` 中的集成提交，然后执行 `sh tools/fetch-aosp-mkbootimg.sh` |
| 发布目录 | 同一版本的全部文件，不与其他版本混用 |
| 主机可用空间 | 约 40 GB：备份（测试机 16 GB）、发布目录（约 9 GB）与数据镜像 |

把[发布](https://github.com/yzddmr6/xiaomipad-8pro-mainline/releases/tag/v0.1.0-preview)的全部 `piano-v0.1.0-preview.tar.zst.part*` 下载到同一目录，还原发布目录（约需 14 GB 空间），使用前先校验：

```bash
sha256sum -c SHA256SUMS.assets                   # 下载的附件
cat piano-v0.1.0-preview.tar.zst.part* | zstd -d | tar -x
cd <release> && sha256sum -c SHA256SUMS          # 预期每行均为 "OK"
```

发布目录包含 `boot/`（A 槽的 Ubuntu 启动镜像组、`boot-ram-check.img` 和 `boot-ram-maintenance.img`）、`rootfs/root.sparse.img`（60 GiB 根）、
`debs/`、`tools/piano-switch.py` 和 KernelSU 模块，内容说明见 [RELEASE.md](RELEASE.md)（英文）。

## 1. 解锁并核对原厂版本

用小米官方工具解锁 Bootloader（会清除平板数据），必要时刷回该原厂版本，并取得 Android root。然后：

```bash
adb -s <SERIAL> shell getprop ro.product.device              # 预期 "piano"
adb -s <SERIAL> shell getprop ro.build.version.incremental   # 预期 "OS3.0.303.0.WPYCNXM"
adb -s <SERIAL> shell getprop ro.boot.slot_suffix            # 预期 "_a"
adb -s <SERIAL> shell su -c id                               # 预期 "uid=0(root) ..."
adb -s <SERIAL> shell dumpsys battery | grep level           # 预期 40 或更高
adb -s <SERIAL> reboot bootloader
fastboot -s <SERIAL> getvar unlocked                         # 预期 "unlocked: yes"
fastboot -s <SERIAL> getvar current-slot                     # 预期 "current-slot: a"
fastboot -s <SERIAL> reboot
```

任何一项不符就停止。

## 2. 备份

*手工。* 备份除 `userdata` 外的全部分区，以及每个 UFS LUN 的分区表。镜像数据用 `adb exec-out`
（可安全传输二进制），不要用 `adb shell`。备份放在仓库之外。

```bash
mkdir -p backup/gpt
adb -s <SERIAL> shell su -c 'for d in /sys/block/sd?; do echo ${d##*/} $(cat $d/size) $(cat $d/queue/logical_block_size); done'
# 预期六个 LUN，逻辑块大小 4096；size 以 512 字节为单位
adb -s <SERIAL> shell su -c 'ls -l /dev/block/by-name/'     # 分区名 -> /dev/block/sdXN

# 除 userdata 外的每个分区
adb -s <SERIAL> exec-out su -c 'dd if=/dev/block/by-name/<label> bs=1048576 2>/dev/null' > backup/<label>.img
adb -s <SERIAL> shell su -c 'sha256sum /dev/block/by-name/<label>'    # 必须与下一行相同
sha256sum backup/<label>.img

# 每个 LUN sdX：MBR 与主 GPT、备份 GPT；<blocks> = size / 8
adb -s <SERIAL> exec-out su -c 'dd if=/dev/block/sdX bs=4096 count=34 2>/dev/null' > backup/gpt/sdX-head.bin
adb -s <SERIAL> exec-out su -c 'dd if=/dev/block/sdX bs=4096 skip=<blocks-34> 2>/dev/null' > backup/gpt/sdX-tail.bin
```

- 记录清单：每个文件的分区名、设备节点、LUN、大小与 SHA-256，以及每个 LUN 的磁盘 GUID。
  `sdX` 盘符每次启动可能不同，只有这份清单能把文件对应到分区。
- `persist` 与 `metadata` 由 Android 读写挂载，读取期间可能变化：计算两次哈希，不一致就重读。

用备份生成 **Android 镜像组**。`init_boot` 必须是 A 槽当前使用的、已打 root 补丁的镜像：

```bash
mkdir android-set
cp backup/boot_a.img android-set/boot.img
cp backup/init_boot_a.img android-set/init_boot.img
cp backup/vendor_boot_a.img android-set/vendor_boot.img
(cd android-set && sha256sum boot.img init_boot.img vendor_boot.img > SHA256SUMS)
```

在主机上保留 `android-set/` 和发布目录 `boot/` 的副本：切换与恢复都用这两组镜像（[FLASHING.zh-CN.md](FLASHING.zh-CN.md)）。

## 3. 收集本机文件

这些文件属于你的平板，不要分享或提交，也不要使用其他平板的文件。它们在[第 10 步](#10-安装本机文件)装入 Ubuntu。

| 文件 | 缺少时 |
|---|---|
| `thp-calibration.json` | 没有触控输入 |
| `bluetooth-address` | 蓝牙控制器不完成配置 |
| `wlan-address` | Wi-Fi 每次启动使用随机 MAC 地址 |
| `boot-profile.json`、`boot-signing.pem` | 无法重建启动镜像组：地址不生效，内核更新也不会改写 A 槽 |
| `boot-partitions.json`（第 10 步生成） | `piano-boot-switch` 拒绝切换 |

**触控标定。** 原厂 ODM 分区有 `piano_nova_csot_thp_config.ini`（CSOT 面板，与测试机相同）和
`piano_nova_boe_thp_config.ini`。使用原厂驱动加载的那一份；测试机的原厂内核日志中是 CSOT 文件。

```bash
adb -s <SERIAL> shell su -c 'find /odm -name "piano_nova_*_thp_config.ini"'
adb -s <SERIAL> exec-out su -c 'cat <ini 路径>' > thp.ini
python3 tools/extract-thp-calibration.py --input thp.ini --output thp-calibration.json
```

**蓝牙地址。**

```bash
adb -s <SERIAL> shell settings get secure bluetooth_address > bluetooth-address
cat bluetooth-address                  # 预期一行 XX:XX:XX:XX:XX:XX
```

**Wi-Fi 地址**（*手工*）。原厂地址是 `persist` 中 `wlan/wlan_mac.bin` 的一行 `wlan0=<12 位十六进制>`，
Android 在 WLAN 固件目录中链接到它。转换为 `XX:XX:XX:XX:XX:XX`：

```bash
adb -s <SERIAL> exec-out su -c 'cat /vendor/firmware/wlan/qca_cld/peach_v2/wlan_mac.bin' \
  | sed -n 's/^wlan0=\(..\)\(..\)\(..\)\(..\)\(..\)\(..\).*/\1:\2:\3:\4:\5:\6/p' > wlan-address
cat wlan-address                       # 预期一行 XX:XX:XX:XX:XX:XX
```

**签名密钥。** 你自己构建的启动镜像组使用的 AVB 密钥：

```bash
openssl genrsa -out boot-signing.pem 4096
```

**启动配置**（*手工*，尚无生成工具）。启动镜像必须带原厂头部字段、回滚索引与 AVB 属性，否则 ABL
会把该槽标为不可启动。按原厂镜像的数值编写 `boot-profile.json`：

```
{
  "serial": "<SERIAL>",
  "boot":        {"header_version": 4, "capacity": 100663296, "rollback_index": <int>, "avb_properties": {<props>}},
  "init_boot":   {"header_version": 4, "capacity": 8388608,   "rollback_index": <int>, "avb_properties": {<props>}},
  "vendor_boot": {"header_version": 4, "capacity": 100663296, "rollback_index": <int>, "avb_properties": {<props>},
                  "page_size": <int>, "kernel_addr": <int>, "ramdisk_addr": <int>, "tags_addr": <int>, "dtb_addr": <int>}
}
```

```bash
python3 tools/local/aosp-mkbootimg/unpack_bootimg.py --boot_img backup/vendor_boot_a.img --out /tmp/vb
# 头版本、页大小、kernel/ramdisk/tags 加载地址、dtb 地址
python3 <avbtool.py> info_image --image backup/boot_a.img
# "Rollback Index:" 与所有 "Prop: com.android.build.boot.*" 行；init_boot_a、vendor_boot_a 同样处理
```

`capacity` 是分区字节数。把每个镜像的全部 `Prop:` 写进对应的 `avb_properties`；`boot` 至少需要
`com.android.build.boot.os_version` 与 `com.android.build.boot.security_patch`。发布目录的
`boot/boot-profile.json` 展示了该原厂版本的同一结构（不含序列号）。

## 4. 分区布局

LUN 0 上原 `userdata` 的范围拆成三个分区，其他分区和 LUN 不变。

| 条目 | 名称 | 大小（512 GB 机型） | 用途 |
|---|---|---|---|
| 34 | `userdata` | 200 GiB | Android 数据；保留起点、类型 GUID、唯一 GUID 和属性 |
| 35 | `linux_rootfs` | 60 GiB | Ubuntu `/` |
| 36 | `linux_data` | 余下约 201.27 GiB | Ubuntu `/home` |

发布版按名称查找分区，名称必须严格为 `linux_rootfs` 和 `linux_data`；两者的 GUID 可以是任意新值。

## 5. 生成新分区表（主机）

*手工。* 只在 LUN 0 分区表的副本上操作，不要直接对平板操作。LUN 0 块大小为 4096 字节
（512 GB 机型共 124,552,192 块）。

```bash
ROOT_UUID=$(uuidgen); DATA_UUID=$(uuidgen)
BLOCKS=<LUN 0 size / 8>                         # 取自第 2 步
truncate -s $((BLOCKS * 4096)) lun0.img
dd if=backup/gpt/<lun0>-head.bin of=lun0.img bs=4096 conv=notrunc
dd if=backup/gpt/<lun0>-tail.bin of=lun0.img bs=4096 seek=$((BLOCKS - 34)) conv=notrunc
LOOP=$(sudo losetup --find --show --sector-size 4096 lun0.img)
sudo sgdisk --print "$LOOP"       # 预期 "Sector size (logical): 4096 bytes" 以及你的分区表
sudo sgdisk --info=34 "$LOOP"     # 预期 "Partition name: 'userdata'"；记下起始扇区、类型 GUID、唯一 GUID、属性
sudo sfdisk --json "$LOOP" > gpt-before.json

S=<userdata 起始扇区>             # 测试机为 3632128
U=<userdata 唯一 GUID>; T=<userdata 类型 GUID>
L=0FC63DAF-8483-4772-8E79-3D69D8477DE4      # Linux filesystem
sudo sgdisk --set-alignment=256 --delete=34 \
  --new=34:$S:$((S + 52428800 - 1)) --typecode=34:$T --partition-guid=34:$U --change-name=34:userdata \
  --new=35:$((S + 52428800)):$((S + 68157440 - 1)) --typecode=35:$L --partition-guid=35:$ROOT_UUID --change-name=35:linux_rootfs \
  --new=36:$((S + 68157440)):0 --typecode=36:$L --partition-guid=36:$DATA_UUID --change-name=36:linux_data \
  "$LOOP"
sudo sgdisk --verify "$LOOP"      # 预期 "No problems found."
sudo sfdisk --json "$LOOP" > gpt-after.json
```

比较 `gpt-before.json` 与 `gpt-after.json`：只允许条目 34–36 不同，起点分别为 `S`、`S + 52428800`、
`S + 68157440`；磁盘 GUID、首末可用 LBA 和表长度不得改变。若 `userdata` 原有非零属性，用
`--attributes=34:=:<hex>` 复制。

取出两段分区表区域（测试机首个可用 LBA 为 6，最后可用 LBA 为 124552186）：

```bash
FIRST=<first usable LBA>; LAST=<last usable LBA>        # 取自 sgdisk --print
sudo dd if="$LOOP" of=new-primary.bin bs=4096 count=$FIRST
sudo dd if="$LOOP" of=new-backup.bin bs=4096 skip=$((LAST + 1))
dd if=backup/gpt/<lun0>-head.bin bs=4096 count=$FIRST 2>/dev/null | sha256sum    # 当前主分区表区域
sha256sum new-primary.bin new-backup.bin
sudo losetup -d "$LOOP"
```

## 6. 写入分区表（平板上）

*在项目环境中手工执行命令。* `boot/boot-ram-maintenance.img` 从 RAM 启动发布版内核和一个小 initramfs：
带 UFS 驱动、经 USB 线提供的 root shell（192.168.88.2，telnet 端口 2323，无密码；该链路只连这根线）以及本步所需工具
（`sgdisk`、`sfdisk`、`lsblk`、`partx`、`blockdev`、`dd`、`sha256sum`、`wget`）。它不挂载任何 UFS 盘的分区，自身不写任何内容，
A 槽仍为 Android。10 分钟内没有打开的会话（拔线后同样计时）时，它会自行重启进入 Fastboot。

在主机上，平板处于 Fastboot，当前目录里有第 5 步的 `new-primary.bin` 和 `new-backup.bin`：

```bash
fastboot -s <SERIAL> boot <release>/boot/boot-ram-maintenance.img    # 预期 "Booting OKAY"
python3 tools/piano-devmode-ssh.py --serial <SERIAL> --check         # 预期 "... 192.168.88.10 -> 192.168.88.2 ready"（约 5 s）
python3 -m http.server --bind 192.168.88.10 8000 &                    # 向平板提供这两个文件
telnet 192.168.88.2 2323
```

`--check` 报告链路就绪后再启动 `http.server`：地址 192.168.88.10 只在链路建立后存在（否则报
`Cannot assign requested address`）。若报 `Address already in use`，说明已有其他服务占用该端口（可能监听全部地址），
请改用空闲端口并同步修改下面的 `wget` 行；下载文件的哈希核对能发现连错服务器。

如果 `--check` 打印的是 `ip` 命令，执行后再检查一次。登录后会打印 LUN 表（LUN、磁盘、以 512 字节扇区计的大小、块大小、设备路径）、
`Mounted from the UFS disks: none` 和 LUN 0 的 `sgdisk -p` 分区表。LUN 0 是以 `0` 开头的那一行，512 GB 机型 size 为
996417536、块大小 4096；核对该分区表就是第 2 步备份的分区表。然后在 telnet 会话中：

```sh
FIRST=<first usable LBA>; LAST=<last usable LBA>; BLOCKS=<LUN 0 blocks>    # 第 5 步的数值
disk=/dev/sdX                                           # 登录表中的 LUN 0
piano-maint map                                         # 再看一次："LUN 0: /dev/sdX"、"Mounted from the UFS disks: none"
wget -O /run/new-primary.bin http://192.168.88.10:8000/new-primary.bin
wget -O /run/new-backup.bin http://192.168.88.10:8000/new-backup.bin
sha256sum /run/new-primary.bin /run/new-backup.bin      # 预期等于第 5 步的哈希
dd if=$disk bs=4096 count=$FIRST | sha256sum            # 预期等于第 5 步当前主分区表区域的哈希
dd if=/run/new-backup.bin of=$disk bs=4096 seek=$((LAST + 1)) conv=fsync
dd if=$disk bs=4096 skip=$((LAST + 1)) count=$((BLOCKS - LAST - 1)) | sha256sum   # 预期等于 new-backup.bin
dd if=/run/new-primary.bin of=$disk bs=4096 conv=fsync
dd if=$disk bs=4096 count=$FIRST | sha256sum            # 预期等于 new-primary.bin
sync
sgdisk --verify $disk                                   # 预期 "No problems found."
sgdisk -p $disk                                         # 预期 34–36 项为 userdata、linux_rootfs、linux_data
piano-maint fastboot                                    # 重启进入 Fastboot
```

先写备份分区表，再写主分区表，每次读回比对通过后再继续。重启前内核仍使用旧的分区列表；本会话中不要挂载或格式化任何分区。
完成后停止主机上的 `http.server`。

- `piano-maint status` 显示空闲计数；`piano-maint keepalive` 重新计数，`piano-maint idle SECONDS`（30–3600）修改时限。
  打开的 telnet 会话只在连着线时才阻止计时。
- 如果 `piano-maint fastboot` 提示 `nvmem-reboot-mode is not bound`，它不会重启；请按电源 + 音量下。
- 测试机已验证（2026-10-10）：启动、约 4 s 后链路就绪、LUN 表、LUN 0 的 `sgdisk -p`、`sfdisk --json` 与 `sgdisk --verify`
  与 2026-10-07 写入的分区表一致、无挂载，以及空闲后自动重启进入 Fastboot。上面的写入命令于 2026-10-07 在更早的
  RAM 环境中写入了该分区表；2026-10-10 在本镜像中以同一分区表原样重写：写前写后区域哈希均等于保存的文件，两次读回一致，
  `sgdisk --verify` 无问题，`piano-maint fastboot` 回到 Fastboot；尚未在本镜像中写入变更后的分区表。

## 7. 写入文件系统（Fastboot）

核对新分区，再按 `linux_data` 的大小生成 `/home` 镜像：

```bash
fastboot -s <SERIAL> getvar partition-size:userdata       # 预期 "3200000000"（十六进制，不带 0x）
fastboot -s <SERIAL> getvar partition-size:linux_rootfs   # 预期 "0xF00000000"
fastboot -s <SERIAL> getvar partition-size:linux_data     # 512 GB 机型为 "0x32517FB000"
truncate -s $((0x<linux_data 大小>)) data.ext4
mkfs.ext4 -L linux_data data.ext4 && img2simg data.ext4 data.sparse.img
```

擦除 Android 数据并写入两个文件系统：

```bash
fastboot -s <SERIAL> erase userdata
fastboot -s <SERIAL> erase metadata
fastboot -s <SERIAL> flash linux_rootfs <release>/rootfs/root.sparse.img   # 约 1 分钟（测试机 USB 3 实测 41 s）
fastboot -s <SERIAL> flash linux_data data.sparse.img                      # 约 30 分钟（测试机实测 1803 s）
# 预期每个 Sending 与 Writing 行均为 "OKAY"，最后 "Finished."
```

稀疏镜像传输量小，但平板会写满整个分区：`data.sparse.img` 只有 6 MB 数据和 201 GiB 零填充，`fastboot` 在唯一一行
`Writing` 期间不显示进度。等每次写入自行结束。已返回 `OKAY` 的写入不要重复。
Android 下次启动时重建 `userdata` 与 `metadata`；全部 Android 数据（包括 root 管理器的配置）都会丢失。

## 8. 可选：不写 A 槽先试启动

```bash
fastboot -s <SERIAL> boot <release>/boot/boot-ram-check.img     # 预期 "Booting OKAY"
```

它从 RAM 启动一次已安装的根，内核、initrd 与命令行与发布镜像组相同，不写任何启动分区。
这是没有调试控制台的普通启动：用电源 + 音量下回到 Fastboot。

## 9. 写入 A 槽并首次启动

核对电量，再把发布镜像组写入 A 槽。`piano-switch.py` 先检查平板和两组镜像，写入失败时写回 Android 镜像组：

```bash
fastboot -s <SERIAL> getvar battery-soc-ok         # 预期 "battery-soc-ok: yes"
python3 <release>/tools/piano-switch.py --serial <SERIAL> --images <release>/boot --rollback android-set
# 预期 "Active A boot triplet written; remain in Fastboot for a RAM readback before reboot."
fastboot -s <SERIAL> reboot
```

- **GNOME 初始设置**创建第一个账户。使用磁吸键盘；第 10 步之前触控不可用。跳过网络页面。必须有人在平板旁：
  从这次启动到第 10 步打开开发者模式之前，主机无法连接平板（开发者模式默认关闭、需要账户且拒绝 root 登录），
  唯一的退路是电源 + 音量下。
- **每次启动后设置时间**，硬件时钟不可写：`sudo date -s 'YYYY-MM-DD HH:MM'`。
- 启动完成后该槽被标记为启动成功：`sudo piano-slot-success --check` 应报告 `"state": "already-successful"`。

第 10 步之前：没有触控和蓝牙，Wi-Fi 使用随机 MAC，不能从 Ubuntu 切换，内核更新也不会改写 A 槽。

## 10. 安装本机文件

**把文件复制到平板**，经开发者模式（USB 线上的 SSH；USB 主机与外接存储不支持）。在平板终端（Ctrl+Alt+T）中：

```bash
sudo piano-devmode on
piano-devmode status       # 预期 "developer mode: enabled, active" 与 "SSH socket: active (192.168.88.2 port 22)"
```

在主机上（`<USER>` 为初始设置中创建的账户）：

```bash
python3 tools/piano-devmode-ssh.py --check     # 预期 "... 192.168.88.10 -> 192.168.88.2 ready"
scp -r thp-calibration.json bluetooth-address wlan-address boot-profile.json boot-signing.pem \
  android-set <USER>@192.168.88.2:
```

如果主机没有取得 DHCP 地址，`--check` 会打印设置地址的 `ip` 命令。

**生成分区映射**（*手工*）。在平板上：

```bash
for p in boot_a init_boot_a vendor_boot_a; do
  n=$(readlink -f /dev/disk/by-partlabel/$p); s=/sys/class/block/${n##*/}
  echo "$p $(lsblk -no PARTUUID $n) $(lsblk -no PTUUID $n) $(($(cat $s/start) * 512)) $(($(cat $s/size) * 512)) $(readlink -f $s/../device)"
done
# 预期设备路径以 ":4" 结尾（LUN 4），大小为 100663296、8388608、100663296
```

把数值写进 `~/boot-partitions.json`：

```
[
  {"label": "boot_a",        "partuuid": "<PARTUUID>", "disk_guid": "<PTUUID>", "lun": 4, "start_bytes": <int>, "bytes": 100663296},
  {"label": "vendor_boot_a", "partuuid": "<PARTUUID>", "disk_guid": "<PTUUID>", "lun": 4, "start_bytes": <int>, "bytes": 100663296},
  {"label": "init_boot_a",   "partuuid": "<PARTUUID>", "disk_guid": "<PTUUID>", "lun": 4, "start_bytes": <int>, "bytes": 8388608}
]
```

> **本步需要 piano-device-support 0.1+20261010.5 或更高版本。** v0.1.0-preview 根自带 0.1+20261010.3，其
> `piano-boot-switch` 在发布启动镜像组上以 `"code": "serial-mismatch"` 拒绝所有命令：发布版命令行不含
> `androidboot.serialno`，引导程序只在 `/proc/bootconfig` 中传入它，而 0.1+20261010.3 只读 `/proc/cmdline`。
> 按 [BUILD](build.zh-CN.md) 构建该包，与下面的文件一起复制到平板并先安装：`sudo dpkg -i piano-device-support_<版本>_arm64.deb`。

**安装文件、存入 Android 镜像组并重建启动镜像组：**

```bash
cd ~
sudo install -m 600 bluetooth-address wlan-address thp-calibration.json boot-profile.json \
  boot-signing.pem boot-partitions.json /etc/piano/
sudo piano-boot-switch status          # 预期 "occupant": "ubuntu" 与 "backup_gpt": "valid"
sudo piano-boot-switch import-android --from ~/android-set     # 预期 "result": "imported"
sudo piano-boot-update $(uname -r)
# 预期 "Piano boot image set prepared for <release>" 与 "Slot A now holds store/ubuntu"
sudo systemctl reboot
```

新镜像组带有你的地址、序列号和密钥；发布镜像组保留为 `ubuntu.prev`。重启后：

```bash
sudo piano-boot-switch verify          # 预期退出码 0
```

然后删除主目录中的副本（`rm -r ~/android-set ~/boot-signing.pem ...`）。若希望从主机访问平板，可保持开发者模式开启；
`sudo piano-devmode off` 关闭它。开发者模式接受所有设有密码的本地账户，如需仅允许 SSH 密钥，见
[device/devmode](../device/devmode/README.md)。

如果重建的镜像组无法启动：按电源 + 音量下，从主机写回发布目录的 `boot/` 镜像组（[FLASHING.zh-CN.md](FLASHING.zh-CN.md#从主机piano-switchpy)）。

## 安装之后

- **切换与恢复：**[FLASHING.zh-CN.md](FLASHING.zh-CN.md)。
- **内核更新：**用 `dpkg -i` 安装新的 `linux-image-<release>` 包；它会重建启动镜像组，A 槽为 Ubuntu 时改写该槽。
  详见 [AGENT-GUIDE.zh-CN.md](AGENT-GUIDE.zh-CN.md) §5。
- **Android：**首次启动 Android 会重建数据，需要几分钟。如需 root，请重新安装 root 管理器应用；
  A 槽中已打补丁的 `init_boot_a` 不变。更换 A 槽的 root 补丁后，要刷新存储的 Android 镜像组（[FLASHING.zh-CN.md](FLASHING.zh-CN.md#镜像组)）。
- **已知问题与支持状态：**[README](../README.zh-CN.md#硬件支持)及发布目录中的 `RELEASE-NOTES.md`。

## v0.1 中尚无项目工具的步骤

| 步骤 | 现状 |
|---|---|
| Android root | 按 root 管理器自身的流程 |
| 分区备份与清单（第 2 步） | 标准 `adb`/`dd` 命令 |
| Wi-Fi 地址、启动配置（第 3 步） | 标准命令，无生成工具 |
| 新分区表（第 5 步） | 在 loop 设备上用标准 `sgdisk`/`sfdisk` |
| 写入分区表（第 6 步） | 在发布目录的维护 RAM 镜像中执行标准 `dd` 命令 |
| 分区映射（第 10 步） | 标准命令 |
| 恢复原分区表并移除 Ubuntu | 无工具，也无已验证流程；请保留分区表备份 |
