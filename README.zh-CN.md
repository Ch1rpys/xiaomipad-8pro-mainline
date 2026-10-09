# Ubuntu on Xiaomi Pad 8 Pro (piano)

[English](README.md)

本项目为小米平板 8 Pro（代号 `piano`，高通 SM8750P）提供主线系 Linux 7.2.y 与 Ubuntu 26.04 LTS
GNOME 桌面，与 Android 共存。两个系统都从当前活动的 A 槽启动：切换时在 Fastboot 下写入另一系统的
`boot`、`init_boot` 和 `vendor_boot` 镜像。本仓库是集成层，包含构建与打包工具、设备用户态和 Ubuntu
集成；内核在独立仓库维护。本项目面向能够通过 Fastboot 自行恢复设备的开发者和有经验的用户。首版中，
安装后的系统可启动到 GNOME，显示、触控和 GPU 加速可用；Wi-Fi 与电池充电尚不可用。

## 支持矩阵

以下为[前提条件](#前提条件)所述测试机截至 2026-10-08 的状态。测试配置、已知问题与路线图见
[docs/STATUS.md](docs/STATUS.md)（英文）。

**可用**：功能正常 · **部分可用**：在所列限制内可用 · **未验证**：已启用，功能未验证 ·
**尚未支持**：未启用 · **不支持**：不在项目范围内

| 组件 | 状态 | 说明 |
|---|---|---|
| 启动（ABL、AVB） | 部分可用 | ABL 从 A 槽启动 v4 `boot`/`init_boot`/`vendor_boot` 镜像组。AVB footer 用设备所有者的密钥签名，只有已解锁的引导程序接受；不修改 `vbmeta`。主机 Fastboot 安装后，ABL 会递减 A 槽的重试计数，直到该槽被标记为启动成功。`piano-slot-success` 在每次持久 Ubuntu 启动后标记该槽；尚未在设备上验证，未标记时若不重置，约 7 次 Ubuntu 启动后该槽将不可启动。 |
| 显示 | 部分可用 | 3200×2136、120 Hz，经 simpledrm 使用引导程序的帧缓冲（固件扫描输出）。没有原生 MDSS/DSI/面板驱动：亮度保持引导程序设定，不能关屏或唤醒。触控运行时出现过偶发整屏闪烁。 |
| GNOME 桌面 | 可用 | Ubuntu 26.04 GNOME（Wayland，GDM），GPU 合成，200 % 缩放。 |
| GPU | 可用 | Adreno 830（msm DRM），OpenGL ES 由 Mesa 26.2.0 加一个补丁提供，打包为 `piano-mesa`。Ubuntu 自带的 Mesa 26.0.3 不支持 A830。Vulkan、持续负载与 GPU 电源管理未验证。 |
| 触摸屏 | 部分可用 | Novatek NT36532E，经 SPI 由主机侧处理（`piano-thp`，使用本机标定）。单指输入与方向正确。长按无效；多指、边缘精度与电源管理未验证。 |
| 手写笔 | 尚未支持 | 触控启动时关闭笔扫描。 |
| 磁吸键盘 | 部分可用 | 小米键盘经 Nanosic WN8030 I2C 桥接（`hid-nanosic`），按键可用。拔插重连与电源管理未验证。所测键盘没有触摸板。 |
| 电源键 | 部分可用 | 按键事件可送达 logind；不能关屏或唤醒。音量键未验证。 |
| 蓝牙 | 部分可用 | WCN7860（UART）：固件加载、上电与设备扫描。配对、音频及与 Wi-Fi 共存未验证。 |
| Wi-Fi | 尚未支持 | WCN7860 位于 PCIe（ath12k）。在确定本板 PHY 供电映射之前，PCIe 保持关闭。 |
| 扬声器 | 尚未支持 | 四颗 FS19xx 系列功放没有主线驱动，没有播放设备。 |
| 麦克风 | 未验证 | 内置 DMIC 经 ADSP（AudioReach）：声卡与录音 PCM 已注册，但该 PCM 没有后端 DAI。录音未验证，没有 UCM 配置。 |
| 电量计、温度 | 可用 | 两颗 BQ27Z561 报告电量、电压和电流；温区可读。温控限频未验证。 |
| 充电 | 尚未支持 | 没有充电驱动。Linux 下即使接 USB 电池也在放电，需回 Android 充电。 |
| 挂起 | 尚未支持 | 在挂起/唤醒验证通过前，由策略禁用（systemd `sleep.conf.d`、GNOME 空闲动作覆盖）。 |
| 休眠到磁盘 | 不支持 | 分区布局中没有 swap 分区。 |
| 实时时钟 | 尚未支持 | PMIC RTC 不可写，每次启动后时间错误，需手动设置。 |
| 内部存储 | 可用 | UFS；ext4 根分区（60 GiB）与 `/home`（约 201 GiB）。 |
| USB 设备模式 | 部分可用 | USB 2.0 NCM gadget 用于调试镜像。正式镜像默认不提供任何 USB 功能，管理员开启[开发者模式](device/devmode/README.md)（经 USB 的 SSH，默认关闭，尚未在设备上运行）后才提供。 |
| USB 主机、Type-C 角色 | 尚未支持 | 未启用 Type-C 角色切换（UCSI）。 |
| 外接显示 | 尚未支持 | DisplayPort Alt Mode 依赖原生显示驱动；DP 与 DIO4485 SBU 开关节点处于禁用状态。 |
| 视频解码 | 尚未支持 | Iris（VPU35）已编译为模块，未启用。 |
| 传感器 | 尚未支持 | 旋转、光感和霍尔传感器位于 ADSP 传感器中枢（SSC）之后；用户态栈已准备，未启用。 |
| 摄像头 | 尚未支持 | 后摄 S5KJN1SQ03、前摄 OV32D40；主线缺少 SM8750 CAMSS 支持。 |
| 指纹 | 尚未支持 | 没有驱动。 |

## 前提条件

- **设备：** 小米平板 8 Pro（`piano`，SM8750P）。测试机型号 25091RP04C（中国版），16 GB 内存、512 GB
  UFS。其他版本与容量未验证；下文布局按 512 GB 计算。
- **原厂版本 OS3.0.303.0.WPYCNXM。** `firmware/` 中的固件锁固定该版本的文件名与哈希；启动镜像沿用该版本的
  头部字段（OS 版本、安全补丁级别）、回滚索引和 AVB 属性，缺少这些字段时 ABL 会把槽标记为不可启动；
  启动 DTB 针对该版本的原厂 DTB 与 DTBO 准备，ABL 启动时会叠加 DTBO。测试机 B 槽是旧版原厂链，不能启动
  Android，因此 B 槽不能作为后备。
- **已解锁的引导程序**（小米官方流程）；不支持锁定状态。
- **备份：** 任何写入前，备份除 `userdata` 外的全部分区及每个 UFS LUN 的 GPT；读取分区需要 Android 下的
  root 权限。A 槽原厂的 `boot`、`init_boot`、`vendor_boot` 即用于切回的 Android 镜像组。
- **离开 Android 前电量不低于 40 %。** Linux 下不能给电池充电。
- **主机：** 带 `fastboot`、`adb` 与 Python 3 的 Linux（见[从源码构建](#从源码构建)）。

## 安装内容

| 分区（UFS LUN 0） | 容量 | 内容 |
|---|---|---|
| `userdata` | 200 GiB | Android 数据，重建为空 |
| `linux_rootfs` | 60 GiB | Ubuntu `/`，ext4 |
| `linux_data` | 余量，约 201.27 GiB | `/home`，ext4 |

- 三个分区占用原 `userdata` 的范围；其他 GPT 条目和其他 LUN 不变。`userdata` 与 `metadata` 被清除后由
  Android 重建，Android 数据全部丢失。
- **活动槽镜像组轮换：** A 槽存放 Android 或 Ubuntu 的镜像组之一，另一组作为带校验和的文件保存。
  `vbmeta`、`dtbo`、B 槽和固件分区从不写入。
- **Ubuntu 镜像组：** `boot.img`（内核、含根分区 PARTUUID 的命令行）、`init_boot.img`（空 ramdisk）、
  `vendor_boot.img`（发行版 dracut initrd、写入本机蓝牙地址的启动 DTB），大小与原厂分区一致（96、8、96 MiB）。
- **镜像位置：** 主机构建目录保存镜像、`SHA256SUMS` 和 `manifest.json`。安装后的系统中，内核 postinst
  钩子 `piano-boot-update` 在内核或 initrd 更新后于 `/var/lib/piano/switch/ubuntu/` 重建 Ubuntu 镜像组
  （上一组移到 `ubuntu.prev/`），A 槽为 Ubuntu 组时原位重写该槽；Android 镜像组保存在
  `/var/lib/piano/switch/android/`。存储布局见 [device/boot/README.md](device/boot/README.md)。
- **软件包：** `linux-image-7.2.6-piano2`（每次打包唯一 release，ABI 见 `kernel/abi.json`）；`piano-device-support`（启动钩子、槽切换与启动成功标记、
  触控服务、平台辅助程序、挂起策略）；`piano-local-firmware`（设备固件，仅限本地使用）；`piano-mesa` 与 `piano-ubuntu-desktop`
  （Mesa 环境、显示缩放）。

## 安装

分区与根文件系统安装器尚未公开（见[路线图](docs/STATUS.md#roadmap)）。
安装由以下步骤组成：

1. 按[前提条件](#前提条件)完成备份。
2. 用本机输入构建内核、软件包、根文件系统和 Ubuntu 镜像组。
3. 在 RAM 启动的 Linux 环境（`fastboot boot`）中，按 UFS 控制器、LUN、GPT GUID、label 和几何确认目标：
   `sdX` 盘符在不同启动间会变化，备份文件名也不是设备名。改写 LUN 0 的 GPT（先备份 GPT），清除
   `userdata` 与 `metadata`，写入根文件系统，并在设备上直接创建空的 `/home` 文件系统。空 ext4 的稀疏镜像
   会把零块编码为 FILL 块，设备仍会完整写入。
4. 用 `tools/piano-switch.py` 把 Ubuntu 镜像组写入 A 槽。

### 切换与恢复

`tools/piano-switch.py` 在主机上于 Fastboot 模式运行：核对产品、解锁状态、当前槽和分区大小，按
`SHA256SUMS` 校验两组镜像，依次写入 `init_boot_a`、`vendor_boot_a`、`boot_a`，任一步失败即写回回滚组。
三次写入不是原子操作；切换中途断电可能需要从主机恢复。

```sh
# 切到 Android：在 Ubuntu 中关机，再长按电源 + 音量下进入 Fastboot。
python3 tools/piano-switch.py --serial <serial> --images <android-set> --rollback <ubuntu-set>
fastboot -s <serial> reboot

# 从 Android 切到 Ubuntu：
adb -s <serial> reboot bootloader
python3 tools/piano-switch.py --serial <serial> --images <ubuntu-set> --rollback <android-set>
fastboot -s <serial> reboot
```

在 Ubuntu 中，应用网格里的 **切换到 Android**（或 `sudo piano-boot-switch to-android --reboot`）以同样的
校验、整分区读回和回滚写入 `/var/lib/piano/switch/android/` 中的 Android 组，然后重启。尚未在设备上验证，
见 [device/boot/README.md](device/boot/README.md)。

- **无画面或无响应：** 长按电源 + 音量下进入 Fastboot，切回 Android。正式镜像没有调试控制台。
- **停在 Fastboot 且 `slot-unbootable:a` 为 `yes`：** 执行 `fastboot -s <serial> --set-active=a` 重置 A 槽
  的重试计数。在测试机上该命令同时提高了 B 槽优先级；B 槽仍不可用。
- **不写分区的诊断：** 调试构建（`build-persistent-boot.py --debug --debug-timeout <秒>`）另外生成
  `boot-ram-check.img`，供 `fastboot boot` 使用。它启动已安装的系统，经 USB NCM（192.168.88.2，端口
  2323）提供无认证的 root shell，超时后回到 Fastboot。
- 不要刷写 `vbmeta`、写入 B 槽或激活 B 槽。该布局下的 Android OTA 更新未验证。

## 从源码构建

| 输入 | 锁定方式 |
|---|---|
| 内核 | [`kernel/source.json`](kernel/source.json)：`piano/dev` 分支上的提交，基于 v7.2.6 |
| 内核配置 | `piano-diagnostic.config` + `piano-desktop-diag.config` + `piano-persistent.config`，启用模块；DTB 为 `sm8750-xiaomi-piano-desktop.dtb` |
| Ubuntu | 官方 26.04 Desktop ARM64 ISO，SHA-256 `c2afd538d66fdd77377d03f1ed2ac76a34f1c116baecc9a8170d68f833121f57`；[`ubuntu/26.04.sources`](ubuntu/26.04.sources)；APT 输入取自 snapshot.ubuntu.com 时间戳快照 |
| Mesa | [`mesa/source.json`](mesa/source.json)（26.2.0）与 `mesa/a830-speedbin.patch` |
| AOSP 工具、BusyBox | `tools/fetch-aosp-mkbootimg.sh`（固定提交）、`tools/fetch-busybox-arm64.sh`（Ubuntu 软件包）；AOSP `external/avb` 的 `avbtool` 尚无获取脚本，经 `--avbtool` 传入 |
| 其他用户态 | `device/*/source.json`、`ubuntu/systemd/source.json` |

| 领域 | `tools/` 中的工具 |
|---|---|
| 内核 | `build-kernel.sh`（镜像、DTB、模块、`build-result.json`）；`build-kernel-deb.py`（`linux-image` 包，其 Ubuntu 维护脚本调用 dracut） |
| 启动 | `prepare-boot-dtb.py`（带 ABL 所需原厂 overlay 符号的启动 DTB）；`build-persistent-boot.py`（签名的 v4 镜像组与 v2 RAM 检查镜像）；`piano-switch.py`（带回滚的切换） |
| Ubuntu 根 | `prepare-ubuntu-desktop.sh`、`merge-desktop-tars.py`、`prepare-ubuntu-apt.py`、`build-ubuntu-ext4.py`（官方层、签名 APT 输入、ext4 镜像，均无需 root 权限） |
| 用户态 | `build-mesa.sh`；`extract-thp-calibration.py`；`build-firmware-deb.py`、`stage-firmware.py`（DSP 固件）；`build-device-debs.py`（四个 `piano-*` 包） |
| 诊断 | `build-boot.py`、`build-initramfs.sh`、`prepare-module-initramfs.py`（有界 RAM 镜像） |

```sh
CONFIG_FRAGMENT_EXTRA="arch/arm64/configs/piano-desktop-diag.config arch/arm64/configs/piano-persistent.config" \
BUILD_MODULES=1 KERNEL_SOURCE=/path/to/linux OUT_DIR="$PWD/out/kernel-persistent" bash tools/build-kernel.sh

python3 tools/build-persistent-boot.py --kernel <Image> --dtb <boot.dtb> --initrd <initrd> \
  --profile <boot-profile.json> --mkbootimg tools/local/aosp-mkbootimg/mkbootimg.py \
  --avbtool <avbtool.py> --key <signing-key.pem> --root-partuuid <linux_rootfs PARTUUID> \
  --bt-address-file <bluetooth-address> --output out/ubuntu-boot
```

详细构建说明（含 RAM 诊断）：[docs/build.zh-CN.md](docs/build.zh-CN.md)。

**本机输入**取自设备所有者自己的设备，从不提交（`.gitignore` 已排除其常用文件名）：

- **固件**，取自同一原厂版本：ADSP/CDSP（`adsp*`、`cdsp*`；锁 `firmware/piano-os3.0.303.0.json`）、GPU
  （`gen80000_sqe.fw`、`gen80000_gmu.bin`、`gen80000_aqe.fw`、设备签名的 `gen80000_zap.mbn`；锁
  `firmware/piano-gpu.json`）、蓝牙（`gngbtfw20.mbn`、`gngbtnv20.*`；锁
  `firmware/piano-bluetooth-rom20.json`）、触控（`novatek_nt36532_piano_fw_csot.bin`）和键盘桥接
  （`MCU_Upgrade.bin`）。再分发许可未确立，生成的固件包只能本地使用。
- **触控标定**，从原厂 `piano_nova_csot_thp_config.ini` 提取。
- **蓝牙地址**，取本机地址；缺少时控制器保留 NVM 默认值，处于未配置状态。
- **启动配置（boot profile）：** 原厂 `boot`、`init_boot`、`vendor_boot` 的头部几何、容量、回滚索引、AVB
  属性及观测到的活动槽。生成工具属于尚未公开的安装器。
- **原厂 DTB 与 DTBO**（供 `prepare-boot-dtb.py`）；设备所有者自行生成的 **AVB 签名密钥**（RSA-4096）。

**可复现性：** 相同输入构建的内核包逐字节一致。`init_boot.img` 随 Python 版本变化（空 ramdisk 的 gzip
头 OS 字节在 Python 3.12 下为 0x03，在 3.14 下为 0xff；两者功能相同）。dracut initrd 不可复现，因此
`vendor_boot.img` 在不同构建间不同。`CONFIG_MODVERSIONS` 关闭：内核镜像与模块须来自同一次构建。

## 仓库结构

```
device/      设备用户态：启动集成、触控处理（piano-thp）、平台身份辅助程序、音频拓扑、QRTR 与传感器栈
docs/        状态页与构建说明
firmware/    用户自备固件的身份锁（文件名、大小、SHA-256），不含固件字节
initramfs/   RAM 诊断 initramfs：USB NCM 控制台、Ubuntu RAM 根、模块交付
kernel/      source.json：内核仓库锁定
mesa/        Mesa 源码锁、A830 补丁与设备检查程序
packaging/   piano-device-support 安装的文件
tools/       构建、打包与切换工具
ubuntu/      APT 源与 systemd 源码包覆盖
LICENSES/    第三方许可证文本
```

三个仓库职责分离：**集成仓**（本仓库：工具、设备用户态、Ubuntu 集成、输入锁和文档）；**内核仓**
（`linux-sm8750-piano`，`piano/dev` 分支：在上游 stable 历史之上维护驱动、设备树、binding 与配置；
`kernel/source.json` 锁定提交，并在公开后记录其地址）；**本机输入**（固件、标定、蓝牙地址、启动配置、
签名密钥、备份），归各设备所有者所有，从不提交到任一仓库。

## 路线图与上游化

已知问题、路线图与上游化状态见 [docs/STATUS.md](docs/STATUS.md)。尚未向上游提交任何补丁；候选包括
driver core、Adreno 电源投票、simpledrm、DIO4485 Type-C、PMIC GLINK Alt Mode 与高通 ASoC 的修复，
以及 NT36532E 触控与 Nanosic 键盘驱动。

## 参与贡献

见 [CONTRIBUTING.md](CONTRIBUTING.md) 与 [AGENTS.md](AGENTS.md)。硬件报告应注明设备型号、原厂版本、内核
提交与镜像组身份，并去除序列号、蓝牙地址、标定数据和个人信息。问题跟踪与公开远端尚未建立。

## 致谢与许可

本项目复用并改编了以下工作：
- 一加平板 2 Pro（`erhai`，SM8750P）主线集成项目：启动镜像、initramfs、RAM 根与桌面层工具（GPL-2.0-only；
  尚无公开地址）；
- 小米平板 6 Pro（`liuqin`）主线项目：AOSP 与 BusyBox 获取脚本、Desktop 层准备、iio-sensor-proxy 补丁及
  `hid-nanosic` 的 HID 传输（MIT）；
- ROCKNIX 与 Teguh Sobirin：WCN7860 Wi-Fi、蓝牙与上电时序提交，SM8750 GPU 时钟节点，以及 Mesa A830 chip ID
  参考；
- 高通（Jie Zhang、Akhil P Oommen、Gaurav Kohli）：Adreno 830 支持；Junjie Cao：NT36532 面板驱动；
  Alexander Koskovich 与 Jonathan Marek：DSC 支持；
- Novatek 触控来源：小米 `vendor_xiaomi_proprietary_touch-driver`（GPL-2.0，Novatek）用于内核 THP 传输，
  ianchb 的 `xiaomi-sheng-thp`（Apache-2.0）用于 `piano-thp` 的手指处理；map220v：WN8030 键盘固件编码；
- AOSP `mkbootimg`（Apache-2.0）与 `avbtool`（MIT）；Mesa（MIT）；linux-msm `hexagonrpc` 与 `qrtr`；
  libssc；iio-sensor-proxy；AudioReach topology；TinyALSA；systemd；BusyBox；Ubuntu。

各文件的来源、提交与改动记录在 [NOTICE](NOTICE)。除文件 SPDX 头另有声明外，原创集成代码采用
[MIT](LICENSE)；若干改编自 GPL-2.0-only 来源的工具保持 GPL-2.0-only。内核为 GPL-2.0。第三方组件保留各自
许可（见 `LICENSES/`）。固件归各自权利人所有，不随本项目分发，也不受上述许可覆盖。
