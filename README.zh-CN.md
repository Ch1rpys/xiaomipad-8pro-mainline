# Ubuntu for Xiaomi Pad 8 Pro

在小米平板 8 Pro（`piano`，SM8750P）上与 Android 双系统运行 Ubuntu 26.04 LTS GNOME 桌面，内核基于上游 Linux 7.2 适配。[English](README.md)

**最新内核/软件包版本：7.2.6-piano9（ABI 9），2026-10-12 已真机验证。** 见 [piano9 升级与验收记录](docs/PIANO9.md)。

v0.2.0 本地全新安装候选见 [INSTALL](docs/INSTALL.zh-CN.md)；尚未发布或完成整套重装验收。镜像只带传感器默认种子，用户自己的 registry 按上述工具在首次启动前暂存。

## 📮 关注与交流

技术长文、经验分享和进展动态在公众号；交流群在小红书，扫码进群交流。刷机问题也欢迎在这两处反馈。

<div align="center">
<table>
<tr><th>公众号：熵减矩阵</th><th>小红书：yzddmr6</th></tr>
<tr>
<td align="center"><img src="docs/assets/gzh-qr.png" width="300" alt="公众号：熵减矩阵"></td>
<td align="center"><img src="docs/assets/xhs-qr.jpg" width="300" alt="小红书：yzddmr6"></td>
</tr>
<tr><td align="center">技术长文 · 经验分享 · 进展动态</td><td align="center">进群交流 · 问题反馈</td></tr>
</table>
</div>

## ⚠️ 安装前请阅读

- **数据清除**：安装会重建 `userdata` 并清除 `metadata`，平板上的 Android 数据全部丢失。
- **解锁 Bootloader**：必须先按小米官方流程解锁；不支持未解锁的设备。
- **原厂版本 OS3.0.303.0.WPYCNXM，运行在 A 槽**：启动镜像沿用该版本的头部字段、回滚索引和 AVB 属性，启动 DTB 也针对该版本的 DTB 与 DTBO 生成。其他版本不支持。
- **先备份**：任何写入前，备份全部分区及每个 UFS LUN 的 GPT（读取分区需要 Android 下的 root 权限）；`userdata` 反正会被清除，可以不备份。切回 Android 需要 A 槽原厂的 `boot`、`init_boot`、`vendor_boot`。
- **Linux 下净充电未验证**：`xiaomi_mca` 提供只读状态，MiPPS/charging3 控制仍待墙充测试。请在 Android 中充电，切换前保持电量不低于 40 %。
- **没有扬声器保护**：FS19xx 播放已验证，增益上限为 −15 dB；保护问题仍开放（TD-026）。
- **挂起由产品策略禁用**（D3）；RTC 不可设置（TD-022）。
- **恢复方法**：无画面或无响应时，长按电源 + 音量下进入 Fastboot，用 `tools/piano-switch.py` 切回 Android（见[使用与维护](#使用与维护)）。正式镜像没有调试控制台。
- **非官方、实验性**：与小米无关。仅适用于小米平板 8 Pro（`piano`，SM8750P），只在一台测试机上验证：型号 25091RP04C（中国版），16 GB 内存、512 GB UFS。其他版本与容量未验证。

512 GB 布局把原 `userdata` 的范围分为 `userdata`（200 GiB，Android）、`linux_rootfs`（60 GiB，Ubuntu `/`）和 `linux_data`（约 201.27 GiB，`/home`），其他分区和 LUN 不变。
不要刷写 `vbmeta`，不要写入或激活 B 槽：测试机的 B 槽是旧版原厂链，无法启动 Android。Android OTA 更新未验证。
标定数据与蓝牙地址必须来自本机，不可跨设备复制。
传感器的私有 registry 标定须用 [tools/stage-sensor-registry.py](tools/stage-sensor-registry.py)
从自己的备份准备，步骤见[传感器包说明](device/sensors/README.zh-CN.md#原厂配置与私有标定)。

## 🚀 获取与安装

硬件表描述已装机的 piano9 系统。下面的预览下载是较早的安装镜像，其包版本须单独核对；从 piano8 升级到 piano9 请按 [docs/PIANO9.md](docs/PIANO9.md) 操作，并保留 `piano9-rollback`。

1. **使用发布版本**：[v0.1.0-preview](https://github.com/yzddmr6/xiaomipad-8pro-mainline/releases/tag/v0.1.0-preview)。从同一发布版本把 SHA256SUMS.assets 及其中列出的全部附件下载到一个空目录。本版归档只有两片：`piano-v0.1.0-preview.tar.zst.part0` 和 `piano-v0.1.0-preview.tar.zst.part1`。在该目录执行 `sha256sum -c SHA256SUMS.assets`，全部条目通过后再解压分卷。用 `cat piano-v0.1.0-preview.tar.zst.part* | zstd -d | tar -x` 还原（约需 14 GB 空间），在解压目录内执行 `sha256sum -c SHA256SUMS`，然后按 [docs/INSTALL.zh-CN.md](docs/INSTALL.zh-CN.md) 安装。内容与构建流程见 [docs/RELEASE.md](docs/RELEASE.md)（英文）。
2. **从源码构建**：输入锁定在 [kernel/source.json](kernel/source.json) 与 [kernel/abi.json](kernel/abi.json)（内核提交、配置片段、release）、[mesa/source.json](mesa/source.json)（Mesa 26.2.0 及 A830 补丁）、[ubuntu/](ubuntu/26.04.sources)（官方 26.04 Desktop ARM64 ISO、快照 APT 源）和 `device/*/source.json`。[tools/](tools/) 中的工具无需 root 权限即可构建内核包、Mesa、设备软件包、ext4 根镜像和签名的启动镜像组。触控标定、蓝牙地址、启动配置（boot profile）、原厂 DTB 与 DTBO、AVB 签名密钥取自你自己的平板，从不提交。详见 [docs/build.zh-CN.md](docs/build.zh-CN.md)。
3. **安装**：按 [docs/INSTALL.zh-CN.md](docs/INSTALL.zh-CN.md) 的手动步骤操作；切换、Fastboot 恢复及禁止刷写的分区见 [docs/FLASHING.zh-CN.md](docs/FLASHING.zh-CN.md)。

不要混用不同构建的文件：内核镜像与模块必须来自同一次构建。

## 硬件支持

2026-10-12 更新，当前装机版本为 **7.2.6-piano9（ABI 9）**。视频解码使用 piano8 模块在 RAM 检查中验证；触控方向和键盘按键由用户此前确认。其他版本和配件未测试。
测试配置、已知问题与路线图见 [docs/STATUS.md](docs/STATUS.md)（英文）。

✅ 可用 · 🟡 部分支持 · ❌ 不支持 · 🧪 未验证

✅ 表示所述功能已真机验证，不代表所有生命周期或应用均已测试。未变的平台条目保留此前证据。本表是支持状态的权威来源，发布说明须保持相同的限制。

### 平台、显示与输入

| 功能 | 器件 / 实现 | 状态 | 范围与限制 |
|---|---|---|---|
| SoC / CPU | 高通骁龙 8 至尊版（SM8750P），ARM64 | ✅ 可用 | 八个核心均可经 SCMI 调频 |
| 启动 / 内核包 | 小米 ABL / AVB，A 槽 | ✅ 可用 | 从 piano8 安装到 piano9，保留 `piano9-rollback`；[冷启动验收通过](docs/STATUS.md#cold-boot-acceptance) |
| 双系统切换 | `piano-boot-switch`，A 槽镜像组 | ✅ 可用 | 镜像组轮换与 Android KernelSU 模块切换已验证；RAM 检查返回时的干净关机已修复 |
| 内置存储 | 铠侠 UFS / ext4 | ✅ 可用 | 60 GiB 根分区与约 201 GiB `/home` |
| 内置显示 | 原生 DSI KMS / `msm_dpu` | ✅ 可用 | 3200×2136、144 Hz，Mutter 背光调节与 DPMS 关/开屏已硬件验证；simpledrm 仅用于初始点亮 |
| GNOME 桌面 | Ubuntu 26.04 GNOME / Wayland / GDM | ✅ 可用 | piano9 冷启动验收通过，GDM 在 12.7 s 启动 |
| GPU | Adreno 830 / msm / Mesa 26.2 | ✅ 可用 | Mesa deb 与 snap `gpu-2404` provider 集成 .3 已验证；Firefox WebRender 已验证 |
| 触摸屏 | Novatek NT36532E THP / SPI / `piano-thp` | ✅ 可用 | 触控输入已验证，方向由用户此前确认 |
| 手写笔 | Novatek NT36532E 笔扫描 | ❌ 不支持 | 触控启动时关闭笔扫描 |
| 磁吸键盘 | Nanosic WN8030 传输 | ✅ 可用 | 按键由用户此前确认；该键盘没有触摸板 |
| 指纹 | — | ❌ 不支持 | 没有驱动 |

### 无线与 USB

| 功能 | 器件 / 实现 | 状态 | 范围与限制 |
|---|---|---|---|
| Wi-Fi | 高通 WCN7860 / PCIe / ath12k | ✅ 可用 | 装机内核上 2.4 GHz 与 5 GHz 80 MHz HE 稳定连接已验证 |
| 蓝牙 | 高通 WCN7860 / UART / `hci_qca` | 🟡 部分支持 | 扫描发现 4 个设备；配对与音频未验证 |
| USB 设备模式 | Synopsys DWC3 / USB 2.0 NCM | ✅ 可用 | 开发者模式下经 USB 的 SSH，默认关闭；正式镜像不提供其他 USB 功能 |
| USB 主机 / Type-C 角色 | UCSI | ❌ 不支持 | 未启用 Type-C 角色切换 |
| USB-C 外接显示 | DisplayPort Alt Mode / DIO4485 | ❌ 不支持 | 控制链仅离线检查，外接显示尚不支持 |

### 音视频与传感器

| 功能 | 器件 / 实现 | 状态 | 范围与限制 |
|---|---|---|---|
| 扬声器 | FS19xx 系列功放 | 🟡 部分支持 | 播放已验证，无扬声器保护，增益上限 −15 dB（TD-026） |
| 内置麦克风 | DMIC / ADSP / AudioReach / PipeWire | ✅ 可用 | PipeWire 录音已验证：1 kHz 单音高于本底 29–36 dB |
| 视频解码 | 高通 Iris / V4L2 | 🟡 部分支持 | piano8 模块 RAM 检查的 1080p H.264 与软件解码逐位一致；piano9 有 `/dev/video0/1`；应用播放未验 |
| 视频编码 | 高通 Iris / V4L2 | 🧪 未验证 | 编码节点存在；编码未测试 |
| 摄像头 | 后摄 S5KJN1SQ03、前摄 OV32D40 | ❌ 不支持 | 已采原厂只读证据；缺少 SM8750 CAMSS 支持 |
| 加速度、陀螺、光感、距离 | SSC / hexagonrpcd / libssc | ✅ 可用 | `piano-sensors` 与 `piano-iio-sensor-proxy` 的样本已验证，SensorProxy 可报告方向 |
| GNOME 自动旋转 | SensorProxy / Mutter 平板模式 | 🧪 未验证 | 按 Mutter 规则仅拆下键盘后启用；实体四方向测试待做 |

### 电源与时间

| 功能 | 器件 / 实现 | 状态 | 范围与限制 |
|---|---|---|---|
| 电源键 / 音量键 | 高通 PMIC | 🟡 部分支持 | 电源键事件可送达 logind；音量键未验证 |
| 电量计 / 温度 | 2 × TI BQ27Z561 / 温区 | ✅ 可用 | 电量、电压和电流；温区可读；温控限频未验证 |
| 充电 | 只读 `xiaomi_mca` / MiPPS | 🟡 部分支持 | MiPPS/charging3 控制待墙充测试；净充电未验证 |
| 挂起 | Linux 电源管理 | ❌ 不支持 | 由产品策略禁用（D3） |
| 休眠到磁盘 | — | ❌ 不支持 | 分区布局中没有 swap 分区 |
| 实时时钟 | PMK8550 RTC | ❌ 不支持 | RTC 不可设置（TD-022） |

## 使用与维护

详见 [docs/FLASHING.zh-CN.md](docs/FLASHING.zh-CN.md)（切换、槽属性、恢复）。
主机命令按 [INSTALL.zh-CN.md](docs/INSTALL.zh-CN.md#准备) 设置 REPO、RELEASE 和 WORK，并在 WORK 中执行。
源码工具使用 `"$REPO/tools/NAME"`，发布文件使用 `"$RELEASE/PATH"`。

**切换系统。** 在 Ubuntu 中运行 `sudo piano-boot-switch to-android --reboot`，会把保存的 Android 镜像组写入 A 槽、读回校验后重启。在 Android 中，可用 [KernelSU 切换模块](device/android/piano-switch-ksu/README.md) 切到 Ubuntu。A 槽镜像组轮换与 Android 模块均已真机验证；RAM 检查返回时的干净关机已修复。
在任一系统内切换都不会改变槽属性。

**从主机恢复。** 在 Fastboot（电源 + 音量下）中，`tools/piano-switch.py` 先核对设备与两组镜像，再写入 A 槽，任一步写入失败即恢复原镜像组：

```sh
python3 "$REPO/tools/piano-switch.py" --serial <serial> --images <android-set> --rollback <ubuntu-set>
fastboot -s <serial> reboot
```

主机写入会重置 A 槽的重试计数，下一次 Ubuntu 启动后由 `piano-slot-success` 重新标记。若 Fastboot 显示 `slot-unbootable:a` 为 `yes`，执行 `fastboot -s <serial> --set-active=a` 即可重置；B 槽仍不可用。详见 [device/boot](device/boot/README.md)。

**更新到 piano9。** 按 [docs/PIANO9.md](docs/PIANO9.md#b-install-on-the-ordinary-piano8-root) 保留独立的 `piano9-rollback` 镜像组，并成套安装内核与配套软件包。GStreamer good/bad 已是桌面包依赖；安装插件不等于应用级硬件播放通过。

**开发者模式。** `sudo piano-devmode on` 开启经 USB 线的 SSH（USB NCM）；默认关闭，需要安装 `openssh-server`。在主机上用 `python3 "$REPO/tools/piano-devmode-ssh.py" --serial <SERIAL> USER` 连接。安装过程会打开它，装完后用 `sudo piano-devmode off` 关闭（[INSTALL](docs/INSTALL.zh-CN.md) 第 10 步）。详见 [device/devmode](device/devmode/README.md)。

**启动后的时间。** PMIC RTC 不可设置（TD-022），启动后请检查系统时间；piano9 冷启动通过不代表 RTC 获得支持。

**传感器与旋转。** 安装 `piano-sensors` 和 `piano-iio-sensor-proxy`，并按[传感器说明](device/sensors/README.zh-CN.md)从自己的备份准备 registry 标定。SensorProxy 可报告方向，但 Mutter 只在拆下键盘时启用自动旋转；实体四方向测试仍待完成。

**初始设置之后。** 初始设置会把用户名设为主机名，除非你修改其中的“计算机”栏；之后可用 `sudo hostnamectl hostname --static <名字>` 修改。第一次 `apt install` 之前先运行 `sudo apt update`：镜像不带当前的软件包索引。

## 开发与贡献

| 仓库 | 内容 |
|---|---|
| xiaomipad-8pro-mainline | 设备用户态、Ubuntu 集成、构建/打包/切换工具、固件、文档 |
| [linux-sm8750-piano](https://github.com/yzddmr6/linux-sm8750-piano) | Linux 内核：在上游 v7.2.6 stable 历史之上维护驱动、设备树与配置，分支 `piano/dev` |

[kernel/source.json](kernel/source.json) 锁定内核提交与配置片段；[kernel/abi.json](kernel/abi.json) 为每次打包构建分配唯一 release（当前为 `7.2.6-piano9`，ABI 9）。
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
