# 离线构建

这些入口准备 piano 最小板级内核、RAM 诊断候选和原始 Ubuntu Desktop 层。
P01 已进行单次 RAM 实测，失败于厂商 ABL 的 overlay 合成，尚未完成主线交接。
它不是可安装系统；不提供安装器，也不使用 QRD/MTP DTB 试机。

## 主机

使用 Linux x86_64、Git、Python 3、GCC、AArch64 GNU 交叉编译器、make、bison、flex、
pkg-config、OpenSSL/ELF 开发库、gzip、sha256sum、flock；ccache 可选。
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
生成 Image、sm8750-xiaomi-piano.dtb、最终 .config、日志与 build-result.json。
当前 DTS 仅用于 RAM 启动与日志；USB、显示、UFS 和远程处理器保持关闭。
日常保持同一 OUT 增量构建；换工具链或基线时使用新 OUT。
构建输出锁避免并发写入，输入 commit/配置和输出 hash 可核查。

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
ramdisk 无板级固件、存储挂载、账户或网络配置；ACM 是实验用 root console，不进入默认产品。
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
  --mkbootimg tools/local/aosp-mkbootimg/mkbootimg.py --output out/ram-boot
```

prepare-boot-dtb 只导出指定 DTBO 引用的符号，指向 disabled 父节点下的隔离区；
真正用 libufdt 合成并确认既有主线硬件属性不变。它不改内核 DTS，不导入整份原厂符号表，
也不修改平板上的 DTBO。根 compatible/model 仍可能被原厂 overlay 覆盖，运行时 ABL/Gunyah
追加内容仍须真机验证，不能将离线合成结果称为实际运行 FDT。
2026-09-24 的 P01 已证明当前离线验证不够覆盖 ABL 行为；具体合成差异尚未定位，不应原样反复试机。

build-boot 使用本机原厂 RAM 探针已接受的 header v2 容器，固定为 pstore-only 首测：
60 秒 PID1 重启计时器、panic=15、不启用 USB 用户态、无存储驱动。
早于 PID1 的卡死不受用户态计时器保护，第一次测试需要人在设备旁边；不能保证自动恢复。
它只生成 boot-piano-ram.img 和精确输入/输出 manifest，不执行 Fastboot。

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
