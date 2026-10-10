# 离线构建

这些入口准备 piano 最小板级内核、RAM 诊断候选和原始 Ubuntu Desktop 层。
P01 失败于厂商 ABL 的 overlay 合成；P02 修正已定位的计时器映射后，进入主线 RAM PID1 并定时返回 Android。
回收日志部分损坏，完整首启未验收。它不是可安装系统；不提供安装器，也不使用 QRD/MTP DTB 试机。

## 主机

使用 Linux x86_64、Git、Python 3、GCC、AArch64 GNU 交叉编译器、make、bison、flex、
pkg-config、OpenSSL/ELF 开发库、gzip、cpio、sha256sum、flock；ccache 可选。
Ubuntu 层提取另需 curl、7z、unsquashfs；模拟器验证使用 QEMU system-aarch64。
不需要先拥有任何旧平板工作区或旧构建输出。

下列命令在本仓根目录执行。KERNEL_SOURCE 指向独立 Linux Git，其 HEAD 必须与
kernel/source.json 相符。项目内核源码以 `kernel/source.json` 的 `url` 为准；仅从 stable 上游无法获取包含本地配置与板级提交的版本。

## 诊断内核

```sh
KERNEL_SOURCE=/path/to/independent/linux OUT_DIR="$PWD/out/kernel-diag" JOBS=8 \
  bash tools/build-kernel.sh
```

配置仅在内核仓 arch/arm64/configs/piano-diagnostic.config 维护。
每次增量构建先运行原生 olddefconfig，处理源码新增的 Kconfig 项；片段变化时才重新生成/合并基线。
生成 Image、sm8750-xiaomi-piano.dtb、安装系统所用的 sm8750-xiaomi-piano-desktop.dtb、最终 .config、日志与 build-result.json。
自 7.2.6-piano3（内核 `8d4d5d32c581`）起，各诊断变体 DTS（adsp/bt/desktop-diag/gpu/input/iris/kbd/mic/power/thp/ufs-ro/usb-role）及其片段、
dummy_hcd 回环片段只保留在内核仓 `piano/diag` 分支（`668c9d7e36d6`，即移除前一提交）；下面对各变体的说明只适用于该分支，
构建时用独立 OUT，并把 kernel/source.json 的 commit 临时指向该分支 HEAD（build-kernel.sh 只构建主分支的两个 DTB，变体 DTB 需另列目标）。
thp-diag 是有人监督触控诊断用的变体，只额外启用 gpi_dma1、spi2 和触控节点；P15 已用它在真机取得触控流，默认 piano DTB 仍禁用它们。
ufs-ro-diag 只把 UFS 主机与 QMP PHY 设为 okay，供有人监督的只读识盘；默认 DTB 和默认配置都不启用 UFS。
power-diag 只把两颗 BQ27Z561 所在的 i2c5/i2c11、QUP2 包装器和 gpi_dma1/gpi_dma2 设为 okay，供有人监督的只读电量计/温度读取；配套 piano-power-diag.config 只把 I2C_QCOM_GENI 改为内建。它不描述充电器、电荷泵、电池通路 GPIO、monitored-battery 或温控策略，默认 DTB 两条总线仍 disabled。SE5 在原厂为多执行环境共享，本内核不做 GPI 锁，只能用于不启动远程处理器的有人监督 RAM 会话。
bt-diag 只把 WCN7860 PMU 与 UART14（含蓝牙子节点）设为 okay，配合 piano-bt-diag.config 内建蓝牙/serdev/rfkill/pwrseq；PCIe0 与 WLAN 不启用，默认 DTB 和默认配置都不启用蓝牙。
可选 CONFIG_FRAGMENT_EXTRA=<内核仓内已跟踪的片段路径> 在固定片段之后再合并一份变体片段，两份片段中的 =y 都逐项断言，
build-result.json 记录 config_fragments；变体必须使用独立 OUT_DIR，例如：

```sh
CONFIG_FRAGMENT_EXTRA=arch/arm64/configs/piano-ufs-ro-diag.config \
KERNEL_SOURCE=/path/to/independent/linux OUT_DIR="$PWD/out/kernel-ufs-ro-diag" bash tools/build-kernel.sh
```
当前 DTS 仅用于 RAM 启动与日志；P03 增加 USB2 固定设备模式，显示、UFS 和远程处理器保持关闭。
USB 尚未真机验证；电源输入拓扑、REFGEN 和完整 Type-C 路径仍未闭合，不用于冷启动/低功耗产品验收。
日常保持同一 OUT 增量构建；换工具链或基线时使用新 OUT。
构建输出锁避免并发写入，输入 commit/配置和输出 hash 可核查。
源码现含回移的上游 NT36532 框架，但尚无 P81 面板 profile；默认诊断配置未启用该驱动。

## 持久启动镜像的本机地址

`tools/build-persistent-boot.py` 把两个每台设备不同、只放私有输入的地址写进打包 DTB，不进公开仓：
- `--bt-address-file`：一行 `XX:XX:XX:XX:XX:XX`，写成蓝牙节点的 `local-bd-address`（小端 bdaddr_t）。
- `--wlan-address-file`：一行 `XX:XX:XX:XX:XX:XX`（单播、非全零），写成 `/soc@0/pcie@1c00000/pcie@0/wifi@0` 的 `local-mac-address`（按书写顺序）。
  本机 WCN7860 在 WMI ready 中报告全零地址，ath12k（内核 `668c9d7e36d6`）此时用 `device_get_mac_address()` 读取该属性。
  原厂值在 persist 分区 `wlan/wlan_mac.bin`（一行 `wlan0=<12 位十六进制>`），换成冒号格式即可。
manifest 只记录 `private_bt_address_injected`/`private_wlan_address_injected`，不记录地址。设备上的 `piano-boot-update` 从
`/etc/piano/bluetooth-address` 与 `/etc/piano/wlan-address` 取这两个文件，均为可选、存在才传；缺少本机 `boot-profile.json` 或 `boot-signing.pem` 时（发布根文件系统首次启动前的状态）它不重建镜像组、保留存储中的镜像组并正常退出。
`--root-partlabel` 与 `--no-serial` 生成不绑定单机的发布镜像组，见 [RELEASE.md](RELEASE.md)。

## USB2 角色与单麦设备树准备

`mic-diag` 复用 ADSP 变体，只有 TX3 capture 声卡，VA 作为 aux-dev 提供共享 DMIC 时钟，
本机 GPIO12/13、4 mA 和 2.4 MHz 配置；RX/WSA/SoundWire 总线保持关闭。
`usb-role-diag` 复用 ADSP 变体，只接 USB2 connector→DWC3 角色图，保持 high-speed，USB3/DP PHY 仍关闭。
两者均已编译/schema 验证，尚无实际声卡、UCSI、外设或录音 PASS。
mic-diag 已接入下述模块/固件交付、按序加载和采集，可装配 60 秒 NCM 探测候选；
USB 角色的断网/回收流程仍未闭合，build-boot 继续拒绝 usb-role-diag。
不能将宽泛 defconfig 的全部模块用于 USB 角色诊断：PMIC GLINK 会创建多个辅助消费者，
本机 MCA 未证明兼容 battmgr；首轮只装明确选择的依赖闭包，不自动加载 battmgr/altmode/FastRPC。

## RAM 诊断用户态

```sh
sh tools/fetch-busybox-arm64.sh
mkdir -p out/host-tools
gcc -O2 /path/to/independent/linux/usr/gen_init_cpio.c -o out/host-tools/gen_init_cpio
BUSYBOX="$PWD/tools/local/busybox-arm64/usr/bin/busybox" \
  GEN_INIT_CPIO="$PWD/out/host-tools/gen_init_cpio" OUT_DIR="$PWD/out/initramfs-diag" \
  bash tools/build-initramfs.sh
```

BusyBox 固定为 Ubuntu ARM64 static 1.36.1-6ubuntu3.1；包和二进制都校验。
gen_init_cpio 由同一内核源码产生，可在无 root 权限下正确描述 /dev/console 等节点。
ramdisk 无板级固件、存储挂载或账户；ACM/NCM 是实验用 root console，不进入默认产品。
可选 FIRMWARE_DIR=<私有目录> 把其中的普通文件按相对路径放入 /lib/firmware/<相对路径>，
供探测或首次打开时请求固件的驱动使用（GPU、PCIe Wi-Fi、ADSP 等）。只接受普通文件和目录，路径限于
字母、数字和 `._+-`，拒绝空目录、符号链接和特殊文件。清单 `相对路径 字节数 sha256` 写入
/etc/piano-firmware 并镜像到 OUT_DIR/firmware-manifest；清单进入 build-id，因此不同私有固件的候选身份不同，
不带 FIRMWARE_DIR 时 build-id 算法与之前相同。Ubuntu 模式的 prepare-ubuntu 在交接前将这些文件复制到
RAM overlay 的 /usr/lib/firmware 并按清单校验，交接后才首次请求固件的驱动也能取到。
FIRMWARE_DIR 的内容可由 `tools/stage-firmware.py` 从仓内 `firmware/` 暂存，也可来自自备提取；仓内固件按 [firmware/README.md](../firmware/README.md) 的说明原样分发，没有厂商再分发许可。
`BUSYBOX=... GEN_INIT_CPIO=... python3 tools/test-build-initramfs.py` 用合成夹具检查 cpio 内容、清单、身份变化和拒绝路径。
RAM `/init` 与 dracut 模块 99piano 的 `/init` 都在最前面接好 fd 0–2：/dev/console 能打开就用它，否则用 /dev/null。
内核打不开初始控制台时（例如只有 `console=ttynull`）以关闭的 fd 0–2 启动 PID 1：dracut `/init` 第一次写输出就在 `set -e` 下
结束 PID 1（Wi-Fi B2），RAM `/init` 原来无条件的 `exec </dev/console` 也会直接结束 PID 1。
`sh initramfs/tests/test-init-stdio.sh` 在主机上以关闭的 fd 0–2 运行两份脚本（设备路径换到临时目录；RAM `/init` 只运行第一个 mount 之前的部分），
检查有、无控制台两种情况都能交接，并确认去掉这段保护后按 B2 的方式退出；`DRACUT_SH`、`RAM_SH` 可指定 qemu-aarch64-static 下的目标 shell。

initramfs/network.json 是 NCM 的唯一网络配置，使用独立 USB 子网和仅一台主机的 DHCP 租约，无默认路由/DNS。
默认 180 秒发出重启请求，piano.diag_timeout 可在 15-900 秒内调整。
该机制的 QEMU 成功不证明 Xiaomi ABL 会回 Fastboot，真机恢复仍需验证。

## RAM 启动候选

需要 python3-libfdt、AOSP libufdt 的 ufdt_apply_overlay，以及与设备系统匹配的
原厂 base DTB/DTBO entry。原厂文件不在本仓分发；示例路径必须指向用户自行取得的输入。
构建器没有设备命令，生成候选不等于允许刷写。

```sh
python3 tools/prepare-boot-dtb.py \
  --mainline-dtb out/kernel-diag/arch/arm64/boot/dts/qcom/sm8750-xiaomi-piano.dtb \
  --stock-base /path/to/matching/base-04.dtb \
  --stock-overlay /path/to/matching/overlay.0 \
  --ufdt /path/to/ufdt_apply_overlay --output out/boot-dtb
python3 tools/build-boot.py \
  --kernel-source /path/to/independent/linux --kernel-out out/kernel-diag \
  --initramfs out/initramfs-diag/initramfs.cpio.gz --dtb out/boot-dtb/piano-boot.dtb \
  --mkbootimg tools/local/aosp-mkbootimg/mkbootimg.py --output out/ram-boot \
  --boot-id mainline-p05 --diagnostic ncm
```

build-boot 默认核对打包 DTB 来自 build-result.json 中的 sm8750-xiaomi-piano.dtb；使用变体时显式传
--dtb-source-name arch/arm64/boot/dts/qcom/sm8750-xiaomi-piano-thp-diag.dtb，manifest 记录 dtb_source。

prepare-boot-dtb 将指定磁盘 DTBO 引用的符号指向 disabled 父节点下的隔离区，
另将本机 RM 已核实的 arch_timer 运行时引用导出到真实 /timer（必要时为其生成 phandle）。
真正用 libufdt 合成并确认磁盘 overlay 不改变打包基线的主线硬件属性。它不改内核 DTS，不导入整份原厂符号表，
也不修改平板上的 DTBO。根 compatible/model 仍可能被原厂 overlay 覆盖，运行时 ABL/Gunyah
追加内容仍须真机验证，不能将离线合成结果称为实际运行 FDT。
2026-09-24 的 P01 已证明仅验证磁盘 DTBO 不够覆盖 ABL 行为，不应原样反复试机。
后续静态分析在本机 RM 的主 VM 3 路径发现 arch_timer 外部引用及 always-on 修改；
P02 只补齐这一映射，参考 ABL 核心的双 overlay 契约测试通过，随后本机交接/PID1/正常超时退出已证。
P04/P05 随后经 NCM 取得精确身份与运行 FDT；P04 对照显示既有外设/保留区未被板级 overlay 改写。
完整原始运行时 DTBO 未取得，跨重启日志损坏仍未解决，不混同于已完整回传的实时日志。

build-boot 使用本机已接受的 header v2 容器。默认 --diagnostic console 保留 pstore-only 模式；
--diagnostic acm 或 ncm 选择 USB 控制台，三种模式都保持 60 秒 PID1 重启计时器、panic=15、无存储驱动。
--boot-id 为实验标签，manifest 从实际 cpio 读取 RAM build-id，不根据待变化源码猜测身份。
--diagnostic ufs-ro 是唯一允许 UFS 驱动的模式：要求 --dtb-source-name 为 ufs-ro 变体 DTB，配置内建 UFSHCD/PLATFORM/QCOM/QMP_UFS
且关闭 UFS_CRYPTO/BSG/HWMON；用 libfdt（python3-libfdt）确认同一构建的默认 piano DTB 中两节点仍为 disabled、变体与打包 DTB 为 okay。
它使用 NCM 控制台和 60 秒计时器，命令行加 ro 仅表意（RAM 根没有 root= 设备）；只读识盘步骤由主机在运行时发送，
本仓不含写入或挂载步骤。其余模式继续断言 UFSHCD 未启用，也不能使用 ufs-ro DTB。
USB 使用 ABL 的 androidboot.serialno 生成 piano-<serial> 标识；无该参数时保留 QEMU 的 piano-diag，
主机实验不能将匿名标识当已绑定的实体设备。ACM 需要 tty 权限；NCM 使用主机已有自动 DHCP，不需要更改串口权限。
NCM 短诊断与后续多 GB Ubuntu 根传输分别已有真机记录，不能相互替代各自验证范围。
早于 PID1 的卡死不受用户态计时器保护，第一次测试需要人在设备旁边；不能保证自动恢复。
initramfs 带 FIRMWARE_DIR 时，manifest 的 inputs_sha256.firmware_manifest 记录清单 hash，firmware 列出路径/大小/hash。
--dtb-source-name 为 sm8750-xiaomi-piano-gpu-diag.dtb 时要求配置内建 DRM_MSM（CONFIG_FRAGMENT_EXTRA=arch/arm64/configs/piano-gpu-diag.config
的独立 OUT）且 initramfs 带固件清单，并在命令行加 msm.separate_gpu_kms=1：MDSS 保持关闭、simpledrm 继续扫描输出，
GPU 需要独立的 DRM 设备。这只是诊断编排，GPU 尚无真机结论。
--dtb-source-name 为 sm8750-xiaomi-piano-bt-diag.dtb 时只允许 --diagnostic ubuntu，并要求 bt-diag 独立 OUT 内建 RFKILL/BT/BT_LE/BT_QCA/HCIUART/SERDEV/HCIUART_QCA/POWER_SEQUENCING_QCOM_WCN；蓝牙固件不进镜像，由内部 runner 在桌面启动后作为运行时 bundle 送达，蓝牙尚无真机结论。
它只生成 boot-piano-ram.img 和精确输入/输出 manifest，不执行 Fastboot。

## 实验性 Ubuntu RAM 交接

--diagnostic ubuntu --rootfs-sha256 <已验证的完整 SquashFS hash> 生成二阶段候选，仍不安装到存储。
先在已绑定的 USB NCM 通道提供根文件，主机就绪后通过 /run/piano-start FIFO 通知 PID1。
prepare-ubuntu 校验 hash、挂只读底层与 RAM overlay，再部署仅本会话的控制台和退出 timer；
初始准备上限 600 秒，交接后会话默认 300 秒，可用 --session-seconds 显式选择 60-900 秒；panic=15 不变。
默认 --root-transport http 会在设备上校验完整根 hash。实验性 nbd 使用只读具名 export，主机校验完整 hash；
NBD 交接只在 QEMU 通过，首个本机块读失败，不能作为默认路径或自动回退。原始根和 Android 分区均不改。
不预置普通账号或密码，正常入口仍为 GDM 首次设置；临时调试服务不能进入默认产品。

BusyBox 必须保留其分派所需的程序名；本项目放在 /usr/local/libexec/piano/busybox。
P06 的错误命名曾使控制台和退出服务都失败，后经完整 Ubuntu/QEMU 复现修正，P08 在本机完成交接与返回。
GDM/会话存在仍不证明图形已绘制、触控可用或已登录桌面。该模式是内部有界 bring-up，不是无人值守安装工具。
后续 P12/P13 已另行取得真实桌面帧、内屏目视及 200% 缩放证据；真实输入、持久安装和产品账户流程仍未完成。

## 官方 Ubuntu Desktop 层

官方输入：
[Ubuntu 26.04 Desktop ARM64](https://cdimage.ubuntu.com/ubuntu/releases/26.04/release/ubuntu-26.04-desktop-arm64.iso)。
完整 ISO SHA-256 为 c2afd538d66fdd77377d03f1ed2ac76a34f1c116baecc9a8170d68f833121f57。
使用官方 SHA256SUMS 和签名验证来源；本脚本进一步固定 ISO 与层的具体字节。

```sh
UBUNTU_ISO=/path/to/ubuntu-26.04-desktop-arm64.iso OUT_DIR="$PWD/out/ubuntu-desktop-layers" \
  bash tools/prepare-ubuntu-desktop.sh
```

该入口只提取 minimal.squashfs 和 minimal.standard.squashfs，保留原始 ownership/xattrs。
不应用语言裁剪/live 安装器层，不带入旧项目修改。layers.json 记录顺序和身份。

## 无 Root 合并桌面层

在已核验的两层之上，使用 squashfs-tools-ng 的 sqfs2tar 保留元数据并转换为 TAR；
不要用普通用户解压目录，也不要把 overlay 删除标记当作最终设备文件。
本项目验证版本为 squashfs-tools-ng 1.2.0 和宿主 sqfstar，构建不运行 ARM64 程序，不需要 sudo。

```sh
mkdir -p out/desktop-tars
sqfs2tar --root-becomes . --no-skip out/ubuntu-desktop-layers/minimal.squashfs \
  > out/desktop-tars/minimal.tar
sqfs2tar --root-becomes . --no-skip out/ubuntu-desktop-layers/minimal.standard.squashfs \
  > out/desktop-tars/minimal.standard.tar
python3 tools/merge-desktop-tars.py \
  --base out/desktop-tars/minimal.tar --desktop out/desktop-tars/minimal.standard.tar \
  --output out/ubuntu-desktop-pristine
python3 tools/test-merge-desktop-tars.py
```

输入 TAR 必须来自上述原始层转换。输出为带数值属主/PAX 扩展属性的 TAR 和 zstd SquashFS，
无需把伪装为 root 的展开目录交给安装器。构建器处理字符设备 0:0 whiteout（包括其硬链接）、
opaque 目录及替换后仍须保留旧内容的硬链接，去除 overlay 内部 bookkeeping。
遇到 redirect/metacopy、未知 overlay 属性或根目录 xattrs 会停止，不宣称支持所有 OverlayFS 变体。
sqfstar 默认忽略 TAR 根目录项，因此构建器从归档显式传入根目录 UID/GID/mode/mtime。

这是官方 Desktop 的原始合并底层，不是 piano 安装镜像：尚未创建用户、更新 APT、加入设备包、
配置启动链或验证 GNOME 真机运行。不要把此 SquashFS 直接写入平板分区。

## 固件包

仓库 `firmware/` 按内核请求的路径存放 OS3.0.303.0.WPYCNXM 的 95 个原厂固件文件；来源、许可与排除项见
[firmware/README.md](../firmware/README.md)，`firmware/piano-*.json` 锁定每个文件的名称、大小与 SHA-256。
build-firmware-deb.py 默认从该树构建 `piano-local-firmware`（Architecture all），另加由 device/audio 构建的
采集拓扑；`--firmware-tree` 可换成按同一布局整理的本机提取。只打包锁中列出的文件（DSP 锁只取内核加载的
adsp/adsp_dtb 两个镜像，CDSP 与服务映射不打包），任一文件缺失或 hash 不符即中止。
只使用 dpkg-deb 标准格式，保留原始字节，不安装、不执行 blob，也不附带刷写/服务脚本。

需要 Python 3、python3-debian 和 dpkg-deb（支持 --root-owner-group / --threads-max）。

```sh
python3 tools/build-firmware-deb.py --topology out/audio/Piano-Capture-Diag-tplg.bin \
  --card-topology out/audio/Xiaomi-Pad-8-Pro-tplg.bin \
  --maintainer 'Your Name <your-email>' --output out/firmware-deb
```

SOURCE_DATE_EPOCH 固定；同输入重复构建与从原厂提取树构建的 deb 逐字节相同。
0.2+os3.0.303.0 与已安装的 0.1+20261007 相比，原有 90 个文件的字节与权限相同，新增 6 个 Wi-Fi 文件和
/usr/share/doc 下的 copyright、inputs.json；control 改为 Architecture all，去掉 Depends: linux-base。
build-device-debs.py 不再构建这个包。包构建成功不等于固件加载成功。

## 隔离 APT 准备

ubuntu/26.04.sources 是显式 ARM64 的官方 Ports 源配置。它不自动覆盖原始桌面层；
正式装配时应移除安装介质的 cdrom.sources，而不是保留对 /cdrom 的依赖。
当前 archive.ubuntu.com 也能提供所查的 26.04 ARM64 索引，选择 Ports 并不表示前者必然不可用。

prepare-ubuntu-apt.py 用主机原生 APT，针对原始 SquashFS 的 ARM64 dpkg/status 解析依赖，
只在全新的输出目录中保存配置、官方 keyring、签名索引、缓存和日志。不安装包、不运行维护脚本，
也不修改主机 /etc/apt、原始根树、账户或分区。依赖 apt、python3-apt、python3-debian 和 unsquashfs。

```sh
python3 tools/prepare-ubuntu-apt.py --rootfs out/ubuntu-desktop-pristine/ubuntu-desktop.squashfs \
  --snapshot 20260924T000000Z --output out/apt-dracut --download dracut
```

构建阶段直接使用[官方时间戳快照](https://snapshot.ubuntu.com/)，保持 APT 正常签名/日期校验；
普通系统更新不应永久固定到旧快照。该工具不自动转用滚动镜像，不设置 trusted=yes 或 AllowUnauthenticated。
失败保留 FAILED manifest 和原始日志，不把部分索引当完成的锁。
2026-09-24 首次遇到快照索引 503，失败记录保留；服务恢复后 dracut 的签名索引、依赖解析和三包下载通过。
原始层已安装 dracut 110-11，这是 26.04 的默认 initramfs 工具。先前尝试 initramfs-tools 会移除 dracut，
被 --no-remove 拒绝；现在沿用原生 dracut，不把包名不存在误判为缺少 initramfs 基础设施。
下载结果为 dracut/dracut-core/dracut-install 110-11ubuntu0.1，没有移除包，尚未执行安装。
这只是指定包集的输入锁，不代表整机软件更新完成。

原始底层已有 GDM/GNOME Initial Setup，默认 InitialSetupEnable=true，且没有普通账户。
后续沿用标准首次建用户流程，不预设用户名/密码、自动登录或开放 SSH；实际首次登录仍须启动验收。
原始层还保留 cloud-init 的用户/磁盘/软件源模块。下面的 ext4 装配阶段使用
[标准禁用标记](https://docs.cloud-init.io/en/latest/howto/disable_cloud_init.html)
/etc/cloud/cloud-init.disabled，明确把用户初始化交给 GDM；原始 TAR/SquashFS 仍保持不变。

## 无 Root 的 Ext4 根系统

build-ubuntu-ext4.py 复用已有 TAR 合并器，把小的配置层直接送入上游 mke2fs 的 TAR 输入；
不展开丢失属主的宿主目录、不挂载 loop、不操作块设备。仅移除光盘源、替换官方 ARM64 源配置，
加入 cloud-init 禁用标记。不创建用户、密码、SSH key、调试服务、fstab 或启动分区定义。

需要启用 libarchive 和 NLS 的 mke2fs，以及匹配的 e2fsck；本项目验证的是上游 v1.47.4，
提交 7ee1d505ef3b37831215f490411f346fe57e9053。关闭 NLS 会同时跳过 locale 初始化，导致实际证书的
非 ASCII 链接名被拒绝；不要用改名/转码来处理。构建器显式使用 C.UTF-8。
mke2fs 配置文件作为显式输入参与 hash，不默默依赖宿主 /etc/mke2fs.conf。

```sh
python3 tools/build-ubuntu-ext4.py --tar out/ubuntu-desktop-pristine/ubuntu-desktop.tar \
  --tar-sha256 <该TAR的SHA256> --mke2fs /path/to/mke2fs \
  --mke2fs-config /path/to/mke2fs.conf --e2fsck /path/to/e2fsck \
  --uuid <根文件系统镜像UUID> --size-mib 12288 --output out/ubuntu-ext4
```

输出是新建的普通 ext4 镜像文件和构建 manifest；失败留 .partial，不覆盖已有输出。
UUID、大小只定义这个文件系统产物，不代表已批准的 GPT/双系统布局。
文件系统检查、元数据样本、全部八处 capability、内容样本、硬链接与 Unicode 链接回读通过；
未宣称全文件逐字节比较。该根系统在 QEMU 中用主线 Image 运行了 Ubuntu systemd/指定命令，
但没有启动 GNOME、安装更新/设备包或验证 piano UFS。**不是可直接刷入平板的安装镜像。**

## piano 内核 deb

build-kernel-deb.py 把 build-kernel.sh 的既有 OUT 打成 Debian 二进制包，不编译、不写 OUT；
读取期间持有 OUT 的 .build.lock，Image/DTB/.config 按 build-result.json 核对，
并核对 Image 版本横幅与 include/config/kernel.release 一致。

```sh
python3 tools/build-kernel-deb.py --kernel-source /path/to/linux \
  --kernel-out out/kernel-release --maintainer 'Your Name <your-email>' --output out/kernel-deb
```

`--boot-dtb` 放入经审计的 ABL 打包 DTB（`piano-boot.dtb`），其 manifest 的主线输入须等于本构建的桌面 DTB；
`--boot-dtb-build <旧 build-result.json>` 允许沿用较早构建的已审计 DTB，但仅当两次内核提交之间只改了
`arch/arm64/boot/dts/`、`Documentation/devicetree/bindings/` 和 `arch/arm64/configs/`（驱动代码相同），
包 manifest 的 `boot_dtb.bound_to` 记录该构建与改动路径。

包名沿用上游 builddeb 与 Ubuntu 的 `linux-image-<kernelrelease>`，SOURCE_DATE_EPOCH 取内核提交时间；同输入重建字节一致。
上游 tag 由 `tools/kernel_tag.py` 按该提交顶层 Makefile 的 VERSION/PATCHLEVEL/SUBLEVEL/EXTRAVERSION 得出（如 `v7.2.6`），
须存在且是该提交的祖先；build-kernel.sh 的 OUT 身份与打包器的版本都用它。原先的 `git describe --match 'v[0-9]*'`
会选中内核仓更近的项目 tag `v0.1.0-preview`（指向 piano5），使 piano5 之后的内核全部被打包器拒绝。

**唯一 release。** 可安装内核的 release 为 `<内核版本>-piano<ABI>`（如 `7.2.6-piano1`）：
`arch/arm64/configs/piano-release.config` 最后合并，设 `CONFIG_LOCALVERSION="-piano<ABI>"` 并关闭
LOCALVERSION_AUTO；build-kernel.sh 以空 `LOCALVERSION=` 调用 Kbuild，不再追加未打 tag 时的 `+`，
build-result.json 顶层记录 `kernel_release`。因此每个打包构建有自己的 `/lib/modules/<release>`、
`/boot/*-<release>` 和包名，多个内核可并存（Ubuntu 做法），`linux-version sort` 按 ABI 数值排序。
ABI 是整数：被打包内核的提交或最终 .config 一变（含只改 DTS、换工具链）就取下一个整数，
不复用、不回退、上游版本更新也不归零；MODVERSIONS 关闭时无法检测模块 ABI 破坏，所以每个打包构建都当新 ABI。
`kernel/abi.json` 记录每个已分配 release 对应的内核提交与 .config sha256；build-kernel-deb.py 只打包
其中记录且提交/配置完全一致的 release，未记录时打印应追加的条目，已被另一构建占用时要求升 ABI。
`kernel/source.json` 的 `commit` 是当前钉住的内核提交，其 piano-release.config 决定 release。
包版本为 `<内核版本>-<ABI>.<upload>`（与 Ubuntu `7.0.0-14.14` 的 `<abi>.<upload>` 对应），
upload 只在以不同包内容重新打包同一构建时增加；包 `Provides: linux-image`，各 ABI 之间不冲突。
不带 piano-release.config 的构建保留诊断后缀（如 `7.2.6-piano-diag`），打包器拒绝。
旧版 `7.2.6-piano+` 在 `linux-version sort` 中排在所有 `7.2.6-piano<N>` 之后（更高），与新 release 并存期间
`update-initramfs -u` 仍选中它，而 piano-device-support 现有启动钩子接受任何 `*-piano*` release；
因此迁移需要钩子只认 `-piano<N>` 且只写最新安装的内核，并在从新 ABI 启动后移除旧包。
内容：/boot 的 vmlinuz（未压缩 Image，与 build-result 同 hash）、System.map、config，
/usr/lib/linux-image-<release>/qcom/ 下 build-result 记录的全部 DTB，
以及 /usr/lib/modules/<release>/ 下的内建清单和可选匹配模块。
维护脚本与 linux-update-<release> 触发器取自 Ubuntu 26.04 linux-image 包，只替换版本；
postinst 经 depmod、linux-update-symlinks 和 /etc/kernel/postinst.d 调用发行版钩子（dracut 生成 initrd）。
模块包只拥有匹配 `.ko` 与 Kbuild 清单；`modules.dep/alias/symbols` 等 depmod 缓存由目标系统的 kmod
在 postinst 生成，不将构建机缓存作为不可变包文件交付。包 manifest 的 `modules.files` 只列实际包载荷，
`omitted_depmod_indexes` 记录省略项；完整输入身份仍由 build-result.json 校验。plain RAM 暂存继续保留其验证过的索引。
依赖 kmod、linux-base，推荐 dracut。默认 BUILD_MODULES=0 保留无 .ko 的 RAM 诊断构建。
需要模块时显式使用独立 OUT：

```sh
BUILD_MODULES=1 KERNEL_SOURCE=/path/to/independent/linux \
  OUT_DIR="$PWD/out/kernel-modules" bash tools/build-kernel.sh
```

复用 Kbuild 的 modules/modules_install、目标 strip 和主机 depmod，暂存到 OUT/modules-root；
build/source 主机链接不进入载荷。build-result.json 记录 release、逐文件 SHA、模块数和 depmod 版本。
已有 modules.order 的 OUT 不接受 BUILD_MODULES=0，避免混合构建身份。
打包器消费同一暂存树，核对文件集合、hash、release 和每个模块的 vermagic，再复制到包；
缺收据、错版本/文件/hash/模块数都拒绝。标准暂存树也可供其他发行版配方消费，不依赖 deb。
当前 1087 个模块来自广泛的 ARM64 defconfig，尚不是精简的产品配置。
USB 音频、UCSI GLINK 和 Iris 的依赖闭包已在匹配 Image 的 ARM64 QEMU 中实际加载；
这只验证模块 ABI/注册，不验证对应硬件。Iris DTB 保持独立诊断用途，尚无配套 RAM boot 镜像。
新含模块包的归档/清单检查已通过，原生 APT 安装、发行版 initrd 生成和 piano 实测尚未完成；下述 RAM initramfs 模块交付已单独验证。

此前不含 .ko 的包曾在 ARM64 QEMU guest 中经原生 APT 安装并由发行版钩子生成 dracut initrd，
随后以该 initrd 挂载 ext4 根；没有在 piano 上安装，也不生成或刷写 ABL boot 镜像。
QEMU 中 flash-kernel 因 linux,dummy-virt 在其数据库中而无操作；piano 机型不在该数据库，
按源码其触发器会报 Unsupported platform，产品安装前须明确处理。

## ADSP 独立 RAM 诊断

`CONFIG_FRAGMENT_EXTRA=arch/arm64/configs/piano-adsp-diag.config` 使用独立 OUT，
对应 `sm8750-xiaomi-piano-adsp-diag.dtb`；基础板级保持禁用。
FIRMWARE_DIR 只提供 DSP 锁中 adsp.* / adsp_dtb.* 的 56 个文件（stage-firmware.py 默认从仓库树暂存），放在
`qcom/sm8750/piano/` 下。build-boot 限定 `--diagnostic ncm`，并核其内建依赖、
禁用的 PMIC GLINK/FastRPC/APR 和完整文件清单。不是充电/音频/传感器功能镜像。
离线检查不证明 PAS、DSP 或服务在平板可用。

## 隔离 Mesa 用户态候选

`mesa/source.json` 固定官方 Mesa 26.2.0 源码；`mesa/a830-speedbin.patch` 修正
A830 revision 1 与 drm/msm speedbin 高位的匹配。此候选只用于后续显式诊断，
前缀为 `/opt/piano/mesa-26.2.0`，未替换 Ubuntu 的默认图形软件包。

```sh
MESA_SOURCE=/path/to/pinned/mesa \
CROSS_FILE=/path/to/arm64-cross.ini \
OUT_DIR=/path/to/new/mesa-out JOBS=4 tools/build-mesa.sh
```

前置：Meson 1.9、Ninja、Mako、PyYAML、Python packaging、Bison/Flex、原生 glslangValidator，
完整 ARM64 GCC/G++ 交叉工具链，以及显式 sysroot 的 Meson cross file。
本轮目标依赖取自 Ubuntu 26.04 ARM64 签名快照：libdrm、zlib、zstd、expat、Wayland 1.24/
wayland-protocols、X11/XCB 开发包；注意单独的 libwayland-egl-backend-dev 与 libx11-xcb-dev。
Wayland scanner 须满足目标依赖版本；可用目标包的 scanner 经 qemu-aarch64 执行。
所有包仅下载/解包到构建目录，不在主机安装。具体 sysroot/工具包身份由构建调用方锁定；
这不是跨任意工具版本的完整产品发布锁。

构建器从固定 commit 导出到 OUT_DIR/source 后应用唯一补丁，在 stage 下安装并生成 manifest。
包含 Freedreno/Turnip、EGL/GLES/GLX/GBM、X11/Wayland 和 softpipe；GLVND 关闭是此隔离诊断的边界。
默认产品须另行收敛原生设备包、GLVND、APT 升级和软件回退，不直接覆盖 /usr/lib。

`mesa/check-device.c` 应链接实际 Mesa freedreno_dev_info.c 与生成表，验证已知速度档及未知 ID。
`mesa/egl-smoke.c` 应用目标交叉编译器及 stage/include、stage/lib 编译，链接 EGL/GLESv2；
链接时同时提供 stage/lib 与目标系统库的 rpath-link。运行可传必需的 renderer 子串，
例如 `Adreno`，使软件渲染回退不能被当作 GPU 通过。
本轮 ARM64 QEMU 的 softpipe 着色器/三角形回读通过，尚未在 piano 验证 A830 渲染、Vulkan 或 GNOME 合成。

## 独立的固件暂存与 HexagonRPC 修复

固件的文件校验/复制在 `tools/firmware_payload.py` 维护，deb 构建器与纯文件暂存入口复用它。
不带 --firmware-dir 时从仓库 firmware/ 暂存内核加载的 ADSP 两个 MDT 及其分段（56 个文件）；
--firmware-dir 指向本机原厂 modem image 目录时，默认暂存锁中全部 76 个 DSP/服务映射文件，可用 --image 选择：

```sh
python3 -S tools/stage-firmware.py --output /path/to/new/output
python3 -S tools/stage-firmware.py --firmware-dir /path/to/own/modem/image \
  --image adsp.mdt --image adsp_dtb.mdt --output /path/to/new/output
```

该入口只需 Python 标准库；输出 `root/usr/lib/firmware/qcom/sm8750/piano/` 和清单，
不安装包或启用服务。失败不发布输出目录，已有输出不会被覆盖。
initramfs 构建器可使用 `FIRMWARE_DIR=/path/to/output/root/usr/lib/firmware`；
另一发行版的包配方可以消费同一文件树，包元数据与生命周期由其原生工具处理。
本轮与旧版 deb、P23 ADSP 子集分别逐字节比对通过；没有重新安装或改变冻结候选。

[HexagonRPC 来源与构建](../device/sensors/hexagonrpc/README.md)提供固定上游版本、两个局部修复和回归。
沿用上游 Meson，主机 ASan/UBSan 与 ARM64 qemu-user 均为 14/14 通过；真实 FastRPC/SSC 输入仍待本机验证。

## 独立暂存模块子集

`kernel_modules.py` 是内核 deb 与 plain 暂存的唯一收据验证实现；不依赖 python-debian/APT。
`stage-kernel-modules.py` 复用 kmod 的 `modprobe --show-depends`，不自己实现模块依赖算法、也不在主机加载模块。
输入为 BUILD_MODULES=1 的匹配构建，输出为独立 `lib/modules/<release>` 根目录及 module-manifest.json。
只复制显式根模块及依赖，保留对应 built-in 清单、用 depmod 重建子集索引。

```sh
python3 tools/stage-kernel-modules.py --kernel-out out/kernel-modules \
  --output out/usb-role-modules \
  --module qcom_q6v5_pas --module qcom_pd_mapper --module qrtr_smd \
  --module ucsi_glink --module usbhid --module usb_storage --module snd_usb_audio \
  --forbid-module qcom_battmgr --forbid-module pmic_glink_altmode --forbid-module fastrpc
```

mic 子集的显式根为 qcom_q6v5_pas、qcom_pd_mapper、qrtr_smd、snd_soc_sc8280xp、snd_soc_lpass_tx_macro、
snd_soc_lpass_va_macro、pinctrl_sm8650_lpass_lpi、q6prm_clocks、q6apm_dai、q6apm_lpass_dais；
除上述 forbidden 三项，另禁止 pmic_glink。它们只是实验模块集合，不是新服务或产品自动加载策略。

暂存持有 OUT 共享锁，核 Image/config、所有模块的 hash/vermagic；禁止模块包括间接依赖，拒绝未知模块与已有输出。
输出 manifest 保存源码/内核/配置身份与相对文件 hash，不包含构建主机路径。
实际 USB 25 个、录音 36 个模块的子集在 ARM64 QEMU 中通过 BusyBox modprobe 加载，禁止项未出现；
这只证明子集完整和匹配内核 ABI，不验证本机 ADSP/UCSI/录音。
输出尚未包含固件或 boot 镜像。产品继续交给发行版 initrd/设备发现机制，不把这个实验集合当永久产品配置。

## 模块进入 RAM 诊断与 Ubuntu 临时根

`build-initramfs.sh` 可选 `MODULES_DIR=<stage-kernel-modules 输出>`。它验证完整子集、复制到构建临时快照，
把 JSON 身份、可读 checksum、release、显式根模块名单和标准 modprobe blacklist 纳入镜像身份。
不启用自动模块加载；`/bin/piano-modules check` 校验运行 release/文件，`load MODULE` 只允许清单中的根模块，
调用原生 BusyBox modprobe 并记入 `/run/piano-modules.log`。没有自制依赖解析、重试或设备管理服务。

```sh
MODULES_DIR=/path/to/verified/mic-modules FIRMWARE_DIR=/path/to/private/mic-firmware \
BUSYBOX=/path/to/pinned/busybox GEN_INIT_CPIO=/path/to/gen_init_cpio \
OUT_DIR="$PWD/out/initramfs-mic" bash tools/build-initramfs.sh
```

Ubuntu RAM 交接复用同一个 helper，将模块置于 `/usr/lib/modules/<release>`，同时保留 checksum、
固件 manifest、临时 blacklist 和与 BusyBox 同目录的 `/usr/local/libexec/piano/modules`。
已有相同 release 的根目录拒绝混合；这里的策略属于 RAM 诊断，产品使用发行版包/initrd/设备发现机制。
两种 helper 路径都只在显式诊断中存在；核心硬件驱动不依赖 Ubuntu、APT、GDM 或固定账号。

boot 打包器核对实际模块/固件字节、所用 Image/config/完整模块收据，不能仅凭清单文本放行。
`initramfs_archive.py` 只读取本构建器的单段 newc，拒绝拼接覆盖、非规范路径、重复项、硬链接和非目录父项；
不支持任意发行版 initrd 的格式。标准 GNU cpio 的首段读取和预读不能证明 Linux 最终展开结果一致，因此未用它作为完整性判据。
没有 MODULES_DIR 时不注入模块 helper/策略，旧候选文件不被改写。

mic 探测要求 `device/audio/diagnostic.json` 对应的拓扑与 56 个 ADSP 文件、精确模块集合和延后加载配置。
主机 runner 必须显式 `--load-modules`：先取得 build-id/FDT/模块基线，再按固定顺序加载，最后回收
module-load、/proc/modules、ALSA cards/PCM 和 remoteproc/rpmsg 状态。加载成功不等于声卡或录音成功。
P23 的 DSP 基础验证仍在前；新候选仍需现场恢复条件和原厂电量准入。

本轮离线验证覆盖真实 ARM64 helper、merged-/usr 复制、交互式串口上的主机编排与 60 秒退出；
另用只读原始 Ubuntu 根验证 systemd 交接、原生 kmod blacklist/显式加载和逐文件校验。
Ubuntu 的检查单元只属于 QEMU fixture，不注入真实候选。QEMU 不证明物理 DSP、USB、声源录音或平板恢复。


## QEMU USB 生命周期测试配置

内核 piano-usb-loopback-test.config 只给独立软件测试 OUT 启用 dummy_hcd/CDC NCM 模块，
不能用于平板；build-boot 要求 CONFIG_USB_DUMMY_HCD 未启用，并用实际测试 OUT 验证拒绝。
它不改变产品驱动归属或 USB 板级参数。项目内核当前包含 device_move 成功路径的 glue-dir 引用释放修正；
ARM64 设备模型测试与软件 NCM 注销/重挂接数据验证通过，物理 DWC3/Type-C/供电仍未验证。

## 合并桌面诊断与隔离 Mesa

`piano-desktop-diag.config` / `sm8750-xiaomi-piano-desktop-diag.dtb` 合并已有输入、BT、GPU、
ADSP/音频基础和电量计；仍是 RAM 开发配置，UFS 写入、PCIe/WLAN、USB host/DP 未启用。
使用 `BUILD_MODULES=1`，通过 stage-kernel-modules 交付与该 Image/config 匹配的显式子集。
WLAN 模块纳入不意味着无线网络已可用；蓝牙/音频/其他功能支持范围以 README 为准。

可为 build-initramfs.sh 显式设置 `MESA_DIR=<build-mesa.sh 的输出目录>`，将锁定的 Mesa
安装到 RAM 根的隔离 `/opt/piano` 前缀。输入必须包含原构建 manifest 与 stage；脚本核对
mesa/source.json、补丁 hash、全部文件内容和符号链接边界，并将清单绑定进 RAM build-id。
build-boot 只允许该载荷与合并 desktop-diag 配对，逐文件核实际 CPIO 字节。
prepare-ubuntu 在原生 GDM 启动前通过标准环境配置选择此栈，不覆盖发行版库，也不修改原始根。
这仍是显式诊断策略；发行版覆盖 A830 后应撤销，产品交付需按原生 Mesa 包收敛。

`MAINTENANCE_DIR=<prepare-maintenance-payload.py build 的输出>` 构建维护 initramfs（`piano.diag=maintenance`）：
载荷含取自锁定桌面 SquashFS 的 Ubuntu `sgdisk`/`sfdisk`/`lsblk`/`partx`/`blockdev` 及其库、内核包的两个 reboot-mode 模块和
基于内核 nolibc 的 `restart2`；`stage` 子命令逐文件核对清单后输出 cpio 行，不与 `FIRMWARE_DIR`/`MODULES_DIR` 组合。
`build-persistent-boot.py --maintenance` 由它生成 `boot-ram-maintenance.img`，命令见 [AGENT-GUIDE.zh-CN.md](AGENT-GUIDE.zh-CN.md) §4.6；
`MAINTENANCE_INITRAMFS=... python3 tools/test-maintenance-initramfs.py` 检查归档内容、ELF 依赖闭包和看门狗逻辑。
