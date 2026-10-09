# Ubuntu for Xiaomi Pad 8 Pro

在小米平板 8 Pro（`piano`，SM8750P）上与 Android 双系统运行 Ubuntu 26.04 LTS GNOME 桌面，内核基于上游 Linux 7.2 适配。[English](README.md)

## 最新版本与近期更新

**v0.1.0-preview** 正在准备中，尚未发布任何版本。发布内容包括 Ubuntu 启动镜像组（`boot`、`init_boot`、`vendor_boot`）、根文件系统镜像、固件包、切换与恢复工具，以及手动安装步骤。自动安装将在后续版本提供。

近期更新：

- **双系统**：测试机已在 Android 旁安装 Ubuntu。从 Ubuntu 切换到 Android、A 槽启动成功标记均已真机验证。
- **Wi-Fi 5 GHz**：测试机使用内核 7.2.6-piano4 时，NetworkManager 的扫描除 2.4 GHz 外也能找到 5 GHz 网络；连接网络尚未验证。
- **内核 7.2.6-piano3**：Wi-Fi 从已安装系统加载固件、使用本机 MAC 地址并可扫描；加入只读的充电器输入状态与若干启动日志修正。
- **内核 7.2.6-piano2**：显示时钟控制器改为内建，修复了启动后黑屏、GPU 与触控超时的问题。
- **开发者模式**：可选的 USB 线 SSH 维护通道，默认关闭，已真机验证。
- **进行中**：Wi-Fi 连接网络与充电控制。

## 📮 关注与交流

最新进展动态、使用技巧和 AI 讨论会先在公众号和小红书更新；刷机遇到问题也欢迎反馈。

| 公众号：熵减矩阵 | 小红书：yzddmr6 |
|:---:|:---:|
| <img src="docs/assets/gzh-qr.png" width="200" alt="公众号：熵减矩阵"> | <img src="docs/assets/xhs-qr.jpg" width="200" alt="小红书：yzddmr6"> |
| 进展动态 · 使用技巧 · AI 讨论 | 使用分享 · 问题反馈 |

## ⚠️ 安装前请阅读

- **数据清除**：安装会重建 `userdata` 并清除 `metadata`，平板上的 Android 数据全部丢失。
- **解锁 Bootloader**：必须先按小米官方流程解锁；不支持未解锁的设备。
- **原厂版本 OS3.0.303.0.WPYCNXM，运行在 A 槽**：启动镜像沿用该版本的头部字段、回滚索引和 AVB 属性，启动 DTB 也针对该版本的 DTB 与 DTBO 生成。其他版本不支持。
- **先备份**：任何写入前，备份全部分区及每个 UFS LUN 的 GPT（读取分区需要 Android 下的 root 权限）；`userdata` 反正会被清除，可以不备份。切回 Android 需要 A 槽原厂的 `boot`、`init_boot`、`vendor_boot`。
- **Linux 下不能充电**：即使接着 USB，电池也在放电。请在 Android 中充电，切换前保持电量不低于 40 %。
- **恢复方法**：无画面或无响应时，长按电源 + 音量下进入 Fastboot，用 `tools/piano-switch.py` 切回 Android（见[使用与维护](#使用与维护)）。正式镜像没有调试控制台。
- **非官方、实验性**：与小米无关。仅适用于小米平板 8 Pro（`piano`，SM8750P），只在一台测试机上验证：型号 25091RP04C（中国版），16 GB 内存、512 GB UFS。其他版本与容量未验证。

512 GB 布局把原 `userdata` 的范围分为 `userdata`（200 GiB，Android）、`linux_rootfs`（60 GiB，Ubuntu `/`）和 `linux_data`（约 201.27 GiB，`/home`），其他分区和 LUN 不变。
不要刷写 `vbmeta`，不要写入或激活 B 槽：测试机的 B 槽是旧版原厂链，无法启动 Android。Android OTA 更新未验证。
标定数据与蓝牙地址必须来自本机，不可跨设备复制。

## 🚀 获取与安装

1. **使用发布版本**：尚未发布，见[最新版本](#最新版本与近期更新)。计划内容与构建流程见 [docs/RELEASE.md](docs/RELEASE.md)（英文）。
2. **从源码构建**：输入锁定在 [kernel/source.json](kernel/source.json) 与 [kernel/abi.json](kernel/abi.json)（内核提交、配置片段、release）、[mesa/source.json](mesa/source.json)（Mesa 26.2.0 及 A830 补丁）、[ubuntu/](ubuntu/26.04.sources)（官方 26.04 Desktop ARM64 ISO、快照 APT 源）和 `device/*/source.json`。[tools/](tools/) 中的工具无需 root 权限即可构建内核包、Mesa、设备软件包、ext4 根镜像和签名的启动镜像组。触控标定、蓝牙地址、启动配置（boot profile）、原厂 DTB 与 DTBO、AVB 签名密钥取自你自己的平板，从不提交。详见 [docs/build.zh-CN.md](docs/build.zh-CN.md)。
3. **安装**：按 [docs/AGENT-GUIDE.md](docs/AGENT-GUIDE.md) §4 的手动步骤操作。

不要混用不同构建的文件：内核镜像与模块必须来自同一次构建。

## 硬件支持

以下为测试机使用内核 7.2.6-piano4、截至 2026-10-10 的状态；不代表其他版本或配件均已验证。
测试配置、已知问题与路线图见 [docs/STATUS.md](docs/STATUS.md)（英文）。

✅ 可用 · 🟡 部分支持 · ❌ 不支持 · 🧪 未验证

✅ 只用于真机验证过的结果。“测试构建”指诊断启动中取得、尚未进入 7.2.6-piano4 的结果。

### 平台、显示与输入

| 功能 | 器件 / 实现 | 状态 | 范围与限制 |
|---|---|---|---|
| SoC / CPU | 高通骁龙 8 至尊版（SM8750P），ARM64 | ✅ 可用 | 八个核心均可经 SCMI 调频 |
| 启动 | 小米 ABL / AVB，A 槽 | ✅ 可用 | 设备所有者签名的 v4 镜像组；每次启动后标记启动成功；不修改 `vbmeta` |
| 双系统切换 | `piano-boot-switch`，A 槽镜像组 | 🟡 部分支持 | 从 Ubuntu 切换已验证；应用网格按钮与 Android 侧模块未验证 |
| 内置存储 | 铠侠 UFS / ext4 | ✅ 可用 | 60 GiB 根分区与约 201 GiB `/home` |
| 内置显示 | 引导程序帧缓冲 / simpledrm | 🟡 部分支持 | 3200×2136，120 Hz；没有原生驱动，亮度固定，不能关屏或唤醒；触控运行时偶有闪屏 |
| GNOME 桌面 | Ubuntu 26.04 GNOME / Wayland / GDM | ✅ 可用 | GPU 合成，200 % 缩放 |
| GPU | Adreno 830 / msm / Mesa 26.2.0 加补丁（`piano-mesa`） | ✅ 可用 | OpenGL ES；Ubuntu 自带的 Mesa 26.0.3 不支持 A830；Vulkan、持续负载与 GPU 电源管理未验证 |
| 触摸屏 | Novatek NT36532E / SPI / `piano-thp` | 🟡 部分支持 | 单指输入、方向正确；长按无效；锁屏屏幕键盘失效；多指、边缘与电源管理未验证 |
| 手写笔 | Novatek NT36532E 笔扫描 | ❌ 不支持 | 触控启动时关闭笔扫描 |
| 磁吸键盘 | Nanosic WN8030 I2C 桥接 / `hid-nanosic` | 🟡 部分支持 | 按键可用；重新吸附与电源管理未验证；所测键盘没有触摸板 |
| 指纹 | — | ❌ 不支持 | 没有驱动 |

### 无线与 USB

| 功能 | 器件 / 实现 | 状态 | 范围与限制 |
|---|---|---|---|
| Wi-Fi | 高通 WCN7860 / PCIe / ath12k | 🟡 部分支持 | 已验证固件加载、MAC 地址与 2.4/5 GHz 扫描；连接网络尚未验证 |
| 蓝牙 | 高通 WCN7860 / UART / `hci_qca` | 🟡 部分支持 | 固件、上电与设备扫描；配对、音频及与 Wi-Fi 共存未验证 |
| USB 设备模式 | Synopsys DWC3 / USB 2.0 NCM | ✅ 可用 | 开发者模式下经 USB 的 SSH，默认关闭；正式镜像不提供其他 USB 功能 |
| USB 主机 / Type-C 角色 | UCSI | ❌ 不支持 | 未启用 Type-C 角色切换 |
| USB-C 外接显示 | DisplayPort Alt Mode / DIO4485 | ❌ 不支持 | 依赖原生显示驱动；DP 与 DIO4485 节点处于禁用状态 |

### 音视频与传感器

| 功能 | 器件 / 实现 | 状态 | 范围与限制 |
|---|---|---|---|
| 扬声器 | 4 × FS19xx 系列功放 | ❌ 不支持 | 没有主线驱动，没有播放设备 |
| 麦克风 | 内置 DMIC / ADSP / AudioReach | 🧪 未验证 | 声卡与录音 PCM 已注册，但没有后端 DAI 和 UCM 配置；录音未测试 |
| 视频解码 | 高通 Iris（VPU35） | ❌ 不支持 | 已编译为模块，未启用 |
| 摄像头 | 后摄 S5KJN1SQ03、前摄 OV32D40 | ❌ 不支持 | 主线缺少 SM8750 CAMSS 支持 |
| 旋转、光感与霍尔传感器 | ADSP 传感器中枢（SSC） | ❌ 不支持 | 用户态栈已准备，未启用 |

### 电源与时间

| 功能 | 器件 / 实现 | 状态 | 范围与限制 |
|---|---|---|---|
| 电源键 / 音量键 | 高通 PMIC | 🟡 部分支持 | 电源键事件可送达 logind；不能关屏或唤醒；音量键未验证 |
| 电量计 / 温度 | 2 × TI BQ27Z561 / 温区 | ✅ 可用 | 电量、电压和电流；温区可读；温控限频未验证 |
| 充电 | 小米 MCA 充电器（经 ADSP） | 🟡 部分支持 | 可只读 USB 输入状态；不能控制充电；Linux 下即使接 USB 电池也在放电 |
| 挂起 | Linux 电源管理 | ❌ 不支持 | 在挂起与唤醒验证通过前由策略禁用 |
| 休眠到磁盘 | — | ❌ 不支持 | 分区布局中没有 swap 分区 |
| 实时时钟 | PMK8550 RTC | ❌ 不支持 | 不可写；每次启动后时间错误，需手动设置或联网校时 |

## 使用与维护

**切换系统。** 在 Ubuntu 中运行 `sudo piano-boot-switch to-android --reboot`，会把保存的 Android 镜像组写入 A 槽、读回校验后重启（已真机验证）；应用网格中的 **切换到 Android** 调用同一工具，尚未验证。
在 Android 中，可用 [device/android/piano-switch-ksu](device/android/piano-switch-ksu/README.md) 的 KernelSU 模块切到 Ubuntu；该模块尚未真机验证，验证前请使用下面的主机方式。
在任一系统内切换都不会改变槽属性。

**从主机恢复。** 在 Fastboot（电源 + 音量下）中，`tools/piano-switch.py` 先核对设备与两组镜像，再写入 A 槽，任一步写入失败即恢复原镜像组：

```sh
python3 tools/piano-switch.py --serial <serial> --images <android-set> --rollback <ubuntu-set>
fastboot -s <serial> reboot
```

主机写入会重置 A 槽的重试计数，下一次 Ubuntu 启动后由 `piano-slot-success` 重新标记。若 Fastboot 显示 `slot-unbootable:a` 为 `yes`，执行 `fastboot -s <serial> --set-active=a` 即可重置；B 槽仍不可用。详见 [device/boot](device/boot/README.md)。

**更新内核。** `sudo dpkg -i linux-image-<release>_*.deb` 会运行 dracut 和 `piano-boot-update`：它重建 Ubuntu 镜像组，A 槽为 Ubuntu 时原位重写该槽（设备上约 12.5 分钟），重启后生效。A 槽不是 Ubuntu 时，用 `sudo piano-boot-switch to-ubuntu` 写入新镜像组。

**开发者模式。** `sudo piano-devmode on` 开启经 USB 线的 SSH（USB NCM，平板地址 192.168.88.2）；默认关闭，需要安装 `openssh-server`。启动约 22 秒后，可在主机上用 `python3 tools/piano-devmode-ssh.py USER` 连接。详见 [device/devmode](device/devmode/README.md)。

**启动后的时间。** PMIC RTC 不可写，每次启动后时钟都不正确。请手动设置（例如 `sudo date -s '2026-10-09 18:00'`），或在联网后由网络校时自动修正。

## 开发与贡献

| 仓库 | 内容 |
|---|---|
| xiaomipad-8pro-mainline | 设备用户态、Ubuntu 集成、构建/打包/切换工具、固件、文档 |
| [linux-sm8750-piano](https://github.com/yzddmr6/linux-sm8750-piano) | Linux 内核：在上游 v7.2.6 stable 历史之上维护驱动、设备树与配置，分支 `piano/dev` |

[kernel/source.json](kernel/source.json) 锁定内核提交与配置片段；[kernel/abi.json](kernel/abi.json) 为每次打包构建分配唯一 release（当前为 `7.2.6-piano4`）。
本机输入（标定、蓝牙地址、启动配置、签名密钥、备份）归各设备所有者所有，从不提交。
调试镜像组（`tools/build-persistent-boot.py --debug`）另带一个供 `fastboot boot` 使用的检查镜像，经 USB 提供无认证的 root shell，仅用于诊断。

在设备上操作前，请先阅读 [docs/AGENT-GUIDE.md](docs/AGENT-GUIDE.md)，它同时面向人工操作者和 AI 代理。贡献规则见 [CONTRIBUTING.md](CONTRIBUTING.md) 与 [AGENTS.md](AGENTS.md)。尚未向上游提交补丁，候选列表见 [docs/STATUS.md](docs/STATUS.md#upstreaming)。

问题请通过 [GitHub Issues](https://github.com/yzddmr6/xiaomipad-8pro-mainline/issues) 反馈，注明设备型号、原厂版本、内核 release 和镜像组身份；提交前去除序列号、蓝牙地址、标定数据和个人信息。

## 致谢与许可证

本项目复用并改编了以下工作：
- 一加平板 2 Pro（`erhai`）主线集成项目（GPL-2.0-only；无公开地址）；
- 小米平板 6 Pro（`liuqin`）主线项目：[集成仓](https://github.com/yzddmr6/xiaomipad-6pro-mainline)（MIT）与[内核](https://github.com/yzddmr6/linux-sm8450-liuqin)（GPL-2.0）；
- [BigfootACA/linux](https://github.com/BigfootACA/linux/tree/full-v7.1.3)（GPL-2.0）；
- [ROCKNIX](https://github.com/ROCKNIX/distribution/tree/92a6fca6afda5ab7e1874af8985095beee19b6a8) 与 Teguh Sobirin 的 [SM8750 内核补丁](https://github.com/ROCKNIX/distribution/tree/92a6fca6afda5ab7e1874af8985095beee19b6a8/projects/ROCKNIX/devices/SM8750/patches/linux)（GPL-2.0；DTS BSD-3-Clause）；
- 高通（Jie Zhang、Akhil P Oommen、Gaurav Kohli）：[Adreno 830 系列](https://patchew.org/linux/20260809-pakala-gpu-v1-0-207ad1fac1c7%40oss.qualcomm.com/)（GPL-2.0）；
- Junjie Cao：[NT36532 面板驱动](https://patch.msgid.link/20260804074233.85629-1-junjie.cao@linux.dev)（GPL-2.0-only）；
- Alexander Koskovich 与 Jonathan Marek：[DSC 单包多 slice 补丁](https://patch.msgid.link/20260318-dsi-dsc-slice-per-pkt-v2-1-0a1b316f8250@pm.me)（GPL-2.0）；
- 小米 [vendor_xiaomi_proprietary_touch-driver](https://github.com/MiCode/vendor_xiaomi_proprietary_touch-driver/tree/piano-w-oss)（GPL-2.0）；
- ianchb 的 [xiaomi-sheng-thp](https://github.com/ianchb/xiaomi-sheng-thp)（Apache-2.0）；
- map220v 的 [hid-nanosic-wn8030](https://github.com/ianchb/sm8550-mainline/blob/42f3b40c702abbc37c3a04c95af008cd283aeaf3/drivers/hid/hid-nanosic-wn8030.c)（GPL-2.0-only）；
- AOSP [mkbootimg](https://android.googlesource.com/platform/system/tools/mkbootimg)（Apache-2.0）与
  [avbtool](https://android.googlesource.com/platform/external/avb/)（MIT）；
- [Mesa](https://gitlab.freedesktop.org/mesa/mesa)（MIT）；
- linux-msm [hexagonrpc](https://github.com/linux-msm/hexagonrpc)（GPL-3.0、LGPL-3.0）与
  [qrtr](https://github.com/linux-msm/qrtr)（BSD-3-Clause）；
- [libssc](https://codeberg.org/DylanVanAssche/libssc)（GPL-3.0）；
- [iio-sensor-proxy](https://gitlab.freedesktop.org/hadess/iio-sensor-proxy)（GPL-3.0）；
- [AudioReach topology](https://github.com/linux-msm/audioreach-topology)（BSD-3-Clause）；
- [TinyALSA](https://github.com/tinyalsa/tinyalsa)（BSD-3-Clause）；
- [systemd](https://github.com/systemd/systemd)（LGPL-2.1-or-later、GPL-2.0-or-later）；
- BusyBox（GPL-2.0）；
- [Ubuntu](https://ubuntu.com/download/desktop)。

相关项目（已调研，未复用）：
- [Project-SunUEFI](https://github.com/slwyts/Project-SunUEFI)（按文件许可）；
- [blu-sharky/linux-piano](https://github.com/blu-sharky/linux-piano)（GPL-2.0）；
- [blu-sharky/debian-piano](https://github.com/blu-sharky/debian-piano)（MIT）。

各文件的来源、提交与改动记录在 [NOTICE](NOTICE)。除文件 SPDX 头另有声明外，原创集成代码采用
[MIT](LICENSE)；若干改编自 GPL-2.0-only 来源的工具保持 GPL-2.0-only。内核为 GPL-2.0。第三方组件保留各自
许可（见 `LICENSES/`）。[firmware/](firmware/README.md) 中的原厂固件取自 OS3.0.303.0.WPYCNXM，为互操作目的
原样分发。相关厂商未授予再分发许可；这些固件不受上述许可覆盖，权利人要求时将予以移除。你也可以用文档所述
工具换成从自己设备提取的固件。
