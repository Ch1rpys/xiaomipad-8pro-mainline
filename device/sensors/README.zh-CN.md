# piano 传感器产品集成

适用于 Ubuntu 26.04 ARM64、带 secure ADSP FastRPC/QRTR 的项目内核。独立 SSC 检查在
全新启动上获得加速度/陀螺各 132 个样本、光感 2 个、距离 1 个；静止加速度模长中位数为
9.86 m/s²，pristine registry 未变。产品集成的设备检查确认两个服务可启动，
`HasAccelerometer=true`，但底座横屏方向错误为 `right-up`、`PanelOrientationManaged=false`，
且未发现光感。当前版本修正了显示坐标矩阵，该修正仅通过主机验证；
**四向旋转、脱离底座后的门控和自动亮度仍需真机验证**。

## 包和边界

- `piano-sensors`：上游 hexagonrpc 0.5.0 固定提交及六个锁定补丁，包含原样导入的
  `f0dfd5095d3b7defc3b368f227337bfc6d6aef42` large-in-bufs 提交；独立的 systemd/udev 集成。
- `piano-iio-sensor-proxy`：固定 iio-sensor-proxy 3.9、libssc 0.4.4，保留
  `libssc/sensorproxy.json` 全部五个补丁（现有文件编号为 0003、0004、0005、0006、0001，未重编号，
  0004 保留）。标准 `net.hadess.SensorProxy`、`iio-sensor-proxy.service` 和 `monitor-sensor` 不改名。
  使用 `Provides: iio-sensor-proxy (= 3.9)`、`Conflicts/Replaces: iio-sensor-proxy` 接管同一服务，
  让 GNOME orientation/自动亮度消费者无需修改，也避免两个代理同时运行。
  包替换语义见 [Debian Policy §7](https://www.debian.org/doc/debian-policy/ch-relationships.html#replacing-whole-packages-forcing-their-removal)。

协议代码仍由 upstream Meson 构建；不调用 APT/GDM、不假定桌面用户名。包/服务位于 `packaging/`；
私有库只装入 `/usr/lib/aarch64-linux-gnu/piano-sensors/` 和 `piano-iio-sensor-proxy/`，其余运行库使用发行版包。
当发行版具备 SSC 与等价冷插拔/通知/释放/轮询修复并通过同样回归后，撤销代理替换，回归发行版维护。
来源、许可证、补丁 hash 和退出条件见相邻 `hexagonrpc/source.json`、`libssc/*.json` 和 `NOTICE`。

## 原厂配置与私有标定

`firmware/sensors/` 的 66 个文件来自 OS3.0.303.0.WPYCNXM ROM 的 ODM/vendor 配置树。
已检查它们为静态配置而非 persist 数据；没有序列号/MAC，配置中的 fac_cal 是 ROM 默认值。
经设备所有者授权，沿用 `firmware/` 政策公开：**没有已确立的再分发许可，应权利方要求移除**，
它们不因集成仓 MIT 而被重新授权。逐文件来源/hash 在 `firmware/sensors/source.json`。
不额外装 Android Java HAL 库；诊断中缺失的 oemconfig.so/部分 json 仍可能有非致命日志，不伪造文件。

persist registry 即使不含序列号/MAC，也含每台设备唯一的传感器 `fac_cal`，**不能入公开仓、通用包，
也不能借用其他平板的副本**。可选工具 `tools/stage-sensor-registry.py` 只消费用户自己的已提取备份，
不读设备、不挂载分区。输入必须是外层 `sensors/registry/`，其下还有内层 `registry/` 及版本/解析列表。

包把不可变 ODM/vendor 配置和空的默认 registry 种子装入 `/usr/share/piano/sensors/`；私有种子放
`/usr/share/piano/sensors/registry-private/`。首次启动复制私有种子（有则使用）或空默认种子至
`/var/lib/piano/sensors/registry/`，让 DSP 按 stock JSON 生成默认标定。后者日志明确打印
`SSC_REGISTRY=stock-default-calibration`；不因缺私有数据拒绝传感器，但默认标定的可用性/精度尚未真机验收。
DSP 写入仅映射到该可写状态，`ProtectSystem=strict` 保持 pristine 配置/种子只读。
升级或普通重启不会覆盖现有状态，也不会重新复制私有种子。唯一例外：本次启动的内核日志中
`crash detected in adsp` 共 ≥3 次，且至少一次传感器看门狗导致的 fatal error（`fatal error received:`
且含 `qsh_process` 或 `sns_watchdog`；此后 ADSP 可能只以 watchdog 崩溃）时，`sensors-prepare`
在 ADSP 恢复后的下一次运行把状态整体移到
`/var/lib/piano/sensors/registry.quarantine-<UTC 时间>`，再按上述规则重新播种（有私有种子则用私有种子），
并打印一行日志。每次启动最多一次；隔离副本保留最新 3 份。

## 安装（由用户在平板执行）

先把交付目录复制到平板，再在该目录执行。以下命令不会刷内核或切槽。

```sh
cd debs
sha256sum -c SHA256SUMS
# 保存当前 Ubuntu 代理的准确版本和包，供离线回滚。
mkdir -p ../rollback
dpkg-query -W -f='${Version}\n' iio-sensor-proxy > ../rollback/iio-sensor-proxy.version
(cd ../rollback && apt-get download "iio-sensor-proxy=$(cat iio-sensor-proxy.version)")
sudo apt install ./piano-sensors_0.1+20261012.2_arm64.deb
sudo apt install ./piano-iio-sensor-proxy_3.9+piano20261012.2_arm64.deb
cd ..
```

APT 应只替换 Ubuntu 的 iio-sensor-proxy；不要接受移除 GNOME 桌面的解算结果。
若原系统没有 iio-sensor-proxy，则跳过保存版本/下载步骤，回滚时仅移除两个 piano 包。
包配置仅启用下次启动，不现场启动/重启 DSP；已有诊断 daemon 必须结束，并正常重启。

可选：在主机从**这台设备**的备份准备私有载荷（该目录不得分享）：

```sh
python3 tools/stage-sensor-registry.py \
  --registry /path/to/own/extracted/persist/sensors/registry \
  --output /path/to/private-sensor-payload
```

把 `private-sensor-payload` 安全复制到平板，在首次启动包服务前执行：

```sh
sudo test ! -e /usr/share/piano/sensors/registry-private
sudo cp -a private-sensor-payload/usr/share/piano/sensors/registry-private /usr/share/piano/sensors/
sudo chown -R root:root /usr/share/piano/sensors/registry-private
sudo reboot
```

不使用私有标定也须 `sudo reboot` 后再测。若已经生成状态，先停止两个服务，将旧状态目录移到自己选定的
备份位置，再装私有种子并正常重启；不要删除原备份、不要把含校准的目录发到公开 issue。

## 升级与检查脚本

矩阵的唯一权威位置是 `packaging/piano-sensors/usr/lib/udev/rules.d/81-piano-sensors.rules`，
所以要升级 **两个包**：`piano-sensors` 更新规则，`piano-iio-sensor-proxy` 更新检查脚本及精确依赖。
代理/SSC/hexagonrpc 的 ELF 和原厂配置字节不变；不修改触控、Mutter 或键盘开关。
在平板交付目录执行：

```sh
(cd debs && sha256sum -c SHA256SUMS)
sudo apt install ./debs/piano-sensors_0.1+20261012.2_arm64.deb \
  ./debs/piano-iio-sensor-proxy_3.9+piano20261012.2_arm64.deb
sudo apt install libinput-tools
sudo reboot
```

升级保留 `/var/lib/piano/sensors/registry` 与私有种子；不用重置、重新导入标定或反复重启 DSP daemon。
正常重启后，在**已登录的 GNOME 用户终端**运行下面这一份脚本（不要 `sudo ./check.sh`）：

```sh
./check.sh --orientations 2>&1 | tee orientation-check-02.txt
# 包内同一脚本名为 piano-sensors-check；--help 显示用法。
```

同一用户的 SSH 终端也可运行，脚本按当前 UID 选择用户 bus 并核对 seat0 的活动 Wayland 会话。
它只为输入设备信息/开关 ioctl/libinput/system journal 请求 sudo，以取得所需读取权限；
不抓取按键、不设置开关、不改 gsettings、不重启服务。日志留在本地，不直接公开。
`libinput list-devices` 是独立上下文的能力检查，并非读取 Mutter 私有 seat；最终以 Mutter 属性及实屏为准。
缺少 `libinput-tools` 会标为未采集并返回非零，不伪报通过。

交互顺序如下。边的名字固定为**最初横屏的物理边**，平板保持近似竖直，避免平放/倾角阈值影响方向。
各姿态就绪后按 Enter，脚本取得开关、5 秒 monitor、D-Bus 属性和当前显示配置，再记录目视/四角触控反馈。

| 姿态 | SW_TABLET_MODE | PanelOrientationManaged | SensorProxy / Mutter logical transform |
|---|---:|---|---|
| 底座横屏、向上倾斜 | 0 | false（正常策略） | normal / 0，tilted-up |
| 拆下键盘，原 top 边朝上 | 1 | true | normal / 0 |
| 原 left 边朝上 | 1 | true | left-up / 1（90°） |
| 原 bottom 边朝上 | 1 | true | bottom-up / 2（180°） |
| 原 right 边朝上 | 1 | true | right-up / 3（270°） |
| 回横屏并重新装底座 | 0 | false | normal / 0 |

测试前通过 GNOME 关闭旋转锁，脚本只读回它。每个方向桌面文字应正立、四角触控应与画面一致；
传感器标签变化不等于实际绘制/触控通过。`3200x2136@144` 是物理 mode，旋转时它可以保持不变；
看 GetCurrentState 的 **logical transform/宽高** 与实屏，不能只看物理 mode。
若拆下键盘后仍 switch=0，先定位键盘 attach 消息/驱动；若 switch=1 但 managed=false，检查触控的
`ID_INPUT_TOUCHSCREEN=1`、libinput `Capabilities: touch`、seat0 和 GNOME 日志，再核实际 Mutter 版本。
若 managed=true 但不转，查锁、claim 错误及显示配置应用错误。脚本返回 0 只表示采集命令成功。

## Mutter 49 的准确旋转条件

当前记录没有 `dpkg -l mutter` 的精确版本；按本任务允许的 49.x 回退，核对上游 **49.0**
（`7697a7993e92dcef3b39b67051691a8b28f0b5ce`），不是宣称已经核过设备上 Ubuntu 的全部补丁。
检查脚本输出 `mutter*`/`libmutter*`/GNOME Shell 版本，若有发行版差异再按实际源包复核。

`meta_monitor_manager_get_panel_orientation_managed()` 仅返回缓存布尔值；本版本的计算函数名为
`update_panel_orientation_managed()`，没有名为 `is_panel_orientation_managed()` 的另一个条件集。

| 层次 | 条件和边界 |
|---|---|
| 属性的全部直接条件 | `touch-mode && has-accelerometer && builtin-monitor`。来自 `meta-monitor-manager.c` 的 `update_panel_orientation_managed()`；不以当前 orientation 是否 normal、旋转锁或已 claim 为直接条件。 |
| touch-mode | 必须有触摸屏；有 tablet switch 时，OFF 为 false、ON 为 true；没有 switch 才退回“没有 pointer/touchpad”判据。普通 keyboard 本身不是否决项。见 `native/meta-seat-impl.c` 的 `update_touch_mode()`。 |
| 输入识别 | `determine_device_type()` 用 libinput capability 分类，touch 为 `CLUTTER_TOUCHSCREEN_DEVICE`；tap/touchpad、tablet-tool/pad、pointer 分类先于 touch。只认当前 seat 成功加入的设备，不因服务名/uinput 名称认定有触屏。 |
| HasAccelerometer | `MetaOrientationManager` 从系统 SensorProxy 代理缓存取此属性；代理出现/消失、PropertiesChanged 会更新并通知 monitor manager。系统 `b true` 证明服务端状态，Mutter 的代理仍需成功连接/收到更新。 |
| 锁与 claim | `orientation-lock=true` 增加 tracking inhibit；`iio_proxy != NULL && inhibited_count == 0` 才异步 ClaimAccelerometer，否则 Release。claim 成功后显式 Get 最新 orientation 并发出 sensor-active；更新要求 has_accel/should_claim/is_claimed。claim 失败影响旋转，并不直接使 managed=false。 |
| 初始方向特例 | 启动首次方向事件可忽略 dock 开关，但仍需触屏、加速度计、builtin，并要求 preferred mode 为竖屏（width <= height）。piano 的 3200x2136 不符合。随后受 managed 门控。 |
| 实际应用旋转 | builtin 必须 active、当前配置存在、builtin 在单独 logical monitor 中（非镜像克隆）、模式有效、目标 transform 有变化，最后配置应用成功。用户保存过 monitors.xml 本身不是关闭 managed 的条件。 |
| lid/会话 | lid 不在 managed 的布尔表达式里，但合盖可导致内屏 inactive，挡住应用旋转；`LidIsPresent=false` 不是禁转理由。Wayland/seat0 活动会话用于确认查的是正确 compositor，不是这个属性的第四个布尔条件。 |

源码：[monitor manager](https://github.com/GNOME/mutter/blob/49.0/src/backends/meta-monitor-manager.c)、
[seat](https://github.com/GNOME/mutter/blob/49.0/src/backends/native/meta-seat-impl.c)、
[input device](https://github.com/GNOME/mutter/blob/49.0/src/backends/native/meta-input-device-native.c)、
[orientation manager](https://github.com/GNOME/mutter/blob/49.0/src/backends/meta-orientation-manager.c)、
[monitor config](https://github.com/GNOME/mutter/blob/49.0/src/backends/meta-monitor-config-manager.c)。

piano 已知 builtin=true、SensorProxy HasAccelerometer=true，底座姿态最符合 **touch-mode 被 tablet switch OFF 禁止**。
内核 `hid-nanosic-wn8030.c` 为 `Xiaomi Keyboard Tablet Mode` 报告
`SW_TABLET_MODE = !(attach & BIT(0))`（初次注册也取当前 attach）；已连键盘为 0，拆下为 1。
原始证据读取开关时 PermissionError，因而**尚无实际 0/1 读回**，不能冒充唯一根因已真机确认。
不屏蔽开关、不强制 GNOME 在底座模式旋转。

触控实际 uinput 名为 `Piano THP Touchscreen`，实现 `device/piano-thp/src/input.cpp` 已声明
`ABS_MT_POSITION_X/Y`、`BTN_TOUCH`、`BTN_TOOL_FINGER` 与 `INPUT_PROP_DIRECT`。
Ubuntu 已保存的 systemd 259.5 `udev-builtin-input_id.c` 按 MT 坐标和 direct/touch 识别为 touchscreen，
不会因 BTN_TOOL_FINGER 把 direct 设备归成 touchpad；规则无需额外 hwdb 标签。
[libinput 要求正确 udev 类型且能力有效](https://wayland.freedesktop.org/libinput/doc/latest/device-configuration-via-udev.html#device-type-assignment-via-udev)。
现有证据没有其实际 udev/libinput 输出，所以保留脚本验证；不加入无证据的强制分类规则。
若未来证实确有缺项，THP 服务及输入规则的所有者是 `piano-device-support`，不是传感器代理。

## 显示坐标矩阵与验证边界

SensorProxy 按行计算 `a_display = M * a_SSC`。以给定底座样本 `(7.1,-0.1,4.9)` 为例：
旧 `diag(-1,-1,+1)` 得 `(-7.1,0.1,4.9)`，因此为 right-up；应当使主分量成为显示的负 Y。
当前版本使用绕 Z 的正交旋转（det=+1，保留 Z）：

```text
ACCEL_MOUNT_MATRIX="0, 1, 0; -1, 0, 0; 0, 0, 1"
X =  y
Y = -x
Z =  z
(7.1,-0.1,4.9) -> (-0.1,-7.1,4.9) -> normal / tilted-up
```

这里只修正 **SSC 已输出的坐标→Linux 原生横屏**，不更改 Android JSON，不重复叠加 Android
`diag(-1,-1,+1)`。原厂 Android 的显示坐标约定不能直接用作 Linux 的最终矩阵。
输入的约数本身模长约 8.63；独立 SSC 检查全序列的 9.86 是另一个统计值，不把两者当作同一精确样本。

单个几乎 y=0 的姿态约束 `Y=-x`，不足以实测确认 `X=+y` 还是 `X=-y`；两者在此姿态均可 normal，
却会交换 left-up/right-up。保留 `Z=+z` 且要求右手纯旋转时，`X=+y` 是 det=+1 的选择；
另一种在固定 Z 下是反射（det=-1），不是等价的平面旋转。DSP 输出坐标/面向约定仍要靠物理测试核实，
不能只凭一次姿态断言左右已经正确。若 top/bottom 正确而 left/right 互换，保存四向结果后再修正符号。
触控历史的 90° 修正不是本矩阵证据；若仅触点偏转，独立定位触控坐标，不盲改传感器补偿。

`HasAmbientLight=false` 是当前包尚未解决的传感器发现问题；坐标矩阵修正不解决该问题。服务 active 或早期 SSC
取得一份 light 样本并不保证 SensorProxy light discovery 成功。可另保留
`monitor-sensor --light` 与 journal，供光感问题定位；旋转行为需独立验证。

服务由 secure FastRPC udev 事件或正常启动触发；准备程序核对 piano DT、ADSP running、最多等待
QRTR 400 五秒。失败时保留 journal 后正常重启，不用自动重试或反复重启 hexagonrpcd。

## 精确卸载/回滚

先保存自己的私有种子及状态。若有保存的 Ubuntu 包，在交付目录执行：

```sh
sudo systemctl stop iio-sensor-proxy.service piano-hexagonrpcd-sns.service
# 同一 APT 事务以原版本恢复标准代理，并移除替换包。
sudo apt install ./rollback/iio-sensor-proxy_*_arm64.deb piano-iio-sensor-proxy- piano-sensors-
sudo apt purge piano-iio-sensor-proxy piano-sensors
sudo reboot
```

若安装前没有代理：`sudo apt purge piano-iio-sensor-proxy piano-sensors` 后正常重启。
没有原包缓存但联网时，可用 `sudo apt install iio-sensor-proxy piano-iio-sensor-proxy- piano-sensors-` 恢复
仓库版本（不一定与安装前相同）。本包未改内核、固件包、GNOME 用户配置或触控程序，不需要回刷。
remove/purge 保留私有标定和学习状态；确认有自己的备份后，若要彻底删除其剩余数据：

```sh
sudo rm -rf /var/lib/piano/sensors /usr/share/piano/sensors/registry-private
```

## 主机构建和离线验证

```sh
python3 tools/build-sensors-debs.py \
  --hexagonrpc-source /path/to/hexagonrpc-git --libssc-source /path/to/libssc-git \
  --sensorproxy-source /path/to/iio-sensor-proxy-git \
  --cross-file /path/to/arm64-cross.ini --sysroot /path/to/ubuntu-arm64-sysroot \
  --output /path/to/piano-sensors-output
```

需要 Meson >=1.4、Ninja、ARM64 GCC/binutils、pkg-config、patchelf、dpkg-deb、qemu-user，
ARM64 GLib/QMI/protobuf-c/GUdev/polkit 开发库及主机 protoc/protoc-gen-c/GLib 生成工具；
SensorProxy Python 模拟测试在 ARM64 guest 中运行，需 gi/dbusmock/psutil/UMockdev。完整 source commit/patch/config hash、工具版本和
包文件清单在输出 `manifest.json`；构建日志在 `build/`。不自动安装到主机、不访问设备。
离线验证结果见交付目录 `verification.json`；模拟传感器与 QEMU 结果不等于 GNOME 真机验收。
