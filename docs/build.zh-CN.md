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
kernel/source.json 相符。项目内核远端尚未建立，当前不能仅从 stable 上游获取包含本地配置的提交。

## 诊断内核

```sh
KERNEL_SOURCE=/path/to/independent/linux OUT_DIR="$PWD/out/kernel-diag" JOBS=8 \
  bash tools/build-kernel.sh
```

配置仅在内核仓 arch/arm64/configs/piano-diagnostic.config 维护。
每次增量构建先运行原生 olddefconfig，处理源码新增的 Kconfig 项；片段变化时才重新生成/合并基线。
生成 Image、sm8750-xiaomi-piano.dtb、sm8750-xiaomi-piano-thp-diag.dtb、最终 .config、日志与 build-result.json。
后者是有人监督触控诊断用的变体，只额外启用 gpi_dma1、spi2 和触控节点；默认 piano DTB 仍禁用它们，硬件未验证。
当前 DTS 仅用于 RAM 启动与日志；P03 增加 USB2 固定设备模式，显示、UFS 和远程处理器保持关闭。
USB 尚未真机验证；电源输入拓扑、REFGEN 和完整 Type-C 路径仍未闭合，不用于冷启动/低功耗产品验收。
日常保持同一 OUT 增量构建；换工具链或基线时使用新 OUT。
构建输出锁避免并发写入，输入 commit/配置和输出 hash 可核查。
源码现含回移的上游 NT36532 框架，但尚无 P81 面板 profile；默认诊断配置未启用该驱动。

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
USB 使用 ABL 的 androidboot.serialno 生成 piano-<serial> 标识；无该参数时保留 QEMU 的 piano-diag，
主机实验不能将匿名标识当已绑定的实体设备。ACM 需要 tty 权限；NCM 使用主机已有自动 DHCP，不需要更改串口权限。
NCM 短诊断与后续多 GB Ubuntu 根传输分别已有真机记录，不能相互替代各自验证范围。
早于 PID1 的卡死不受用户态计时器保护，第一次测试需要人在设备旁边；不能保证自动恢复。
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

## 本地 DSP 固件包

build-firmware-deb.py 接受用户自行取得的同版 modem/image 文件，不下载或分发固件。
firmware/piano-os3.0.303.0.json 是 OS3.0.303.0.WPYCNXM 的输入身份锁：72 个 ADSP/CDSP
加载文件和 4 个服务域描述；不读取 persist 或用户私钥，不打包 Wi-Fi BDF 或触控算法。
只使用 dpkg-deb 标准格式，保留原始字节，不安装、不执行 blob，也不附带刷写/服务脚本。

需要 Python 3、python3-debian 和 dpkg-deb（支持 --root-owner-group / --threads-max）。

```sh
python3 tools/build-firmware-deb.py \
  --firmware-dir /path/to/own/stock/modem/image \
  --maintainer 'Your Name <your-email>' --output private/firmware-package
```

输出包只写 /usr/lib/firmware/qcom/sm8750/piano 和自身文档目录，不覆盖发行版通用固件。
后续 DTS 的 firmware-name 必须显式选择这个目录，包构建成功不等于 PAS 认证或 DSP 启动成功。
当前原厂字节的再分发许可尚未确认；代码可开源，生成的 deb 不得随公开仓发布。
包归档全文件 hash、root 属主/权限、md5sums 和同输入重复构建已离线验证。
构建器按 Debian 的 KiB 估算规则填写 Installed-Size，当前锁定输入为 38427 KiB；
补齐字段前后的 data.tar 完全相同，避免 APT 将固件空间误估为零。目标根镜像/平板尚未安装此包。

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
